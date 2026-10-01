"""F13 capacity bounds — incremental tail, paged /trace read, bounded queues.

Covers the fixes for the defects measured in the pre-fix baseline
(audit/f13-capacity.json): trajectory_tail re-scanned the whole file every
250 ms (O(N) per poll), the /trace endpoint materialised the whole trajectory
and ran the sync file read on the event loop, and the orchestrator's subscriber
queues were unbounded. Every case uses a throwaway temp run root.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from server import relay
from server.config import get_config, run_dir_for
from server.orchestrator import Orchestrator

_TRAJ = "run/agent/trajectories/react_agent.jsonl"


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    cfg = get_config()
    monkeypatch.setattr(cfg, "runs_root", tmp_path / "runs")
    cfg.ensure_dirs()
    rid = "f13test00000000000000000000000000"
    root = run_dir_for(rid)
    traj = root / _TRAJ
    traj.parent.mkdir(parents=True, exist_ok=True)
    return rid, root, traj


def _write(traj: Path, lines: list[dict]) -> None:
    traj.write_text(
        "".join(json.dumps(rec, ensure_ascii=False) + "\n" for rec in lines), encoding="utf-8"
    )


def _finish(root: Path) -> None:
    (root / "summary.json").write_text("{}", encoding="utf-8")


async def _drain(gen) -> list[tuple[int, dict]]:
    out: list[tuple[int, dict]] = []
    async for item in gen:
        out.append(item)
    return out


async def test_tail_incremental_yields_exact_line_numbers(run_dir):
    rid, root, traj = run_dir
    lines = [{"t": "start"}] + [{"t": "llm", "turn": i} for i in range(1, 4)] + [{"t": "end"}]
    _write(traj, lines)
    _finish(root)
    got = await _drain(relay.trajectory_tail(rid, after_line=0))
    assert [n for n, _ in got] == list(range(1, len(lines) + 1))
    assert [r["t"] for _, r in got] == ["start", "llm", "llm", "llm", "end"]


async def test_tail_resumes_from_after_line_cursor(run_dir):
    rid, root, traj = run_dir
    _write(traj, [{"t": "start"}, {"t": "llm", "turn": 1}, {"t": "result", "name": "x"}, {"t": "end"}])
    _finish(root)
    got = await _drain(relay.trajectory_tail(rid, after_line=2))
    assert [n for n, _ in got] == [3, 4]
    assert [r["t"] for _, r in got] == ["result", "end"]


async def test_tail_defers_broken_line_until_newline(run_dir):
    rid, root, traj = run_dir
    traj.write_text('{"t":"start"}\n{"t":"llm","turn":1}', encoding="utf-8")
    gen = relay.trajectory_tail(rid, after_line=0)
    first = await gen.__anext__()
    assert first == (1, {"t": "start"})
    # Let the tail run several poll rounds while the last line is still broken
    # (no newline). A non-deferring implementation would have consumed the
    # partial bytes during those polls; the deferring one parks the offset just
    # past line 1 and re-reads the tail on every poll without consuming it.
    #
    # NOTE: this must NOT be verified with ``wait_for(gen.__anext__, ...)`` —
    # a timeout there cancels ``__anext__`` and injects CancelledError into the
    # generator at its sleep point, terminating it (the next ``__anext__`` then
    # raises StopAsyncIteration). Only a real sleep exercises the defer path.
    await asyncio.sleep(0.55)
    # Complete the broken line; the incremental read picks it up on the next poll.
    with traj.open("a", encoding="utf-8") as fh:
        fh.write("\n")
    second = await gen.__anext__()
    assert second == (2, {"t": "llm", "turn": 1})
    # Terminate the stream.
    _finish(root)
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()


async def test_tail_terminal_drain_reads_parseable_tail_without_newline(run_dir):
    rid, root, traj = run_dir
    # A complete file whose last record has no trailing newline must still emit
    # it (old iterator semantics).
    traj.write_text('{"t":"start"}\n{"t":"end"}', encoding="utf-8")
    _finish(root)
    got = await _drain(relay.trajectory_tail(rid, after_line=0))
    assert got == [(1, {"t": "start"}), (2, {"t": "end"})]


def test_page_bounds_records_and_carries_resume_cursor(run_dir):
    rid, _root, traj = run_dir
    _write(traj, [{"t": "llm", "turn": i} for i in range(25)])
    page1, next_line, has_more = relay.trajectory_page(rid, after_line=0, limit=10)
    assert len(page1) == 10 and has_more and next_line == 10
    page2, next2, more2 = relay.trajectory_page(rid, after_line=next_line, limit=10)
    assert len(page2) == 10 and more2 and next2 == 20
    page3, next3, more3 = relay.trajectory_page(rid, after_line=next2, limit=10)
    assert len(page3) == 5 and not more3 and next3 == 25
    assert page1[0]["turn"] == 0 and page3[-1]["turn"] == 24, "no overlap/gap across pages"


def test_page_unlimited_keeps_historical_contract(run_dir):
    rid, _root, traj = run_dir
    _write(traj, [{"t": "llm", "turn": i} for i in range(5)])
    records, _next_line, has_more = relay.trajectory_page(rid, after_line=0, limit=0)
    assert len(records) == 5 and not has_more


async def test_subscriber_queue_bounded_drops_deltas_preserves_terminal(run_dir):
    orch = Orchestrator()
    rid, _, _ = run_dir
    q = orch.subscribe(rid)
    assert q.maxsize == 256
    for i in range(q.maxsize + 50):
        orch._publish(rid, {"type": "assistant_delta", "i": i})
    await asyncio.sleep(0.05)
    assert q.qsize() <= q.maxsize, "delta flood must not grow the queue past the cap"
    # Terminal events are never dropped, even on a full queue.
    orch._publish(rid, {"type": "run_completed", "final_answer": "ok"})
    await asyncio.sleep(0.05)
    found = False
    while not q.empty():
        ev = q.get_nowait()
        if ev is not None and ev.get("type") == "run_completed":
            found = True
    if not found:
        await asyncio.sleep(0.05)
        while not q.empty():
            ev = q.get_nowait()
            if ev is not None and ev.get("type") == "run_completed":
                found = True
    assert found, "terminal event lost to backpressure"
    orch.unsubscribe(rid, q)


async def test_sentinel_delivered_on_full_queue(run_dir):
    orch = Orchestrator()
    rid, _, _ = run_dir
    q = orch.subscribe(rid)
    for i in range(q.maxsize + 10):
        orch._publish(rid, {"type": "assistant_delta", "i": i})
    orch._close_streams(rid)
    await asyncio.sleep(0.05)
    seen = False
    while not q.empty():
        if q.get_nowait() is None:
            seen = True
    if not seen:
        await asyncio.sleep(0.05)
        while not q.empty():
            if q.get_nowait() is None:
                seen = True
    assert seen, "end-of-stream sentinel lost to backpressure"
    orch.unsubscribe(rid, q)
