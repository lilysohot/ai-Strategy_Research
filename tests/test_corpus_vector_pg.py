"""Opt-in tests against the populated isolated pilot; no real embedding API calls.

CORPUS_VECTOR_TEST_PG=1 uv run pytest tests/test_corpus_vector_pg.py -q
Only synthetic profile rows are committed. Publication mutations are rolled back.
"""

import json
import os
from dataclasses import replace
from uuid import uuid4

import pytest
from dotenv import load_dotenv

from plugins.corpus.preparation import read_pg
from plugins.corpus.preparation.search_pg import build_search_params
from plugins.corpus.retrieval import hybrid
from plugins.corpus.retrieval.cli import pilot_dsn
from plugins.corpus.retrieval.diagnostics import RetrievalTrace
from plugins.corpus.retrieval.embedding import EmbeddingError, EmbeddingResult, VectorConfig
from plugins.corpus.retrieval.index_pg import ACTIVE_SQL, VectorIndex, ready_counts
from plugins.corpus.service import CorpusService

pytestmark = pytest.mark.skipif(
    os.getenv("CORPUS_VECTOR_TEST_PG") != "1", reason="explicit isolated PG opt-in required"
)


@pytest.fixture
def pilot(monkeypatch):
    load_dotenv()
    # Register the original environment with monkeypatch before CLI changes it.
    for key in ("CORPUS_TARGET_DB", "CORPUS_DSN", "CORPUS_READ_CHAIN"):
        monkeypatch.setenv(key, os.getenv(key, ""))
    cfg = replace(VectorConfig.from_env(), revision="test-" + uuid4().hex, dimensions=1024)
    dsn = pilot_dsn(cfg)
    index = VectorIndex(dsn, cfg)
    index.initialize()
    try:
        yield index, cfg, dsn
    finally:
        with index.connect() as conn:
            conn.execute(
                "DELETE FROM corpus_retrieval.chunk_vectors WHERE profile=%s", (cfg.profile,)
            )
            conn.execute("DELETE FROM corpus_retrieval.embeddings WHERE profile=%s", (cfg.profile,))
            conn.execute("DELETE FROM corpus_retrieval.spaces WHERE profile=%s", (cfg.profile,))


def fake_vector(text, role):
    # Distinct, deterministic nonzero vectors. These test mechanics, never relevance.
    values = [0.0] * 1024
    values[0] = 1
    values[1] = (sum(map(ord, text)) % 997) / 997
    return EmbeddingResult(tuple(values), {"total_tokens": 1})


def test_incremental_reuse_retrieval_revocation_and_input_integrity(pilot, monkeypatch):
    index, cfg, dsn = pilot
    before = index.status()
    assert before["active_chunks"] > 0
    assert before["ready_chunks"] == 0
    first = index.build(fake_vector, max_requests=1)
    assert first["requests_this_run"] == 1

    # Incomplete index must fall back before a paid query call.
    monkeypatch.setattr(VectorConfig, "from_env", classmethod(lambda cls: cfg))
    monkeypatch.setattr(hybrid, "query_vector", lambda *a: pytest.fail("index incomplete"))
    fallback = hybrid.search(dsn, "行业", original_query="行业", sandbox_db=cfg.target_db)
    assert fallback[2]["retrieval"]["reason"] == "vector_index_incomplete"
    done = index.build(fake_vector, max_requests=2000)
    assert done["ready_chunks"] == done["active_chunks"]
    assert done["requests_this_run"] + 1 == before["unique_inputs"]
    again = index.build(lambda *a: pytest.fail("must reuse durable cache"), max_requests=2000)
    assert again["requests_this_run"] == 0
    # Recovery after vectors were saved but bindings were not committed needs no API.
    with index.connect() as conn:
        conn.execute("DELETE FROM corpus_retrieval.chunk_vectors WHERE profile=%s", (cfg.profile,))
    rebound = index.build(lambda *a: pytest.fail("cached vectors must rebind"), max_requests=0)
    assert rebound["ready_chunks"] == done["active_chunks"]

    monkeypatch.setattr(
        hybrid, "query_vector", lambda c, q: (fake_vector(q, "query").vector, False, {})
    )
    monkeypatch.setenv("CORPUS_RETRIEVAL_MODE", "hybrid")
    service = CorpusService(dsn)
    hits, coverage = service.search_with_coverage("行业供需变化", limit=10)
    trace = RetrievalTrace()
    traced_hits, _ = service.search_with_coverage("行业供需变化", limit=10, trace=trace)
    assert traced_hits == hits
    assert trace.status == "hybrid"
    assert trace.dense and trace.fused and trace.selected and trace.selectable_bands
    assert coverage["retrieval"]["used"] == "hybrid"
    assert hits and all(hit.build_id and hit.context_locators for hit in hits)
    views = service.evidence_previews("行业供需变化", hits)
    assert len(views) == len(hits)
    for hit, view in zip(hits, views, strict=True):
        assert set(view["core_fetch_plan"]["locators"]) <= set(hit.context_locators)
        assert view["expansion"]["locators"] == list(dict.fromkeys(hit.context_locators))
    # Exercise the existing authoritative fetch protocol for an actual vector result.
    evidence = read_pg.fetch_verbatim(
        dsn, hits[0].doc_id, hits[0].locator, sandbox_db=cfg.target_db
    )
    assert evidence.units and any(unit.raw_text for unit in evidence.units)

    params = build_search_params("行业", limit=1000)
    params.update(
        profile=cfg.profile,
        dimensions=cfg.dimensions,
        input_variant=cfg.input_variant,
        vector=json.dumps(fake_vector("行业", "query").vector),
    )
    with index.connect() as conn, conn.transaction(force_rollback=True), conn.cursor() as cur:
        cur.execute(ACTIVE_SQL)
        source, build, chunk, text, *_ = cur.fetchone()
        # Current-version checks invalidate stale text without rebuilding source data.
        cur.execute(
            "UPDATE corpus.corpus_chunks SET search_text=%s WHERE build_id=%s AND chunk_id=%s",
            (text + "测试", build, chunk),
        )
        expected, ready = ready_counts(cur, cfg)
        assert ready == expected - 1
        cur.execute(hybrid._VECTOR_SQL, params)
        assert (build, chunk) not in {(r[1], r[2]) for r in cur.fetchall()}
        # Retraction takes effect at read time even though cached vectors remain.
        cur.execute(
            "UPDATE corpus.corpus_publications SET active_build_id=NULL WHERE source_id=%s",
            (source,),
        )
        cur.execute(hybrid._VECTOR_SQL, params)
        assert source not in {r[0] for r in cur.fetchall()}
    assert index.status()["ready_chunks"] == done["active_chunks"]

    # Date filter applies before vector ranking, exactly as on the FTS channel.
    filtered = hybrid.search(
        dsn,
        "行业",
        original_query="行业",
        sandbox_db=cfg.target_db,
        published_from="9999-01-01",
    )
    assert filtered[0] == ()
    assert filtered[2]["retrieval"]["used"] == "hybrid"

    with monkeypatch.context() as patch:

        def fail_query(*args):
            raise EmbeddingError("provider_transport_uncertain", uncertain=True)

        patch.setattr(hybrid, "query_vector", fail_query)
        trace = RetrievalTrace()
        degraded = hybrid.search(
            dsn, "行业", original_query="行业", sandbox_db=cfg.target_db, trace=trace
        )
        assert trace.status == "lexical_fallback"
        assert trace.dense == () and trace.fused == trace.lexical
        assert degraded[2]["retrieval"]["reason"] == "provider_transport_uncertain"
        assert degraded[3] is None
    with monkeypatch.context() as patch:
        patch.setattr(hybrid, "_VECTOR_SQL", "SELECT nonexistent_vector_column")
        degraded = hybrid.search(dsn, "行业", original_query="行业", sandbox_db=cfg.target_db)
        assert degraded[2]["retrieval"]["reason"] == "vector_configuration_or_database_error"
        assert degraded[0]  # Lexical read works after the failed vector transaction.

    # A new model revision must not read the old vector space.
    assert VectorIndex(dsn, replace(cfg, revision="other")).status()["ready_chunks"] == 0


def test_uncertain_request_is_not_automatically_charged_again(pilot):
    index, cfg, _ = pilot
    calls = []

    def uncertain(text, role):
        calls.append(text)
        raise EmbeddingError("provider_transport_uncertain", uncertain=True)

    result = index.build(uncertain, max_requests=1)
    assert result["error_code"] == "provider_transport_uncertain"
    assert len(calls) == 1
    # Zero budget still identifies blocked unknown work without changing its state.
    retry = index.build(lambda *a: pytest.fail("unknown outcome must not retry"), max_requests=0)
    assert retry["blocked_this_run"] >= 1
    assert retry["requests_this_run"] == 0
    # Simulate a process killed after request dispatch: running is equally uncertain.
    with index.connect() as conn:
        conn.execute(
            "UPDATE corpus_retrieval.embeddings SET status='running' WHERE profile=%s",
            (cfg.profile,),
        )
    assert index.build(fake_vector, max_requests=0)["blocked_this_run"] >= 1
    explicit = index.build(fake_vector, max_requests=1, retry_uncertain=True)
    assert explicit["requests_this_run"] == 1
    assert explicit["ready_chunks"] >= 1
