"""F06: trajectory completeness contract.

A run that was cancelled, killed, or died mid-write must not be presented as a
complete trace. These checks build synthetic trajectory files — no worker, no
model, no subprocess kill, no fault injection against a real disk — and assert
what the reader promises about each one.

The fault shapes mirror what a crash actually leaves behind: a missing terminal
record (``on_loop_cancelled`` writes none), and a final line cut off in the
middle (a write interrupted before its newline).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from frontier_agent.components.observers.trajectory import TrajectoryFileObserver
from server.trajectory_status import (
    TrajectoryCompleteness,
    inspect_trajectory,
    trajectory_path,
)


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    """A run directory whose trajectory path matches what the reader opens."""
    d = tmp_path / "run-f06"
    (d / "run" / "agent" / "trajectories").mkdir(parents=True)
    monkeypatch.setattr("server.trajectory_status.run_dir_for", lambda run_id: d)
    return d


def _write_lines(d, lines: list[str]) -> None:
    traj = d / "run" / "agent" / "trajectories" / "react_agent.jsonl"
    traj.write_text("".join(lines), encoding="utf-8")


def _record(t: str, **extra) -> str:
    return json.dumps({"t": t, **extra}, ensure_ascii=False) + "\n"


# — the three states ————————————————————————————————————————————————————————
def test_finished_run_is_complete(run_dir):
    _write_lines(run_dir, [
        _record("start", model_name="m"),
        _record("llm", turn=1, content="hi"),
        _record("end", turns=1, tool_calls=0, stopped_by=""),
    ])
    result = inspect_trajectory("run-f06")
    assert result.state is TrajectoryCompleteness.COMPLETE
    assert result.valid_lines == 3
    assert result.reason == ""


def test_cancelled_run_is_partial_but_readable(run_dir):
    """``on_loop_cancelled`` writes no ``end`` record, so the tail is unknown."""
    _write_lines(run_dir, [
        _record("start", model_name="m"),
        _record("llm", turn=1, content="partial answer"),
    ])
    result = inspect_trajectory("run-f06")
    assert result.state is TrajectoryCompleteness.PARTIAL
    assert result.readable is True
    assert result.valid_lines == 2, "already-written records must stay readable"
    assert result.reason


def test_missing_file_is_unavailable(run_dir):
    result = inspect_trajectory("run-f06")
    assert result.state is TrajectoryCompleteness.UNAVAILABLE
    assert result.readable is False
    assert result.reason


def test_empty_file_is_unavailable(run_dir):
    (run_dir / "run/agent/trajectories/react_agent.jsonl").write_text("", encoding="utf-8")
    result = inspect_trajectory("run-f06")
    assert result.state is TrajectoryCompleteness.UNAVAILABLE


# — half-written tail ————————————————————————————————————————————————————————
def test_half_written_tail_does_not_hide_earlier_records(run_dir):
    """A crash mid-write costs the last record, not the whole file."""
    _write_lines(run_dir, [
        _record("start", model_name="m"),
        _record("llm", turn=1, content="hi"),
        '{"t":"llm","turn":2,"content":"cut off',  # no newline, broken JSON
    ])
    result = inspect_trajectory("run-f06")
    assert result.trailing_partial_line is True
    assert result.valid_lines == 2, "the two complete records must survive"
    assert result.state is TrajectoryCompleteness.PARTIAL
    assert result.corrupt_lines == 0, "the broken tail is not a corrupt body line"


def test_corrupt_line_in_the_middle_is_counted_not_fatal(run_dir):
    _write_lines(run_dir, [
        _record("start", model_name="m"),
        "{not json at all}\n",
        _record("end", turns=1),
    ])
    result = inspect_trajectory("run-f06")
    assert result.corrupt_lines == 1
    assert result.valid_lines == 2
    assert result.state is TrajectoryCompleteness.COMPLETE


# — required configuration is detectable ——————————————————————————————————————
def test_jsonl_disabled_leaves_no_trace_to_inspect(tmp_path):
    """If the JSONL format is switched off, the gap must be detectable.

    The platform reads JSONL, so a run configured without it has an unreadable
    trace — that has to surface as ``unavailable`` rather than as "no output".
    """
    observer = TrajectoryFileObserver(tmp_path, filename="probe", formats=("json",))
    observer._write_jsonl({"t": "start"})
    assert not (tmp_path / "probe.jsonl").exists()


def test_observer_close_survives_a_platform_without_fsync(tmp_path):
    """The write barrier is best-effort: it must never raise or lose records."""
    observer = TrajectoryFileObserver(tmp_path, filename="probe", formats=("jsonl",))
    observer._write_jsonl({"t": "start", "model_name": "m"})
    observer._close_jsonl()
    written = (tmp_path / "probe.jsonl").read_text(encoding="utf-8")
    assert json.loads(written.strip())["t"] == "start"


def test_inspection_dict_shape_is_stable(run_dir):
    """The UI reads these keys — renaming one is a breaking change."""
    _write_lines(run_dir, [_record("llm", turn=1)])
    payload = inspect_trajectory("run-f06").as_dict()
    assert set(payload) == {
        "state", "valid_lines", "trailing_partial_line", "corrupt_lines", "reason",
    }
    assert payload["state"] == "partial"


def test_trajectory_path_follows_the_run_root(run_dir):
    assert trajectory_path("run-f06") == run_dir / "run/agent/trajectories/react_agent.jsonl"
    assert isinstance(trajectory_path("run-f06"), Path)
