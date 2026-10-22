"""Target-bound search and exact native delivery in one publication read snapshot."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

import psycopg

from plugins.corpus.preparation import read_pg
from plugins.corpus.preparation.chunk import normalize_search_text
from plugins.corpus.preparation.negative_query import retrieval_query
from plugins.corpus.preparation.search_pg import (
    _SEARCH_SQL,
    SearchHit,
    _check_target,
    _rank_query_on,
    build_search_params,
)
from plugins.corpus.retrieval.diagnostics import RetrievalTrace, global_rrf
from plugins.corpus.retrieval.embedding import EmbeddingError, VectorConfig, validate_vector
from plugins.corpus.retrieval.hybrid import fuse, query_vector
from plugins.corpus.retrieval.native import (
    NativeBlock,
    NativeIndex,
    NativeResult,
    NativeSpan,
    raw_slices,
    select_native,
)
from plugins.corpus.retrieval.native_target import check_native_target

_DENSE_SQL = """
WITH matches AS (
 SELECT p.source_id,c.build_id,c.chunk_id,c.kind,c.title_text,c.section_path,c.unit_refs,
        c.search_text,d.published,c.eval_vector <=> %(vector)s::vector AS distance
 FROM pg_temp.native_chunks c
 JOIN corpus.corpus_publications p ON p.active_build_id=c.build_id
 JOIN pg_temp.native_dates d ON d.source_id=p.source_id
 WHERE d.published IS NULL OR d.published<=%(date_to)s
), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY source_id ORDER BY distance,build_id,chunk_id) AS pos
 FROM matches
)
SELECT * FROM ranked WHERE pos<=40 ORDER BY distance,build_id,chunk_id LIMIT 200
"""


def _snapshot(cur: psycopg.Cursor, index: NativeIndex) -> None:
    cur.execute(
        "SELECT source_id,active_build_id,generation FROM corpus.corpus_publications "
        "ORDER BY source_id"
    )
    if [list(row) for row in cur.fetchall()] != index.manifest["publications"]:
        raise read_pg.IntegrityError("native_index_publications_changed_rebuild_required")
    cur.execute(
        "SELECT p.source_id,a.decision,s.original_names,m.confirmed_publication_date::text,sa.decision,"
        "ba.metadata_snapshot->'report_publication'->>'value' "
        "FROM corpus.corpus_publications p "
        "JOIN corpus.corpus_sources s ON s.source_id=p.source_id "
        "JOIN corpus.corpus_builds b ON b.build_id=p.active_build_id "
        "LEFT JOIN corpus.corpus_admissions ba ON ba.decision_id=b.decision_id "
        "LEFT JOIN corpus.corpus_admissions a ON a.decision_id=p.current_decision_id "
        "LEFT JOIN corpus.corpus_admissions sa ON sa.decision_id=s.current_decision_id "
        "LEFT JOIN corpus_retrieval.source_metadata m ON m.source_id=p.source_id "
        "WHERE p.source_id=ANY(%s::text[])",
        (index.manifest["source_allowlist"],),
    )
    live = {r[0]: r for r in cur.fetchall()}
    for d in index.dates:
        row = live.get(d["source_id"])
        if row is None or row[1] != "in_scope" or row[4] != "in_scope":
            raise read_pg.WithdrawnError("native_source_not_in_scope")
        if sorted(row[2]) != sorted(d["names"]):
            raise read_pg.IntegrityError("native_source_names_changed_rebuild_required")
        if (
            (row[3] and row[3] != d["date"])
            or (d["basis"] == "reviewed_metadata" and row[3] != d["date"])
            or (not row[3] and row[5] and row[5] != d["date"])
            or (d["basis"] == "admission" and not row[3] and row[5] != d["date"])
        ):
            raise read_pg.IntegrityError("native_source_date_changed_rebuild_required")


def _load_blocks(cur: psycopg.Cursor, index: NativeIndex) -> dict[tuple[str, str], NativeBlock]:
    """Read authoritative units, verify their hashes, then expose mapped slices only."""
    bids = sorted({c["build_id"] for c in index.chunks})
    cur.execute(
        "SELECT build_id,unit_id,kind,raw_text,location,content_hash,status "
        "FROM corpus.corpus_units WHERE build_id=ANY(%s::text[])",
        (bids,),
    )
    units: dict[tuple[str, str], dict[str, Any]] = {}
    needed = {(c["build_id"], uid) for c in index.chunks for uid in c["unit_refs"]}
    for bid, uid, kind, raw, location, content_hash, status in cur.fetchall():
        if (bid, uid) not in needed:
            continue
        read_pg.verified_unit(bid, uid, raw, location, content_hash)
        frozen = index.units[bid, uid]
        expected_location = dict(frozen["location"])
        span = expected_location.get("char_span")
        if isinstance(span, dict):
            expected_location["char_span"] = [span["start"], span["end"]]
        if (
            status != "kept"
            or kind != frozen["kind"]
            or content_hash != frozen["content_hash"]
            or location != expected_location
        ):
            raise read_pg.IntegrityError("native_unit_changed_rebuild_required")
        units[bid, uid] = {
            "unit_id": uid,
            "kind": kind,
            "raw_text": raw,
            "location": location,
            "content_hash": content_hash,
            "status": status,
        }
    if units.keys() != needed:
        raise read_pg.IntegrityError("native_unit_missing")
    dates = {d["source_id"]: d["date"] for d in index.dates}
    result = {}
    for c in index.chunks:
        slices = raw_slices(c["search_text"], [units[c["build_id"], u] for u in c["unit_refs"]])
        result[c["build_id"], c["chunk_id"]] = NativeBlock(
            c["source_id"],
            c["build_id"],
            c["chunk_id"],
            dates[c["source_id"]],
            "\n".join(s.text for s in slices),
            tuple(NativeSpan(s.unit_id, s.page, s.start, s.end, s.raw_sha256) for s in slices),
        )
    return result


def _prepare(conn: psycopg.Connection, index: NativeIndex) -> None:
    conn.execute("CREATE TEMP TABLE native_dates(source_id text PRIMARY KEY,published text)")
    for d in index.dates:
        conn.execute("INSERT INTO native_dates VALUES(%s,%s)", (d["source_id"], d["date"]))
    conn.execute(
        "CREATE TEMP TABLE native_chunks AS SELECT * FROM corpus.corpus_chunks WITH NO DATA"
    )
    conn.execute("ALTER TABLE native_chunks ADD COLUMN eval_vector vector")
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO native_chunks(build_id,chunk_id,kind,title_text,section_path,unit_refs,"
            "search_text,search_tsv,context_refs,eval_vector) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,to_tsvector('zhcfg',%s),%s,%s::vector)",
            [
                (
                    c["build_id"],
                    c["chunk_id"],
                    c["kind"],
                    c["title_text"],
                    c["section_path"],
                    c["unit_refs"],
                    c["search_text"],
                    c["search_text"],
                    [],
                    json.dumps(index.vectors[c["input_hash"]]["vector"])
                    if c["input_hash"] in index.vectors
                    else None,
                )
                for c in index.chunks
            ],
        )


def search_native(
    dsn: str,
    target: str | None,
    query: str,
    index: NativeIndex,
    *,
    limit: int = 20,
    char_budget: int = 16000,
    trace: RetrievalTrace | None = None,
    allow_fallback: bool = False,
) -> NativeResult:
    """Return the final bounded evidence; callers must not expand it with old fetch."""
    check_native_target(target)
    if target != index.target:
        raise ValueError("native_pilot_target_mismatch")
    if not query.strip() or not 1 <= limit <= 20 or not 1 <= char_budget <= 16000:
        raise ValueError("native_query_or_budget_invalid")
    config = VectorConfig.from_env()
    if config.target_db != target or config.profile != index.manifest["profile"]:
        raise ValueError("native_embedding_profile_or_target_mismatch")
    match = re.search(r"截至(\d{4})年(\d{1,2})月(\d{1,2})日", query)
    cutoff = index.manifest["cutoff"]
    if match:
        cutoff = min(cutoff, date(*map(int, match.groups())).isoformat())
    with psycopg.connect(dsn, autocommit=True, connect_timeout=10) as conn:
        _check_target(conn, target)
        # Refuse a stale/withdrawn corpus before paying for a query vector.
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            _snapshot(cur, index)
        vector = None
        fallback_reason = None
        complete = all(c["input_hash"] in index.vectors for c in index.chunks)
        if not complete and allow_fallback:
            fallback_reason = "native_vectors_pending"
        else:
            try:
                vector, _, _ = query_vector(config, query)
                vector = validate_vector(vector, config.dimensions)
            except EmbeddingError as exc:
                if not allow_fallback:
                    raise
                fallback_reason = "embedding_" + exc.code
        _prepare(conn, index)
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            _snapshot(cur, index)
            cur.execute(
                "SELECT tsvector_to_array(to_tsvector('zhcfg',%s))",
                (normalize_search_text(query),),
            )
            row = cur.fetchone()
            candidate_query = retrieval_query(tuple(row[0])) if row else query
            params = build_search_params(candidate_query or query, limit=200, published_to=cutoff)
            params["rank_query"] = _rank_query_on(cur, candidate_query or query)
            sql = _SEARCH_SQL.replace("corpus.corpus_chunks AS c", "pg_temp.native_chunks AS c")
            sql = sql.replace("a.metadata_snapshot->'report_publication'->>'value'", "nd.published")
            sql = sql.replace(
                "JOIN corpus.corpus_sources AS s",
                "JOIN pg_temp.native_dates nd ON nd.source_id=p.source_id "
                "JOIN corpus.corpus_sources AS s",
            ).replace(
                "OR nd.published <= %(date_to)s)",
                "OR nd.published IS NULL OR nd.published <= %(date_to)s)",
            )
            cur.execute(sql, params)
            lexical = tuple(
                SearchHit(
                    source_id=r[0],
                    build_id=r[1],
                    chunk_id=r[2],
                    kind=r[3],
                    title_text=r[4],
                    section_path=tuple(r[5]),
                    unit_refs=tuple(r[6]),
                    score=r[7],
                    snippet=r[8],
                    published=r[9],
                    source_coverage=r[10],
                )
                for r in cur.fetchall()
            )
            dense_rows = []
            if vector is not None:
                params["vector"] = json.dumps(vector)
                try:
                    # A savepoint prevents a vector SQL failure poisoning lexical reads.
                    with conn.transaction():
                        cur.execute(_DENSE_SQL, params)
                        dense_rows = cur.fetchall()
                except psycopg.Error:
                    if not allow_fallback:
                        raise
                    fallback_reason = "native_vector_query_failed"
            dense = tuple(
                SearchHit(
                    source_id=r[0],
                    build_id=r[1],
                    chunk_id=r[2],
                    kind=r[3],
                    title_text=r[4],
                    section_path=tuple(r[5]),
                    unit_refs=tuple(r[6]),
                    snippet=r[7][:280],
                    published=r[8],
                    score=1 - float(r[9]),
                )
                for r in dense_rows
            )
            current = fuse(lexical, dense)
            global_rank = global_rrf(RetrievalTrace(lexical=lexical, dense=dense))
            first = (current[0].build_id, current[0].chunk_id) if current else None
            guarded = current[:1] + tuple(
                h for h in global_rank if (h.build_id, h.chunk_id) != first
            )
            if fallback_reason:
                guarded = lexical
            blocks = _load_blocks(cur, index)
            chosen = select_native(
                [(h.build_id, h.chunk_id) for h in guarded],
                blocks,
                char_budget=char_budget,
                limit=limit,
            )
            if trace is not None:
                trace.lexical, trace.dense, trace.fused = lexical, dense, guarded
                selected_keys = {(b.build_id, b.chunk_id) for b in chosen}
                trace.selected = tuple(
                    h for h in guarded if (h.build_id, h.chunk_id) in selected_keys
                )
                trace.status = "native_lexical_fallback" if fallback_reason else "native_hybrid"
    return NativeResult(
        query,
        index.index_id,
        chosen,
        sum(len(b.text) for b in chosen),
        char_budget,
        limit,
        cutoff,
        tuple(d["source_id"] for d in index.dates if d["date"] is None),
        bool(chosen and (chosen[0].build_id, chosen[0].chunk_id) == first),
        "lexical" if fallback_reason else "hybrid",
        fallback_reason,
    )
