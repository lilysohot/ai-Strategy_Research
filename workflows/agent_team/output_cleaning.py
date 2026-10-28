"""Remove unexecuted team-control syntax at both terminal output paths."""

from __future__ import annotations

import re

_FENCED = re.compile(r"(```[^\n]*\n[\s\S]*?```|~~~[^\n]*\n[\s\S]*?~~~)")
_CONTROL = re.compile(
    r"<\s*(update_task|add_task|assign_task|create_subagent|collect_reports|"
    r"stop_subagent|submit_report|finalize_answer)\s*>[\s\S]*?</\s*\1\s*>",
    re.IGNORECASE,
)


def strip_team_control(text: str) -> str:
    """Never execute leaked markup; preserve fenced examples in explanations."""
    parts = _FENCED.split(text)
    return "".join(
        part if i % 2 else _CONTROL.sub("", part) for i, part in enumerate(parts)
    ).strip()
