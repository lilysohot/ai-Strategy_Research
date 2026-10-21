"""Opt-in isolated PostgreSQL lifecycle checks; all mutations roll back.

Set CORPUS_RANKING_TEST_PG=1 and CORPUS_VECTOR_TARGET_DB to the pilot database.
No embedding requests or committed publication changes.
"""

import os

import pytest

from plugins.corpus.preparation.search_pg import build_search_params, search_chunks_on
from plugins.corpus.retrieval.ranking_pg import _CACHE, _LOCK, load_corpus_on

pytestmark = pytest.mark.skipif(
    os.getenv("CORPUS_RANKING_TEST_PG") != "1", reason="explicit isolated PG opt-in required"
)


def test_active_version_withdrawal_metadata_and_cache_snapshot(monkeypatch):
    import psycopg
    from dotenv import load_dotenv

    from plugins.corpus.retrieval.cli import pilot_dsn
    from plugins.corpus.retrieval.embedding import VectorConfig

    load_dotenv()
    for key in ("CORPUS_TARGET_DB", "CORPUS_DSN", "CORPUS_READ_CHAIN"):
        monkeypatch.setenv(key, os.getenv(key, ""))
    config = VectorConfig.from_env()
    dsn = pilot_dsn(config)  # Requires vector_pilot_* and existing target guards.
    with _LOCK:
        _CACHE.clear()
    conn = psycopg.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            original, warm = load_corpus_on(cur)
            assert not warm and original.bodies
            cached, warm = load_corpus_on(cur)
            assert warm and cached is original
            cur.execute("""
                SELECT p.source_id, p.active_build_id, b.build_id
                FROM corpus.corpus_publications p
                JOIN corpus.corpus_builds b ON b.source_id=p.source_id
                WHERE p.active_build_id IS NOT NULL AND b.build_id<>p.active_build_id
                  AND EXISTS (SELECT 1 FROM corpus.corpus_chunks c WHERE c.build_id=b.build_id)
                ORDER BY p.source_id, b.build_id LIMIT 1
            """)
            sid, active, alternate = cur.fetchone()
            # Reproduce a publication pointer advance inside a rollback-only
            # transaction. This tests the reader, not bypassing a real release gate.
            cur.execute(
                "UPDATE corpus.corpus_publications SET active_build_id=%s, "
                "generation=generation+1 WHERE source_id=%s",
                (alternate, sid),
            )
            updated, warm = load_corpus_on(cur)
            assert not warm
            assert not any(bid == active for bid, _ in updated.bodies)
            assert any(bid == alternate for bid, _ in updated.bodies)
            assert not any(a.evidence_ref.startswith(active + ":") for a in updated.aliases)
            params = build_search_params("行业 公司 收入", limit=200)
            assert not any(h.build_id == active for h in search_chunks_on(cur, params))

            # Another connection must keep the committed snapshot despite an
            # uncommitted version entering the process feature cache above.
            with psycopg.connect(dsn) as reader, reader.cursor() as other:
                other.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                concurrent, _ = load_corpus_on(other)
                assert concurrent is original

            cur.execute(
                "UPDATE corpus.corpus_publications SET active_build_id=NULL, "
                "generation=generation+1 WHERE source_id=%s",
                (sid,),
            )
            withdrawn, warm = load_corpus_on(cur)
            assert not warm
            assert not any(bid in (active, alternate) for bid, _ in withdrawn.bodies)
            assert sid not in withdrawn.companies and sid not in withdrawn.issuers
            assert not any(h.source_id == sid for h in search_chunks_on(cur, params))

            # Source metadata and names are mutable independently of build IDs.
            other_sid = next(iter(withdrawn.issuers))
            cur.execute(
                "UPDATE corpus_retrieval.source_metadata SET institution=%s WHERE source_id=%s",
                ("回归专用证券", other_sid),
            )
            changed, warm = load_corpus_on(cur)
            assert not warm and changed.issuers[other_sid] == "回归专用"
            cur.execute(
                "UPDATE corpus.corpus_sources SET original_names="
                "ARRAY['测试-新增公司-123456-报告.pdf'] WHERE source_id=%s",
                (other_sid,),
            )
            renamed, warm = load_corpus_on(cur)
            assert not warm and renamed.companies[other_sid] == "新增公司"
    finally:
        conn.rollback()
        conn.close()
    with psycopg.connect(dsn) as restored, restored.cursor() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        actual, _ = load_corpus_on(cur)
        assert actual.bodies == original.bodies
        assert actual.aliases == original.aliases
        assert actual.issuers == original.issuers
        with _LOCK:
            assert len(_CACHE) <= 2
