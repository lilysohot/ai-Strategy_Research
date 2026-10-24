"""Translate engine exit reasons into Web interruption semantics."""

from __future__ import annotations


def interruption_reason(reason: str | None) -> str:
    """Recognize natural single-agent and team completion markers.

    Keep unknown reasons conservative. Errors are checked separately by the
    caller, so this never promotes a failed worker to a successful run.
    """
    return "" if reason in {"no_tool", "final_answer"} else reason or ""


def is_legacy_normal_completion(status: str, reason: str | None, error: str | None) -> bool:
    """Recognize old rows misclassified before normal exits were distinguished."""
    return status in {"stopped", "completed"} and reason == "no_tool" and not error
