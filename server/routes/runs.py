"""Run lifecycle routes (M1 → T2.7).

POST /api/runs                 submit a run; returns {run_id} (202 when queued)
GET  /api/runs/{id}/events    SSE: replay trajectory from `after=` then live tail
POST /api/runs/{id}/control   {action:"stop"}  → cooperative stop
GET  /api/runs/{id}/trace     one-shot replay of the trajectory timeline

Auth (T2.7): every route now declares ``get_current_user`` so the run is always
bound to the authenticated caller. The run_id stays a server-generated UUID (the
path is still unguessable), but ownership is now enforced at the DB layer too
(store.get_run filters by user_id). The api_key is NEVER accepted from the
client — credentials are resolved server-side from the user's default LLM config.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# NOTE: import UploadFile from Starlette, not FastAPI. Starlette's multipart
# parser instantiates *its own* UploadFile, which is the BASE class of
# fastapi.UploadFile — so ``isinstance(part, fastapi.UploadFile)`` is always
# False and would silently drop every uploaded file. The base class matches both.
from starlette.datastructures import UploadFile

from server.artifacts import scan_outputs
from server.config import build_run_paths, canonical_run_id, get_config, run_dir_for
from server.deps import get_current_user
from server.diff import revert_paths
from server.orchestrator import Orchestrator, _session_uuid, get_orchestrator
from server.relay import sse_for_run, trajectory_records_for_egress
from server.trajectory_status import inspect_trajectory
from server.store import (
    ACTIVE_RUN_STATUSES,
    build_llm_snapshot,
    create_run,
    ensure_session,
    get_default_llm_config,
    get_run,
    get_session,
    session_exists,
    sync_run_artifacts,
)
from server.store import Run as RunModel
from server.store import User as UserModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/runs", tags=["runs"])


class RunRequest(BaseModel):
    """Run submission payload (T2.5 security contract, T2.10 multipart).

    The api_key / model / base_url are intentionally NOT fields: credentials are
    resolved server-side from the user's default LLM config (T2.5) and injected
    into the worker env, never accepted from the client. Pydantic's default
    ``extra="ignore"`` means a client that smuggles ``api_key`` into the payload
    is silently dropped rather than honoured.
    """

    message: str
    session_id: str = "default"
    # Accepted for backwards compatibility only; ignored when auth is on (T2.7) —
    # identity is always the authenticated user.
    user_id: str | None = None


async def _parse_submit(request: Request) -> tuple[str, str, list[UploadFile]]:
    """Accept either JSON or multipart for run submission (T2.10).

    JSON keeps the M1/M2 ``{"message": ...}`` contract intact (so existing clients
    and tests need no change); multipart adds optional file uploads written into
    the run's inputs dir. We branch on the content type and parse accordingly.

    Both branches go through ``RunRequest`` so the "no credentials from the
    client" contract is enforced identically for either encoding.
    """
    ctype = request.headers.get("content-type", "")
    if "multipart/form-data" in ctype:
        form = await request.form()
        # NOTE: Starlette's ``FormData.getlist`` only returns scalar (non-file)
        # values, so it drops ``UploadFile`` parts. Iterate ``multi_items`` instead,
        # which yields every part including file uploads.
        files = [v for _, v in form.multi_items() if isinstance(v, UploadFile)]
        req = RunRequest(
            message=str(form.get("message", "")),
            session_id=str(form.get("session_id", "default")),
        )
        return req.message, req.session_id, files
    # Fall back to the legacy JSON body.
    body = await request.json()
    # A missing/None session_id is valid (the orchestrator synthesises a stable
    # UUID from it); normalise before validation so a null payload doesn't 500.
    if isinstance(body, dict) and body.get("session_id") is None:
        body["session_id"] = "default"
    req = RunRequest.model_validate(body)
    return req.message, req.session_id, []


@router.post("", status_code=202)
async def submit_run(
    request: Request,
    user: UserModel = Depends(get_current_user),
) -> dict[str, Any]:
    orch = get_orchestrator()

    message, session_id, files = await _parse_submit(request)
    if not message:
        raise HTTPException(status_code=422, detail="message is required")

    # Identity is ALWAYS the authenticated user (T2.7). The client-supplied
    # user_id, if any, is ignored — credentials are resolved from this user's own
    # default LLM config and injected into the worker env, never from the request.
    user_id = user.id
    run_id = uuid.uuid4()
    run_id_hex = run_id.hex

    cfg = get_config()

    # F08 — session admission BEFORE any side effect. A session belongs to
    # exactly one user, and a foreign (or soft-deleted) one must read as absent:
    # answer 404 and, crucially, write NOTHING — no uploaded inputs, no run row,
    # no session message. Validating after the uploads (as this used to) let user
    # B append to user A's conversation and still get a 202.
    session_uuid = _session_uuid(session_id, user_id)
    # "Not mine" and "does not exist" are the same answer to the caller; only the
    # server needs to tell them apart, to decide whether to create the session
    # lazily below. Short-circuits, so the existence probe only runs when the
    # caller is not already the owner.
    if (
        await get_session(session_id=session_uuid, user_id=user_id) is None
        and await session_exists(session_uuid)
    ):
        raise HTTPException(status_code=404, detail="会话不存在")

    # T2.10: write uploaded files into the run's inputs dir (read-only to the
    # agent). Bounds are enforced here so a single request can't exhaust disk:
    # per-file byte cap and a per-request file-count cap. Both paths write to the
    # same private per-run tree, never anywhere user-supplied paths could escape.
    uploaded_names: list[str] = []
    if files:
        if len(files) > cfg.max_upload_files:
            raise HTTPException(
                status_code=413,
                detail=f"too many files: {len(files)} > {cfg.max_upload_files}",
            )
        paths = build_run_paths(run_id_hex)
        inputs_dir = paths["inputs"]
        # F12: the batch is all-or-nothing. A cap breach (or an I/O failure) on
        # the LAST file used to leave the earlier ones on disk, orphaned — the
        # run row is never created, so nothing would ever reference them and no
        # cleanup path would ever find them. Any failure after the first write
        # removes the whole per-run tree: this request created it, and no run row
        # points at it yet.
        try:
            for part in files:
                # Reject empty / unnamed parts and any path-like filename — we flatten
                # every upload to a single basename inside inputs_dir.
                raw_name = (part.filename or "").strip()
                if not raw_name:
                    continue
                safe_name = _flatten_filename(raw_name)
                if not safe_name:
                    continue
                data = await part.read()
                if len(data) > cfg.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"file {safe_name} too large: {len(data)} > {cfg.max_upload_bytes} bytes"
                        ),
                    )
                dest = inputs_dir / safe_name
                dest.write_bytes(data)
                uploaded_names.append(safe_name)
        except BaseException:
            shutil.rmtree(paths["root"], ignore_errors=True)
            raise

    # Surface the uploaded input files to the agent via the system-prompt addendum
    # (worker.py forwards this into metadata["_sys_prompt_addendum"], which the
    # react node appends to the system prompt — see main_agent.py:817). In container
    # / serve mode the inputs dir is bind-mounted at /inputs; in native mode the
    # physical path is FRONTIER_AGENT_INPUTS_DIR, so we hand the agent both the
    # /inputs convention name and the real path it can read_file directly.
    prompt_addendum = ""
    if uploaded_names:
        file_list = "\n".join(f"  - /inputs/{n}" for n in uploaded_names)
        inputs_path = str(build_run_paths(run_id_hex)["inputs"])
        prompt_addendum = (
            f"The user attached {len(uploaded_names)} input file(s) for this task. "
            f"Read them from these read-only paths:\n{file_list}\n"
            f"(native: read directly from {inputs_path})"
        )

    # The session was admitted (or is about to be created) above; make sure the
    # row exists so the turns table and the Run FK stay consistent.
    await ensure_session(session_id=session_uuid, user_id=user_id, title=message[:80] or "新对话")

    # F20: record WHICH model drove this run — never the secret. The column has
    # existed since T2.5 but nothing ever filled it, so a finished run could not
    # say which model produced it and the UI read ``model: null``.
    default_llm = await get_default_llm_config(user_id=user_id)
    snapshot = await build_llm_snapshot(user_id=user_id)

    # Persist the Run row up-front (status="queued"); the orchestrator flips it to
    # "running" when the worker reports run_started and to its terminal state when
    # the worker emits run_finished.
    await create_run(
        run_id=run_id,
        session_id=session_uuid,
        user_id=user_id,
        prompt=message,
        pipeline_id=cfg.pipeline_id,
        run_dir=str(run_dir_for(run_id_hex)),
        status="queued",
        llm_config_id=default_llm.id if default_llm is not None else None,
        llm_snapshot_json=snapshot,
    )

    await orch.submit(
        run_id=run_id_hex,
        session_id=session_id,
        prompt=message,
        user_id=user_id,
        prompt_addendum=prompt_addendum,
    )
    return {"run_id": run_id_hex, "status": "queued"}


def _flatten_filename(name: str) -> str:
    """Reduce an uploaded filename to a safe single-path basename.

    Directory separators, drive letters and parent-dir markers are stripped so the
    file can only ever land inside the run's inputs dir — never a sibling path the
    client hinted at.
    """
    for sep in ("/", "\\"):
        name = name.replace(sep, "_")
    name = name.replace("..", "_").replace(":", "_")
    return name.strip() or ""


def _live_queue_for(
    orch: Orchestrator, run_id: str, run: RunModel
) -> asyncio.Queue[dict[str, Any] | None] | None:
    """Join the run's live fan-out, or return None to serve it by replay alone.

    A subscriber that joins a stream which can no longer produce events waits
    forever: nothing pushes the end-of-stream sentinel, so the browser shows a run
    that never finishes (F09). Whether a run is still live cannot be answered from
    the orchestrator's memory of closed streams — a run can end in *another*
    process (an API restart, a start-up orphan sweep) or age out of that bounded
    window — so the decision is made on two authoritative facts instead:

    * this process holds no worker handle for the run (only the spawning process
      ever receives its frames), and
    * the persisted row is no longer queued/running.

    Both must hold to skip the subscription: a freshly submitted run has no handle
    yet while its worker is still starting, so absence alone would truncate a live
    stream. Whenever either fact says the run may still emit frames, the caller
    gets a queue and the stream ends on the worker's sentinel as before.
    """
    if not orch.has_worker(run_id) and run.status not in ACTIVE_RUN_STATUSES:
        return None
    return orch.subscribe(run_id)


@router.get("/{run_id}/events")
async def run_events(
    run_id: str,
    after: int = 0,
    user: UserModel = Depends(get_current_user),
) -> StreamingResponse:
    # Ownership check: a run that isn't the caller's reads as 404, so an
    # unguessable id alone is not enough to subscribe to someone else's stream.
    # The row also carries the status the live-vs-replay decision needs (F09).
    row = await _visible_run(run_id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    # Live fan-out is keyed by the id the orchestrator spawned the worker with
    # (the compact hex form), so a hyphenated request would otherwise subscribe
    # to a channel nobody publishes on (F01).
    run_id = canonical_run_id(run_id)

    # Live events come from the worker's BridgeObserver, which the orchestrator
    # receives as stdout frames and fans out to subscribers. Subscribing here is
    # what lets token deltas reach the browser while the run is still going;
    # without it the stream is replay-only and the answer appears all at once.
    # A run that can no longer produce events must NOT subscribe — see F09.
    orch = get_orchestrator()
    queue = _live_queue_for(orch, run_id, row)

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for frame in sse_for_run(run_id, queue=queue, after_line=after):
                yield frame
        finally:
            # A disconnected client must stop receiving fan-out, or its queue
            # grows unbounded for the rest of the run. Nothing to release when the
            # stream was served by replay alone.
            if queue is not None:
                orch.unsubscribe(run_id, queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{run_id}/trace")
async def run_trace(
    run_id: str,
    after: int = 0,
    user: UserModel = Depends(get_current_user),
) -> dict[str, Any]:
    if not await _run_visible(run_id, user.id):
        raise HTTPException(status_code=404, detail="run not found")
    # F03: this endpoint is an HTTP egress like SSE, so it uses the same
    # redaction boundary — the trajectory on disk holds whatever a tool echoed.
    #
    # F06: records alone cannot tell a finished run from an interrupted one, so
    # the completeness verdict travels with them and the UI shows the gap
    # instead of presenting a cut-short trace as the whole story.
    return {
        "run_id": run_id,
        "records": trajectory_records_for_egress(run_id, after_line=after),
        "completeness": inspect_trajectory(run_id).as_dict(),
    }


@router.post("/{run_id}/control")
async def run_control(
    run_id: str,
    body: dict[str, Any],
    user: UserModel = Depends(get_current_user),
) -> dict[str, Any]:
    # A stop on a run you don't own must fail closed (404), not 409.
    if not await _run_visible(run_id, user.id):
        raise HTTPException(status_code=404, detail="run not found")
    # The live handle is keyed by the spawned id form (F01): stop a hyphenated
    # spelling without this and it would silently answer "run not running".
    run_id = canonical_run_id(run_id)
    action = body.get("action")
    if action != "stop":
        raise HTTPException(status_code=400, detail="unknown action")
    ok = await get_orchestrator().stop(run_id)
    if not ok:
        raise HTTPException(status_code=409, detail="run not running")
    return {"run_id": run_id, "stopped": True}


class SteerRequest(BaseModel):
    """P3.1 live-steering payload (§6.2): ``{"message": "..."}``."""

    message: str


@router.post("/{run_id}/steer")
async def run_steer(
    run_id: str,
    body: SteerRequest,
    user: UserModel = Depends(get_current_user),
) -> dict[str, Any]:
    # A steer on a run you don't own must fail closed (404), like stop.
    if not await _run_visible(run_id, user.id):
        raise HTTPException(status_code=404, detail="run not found")
    run_id = canonical_run_id(run_id)  # live handle key form (F01)
    if not body.message.strip():
        raise HTTPException(status_code=422, detail="message is required")
    seq = await get_orchestrator().steer(run_id, body.message)
    if seq is None:
        raise HTTPException(status_code=409, detail="run not running")
    return {"run_id": run_id, "queued": True, "seq": seq}


class ApproveRequest(BaseModel):
    """P3.2 approval payload (§6.1).

    ``decision`` is a closed Literal so an out-of-enum value fails validation
    (422) before it can reach the worker's gate.
    """

    approval_id: str
    decision: Literal["once", "reject", "session_bash", "session_all", "persist"]
    replacement_command: str | None = None


@router.post("/{run_id}/approve")
async def run_approve(
    run_id: str,
    body: ApproveRequest,
    user: UserModel = Depends(get_current_user),
) -> dict[str, Any]:
    if not await _run_visible(run_id, user.id):
        raise HTTPException(status_code=404, detail="run not found")
    run_id = canonical_run_id(run_id)  # live handle key form (F01)
    ok = await get_orchestrator().approve(
        run_id, body.approval_id, body.decision, body.replacement_command,
    )
    if not ok:
        raise HTTPException(status_code=409, detail="run not running")
    return {"run_id": run_id, "approved": True}


class RevertRequest(BaseModel):
    """P3.3 revert payload (§6.3): the diff paths to restore, as ``/diff`` lists them."""

    paths: list[str]


#: Revert is a post-run action — the terminal's ``/revert`` is too. A live worker
#: is still writing into the same tree, so restoring a baseline underneath it
#: would either be undone by its next write or leave the file half-reverted.
_REVERTABLE_STATUSES = frozenset({"completed", "failed", "stopped"})


@router.post("/{run_id}/revert")
async def run_revert(
    run_id: str,
    body: RevertRequest,
    user: UserModel = Depends(get_current_user),
) -> dict[str, Any]:
    """Restore file-tool changes to their pre-run content (§6.3).

    Same ownership gate as every other run route (404 on a foreign id). Results
    are reported **per path**: a revert is a bulk, user-driven action where some
    rows are legitimately not revertable (the ``bash_scan`` class — §2.2 第二类),
    and collapsing that into one 4xx would make the whole selection look broken.
    The UI greys those rows out up front and explains why.
    """
    try:
        rid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="run not found") from None
    run = await get_run(run_id=rid, user_id=user.id)
    # Uniform 404: don't distinguish "not yours" from "doesn't exist".
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.status not in _REVERTABLE_STATUSES:
        raise HTTPException(status_code=409, detail="run not finished")
    if not body.paths:
        raise HTTPException(status_code=422, detail="paths is required")

    # Blocking file IO (baseline read + write back), so keep it off the loop.
    outcome = await asyncio.to_thread(revert_paths, run_dir_for(run_id), body.paths)
    # F18: the files just changed underneath the index, so re-derive it before
    # answering. Without this the artifact list kept the size and sha256 of the
    # content the user had just reverted away, and a reverted deliverable was
    # indistinguishable from an untouched one. Best-effort: the revert itself has
    # already happened and must still be reported.
    if outcome.get("reverted"):
        try:
            await sync_run_artifacts(
                run_id=rid, artifacts=scan_outputs(run_id)
            )
        except Exception:
            logger.exception("artifact index refresh after revert failed for %s", run_id)
    return {"run_id": run_id, **outcome}


class RunSummaryResponse(BaseModel):
    """Final, authoritative view of one run (§6.4 P2 + failure reason, T2.7/T2.8).

    Returned by ``GET /{run_id}`` so a client that just watched the SSE stream can
    reconcile the outcome it was told from the row the server persisted — the live
    stream is best-effort and may drop the terminal frame under backpressure, and a
    failed run's *reason* is only ever stored on the run row, never on the stream.
    """

    run_id: str
    session_id: str
    user_id: str
    prompt: str
    status: str
    pipeline_id: str | None = None
    model: str | None = None
    final_answer: str | None = None
    error: str | None = None
    stopped_by: str | None = None
    usage: dict[str, Any] | None = None
    run_dir: str | None = None
    created_at: str | None = None
    finished_at: str | None = None


@router.get("/{run_id}")
async def run_get(
    run_id: str,
    user: UserModel = Depends(get_current_user),
) -> RunSummaryResponse:
    """Authoritative single-run view (ownership: uniform 404, like every other route)."""
    try:
        rid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="run not found") from None
    run = await get_run(run_id=rid, user_id=user.id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return RunSummaryResponse(
        run_id=str(run.id),
        session_id=str(run.session_id),
        user_id=str(run.user_id),
        prompt=run.prompt,
        status=run.status,
        pipeline_id=run.pipeline_id,
        model=(run.llm_snapshot_json or {}).get("model"),
        final_answer=run.final_answer,
        error=run.error,
        stopped_by=run.stopped_by,
        usage=run.usage_json,
        run_dir=run.run_dir,
        created_at=run.created_at.isoformat() if run.created_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
    )


async def _visible_run(run_id: str, user_id: uuid.UUID) -> RunModel | None:
    """Return the caller's run row, or None when it is absent or another's.

    The DB is the authority: a run row without a matching owner is invisible
    regardless of disk state (anti-IDOR), and the row's status is what decides
    whether a run's event stream can still produce events (F09).
    """
    try:
        rid = uuid.UUID(run_id)
    except ValueError:
        return None
    return await get_run(run_id=rid, user_id=user_id)


async def _run_visible(run_id: str, user_id: uuid.UUID) -> bool:
    """True iff the run exists and belongs to ``user_id``.

    Used by the read/control routes so a guessed run id yields 404 rather than
    leaking existence or streaming another user's events.
    """
    return await _visible_run(run_id, user_id) is not None
