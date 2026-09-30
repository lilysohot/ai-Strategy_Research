"""E4 分层评分器纯函数测试。

覆盖 `docs/data_clean_dos/03-end-to-end-validation.md` §5 E4：判定链路与五类缺陷
分类（漏提取 L2／误清洗 L3／漏检索 L5／截断 L7·L8／错用结构 L9）。仅依赖
``e4_scorer.py`` 纯函数，不读库、不调模型、不需环境 —— 直接运行。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".scratch" / "corpus-access-validation"
sys.path.insert(0, str(SCRATCH))

from e4_scorer import (  # noqa: E402
    L1,
    L2,
    L3,
    L4,
    L5,
    L6,
    L7,
    L8,
    L9,
    classify_failure,
    norm,
    score_consumption,
    score_prep,
    score_target,
    self_check,
    value_tokens,
)


def _all_pass_prep() -> dict:
    return {
        "source_present": True,
        "in_reader_contiguous": True,
        "reader_tokens_present": True,
        "has_reader_tokens": True,
        "in_clean_contiguous": True,
        "clean_tokens_present": True,
        "single_chunk_hit": True,
        "offered_contains": True,
    }


def _target() -> dict:
    return {
        "target_id": "t1",
        "verbatim_quote": "我们维持26-28年EPS预测值67.74元，维持强推评级。",
        "quote": "我们维持26-28年EPS预测值67.74元，维持强推评级。",
        "period": "2026E",
        "unit": "元",
        "row": None,
        "col": None,
        "cell": None,
    }


def test_classify_failure_mapping() -> None:
    assert classify_failure(L2) == "漏提取"
    assert classify_failure(L3) == "误清洗"
    assert classify_failure(L5) == "漏检索"
    assert classify_failure(L7) == "截断"
    assert classify_failure(L8) == "截断"
    assert classify_failure(L9) == "错用结构"
    # L1 前置、L4 诊断用、L6 模型使用 → 不属五类缺陷。
    for layer in (L1, L4, L6):
        assert classify_failure(layer) is None


def test_norm_strips_all_whitespace() -> None:
    assert norm("a b\nc　d\u200be") == "abcde"


def test_value_tokens_extracts_numeric() -> None:
    vals = value_tokens("维持业绩 67.74 亿元、同降 2.0%，预测 (138) 百万")
    assert "67.74" in vals
    assert "2.0%" in vals
    assert "(138)" in vals


def test_all_pass_target() -> None:
    cons = {
        "requested_covers": True,
        "fetched_text": _target()["verbatim_quote"],
        "final_input_text": f"{_target()['verbatim_quote']} 2026E",
        "answer_text": _target()["verbatim_quote"],
    }
    v = score_target(_target(), _all_pass_prep(), cons)
    assert v["all_pass"] is True
    assert v["first_fail"] is None
    assert v["failure_class"] is None


def test_consumption_na_without_run() -> None:
    layers, _ = score_consumption(_target(), None)
    for layer in (L6, L7, L8, L9):
        assert layers[layer] == "n/a"


def test_each_defect_class_detected() -> None:
    """五类缺陷在预期层报 fail，且分类正确（准入标准 protocol §6.4）。"""
    for entry in self_check():
        assert entry["ok"], entry
        assert entry["expect_class"] == entry["got_class"]


def test_leak_extraction_l2() -> None:
    prep = {
        **_all_pass_prep(),
        "in_reader_contiguous": False,
        "reader_tokens_present": False,
        "in_clean_contiguous": False,
        "clean_tokens_present": False,
    }
    layers, _ = score_prep(prep)
    assert layers[L2] == "fail"
    v = score_target(_target(), prep, None)
    assert v["first_fail"] == L2
    assert v["failure_class"] == "漏提取"


def test_over_clean_l3() -> None:
    prep = {
        **_all_pass_prep(),
        "in_clean_contiguous": False,
        "clean_tokens_present": False,
    }
    layers, _ = score_prep(prep)
    assert layers[L3] == "fail"  # L2 已提取，clean 层误排除
    v = score_target(_target(), prep, None)
    assert v["first_fail"] == L3
    assert v["failure_class"] == "误清洗"


def test_miss_offer_l5() -> None:
    prep = {**_all_pass_prep(), "offered_contains": False}
    layers, _ = score_prep(prep)
    assert layers[L5] == "fail"
    v = score_target(_target(), prep, None)
    assert v["first_fail"] == L5
    assert v["failure_class"] == "漏检索"


def test_truncate_l7() -> None:
    cons = {
        "requested_covers": True,
        "fetched_text": _target()["verbatim_quote"][:10],
        "final_input_text": "",
        "answer_text": "",
    }
    v = score_target(_target(), _all_pass_prep(), cons)
    assert v["first_fail"] == L7
    assert v["failure_class"] == "截断"


def test_misuse_structure_l9() -> None:
    cons = {
        "requested_covers": True,
        "fetched_text": _target()["verbatim_quote"],
        "final_input_text": f"{_target()['verbatim_quote']} 2026E",
        "answer_text": "维持强推评级，但未给出 EPS 数值。",
    }
    v = score_target(_target(), _all_pass_prep(), cons)
    assert v["first_fail"] == L9
    assert v["failure_class"] == "错用结构"
