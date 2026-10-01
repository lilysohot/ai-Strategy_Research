"""F06 request-attempt identity: failed/retried LLM attempts become auditable.

Contract level frozen (the open decision on the F06 ticket): **summary-only**.
Every provider attempt — including the ones that fail and get retried — leaves
ONE identity line (``t:"attempt"``: turn / call_id / attempt_index / phase /
outcome / error_type / duration / usage) in the trajectory JSONL, so "all
successful turns are saved" stops being the only story an auditor can read.
Request/response bodies are deliberately NOT persisted (they can be huge and
have no UI), and the JSON envelope is untouched.

Egress stays unchanged: attempt lines occupy a physical line number (the T3.1
cursor arithmetic stays exact) but are filtered from the SSE replay, from
``/trace`` pagination, and they never affect completeness (only ``end`` is
terminal).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from frontier_agent.components.observers.trajectory import TrajectoryFileObserver
from frontier_agent.core.loop_types import LLMAttemptContext
from server.relay import _traj_record_to_events, trajectory_page
from server.trajectory_status import inspect_trajectory

RUN = "f06attempt0000000000000000000000000000"


@pytest.fixture
def traj_path(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr("server.relay.run_dir_for", lambda rid: tmp_path / "runs" / rid)
    run_dir = tmp_path / "runs" / RUN
    traj = run_dir / "run" / "agent" / "trajectories"
    traj.mkdir(parents=True)
    return traj / "react_agent.jsonl"


def _attempt(turn: int, index: int, **kw) -> LLMAttemptContext:
    base = dict(
        turn=turn, max_turns=8, task_id="t", role_id="main",
        call_id=f"call_{turn}", attempt_id=f"call_{turn}_attempt_{index:02d}",
        attempt_index=index, phase="failed", outcome="retry",
        reason="provider 429", error_type="RateLimitError", duration_ms=1200,
    )
    base.update(kw)
    return LLMAttemptContext(**base)


async def test_failed_attempts_are_persisted_with_identity(traj_path):
    obs = TrajectoryFileObserver(
        traj_path.parent, filename="react_agent", formats=("jsonl",),
    )
    assert traj_path.exists() is False  # the attempt must CREATE the file too
    await obs.on_llm_attempt(_attempt(3, 1))
    await obs.on_llm_attempt(_attempt(3, 2, error_type="", reason=""))
    obs._close_jsonl()
    lines = [json.loads(x) for x in traj_path.read_text(encoding="utf-8").splitlines()]
    assert [r["t"] for r in lines] == ["attempt", "attempt"]
    first = lines[0]
    assert first["attempt_index"] == 1 and first["outcome"] == "retry"
    assert first["error_type"] == "RateLimitError"
    assert first["duration_ms"] == 1200 and first["reason"].startswith("provider 429")
    assert "content" not in first and "messages" not in first  # summary-only


def _write(traj_path: Path, records: list[dict]) -> None:
    traj_path.write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8",
    )


def _run_root(traj_path: Path) -> Path:
    # .../run/agent/trajectories/react_agent.jsonl → the run dir itself.
    return traj_path.parent.parent.parent.parent


def test_attempt_lines_do_not_affect_completeness(traj_path):
    # attempt + end → complete; attempt without end → partial (unchanged rules).
    _write(traj_path, [{"t": "attempt", "turn": 1}, {"t": "end"}])
    assert inspect_trajectory(_run_root(traj_path)).state.value == "complete"
    _write(traj_path, [{"t": "attempt", "turn": 1}])
    assert inspect_trajectory(_run_root(traj_path)).state.value == "partial"


def test_attempt_lines_are_filtered_from_egress_but_keep_the_cursor(traj_path):
    traj_path.write_text(
        '{"t": "llm", "turn": 1, "content": "a"}\n'
        '{"t": "attempt", "turn": 1, "attempt_index": 1, "outcome": "retry"}\n'
        '{"t": "llm", "turn": 2, "content": "b"}\n',
        encoding="utf-8",
    )
    # /trace pagination: physical line numbers count attempt lines, but the
    # records returned never include them.
    records, next_line, has_more = trajectory_page(RUN, after_line=0, limit=2)
    assert [r.get("t") for r in records] == ["llm", "llm"]
    assert next_line == 3 and has_more is False  # cursor counts the attempt line
    # SSE mapping: no event, and no bogus "unknown traj record" warning.
    assert _traj_record_to_events({"t": "attempt", "turn": 1}) == []


def test_real_turns_are_untouched(traj_path):
    traj_path.write_text('{"t": "llm", "turn": 1, "content": "x"}\n', encoding="utf-8")
    events = _traj_record_to_events({"t": "llm", "turn": 1, "content": "x"}, seq=1)
    assert events and events[0]["type"] == "assistant_delta"
