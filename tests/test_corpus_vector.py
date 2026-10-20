"""Provider contract, cache isolation, fusion and final evidence-band delivery."""

import json
from dataclasses import replace

import httpx
import pytest

from plugins.corpus.preparation.search_pg import SearchHit
from plugins.corpus.retrieval import hybrid
from plugins.corpus.retrieval.context import (
    SourceMetadata,
    contextual_model_input,
    deterministic_context_prefix,
)
from plugins.corpus.retrieval.embedding import (
    DoubaoEmbedder,
    EmbeddingError,
    VectorConfig,
    validate_vector,
)
from plugins.corpus.service import CorpusService


def hit(source, chunk, score=1.0):
    return SearchHit(source, "build-" + source, chunk, "paragraph", "", (), (), score)


def test_provider_text_contract_and_distinct_instructions():
    calls = []
    cfg = VectorConfig(api_key="test-secret", dimensions=1024)

    def handler(request):
        calls.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer test-secret"
        return httpx.Response(
            200,
            json={
                "data": {"embedding": [1.0] + [0.0] * 1023},
                "usage": {"total_tokens": 9},
            },
        )

    provider = DoubaoEmbedder(cfg, transport=httpx.MockTransport(handler))
    assert provider.embed("原文", "document").usage == {"total_tokens": 9}
    provider.embed("问题", "query")
    assert calls[0]["input"] == [{"type": "text", "text": "原文"}]
    assert calls[0]["instructions"] == cfg.document_instruction
    assert calls[1]["instructions"] == cfg.query_instruction
    assert calls[0]["instructions"] != calls[1]["instructions"]
    assert calls[0]["dimensions"] == 1024
    assert "test-secret" not in repr(cfg)


@pytest.mark.parametrize(
    "base",
    [
        "https://ark.cn-beijing.volces.com/api/plan/v3",
        "https://ark.cn-beijing.volces.com/api/plan/v3/",
        "https://ark.cn-beijing.volces.com/api/v3",
    ],
)
def test_ark_base_url_and_environment_override_reach_actual_request(monkeypatch, base):
    monkeypatch.setenv("CORPUS_VECTOR_API_URL", base)
    monkeypatch.setenv("CORPUS_VECTOR_API_KEY", "test-only")
    monkeypatch.setenv("CORPUS_VECTOR_MODEL", "doubao-embedding-vision")
    monkeypatch.setenv("CORPUS_VECTOR_REVISION", "user-pinned-revision")
    monkeypatch.setenv("CORPUS_VECTOR_DIMENSIONS", "1024")
    cfg = VectorConfig.from_env()
    expected = base.rstrip("/") + "/embeddings/multimodal"
    assert cfg.api_url == expected
    assert cfg.model == "doubao-embedding-vision"
    assert cfg.revision == "user-pinned-revision"

    def handler(request):
        payload = json.loads(request.content)
        assert str(request.url) == expected
        assert payload["model"] == "doubao-embedding-vision"
        assert "revision" not in payload  # Local cache identity, not a provider parameter.
        return httpx.Response(200, json={"data": {"embedding": [1.0] + [0.0] * 1023}})

    DoubaoEmbedder(cfg, transport=httpx.MockTransport(handler)).embed("测试", "document")


@pytest.mark.parametrize("value", [[0, 0], [1], [float("nan"), 1], [True, 1], ["1", 2]])
def test_invalid_vectors_rejected(value):
    with pytest.raises(EmbeddingError):
        validate_vector(value, 2)


@pytest.mark.parametrize("status,uncertain", [(401, False), (429, False), (503, True)])
def test_http_failure_does_not_leak_provider_body(status, uncertain):
    cfg = VectorConfig(api_key="secret")
    provider = DoubaoEmbedder(
        cfg,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, text="secret report or credential")
        ),
    )
    with pytest.raises(EmbeddingError) as error:
        provider.embed("report", "document")
    assert error.value.uncertain is uncertain
    assert str(error.value) == f"provider_http_{status}"


def test_timeout_and_malformed_success_are_uncertain():
    def fail(request):
        raise httpx.ReadTimeout("unsafe body", request=request)

    for transport in (
        httpx.MockTransport(fail),
        httpx.MockTransport(lambda request: httpx.Response(200, json={"data": []})),
    ):
        with pytest.raises(EmbeddingError) as error:
            DoubaoEmbedder(VectorConfig(api_key="x"), transport=transport).embed("x", "query")
        assert error.value.uncertain
        assert "unsafe" not in str(error.value)


def test_profile_changes_for_semantics_but_not_secret_or_timeout():
    cfg = VectorConfig()
    assert replace(cfg, api_key="changed", timeout=8).profile == cfg.profile
    for other in (
        replace(cfg, revision="new"),
        replace(cfg, dimensions=1024),
        replace(cfg, query_instruction="different"),
        replace(cfg, document_instruction="different"),
        replace(cfg, input_variant="reviewed-context-prefix-v1"),
    ):
        assert other.profile != cfg.profile


def test_reported_model_drift_is_rejected_before_vector_is_cached():
    cfg = VectorConfig(api_key="test-only", model="doubao-embedding-vision", dimensions=1024)
    provider = DoubaoEmbedder(
        cfg,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "model": "doubao-embedding-vision-250615",
                    "data": {"embedding": [1.0] + [0.0] * 1023},
                },
            )
        ),
    )
    with pytest.raises(EmbeddingError, match="embedding_model_revision_mismatch"):
        provider.embed("文本", "document")


def test_complete_endpoint_and_base_url_use_same_space(monkeypatch):
    monkeypatch.setenv("CORPUS_VECTOR_API_URL", "https://ark.cn-beijing.volces.com/api/plan/v3")
    base = VectorConfig.from_env()
    monkeypatch.setenv("CORPUS_VECTOR_API_URL", base.api_url)
    complete = VectorConfig.from_env()
    assert base.api_url == complete.api_url
    assert base.profile == complete.profile


def test_query_cache_isolates_profiles(monkeypatch):
    calls = []
    from plugins.corpus.retrieval.embedding import EmbeddingResult

    def embed(self, text, role):
        calls.append((self.config.profile, text, role))
        return EmbeddingResult((1.0,), {"total_tokens": 3})

    monkeypatch.setattr(DoubaoEmbedder, "embed", embed)
    hybrid._QUERY_CACHE.clear()
    cfg = VectorConfig()
    assert hybrid.query_vector(cfg, "问题")[1] is False
    assert hybrid.query_vector(cfg, "问题")[1] is True
    assert hybrid.query_vector(replace(cfg, revision="other"), "问题")[1] is False
    assert len(calls) == 2


def test_rrf_duplicate_does_not_vote_twice_and_retains_vector_only_source():
    a, b, c = hit("a", "a1"), hit("a", "a2"), hit("c", "c1")
    first = hybrid.fuse((a, b), (c, b))
    assert first == hybrid.fuse((a, a, b), (c, c, b))
    assert {h.source_id for h in first} == {"a", "c"}
    assert first[0].chunk_id == "a2"


def test_hybrid_selection_keeps_vector_band_and_true_lexical_band():
    svc = CorpusService.__new__(CorpusService)
    lexical = (hit("a", "c0", 100),)
    # Strong semantic evidence at the other end of a document, absent from FTS.
    fused = (hit("a", "c20", 0.03), hit("a", "c0", 0.01))
    selected = svc._selected_context_hits(
        fused,
        {"a": tuple(f"c{i}" for i in range(21))},
        2,
        lexemes=("行业",),
        lexical_fallback_hits=lexical,
    )
    assert [h.chunk_id for h in selected] == ["c20", "c0"]
    assert all(len(h.context_chunk_ids) < 21 for h in selected)


def test_wrong_target_falls_back_without_query_embedding(monkeypatch):
    monkeypatch.setattr(hybrid.read_pg, "search_with_coverage_bands", lambda *a, **kw: ((), {}, {}))
    monkeypatch.setattr(
        hybrid, "query_vector", lambda *a: pytest.fail("wrong target must not call provider")
    )
    result = hybrid.search("unused", "x", original_query="x", sandbox_db="postgres")
    assert result[2]["retrieval"]["reason"] == "vector_target_mismatch"


def test_reviewed_context_is_deterministic_and_separate_from_source_text():
    metadata = SourceMetadata(
        source_id="a" * 64,
        report_title="  半导体  行业周报 ",
        institution="研究所",
        confirmed_publication_date="2026-09-06",
        field_evidence={
            "report_title": ("chunk:heading:1",),
            "institution": ("chunk:footer:1",),
            "confirmed_publication_date": ("chunk:first-page:1",),
        },
        reviewed_by="reviewer",
        reviewed_at="2026-10-20T12:00:00+08:00",
    )
    prefix = deterministic_context_prefix(metadata, (" 行业 ", " 供需  跟踪 "))
    assert prefix == (
        "[来源元数据]\n"
        "报告标题：半导体 行业周报\n"
        "研究机构：研究所\n"
        "已确认发布日期：2026-09-06\n"
        "章节路径：行业 > 供需 跟踪"
    )
    assert contextual_model_input(prefix, "逐字原文") == prefix + "\n[原文片段]\n逐字原文"


def test_reviewed_context_requires_evidence_and_iso_date():
    with pytest.raises(EmbeddingError, match="report_title_evidence_missing"):
        SourceMetadata(
            source_id="a" * 64,
            report_title="标题",
            institution=None,
            confirmed_publication_date=None,
            field_evidence={},
            reviewed_by="reviewer",
            reviewed_at="2026-10-20T12:00:00+08:00",
        )
    with pytest.raises(EmbeddingError, match="date_invalid"):
        SourceMetadata(
            source_id="a" * 64,
            report_title="标题",
            institution=None,
            confirmed_publication_date="2026-9-6",
            field_evidence={"report_title": ("chunk:heading:1",)},
            reviewed_by="reviewer",
            reviewed_at="2026-10-20T12:00:00+08:00",
        )
