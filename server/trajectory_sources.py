"""Locate and merge the trajectory files produced by one product run.

Single-Agent writes ``react_agent.jsonl``. Agent Team writes one coordinator
file, an optional planning file, and one file per member task.  The Web replay
surface consumes both layouts through this module so status inspection, paging,
and SSE reconnect cannot disagree about which files belong to the run.
"""

from __future__ import annotations

import heapq
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_TRACE_RELPATH = Path("run/agent/trajectories")
_TASK_SUFFIX = re.compile(r"\.t\d+$")


@dataclass(frozen=True)
class TrajectorySource:
    """One append-only JSONL stream and its stable Agent identity."""

    source: str
    path: Path
    agent_id: str
    agent_kind: str
    role_id: str
    authoritative: bool = False


def trajectory_root(run_dir: Path) -> Path:
    return run_dir / _TRACE_RELPATH


def discover_trajectory_sources(run_dir: Path) -> tuple[TrajectorySource, ...]:
    """Return the run's existing trajectory files in a deterministic order.

    Team files take precedence if any are present. This avoids accidentally
    mixing a stale legacy ``react_agent.jsonl`` into a team replay when a run
    directory was recovered or copied from an older build.
    """
    root = trajectory_root(run_dir)
    main = root / "main_agent.jsonl"
    planning = root / "main_planning.jsonl"
    members = sorted((root / "subagents").glob("*.jsonl"))
    if main.exists() or planning.exists() or members:
        sources: list[TrajectorySource] = []
        if planning.exists():
            sources.append(
                TrajectorySource(
                    source="main_planning",
                    path=planning,
                    agent_id="agent_team_main",
                    agent_kind="coordinator",
                    role_id="agent_team_main",
                )
            )
        if main.exists():
            sources.append(
                TrajectorySource(
                    source="main_agent",
                    path=main,
                    agent_id="agent_team_main",
                    agent_kind="coordinator",
                    role_id="agent_team_main",
                    authoritative=True,
                )
            )
        for path in members:
            stem = _TASK_SUFFIX.sub("", path.stem)
            sources.append(
                TrajectorySource(
                    source=f"subagents/{path.stem}",
                    path=path,
                    agent_id=stem,
                    agent_kind="subagent",
                    role_id="agent_team_sub",
                )
            )
        return tuple(sources)

    legacy = root / "react_agent.jsonl"
    if legacy.exists():
        return (
            TrajectorySource(
                source="react_agent",
                path=legacy,
                agent_id="react_agent",
                agent_kind="single",
                role_id="stateful_react",
                authoritative=True,
            ),
        )
    return ()


def annotate_record(
    record: dict[str, Any],
    source: TrajectorySource,
    source_line: int,
) -> dict[str, Any]:
    """Attach identity needed to distinguish equal turn/call ids across agents."""
    enriched = dict(record)
    enriched.setdefault("agent_id", source.agent_id)
    enriched.setdefault("agent_kind", source.agent_kind)
    enriched.setdefault("role_id", source.role_id)
    enriched["trajectory_source"] = source.source
    enriched["source_line"] = source_line
    return enriched


def _sort_key(
    record: dict[str, Any],
    source: TrajectorySource,
    source_line: int,
) -> tuple[int, float, str, int]:
    raw_ts = record.get("ts")
    if isinstance(raw_ts, (int, float)) and not isinstance(raw_ts, bool):
        return (0, float(raw_ts), source.source, source_line)
    # Runtime records always carry ts. This deterministic fallback keeps old or
    # hand-authored traces replayable without pretending to know their timing.
    return (1, 0.0, source.source, source_line)


def iter_source_records(
    source: TrajectorySource,
    *,
    start_offset: int = 0,
    start_line: int = 0,
    terminal: bool = True,
) -> Iterator[tuple[tuple[int, float, str, int], dict[str, Any], int]]:
    """Yield valid records after a byte offset and the next committed offset.

    An unterminated final line is deferred while the run is live. On terminal
    drain, a complete JSON value without a newline is accepted, matching the
    historical single-file tail behavior.
    """
    try:
        size = source.path.stat().st_size
        offset = start_offset if start_offset <= size else 0
        with source.path.open("rb") as handle:
            handle.seek(offset)
            source_line = start_line if offset else 0
            # Freeze this read at the size observed on entry. Without this, a
            # source appended while the merged generator is paused can slip
            # ahead of a newly-created member file that the next poll has not
            # discovered yet, making reconnect rebuild a different cursor order.
            while handle.tell() < size:
                before = handle.tell()
                raw = handle.readline(size - before)
                if not raw:
                    return
                complete = raw.endswith(b"\n")
                if not complete and not terminal:
                    return
                source_line += 1
                next_offset = handle.tell() if complete or terminal else before
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                enriched = annotate_record(record, source, source_line)
                yield _sort_key(enriched, source, source_line), enriched, next_offset
    except OSError:
        return


def iter_merged_records(
    sources: tuple[TrajectorySource, ...],
    *,
    offsets: dict[Path, int] | None = None,
    line_numbers: dict[Path, int] | None = None,
    terminal: bool = True,
) -> Iterator[tuple[dict[str, Any], Path, int]]:
    """K-way merge source streams without materialising the full trajectory."""
    cursors = offsets if offsets is not None else {}
    lines = line_numbers if line_numbers is not None else {}
    heap: list[
        tuple[
            tuple[int, float, str, int],
            int,
            dict[str, Any],
            int,
            Iterator[tuple[tuple[int, float, str, int], dict[str, Any], int]],
        ]
    ] = []
    for index, source in enumerate(sources):
        iterator = iter_source_records(
            source,
            start_offset=cursors.get(source.path, 0),
            start_line=lines.get(source.path, 0),
            terminal=terminal,
        )
        try:
            key, record, next_offset = next(iterator)
        except StopIteration:
            continue
        heapq.heappush(heap, (key, index, record, next_offset, iterator))

    while heap:
        _key, index, record, next_offset, iterator = heapq.heappop(heap)
        source = sources[index]
        cursors[source.path] = next_offset
        lines[source.path] = int(record["source_line"])
        yield record, source.path, next_offset
        try:
            key, following, following_offset = next(iterator)
        except StopIteration:
            continue
        heapq.heappush(
            heap,
            (key, index, following, following_offset, iterator),
        )
