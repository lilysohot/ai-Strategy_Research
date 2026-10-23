"""Native search evidence wire contract, shared by delivery and consumption.

The producer has already verified raw units. These descriptors bind the exact
visible substring to an existing versioned handle and source interval. Decoding
does not establish delivery or replace authoritative source verification.
"""

from __future__ import annotations

import re
from typing import Any

from plugins.corpus.retrieval.embedding import text_hash

SEARCH_EVIDENCE_CONTRACT = "native-search-evidence-v1"
_HASH = re.compile(r"[0-9a-f]{64}")


def search_evidence_items(hit: dict[str, Any]) -> list[dict[str, Any]]:
    """Decode only intact, explicitly marked ranges; legacy snippets stay previews."""
    if hit.get("evidence_contract") != SEARCH_EVIDENCE_CONTRACT:
        return []
    snippet = hit.get("snippet")
    locators = hit.get("context_locators")
    spans = hit.get("evidence_spans")
    if (
        not isinstance(snippet, str)
        or not isinstance(locators, list)
        or not isinstance(spans, list)
        or not isinstance(hit.get("doc_id"), str)
        or hit["doc_id"] != "cv2:" + str(hit.get("build_id") or "")
        or not hit.get("build_id")
    ):
        return []
    items = []
    for span in spans:
        if not isinstance(span, dict):
            continue
        keys = ("member", "start", "end", "snippet_start", "snippet_end", "text_chars")
        if any(type(span.get(k)) is not int for k in keys):
            continue
        member, start, end, left, right, total = (span[k] for k in keys)
        if not (
            1 <= member <= len(locators)
            and 0 <= start < end <= total
            and 0 <= left < right <= len(snippet)
            and end - start == right - left
        ):
            continue
        locator = locators[member - 1]
        if not isinstance(locator, str) or not locator.startswith("chunk:native1/"):
            continue
        text = snippet[left:right]
        content_hash = span.get("text_sha256")
        if (
            not isinstance(content_hash, str)
            or not _HASH.fullmatch(content_hash)
            or text_hash(text) != span.get("quote_sha256")
            or (start == 0 and end == total and text_hash(text) != content_hash)
        ):
            continue
        items.append(
            {
                "locator": locator,
                "build_id": hit["build_id"],
                "text": text,
                "fragment": {"start": start, "end": end},
                "text_chars": total,
                "text_sha256": content_hash,
            }
        )
    return items
