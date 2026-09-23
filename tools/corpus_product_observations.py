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
            body = await invoke(
                "corpus_fetch", fetch, {"doc_id": hit["doc_id"], "locator": hit["locator"]}
            )
            if any(body.get(key) != hit[key] for key in ("source_id", "build_id", "chunk_id")):
                raise ValueError("corpus_fetch: cross-version/source/chunk response")
            text, units = body.get("text"), body.get("units")
            if not isinstance(text, str) or not isinstance(units, list):
                raise ValueError("corpus_fetch: invalid authority payload")
            pages = sorted(
                {u["page"] for u in units if isinstance(u, dict) and isinstance(u.get("page"), int)}
            )
            evidence = FetchedEvidence(text, tuple(f"page:{p}" for p in pages), True)
            previous_build, evidences = sources.setdefault(source, (build, []))
            if previous_build != build:
                raise ValueError("corpus_search: multiple versions of one source")
            evidences.append(evidence)
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
