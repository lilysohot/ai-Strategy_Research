"""Gold-independent collection through the actual registered corpus tools.

This module deliberately takes only query IDs and text. Gold labels are used by
scoring *after* collection, never to decide which queries to execute or abstain.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from plugins.corpus.scoring import (
    FetchedEvidence,
    ObservationOutcome,
    QueryObservation,
    RetrievedDocument,
)


class Invokable(Protocol):
    async def ainvoke(self, args: dict[str, object]) -> str: ...


@dataclass(frozen=True)
class ProductQuery:
    query_id: str
    text: str


@dataclass(frozen=True)
class CollectedQuery:
    observation: QueryObservation
    calls: tuple[dict[str, object], ...]
    error: str | None = None


async def collect_query(
    query: ProductQuery,
    *,
    search: Invokable,
    fetch: Invokable,
    limit: int = 10,
) -> CollectedQuery:
    """Collect actual search/fetch results; errors stay FAILED, never NO_MATCH.

    The 1..20 limit is the public tool contract. Text is sent unchanged. Source
    aliases, expectations, truth labels and evaluation thresholds are not inputs.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise ValueError("limit must be an integer in the public tool range 1..20")
    calls: list[dict[str, object]] = []

    async def invoke(name: str, tool: Invokable, args: dict[str, object]) -> dict:
        record: dict[str, object] = {"tool": name, "args": args}
        calls.append(record)
        raw = await tool.ainvoke(args)
        payload = json.loads(raw)
        record["response"] = payload
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise ValueError(f"{name}: failed response")
        return payload

    try:
        found = await invoke("corpus_search", search, {"query": query.text, "limit": limit})
        hits = found.get("hits")
        if not isinstance(hits, list) or len(hits) > limit:
            raise ValueError("corpus_search: invalid hits or exceeded limit")
        if not hits:
            return CollectedQuery(
                QueryObservation(query.query_id, ObservationOutcome.NO_MATCH, ()), tuple(calls)
            )
        sources: dict[str, tuple[str, list[FetchedEvidence]]] = {}
        for hit in hits:
            if not isinstance(hit, dict):
                raise ValueError("corpus_search: invalid hit")
            source, build, chunk = (hit.get(key) for key in ("source_id", "build_id", "chunk_id"))
            if not all(isinstance(v, str) and v for v in (source, build, chunk)):
                raise ValueError("corpus_search: missing versioned identity")
            source, build, chunk = str(source), str(build), str(chunk)
            if hit.get("doc_id") != f"cv2:{build}" or hit.get("locator") != f"chunk:{chunk}":
                raise ValueError("corpus_search: handle identity mismatch")
            context = hit.get("context_locators", [hit["locator"]])
            if not isinstance(context, list) or any(
                not isinstance(locator, str) or not locator.startswith("chunk:")
                for locator in context
            ):
                raise ValueError("corpus_search: invalid context locators")
            # ``context_locators`` is emitted in authoritative document order.
            # Keep that order even when the relevance-ranked anchor is in the
            # middle of the selected band; moving it to the front breaks long
            # verbatim evidence that spans adjacent chunks.
            locators = list(dict.fromkeys(context))
            if hit["locator"] not in locators:
                locators.insert(0, hit["locator"])
            if len(locators) > 400:
                raise ValueError("corpus_search: context locator bound exceeded")
            texts: list[str] = []
            pages: set[int] = set()
            cells_out: list[FetchedEvidence] = []
            seen_cells: set[tuple[str, int, str, str, str]] = set()
            for locator in locators:
                expected_chunk = locator.split(":", 1)[1]
                body = await invoke(
                    "corpus_fetch", fetch, {"doc_id": hit["doc_id"], "locator": locator}
                )
                if (
                    body.get("source_id") != source
                    or body.get("build_id") != build
                    or body.get("chunk_id") != expected_chunk
                ):
                    raise ValueError("corpus_fetch: cross-version/source/chunk response")
                text, units = body.get("text"), body.get("units")
                if not isinstance(text, str) or not isinstance(units, list):
                    raise ValueError("corpus_fetch: invalid authority payload")
                texts.append(text)
                unit_pages: dict[str, int | None] = {}
                for unit in units:
                    if not isinstance(unit, dict) or not isinstance(unit.get("unit_id"), str):
                        raise ValueError("corpus_fetch: invalid authority unit")
                    page = unit.get("page")
                    if page is not None and not isinstance(page, int):
                        raise ValueError("corpus_fetch: invalid authority page")
                    unit_pages[str(unit["unit_id"])] = page
                    if isinstance(page, int):
                        pages.add(page)
                semantic_cells = body.get("semantic_cells", [])
                if not isinstance(semantic_cells, list):
                    raise ValueError("corpus_fetch: invalid semantic cells")
                unit_texts: dict[str, str] = {}
                if semantic_cells:
                    spans = body.get("spans")
                    if not isinstance(spans, list):
                        raise ValueError("corpus_fetch: semantic cells require authority spans")
                    for span in spans:
                        if not isinstance(span, dict):
                            raise ValueError("corpus_fetch: invalid authority span")
                        span_unit = span.get("unit_id")
                        start = span.get("start")
                        end = span.get("end")
                        if (
                            not isinstance(span_unit, str)
                            or span_unit not in unit_pages
                            or isinstance(start, bool)
                            or not isinstance(start, int)
                            or isinstance(end, bool)
                            or not isinstance(end, int)
                            or not 0 <= start <= end <= len(text)
                            or span_unit in unit_texts
                        ):
                            raise ValueError("corpus_fetch: invalid authority span")
                        unit_texts[span_unit] = text[start:end]
                for cell in semantic_cells:
                    if not isinstance(cell, dict):
                        raise ValueError("corpus_fetch: invalid semantic cell")
                    unit_id, page, row, col, cell_text = (
                        cell.get(key) for key in ("unit_id", "page", "row", "col", "text")
                    )
                    if (
                        not isinstance(unit_id, str)
                        or unit_id not in unit_pages
                        or not isinstance(page, int)
                        or unit_pages[unit_id] != page
                        or not isinstance(row, str)
                        or not row
                        or not isinstance(col, str)
                        or not col
                        or not isinstance(cell_text, str)
                        or not cell_text
                        or cell_text not in unit_texts.get(unit_id, "")
                    ):
                        raise ValueError(
                            "corpus_fetch: semantic cell is not backed by authority units"
                        )
                    cell_key = (unit_id, page, row, col, cell_text)
                    if cell_key in seen_cells:
                        continue
                    seen_cells.add(cell_key)
                    cells_out.append(
                        FetchedEvidence(
                            cell_text,
                            (
                                f"page:{page}",
                                f"row:{row}",
                                f"col:{col}",
                                f"cell:{row}×{col}",
                            ),
                            True,
                        )
                    )
            fetched = [
                FetchedEvidence(
                    "\n".join(texts), tuple(f"page:{page}" for page in sorted(pages)), True
                ),
                *cells_out,
            ]
            previous_build, evidences = sources.setdefault(source, (build, []))
            if previous_build != build:
                raise ValueError("corpus_search: multiple versions of one source")
            evidences.extend(fetched)
        docs = tuple(RetrievedDocument(s, tuple(e), b) for s, (b, e) in sources.items())
        return CollectedQuery(
            QueryObservation(query.query_id, ObservationOutcome.OK, docs), tuple(calls)
        )
    except (ValueError, TypeError, KeyError, RuntimeError, OSError) as exc:
        return CollectedQuery(
            QueryObservation(query.query_id, ObservationOutcome.FAILED, ()),
            tuple(calls),
            f"{type(exc).__name__}: {exc}",
        )
