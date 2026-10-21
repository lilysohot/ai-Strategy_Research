"""Opt-in pilot previews and first-read plans; retrieval ranks never change.

Previews are exact contiguous slices of verified chunk text, not new evidence
receipts. Quotes still require the normal fetch/delivery path.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from plugins.corpus.preparation.negative_query import abstain_content_lexemes
from plugins.corpus.preparation.read_pg import ChunkEvidence, fetch_bands
from plugins.corpus.preparation.search_pg import query_lexemes
from plugins.corpus.preparation.selection import SelectedBand

if TYPE_CHECKING:
    from plugins.corpus.service import SearchHit


@dataclass(frozen=True)
class Preview:
    text: str
    start: int | None
    end: int | None
    status: str
    matched_terms: tuple[str, ...] = ()
    citation_ready: bool = False


def _compact(text: str) -> str:
    return "".join(text.casefold().split())


def sentence_preview(
    evidence: ChunkEvidence, terms: Sequence[str], *, max_chars: int = 600
) -> Preview:
    """Locate a matching window, retain adjacent complete sentences within budget.

    PDF line wraps are preserved and do not terminate sentences. We never take
    an oversized sentence prefix or pass a table row off as standalone prose.
    A subject/time may still live outside the window: no answerability claim.
    """
    if max_chars < 1:
        raise ValueError("positive_preview_budget_required")
    if evidence.kind in {"table", "heading"}:
        return Preview("", None, None, "structured_content_requires_fetch")
    text = evidence.text
    boundaries = [match.end() for match in re.finditer(r"[。！？!?](?:[”’」』])?", text)]
    spans: list[tuple[int, int]] = []
    start = 0
    for end in boundaries:
        while start < end and text[start].isspace():
            start += 1
        if start < end:
            spans.append((start, end))
        start = end
    # An unterminated trailing fragment is intentionally not called a sentence.
    tokens = tuple(dict.fromkeys(_compact(t) for t in terms if len(_compact(t)) > 1))
    candidates: list[tuple[float, int, int, tuple[str, ...]]] = []
    for i, (start, _) in enumerate(spans):
        for j in range(i, min(len(spans), i + 3)):
            end = spans[j][1]
            if end - start > max_chars:
                break
            window = _compact(text[start:end])
            matched = tuple(t for t in tokens if t in window)
            if not matched:
                continue
            # Unique query-term coverage, then prefer the shorter complete window.
            score = sum(min(len(t), 6) for t in matched)
            candidates.append((score, start, end, matched))
    if not candidates:
        return Preview("", None, None, "no_complete_matching_sentence")
    _, start, end, matched = min(
        candidates, key=lambda item: (-item[0], item[2] - item[1], item[1])
    )
    # Anaphoric openings need their preceding sentence, if it fits.
    if re.match(r"(?:因此|所以|这|该|其|同时|其中|由此|此外|但|而)", text[start:end]):
        index = next(i for i, span in enumerate(spans) if span[0] == start)
        if index and end - spans[index - 1][0] <= max_chars:
            start = spans[index - 1][0]
    # Preserve the surrounding explanation, including qualifiers that do not
    # repeat query words. Alternate forward/backward; never cross a partial
    # sentence just to fill the budget or synthesize a disconnected quotation.
    left = next(i for i, span in enumerate(spans) if span[0] == start)
    right = next(i for i, span in enumerate(spans) if span[1] == end)
    while True:
        changed = False
        if right + 1 < len(spans) and spans[right + 1][1] - start <= max_chars:
            right += 1
            end = spans[right][1]
            changed = True
        if left and end - spans[left - 1][0] <= max_chars:
            left -= 1
            start = spans[left][0]
            changed = True
        if not changed:
            break
    return Preview(text[start:end], start, end, "complete_sentence_window", matched)


def delivery_views(
    hits: Sequence[SearchHit],
    evidence: Sequence[ChunkEvidence],
    terms: Sequence[str],
) -> list[dict[str, object]]:
    """Pure projection: same hits/order, full scope retained, core is a subset.

    Tables/headings keep their full existing scope. Body anchors rely on the
    authoritative fetcher's structural dependencies. Already requested chunks
    can be skipped on expansion using remaining_locators, but full expansion
    remains available when neighbouring arguments are needed.
    """
    by_key = {(chunk.build_id, chunk.chunk_id): chunk for chunk in evidence}
    seen: dict[str, set[str]] = {}
    result: list[dict[str, object]] = []
    for hit in hits:
        chunk = by_key[(hit.build_id, hit.chunk_id)]
        if (
            chunk.source_id != hit.source_id
            or hit.doc_id != "cv2:" + chunk.build_id
            or hit.locator != "chunk:" + chunk.chunk_id
        ):
            raise ValueError("evidence_identity_mismatch")
        full = tuple(dict.fromkeys(hit.context_locators or (hit.locator,)))
        if hit.locator not in full:
            raise ValueError("anchor_outside_offered_scope")
        core = full if chunk.kind in {"table", "heading"} else (hit.locator,)
        previous = seen.setdefault(hit.doc_id, set())
        remaining = tuple(locator for locator in full if locator not in previous)
        previous.update(full)
        result.append(
            {
                "preview": asdict(sentence_preview(chunk, terms)),
                "core_fetch_plan": {
                    "doc_id": hit.doc_id,
                    "locators": list(core),
                    "view": "compact",
                },
                "expansion": {
                    "doc_id": hit.doc_id,
                    "locators": list(full),
                    "remaining_after_prior_full_expansions": list(remaining),
                    "view": "compact",
                    "may_contain_additional_answer_parts": True,
                },
                "delivery_hint": (
                    "先读核心锚点；比较、原因链或指代未完整时继续扩展。"
                    "预览仅供选读，不是已取证或已送达的引用。"
                ),
            }
        )
    return result


def load_delivery_views(
    dsn: str, sandbox_db: str, query: str, hits: Sequence[SearchHit]
) -> list[dict[str, object]]:
    """One batch authority fetch for anchors; only available in the vector pilot."""
    if not sandbox_db.startswith("vector_pilot_"):
        raise ValueError("delivery_preview_requires_pilot_database")
    order: dict[str, tuple[str, ...]] = {}
    builds: dict[str, str] = {}
    bands: list[SelectedBand] = []
    for hit in hits:
        if hit.source_id in builds and builds[hit.source_id] != hit.build_id:
            raise ValueError("mixed_builds_in_source")
        builds[hit.source_id] = hit.build_id
        chunks = order.get(hit.source_id, ())
        if hit.chunk_id not in chunks:
            order[hit.source_id] = (*chunks, hit.chunk_id)
            position = len(chunks)
            bands.append(
                SelectedBand(hit.source_id, hit.build_id, position, position, hit.score, (position,))
            )
    originals = fetch_bands(dsn, tuple(bands), order, sandbox_db=sandbox_db)
    terms = abstain_content_lexemes(query_lexemes(dsn, query, sandbox_db=sandbox_db))
    return delivery_views(hits, originals, terms)
