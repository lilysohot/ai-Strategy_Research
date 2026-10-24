"""Precision improvements must preserve partial, qualified and attributable evidence."""

from types import SimpleNamespace

import pytest

from plugins.corpus.retrieval.display import compose_with_evidence, select_passages
from plugins.corpus.retrieval.native import NativeBlock
from plugins.corpus.retrieval.purity import select_sources
from plugins.corpus.retrieval.text_quality import comparison_text, noise_reason


def choose(query, texts, *, notes=None, names=None):
    groups, chunks = {}, {}
    for i, text in enumerate(texts):
        bid = str(i)
        groups[bid] = [NativeBlock(bid, bid, bid, None, text, ())]
        chunks[bid, bid] = {
            "search_text": text,
            "index_text": (notes or {}).get(i, "") + "\n" + text,
            "title_text": None,
        }
    return select_sources(groups, chunks, query, (), names=names or {})


COMPANY = {"0": ("2026-研究-贵州茅台-600519-事件.pdf",)}


def test_company_price_query_does_not_return_property_or_stock_price():
    decisions = choose(
        "茅台 调价 批价 成交价 联动",
        ["茅台调价后，批价与成交价联动。", "二手房成交价回落。", "联动科技发布季度财报。"],
        names=COMPANY,
    )
    assert [d.keep for d in decisions] == [True, False, False]


def test_company_risks_are_retained_but_other_industry_risks_are_not():
    decisions = choose(
        "茅台 稳价 风险 批价回落",
        [
            "茅台稳价仍面临批价回落风险。",
            "风险提示：消费复苏不及预期。",
            "二手房租金回落风险上升。",
        ],
        names={**COMPANY, "1": ("2026-研究-贵州茅台-600519-中报.pdf",)},
    )
    assert [d.keep for d in decisions] == [True, True, False]


def test_comparison_keeps_each_company_without_requiring_all_subjects_in_one_source():
    decisions = choose(
        "贵州茅台与光力科技的收入、利润、现金流分别如何？",
        ["贵州茅台收入利润现金流稳健。", "本公司收入上升，但现金回款滞后。"],
        names={**COMPANY, "1": ("研究-光力科技-300480-中报.pdf",)},
    )
    assert all(d.keep for d in decisions)


def test_context_note_can_supply_implicit_subject_with_real_body_facets():
    decisions = choose(
        "茅台 稳价 风险 批价回落",
        ["茅台稳价面临批价回落风险。", "公司通过调整供给，改善批价回落风险。"],
        notes={1: "贵州茅台渠道管理章节"},
        names=COMPANY,
    )
    assert all(d.keep for d in decisions)


def test_compound_technical_query_keeps_source_answering_only_second_topic():
    decisions = choose(
        "AI数据中心800V高压直流与液冷的技术方向是什么？",
        ["AI数据中心采用800V高压直流供电。", "Meta推出液冷网络机柜，提升散热能力。"],
    )
    assert all(d.keep for d in decisions)


def test_partial_topic_does_not_override_named_subject_constraint():
    decisions = choose(
        "茅台批价与成交价如何联动？",
        ["茅台批价与成交价联动。", "二手房成交价回落。"],
        names=COMPANY,
    )
    assert [d.keep for d in decisions] == [True, False]


def test_context_note_does_not_turn_unrelated_body_into_company_evidence():
    decisions = choose(
        "茅台 稳价 风险 批价回落",
        ["茅台稳价面临批价回落风险。", "三友化工产品价格上涨。"],
        notes={1: "本章配有茅台批价图表，并讨论化工标的。"},
        names=COMPANY,
    )
    assert [d.keep for d in decisions] == [True, False]


def test_high_facet_coverage_with_unknown_subject_is_conservatively_retained():
    decisions = choose(
        "茅台 调价 批价 成交价 联动 风险",
        ["茅台调价，批价与成交价联动，有风险。", "Kweichow Moutai调价，批价与成交价联动，有风险。"],
        names=COMPANY,
    )
    assert all(d.keep for d in decisions)


def test_semantic_first_source_survives_lack_of_word_overlap():
    decisions = choose(
        "可插拔光模块 可靠性 系统瓶颈",
        [
            "Pluggable optics encounter thermal limits; FIT must improve tenfold.",
            "可插拔光模块可靠性受到系统瓶颈影响。",
        ],
    )
    assert decisions[0].keep and decisions[0].reason == "semantic_anchor"


@pytest.mark.parametrize("query", ["稳价", "2026年8月", "xyzzy", ""])
def test_sparse_or_unknown_query_does_not_claim_no_evidence(query):
    assert all(d.keep for d in choose(query, ["相关分析正文。", "另一来源正文。"]))


def test_dates_negations_and_new_values_are_not_deduplicated():
    values = [
        "2025年收入增加10%。",
        "2026年收入增加10%。",
        "2026年收入未增加10%。",
        "2026年收入增加11%。",
    ]
    assert len({comparison_text(v) for v in values}) == 4
    assert comparison_text("利润+1.2%") != comparison_text("利润-1.2%")


def test_layout_only_duplicates_are_shown_once_with_original_offsets():
    text = "茅台批价增长10%。\n\n茅台\x01批价增长 10%。"
    block = SimpleNamespace(text=text, slices=())
    snippet, spans = compose_with_evidence([block], "茅台批价", chars_per_block=600)
    assert len(spans) == 1
    span = spans[0]
    assert snippet[span["snippet_start"] : span["snippet_end"]] == text[span["start"] : span["end"]]


def test_independent_sources_are_not_deduplicated():
    decisions = choose("公司收入 利润 现金流", ["公司收入、利润和现金流改善。"] * 2)
    assert all(d.keep for d in decisions)


def test_region_in_company_name_does_not_turn_regional_query_into_company_query():
    decisions = choose(
        "贵州 消费 投资 收入 风险",
        ["贵州消费投资收入面临风险。", "本地区消费投资存在风险。"],
        names=COMPANY,
    )
    assert all(d.keep for d in decisions)


async def test_all_filtered_tool_response_does_not_claim_corpus_absence(monkeypatch):
    import importlib
    import json

    module = importlib.import_module("plugins.tools.corpus_search")
    service = SimpleNamespace(
        search_with_coverage=lambda *a, **kw: (
            [],
            {
                "availability": "unknown",
                "purity": {"sources_filtered": 1},
            },
        )
    )
    monkeypatch.setattr(module, "get_service", lambda: service)
    payload = json.loads(await module.corpus_search.func("目标风险"))
    assert payload["ok"] and payload["hits"] == []
    assert payload["coverage"]["availability"] == "unknown"
    assert "不代表资料库无答案" in payload["hint"]


def test_disclosure_does_not_displace_relevant_passage_but_explicit_request_keeps_it():
    text = "茅台批价锚定市场成交价。\n\n分析师声明：本报告涉及贵州茅台股票。"
    block = SimpleNamespace(text=text, slices=())
    passages, _ = select_passages([block], "茅台批价", chars_per_block=600)
    assert all("声明" not in text[p.start : p.end] for p in passages)
    passages, _ = select_passages([block], "茅台分析师声明", chars_per_block=600)
    assert any("声明" in text[p.start : p.end] for p in passages)


def test_ownership_and_risk_facts_are_not_treated_as_disclosures():
    assert noise_reason("本公司持有子公司70%的股份。", "公司资产结构") is None
    assert noise_reason("风险提示：终端需求下滑，稳价效果可能不及预期。", "稳价机制") is None


def test_bare_axes_are_suppressed_but_readable_quantitative_rows_survive():
    axes = "\n".join(str(i * 500) for i in range(10)) + "\n茅台批价（元/瓶）"
    assert noise_reason(axes, "茅台批价") == "detached_chart_axes"
    assert noise_reason("2025年 收入 300\n2026年 收入 400", "收入") is None
    assert not choose("茅台批价", [axes])[0].keep


def test_qualification_stays_attached_after_noise_and_duplicate_selection():
    text = "茅台双锚机制有望稳价。但需求疲软时，效果可能不及预期。\n\n分析师声明：观点仅供参考。"
    block = SimpleNamespace(text=text, slices=())
    snippet, _ = compose_with_evidence([block], "茅台稳价", chars_per_block=600)
    assert "但需求疲软时，效果可能不及预期。" in snippet
    assert "声明" not in snippet
