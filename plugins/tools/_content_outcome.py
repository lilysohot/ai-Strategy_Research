"""Explicit acquisition limits, serializable in both live tools and trace replay."""

from __future__ import annotations

import json
from typing import Any, Literal

from frontier_agent.core.tool import ToolOutcome


def content_limitation(
    source: str,
    detail: str,
    *,
    status: Literal["unavailable", "failed", "policy_blocked", "partial"] = "unavailable",
    content: str = "",
    coverage: dict[str, Any] | None = None,
) -> ToolOutcome:
    """Keep usable partial text while refusing to label acquisition complete."""
    payload: dict[str, Any] = {
        "ok": False,
        "status": status,
        "source": source,
        "content": content,
        "detail": detail,
    }
    if coverage is not None:
        payload["coverage"] = coverage
    return ToolOutcome(json.dumps(payload, ensure_ascii=False), is_error=True)


def combine_content_outcomes(
    sources: list[str], results: list[str | ToolOutcome]
) -> ToolOutcome | None:
    """Return an itemized partial/failure envelope; leave all-success text unchanged."""
    if not any(isinstance(result, ToolOutcome) for result in results):
        return None
    items = [
        json.loads(result.result)
        if isinstance(result, ToolOutcome)
        else {"ok": True, "status": "success", "source": source, "content": result}
        for source, result in zip(sources, results, strict=True)
    ]
    return ToolOutcome(
        json.dumps(
            {
                "ok": False,
                "status": "partial"
                if any(item.get("content") for item in items)
                else "unavailable",
                "items": items,
            },
            ensure_ascii=False,
        ),
        is_error=True,
    )
