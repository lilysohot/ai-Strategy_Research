"""Run orchestrator: spawns one worker subprocess per run.

Design (tech-stack.md §5.1):
  * run-per-subprocess, never pooled — the runtime keeps process-global state
    (``_llm_cache``, ``ResourceManager``, ``_sandbox`` singleton, ``get_config``);
    a pool would leak user A's config into user B's run.
  * worker CWD = repo root (set inside worker.py itself).
  * ``start_new_session=True`` so the orchestrator can kill the whole process
    group (children the worker spawns) on stop/shutdown.
  * hard wall-clock timeout → SIGKILL fallback after grace period.
  * per-session serialisation: runs in the same session queue; runs across
    sessions run in parallel up to ``worker_pool_size``.

The orchestrator owns the asyncio side: it launches the worker, reads the
worker's JSONL stdout frames (lifecycle + summary), and forwards ``stop`` requests
to the worker's stdin.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from server.artifacts import scan_outputs
from server.bridge import redact_deep
from server.config import REPO_ROOT, build_run_paths, get_config, run_dir_for
from server.events import EventType, is_droppable, make_event
from server.history import STEER_TURN_PREFIX, extract_final_answer, render_session_history
from server.investment_context import InvestmentContextResolver, materialize_context
from server.store import (
    APPROVAL_ABANDONED,
    APPROVAL_ADOPTED,
    APPROVAL_EXPIRED,
    APPROVAL_PENDING,
    APPROVAL_REJECTED,
    CONTROL_KIND_APPROVAL,
    STEER_ADOPTED,
    LLMCredentialError,
    append_turn,
    close_open_controls,
    create_control,
    ensure_session,
    get_control,
    list_active_runs,
    list_turns,
    mark_run_failed_if_active,
    mark_run_started,
    record_artifacts,
    resolve_control,
    resolve_user_llm_env,
    update_run_result,
    update_run_usage,
)
from server.usage import usage_for_run

logger = logging.getLogger(__name__)

WorkerCallback = Callable[[str, dict[str, Any]], None]


def _signal_worker(proc: asyncio.subprocess.Process, sig: int) -> None:
    """Signal a worker through its process group, where the platform has one.

    ``os.killpg``/``os.getpgid`` are POSIX-only, and they were called
    unconditionally from the reaping path. Where they are absent the call raised
    ``AttributeError`` — which the surrounding ``contextlib.suppress`` did not
    cover (it only suppresses ``ProcessLookupError``). That exception escaped
    ``_spawn``'s ``finally``, so the artifact scan, the usage metering and the
    pool-slot release were all skipped, and it then terminated the session's
    drain task. Reproduced live: every run silently lost its usage row and
    leaked one worker-pool slot, wedging the whole service after two runs.

    Where there is no process-group API the correct behaviour is therefore to
    signal NOTHING and let the caller's bounded ``wait`` (grace, then the SIGKILL
    escalation) do the reaping — the same thing the code did before, minus the
    exception. Substituting a per-process ``terminate()``/``kill()`` was tried
    and rejected: it only reaches the worker, never the children it spawned, and
    on this platform it wedged the orchestrator's teardown (the escalation path
    never returned; the isolated stop/escalation suite hung 2 runs in 3 where the
    un-signalled version completed every time). It is also not what a
    process-group kill means: the group is the unit that must die together.
    """
    killpg = getattr(os, "killpg", None)
    getpgid = getattr(os, "getpgid", None)
    if killpg is None or getpgid is None:
        logger.debug(
            "no process-group API on this platform; worker %s not signalled "
            "(grace wait and escalation still bound the reaping)",
            getattr(proc, "pid", "?"),
        )
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        killpg(getpgid(proc.pid), sig)


def _turns_as_of_submission(turns: list[Any], *, current_run_id: uuid.UUID | None) -> list[Any]:
    """The conversation as it stood when ``current_run_id`` was submitted (F14.

    Subtraction — "every turn except mine" — was not the same thing: a run is
    created ``queued`` and its worker may start much later, while the user keeps
    talking. Those later messages are already in ``turns``, so the model could be
    handed a question the user had not asked yet and answer it, or take a
    message that belonged to a run still waiting in the queue.

    ``submit`` writes this run's own user turn BEFORE enqueueing it, so turns
    ahead of that one are exactly the conversation the run was submitted against;
    everything after it belongs to a later submission. A run with no turn on
    record (a resumed or externally driven run) falls back to excluding only its
    own turns, which is the previous behaviour.
    """
    my_index = next((i for i, turn in enumerate(turns) if turn.run_id == current_run_id), None)
    if my_index is None:
        return [turn for turn in turns if turn.run_id != current_run_id]
    return [turn for i, turn in enumerate(turns) if i < my_index and turn.run_id != current_run_id]


def _read_run_summary(run_dir: str | Path) -> dict[str, Any]:
    """Best-effort read of a worker's ``summary.json``.

    The worker rewrites it as it makes progress, so it is the only record that
    survives a worker which was killed outright (SIGKILL) or died together with
    its parent process. A missing or unreadable file yields ``{}`` — callers
    read that as "no partial result", never as an error to surface.
    """
    path = Path(run_dir) / "summary.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


# Stable namespace so the same free-form session string (e.g. "default") always
# maps to the same UUID across restarts — important for persistent history.
_SESSION_NS = uuid.uuid5(uuid.NAMESPACE_URL, "frontier-agent/session")

#: How many recently-finished runs keep their "stream already closed" marker
#: (F09). Only a subscriber that connects just after a run ends benefits from
#: it, so a bounded window is enough — and it keeps a long-lived process from
#: accumulating one entry per run it has ever executed.
_CLOSED_STREAM_MEMORY = 512

#: Bounded in-memory fan-out per SSE subscriber (F13). A slow browser must not
#: make the relay buffer grow without limit; when a queue is full the droppable
#: delta class is discarded (the trajectory holds it for replay) and only
#: terminal/control events are parked as waiters.
_SUBSCRIBER_QUEUE_MAXSIZE = 256


def _looks_like_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _session_uuid(session_id: str, user_id: uuid.UUID | None = None) -> uuid.UUID:
    """Map a session identifier (UUID or arbitrary string) to a UUID.

    A proper UUID passes through unchanged; any other string is hashed into a
    deterministic UUID v5.

    The namespace is scoped per user (F08). A client that omits ``session_id``
    sends the literal ``"default"``, and under one shared namespace every user's
    "default" collapsed onto the SAME session — the first user to create it then
    owned everyone else's runs, and every later user's submission was a foreign
    write. Scoping the namespace by ``user_id`` gives each user their own
    conversation while keeping the mapping deterministic across restarts.

    ``user_id=None`` keeps the historical mapping, for callers that genuinely
    have no identity (the orchestrator's last-resort fallback); every
    identity-bearing call site passes it explicitly.
    """
    if _looks_like_uuid(session_id):
        return uuid.UUID(session_id)
    ns = _SESSION_NS if user_id is None else uuid.uuid5(_SESSION_NS, str(user_id))
    return uuid.uuid5(ns, session_id)


@dataclass
class RunHandle:
    run_id: str
    session_id: str
    proc: asyncio.subprocess.Process
    frames: list[dict[str, Any]] = field(default_factory=list)
    stopped: bool = False
    _params: dict[str, Any] = field(default_factory=dict)
    # Set True once the worker emits a run_finished frame, so the SIGKILL fallback
    # in _spawn only synthesizes a terminal frame when needed (T2.8).
    _finished: bool = False
    # Set by ``stop()`` when the stop was user-initiated; consulted when the
    # worker dies without emitting a run_finished frame (T2.8).
    _stopped_by: str = ""
    # Monotonic per-run counter for steered messages (§7: every event carries
    # a client-orderable seq).
    steer_seq: int = 0
    # F21 bookkeeping for live steers: control id → the steer_seq the client was
    # told about, and control id → the raw text. The raw text never goes into the
    # control record (that stores the redacted payload), so the adopted turn is
    # written from here — a run whose worker died has nothing to adopt, which is
    # exactly why an in-process map is sufficient.
    steer_controls: dict[str, int] = field(default_factory=dict)
    steer_texts: dict[str, str] = field(default_factory=dict)


class Orchestrator:
    """Manages worker subprocesses and per-session run queues."""

    def __init__(self, *, on_frame: WorkerCallback | None = None) -> None:
        self._cfg = get_config()
        self._on_frame = on_frame
        self._handles: dict[str, RunHandle] = {}
        self._session_queues: dict[str, asyncio.Queue[dict[str, Any] | None]] = {}
        self._session_tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._shutting_down = False
        # Per-run live-event subscribers (SSE clients). The worker is a
        # subprocess, so realtime bridge events reach us as stdout frames and
        # are fanned out here; each subscriber is a queue drained by relay.py.
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any] | None]]] = {}
        # Runs whose frame stream has already ended in THIS process (F09). A
        # subscriber that arrives afterwards must be told immediately, otherwise
        # its SSE generator waits on a queue nothing will ever publish to and the
        # browser shows a run that never finishes. Bounded: only recent runs can
        # have an in-flight reconnect.
        self._closed_streams: deque[str] = deque(maxlen=_CLOSED_STREAM_MEMORY)
        self._closed_stream_ids: set[str] = set()
        self._investment_context_resolver = InvestmentContextResolver()

    # — public API ————————————————————————————————————————————
    async def submit(
        self,
        *,
        run_id: str,
        session_id: str,
        prompt: str,
        user_id: uuid.UUID | None = None,
        agent_tools: str = "",
        prompt_addendum: str = "",
        turn_index: int = 1,
        backfill_turn: bool = True,
    ) -> None:
        """Enqueue a run. Same-session runs execute serially.

        The LLM credentials are NEVER passed in cleartext through here. The
        orchestrator resolves the caller's default config from the store, decrypts
        the api_key in-process, and injects ``OPENAI_*`` into the worker's
        environment (see :meth:`_resolve_llm_env`). When the user has no usable
        config, nothing is injected and the worker falls back to the server's own
        ``.env`` — the "all present or all absent" rule from tech-stack §5.3.

        Multi-turn backfill (T2.6): the user's prompt is written as a ``user`` turn
        immediately, and the prior turns of the session are rendered into the
        worker's history input so the next run sees the full conversation. The
        assistant's reply is back-filled once the worker emits ``run_finished``.
        """
        # Normalise the session id to a UUID. The M1 API accepts a free-form
        # string (e.g. "default"); we synthesise a stable UUID from it so the
        # runs/turns tables key on a proper foreign key. A fixed namespace keeps
        # the same string mapping to the same id across restarts.
        session_uuid = _session_uuid(session_id, user_id)
        if user_id is not None:
            await ensure_session(
                session_id=session_uuid, user_id=user_id, title=prompt[:80] or "New chat"
            )
        # Write the user turn up-front so the assistant reply can be appended in
        # the correct order regardless of run latency. Outbox-dispatched runs
        # (DATA-06) wrote it inside the submit transaction — appending again
        # here would duplicate the message in the transcript.
        if backfill_turn:
            await append_turn(
                session_id=session_uuid,
                role="user",
                content=prompt,
                run_id=uuid.UUID(run_id) if _looks_like_uuid(run_id) else None,
            )

        async with self._lock:
            q = self._session_queues.setdefault(session_id, asyncio.Queue())
            task = self._session_tasks.get(session_id)
            # Start a drain task only if this session has none, or the one it had
            # is already finished. Checking ``done()`` is what makes a session
            # self-healing: a drain task that ended (a queue sentinel, or an
            # error that slipped past its guard) used to leave the session
            # permanent — every later submission was enqueued to a queue nobody
            # was reading, so the run sat "queued" forever.
            if task is None or task.done():
                self._session_tasks[session_id] = asyncio.create_task(
                    self._drain_session(session_id, q)
                )
        params: dict[str, Any] = {
            "run_id": run_id,
            "session_id": session_id,
            "session_uuid": session_uuid,
            "prompt": prompt,
            "user_id": user_id,
            "agent_tools": agent_tools,
            "prompt_addendum": prompt_addendum,
            "turn_index": turn_index,
        }
        await q.put(params)

    async def stop(self, run_id: str, *, stopped_by: str = "user_stop") -> bool:
        """Cooperatively stop a running worker via its stdin channel."""
        handle = self._handles.get(run_id)
        if handle is None or handle.proc.returncode is not None:
            return False
        stdin = handle.proc.stdin
        if stdin is None:
            # The worker exited before its stdin pipe was wired up; there is
            # nothing left to signal, so report the stop as a no-op.
            return False
        try:
            stdin.write((json.dumps({"action": "stop"}) + "\n").encode())
            await stdin.drain()
        except (BrokenPipeError, ValueError):
            return False
        handle.stopped = True
        # Record why *we* initiated the stop, so the resulting run preserves the
        # caller's durable reason even if the worker observer reports another one.
        handle._stopped_by = stopped_by
        return True

    async def wait_stopped(self, run_id: str, *, timeout: float) -> bool:
        """Wait for **this process's** worker for ``run_id`` to exit (DATA-06).

        Returns True when the worker is confirmed gone: it was never spawned here,
        already exited, or exited within ``timeout``. Returns False only when a
        live worker of this process ignored the stop past the deadline. An absent
        handle is not ours to observe (another API process may own that worker), so
        it counts as confirmed rather than blocking the caller forever — the
        database-level research mutex still guarantees no two runs of the same
        research execute concurrently.
        """
        handle = self._handles.get(run_id)
        if handle is None or handle.proc.returncode is not None:
            return True
        try:
            await asyncio.wait_for(handle.proc.wait(), timeout=max(0.0, timeout))
            return True
        except TimeoutError:
            return False

    async def steer(
        self, run_id: str, message: str, *, control_id: str | None = None
    ) -> int | None:
        """Queue a live-steering line into a running worker via stdin.

        Returns the new per-run seq for the queued message, or ``None`` when
        the run has no live worker. The SSE ``steer_queued`` event is fanned
        out here (not by the bridge) with the message redacted at the egress
        boundary (§7 出口统一脱敏).

        ``control_id`` is the id of the ``control_records`` row the caller
        persisted (F21). It is forwarded to the worker so the adoption report can
        name it, and kept here so an adopted steer can be turned into a transcript
        row when the worker confirms it. The payload keeps its historical shape
        when no control row exists (internal callers, tests).
        """
        handle = self._handles.get(run_id)
        if handle is None or handle.proc.returncode is not None:
            return None
        stdin = handle.proc.stdin
        if stdin is None:
            return None
        payload: dict[str, Any] = {"action": "steer", "message": message}
        if control_id:
            payload["control_id"] = control_id
        try:
            stdin.write((json.dumps(payload) + "\n").encode())
            await stdin.drain()
        except (BrokenPipeError, ValueError):
            return None
        handle.steer_seq += 1
        if control_id:
            handle.steer_controls[control_id] = handle.steer_seq
            handle.steer_texts[control_id] = message
        self._publish(
            run_id,
            # ``steer_seq``, not ``seq``: ``seq`` is reserved for the trajectory
            # line number, which is the reconnect cursor (``?after=seq``). Reusing
            # it for the steer counter jumped the cursor past unread lines on the
            # next reconnect (F09).
            make_event(
                "steer_queued",
                steer_seq=handle.steer_seq,
                message=redact_deep(message),
                **({"control_id": control_id} if control_id else {}),
            ),
        )
        return handle.steer_seq

    async def approve(
        self,
        run_id: str,
        approval_id: str,
        decision: str,
        replacement_command: str | None = None,
    ) -> bool:
        """Forward an approval decision to a running worker via stdin (§6.1).

        Returns ``False`` when the run has no live worker (route → 409). No SSE
        fan-out here: the worker's own observer emits ``approval_resolved`` on
        the event bridge once the gate future is resolved.
        """
        handle = self._handles.get(run_id)
        if handle is None or handle.proc.returncode is not None:
            return False
        payload: dict[str, Any] = {
            "action": "approve",
            "approval_id": approval_id,
            "decision": decision,
        }
        if replacement_command:
            payload["replacement_command"] = replacement_command
        stdin = handle.proc.stdin
        if stdin is None:
            return False
        try:
            stdin.write((json.dumps(payload) + "\n").encode())
            await stdin.drain()
        except (BrokenPipeError, ValueError):
            return False
        return True

    # — live event fan-out ————————————————————————————————————
    def has_worker(self, run_id: str) -> bool:
        """True when THIS process owns the worker running ``run_id``.

        Only the process that spawned the worker receives its frames, so a run
        with no handle here cannot publish another live event to this process.
        Absence alone does not mean the run is over — a freshly submitted run has
        no handle until the session queue drains — which is why the caller pairs
        this with the run's persisted status; see
        ``server.routes.runs._live_queue_for`` (F09).
        """
        return run_id in self._handles

    def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any] | None]:
        """Register an SSE client for ``run_id`` and return its event queue.

        A ``None`` sentinel is pushed when the worker's frame stream ends, which
        is what lets the relay's live producer terminate.

        F09: when the run's stream already ended, the sentinel is queued BEFORE
        the caller's generator starts, so a late (or reconnecting) subscriber
        sees the replay and then a closed stream instead of hanging forever on a
        queue that will never be published to again.

        This is the in-process fast path: it can only know about runs whose stream
        ended HERE. A run that ended in another process (an API restart, a
        start-up orphan sweep) is filtered out one layer up, before subscribing at
        all, by the runs routes — see ``_live_queue_for``, which pairs
        ``has_worker`` with the run's persisted status. Handle absence alone is
        not a terminal test, because a freshly submitted run has no handle yet
        while its worker is still starting.
        """
        q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_MAXSIZE)
        self._subscribers.setdefault(run_id, set()).add(q)
        if run_id in self._closed_stream_ids:
            q.put_nowait(None)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue[dict[str, Any] | None]) -> None:
        subs = self._subscribers.get(run_id)
        if subs is None:
            return
        subs.discard(q)
        if not subs:
            self._subscribers.pop(run_id, None)

    @staticmethod
    def _q_put_bounded(
        q: asyncio.Queue[dict[str, Any] | None], payload: dict[str, Any] | None
    ) -> None:
        """Put into a bounded subscriber queue; under pressure drop deltas only.

        F13: a slow SSE consumer must not make the in-memory fan-out grow
        without bound. ``put_nowait`` raises when the queue is full; the
        droppable event class (``assistant_delta``) is discarded — the
        trajectory holds the full per-turn content for replay — while
        terminal/control events and the end-of-stream sentinel are parked as a
        single waiter task that completes once the consumer drains (rare
        lifecycle frames, so bounded by construction).
        """
        try:
            q.put_nowait(payload)
            return
        except asyncio.QueueFull:
            pass
        if isinstance(payload, dict) and is_droppable(payload):
            return
        asyncio.get_running_loop().create_task(q.put(payload))

    def _publish(self, run_id: str, payload: Any) -> None:
        """Fan one live event (or the ``None`` sentinel) out to subscribers."""
        if not isinstance(payload, dict):
            return
        for q in tuple(self._subscribers.get(run_id, ())):
            # Never block the frame reader on a slow client.
            self._q_put_bounded(q, payload)

    def _close_streams(self, run_id: str) -> None:
        """Signal every subscriber that no more live events will arrive.

        The run is also remembered as closed (F09) so a subscriber that connects
        AFTER this point is terminated immediately, instead of waiting for a
        sentinel that has already been delivered to the subscribers that were
        present at the time.
        """
        if run_id not in self._closed_stream_ids:
            if len(self._closed_streams) == self._closed_streams.maxlen:
                # ``append`` below evicts this entry; drop it from the mirror set
                # so the two structures cannot drift apart.
                self._closed_stream_ids.discard(self._closed_streams[0])
            self._closed_streams.append(run_id)
            self._closed_stream_ids.add(run_id)
        for q in tuple(self._subscribers.get(run_id, ())):
            self._q_put_bounded(q, None)

    async def reconcile_orphan_runs(self) -> int:
        """Close out runs left active by a process that no longer exists.

        ``runs`` rows outlive the server process, but the worker handles that
        would have finished them live only in memory. After a start-up that
        follows a crash, a deploy or a container reschedule, every row still
        marked queued/running is one nobody will ever complete: its worker is
        gone, so the SSE stream the UI is holding open will never produce a
        terminal frame. Without this sweep the run spins in the UI forever, and
        (once quotas land) keeps consuming a concurrency slot.

        Runs whose handle exists in this process are skipped — they are live and
        will report their own outcome.

        Returns how many runs were closed. Never raises: a failed sweep must not
        take the API down, it only means the next start-up will try again.
        """
        from server import dispatch_outbox, store

        try:
            stale = await list_active_runs()
        except Exception:
            logger.exception("orphan-run reconcile: query failed, skipping sweep")
            return 0

        # DATA-06: a run that was committed but whose worker never started is NOT an
        # orphan — it still has a live dispatch intent, and the dispatch loop will
        # pick it up after this sweep. Reaping it (and abandoning its outbox) would
        # break the "a committed submit survives a crash" promise (AC-05).
        try:
            async with store.get_sessionmaker()() as session:
                recoverable = await dispatch_outbox.recoverable_run_ids(
                    session, {row.id for row in stale}
                )
        except Exception:
            logger.exception("orphan-run reconcile: dispatch intent lookup failed")
            recoverable = set()

        closed = 0
        for row in stale:
            if row.id in recoverable:
                logger.info(
                    "orphan run kept for dispatch: run_id=%s (live outbox intent)", row.id.hex
                )
                continue
            run_id = row.id.hex
            if run_id in self._handles:
                continue
            partial = _read_run_summary(row.run_dir)
            final_answer = str(partial.get("final_answer") or "").strip()
            error = str(partial.get("error") or "").strip()
            # A partial answer means the worker got far enough to be worth
            # keeping — but the run was still cut short, so it is "stopped",
            # never "completed".
            status = "stopped" if final_answer else "failed"
            await update_run_result(
                run_id=row.id,
                status=status,
                final_answer=final_answer or None,
                error=error or ("服务重启导致运行中断" if status == "failed" else None),
                stopped_by="server_restart",
            )
            # F15: the row is only half the record. Whatever the worker had
            # already written — the answer the user was watching, the deliverables
            # in ws/outputs, the tokens it spent — is recovered here, so a restart
            # no longer leaves a "stopped" run whose conversation has no message,
            # whose artifact index is empty and whose usage reads null while the
            # trajectory sits on disk.
            try:
                await self._recover_finished_run(
                    run_id=row.id,
                    session_id=row.session_id,
                    final_answer=final_answer,
                    stopped_by="server_restart",
                    error=error,
                )
            except Exception:
                # One unrecoverable run must not abort the sweep — the remaining
                # rows still need closing out.
                logger.exception("orphan recovery failed for run_id=%s", run_id)
            # F21: a control action that was pending when the process died can
            # never take effect now — the worker that owned the gate is gone.
            await self._close_control_records(run_id, closed_by="server_restart")
            # DATA-06: the dispatch intent must follow the run — an orphaned run
            # must not be re-dispatched by the outbox on the next start-up.
            try:
                async with store.get_sessionmaker()() as session, session.begin():
                    await dispatch_outbox.abandon_for_run(
                        session,
                        run_id=row.id,
                        reason="服务重启判定运行中断，派发作废",
                    )
            except Exception:
                logger.exception("outbox abandon failed for run_id=%s", run_id)
            closed += 1
            logger.warning("orphan run reconciled: run_id=%s status=%s", run_id, status)

        if closed:
            logger.warning("orphan-run reconcile: closed %d run(s)", closed)
        return closed

    async def shutdown(self) -> None:
        """Drain queues, then SIGKILL any live workers."""
        self._shutting_down = True
        # Cancel per-session drain tasks; in-flight runs get killed below.
        for task in self._session_tasks.values():
            task.cancel()
        # Give a short grace for clean exits, then SIGKILL the process groups.
        await asyncio.sleep(0)
        for handle in list(self._handles.values()):
            await self._kill_handle(handle)
        for task in self._session_tasks.values():
            with contextlib.suppress(asyncio.CancelledError):
                await task

    # — internals —————————————————————————————————————————————
    async def _drain_session(
        self, session_id: str, q: asyncio.Queue[dict[str, Any] | None]
    ) -> None:
        while not self._shutting_down:
            params = await q.get()
            # ``None`` is the end-of-queue sentinel: drain what is already queued
            # and retire this task instead of blocking on an empty queue forever.
            if params is None or self._shutting_down:
                q.task_done()
                break
            try:
                await self._spawn(**params)
            except Exception as exc:
                # F15: one run that fails to launch must not abandon the items
                # already queued behind it in the same session. Letting the
                # exception escape killed this drain task, so every later run of
                # that session stayed "queued" forever with no worker coming.
                logger.exception(
                    "run launch failed for session=%s run_id=%s; continuing queue",
                    session_id,
                    params.get("run_id"),
                )
                # F22 / F06-RUN-1: a launch failure used to leave the run row
                # "queued" with no worker and no terminal state — a full
                # run-data root (ENOSPC on the history write) wedged the row
                # forever. Close it now so it is not a zombie in the UI.
                await self._mark_launch_failed(params, exc)
            finally:
                q.task_done()

    async def _mark_launch_failed(self, params: dict[str, Any], exc: Exception) -> None:
        """Close the run row of a run that failed to launch (F22 / F06-RUN-1).

        Best-effort: the run data root may be full (the launch failure itself)
        but the database is a separate store, so closing the row usually
        succeeds. A row that already reached a terminal state is never touched.
        """
        run_id = params.get("run_id")
        if not run_id or not _looks_like_uuid(run_id):
            return
        reason = str(exc).strip().replace("\n", " ")[:500] or type(exc).__name__
        try:
            await mark_run_failed_if_active(
                run_id=uuid.UUID(run_id),
                error=f"launch failed: {reason}",
            )
        except Exception:
            logger.exception("failed to close run %s after launch error", run_id)

    async def _spawn(self, **params: Any) -> None:
        run_id = params["run_id"]
        session_uuid = params.get("session_uuid")
        # Render the prior turns of this session as history for the worker. We
        # deliberately use the turns table (user/assistant transcript) and NEVER
        # the workflow's internal messages — the pipeline state stays opaque.
        # The current run's own turn (the user prompt we just wrote) is excluded
        # so the worker's prompt carries the live question and history holds only
        # the prior conversation — no duplication.
        history = ""
        if session_uuid is not None:
            current = uuid.UUID(run_id) if _looks_like_uuid(run_id) else None
            turns = await list_turns(session_id=session_uuid)
            history = render_session_history(_turns_as_of_submission(turns, current_run_id=current))
        handle: RunHandle | None = None
        try:
            handle = await self._launch(run_id, params, history=history)
            handle._params = params  # keep session_uuid for assistant backfill
            self._handles[run_id] = handle
            await self._pump_frames(handle)
        finally:
            if handle is not None:
                await self._kill_handle(handle, grace=self._cfg.stop_grace_period_s)
                # T2.8: a worker killed by the hard-timeout SIGKILL never emits a
                # run_finished frame, so synthesize one now that the process is gone.
                if not getattr(handle, "_finished", False):
                    await self._synthesize_terminal_frame(handle)
                # T2.9: scan the deliverables the agent left in ws/outputs *after* the
                # worker is gone — a live process may still be writing. Artifacts are
                # recorded even for stopped/failed runs: a partial deliverable is still
                # something the user should be able to download.
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(self._record_artifacts(handle), timeout=15)
                # T2.11: meter the run now that the worker is gone and its trajectory
                # is complete. Stopped/failed runs are metered too — the user was
                # billed for those tokens whether or not the run produced an answer.
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(self._record_usage(handle), timeout=15)
                # F21: whatever control action never reached the conversation
                # ends here — a steer left in the inbox and an approval left on
                # the gate are both answered by "the run is over".
                await self._close_control_records(run_id, closed_by="run_finished")
                self._handles.pop(run_id, None)
            # Release the slot acquired in _launch exactly once, on every path:
            # a normally-finished worker exits on its own, so _kill_handle
            # early-returns without touching the semaphore — releasing only
            # there would leak a slot per completed run and wedge the pool.
            await self._release_slot()

    async def _persist_run_started(self, handle: RunHandle) -> None:
        """Persist "this run is executing now" (F20).

        Best-effort like the other lifecycle sinks: a bookkeeping failure must
        not abort the frame pump and leave the run's stream unread.
        """
        if not _looks_like_uuid(handle.run_id):
            return
        try:
            await mark_run_started(run_id=uuid.UUID(handle.run_id))
        except Exception:
            logger.exception("run_started persist failed for %s", handle.run_id)

    # — control records (F21) —————————————————————————————————————————
    def _control_owner(self, handle: RunHandle) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID] | None:
        """``(run_id, session_id, user_id)`` for a control record, or ``None``.

        A control action is user content, so it is recorded only when all three
        identities are known: a real UUID run row, a session, and the
        authenticated user carried on the spawn params. A run with no user (an
        internal or legacy caller) records nothing rather than inventing an owner.
        """
        if not _looks_like_uuid(handle.run_id):
            return None
        params = getattr(handle, "_params", None) or {}
        session_uuid = params.get("session_uuid")
        user_id = params.get("user_id")
        if session_uuid is None or user_id is None:
            return None
        return uuid.UUID(handle.run_id), session_uuid, user_id

    @staticmethod
    def _approval_status(decision: str, source: str) -> str:
        """Map a worker verdict onto the durable approval states (F21).

        The gate fails closed with ``decision="reject"`` for three different
        reasons (a real decline, the 300s timeout, a stop that force-rejected the
        pending item) and for an unknown id. Collapsing them would record a
        decision the user never made, so ``source`` decides which state it is.
        """
        if source in ("timeout", "unknown"):
            return APPROVAL_EXPIRED
        if source == "stopped":
            return APPROVAL_ABANDONED
        return APPROVAL_REJECTED if decision == "reject" else APPROVAL_ADOPTED

    async def _persist_control_event(self, handle: RunHandle, payload: Any) -> None:
        """Persist an approval request or verdict as it streams by (F21).

        Best-effort like the other lifecycle sinks: a bookkeeping failure must
        not abort the frame pump and leave the run's stream unread. Both events
        already crossed the worker's redaction boundary
        (``ApprovalObserver._publish``), so what is stored has the same shape the
        browser received.
        """
        if not isinstance(payload, dict):
            return
        type_ = payload.get("type")
        if type_ not in ("approval_requested", "approval_resolved"):
            return
        owner = self._control_owner(handle)
        if owner is None:
            return
        run_id, session_id, user_id = owner
        approval_id = str(payload.get("approval_id") or "")
        if not approval_id:
            return
        try:
            if type_ == "approval_requested":
                await create_control(
                    run_id=run_id,
                    session_id=session_id,
                    user_id=user_id,
                    kind=CONTROL_KIND_APPROVAL,
                    status=APPROVAL_PENDING,
                    external_id=approval_id,
                    request_payload={
                        key: payload.get(key)
                        for key in ("tool_name", "target", "reason", "preview", "risk")
                        if payload.get(key) is not None
                    },
                )
                return
            decision = str(payload.get("decision") or "")
            source = str(payload.get("source") or "user")
            status = self._approval_status(decision, source)
            row = await resolve_control(
                kind=CONTROL_KIND_APPROVAL,
                external_id=approval_id,
                status=status,
                decision=decision or None,
                replacement_command=payload.get("replacement_command"),
                detail={"source": source},
            )
            if row is None:
                # The request frame never arrived (a decision for an id opened
                # before this process existed). Record the verdict rather than
                # dropping the fact; the mark says it was reconstructed late.
                await create_control(
                    run_id=run_id,
                    session_id=session_id,
                    user_id=user_id,
                    kind=CONTROL_KIND_APPROVAL,
                    status=status,
                    external_id=approval_id,
                    request_payload={"tool_name": payload.get("tool_name")}
                    if payload.get("tool_name")
                    else None,
                    detail={"source": source, "recorded_late": True},
                )
        except Exception:
            logger.exception("control event persist failed for run_id=%s", handle.run_id)

    async def _record_steer_adopted(self, handle: RunHandle, frame: dict[str, Any]) -> None:
        """Mark a steer as adopted and write it into the transcript (F21).

        Both halves are written together, because either alone is a half-truth:
        the record says the direction took effect, and the turn is what makes the
        *next* run see it (``server/history.py`` renders history from ``turns``).
        The turn goes first — its ``seq`` is the adoption position stored on the
        record. A re-delivered frame is a no-op: a record that already has an
        ``adopted_turn_seq`` must not produce a second message (the F15 duplicate
        terminal-frame lesson, one layer down).
        """
        control_id = str(frame.get("control_id") or "")
        if not control_id or not _looks_like_uuid(control_id):
            return
        owner = self._control_owner(handle)
        if owner is None:
            return
        run_id = owner[0]
        try:
            record = await get_control(control_id=uuid.UUID(control_id))
            if record is None or record.run_id != run_id:
                return
            if record.adopted_turn_seq is not None:
                return
            text = handle.steer_texts.pop(control_id, None)
            turn_seq = record.adopted_turn_seq
            if text:
                turn = await append_turn(
                    session_id=record.session_id,
                    role="user",
                    content=f"{STEER_TURN_PREFIX}{text}",
                    run_id=record.run_id,
                )
                turn_seq = turn.seq
            await resolve_control(
                control_id=uuid.UUID(control_id),
                status=STEER_ADOPTED,
                adopted_turn_seq=turn_seq,
                detail={"reported_by": "worker"},
            )
        except Exception:
            logger.exception("steer adoption persist failed for run_id=%s", handle.run_id)
            return
        self._publish(
            handle.run_id,
            make_event(
                EventType.STEER_APPLIED.value,
                control_id=control_id,
                steer_seq=handle.steer_controls.pop(control_id, None),
                turn_index=turn_seq,
            ),
        )

    async def _close_control_records(self, run_id: str, *, closed_by: str) -> None:
        """Close out a finished run's still-open control records (F21).

        A steer sitting in the worker's inbox, or an approval parked on its gate,
        dies with the worker. Without this they would read "queued"/"pending"
        forever — indistinguishable from an action about to take effect, which is
        exactly the failure this task removes.
        """
        if not _looks_like_uuid(run_id):
            return
        try:
            closed = await close_open_controls(run_id=uuid.UUID(run_id), closed_by=closed_by)
        except Exception:
            logger.exception("control record closure failed for run_id=%s", run_id)
            return
        if closed:
            logger.info("closed %d open control record(s) for run_id=%s", closed, run_id)

    async def _record_usage(self, handle: RunHandle) -> None:
        """Aggregate the run's per-turn usage from its trajectory and persist it.

        Best-effort: metering must never break the run lifecycle, so every
        failure (missing trajectory, unreadable file, DB error) is swallowed
        after logging.
        """
        if not _looks_like_uuid(handle.run_id):
            return
        try:
            usage = usage_for_run(handle.run_id)
        except Exception:
            return
        try:
            await update_run_usage(run_id=uuid.UUID(handle.run_id), usage=usage)
        except Exception:
            return

    async def _record_artifacts(self, handle: RunHandle) -> None:
        """Scan the run's outputs dir and persist size+sha256 (T2.9).

        Best-effort by design: a missing run row (non-UUID id) or an unreadable
        tree must never break the run lifecycle — the artifacts table is an index,
        not a source of truth for the files themselves.
        """
        if not _looks_like_uuid(handle.run_id):
            return
        try:
            found = scan_outputs(handle.run_id)
        except Exception:
            return
        if not found:
            return
        try:
            await record_artifacts(run_id=uuid.UUID(handle.run_id), artifacts=found)
        except Exception:
            # Never propagate a bookkeeping failure into the run lifecycle.
            return

    async def _launch(self, run_id: str, params: dict[str, Any], *, history: str = "") -> RunHandle:
        # Resolve the immutable business snapshot in the authenticated parent.
        # The worker receives only this Run's minimal materialized context, not
        # database credentials or access to another user's ledger.
        user_id = params.get("user_id")
        run_uuid = uuid.UUID(run_id)
        run_dir = run_dir_for(run_id)
        context = None
        if user_id is not None:
            context = await self._investment_context_resolver.resolve(
                run_id=run_uuid, user_id=user_id
            )
            if context is not None:
                materialize_context(
                    run_dir, context, resolver=self._investment_context_resolver
                )
        if context is None:
            # Never let a prior launch's materialized data bypass a failed or
            # absent authenticated resolution on a later launch attempt.
            for name in ("investment-context.json", "investment-context-resolver.json"):
                (run_dir / name).unlink(missing_ok=True)
        # Resolve credentials here, in the parent, then hand them to the worker via
        # its environment only — never as argv (argv is world-readable via ps). The
        # api_key is decrypted in-process and lives solely in the child's env.
        llm_env = await self._resolve_llm_env(params.get("user_id"))
        # Gate cross-session parallelism at worker_pool_size.
        await self._acquire_slot()
        # Persist the rendered history next to the run so the worker can read it
        # back (keeps long transcripts out of argv). Empty file == no history.
        run_dir.mkdir(parents=True, exist_ok=True)
        history_path = run_dir / "history.txt"
        history_path.write_text(history, encoding="utf-8")
        cmd = [
            sys.executable,
            "-m",
            "server.worker",
            "--run-id",
            run_id,
            "--session-id",
            params["session_id"],
            "--turn-index",
            str(params.get("turn_index", 1)),
            "--prompt",
            params["prompt"],
            "--backend",
            self._cfg.sandbox_backend,
            "--wall-time",
            str(self._cfg.wall_timeout_s),
            "--max-turns",
            str(self._cfg.max_turns),
            "--pipeline-id",
            self._cfg.pipeline_id,
        ]
        if params.get("agent_tools"):
            cmd += ["--agent-tools", params["agent_tools"]]
        if params.get("prompt_addendum"):
            cmd += ["--prompt-addendum", params["prompt_addendum"]]

        child_env = {**os.environ}
        # The worker has no database responsibility. Give accidental store use a
        # private in-memory database instead of inheriting the platform DSN.
        # Empty tombstones also prevent worker-side ``load_dotenv(override=False)``
        # from restoring platform secrets from the repository .env file.
        child_env["SERVER_DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
        child_env["SERVER_DATABASE_URL_DOCKER"] = ""
        child_env["SERVER_MASTER_KEY"] = ""
        child_env["SERVER_JWT_SECRET"] = ""
        if llm_env:
            child_env.update(llm_env)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(REPO_ROOT),
            start_new_session=True,  # → own process group, killable as a unit
            env=child_env,
        )
        return RunHandle(run_id=run_id, session_id=params["session_id"], proc=proc)

    async def _resolve_llm_env(self, user_id: uuid.UUID | None) -> dict[str, str] | None:
        """Resolve a user's default config to ``OPENAI_*`` env vars, or None.

        ``None`` means "inject nothing" — the worker then falls back to the
        server's own ``.env``. The three vars are only ever injected together.

        F07-KEY-1: an undecryptable key is NOT "no config" — swallowing it into
        ``None`` here made the worker silently run on the server's provider while
        the run's snapshot still claimed ``user-config``. That error therefore
        propagates (the spawn fails and the run closes as failed) instead of
        rerouting; the submission route's ``user_llm_cred_state`` gate already
        refuses such runs up front, this is the second line of defence for keys
        that go bad between the gate and the spawn.
        """
        if user_id is None:
            return None
        try:
            return await resolve_user_llm_env(user_id=user_id)
        except LLMCredentialError:
            raise
        except Exception:
            # A store failure (transient DB hiccup etc.) must not crash run
            # submission; fall back to the server default rather than injecting
            # a broken partial set.
            return None

    @staticmethod
    async def _iter_worker_frames(stream: asyncio.StreamReader) -> AsyncIterator[bytes]:
        """Yield worker stdout frames by chunk instead of by line.

        ``async for line in proc.stdout`` uses asyncio's line reader, whose
        buffered size is bounded: a single frame larger than ``_DEFAULT_LIMIT``
        (64 KiB) raises ``LimitOverrunError``/``ValueError`` right in the pump,
        which killed the whole run's frame stream and left the UI stuck on
        "executing" with no terminal frame. Reading raw chunks and splitting on
        ``\n`` ourselves is immune to that. Over-long frames are dropped with a
        warning instead of crashing the pump.
        """
        max_frame = 1 << 20  # 1 MiB; a legit worker frame is far below this
        buffer = b""
        while True:
            chunk = await stream.read(65536)
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, _, buffer = buffer.partition(b"\n")
                if len(line) > max_frame:
                    logger.warning(
                        "dropping worker frame of %d bytes (> %d) for run (overlong)",
                        len(line),
                        max_frame,
                    )
                    continue
                yield line
        if buffer:
            yield buffer

    async def _pump_frames(self, handle: RunHandle) -> None:
        """Read worker JSONL frames and forward them to the callback.

        On the hard-timeout escalation (``wall + grace``) the worker is still
        running; we do NOT block on ``proc.wait()`` here — that would hang until the
        worker exits on its own. Instead we return and let ``_spawn``'s ``finally``
        apply the SIGKILL and then synthesize a terminal frame (T2.8). The normal
        path (worker emits ``run_finished``) is handled inline below.
        """
        assert handle.proc.stdout is not None
        wall = self._cfg.wall_timeout_s
        try:
            async with asyncio.timeout(wall + self._cfg.stop_grace_period_s):
                async for raw in self._iter_worker_frames(handle.proc.stdout):
                    line = raw.decode("utf-8", "replace").strip()
                    if not line:
                        continue
                    try:
                        frame = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    handle.frames.append(frame)
                    if self._on_frame is not None:
                        self._on_frame(handle.run_id, frame)
                    # Realtime bridge events (token deltas, tool lifecycle) ride
                    # inside an ``event`` frame because the worker is a
                    # subprocess — its observer queue cannot cross the boundary.
                    # Rehydrate and fan them out to any SSE subscribers.
                    if frame.get("type") == "event":
                        payload = frame.get("payload")
                        self._publish(handle.run_id, payload)
                        # F21: the approval events are the only place a request
                        # or a verdict is ever stated — persist them while they
                        # are live, or a refresh has nothing to rebuild from.
                        await self._persist_control_event(handle, payload)
                    # F21: the worker reports which steers actually reached the
                    # conversation; only it can know that.
                    if frame.get("type") == "control_applied":
                        await self._record_steer_adopted(handle, frame)
                    # F20: the worker's own start frame is the only proof it
                    # launched — persist it, or the row reads "queued" forever.
                    if frame.get("type") == "run_started":
                        await self._persist_run_started(handle)
                    # Backfill the assistant turn and persist the run row when the
                    # run terminates (T2.6 / T2.7 / T2.8): take ONLY the
                    # final_answer from the worker's summary — never the workflow's
                    # internal messages.
                    if frame.get("type") == "run_finished":
                        if handle._finished:
                            # F15: a terminal frame can arrive twice (a resumed
                            # stdout stream, a retried read, a worker that emits
                            # its summary and then exits). Processing it again
                            # appended a SECOND assistant turn for the same run,
                            # so the conversation showed the answer twice.
                            continue
                        handle._finished = True
                        await self._backfill_assistant_turn(handle, frame)
                        await self._persist_run_result(handle, frame)
        except TimeoutError:
            # Worker overran; _spawn's finally will SIGKILL it and synthesize a
            # terminal frame. We must not block on proc.wait() here.
            pass
        finally:
            # The stdout frame stream is over (worker exited, or we timed out and
            # abandoned it). Release every live subscriber with the sentinel so
            # its SSE generator can terminate instead of hanging forever.
            self._close_streams(handle.run_id)

    @staticmethod
    def _trajectory_degraded(run_id: str) -> bool:
        """True when the run's trajectory file exists but holds no data (F22).

        The trajectory JSONL is created on the observer's first write. An
        existing-but-empty file therefore means every write failed (a full
        run-data root) — NOT that recording was disabled, which leaves no file
        at all. Only a cleanly-finished run is checked by the caller, so an
        empty file here is a silent storage loss, not a partial stop.
        """
        if not _looks_like_uuid(run_id):
            return False
        try:
            path = build_run_paths(run_id)["run"] / "agent" / "trajectories" / "react_agent.jsonl"
            return path.exists() and path.stat().st_size == 0
        except OSError:
            return False

    async def _backfill_assistant_turn(self, handle: RunHandle, frame: dict[str, Any]) -> None:
        """Append the assistant's reply (from ``final_answer``) to the session.

        Handles partial answers: when the run failed/stopped but still produced a
        non-empty ``final_answer`` (e.g. a user stop mid-stream), we still persist
        it as the assistant turn, tagging it with the stop/error reason so the UI
        can surface it as a partial result rather than a clean answer.
        """
        session_uuid = self._session_uuid_for(handle)
        if session_uuid is None:
            return
        # The worker's run_finished frame carries the final answer directly.
        answer = (frame.get("final_answer") or "").strip()
        if not answer:
            # Try a structured final_content / fallback extraction.
            answer = extract_final_answer(frame).strip()
        if not answer:
            return
        stopped_by = frame.get("stopped_by") or ""
        error = frame.get("error") or ""
        content = answer
        if stopped_by or error:
            tag = stopped_by or "error"
            content = f"{answer}\n\n_[partial: {tag}]_"
        elif self._trajectory_degraded(handle.run_id):
            # F22 / F06-RUN-2: a run that finished cleanly MUST have recorded a
            # trajectory; an existing-but-empty file means every observer write
            # failed (e.g. ENOSPC on a full run-data root), and the loss was
            # silent — the row read as a normal completion. Surface it.
            content = f"{answer}\n\n_[存储降级：轨迹未落盘，用量不可统计]_"
        await append_turn(
            session_id=session_uuid,
            role="assistant",
            content=content,
            run_id=uuid.UUID(handle.run_id) if _looks_like_uuid(handle.run_id) else None,
        )

    async def _materialize_input_intent(self, handle: RunHandle) -> None:
        """Best-effort：把 worker 的缺料意图落库（方案 A）。

        失败只记日志，绝不能影响 Run 终态写入；幂等由 ``worker-intent:<run_id>`` 保证，
        因此兜底 summary 路径与孤儿恢复重复调用是安全的。
        """
        try:
            from server import business_service as _biz
            from server import input_requests as _input_requests

            async with _biz.business_transaction() as session:
                await _input_requests.materialize_worker_intent(
                    session, run_id=uuid.UUID(handle.run_id)
                )
        except Exception:
            logging.getLogger("orchestrator").warning(
                "worker input intent materialize failed", exc_info=True
            )

    async def _persist_run_result(self, handle: RunHandle, frame: dict[str, Any]) -> None:
        """Persist the run's terminal state (T2.7 / T2.8).

        Status precedence (T2.8): a non-empty ``stopped_by`` means the run ended
        early — it is recorded as ``"stopped"`` (not ``"completed"``) so the UI
        can show it as a partial/stopped run. ``"failed"`` is reserved for runs
        that raised. The api_key/prompt are never touched here (they were set at
        submission). A run id that is not a UUID (defensive) is skipped.
        """
        if not _looks_like_uuid(handle.run_id):
            return
        # 方案 A：先按 worker 留下的意图建补数请求（此时 Run 仍活跃，会被置
        # stopped/input_required），再落终态；update_run_result 对该原因有防复活保护。
        await self._materialize_input_intent(handle)
        ok = frame.get("ok")
        stopped_by = frame.get("stopped_by") or ""
        error = frame.get("error") or ""
        answer = (frame.get("final_answer") or "").strip()
        if not answer:
            answer = extract_final_answer(frame).strip()
        if stopped_by:
            status = "stopped"
        elif ok:
            status = "completed"
        else:
            status = "failed"
        # A stopped/failed run with a partial answer still records the answer but
        # keeps a non-"completed" status so the UI can surface it as partial.
        await update_run_result(
            run_id=uuid.UUID(handle.run_id),
            status=status,
            final_answer=answer or None,
            error=error or None,
            stopped_by=stopped_by or None,
        )
        # Live terminal parity (cli-web-parity §5.6 / T3.1): the SSE stream must
        # carry the run's outcome, not just a closed socket that the client then
        # guesses as "completed". Without this a *failed* run is shown as completed.
        # Stops are owned by the bridge's run_stopped event, so we only emit the
        # other two outcomes here.
        if not stopped_by:
            if ok:
                self._publish(
                    handle.run_id,
                    make_event(
                        EventType.RUN_COMPLETED.value,
                        final_answer=answer or "",
                    ),
                )
            else:
                self._publish(
                    handle.run_id,
                    make_event(
                        EventType.RUN_FAILED.value,
                        error=error or "",
                    ),
                )

    async def _synthesize_terminal_frame(self, handle: RunHandle) -> None:
        """Build a terminal frame when the worker died without one (e.g. SIGKILL).

        The hard-timeout escalation in ``_kill_handle`` sends SIGKILL, which cannot
        be caught, so no ``run_finished`` arrives. We recover a best-effort result
        from the worker's ``summary.json`` (partial answer if any) and stamp the
        stop reason: a user-initiated stop wins (``user_stop``), otherwise an
        externally-killed worker is recorded as ``sigkill`` (T2.8).
        """
        if not _looks_like_uuid(handle.run_id):
            return
        summary = _read_run_summary(run_dir_for(handle.run_id))
        final_answer = (summary.get("final_answer") or "").strip()
        error = summary.get("error") or ""
        # stopped_by precedence: explicit user stop > externally killed.
        stopped_by = getattr(handle, "_stopped_by", "") or "sigkill"
        frame = {
            "type": "run_finished",
            "ok": False,
            "error": error or "killed",
            "stopped_by": stopped_by,
            "final_answer": final_answer,
        }
        handle.frames.append(frame)
        if self._on_frame is not None:
            self._on_frame(handle.run_id, frame)
        await self._backfill_assistant_turn(handle, frame)
        await self._persist_run_result(handle, frame)

    async def _recover_finished_run(
        self,
        *,
        run_id: uuid.UUID,
        session_id: uuid.UUID,
        final_answer: str,
        stopped_by: str,
        error: str,
    ) -> None:
        """Rebuild the parts of a crashed run's record that live outside its row.

        F15. Recovery used to stop at the ``runs`` row, so after a restart the
        conversation had no assistant message, the artifact index was empty and
        the token counters were null — even though the summary, the deliverables
        and the trajectory were all still on disk. Each step is idempotent: the
        message is appended only when this run has no assistant turn yet, the
        artifact scan upserts on ``(run_id, rel_path)`` and usage is a pure sum
        over the trajectory.
        """
        if final_answer:
            existing = await list_turns(session_id=session_id)
            already_recorded = any(
                turn.role == "assistant" and turn.run_id == run_id for turn in existing
            )
            if not already_recorded:
                tag = stopped_by or error
                content = final_answer if not tag else f"{final_answer}\n\n_[partial: {tag}]_"
                await append_turn(
                    session_id=session_id, role="assistant", content=content, run_id=run_id
                )
        found = scan_outputs(run_id.hex)
        if found:
            await record_artifacts(run_id=run_id, artifacts=found)
        await update_run_usage(run_id=run_id, usage=usage_for_run(run_id.hex))

    def _session_uuid_for(self, handle: RunHandle) -> uuid.UUID | None:
        """Resolve the session UUID for a handle from its enqueued params."""
        # The session uuid is stored on the handle at spawn time via params; we
        # look it up from the in-flight params bag kept on the handle.
        params = getattr(handle, "_params", None)
        if params and params.get("session_uuid"):
            return params["session_uuid"]
        # Fallback: derive deterministically from the session_id string.
        return _session_uuid(handle.session_id)

    async def _kill_handle(self, handle: RunHandle, grace: int | None = None) -> None:
        if handle.proc.returncode is not None:
            return
        grace = self._cfg.stop_grace_period_s if grace is None else grace
        # Send SIGTERM to the whole process group; escalate to SIGKILL if the
        # worker ignores it past the grace period (orphan containment, §5.1).
        _signal_worker(handle.proc, signal.SIGTERM)
        try:
            await asyncio.wait_for(handle.proc.wait(), timeout=grace)
        except TimeoutError:
            _signal_worker(handle.proc, signal.SIGKILL)
            # Bound the reaping wait so a defunct/zombie worker can never pin
            # the slot semaphore forever (which would wedge every later run at
            # _acquire_slot). The slot itself is released by _spawn's finally.
            with contextlib.suppress(Exception):
                await asyncio.wait_for(handle.proc.wait(), timeout=10)

    async def _acquire_slot(self) -> None:
        # Simple semaphore over cross-session concurrency.
        if not hasattr(self, "_sem"):
            self._sem = asyncio.Semaphore(max(1, self._cfg.worker_pool_size))
        await self._sem.acquire()

    async def _release_slot(self) -> None:
        if hasattr(self, "_sem"):
            self._sem.release()


# Module-level singleton used by the API layer.
_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator
