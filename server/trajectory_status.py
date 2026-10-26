"""Trajectory completeness contract (F06).

The runtime appends one JSONL line per turn and writes a terminal ``{"t":"end"}``
record in ``on_loop_end``. A run that was cancelled, SIGKILLed, or died mid-write
never gets that record, so "the file exists" is not the same as "the trace is
complete".

This module is the single place that answers *how much* of a trace can be trusted.
It is deliberately read-only: deriving the state from what is on disk keeps it
honest after a crash, where any in-memory "I finished" flag would be gone along
with the process.

What the three states mean:

- ``complete``   a terminal ``end`` record is present — the loop finished.
- ``partial``    records exist but no terminal marker: the run was cut short.
                 Everything already written is still readable; the *tail* is not
                 guaranteed to be the whole story.
- ``unavailable`` nothing readable — no file, empty, or unreadable.

Guarantees this module does NOT make:

- ``flush()`` is not ``fsync()``. Lines handed to the OS survive a process kill
  but not necessarily a power loss; see the write barrier in the observer.
- Streaming deltas shown live are not persisted. A turn interrupted mid-stream
  can be visible in the UI and absent here — that is a ``partial`` trace, not a
  lost one, and the UI must say so rather than implying completeness.
"""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from server.config import run_dir_for
from server.trajectory_sources import TrajectorySource, discover_trajectory_sources

# Kept in sync with the runtime writer (components/observers/trajectory.py).
_TRAJECTORY_RELPATH = "run/agent/trajectories/react_agent.jsonl"
_TERMINAL_RECORD_TYPES = frozenset({"end"})


class TrajectoryCompleteness(StrEnum):
    """How much of a run's trace survived."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class TrajectoryInspection:
    """Result of reading a run's trajectory for completeness."""

    state: TrajectoryCompleteness
    # Number of lines that parsed as JSON records.
    valid_lines: int = 0
    # True when the file ends mid-record (no trailing newline / broken JSON).
    trailing_partial_line: bool = False
    # Lines that could not be parsed, excluding the trailing partial one.
    corrupt_lines: int = 0
    # Why the state was chosen — shown to the user, so keep it human-readable.
    reason: str = ""
    # Present only for multi-file Agent Team traces. Keeping the single-file
    # payload unchanged preserves the original Web/API contract.
    sources: tuple[dict[str, object], ...] = ()

    @property
    def readable(self) -> bool:
        """True when there is anything at all to show."""
        return self.state is not TrajectoryCompleteness.UNAVAILABLE

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "state": str(self.state),
            "valid_lines": self.valid_lines,
            "trailing_partial_line": self.trailing_partial_line,
            "corrupt_lines": self.corrupt_lines,
            "reason": self.reason,
        }
        if self.sources:
            payload["sources"] = list(self.sources)
        return payload


def trajectory_path(run_id: str) -> Path:
    """Path of a run's JSONL trajectory."""
    return run_dir_for(run_id) / _TRAJECTORY_RELPATH


def _inspect_path(path: Path) -> TrajectoryInspection:
    """Inspect one JSONL stream without trusting any in-memory state.

    A half-written final line is reported as ``trailing_partial_line`` and never
    hides the records before it: every other line still parses, so a crash in the
    middle of a write costs the last record, not the whole file.
    """
    if not path.exists():
        return TrajectoryInspection(
            TrajectoryCompleteness.UNAVAILABLE,
            reason="轨迹文件不存在（运行可能未产生输出）",
        )

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return TrajectoryInspection(
            TrajectoryCompleteness.UNAVAILABLE,
            reason=f"轨迹文件不可读：{exc.strerror or exc}",
        )

    if not raw.strip():
        return TrajectoryInspection(
            TrajectoryCompleteness.UNAVAILABLE,
            reason="轨迹文件为空（运行尚未写入记录）",
        )

    lines = raw.split("\n")
    # A well-formed file ends with "\n", so the final split element is "".
    last_index = len(lines) - 1
    trailing_partial = False

    valid = 0
    corrupt = 0
    saw_terminal = False

    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            if index == last_index:
                trailing_partial = True
            else:
                corrupt += 1
            continue
        if not isinstance(record, dict):
            corrupt += 1
            continue
        valid += 1
        if record.get("t") in _TERMINAL_RECORD_TYPES:
            saw_terminal = True

    if valid == 0:
        state = TrajectoryCompleteness.UNAVAILABLE
        reason = "轨迹中没有可解析的记录"
    elif saw_terminal:
        state = TrajectoryCompleteness.COMPLETE
        reason = ""
    else:
        state = TrajectoryCompleteness.PARTIAL
        reason = "运行未正常结束，已保存的记录可读，但可能缺少最后一部分内容"

    return TrajectoryInspection(
        state=state,
        valid_lines=valid,
        trailing_partial_line=trailing_partial,
        corrupt_lines=corrupt,
        reason=reason,
    )


def _source_payload(
    source: TrajectorySource,
    inspection: TrajectoryInspection,
) -> dict[str, object]:
    return {
        "source": source.source,
        "agent_id": source.agent_id,
        "agent_kind": source.agent_kind,
        **inspection.as_dict(),
    }


def inspect_trajectory(run_id: str) -> TrajectoryInspection:
    """Classify the complete single- or multi-agent trajectory of one run.

    The coordinator stream is authoritative for the product run's terminal
    state. A member can be cancelled after its findings were collected without
    turning an otherwise completed team run into a false platform failure; its
    own partial state is still exposed in ``sources`` for audit.
    """
    run_dir = run_dir_for(run_id)
    sources = discover_trajectory_sources(run_dir)
    if not sources:
        return _inspect_path(trajectory_path(run_id))
    if len(sources) == 1 and sources[0].source == "react_agent":
        return _inspect_path(sources[0].path)

    inspected = [(source, _inspect_path(source.path)) for source in sources]
    source_payloads = tuple(_source_payload(source, result) for source, result in inspected)
    valid = sum(result.valid_lines for _, result in inspected)
    corrupt = sum(result.corrupt_lines for _, result in inspected)
    trailing = any(result.trailing_partial_line for _, result in inspected)
    authoritative = next(
        ((source, result) for source, result in inspected if source.authoritative),
        None,
    )

    if authoritative is None:
        if valid:
            state = TrajectoryCompleteness.PARTIAL
            reason = "团队轨迹缺少主 Agent 记录；已有成员记录仍可读取"
        else:
            state = TrajectoryCompleteness.UNAVAILABLE
            reason = "团队轨迹中没有可解析的记录"
    else:
        _source, main_result = authoritative
        state = main_result.state
        reason = main_result.reason
        if state is TrajectoryCompleteness.UNAVAILABLE and valid:
            state = TrajectoryCompleteness.PARTIAL
            reason = "主 Agent 轨迹不可读；已有团队成员记录仍可读取"

    return TrajectoryInspection(
        state=state,
        valid_lines=valid,
        trailing_partial_line=trailing,
        corrupt_lines=corrupt,
        reason=reason,
        sources=source_payloads,
    )


def fsync_directory(path: Path) -> None:
    """Best-effort fsync of a directory so a new file's entry is durable.

    Only meaningful on POSIX; Windows raises or no-ops depending on the handle,
    so failures are swallowed — this is a barrier, not a guarantee.
    """
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    with contextlib.suppress(OSError):
        os.fsync(fd)
    with contextlib.suppress(OSError):
        os.close(fd)
