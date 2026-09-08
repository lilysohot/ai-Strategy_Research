"""BridgeObserver: the realtime event bridge from the runtime to the web layer.

Injected into the agent loop via ``metadata["sdk_extra_observers"]``. It forwards
*realtime* events (assistant deltas, tool lifecycle) to an asyncio queue that the
relay drains into SSE. Per tech-stack.md §5.2 it is **push-only and never writes
to disk** — the runtime's own ``TrajectoryFileObserver`` owns persistence and
replay. ``stopped_by`` is captured here on ``on_loop_end`` because it lives on
``AgentLoopResult``, not on the pipeline state returned by ``BenchmarkSession.run``.

The observer also records token usage aggregated from the trajectory is NOT done
here (usage lives in the trajectory file, T2.11) — this is purely the live bridge.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from server.events import EventType, make_event

# Secrets that must never appear in a pushed event, even inside an argument blob.
_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9]{6,}|api[_-]?key\s*[=:]\s*\S+|Bearer\s+[A-Za-z0-9._-]+)",
    re.IGNORECASE,
)

# Result texts that mean the call never actually ran (per-turn tool-call cap,
# rejection, safety block) — the terminal renders these as "skipped", not as a
# clean success (apodex/observers.py ``_SYNTHETIC_RESULT_MARKERS``; the extra
# "[tool call skipped]" marker is the kernel's cap enforcement, which the
# terminal tracks via its own synthetic-call deque and the bridge can only see
# as text). Duplicated here rather than imported so the server layer does not
# depend on the terminal layer.
_SYNTHETIC_RESULT_MARKERS = (
    "[user rejected this ",
    "[The user declined",
    "[blocked by safety policy",
    "[tool call skipped]",
)


def _is_skipped_result(text: str) -> bool:
    return text.lstrip().startswith(_SYNTHETIC_RESULT_MARKERS)


def _redact(text: str) -> str:
    """Mask obvious secrets in a pushed string (best-effort, not a parser)."""
    return _SECRET_RE.sub(lambda m: m.group(0)[:6] + "…(redacted)", text)


def redact_deep(value: Any) -> Any:
    """Recursively mask every string in a JSON-like structure (dict/list/str).

    Replay events carry nested payloads the live path flattens away — tool args
    arrive as dicts, results as strings — and the trajectory file the replay
    reads is written *unredacted* by the runtime. The SSE egress must apply the
    same masking as the live bridge (``_redact``) to every string it crosses,
    otherwise a key a tool echoed survives into the browser via replay.
    """
    if isinstance(value, str):
        return _redact(value)
    if isinstance(value, dict):
        return {k: redact_deep(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_deep(v) for v in value]
    return value


class BridgeObserver:
    """Streams live run events into ``queue``; captures ``stopped_by``.

    Hook shapes are exactly as the runtime delivers them (tech-stack.md §5.2):
    ``on_tool_call`` receives a *flattened* ``{"id","name","args"}`` dict, not the
    OpenAI wire shape, and ``args`` is empty mid-stream. Argument previews are
    therefore NOT taken from here — they live in the trajectory file. The bridge
    only emits a tool name + a redacted, length-limited hint.
    """

    # Opt in to token-by-token streaming. The runtime only builds and delivers
    # ``on_llm_delta`` when some observer declares this (agent_loop.py:
    # ``stream_llm_tokens = any(getattr(o, "wants_llm_delta", False))``).
    # Without it ``call_llm`` receives ``on_delta=None`` and returns the whole
    # turn at once, which is why the UI used to show only finished answers.
    wants_llm_delta = True

    def __init__(
        self,
        # ``| None`` element: the worker's pump uses a None sentinel on the same
        # queue; the observer itself only ever puts dicts.
        queue: asyncio.Queue[dict[str, Any] | None] | None = None,
        *,
        run_meta: dict[str, Any] | None = None,
    ) -> None:
        # ``queue`` is optional: the worker uses this observer purely as a capture
        # sink for ``stopped_by`` / ``final_content`` and never drains the queue,
        # while an in-process run (M2+) forwards live events through it.
        self._queue = queue
        # Run-level facts the status bar renders (§5.6): pipeline id, model, …
        # The worker knows these before the loop starts; the loop config itself
        # only carries the context window, stamped at ``on_loop_start``.
        self._run_meta = dict(run_meta or {})
        self.tool_calls: list[str] = []
        self.tool_errors: list[str] = []
        self.deltas = 0
        self.turns = 0
        self.stopped_by = ""
        # The partial answer captured from ``AgentLoopResult.final_content`` at
        # ``on_loop_end`` — this is the ONLY place ``stopped_by`` and the partial
        # answer are observable (tech-stack.md §5.2): the pipeline state returned
        # by ``BenchmarkSession.run`` does not carry them.
        self.final_content = ""

    async def _emit(self, type_: str, **data: Any) -> None:
        # Redact any value that might carry a secret before enqueueing. A None
        # queue (capture-only mode in the worker) simply drops the live event.
        if self._queue is None:
            return
        safe = {
            k: (_redact(v) if isinstance(v, str) else v) for k, v in data.items()
        }
        await self._queue.put(make_event(type_, **safe))

    # — loop lifecycle ————————————————————————————————————————
    async def on_loop_start(self, config: Any) -> None:
        """Emit ``run_started`` with the run's status-bar facts and context limit."""
        await self._emit(
            EventType.RUN_STARTED.value,
            **self._run_meta,
            # The context window the loop enforces (LoopConfig); the status bar
            # renders "used / limit" from this plus the accumulated usage.
            context_limit=int(getattr(config, "context_token_limit", 0) or 0) or None,
        )

    async def on_loop_end(self, result: Any) -> None:
        """Capture terminal facts and emit ``run_stopped`` when the loop ended early."""
        # ``stopped_by`` is the authoritative source for the runs table (§5.2):
        # it lives on ``AgentLoopResult``, never on the pipeline state. We capture
        # it here and surface a run_stopped event when the run ended early.
        self.stopped_by = str(getattr(result, "stopped_by", "") or "")
        # The partial answer (text produced before the loop ended) is only
        # observable here, not in the pipeline state returned by
        # ``BenchmarkSession.run``. Capture it so a stopped run can still show a
        # useful partial result to the user.
        self.final_content = str(getattr(result, "final_content", "") or "")
        if self.stopped_by:
            await self._emit(EventType.RUN_STOPPED.value, stopped_by=self.stopped_by)

    # — streaming ——————————————————————————————————————————————
    async def on_llm_delta(self, ctx: Any) -> None:
        """Forward one token fragment (content and/or reasoning) as it arrives.

        Emitted with ``turn`` so the UI can accumulate fragments into the block
        belonging to that turn, and so replay can tell which turns it already
        streamed (see ``full`` on the trajectory-sourced event).
        """
        delta = str(getattr(ctx, "delta", "") or "")
        thinking = str(getattr(ctx, "thinking_delta", "") or "")
        if not delta and not thinking:
            return
        self.deltas += 1
        await self._emit(
            EventType.ASSISTANT_DELTA.value,
            text=delta,
            thinking_text=thinking,
            turn=int(getattr(ctx, "turn", 0) or 0),
        )

    # — tools —————————————————————————————————————————————————
    async def on_tool_call(self, ctx: Any, tool_call: dict[str, Any]) -> None:
        """Emit ``tool_started`` for one authorised call about to execute."""
        # Flattened shape on the streaming path; tolerate either.
        fn = tool_call.get("function") or tool_call
        name = str(fn.get("name") or "")
        if not name:
            return
        self.tool_calls.append(name)
        # Carry the id so the UI can open the card here and close it on the
        # matching result; the trajectory (which holds the arguments) stamps the
        # same id on its own tool_started, and the UI de-duplicates by it.
        call_id = str(tool_call.get("id") or fn.get("id") or "")
        await self._emit(
            EventType.TOOL_STARTED.value,
            name=name,
            tool_name=name,
            tool_call_id=call_id,
            turn=int(getattr(ctx, "turn", 0) or 0),
        )

    async def on_tool_result(self, ctx: Any, result: Any) -> None:
        """Emit ``tool_finished`` with the redacted output and outcome classification."""
        text = str(getattr(result, "result", "") or "")
        name = str(getattr(result, "name", "") or "")
        failed = bool(getattr(result, "is_error", False)) or text.lstrip().startswith(
            "Error"
        )
        if failed:
            self.tool_errors.append(name)
        ms = getattr(result, "duration_ms", None)
        await self._emit(
            EventType.TOOL_FINISHED.value,
            name=name,
            tool_name=name,
            tool_call_id=str(getattr(result, "tool_call_id", "") or ""),
            ok=not failed,
            skipped=_is_skipped_result(text),
            detail=_redact(text)[:400],
            output=_redact(text),
            ms=int(ms) if isinstance(ms, (int, float)) else None,
            turn=int(getattr(ctx, "turn", 0) or 0),
        )

    async def on_turn_end(self, ctx: Any) -> None:
        """Track the highest turn number reached (no event emitted)."""
        self.turns = max(self.turns, int(getattr(ctx, "turn", 0) or 0))

    async def on_compaction(self, event: Any) -> None:
        """Emit a ``warning`` event so the timeline shows the compaction."""
        # Compaction is informational; surface as a warning for the timeline.
        await self._emit(EventType.WARNING.value, detail="context compaction")
