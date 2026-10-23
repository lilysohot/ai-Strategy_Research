"""Behavioral regressions for general query-guided raw passage delivery."""

from types import SimpleNamespace

import pytest

from plugins.corpus.retrieval.display import compose, query_terms, select_passages


def block(text, page=1):
    return SimpleNamespace(text=text, slices=[SimpleNamespace(page=page)])


def texts(blocks, passages):
    return [blocks[p.block].text[p.start : p.end] for p in passages]


def test_company_name_and_metric_are_not_interchangeable():
    blocks = [block("2025年其他公司收入10亿元。"), block("2025年光力收入3.62亿元。")]
    passages, matched = select_passages(blocks, "光力2025年收入", lexemes=("光力", "2025", "收入"))
    assert matched and passages[0].block == 1


def test_unlisted_technical_topics_survive_pg_splitting():
    terms = query_terms("800V 与液冷", ("800", "v", "与", "液冷"))
    assert "800v" in terms and "液冷" in terms
    assert "800" not in terms
    blocks = [block("液冷设备交付。"), block("800V供电与液冷改造同时推进。")]
    passages, _ = select_passages(blocks, "800V 与液冷", lexemes=terms)
    assert passages[0].block == 1


@pytest.mark.parametrize(
    "query,terms,answer",
    [
        ("CRISPR off-target", ("crispr", "off-target"), "CRISPR off-target risk remains."),
        ("钙钛矿封装寿命", ("钙钛矿", "封装", "寿命"), "钙钛矿封装寿命仍受水汽影响。"),
        ("跨境物流清关延迟", ("跨境", "物流", "清关", "延迟"), "跨境物流清关延迟源于检验。"),
    ],
)
def test_no_domain_dictionary_needed(query, terms, answer):
    blocks = [block("公司发布年度经营计划。"), block(answer)]
    passages, _ = select_passages(blocks, query, lexemes=terms)
    assert passages[0].block == 1


def test_no_score_pooling_across_unrelated_sentences():
    blocks = [
        block("2025年估值有所变化。" + "说明材料。" * 25 + "2024年收入增长。"),
        block("2025年收入增长31%。"),
    ]
    passages, _ = select_passages(blocks, "2025年收入", lexemes=("2025", "收入"))
    assert passages[0].block == 1


def test_complete_answer_is_not_padded_to_budget_with_unrelated_text():
    answer = "2025年收入增长31%。"
    blocks = [block(answer + "无关背景文字" * 80 + "。")]
    passages, _ = select_passages(blocks, "2025年收入", lexemes=("2025", "收入"))
    assert texts(blocks, passages) == [answer]
    assert passages[0].complete


def test_pdf_line_wrap_does_not_sever_sentence_or_change_whitespace():
    raw = "光力科技2025年收入为\n  3.62亿元，同比增长31.16%。"
    blocks = [block(raw)]
    passages, _ = select_passages(blocks, "光力科技收入", lexemes=("光力科技", "收入"))
    assert texts(blocks, passages) == [raw]


def test_qualification_is_retained_with_answer():
    raw = "收入增长31%。但主要来自并表，原有业务持平。"
    blocks = [block(raw)]
    passages, _ = select_passages(blocks, "收入增长", lexemes=("收入", "增长"))
    assert texts(blocks, passages) == [raw]


def test_dependency_keeps_subject():
    raw = "本段讨论CPO方案。该方案降低功耗。"
    blocks = [block(raw)]
    passages, _ = select_passages(blocks, "方案功耗", lexemes=("方案", "功耗"))
    assert texts(blocks, passages) == [raw]


def test_complementary_topics_beat_duplicate_passage():
    blocks = [block("800V供电降低损耗。"), block("800V供电降低损耗。"), block("液冷采用冷板。")]
    passages, _ = select_passages(blocks, "800V与液冷", lexemes=("800v", "液冷"), max_blocks=2)
    assert {p.block for p in passages} == {0, 2}


def test_complementary_sentences_within_one_block_are_separated():
    blocks = [block("800V供电降低损耗。背景描述。液冷采用冷板。")]
    output = compose(blocks, "800V与液冷", lexemes=("800v", "液冷"))
    assert output.count("【1/1") == 2
    assert "背景描述" not in output
    assert "原文字符" in output


def test_numeric_terms_do_not_match_substrings():
    blocks = [block("12025年收入记录。"), block("2025年收入记录。")]
    passages, _ = select_passages(blocks, "2025年收入", lexemes=("2025", "收入"))
    assert passages[0].block == 1


def test_no_match_is_explicit_and_preserves_first_fused_block():
    blocks = [block("原始首条。"), block("另一条。")]
    output = compose(blocks, "引力波", lexemes=("引力波",))
    assert output.startswith("【1/2")
    assert "未找到明确的查询词匹配" in output
    assert "同源另有1块未展示" in output


def test_long_sentence_is_explicitly_partial_with_reversible_offsets():
    raw = "前文" * 110 + "钙钛矿封装寿命" + "后文" * 110 + "。"
    blocks = [block(raw)]
    passages, _ = select_passages(blocks, "钙钛矿封装", lexemes=("钙钛矿", "封装"))
    assert len(passages) == 1 and not passages[0].complete
    assert len(texts(blocks, passages)[0]) <= 180
    assert "钙钛矿" in texts(blocks, passages)[0]
    assert "句内节选，上下文不完整" in compose(blocks, "钙钛矿封装", lexemes=("钙钛矿", "封装"))


def test_page_follows_selected_raw_slice_not_first_block_page():
    first, second = "第一页背景。", "钙钛矿封装寿命受水汽影响。"
    b = SimpleNamespace(
        text=first + "\n" + second,
        slices=[
            SimpleNamespace(start=12, end=12 + len(first), page=1),
            SimpleNamespace(start=30, end=30 + len(second), page=2),
        ],
    )
    output = compose([b], "钙钛矿封装", lexemes=("钙钛矿", "封装"))
    assert "｜p2】" in output and "｜p1】" not in output


def test_discontinuous_slices_are_not_stitched_as_one_quote():
    first, second = "800V供电。", "液冷改造。"
    b = SimpleNamespace(
        text=first + "\n" + second,
        slices=[
            SimpleNamespace(start=0, end=len(first), page=1),
            SimpleNamespace(start=80, end=80 + len(second), page=1),
        ],
    )
    passages, _ = select_passages([b], "800V与液冷", lexemes=("800v", "液冷"))
    assert texts([b], passages) == [first, second]


def test_selection_does_not_mutate_block_order_or_text():
    blocks = [block("估值分析。"), block("2025年收入增长。")]
    original = [(id(b), b.text) for b in blocks]
    compose(blocks, "2025年收入", lexemes=("2025", "收入"))
    assert [(id(b), b.text) for b in blocks] == original


def test_unknown_or_mixed_page_mapping_is_not_guessed():
    b = SimpleNamespace(
        text="液冷改造。", slices=[SimpleNamespace(page=1), SimpleNamespace(page=2)]
    )
    assert "｜p" not in compose([b], "液冷", lexemes=("液冷",))


def test_question_heading_does_not_displace_the_explanation_in_next_raw_unit():
    heading, answer = "产品价格还是价差？", "应看产品价差，价格上涨不代表利润改善。"
    b = SimpleNamespace(
        text=heading + "\n" + answer,
        slices=[
            SimpleNamespace(start=0, end=len(heading), page=1),
            SimpleNamespace(start=30, end=30 + len(answer), page=1),
        ],
    )
    passages, _ = select_passages([b], "产品价格还是价差", lexemes=("产品", "价格", "价差"))
    assert answer in texts([b], passages)
    assert texts([b], passages)[0] == answer


def test_explicit_other_year_does_not_displace_requested_period():
    blocks = [
        block("2026年封测装备制造收入增长。"),
        block("2025年封测收入3.62亿元。"),
    ]
    passages, _ = select_passages(
        blocks, "2025年封测装备制造收入", lexemes=("2025", "封测", "装备", "制造", "收入")
    )
    assert passages[0].block == 1


def test_pg_single_character_splits_do_not_erase_chinese_subject():
    terms = query_terms("光力科技液冷", ("光", "力", "科技", "液", "冷"))
    assert "光力" in terms and "液冷" in terms


def test_tied_new_topic_prefers_contextually_related_passage():
    blocks = [block("800V数据中心技术方向明确。AI订单增加。800V与液冷技术共同用于数据中心。")]
    passages, _ = select_passages(
        blocks,
        "AI数据中心800V技术方向与液冷",
        lexemes=("ai", "数据中心", "800v", "技术", "方向", "液冷"),
        chars_per_block=45,
    )
    assert any("液冷" in t for t in texts(blocks, passages))


def test_equal_query_coverage_prefers_compact_complete_statement():
    blocks = [
        block("半导体装备收入取决于市场变化以及未来很多尚不能确定的条件。"),
        block("半导体装备收入3.62亿元。"),
    ]
    passages, _ = select_passages(blocks, "半导体装备收入", lexemes=("半导体", "装备", "收入"))
    assert passages[0].block == 1


def test_generic_year_and_country_do_not_outweigh_causal_subject():
    blocks = [
        block("2026年美国经济预期保持稳定。"),
        block("美国非农数据超出预期，但尚不足以驱动加息。"),
    ]
    passages, _ = select_passages(
        blocks,
        "美国2026年非农数据对加息预期的影响",
        lexemes=("美国", "2026", "非农", "数据", "加息", "预期", "影响"),
    )
    assert passages[0].block == 1


def test_verified_consecutive_raw_units_recover_wrapped_sentence():
    parts = ["产品价差的变", "化反映景气，而非单看价格。"]
    b = SimpleNamespace(
        text="\n".join(parts),
        slices=[
            SimpleNamespace(unit_id="unit:0001", start=0, end=len(parts[0]), page=1),
            SimpleNamespace(unit_id="unit:0002", start=0, end=len(parts[1]), page=2),
        ],
        unit_lengths=tuple(map(len, parts)),
    )
    output = compose([b], "产品价差景气", lexemes=("产品", "价差", "景气"))
    assert "产品价差的变\n化反映景气" in output
    assert "跨原文单元" in output and "｜p1,2】" in output


def test_partial_or_nonadjacent_raw_units_are_not_merged():
    parts = ["800V供电", "液冷改造。"]
    b = SimpleNamespace(
        text="\n".join(parts),
        slices=[
            SimpleNamespace(unit_id="unit:0001", start=0, end=len(parts[0]), page=1),
            SimpleNamespace(unit_id="unit:0002", start=0, end=len(parts[1]), page=1),
        ],
        unit_lengths=(len(parts[0]) + 10, len(parts[1])),
    )
    passages, _ = select_passages([b], "800V液冷", lexemes=("800v", "液冷"))
    assert all("\n" not in text for text in texts([b], passages))
    b.unit_lengths = tuple(map(len, parts))
    b.slices[1].unit_id = "unit:0004"
    passages, _ = select_passages([b], "800V液冷", lexemes=("800v", "液冷"))
    assert all("\n" not in text for text in texts([b], passages))


def test_long_sentence_window_does_not_anchor_only_on_early_year():
    raw = "2025年" + "背景" * 150 + "钙钛矿封装寿命得到改善" + "说明" * 120 + "。"
    blocks = [block(raw)]
    passages, matched = select_passages(
        blocks, "2025年钙钛矿封装寿命", lexemes=("2025", "钙钛矿", "封装", "寿命")
    )
    assert matched
    assert "钙钛矿封装寿命" in texts(blocks, passages)[0]
    assert not passages[0].complete
