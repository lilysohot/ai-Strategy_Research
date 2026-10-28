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
    # A mixed batch is not an all-or-nothing failure: the caller already paid
    # for the items that succeeded (one live batch returned 17K usable chars
    # while the envelope only said ok=false, which invites a full re-buy).
    # Name both sides so the model can keep the good half and change route for
    # the rest instead of repeating the same URLs.
    succeeded = [
        str(item.get("source") or "")
        for item in items
        if item.get("ok") is True and str(item.get("content") or "").strip()
    ]
    failed = [
        str(item.get("source") or "")
        for item in items
        if str(item.get("source") or "") not in succeeded
    ]
    return ToolOutcome(
        json.dumps(
            {
                "ok": False,
                "status": "partial" if succeeded else "unavailable",
                "acquired_count": len(succeeded),
                "failed_count": len(failed),
                "succeeded": succeeded,
                "failed": failed,
                "items": items,
                "advice": (
                    "Use the succeeded sources; do not re-fetch this whole batch. "
                    "For the failed ones, change route (site API, PDF, archive) "
                    "instead of repeating the same URL."
                    if succeeded
                    else "No source in this batch produced content. Switch to "
                    "different sources instead of retrying these URLs."
                ),
            },
            ensure_ascii=False,
        ),
        is_error=True,
    )
