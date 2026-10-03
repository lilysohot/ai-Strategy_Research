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
import uuid
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# NOTE: import UploadFile from Starlette, not FastAPI. Starlette's multipart
# parser instantiates *its own* UploadFile, which is the BASE class of
# fastapi.UploadFile — so ``isinstance(part, fastapi.UploadFile)`` is always
# False and would silently drop every uploaded file. The base class matches both.
from starlette.datastructures import UploadFile

from server import business_service as biz
from server import dispatch_outbox, investment_snapshot, store, uploads
from server.artifacts import scan_outputs
from server.bridge import redact_deep
from server.config import build_run_paths, canonical_run_id, get_config, run_dir_for
from server.deps import get_current_user
from server.diff import revert_paths
from server.orchestrator import Orchestrator, _session_uuid, get_orchestrator
from server.readiness import probe_data_root
from server.relay import sse_for_run, trajectory_page
from server.store import (
    ACTIVE_RUN_STATUSES,
    CONTROL_KIND_APPROVAL,
    CONTROL_KIND_STEER,
    STEER_QUEUED,
    STEER_UNDELIVERED,
    build_llm_snapshot,
    control_to_dict,
    create_control,
    create_run,
    ensure_session,
    get_control_by_external_id,
    get_default_llm_config,
    get_run,
    get_session,
    list_controls,
    resolve_control,
    session_exists,
    sync_run_artifacts,
    user_llm_cred_state,
)
from server.store import Run as RunModel
from server.store import User as UserModel
from server.trajectory_status import inspect_trajectory

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


async def _parse_submit(
    request: Request,
) -> tuple[str, str, list[UploadFile], Any]:
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
        # DATA-05: the business structure rides along as a JSON TEXT form field.
        # It must be parsed, not silently dropped by the legacy form parser —
        # otherwise a multipart submit would bypass every business check.
        return req.message, req.session_id, files, form.get("investment_input")
    # Fall back to the legacy JSON body.
    body = await request.json()
    # A missing/None session_id is valid (the orchestrator synthesises a stable
    # UUID from it); normalise before validation so a null payload doesn't 500.
    if isinstance(body, dict) and body.get("session_id") is None:
        body["session_id"] = "default"
    req = RunRequest.model_validate(body)
    investment_input = body.get("investment_input") if isinstance(body, dict) else None
    return req.message, req.session_id, [], investment_input


@router.post("", status_code=202)
async def submit_run(
    request: Request,
    user: UserModel = Depends(get_current_user),
) -> dict[str, Any]:
    orch = get_orchestrator()

    # F22 / F06-RUN-1: refuse work the process cannot persist. A full (or
    # read-only) run-data root made the worker's history write fail with ENOSPC
    # *after* the run was accepted — it then sat "queued" forever with no worker
    # and no terminal state. The /readyz probe is the same cheap real-bytes
    # write, so gate submission on it too, before any side effect.
    if probe_data_root() is not None:
        raise HTTPException(
            status_code=503,
            detail="运行数据根不可写（磁盘满或只读），无法持久化新的运行",
        )

    message, session_id, files, raw_investment_input = await _parse_submit(request)
    if not message:
        raise HTTPException(status_code=422, detail="message is required")

    # DATA-05: parse (and structurally validate) the business structure *before*
    # any side effect — an invalid investment_input must not leave uploaded files
    # or a run row behind. ``None`` means a legacy client: no business checks.
    spec = investment_snapshot.parse_investment_input(raw_investment_input)

    # Identity is ALWAYS the authenticated user (T2.7). The client-supplied
    # user_id, if any, is ignored — credentials are resolved from this user's own
    # default LLM config and injected into the worker env, never from the request.
    user_id = user.id

    # F07-KEY-1: an existing-but-undecryptable default key must refuse the run
    # instead of silently rerouting it to the server's provider. "No default
    # config" is the legitimate fallback case and passes through.
    if await user_llm_cred_state(user_id=user_id) == "error":
        raise HTTPException(
            status_code=503,
            detail="用户 LLM 凭据无法解密（SERVER_MASTER_KEY 已变更或损坏）；"
            "请恢复密钥或重置该 API key 后再提交",
        )
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
    if await get_session(session_id=session_uuid, user_id=user_id) is None and await session_exists(
        session_uuid
    ):
        raise HTTPException(status_code=404, detail="会话不存在")

    # DATA-06: uploaded bytes go through a controlled staging area first, so a
    # partially written attachment never appears in the read-only ``inputs`` a
    # worker may already be reading. plan() finishes every check (file count /
    # per-file size / duplicate name) BEFORE a single byte is written; a rejected
    # request therefore leaves no bytes and no run tree behind.
    uploaded: list[uploads.StagedUpload] = []
    if files:
        try:
            planned = await uploads.plan(
                files, max_files=cfg.max_upload_files, max_bytes=cfg.max_upload_bytes
            )
        except uploads.UploadError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
        uploaded = await uploads.stage(run_id_hex, planned)

    # Surface the uploaded input files to the agent via the system-prompt addendum
    # (worker.py forwards this into metadata["_sys_prompt_addendum"], which the
    # react node appends to the system prompt — see main_agent.py:817). Files are
    # published into inputs before any worker is spawned (see server/uploads.py
    # and dispatch_outbox), so the agent sees them at /inputs in container/serve
    # mode and at the physical path in native mode.
    prompt_addendum = ""
    if uploaded:
        file_list = "\n".join(f"  - /inputs/{u.stored_name}" for u in uploaded)
        inputs_path = str(build_run_paths(run_id_hex)["inputs"])
        prompt_addendum = (
            f"The user attached {len(uploaded)} input file(s) for this task. "
            f"Read them from these read-only paths:\n{file_list}\n"
            f"(native: read directly from {inputs_path})"
        )

    # The session was admitted (or is about to be created) above; make sure the
    # row exists so the turns table and the Run FK stay consistent. The business
    # path (DATA-06) creates it inside the atomic submit transaction instead —
    # legacy clients keep the original behaviour unchanged.
    if spec is None:
        await ensure_session(
            session_id=session_uuid, user_id=user_id, title=message[:80] or "新对话"
        )

    # F20: record WHICH model drove this run — never the secret. The column has
    # existed since T2.5 but nothing ever filled it, so a finished run could not
    # say which model produced it and the UI read ``model: null``.
    default_llm = await get_default_llm_config(user_id=user_id)
    snapshot = await build_llm_snapshot(user_id=user_id)

    snapshot_id: str | None = None
    outcome: Any = None
    replayed = False
    if spec is None:
        # Legacy client: no business structure, no snapshot, no business checks.
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
    else:
        if not spec.idempotency_key:
            # 建 Run 也要可重放：超时后重试必须回到同一个 Run，而不是第二个分析。
            raise biz.ValidationError(
                "缺少幂等键",
                fields={"investment_input.idempotency_key": "保存并分析必须携带幂等键"},
            )
        submitted_run_id_hex = run_id_hex
        payload = {
            "session_id": str(session_uuid),
            "message": message,
            "investment_input": raw_investment_input,
        }

        async def _execute() -> dict[str, Any]:
            # 逐研究队列上限：提交前先看深度，超限直接拒绝，不建任何东西（DATA-06）。
            depth = await dispatch_outbox.research_queue_depth(session, session_uuid)
            if depth >= cfg.dispatch_research_queue_limit:
                raise biz.QueueFullError(
                    "该研究的待执行任务已达上限，请先等待或取消已有任务",
                    current={
                        "queue_depth": depth,
                        "queue_limit": cfg.dispatch_research_queue_limit,
                        "research_id": str(session_uuid),
                    },
                )
            resolution = await investment_snapshot.resolve_for_run(
                session, user_id=user_id, research_id=session_uuid, spec=spec
            )
            store.add_run(
                session,
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
            row = investment_snapshot.build_snapshot(
                run_id=run_id,
                user_id=user_id,
                research_id=session_uuid,
                spec=spec,
                resolution=resolution,
                source="manual",
            )
            session.add(row)
            # DATA-06: 附件清单（发布意图）随 Run/outbox 同事务落库；派发前按清单
            # 校验并发布到 inputs，校验不过就不投递（见 server/uploads.py）。
            uploads.record(session, run_id=run_id, user_id=user_id, staged=uploaded)
            # DATA-06: 用户消息与派发意图进入同一事务 —— 提交成功即同时存在，
            # 派发不得再次追加相同消息；提交失败则什么都不留下。
            await store.append_turn_in(
                session, session_id=session_uuid, role="user", content=message, run_id=run_id
            )
            dispatch = await dispatch_outbox.enqueue(
                session,
                run_id=run_id,
                user_id=user_id,
                research_id=session_uuid,
                session_key=session_id,
                prompt=message,
                prompt_addendum=prompt_addendum,
            )
            await session.flush()
            return {
                "run_id": run_id_hex,
                "snapshot_id": str(row.id),
                "dispatch": dispatch_outbox.dispatch_view(dispatch),
            }

        try:
            async with biz.business_transaction() as session:
                outcome = await biz.run_write(
                    session,
                    user_id=user_id,
                    scope="run.submit",
                    idempotency_key=spec.idempotency_key,
                    payload=payload,
                    execute=_execute,
                )
        except BaseException:
            # 提交失败：本次暂存的附件随 Run 目录一起作废 —— 回滚了数据库就绝不能
            # 在盘上留下无人认领的文件（可重入补偿）。
            if uploaded:
                uploads.discard(run_id_hex)
            raise
        replayed = outcome.replayed
        snapshot_id = outcome.result.get("snapshot_id")
        if replayed:
            # 原提交已经建过 Run 并派发过；本次只回原结果，不能再造一个分析。
            run_id_hex = outcome.result["run_id"]
            run_id = uuid.UUID(run_id_hex)
            # 上传文件属于被重放的提交：新 run id 的目录没有运行行指向，删掉。
            if uploaded:
                uploads.discard(submitted_run_id_hex)
                uploaded = []

    # Legacy path dispatches in-process exactly as before. Business runs are
    # dispatched by the outbox worker (DATA-06): the dispatch intent was already
    # committed with the run, so a crash here can no longer orphan a queued run.
    if spec is None and not replayed:
        # 旧客户端直投：先把附件清单落库、做发布校验（暂存文件可读且摘要一致），
        # 再把 worker 放出去。业务 Run 的等价动作由 dispatch_outbox 在投递前执行。
        if uploaded:
            await uploads.record_for_run(run_id, user_id, uploaded)
            await uploads.publish_for_run(run_id)
        await orch.submit(
            run_id=run_id_hex,
            session_id=session_id,
            prompt=message,
            user_id=user_id,
            prompt_addendum=prompt_addendum,
        )
    dispatch_info = outcome.result.get("dispatch") if outcome is not None else None
    status = "queued"
    if replayed:
        existing = await get_run(run_id=run_id, user_id=user_id)
        status = existing.status if existing is not None else "queued"
    return {
        "run_id": run_id_hex,
        "status": status,
        "snapshot_id": snapshot_id,
        "dispatch": dispatch_info,
        "replayed": replayed,
    }


def _run_uuid(run_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(run_id))
    except (ValueError, AttributeError):
        # 与“不存在/无权”同结果，不泄漏 ID 是否合法之外的信息。
        raise biz.NotFoundOrForbiddenError("运行不存在或无权访问") from None


@router.get("/{run_id}/investment-snapshot")
async def run_investment_snapshot(
    run_id: str,
    user: UserModel = Depends(get_current_user),
) -> dict[str, Any]:
    """读取 Run 冻结的业务输入快照（DATA-05）。

    没有快照的旧运行明确报 ``404 snapshot_absent``：用当前资料回填会让历史报告
    读到用户后来才填的数字，这正是 AC-06/07 要防的事。
    """
    run_uuid = _run_uuid(run_id)
    run = await get_run(run_id=run_uuid, user_id=user.id)
    if run is None:
        raise biz.NotFoundOrForbiddenError("运行不存在或无权访问")
    async with biz.business_transaction() as session:
        row = await investment_snapshot.get_snapshot(session, user_id=user.id, run_id=run_uuid)
    if row is None:
        raise biz.SnapshotAbsentError("该运行没有业务输入快照（非业务运行）")
    return investment_snapshot.snapshot_view(row)


@router.get("/{run_id}/dispatch")
async def run_dispatch_status(
    run_id: str,
    user: UserModel = Depends(get_current_user),
) -> dict[str, Any]:
    """读取 Run 的持久派发状态（DATA-06，契约 §7）。

    派发状态与 Run 状态分离：``not_required`` 表示旧客户端直投路径（无 outbox 行），
    其余为 ``pending``/``claimed``/``dispatched``/``retryable_failed``/``abandoned``。
    派发延迟不得显示为资料丢失 —— UI 用这个端点区分"排队待派发"与"运行中"。
    """
    run_uuid = _run_uuid(run_id)
    run = await get_run(run_id=run_uuid, user_id=user.id)
    if run is None:
        raise biz.NotFoundOrForbiddenError("运行不存在或无权访问")
    async with biz.business_transaction() as session:
        row = await dispatch_outbox.get_for_run(session, run_id=run_uuid)
    if row is None:
        return {"run_id": run_uuid.hex, "status": "not_required"}
    return dispatch_outbox.dispatch_view(row)


@router.post("/{run_id}/rerun", status_code=202)
async def rerun_run(
    run_id: str,
    body: dict[str, Any],
    user: UserModel = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    """重算：停止旧执行，用**当前**资料冻结新快照，建一个新 Run（DATA-05）。

    旧 Run 的轨迹与快照原样保留，新 Run 通过 ``rerun_of_run_id`` 指回它；
    旧快照不被修改、也不被复用 —— 重算的意义就是采用新资料。
    """
    orch = get_orchestrator()
    if probe_data_root() is not None:
        raise HTTPException(
            status_code=503, detail="运行数据根不可写（磁盘满或只读），无法持久化新的运行"
        )

    old_run_uuid = _run_uuid(run_id)
    old_run = await get_run(run_id=old_run_uuid, user_id=user.id)
    if old_run is None:
        raise biz.NotFoundOrForbiddenError("运行不存在或无权访问")

    async with biz.business_transaction() as session:
        old_snapshot = await investment_snapshot.get_snapshot(
            session, user_id=user.id, run_id=old_run_uuid
        )
        if old_snapshot is None:
            raise biz.SnapshotAbsentError("该运行没有业务输入快照，无法重算")
        spec = investment_snapshot.spec_from_snapshot(old_snapshot)

    if not idempotency_key or not idempotency_key.strip():
        raise biz.ValidationError(
            "缺少幂等键", fields={"Idempotency-Key": "重算必须携带幂等键，避免重复建 Run"}
        )

    cfg = get_config()

    # 旧执行的处置：排队中且派发未投出 → 取消重提（DATA-06）；运行中 → 请求停止，
    # 并在停止超时内等它确认退出。``Orchestrator.stop`` is async: without the await
    # this returns a coroutine (always truthy), reports a stop that was never sent,
    # and leaves the old worker running until it finishes on its own.
    stop_requested = False
    old_run_stopped = False
    old_cancelled = False
    if old_run.status == "running":
        stop_requested = await orch.stop(old_run_uuid.hex)
        # 存在 native 文件副作用时，未确认旧进程停止不得并发重启（DATA-06）。这里等
        # 本进程的 worker 退出；即便超时，新 Run 也会被库级研究互斥挡住，不会并发执行。
        old_run_stopped = await orch.wait_stopped(
            old_run_uuid.hex, timeout=cfg.dispatch_stop_timeout_seconds
        )

    new_run_id = uuid.uuid4()
    new_run_id_hex = new_run_id.hex
    session_id_str = str(body.get("session_id") or old_run.session_id)
    prompt = str(body.get("message") or old_run.prompt)

    default_llm = await get_default_llm_config(user_id=user.id)
    llm_snapshot = await build_llm_snapshot(user_id=user.id)

    async def _execute() -> dict[str, Any]:
        nonlocal old_cancelled
        # 排队中且派发未投出的旧 Run：取消重提 —— 派发意图作废 + Run 置 stopped，
        # 与新 Run 的建立在同一事务，不会出现"旧的没取消、新的已派发"。
        if old_run.status == "queued" and await dispatch_outbox.cancel_pending(
            session, run_id=old_run_uuid, reason="被重算取代（取消重提）"
        ):
            fresh_old = await session.get(store.Run, old_run_uuid, with_for_update=True)
            if fresh_old is not None and fresh_old.status == "queued":
                fresh_old.status = "stopped"
                fresh_old.stopped_by = "superseded_by_rerun"
                old_cancelled = True
        # 逐研究队列上限：被取代的旧 Run 即将作废，不计入，避免它把新 Run 顶到上限外。
        depth = await dispatch_outbox.research_queue_depth(
            session, old_run.session_id, exclude_run=old_run_uuid
        )
        if depth >= cfg.dispatch_research_queue_limit:
            raise biz.QueueFullError(
                "该研究的待执行任务已达上限，请先等待或取消已有任务",
                current={
                    "queue_depth": depth,
                    "queue_limit": cfg.dispatch_research_queue_limit,
                    "research_id": str(old_run.session_id),
                },
            )
        resolution = await investment_snapshot.resolve_for_run(
            session, user_id=user.id, research_id=old_run.session_id, spec=spec
        )
        store.add_run(
            session,
            run_id=new_run_id,
            session_id=old_run.session_id,
            user_id=user.id,
            prompt=prompt,
            pipeline_id=cfg.pipeline_id,
            run_dir=str(run_dir_for(new_run_id_hex)),
            status="queued",
            llm_config_id=default_llm.id if default_llm is not None else None,
            llm_snapshot_json=llm_snapshot,
        )
        row = investment_snapshot.build_snapshot(
            run_id=new_run_id,
            user_id=user.id,
            research_id=old_run.session_id,
            spec=spec,
            resolution=resolution,
            source="manual",
            rerun_of_run_id=old_run_uuid,
        )
        session.add(row)
        # 用户消息随重算事务落库；派发经 outbox，不再重复追加。
        await store.append_turn_in(
            session, session_id=old_run.session_id, role="user", content=prompt, run_id=new_run_id
        )
        dispatch = await dispatch_outbox.enqueue(
            session,
            run_id=new_run_id,
            user_id=user.id,
            research_id=old_run.session_id,
            session_key=session_id_str,
            prompt=prompt,
        )
        await session.flush()
        return {
            "run_id": new_run_id_hex,
            "snapshot_id": str(row.id),
            "dispatch": dispatch_outbox.dispatch_view(dispatch),
        }

    async with biz.business_transaction() as session:
        outcome = await biz.run_write(
            session,
            user_id=user.id,
            scope="run.rerun",
            idempotency_key=idempotency_key.strip(),
            payload={"rerun_of_run_id": str(old_run_uuid), "message": prompt},
            execute=_execute,
        )

    # 新 Run 由 outbox 派发；研究忙时派发自动延后，串行由库级判定保证（DATA-06）。
    return {
        "run_id": outcome.result["run_id"],
        "status": "queued",
        "snapshot_id": outcome.result.get("snapshot_id"),
        "dispatch": outcome.result.get("dispatch"),
        "rerun_of_run_id": old_run_uuid.hex,
        "old_run_stop_requested": stop_requested,
        "old_run_stopped": old_run_stopped,
        "old_run_stop_timed_out": stop_requested and not old_run_stopped,
        "old_run_cancelled": old_cancelled,
        "replayed": outcome.replayed,
    }


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
    limit: int = 0,
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
    #
    # F13: the file read is blocking I/O and used to run synchronously on the
    # event loop, and the whole trajectory was materialised regardless of size.
    # The read now happens in a worker thread and is paged when ``limit`` is
    # given; ``limit=0`` keeps the historical "return everything" contract.
    records, next_line, has_more = await asyncio.to_thread(trajectory_page, run_id, after, limit)
    return {
        "run_id": run_id,
        "records": [redact_deep(rec) for rec in records],
        "completeness": inspect_trajectory(run_id).as_dict(),
        "next_line": next_line,
        "has_more": has_more,
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
    row = await _visible_run(run_id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    if not body.message.strip():
        raise HTTPException(status_code=422, detail="message is required")
    run_id = canonical_run_id(run_id)  # live handle key form (F01)
    # F21: the record is written BEFORE delivery. The worker's adoption report
    # names a control id, so there has to be a row for it to name — otherwise a
    # steer that takes effect in the very next turn would race its own record.
    # Delivery failure downgrades it immediately, so "received but never
    # delivered" (409) stays distinguishable from "delivered but never adopted".
    # Bookkeeping must never block the user's action, so a store failure only
    # costs the traceability of this one steer (the id stays None).
    control_id: str | None = None
    try:
        control = await create_control(
            run_id=row.id,
            session_id=row.session_id,
            user_id=user.id,
            kind=CONTROL_KIND_STEER,
            status=STEER_QUEUED,
            # Same redaction boundary as the SSE egress (§7): the row must never
            # hold more than what the browser was allowed to see.
            request_payload={"message": redact_deep(body.message)},
        )
        control_id = control.id.hex
    except Exception:
        logger.exception("steer control record failed for run_id=%s", row.id.hex)
    seq = await get_orchestrator().steer(run_id, body.message, control_id=control_id)
    if seq is None:
        if control_id is not None:
            # The direction never reached a worker: record that it was received
            # but not delivered, instead of leaving no trace of the 409.
            await resolve_control(
                control_id=uuid.UUID(control_id),
                status=STEER_UNDELIVERED,
                detail={"http": 409},
            )
        raise HTTPException(
            status_code=409,
            detail={"message": "run not running", "control_id": control_id},
        )
    return {"run_id": run_id, "queued": True, "seq": seq, "control_id": control_id}


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
        run_id,
        body.approval_id,
        body.decision,
        body.replacement_command,
    )
    if not ok:
        raise HTTPException(status_code=409, detail="run not running")
    # F21: the durable record is written from the worker's own frames, never from
    # this body — a client-supplied verdict is a request, not a fact. The id is
    # echoed back only when the request frame has already been persisted.
    try:
        record = await get_control_by_external_id(
            kind=CONTROL_KIND_APPROVAL, external_id=body.approval_id
        )
    except Exception:
        logger.exception("approval control lookup failed for run_id=%s", run_id)
        record = None
    return {
        "run_id": run_id,
        "approved": True,
        "control_id": record.id.hex if record is not None else None,
    }


@router.get("/{run_id}/controls")
async def run_controls(
    run_id: str,
    kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    user: UserModel = Depends(get_current_user),
) -> dict[str, Any]:
    """Durable control history for one run (F21).

    This is what a refreshed or reconnected page reads to rebuild state that
    used to exist only in a live SSE frame — most importantly an approval that
    is still pending. Ownership is checked like every other route here, so a
    guessed run id is a 404 rather than someone else's control history.
    """
    row = await _visible_run(run_id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    if kind is not None and kind not in (CONTROL_KIND_STEER, CONTROL_KIND_APPROVAL):
        raise HTTPException(status_code=422, detail="unknown kind")
    records = await list_controls(
        run_id=row.id,
        kind=kind,
        statuses=[status] if status else None,
    )
    return {"run_id": row.id.hex, "controls": [control_to_dict(r) for r in records]}


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
            await sync_run_artifacts(run_id=rid, artifacts=scan_outputs(run_id))
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
