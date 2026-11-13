"""Dependency-light shared vocabulary for task-board producers and views."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import NamedTuple

#: Tools whose successful completion can change the task rows shown by a board
#: projection. Planning-phase transitions do not change row state and therefore
#: intentionally stay outside this set.
BOARD_TOOLS = frozenset({"add_task", "update_task"})

#: The single source of truth for valid resolutions and their display glyphs.
#: Keep insertion order stable because ``VALID_RESOLUTION`` is also rendered in
#: validation errors.
RESOLUTION_MARKS: dict[str, str] = {
    "open": "○",
    "in_progress": "▶",
    "resolved": "✓",
    "cancelled": "⊘",
    "blocked": "!",
}
VALID_RESOLUTION = tuple(RESOLUTION_MARKS)

#: Resolutions that end a task's work. ``blocked`` keeps a gap; ``cancelled``
#: retracts the work (nothing is owed); ``resolved`` claims it is answered.
TERMINAL_RESOLUTIONS: frozenset[str] = frozenset({"resolved", "cancelled", "blocked"})

#: Resolutions a final delivery may declare. This MUST stay identical to the
#: board's terminal set: a task the coordinator already retracted with
#: ``update_task(resolution="cancelled")`` must not be forced into ``blocked``
#: (which records a gap and downgrades the whole answer) merely because the
#: delivery schema did not accept ``cancelled``.
FINAL_RESOLUTIONS: tuple[str, ...] = ("resolved", "cancelled", "blocked")


def task_is_required(task: dict[str, object]) -> bool:
    """True unless the board explicitly marked the item optional.

    Optional ("self-added enrichment") work may stay unfinished without turning
    the user's requested result into a partial answer. Anything not carrying an
    explicit ``required_for_completion=False`` is required — the conservative
    default, so a missing field can never waive an obligation.
    """
    return task.get("required_for_completion") is not False


class BoardCounts(NamedTuple):
    """Board tallies with the "cancelled is retracted" rule applied once."""

    total: int
    resolved: int
    in_progress: int
    open: int
    cancelled: int
    blocked: int = 0

    @property
    def active(self) -> int:
        """Denominator for the resolved ratio.

        Cancelled tasks are retracted, so they leave the denominator—a dropped
        task must not sit forever in the unresolved count.
        """
        return self.total - self.cancelled


def count_resolutions(resolutions: Iterable[str]) -> BoardCounts:
    """Tally resolutions, folding anything unrecognised into ``open``."""
    counts = Counter(
        resolution if resolution in RESOLUTION_MARKS else "open"
        for resolution in resolutions
    )
    return BoardCounts(
        total=sum(counts.values()),
        resolved=counts["resolved"],
        in_progress=counts["in_progress"],
        open=counts["open"],
        cancelled=counts["cancelled"],
        blocked=counts["blocked"],
    )


__all__ = [
    "BOARD_TOOLS",
    "FINAL_RESOLUTIONS",
    "RESOLUTION_MARKS",
    "TERMINAL_RESOLUTIONS",
    "VALID_RESOLUTION",
    "BoardCounts",
    "count_resolutions",
    "task_is_required",
]
