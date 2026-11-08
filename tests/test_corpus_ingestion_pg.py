"""Opt-in real PostgreSQL migration and pre-top-k filtering tests.

CORPUS_INGESTION_TEST_DSN must name an empty vector_pilot_ingestion_* database.
All test tables and migrations roll back; this never touches the configured corpus.
"""

import os

import pytest

from plugins.corpus.ingestion_dates import filter_sql
from plugins.corpus.preparation.ingestion_schema import migrate
from plugins.corpus.preparation.search_pg import build_search_params, search_chunks_on
from plugins.corpus.retrieval.hybrid import _VECTOR_SQL


@pytest.fixture
def pg(monkeypatch):
    import psycopg

    dsn = os.environ.get("CORPUS_INGESTION_TEST_DSN")
    if not dsn:
        pytest.skip("CORPUS_INGESTION_TEST_DSN not configured")
    with psycopg.connect(dsn, autocommit=True) as conn:
        target = conn.execute("SELECT current_database()").fetchone()[0]
        assert target.startswith("vector_pilot_ingestion_")
        assert conn.execute("SELECT to_regnamespace('corpus')").fetchone()[0] is None
        monkeypatch.setenv("CORPUS_TARGET_DB", target)
        with conn.transaction(force_rollback=True):
            conn.execute("""
                CREATE SCHEMA corpus;
                CREATE TABLE corpus.corpus_sources(source_id text PRIMARY KEY,
                    original_names text[] DEFAULT '{}');
                CREATE TABLE corpus.corpus_publications(source_id text PRIMARY KEY,
                    active_build_id text, generation integer, activated_at timestamptz);
                CREATE TABLE corpus.corpus_admissions(decision_id text PRIMARY KEY,
                    research_domain text, metadata_snapshot jsonb DEFAULT '{}');
                CREATE TABLE corpus.corpus_builds(build_id text PRIMARY KEY, decision_id text);
                CREATE TEXT SEARCH CONFIGURATION zhcfg(COPY=pg_catalog.simple);
                CREATE TABLE corpus.corpus_chunks(build_id text, chunk_id text, kind text,
                    title_text text, section_path text[], unit_refs text[], search_text text,
                    search_tsv tsvector GENERATED ALWAYS AS(to_tsvector('zhcfg',search_text)) STORED);
            """)
            yield conn, target


def source(conn, sid, stamp, *, generation=1, active=True):
    conn.execute("INSERT INTO corpus.corpus_sources(source_id) VALUES(%s)", (sid,))
    conn.execute(
        "INSERT INTO corpus.corpus_publications VALUES(%s,%s,%s,%s)",
        (sid, sid if active else None, generation, stamp),
    )


def test_backfill_is_conservative_and_rebuild_retirement_do_not_refresh(pg):
    conn, target = pg
    source(conn, "known", "2024-03-01T00:00:00Z")
    source(conn, "unknown", "2024-03-02T00:00:00Z", generation=3)
    original = migrate(conn, target)
    assert original == dict(active_sources=2, known_ingestion_times=1, unknown_ingestion_times=1)
    assert migrate(conn, target) == original
    conn.execute(
        "UPDATE corpus.corpus_publications SET generation=generation+1, activated_at=now(), active_build_id=NULL"
    )
    conn.execute(
        "UPDATE corpus.corpus_publications SET generation=generation+1, activated_at=now(), active_build_id=source_id"
    )
    assert (
        conn.execute("SELECT ingested_at FROM corpus.corpus_sources WHERE source_id='known'")
        .fetchone()[0]
        .isoformat()
        == "2024-03-01T00:00:00+00:00"
    )
    assert (
        conn.execute(
            "SELECT ingested_at FROM corpus.corpus_sources WHERE source_id='unknown'"
        ).fetchone()[0]
        is None
    )
    assert migrate(conn, target) == original


def test_new_sources_record_only_first_successful_publication_atomically(pg):
    conn, target = pg
    conn.execute("INSERT INTO corpus.corpus_sources(source_id) VALUES('pending')")
    migrate(conn, target)
    assert conn.execute("SELECT ingested_at FROM corpus.corpus_sources").fetchone()[0] is None
    source(conn, "new", "2024-03-03T00:00:00Z")
    source(conn, "retired_before_success", "2024-03-02T00:00:00Z", active=False)
    conn.execute(
        "UPDATE corpus.corpus_publications SET generation=2 WHERE source_id='retired_before_success'"
    )
    conn.execute(
        "UPDATE corpus.corpus_publications SET generation=3, active_build_id=source_id, activated_at='2024-03-04T00:00:00Z' WHERE source_id='retired_before_success'"
    )
    with conn.transaction(force_rollback=True):
        source(conn, "rollback", "2024-03-01T00:00:00Z")
    assert (
        conn.execute(
            "SELECT count(*) FROM corpus.corpus_sources WHERE source_id='rollback'"
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT ingested_at FROM corpus.corpus_sources WHERE source_id='retired_before_success'"
        )
        .fetchone()[0]
        .isoformat()
        == "2024-03-04T00:00:00+00:00"
    )
    conn.execute(
        "UPDATE corpus.corpus_publications SET generation=2, activated_at=now() WHERE source_id='new'"
    )
    assert (
        conn.execute("SELECT ingested_at FROM corpus.corpus_sources WHERE source_id='new'")
        .fetchone()[0]
        .isoformat()
        == "2024-03-03T00:00:00+00:00"
    )


def seed_search(conn, target):
    migrate(conn, target)
    for sid, stamp, scoretext in [
        ("before", "2024-02-29T15:59:59Z", "topic " * 25),
        ("start", "2024-02-29T16:00:00Z", "topic"),
        ("last", "2024-03-01T15:59:59.999999Z", "topic"),
        ("next", "2024-03-01T16:00:00Z", "topic " * 25),
    ]:
        source(conn, sid, stamp)
        conn.execute("INSERT INTO corpus.corpus_admissions(decision_id) VALUES(%s)", (sid,))
        conn.execute("INSERT INTO corpus.corpus_builds VALUES(%s,%s)", (sid, sid))
        conn.execute(
            "INSERT INTO corpus.corpus_chunks VALUES(%s,%s,'paragraph','Title','{}','{}',%s)",
            (sid, sid, scoretext),
        )


def test_lexical_filter_includes_full_local_day_and_precedes_limit(pg):
    conn, target = pg
    seed_search(conn, target)
    with conn.cursor() as cur:
        params = build_search_params(
            "topic", ingested_from="2024-03-01", ingested_to="2024-03-01", limit=1
        )
        hits = search_chunks_on(cur, params)
        assert len(hits) == 1
        assert hits[0].source_id in {"start", "last"}
        assert hits[0].published is None
        assert hits[0].ingested_at is not None
        params["limit"] = 20
        assert {h.source_id for h in search_chunks_on(cur, params)} == {"start", "last"}
        params = build_search_params("", ingested_from="2024-03-01", ingested_to="2024-03-01")
        assert {h.source_id for h in search_chunks_on(cur, params)} == {"start", "last"}
        params = build_search_params("", published_from="2024-03-01", ingested_from="2024-03-01")
        assert search_chunks_on(cur, params) == ()  # unknown publication dates excluded only here


def test_dense_filter_precedes_limit_and_matches_lexical_dates(pg):
    conn, target = pg
    seed_search(conn, target)
    conn.execute("""CREATE EXTENSION IF NOT EXISTS vector;
        CREATE SCHEMA corpus_retrieval;
        CREATE TABLE corpus_retrieval.source_metadata(source_id text, metadata_hash text);
        CREATE TABLE corpus_retrieval.chunk_vectors(profile text, source_id text, build_id text,
            chunk_id text, input_text text, section_path text[], metadata_hash text, input_hash text);
        CREATE TABLE corpus_retrieval.embeddings(profile text, input_hash text, status text,
            dimensions integer, embedding vector(2));
        INSERT INTO corpus_retrieval.chunk_vectors
            SELECT 'test',build_id,build_id,chunk_id,search_text,section_path,'',build_id
            FROM corpus.corpus_chunks;
        INSERT INTO corpus_retrieval.embeddings
            SELECT 'test',source_id,'ready',2,
                CASE WHEN source_id IN ('before','next') THEN '[1,0]'::vector
                     ELSE '[0.8,0.2]'::vector END FROM corpus.corpus_sources;
    """)
    params = build_search_params(
        "topic", ingested_from="2024-03-01", ingested_to="2024-03-01", limit=1
    )
    params.update(
        vector="[1,0]", profile="test", dimensions=2, input_variant="published-search-text-v1"
    )
    hits = conn.execute(filter_sql(_VECTOR_SQL, params), params).fetchall()
    assert len(hits) == 1 and hits[0][0] in {"start", "last"}
    params["limit"] = 20
    assert {r[0] for r in conn.execute(filter_sql(_VECTOR_SQL, params), params)} == {
        "start",
        "last",
    }
