"""Compare candidate excerpts with captured tool evidence, never model copies."""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr


class QuoteCheck(BaseModel):
    """An excerpt in the bound candidate and its already captured source locator."""

    model_config = ConfigDict(extra="forbid")
    source_key: StrictStr = Field(description="Exact key of a bound evidence job/ref.")
    locator: StrictStr = Field(description="Exact captured corpus locator or web source URL.")
    quote: StrictStr = Field(
        min_length=1,
        max_length=8000,
        description="Exact excerpt present in subject.text; never supply source text.",
    )
    mode: Literal["exact", "nbsp_space"] = Field(
        default="exact",
        description="exact requires raw character equality. nbsp_space permits ONLY NBSP/space "
        "display normalization; it does not certify raw equality or equal hashes. Neither mode "
        "changes dates, numbers, words, line breaks or duplicate OCR lines.",
    )


def compare_quotes(
    checks: list[QuoteCheck],
    subject: str,
    sources: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Deterministic receipts bound into the same candidate/evidence identity."""
    comparisons = []
    for check in checks:
        if check.quote not in subject:
            raise ValueError("quote check must refer to an excerpt in the bound subject")
        records = sources.get(check.source_key)
        if records is None:
            raise ValueError("quote check source_key is not bound evidence")
        texts = {
            record["text"]
            for record in records
            if check.locator
            in {record.get("locator"), record.get("source"), record.get("evidence_ref")}
            and isinstance(record.get("text"), str)
        }
        if len(texts) != 1:
            raise ValueError("quote check requires one unambiguous captured source locator")
        original = texts.pop()
        raw_match = check.quote in original
        normalized_match = check.quote.replace("\u00a0", " ") in original.replace("\u00a0", " ")
        comparisons.append(
            {
                **check.model_dump(),
                "source_text_sha256": hashlib.sha256(original.encode()).hexdigest(),
                "quote_sha256": hashlib.sha256(check.quote.encode()).hexdigest(),
                "raw_match": raw_match,
                "normalized_match": normalized_match,
                "matched": raw_match if check.mode == "exact" else normalized_match,
                "basis": "captured_tool_text",
            }
        )
    return comparisons


def validate_quotes(check: dict[str, Any]) -> None:
    """A prose/model PASS cannot override a failed deterministic quote check."""
    for comparison in check.get("quote_comparisons", []):
        if comparison.get("basis") != "captured_tool_text" or comparison.get("matched") is not True:
            raise ValueError(
                "quote comparison failed; correct the candidate or report fail/unchecked"
            )
