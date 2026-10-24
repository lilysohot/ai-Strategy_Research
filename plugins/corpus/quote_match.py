"""Locate citations without losing original source code-point offsets."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

# Only one-to-one typographic space substitutions are permitted. Do not use
# NFKC, strip whitespace, fold line breaks, or normalize punctuation/numbers.
_SPACE_MAP = str.maketrans({"\u00a0": " ", "\u202f": " "})


@dataclass(frozen=True, slots=True)
class QuoteMatch:
    start: int
    end: int
    text: str
    kind: str


def find_quote_matches(source: str, quote: str) -> Iterator[QuoteMatch]:
    """Return original spans for exact or narrowly space-equivalent citations."""
    if not quote:
        return
    haystack = source.translate(_SPACE_MAP)
    needle = quote.translate(_SPACE_MAP)
    offset = haystack.find(needle)
    while offset >= 0:
        end = offset + len(quote)
        original = source[offset:end]
        yield QuoteMatch(offset, end, original, "exact" if original == quote else "unicode_space")
        offset = haystack.find(needle, offset + 1)
