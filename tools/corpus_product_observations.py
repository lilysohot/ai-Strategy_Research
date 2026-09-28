"""Gold-independent collection through the actual registered corpus tools.

This module deliberately takes only query IDs and text. Gold labels are used by
scoring *after* collection, never to decide which queries to execute or abstain.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from plugins.corpus.scoring import (
    FetchedEvidence,
    ObservationOutcome,
    QueryObservation,
    RetrievedDocument,
)

#: 分页信封的安全页数上限（防御游标环；正常远小于此）。
_MAX_PAGES = 200


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


async def _collect_paged_block(
    invoke: Callable[[str, Invokable, dict[str, object]], Awaitable[dict]],
    fetch: Invokable,
    first: dict[str, object],
    doc_id: str,
    expected_chunk: str,
) -> dict[str, object]:
    """D2：跟随 ``next_cursor`` 取全分页信封，并按 ``block_evidence`` 拼回整块。

    单块超限时 ``corpus_fetch`` 返回分页信封：``items`` 持有正文分片
    （``fragment.start/end`` 无缝覆盖整块），信封级 ``block_evidence`` 持有整块坐标的
    ``source_id``／``units``／``spans``／``semantic_cells``。拼回整块后与单块结果同构，
    后续权威校验（跨版本身份、span 切片、cell 对齐）逻辑不变。
    """
    frags: list[tuple[int, int, str]] = []
    sha: object = None
    chars: object = None
    envelope: dict[str, object] = first
    pages = 0
    while True:
        pages += 1
        if pages > _MAX_PAGES:
            raise ValueError("corpus_fetch: paging did not terminate")
        if envelope.get("unresolved") or envelope.get("item_errors"):
            raise ValueError("corpus_fetch: unresolved members in paged response")
        items = envelope.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("corpus_fetch: paged response without items")
        for item in items:
            if not isinstance(item, dict) or item.get("chunk_id") != expected_chunk:
                raise ValueError("corpus_fetch: paged response mixes blocks")
            piece = item.get("text")
            if not isinstance(piece, str):
                raise ValueError("corpus_fetch: paged item without text")
            fragment = item.get("fragment")
            if fragment is None:
                start, end = 0, len(piece)
            elif (
                isinstance(fragment, dict)
                and isinstance(fragment.get("start"), int)
                and isinstance(fragment.get("end"), int)
            ):
                start, end = fragment["start"], fragment["end"]
            else:
                raise ValueError("corpus_fetch: invalid fragment in paged item")
            frags.append((start, end, piece))
            item_sha, item_chars = item.get("text_sha256"), item.get("text_chars")
            if sha is None and chars is None:
                sha, chars = item_sha, item_chars
            elif item_sha != sha or item_chars != chars:
                raise ValueError("corpus_fetch: paged fragments disagree on block identity")
        if envelope.get("exhausted"):
            break
        cursor = envelope.get("next_cursor")
        if not isinstance(cursor, str) or not cursor:
            raise ValueError("corpus_fetch: paged response without next_cursor")
        envelope = await invoke("corpus_fetch", fetch, {"doc_id": doc_id, "cursor": cursor})

    frags.sort(key=lambda triple: triple[0])
    position = 0
    for start, end, _piece in frags:
        if start != position:
            raise ValueError("corpus_fetch: paged fragments do not tile the block")
        position = end
    text = "".join(piece for _, _, piece in frags)
    if chars is not None and position != chars:
        raise ValueError("corpus_fetch: paged fragments do not cover the block")
    if isinstance(sha, str) and hashlib.sha256(text.encode()).hexdigest() != sha:
        raise ValueError("corpus_fetch: reassembled block fails content check")
    evidence = first.get("block_evidence")
    if not isinstance(evidence, dict):
        raise ValueError("corpus_fetch: paged response missing block evidence")
    units = evidence.get("units")
    if not isinstance(units, list):
        raise ValueError("corpus_fetch: invalid authority payload")
    spans = evidence.get("spans")
    if evidence.get("semantic_cells") and not isinstance(spans, list):
        raise ValueError("corpus_fetch: semantic cells require authority spans")
    return {
        "ok": True,
        "source_id": evidence.get("source_id"),
        "build_id": first.get("build_id"),
        "chunk_id": expected_chunk,
        "locator": first.get("locator"),
        "text": text,
        "units": units,
        "spans": spans,
        "semantic_cells": evidence.get("semantic_cells") or [],
    }


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
                if isinstance(body.get("items"), list):
                    # A2 分页信封（单块超限自动分片）：跟游标拼回整块再走同一校验（D2）。
                    body = await _collect_paged_block(
                        invoke, fetch, body, str(hit["doc_id"]), expected_chunk
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
