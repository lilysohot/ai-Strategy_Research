"""Publication-date constraints shared by tool and retrieval boundaries."""

from __future__ import annotations

from datetime import date
from typing import Any, TypedDict

PUBLICATION_BASES = frozenset({"reviewed_metadata", "admission"})


class PublicationDateOptions(TypedDict, total=False):
    published_from: str | None
    published_to: str | None


def validate_range(start: str | None, end: str | None) -> None:
    """Accept only ISO calendar dates and an inclusive, ordered interval."""
    for name, value in (("published_from", start), ("published_to", end)):
        if value is None:
            continue
        try:
            if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a valid YYYY-MM-DD publication date") from exc
    if start is not None and end is not None and start > end:
        raise ValueError("published_from must not be after published_to")


def publication_matches(record: dict[str, Any], start: str | None, end: str | None) -> bool:
    """Filename guesses never satisfy an explicit publication constraint."""
    value = record.get("date")
    if record.get("basis") not in PUBLICATION_BASES or not value:
        return False
    try:
        validate_range(value, value)
    except ValueError:
        return False
    return (start is None or value >= start) and (end is None or value <= end)
