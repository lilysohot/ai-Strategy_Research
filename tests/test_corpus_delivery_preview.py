"""Sentence integrity, scope preservation and pilot tool budget behaviour."""

import asyncio
import importlib
import json
from dataclasses import replace

import pytest

from plugins.corpus.preparation.read_pg import ChunkEvidence
from plugins.corpus.retrieval.delivery import (
    delivery_views,
    load_delivery_views,
    sentence_preview,
)
from plugins.corpus.service import SearchHit


def evidence(text, kind="body"):
    return ChunkEvidence("s", "b", "c", kind, "", (), (), text, (), (), True)


def hit():
    return SearchHit(
        "cv2:b", "chunk:c", "", "短摘要", 1, "undated",
        "s", "b", "c", ("chunk:before", "chunk:c", "chunk:after"),
    )


def test_preview_keeps_forecast_negation_decimals_and_original_offsets():
    chunk = evidence("无关背景。我们预计2028年出货500万只，并非已经实现。价格为3.2元。尾部残句")
    preview = sentence_preview(chunk, ("2028", "500万", "实现"))
    assert "预计" in preview.text and "并非" in preview.text
    assert chunk.text[preview.start:preview.end] == preview.text
    assert not preview.citation_ready
    assert preview.text.endswith("。")
    assert "尾部残句" not in preview.text
    assert "3.2元" in sentence_preview(chunk, ("3.2元",)).text


def test_no_half_sentence_or_fake_table_sentence():
    assert not sentence_preview(evidence("目标" * 400 + "。"), ("目标",)).text
    assert not sentence_preview(evidence("只有没有句末的目标"), ("目标",)).text
    assert not sentence_preview(evidence("营业收入。2026E。", "table"), ("收入",)).text


def test_neighbouring_explanation_not_repeating_query_is_preserved():
    chunk = evidence("该产品销量增加。原因是客户完成验证并开始批量采购。")
    preview = sentence_preview(chunk, ("销量",))
    assert "原因是客户完成验证" in preview.text
    assert len(preview.text) <= 600


def test_original_scope_retained_and_core_can_expand_without_cross_version_dedup():
    first = hit()
    second = replace(first, doc_id="cv2:b2", build_id="b2")
    originals = (evidence("目标原因在于需求增加。"), replace(evidence("另一版本。"), build_id="b2"))
    views = delivery_views((first, first, second), originals, ("目标",))
    assert views[0]["core_fetch_plan"]["locators"] == ["chunk:c"]
    assert views[0]["expansion"]["locators"] == list(first.context_locators)
    assert views[1]["expansion"]["remaining_after_prior_full_expansions"] == []
    assert views[2]["expansion"]["remaining_after_prior_full_expansions"] == list(
        first.context_locators
    )
    table = delivery_views((first,), (evidence("表头与数值", "table"),), ("数值",))[0]
    assert table["core_fetch_plan"]["locators"] == list(first.context_locators)


def test_identity_and_nonpilot_target_fail_closed():
    with pytest.raises(ValueError, match="identity"):
        delivery_views((hit(),), (replace(evidence("正文。"), source_id="other"),), ())
    with pytest.raises(ValueError, match="pilot_database"):
        load_delivery_views("unused", "postgres", "问题", ())


def test_real_tool_opt_in_preserves_hits_and_default_output(monkeypatch):
    module = importlib.import_module("plugins.tools.corpus_search")
    calls = []

    class Service:
        def search_with_coverage(self, query, limit):
            return [hit()], {"query_status": "matched"}

        def evidence_previews(self, query, hits):
            calls.append(query)
            return delivery_views(hits, (evidence("目标包含原因和限定。"),), ("目标",))

    monkeypatch.setattr(module, "get_service", lambda: Service())
    monkeypatch.delenv("CORPUS_EVIDENCE_PREVIEW", raising=False)
    baseline = json.loads(asyncio.run(module.corpus_search.ainvoke({"query": "目标"})))
    assert not calls and "preview" not in baseline["hits"][0]
    monkeypatch.setenv("CORPUS_EVIDENCE_PREVIEW", "pilot")
    trial = json.loads(asyncio.run(module.corpus_search.ainvoke({"query": "目标"})))
    for key in ("doc_id", "locator", "context_locators", "fetch_plan"):
        assert trial["hits"][0][key] == baseline["hits"][0][key]
    assert trial["hits"][0]["preview"]["text"] == "目标包含原因和限定。"
    assert len(calls) == 1


def test_budget_drops_preview_before_evidence_handles():
    module = importlib.import_module("plugins.tools.corpus_search")
    row = {
        "doc_id": "cv2:b", "locator": "chunk:c", "context_locators": ["chunk:c"],
        "core_fetch_plan": {"doc_id": "cv2:b", "locators": ["chunk:c"], "view": "compact"},
        "preview": {"text": "大" * 1000},
    }
    payload = {"ok": True, "count": 1, "hits": [row], "delivery_preview": "pilot"}
    fitted = json.loads(module.fit_search_payload(json.dumps(payload, ensure_ascii=False), 600))
    assert fitted["previews_elided"]
    assert len(fitted["hits"]) == 1
    assert "core_fetch_plan" in fitted["hits"][0]
    assert "preview" not in fitted["hits"][0]


def test_compacted_pilot_keeps_full_scope_and_does_not_record_preview_as_fetched():
    from plugins.corpus.ledger import ConsumptionLedger

    module = importlib.import_module("plugins.tools.corpus_search")
    row = {
        "doc_id": "cv2:b", "locator": "chunk:c", "context_locators": ["chunk:c", "chunk:d"],
        "fetch_plan": {"doc_id": "cv2:b", "locators": ["chunk:c", "chunk:d"], "view": "compact"},
        "core_fetch_plan": {"doc_id": "cv2:b", "locators": ["chunk:c"], "view": "compact"},
        "preview": {"text": "原文预览。", "citation_ready": False},
        "expansion": {"unused_diagnostics": "x" * 1000},
    }
    payload = {"ok": True, "count": 1, "hits": [row], "delivery_preview": "pilot"}
    fitted = module.fit_search_payload(json.dumps(payload, ensure_ascii=False), 800)
    parsed = json.loads(fitted)
    assert parsed["hits"][0]["context_locators"] == row["context_locators"]
    assert parsed["hits"][0]["preview"]["text"] == "原文预览。"
    assert "fetch_plan" not in parsed["hits"][0]
    ledger = ConsumptionLedger()
    ledger.record_search(fitted)
    assert ledger.offered[0]["locators"] == row["context_locators"]
    assert ledger.fetched == [] and ledger.delivered == {}
