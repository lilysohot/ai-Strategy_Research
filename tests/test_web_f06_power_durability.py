"""F06 power durability: what a power cut leaves behind, and what survives it.

A real power cut cannot be injected on this host; its *filesystem aftermath*
can, and that is what this suite fixes. Two halves:

**Aftermath replay** — the file states a power cut is known to leave (truncated
JSONL tail, zero-byte summary whose rename survived while its content did not,
corrupt JSON) must degrade readably, not 500. The completeness taxonomy
(COMPLETE/PARTIAL/UNAVAILABLE + corrupt/partial counters) was built for exactly
this in F06; these cases pin the consumer side (``_read_run_summary`` and
``inspect_trajectory``).

**Durability write path** — ``worker.persist_summary`` now fsyncs the tmp file
before the rename and the directory entry after it, plus one terminal fsync of
the trajectory (the runtime streams deltas without fsync; a cut may lose the
last unflushed deltas — that is the PARTIAL contract — but must not lose the
whole file). fsync failures are best-effort: a platform without fsync must
still produce a correct summary (mirrors the observer-close tolerance test in
test_web_f06_trace_completeness.py).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from server import worker
from server.orchestrator import _read_run_summary
from server.trajectory_status import inspect_trajectory

TRAJ_RELPATH = Path("run/agent/trajectories/react_agent.jsonl")


@pytest.fixture
def run_root(tmp_path) -> Path:
    root = tmp_path / "runs" / ("f06power0000000000000000000000000000")
    (root / TRAJ_RELPATH).parent.mkdir(parents=True)
    return root


def _records(root: Path, n: int) -> None:
    traj = root / TRAJ_RELPATH
    with traj.open("w", encoding="utf-8") as fh:
        for i in range(n):
            fh.write(json.dumps({"t": "llm", "turn": i}) + "\n")


# --- aftermath replay: degraded-but-readable consumers -----------------------


def test_truncated_tail_is_partial_and_counted(run_root):
    """A cut mid-write leaves a half line; earlier records must survive."""
    _records(run_root, 3)
    with (run_root / TRAJ_RELPATH).open("a", encoding="utf-8") as fh:
        fh.write('{"t": "llm", "turn": 3, "content": "half-wri')  # no newline
    insp = inspect_trajectory(run_root)
    assert insp.state.value == "partial"
    assert insp.valid_lines == 3
    assert insp.trailing_partial_line is True


def test_zero_byte_summary_reads_as_no_data(run_root):
    """Cut after the rename but before the content hit disk → 0-byte summary."""
    _records(run_root, 2)
    (run_root / "summary.json").write_bytes(b"")
    assert _read_run_summary(run_root) == {}


def test_corrupt_summary_reads_as_no_data(run_root):
    _records(run_root, 2)
    (run_root / "summary.json").write_text('{"run_id": "cut', encoding="utf-8")
    assert _read_run_summary(run_root) == {}


def test_missing_summary_and_missing_trajectory_degrade(run_root):
    assert _read_run_summary(run_root) == {}
    assert inspect_trajectory(run_root).state.value == "unavailable"


# --- durability write path ----------------------------------------------------


def test_persist_summary_is_durable_and_cleans_tmp(run_root):
    _records(run_root, 2)
    worker.persist_summary(
        run_root, {"run_id": "f06power", "final_answer": "ok", "error": ""}
    )
    summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    assert summary["run_id"] == "f06power"
    assert not (run_root / "summary.json.tmp").exists()


def test_persist_summary_survives_a_platform_without_fsync(
    run_root, monkeypatch
):
    """fsync raising OSError must not prevent the summary from being written."""
    _records(run_root, 1)

    def boom(fd):
        raise OSError("no fsync here")

    monkeypatch.setattr(os, "fsync", boom)
    worker.persist_summary(run_root, {"run_id": "f06power"})
    assert json.loads((run_root / "summary.json").read_text(encoding="utf-8"))[
        "run_id"
    ] == "f06power"


def test_persist_summary_swallows_write_errors(run_root, monkeypatch):
    """A failing rename (ENOSPC et al.) is logged, never raised to the run."""
    _records(run_root, 1)

    def fail_write(self, data, encoding="utf-8"):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "write_text", fail_write)
    worker.persist_summary(run_root, {"run_id": "f06power"})  # must not raise
    assert not (run_root / "summary.json").exists()


def test_persist_summary_without_trajectory(run_root):
    """A run that produced no trajectory (jsonl disabled) still gets a summary."""
    worker.persist_summary(run_root, {"run_id": "f06power"})
    assert (run_root / "summary.json").exists()
