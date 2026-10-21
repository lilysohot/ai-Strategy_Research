"""Ranking boundaries: request isolation, topic guard, provenance, and no deletion."""

import pytest

from plugins.corpus.preparation.read_pg import ChunkEvidence
from plugins.corpus.preparation.search_pg import SearchHit
from plugins.corpus.retrieval.ranking import (
    RankingCorpus,
    RankingSession,
    RankingSource,
    scoring_body,
)


def hit(cid, sid="s", bid="b", score=1):
    return SearchHit(
        source_id=sid,
        build_id=bid,
        chunk_id=cid,
        kind="body",
        title_text="",
        section_path=(),
        unit_refs=(),
        snippet="",
        published=None,
        score=score,
        context_chunk_ids=(cid,),
    )


def corpus(bodies):
    return RankingCorpus(
        (
            RankingSource(
                "s",
                "b",
                ("国信-光力科技-300480-报告.pdf",),
                "国信证券",
                (("u", "光力科技（300480.SZ）"),),
            ),
        ),
        bodies,
    )


def test_parallel_query_sessions_do_not_share_intent_or_results():
    data = corpus({("b", "a"): "光力科技2026年设备收入同比增长", ("b", "z"): "行业需求"})
    hits = (hit("a"), hit("z"))
    first = RankingSession("国信关于300480的报告，2026年设备收入", ("设备", "收入"))
    second = RankingSession("紫荆量子光电股份有限公司2035年收入", ("收入",))
    first.prepare(data, hits)
    expected = first.diagnostics(hits)
    second.prepare(data, hits)
    assert first.diagnostics(hits) == expected
    assert second.features[("b", "a")].match.entity_status == "not_observed"
    assert len(second.order_selected(second.rerank(hits))) == 2
    assert data.aliases[1].evidence_ref == "b:u"
    with pytest.raises(TypeError):
        data.bodies[("b", "a")] = "mutated"


def test_year_priority_cannot_replace_stronger_body_topic_or_cross_sources():
    data = corpus(
        {
            ("b", "a"): "设备收入同比增长",
            ("b", "z"): "2026年日历",
            ("other", "c"): "2026年设备收入同比增长",
        }
    )
    hits = (hit("a"), hit("z"), hit("c", "other", "other"))
    session = RankingSession("2026年设备收入", ("设备", "收入"))
    session.prepare(data, hits)
    assert session.order_selected(hits) == hits


@pytest.mark.parametrize(
    "text,promoted", [("2026年设备收入实现增长", True), ("预计2026年设备收入增长", False)]
)
def test_year_can_promote_only_supported_actual_same_source(text, promoted):
    data = corpus({("b", "a"): "设备收入增长", ("b", "z"): text})
    hits = (hit("a"), hit("z"))
    session = RankingSession("2026年实际设备收入", ("设备", "收入"))
    session.prepare(data, hits)
    ordered = session.order_selected(hits)
    assert ordered == (hits[::-1] if promoted else hits)
    assert set(ordered) == set(hits)


def test_entity_ranking_keeps_source_slots_and_version_keys():
    data = corpus(
        {("b", "same"): "华工正源", ("b", "both"): "华工正源和立讯技术", ("other", "same"): "行业"}
    )
    hits = (hit("same"), hit("both", score=0.9), hit("same", "other", "other", score=100))
    session = RankingSession("华工正源和立讯技术分别如何", ("华工", "技术"))
    session.prepare(data, hits)
    ranked = session.rerank(hits)
    assert [(h.build_id, h.chunk_id) for h in ranked] == [
        ("b", "both"),
        ("b", "same"),
        ("other", "same"),
    ]
    assert {(h.build_id, h.chunk_id, h.context_chunk_ids) for h in ranked} == {
        (h.build_id, h.chunk_id, h.context_chunk_ids) for h in hits
    }


def test_provenance_only_alias_does_not_count_as_body_entity():
    text = "华工正源\n设备收入\n资料来源：立讯技术LuxshareTech"
    evidence = ChunkEvidence(
        "s", "b", "c", "body", "", (), (), text, (), (("h", 0, 4), ("u", 5, len(text))), True
    )
    body = scoring_body(evidence, ("h",), {"h": "heading", "u": "paragraph"})
    assert body == "设备收入"
    assert evidence.text == text


def test_unprepared_fallback_preserves_hits():
    session = RankingSession("设备收入", ())
    hits = (hit("c"),)
    assert session.order_selected(hits) is hits
    assert session.diagnostics(hits)["reason"] == "hybrid_unavailable"


def test_wrong_target_rejected_before_hybrid_call(monkeypatch):
    from plugins.corpus.preparation import search_pg
    from plugins.corpus.preparation.repository import StoreError
    from plugins.corpus.service import CorpusService

    monkeypatch.setenv("CORPUS_RETRIEVAL_MODE", "hybrid")
    monkeypatch.setenv("CORPUS_RETRIEVAL_RANKING", "body-constraints-v1")
    monkeypatch.setenv("CORPUS_RETRIEVAL_RANKING_TARGET_DB", "postgres")
    monkeypatch.setenv("CORPUS_TARGET_DB", "postgres")
    monkeypatch.setenv("CORPUS_READ_CHAIN", "new")
    monkeypatch.setattr(search_pg, "query_lexemes", lambda *a, **kw: ("设备",))
    monkeypatch.setattr(CorpusService, "read_chain", lambda self: "new")
    with pytest.raises(StoreError, match="explicit matching target"):
        CorpusService("dbname=postgres").search_with_coverage("设备收入")
