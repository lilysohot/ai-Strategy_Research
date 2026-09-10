"""Event relay: bridges live worker frames + trajectory replay into SSE.

Two sources feed a run's SSE stream (tech-stack.md §5.2):
  1. **Live**: the orchestrator forwards the worker's JSONL lifecycle frames
     (run_started / run_finished) and, at M1, the bridge is in-process — the
     orchestrator drains the worker and emits run-level events. Delta/tool events
     will come from an in-process BridgeObserver once runs are in-process (M2+);
     at M1 the worker is a subprocess and emits only lifecycle frames.
  2. **Replay**: the runtime trajectory file
     ``<run_dir>/run/agent/trajectories/react_agent.jsonl`` is tailed from a
     line-number cursor. This is the authoritative L3 timeline and the only
     source for tool argument previews and token usage.

Backpressure (§5.2): under pressure we may drop assistant_delta frames, never
lifecycle events — the trajectory always holds the full per-turn content for
replay. At M1 the live stream is lifecycle-only, so there is nothing droppable
yet; the hook is in place for M2.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from server.bridge import _is_skipped_result, redact_deep
from server.config import run_dir_for
from server.events import EventType, is_droppable, make_event, to_sse

_TRAJ = "run/agent/trajectories/react_agent.jsonl"


async def trajectory_tail(run_id: str, after_line: int = 0) -> AsyncIterator[tuple[int, dict]]:
    """Yield ``(line_number, record)`` from ``after_line`` (1-based) onward.

    Blocks (polling) for new lines until the run's summary.json appears, then
    drains any remainder and stops. Used for both initial replay and live tail.

    The line number is yielded alongside the record so the SSE layer can stamp
    every replayed event with the trajectory cursor it came from (T3.1). Without
    it a client can only *count* events to resubscribe, which breaks the moment a
    non-trajectory event (a live bridge delta) shares the stream.
    """
    traj = run_dir_for(run_id) / _TRAJ
    finished = run_dir_for(run_id) / "summary.json"
    cursor = after_line
    seen_finished = finished.exists()
    while True:
        if traj.exists():
            with traj.open("r", encoding="utf-8") as fh:
                for i, line in enumerate(fh, start=1):
                    if i <= cursor:
                        continue
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield i, json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    cursor = i
        if finished.exists() and not seen_finished:
            seen_finished = True
        if seen_finished:
            # Drain once more in case the file grew between the read and the check.
            if traj.exists():
                with traj.open("r", encoding="utf-8") as fh:
                    for i, line in enumerate(fh, start=1):
                        if i <= cursor:
                            continue
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            yield i, json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        cursor = i
            return
        await asyncio.sleep(0.25)


def trajectory_records(run_id: str, after_line: int = 0) -> list[dict]:
    """Synchronous, one-shot read of the trajectory up to ``after_line``.

    Used by the ``/trace`` replay endpoint and by the usage aggregator. Returns
    raw records (the ``t`` field discriminates start/llm/result/compaction).
    """
    traj = run_dir_for(run_id) / _TRAJ
    if not traj.exists():
        return []
    out: list[dict] = []
    with traj.open("r", encoding="utf-8") as fh:
        for i, line in enumerate(fh, start=1):
            if i <= after_line:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


async def _merge_async(
    *sources: AsyncIterator[str],
) -> AsyncIterator[str]:
    """Yield items from several async iterators as they arrive.

    There is no ``asyncio.merge`` (not even on 3.12), and the two producers have
    very different pacing — live deltas trickle in continuously while replay
    drains in bursts — so ordering is arrival-based, which is what the client
    needs to render progressively.

    A producer that raises still counts as finished, so one failing source
    cannot hang the stream; the other source keeps feeding it.
    """
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    remaining = len(sources)

    async def pump(source: AsyncIterator[str]) -> None:
        nonlocal remaining
        try:
            async for item in source:
                await queue.put(item)
        finally:
            remaining -= 1
            # Wake the consumer so it can re-check ``remaining``.
            await queue.put(None)

    tasks = [asyncio.create_task(pump(src)) for src in sources]
    try:
        while remaining > 0:
            item = await queue.get()
            if item is not None:
                yield item
        # Producers are done but items may still be buffered.
        while not queue.empty():
            item = queue.get_nowait()
            if item is not None:
                yield item
    finally:
        for task in tasks:
            task.cancel()


async def sse_for_run(
    run_id: str,
    *,
    # The queue carries a ``None`` end-of-stream sentinel (see subscribe()), so
    # its element type is ``dict | None`` — matching the orchestrator's fan-out.
    queue: asyncio.Queue[dict[str, Any] | None] | None = None,
    after_line: int = 0,
) -> AsyncIterator[str]:
    """Produce the SSE byte stream for a run.

    Two producers run **concurrently** and their frames are merged:

    * **Live** — realtime events from the worker's BridgeObserver, which crossed
      the process boundary as stdout ``event`` frames and were fanned out to
      this queue by the orchestrator. This is the only source of *incremental*
      text, so it must not wait for the replay to catch up.
    * **Replay** — the trajectory tail from the ``after`` line cursor. Authoritative
      for tool arguments and token usage, and the only source after a reconnect.

    The two overlap: a turn's text arrives as many live fragments *and* once more
    as a single whole-turn replay record. Replay ``assistant_delta`` frames are
    stamped ``full=True`` so the client can drop the replay copy of any turn it
    already streamed (see the store's de-duplication).

    Lifecycle events are never dropped; delta frames may be under backpressure.
    """
    if queue is None:
        # Replay-only fallback (tests, and any caller without a live handle).
        async for line_no, rec in trajectory_tail(run_id, after_line=after_line):
            for event in _traj_record_to_events(rec, seq=line_no):
                yield to_sse(event)
        return

    async def live() -> AsyncIterator[str]:
        while True:
            event = await queue.get()
            # None is the end-of-stream sentinel pushed when the worker's frame
            # stream closes; without it this generator would hang forever.
            if event is None:
                return
            # Best-effort drop: under backpressure, skip droppable deltas
            # (the trajectory holds the full per-turn content for replay).
            if is_droppable(event) and queue.qsize() > 64:
                continue
            terminal = event.get("type") in (
                EventType.RUN_COMPLETED.value,
                EventType.RUN_FAILED.value,
                EventType.RUN_STOPPED.value,
            )
            yield to_sse(event)
            if terminal:
                return

    async def replay() -> AsyncIterator[str]:
        # Each event carries the trajectory line it came from (``seq``), the
        # reconnect cursor the client replays (T3.1). One trajectory line can
        # expand to several events: an ``llm`` record that requests tool calls
        # yields the assistant message *and* one tool_started per call, so the
        # UI can show the step while the tool is still running.
        async for line_no, rec in trajectory_tail(run_id, after_line=after_line):
            for event in _traj_record_to_events(rec, seq=line_no):
                # Mark the whole-turn copy so the client can prefer the live
                # fragments it already rendered and skip this one.
                if event.get("type") == EventType.ASSISTANT_DELTA.value:
                    event["full"] = True
                yield to_sse(event)

    # Drives both at once and finishes when both are exhausted. Ordering between
    # the two is best-effort; the client orders by `turn`/`seq`, not by arrival,
    # so interleaving the two sources is safe.
    async for frame in _merge_async(live(), replay()):
        yield frame


def _traj_record_to_events(rec: dict, *, seq: int | None = None) -> list[dict]:
    """Map one runtime trajectory record to platform SSE event envelopes.

    The runtime's ``t`` field is start/llm/result/compaction/end. We translate to
    the platform vocabulary (tool_started/finished, run_completed, etc.) without
    losing the raw fields the timeline UI needs — notably ``thinking`` (the
    model's chain-of-thought) and ``tool_call_id`` (what pairs a started call
    with its result).

    Returns a *list*: an ``llm`` record that requests tool calls expands into the
    assistant message plus one ``tool_started`` per call, because the trajectory
    only records a tool's outcome later, in its own ``result`` line. Emitting the
    start alongside the request is what lets the UI show a running step instead
    of one that appears already finished.

    ``seq`` is the 1-based trajectory line number, stamped on replayed events so a
    reconnecting client can resume with ``?after=seq`` instead of counting frames
    (T3.1). Live (non-trajectory) events have no line and omit it — the client
    keeps the last replayed value as its cursor.
    """
    t = rec.get("t")
    events: list[dict] = []

    if t == "start":
        events.append(
            make_event(
                EventType.RUN_STARTED.value,
                model_name=rec.get("model_name"),
                tool_names=rec.get("tool_names"),
                max_turns=rec.get("max_turns"),
            )
        )
    elif t == "llm":
        turn = rec.get("turn")
        events.append(
            make_event(
                EventType.ASSISTANT_DELTA.value,
                turn=turn,
                content=rec.get("content"),
                # The reasoning text is what makes the run auditable; dropping it
                # here is why the UI used to show only the final answer.
                thinking=rec.get("thinking") or "",
                tool_calls=rec.get("tool_calls"),
                usage=rec.get("usage"),
            )
        )
        for idx, call in enumerate(rec.get("tool_calls") or []):
            if not isinstance(call, dict):
                continue
            # The trajectory's llm record names the call but carries no id, so
            # mirror the runtime's synthesised id shape (see the trajectory
            # observer) to keep start/result pairing stable.
            call_id = call.get("id") or f"call_{turn}_{idx}"
            events.append(
                make_event(
                    EventType.TOOL_STARTED.value,
                    turn=turn,
                    tool_call_id=call_id,
                    tool_name=call.get("name") or "tool",
                    input=call.get("args"),
                )
            )
    elif t == "result":
        name = rec.get("name")
        result_text = str(rec.get("result", "") or "")
        events.append(
            make_event(
                EventType.TOOL_FINISHED.value,
                turn=rec.get("turn"),
                # Without the id the UI cannot close the card it opened.
                tool_call_id=rec.get("tool_call_id") or "",
                name=name,
                tool_name=name,
                ok=not rec.get("error"),
                # Same never-ran semantics as the live bridge, so a replayed
                # skipped call does not present as a clean success.
                skipped=_is_skipped_result(result_text),
                detail=result_text[:400],
                output=rec.get("result"),
                ms=rec.get("ms"),
            )
        )
    elif t == "compaction":
        events.append(make_event(EventType.WARNING.value, detail="compaction"))
    elif t == "end":
        # Terminal bookkeeping (turns used / stop reason). The stream is closed
        # by the summary.json watcher in trajectory_tail, so there is nothing
        # user-visible to emit — and falling through to the generic warning
        # would surface a bogus "unknown traj record: end" on every run.
        return []
    else:
        events.append(make_event("warning", detail=f"unknown traj record: {t}"))

    # Replay egress masking: the trajectory is persisted unredacted by the
    # runtime, so without this a secret a tool echoed would reach the browser
    # verbatim on reconnect/replay even though the live bridge masks it. Same
    # ``_redact`` semantics, applied deeply because args are nested dicts.
    events = [redact_deep(event) for event in events]

    if seq is not None:
        for event in events:
            event["seq"] = seq
    return events
