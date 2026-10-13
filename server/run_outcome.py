"""Translate engine exit reasons into Web interruption semantics."""

from __future__ import annotations


def interruption_reason(reason: str | None) -> str:
    """A text-only ``no_tool`` finish is normal, not an interrupted answer.

    Keep unknown reasons conservative. Errors are checked separately by the
    caller, so this never promotes a failed worker to a successful run.
    """
    return "" if reason == "no_tool" else reason or ""


def is_legacy_normal_completion(status: str, reason: str | None, error: str | None) -> bool:
    """Recognize old rows misclassified before normal exits were distinguished."""
    return status in {"stopped", "completed"} and reason == "no_tool" and not error
