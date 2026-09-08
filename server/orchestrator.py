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
import os
import signal
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from server.artifacts import scan_outputs
from server.bridge import redact_deep
from server.config import REPO_ROOT, get_config, run_dir_for
from server.events import EventType, make_event
from server.history import extract_final_answer, render_session_history
from server.store import (
    append_turn,
    ensure_session,
    list_turns,
    record_artifacts,
    resolve_user_llm_env,
    update_run_result,
    update_run_usage,
)
from server.usage import usage_for_run

WorkerCallback = Callable[[str, dict[str, Any]], None]


# Stable namespace so the same free-form session string (e.g. "default") always
# maps to the same UUID across restarts — important for persistent history.
_SESSION_NS = uuid.uuid5(uuid.NAMESPACE_URL, "frontier-agent/session")


def _looks_like_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _session_uuid(session_id: str) -> uuid.UUID:
    """Map a session identifier (UUID or arbitrary string) to a UUID.

    A proper UUID passes through unchanged; any other string is hashed into a
    deterministic UUID v5 under a fixed namespace.
    """
    if _looks_like_uuid(session_id):
        return uuid.UUID(session_id)
    return uuid.uuid5(_SESSION_NS, session_id)


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


class Orchestrator:
    """Manages worker subprocesses and per-session run queues."""

    def __init__(self, *, on_frame: WorkerCallback | None = None) -> None:
        self._cfg = get_config()
        self._on_frame = on_frame
        self._handles: dict[str, RunHandle] = {}
        self._session_queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._session_tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._shutting_down = False
        # Per-run live-event subscribers (SSE clients). The worker is a
        # subprocess, so realtime bridge events reach us as stdout frames and
        # are fanned out here; each subscriber is a queue drained by relay.py.
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any] | None]]] = {}

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
        session_uuid = _session_uuid(session_id)
        if user_id is not None:
            await ensure_session(
                session_id=session_uuid, user_id=user_id, title=prompt[:80] or "New chat"
            )
        # Write the user turn up-front so the assistant reply can be appended in
        # the correct order regardless of run latency.
        await append_turn(
            session_id=session_uuid,
            role="user",
            content=prompt,
            run_id=uuid.UUID(run_id) if _looks_like_uuid(run_id) else None,
        )

        async with self._lock:
            q = self._session_queues.setdefault(session_id, asyncio.Queue())
            if session_id not in self._session_tasks:
                task = asyncio.create_task(self._drain_session(session_id, q))
                self._session_tasks[session_id] = task
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

    async def stop(self, run_id: str) -> bool:
        """Cooperatively stop a running worker via its stdin channel."""
        handle = self._handles.get(run_id)
        if handle is None or handle.proc.returncode is not None:
            return False
        try:
            handle.proc.stdin.write((json.dumps({"action": "stop"}) + "\n").encode())
            await handle.proc.stdin.drain()
        except (BrokenPipeError, ValueError):
            return False
        handle.stopped = True
        # Record that *we* initiated the stop, so the resulting run lands as a
        # user-stopped run (status="stopped", stopped_by="user_stop") even if the
        # worker's own observer reports a different reason.
        handle._stopped_by = "user_stop"
        return True

    async def steer(self, run_id: str, message: str) -> int | None:
        """Queue a live-steering line into a running worker via stdin.

        Returns the new per-run seq for the queued message, or ``None`` when
        the run has no live worker. The SSE ``steer_queued`` event is fanned
        out here (not by the bridge) with the message redacted at the egress
        boundary (§7 出口统一脱敏).
        """
        handle = self._handles.get(run_id)
        if handle is None or handle.proc.returncode is not None:
            return None
        try:
            handle.proc.stdin.write(
                (json.dumps({"action": "steer", "message": message}) + "\n").encode()
            )
            await handle.proc.stdin.drain()
        except (BrokenPipeError, ValueError):
            return None
        handle.steer_seq += 1
        self._publish(
            run_id,
            make_event(
                "steer_queued",
                seq=handle.steer_seq,
                message=redact_deep(message),
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
        try:
            handle.proc.stdin.write((json.dumps(payload) + "\n").encode())
            await handle.proc.stdin.drain()
        except (BrokenPipeError, ValueError):
            return False
        return True

    # — live event fan-out ————————————————————————————————————
    def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any] | None]:
        """Register an SSE client for ``run_id`` and return its event queue.

        A ``None`` sentinel is pushed when the worker's frame stream ends, which
        is what lets the relay's live producer terminate.
        """
        q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._subscribers.setdefault(run_id, set()).add(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue[dict[str, Any] | None]) -> None:
        subs = self._subscribers.get(run_id)
        if subs is None:
            return
        subs.discard(q)
        if not subs:
            self._subscribers.pop(run_id, None)

    def _publish(self, run_id: str, payload: Any) -> None:
        """Fan one live event (or the ``None`` sentinel) out to subscribers."""
        if not isinstance(payload, dict):
            return
        for q in tuple(self._subscribers.get(run_id, ())):
            # Never block the frame reader on a slow client.
            q.put_nowait(payload)

    def _close_streams(self, run_id: str) -> None:
        """Signal every subscriber that no more live events will arrive."""
        for q in tuple(self._subscribers.get(run_id, ())):
            q.put_nowait(None)

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
    async def _drain_session(self, session_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        while not self._shutting_down:
            params = await q.get()
            if self._shutting_down:
                q.task_done()
                break
            try:
                await self._spawn(**params)
            finally:
                q.task_done()

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
            if current is not None:
                turns = [t for t in turns if t.run_id != current]
            history = render_session_history(turns)
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
                self._handles.pop(run_id, None)
            # Release the slot acquired in _launch exactly once, on every path:
            # a normally-finished worker exits on its own, so _kill_handle
            # early-returns without touching the semaphore — releasing only
            # there would leak a slot per completed run and wedge the pool.
            await self._release_slot()

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
        # Resolve credentials here, in the parent, then hand them to the worker via
        # its environment only — never as argv (argv is world-readable via ps). The
        # api_key is decrypted in-process and lives solely in the child's env.
        llm_env = await self._resolve_llm_env(params.get("user_id"))
        # Gate cross-session parallelism at worker_pool_size.
        await self._acquire_slot()
        # Persist the rendered history next to the run so the worker can read it
        # back (keeps long transcripts out of argv). Empty file == no history.
        from server.config import run_dir_for

        run_dir = run_dir_for(run_id)
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
        """
        if user_id is None:
            return None
        try:
            return await resolve_user_llm_env(user_id=user_id)
        except Exception:
            # A store/decrypt failure must not crash run submission; fall back to
            # the server default rather than injecting a broken partial set.
            return None

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
                async for line in handle.proc.stdout:
                    line = line.decode("utf-8", "replace").strip()
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
                        self._publish(handle.run_id, frame.get("payload"))
                    # Backfill the assistant turn and persist the run row when the
                    # run terminates (T2.6 / T2.7 / T2.8): take ONLY the
                    # final_answer from the worker's summary — never the workflow's
                    # internal messages.
                    if frame.get("type") == "run_finished":
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
        await append_turn(
            session_id=session_uuid,
            role="assistant",
            content=content,
            run_id=uuid.UUID(handle.run_id) if _looks_like_uuid(handle.run_id) else None,
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
        run_root = run_dir_for(handle.run_id)
        summary_path = run_root / "summary.json"
        final_answer = ""
        error = ""
        if summary_path.exists():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                final_answer = (summary.get("final_answer") or "").strip()
                error = summary.get("error") or ""
            except (json.JSONDecodeError, OSError):
                pass
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
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(handle.proc.pid), signal.SIGTERM)
        try:
            await asyncio.wait_for(handle.proc.wait(), timeout=grace)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(handle.proc.pid), signal.SIGKILL)
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
