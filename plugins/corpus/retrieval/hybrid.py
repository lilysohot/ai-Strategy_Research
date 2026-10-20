"""Exact cosine candidates and two-level RRF inside the publication read snapshot."""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from dataclasses import replace

import psycopg

from plugins.corpus.preparation import read_pg
from plugins.corpus.preparation.contract import ResearchDomain
from plugins.corpus.preparation.search_pg import (
    SearchHit,
    _check_target,
    _enrich_hits,
    build_search_params,
    search_chunks_on,
)
from plugins.corpus.retrieval.embedding import (
    DoubaoEmbedder,
    EmbeddingError,
    VectorConfig,
    text_hash,
)
from plugins.corpus.retrieval.index_pg import ready_counts

_VECTOR_SQL = """
WITH matches AS (
  SELECT p.source_id, c.build_id, c.chunk_id, c.kind, c.title_text,
         c.section_path, c.unit_refs, left(c.search_text, 280) AS snippet,
         a.metadata_snapshot->'report_publication'->>'value' AS published,
         e.embedding <=> %(vector)s::vector AS distance
  FROM corpus.corpus_publications p
  JOIN corpus.corpus_chunks c ON c.build_id=p.active_build_id
  JOIN corpus.corpus_builds b ON b.build_id=c.build_id
  JOIN corpus.corpus_admissions a ON a.decision_id=b.decision_id
  LEFT JOIN corpus_retrieval.source_metadata m ON m.source_id=p.source_id
  JOIN corpus_retrieval.chunk_vectors v
    ON v.profile=%(profile)s AND v.source_id=p.source_id
    AND v.build_id=c.build_id AND v.chunk_id=c.chunk_id AND v.input_text=c.search_text
    AND v.section_path=c.section_path
    AND (
      (%(input_variant)s='published-search-text-v1' AND v.metadata_hash='')
      OR
      (%(input_variant)s='reviewed-context-prefix-v1'
       AND v.metadata_hash=m.metadata_hash)
    )
  JOIN corpus_retrieval.embeddings e
    ON e.profile=v.profile AND e.input_hash=v.input_hash
    AND e.status='ready' AND e.dimensions=%(dimensions)s
  WHERE (%(domain)s::text IS NULL OR a.research_domain=%(domain)s)
    AND (%(date_from)s::text IS NULL
         OR a.metadata_snapshot->'report_publication'->>'value' >= %(date_from)s)
    AND (%(date_to)s::text IS NULL
         OR a.metadata_snapshot->'report_publication'->>'value' <= %(date_to)s)
), ranked AS (
  SELECT *, row_number() OVER (
    PARTITION BY source_id ORDER BY distance, build_id, chunk_id
  ) AS source_position FROM matches
)
SELECT source_id, build_id, chunk_id, kind, title_text, section_path, unit_refs,
       snippet, published, distance
FROM ranked WHERE source_position <= 40
ORDER BY distance, build_id, chunk_id LIMIT %(limit)s
"""

_QUERY_CACHE: OrderedDict[tuple[str, str], tuple[float, tuple[float, ...]]] = OrderedDict()
_QUERY_LOCK = threading.Lock()


def query_vector(
    config: VectorConfig, query: str
) -> tuple[tuple[float, ...], bool, dict[str, int]]:
    """Bounded process cache. Only embeddings are cached, never publication results."""
    key = (config.profile, text_hash(query))
    # Serialize misses as well: concurrent identical queries make a single API call.
    with _QUERY_LOCK:
        cached = _QUERY_CACHE.get(key)
        if cached and time.monotonic() - cached[0] < 300:
            _QUERY_CACHE.move_to_end(key)
            return cached[1], True, {}
        result = DoubaoEmbedder(config).embed(query, "query")
        _QUERY_CACHE[key] = (time.monotonic(), result.vector)
        _QUERY_CACHE.move_to_end(key)
        while len(_QUERY_CACHE) > 128:
            _QUERY_CACHE.popitem(last=False)
        return result.vector, False, result.usage


def fuse(lexical: tuple[SearchHit, ...], dense: tuple[SearchHit, ...]) -> tuple[SearchHit, ...]:
    """RRF source ranks, then RRF within each source. Duplicates vote only once."""
    source_scores: dict[str, float] = {}
    chunk_scores: dict[tuple[str, str], float] = {}
    hits: dict[tuple[str, str], SearchHit] = {}
    for channel in (lexical, dense):
        source_ranks: dict[str, int] = {}
        positions: dict[str, int] = {}
        seen: set[tuple[str, str]] = set()
        for hit in channel:
            key = (hit.build_id, hit.chunk_id)
            if key in seen:
                continue
            seen.add(key)
            if hit.source_id not in source_ranks:
                rank = len(source_ranks) + 1
                source_ranks[hit.source_id] = rank
                source_scores[hit.source_id] = source_scores.get(hit.source_id, 0) + 1 / (60 + rank)
            positions[hit.source_id] = positions.get(hit.source_id, 0) + 1
            chunk_scores[key] = chunk_scores.get(key, 0) + 1 / (60 + positions[hit.source_id])
            hits.setdefault(key, hit)  # Prefer lexical snippet/structural metadata when shared.
    ordered = sorted(
        hits,
        key=lambda key: (
            -source_scores[hits[key].source_id],
            hits[key].source_id,
            -chunk_scores[key],
            key,
        ),
    )
    return tuple(replace(hits[key], score=chunk_scores[key]) for key in ordered)


def search(
    dsn: str,
    query: str,
    *,
    original_query: str,
    sandbox_db: str | None,
    limit: int = 200,
    domain: ResearchDomain | None = None,
    published_from: str | None = None,
    published_to: str | None = None,
) -> tuple[
    tuple[SearchHit, ...],
    dict[str, tuple[str, ...]],
    dict[str, object],
    tuple[SearchHit, ...] | None,
]:
    """Return fused hits + true lexical hits; unavailable vectors fall back as one read."""
    started = time.monotonic()
    kwargs = {
        "sandbox_db": sandbox_db,
        "domain": domain,
        "published_from": published_from,
        "published_to": published_to,
        "limit": limit,
    }

    def fallback(reason: str) -> tuple:
        hits, order, coverage = read_pg.search_with_coverage_bands(dsn, query, **kwargs)
        coverage["retrieval"] = {
            "requested": "hybrid",
            "used": "lexical",
            "reason": reason,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        }
        return hits, order, coverage, None

    try:
        config = VectorConfig.from_env()
        if sandbox_db != config.target_db:
            return fallback("vector_target_mismatch")
        # Do not charge for a query if the index cannot serve it. Recheck inside the
        # final snapshot because publication may advance during the network request.
        with psycopg.connect(dsn, autocommit=True, connect_timeout=10) as conn:
            _check_target(conn, sandbox_db)
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('corpus_retrieval.embeddings')")
                schema_row = cur.fetchone()
                if schema_row is None or schema_row[0] is None:
                    return fallback("vector_schema_missing")
                expected, ready = ready_counts(cur, config)
                if expected == 0 or expected != ready:
                    return fallback("vector_index_incomplete")
        vector, cached, usage = query_vector(config, original_query)
        params = build_search_params(
            query,
            domain=domain,
            published_from=published_from,
            published_to=published_to,
            limit=limit,
        )
        params.update(
            {
                "profile": config.profile,
                "dimensions": config.dimensions,
                "vector": json.dumps(vector),
                "input_variant": config.input_variant,
            }
        )
        with psycopg.connect(dsn, autocommit=True, connect_timeout=10) as conn:
            _check_target(conn, sandbox_db)
            with conn.transaction(), conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                expected, ready = ready_counts(cur, config)
                lexical = search_chunks_on(cur, params)
                complete = expected > 0 and expected == ready
                dense: tuple[SearchHit, ...] = ()
                if complete:
                    cur.execute(_VECTOR_SQL, params)
                    dense = _enrich_hits(
                        cur,
                        tuple(
                            SearchHit(
                                source_id=r[0],
                                build_id=r[1],
                                chunk_id=r[2],
                                kind=r[3],
                                title_text=r[4],
                                section_path=tuple(r[5]),
                                unit_refs=tuple(r[6]),
                                snippet=r[7],
                                published=str(r[8]) if r[8] else None,
                                score=1 - float(r[9]),
                            )
                            for r in cur.fetchall()
                        ),
                    )
                hits = fuse(lexical, dense) if complete else lexical
                coverage = read_pg.coverage_snapshot_on(
                    cur, query_status="matched" if hits else "no_match"
                )
                order = read_pg._chunk_order_by_source_on(cur, hits)
        coverage["retrieval"] = {
            "requested": "hybrid",
            "used": "hybrid" if complete else "lexical",
            "reason": None if complete else "publication_changed_index_incomplete",
            "profile": config.profile,
            "expected_chunks": expected,
            "ready_chunks": ready,
            "lexical_candidates": len(lexical),
            "vector_candidates": len(dense),
            "query_cache_hit": cached,
            "query_usage": usage,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        }
        return hits, order, coverage, lexical if complete else None
    except EmbeddingError as exc:
        return fallback(exc.code)
    except (ValueError, psycopg.Error):
        # A failed vector SQL transaction is discarded; fallback reads all lexical
        # candidates, ordering and coverage again in a fresh consistent snapshot.
        return fallback("vector_configuration_or_database_error")
