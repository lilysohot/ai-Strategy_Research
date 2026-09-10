"""strategy_lint 单测：确保「不合规策略一定被拒」。

最重要的一条是 ``test_missing_computed_by_is_error``：它是硬闸②的回归测试。
它保证**任何绕过 position_sizing 自行编造仓位的策略都无法通过校验**——
这条测试一旦变绿，整个 P0a 的意义就没了。
"""

from __future__ import annotations

import copy
import json

import pytest

from plugins.corpus.strategy_schema import (
    POSITION_SIZING_ID,
    STRATEGY_LINT_ID,
    build_strategy_card,
)
from plugins.tools.strategy_lint import strategy_lint

# 一张合规卡：价格关系 / 风险预算 / 权重 / 失效条件 / 时间窗 / 整手 全部满足，
# 风险收益比 (24.50-19.20)/(19.20-17.30) = 2.79 >= 1.5，无 WARN。
_VALID: dict = {
    "version": 1,
    "capital_total": 1_000_000,
    "position": {
        "symbol": "LHXC.SH",
        "thesis": "产能爬坡打开第二成长曲线",
        # 必须含至少一条 kind=fact（否则 evidence_no_fact）；quote 逐字取自
        # tests/fixtures/stub_reports/R01_看多.md
        "evidence": [
            {
                "source_ref": "stub:R01",
                "page": 1,
                "quote": "公司 2025 年全年营业收入为 47.3 亿元，同比增长 18.6%。",
                "kind": "fact",
            },
            {
                "source_ref": "stub:R01",
                "page": 1,
                "quote": "目标价 24.50 元",
                "kind": "forecast",
            },
        ],
        "entry": {"low": 18.60, "high": 19.20},
        "stop_loss": 17.30,
        "target": 24.50,
        "invalidation": "若季度营收同比转负则逻辑失效",
        "horizon": "3-6M",
        "sizing": {
            "risk_budget_pct": 1.0,
            "shares": 5_200,
            "amount": 99_840.0,
            "weight_pct": 9.984,
            "max_weight_pct": 40.0,
            "lot_size": 100,
            "constrained_by": "risk",
            "computed_by": POSITION_SIZING_ID,
        },
    },
    "lint": {},
    "disclaimer": "本研究性推演不构成投资建议，不涉及任何交易执行。",
    # evidence.source_ref 的解析表：strategy_lint 用它识别悬空引用
    "sources": [
        {
            "id": "stub:R01",
            "title": "蓝海新材（LHXC.SH）首次覆盖（stub）",
            "url": "file://tests/fixtures/stub_reports/R01_看多.md",
        },
    ],
}


def _card() -> dict:
    return copy.deepcopy(_VALID)


async def _lint(card: dict) -> dict:
    payload = json.dumps(card, ensure_ascii=False)
    return json.loads(await strategy_lint.func(payload))


def _codes(result: dict) -> set[str]:
    return {item["code"] for item in result["errors"]}


def _warn_codes(result: dict) -> set[str]:
    return {item["code"] for item in result["warnings"]}


# ── 正向 ────────────────────────────────────────────────────────────────


async def test_valid_card_passes():
    result = await _lint(_card())
    assert result["passed"] is True
    assert result["errors"] == []
    assert result["warnings"] == []


async def test_lint_result_is_stamped_with_checked_by():
    """离线校验要能确认这份结果确实出自 strategy_lint。"""
    result = await _lint(_card())
    assert result["checked_by"] == STRATEGY_LINT_ID


# ── ERROR：价格关系 ─────────────────────────────────────────────────────


async def test_stop_loss_not_below_entry_low_is_error():
    card = _card()
    card["position"]["stop_loss"] = 19.00  # > entry.low 18.60
    result = await _lint(card)
    assert result["passed"] is False
    assert "stop_loss_not_below_entry" in _codes(result)


async def test_entry_low_not_below_entry_high_is_error():
    card = _card()
    card["position"]["entry"] = {"low": 19.20, "high": 18.60}
    result = await _lint(card)
    assert result["passed"] is False
    assert "entry_range_inverted" in _codes(result)


async def test_target_not_above_entry_high_is_error():
    card = _card()
    card["position"]["target"] = 19.00
    result = await _lint(card)
    assert result["passed"] is False
    assert "target_not_above_entry" in _codes(result)


async def test_missing_stop_loss_is_error():
    card = _card()
    del card["position"]["stop_loss"]
    result = await _lint(card)
    assert result["passed"] is False
    assert "missing_stop_loss" in _codes(result)


# ── ERROR：风险预算 / 权重 ──────────────────────────────────────────────


async def test_risk_budget_below_floor_is_error():
    card = _card()
    card["position"]["sizing"]["risk_budget_pct"] = 0.05
    result = await _lint(card)
    assert result["passed"] is False
    assert "risk_budget_out_of_range" in _codes(result)


async def test_risk_budget_above_ceiling_is_error():
    card = _card()
    card["position"]["sizing"]["risk_budget_pct"] = 8.0
    result = await _lint(card)
    assert result["passed"] is False
    assert "risk_budget_out_of_range" in _codes(result)


async def test_weight_over_max_weight_is_error():
    card = _card()
    card["position"]["sizing"]["weight_pct"] = 55.0  # > max_weight_pct 40
    result = await _lint(card)
    assert result["passed"] is False
    assert "weight_over_limit" in _codes(result)


# ── ERROR：必填字段 ─────────────────────────────────────────────────────


async def test_empty_invalidation_is_error():
    card = _card()
    card["position"]["invalidation"] = "   "
    result = await _lint(card)
    assert result["passed"] is False
    assert "missing_invalidation" in _codes(result)


async def test_empty_horizon_is_error():
    card = _card()
    card["position"]["horizon"] = ""
    result = await _lint(card)
    assert result["passed"] is False
    assert "missing_horizon" in _codes(result)


async def test_horizon_outside_enum_is_error():
    card = _card()
    card["position"]["horizon"] = "3-6个月"  # 自由文本，非预设枚举
    result = await _lint(card)
    assert result["passed"] is False
    assert "horizon_not_in_enum" in _codes(result)


# ── ERROR：最小交易单位 ─────────────────────────────────────────────────


async def test_shares_below_one_lot_is_error():
    card = _card()
    card["position"]["sizing"]["shares"] = 80
    result = await _lint(card)
    assert result["passed"] is False
    assert "shares_below_one_lot" in _codes(result)


async def test_shares_not_multiple_of_lot_is_error():
    card = _card()
    card["position"]["sizing"]["shares"] = 5_250
    result = await _lint(card)
    assert result["passed"] is False
    assert "shares_not_multiple_of_lot" in _codes(result)


# ── ERROR：硬闸② 算术出工具 ─────────────────────────────────────────────


async def test_missing_computed_by_is_error():
    """硬闸②回归测试（最关键）。

    删掉 ``computed_by`` 必须 ERROR：它挡住的是「LLM 自己编一个仓位数字」
    这条路径。若这条用例变绿，说明校验已失去约束力。
    """
    card = _card()
    del card["position"]["sizing"]["computed_by"]
    result = await _lint(card)
    assert result["passed"] is False
    assert "missing_computed_by" in _codes(result)


async def test_hand_written_computed_by_is_error():
    card = _card()
    card["position"]["sizing"]["computed_by"] = "estimated_by_llm"
    result = await _lint(card)
    assert result["passed"] is False
    assert "unknown_computed_by" in _codes(result)


# ── ERROR：evidence 可溯源（硬闸①的在线形态）────────────────────────────
# 这一组是「数字可溯源」从文档口号变成在线约束的地方：没有证据、证据没有
# 页码、引用了不存在的来源、全是观点没有事实——都必须在落卡前被挡住。


async def test_missing_evidence_is_error():
    card = _card()
    del card["position"]["evidence"]
    result = await _lint(card)
    assert result["passed"] is False
    assert "missing_evidence" in _codes(result)


async def test_empty_evidence_is_error():
    card = _card()
    card["position"]["evidence"] = []
    result = await _lint(card)
    assert result["passed"] is False
    assert "evidence_empty" in _codes(result)


async def test_evidence_item_not_object_is_error():
    card = _card()
    card["position"]["evidence"] = ["目标价 24.50 元"]
    result = await _lint(card)
    assert result["passed"] is False
    assert "evidence_not_object" in _codes(result)


@pytest.mark.parametrize("key", ["source_ref", "page", "quote", "kind"])
async def test_evidence_missing_required_field_is_error(key: str):
    """溯源四键缺任一，溯源链就断一环。"""
    card = _card()
    del card["position"]["evidence"][0][key]
    result = await _lint(card)
    assert result["passed"] is False
    assert "evidence_missing_field" in _codes(result)


async def test_evidence_bad_kind_is_error():
    card = _card()
    card["position"]["evidence"][0]["kind"] = "guess"
    result = await _lint(card)
    assert result["passed"] is False
    assert "evidence_bad_kind" in _codes(result)


async def test_placeholder_page_is_error():
    """网页抓取留下的 ``page="—"`` 让硬闸①的「页码」退化成半条腿。

    这是 run 828a 产出物的真实缺陷：数据全是东方财富接口抓的，
    13 条 evidence 的 page 无一例外是 ``—``，而当时的 lint 根本不看 evidence。
    """
    card = _card()
    for item in card["position"]["evidence"]:
        item["page"] = "—"
    result = await _lint(card)
    assert result["passed"] is False
    assert "evidence_page_placeholder" in _codes(result)


@pytest.mark.parametrize("page", ["N/A", "未知", "", "-", None])
async def test_other_page_placeholders_are_error(page: object):
    card = _card()
    for item in card["position"]["evidence"]:
        item["page"] = page
    result = await _lint(card)
    assert result["passed"] is False
    assert "evidence_page_placeholder" in _codes(result)


async def test_real_page_number_passes():
    card = _card()
    card["position"]["evidence"][0]["page"] = 7
    result = await _lint(card)
    assert result["passed"] is True, result["errors"]


async def test_unknown_source_ref_is_error():
    """悬空引用：evidence 指向 sources 里根本不存在的 id。"""
    card = _card()
    card["position"]["evidence"][0]["source_ref"] = "stub:R99"
    result = await _lint(card)
    assert result["passed"] is False
    assert "evidence_unknown_source_ref" in _codes(result)


async def test_missing_sources_section_is_error():
    """没有 sources，source_ref 只是个无法解析的字符串。"""
    card = _card()
    del card["sources"]
    result = await _lint(card)
    assert result["passed"] is False
    assert "missing_sources" in _codes(result)


async def test_source_without_id_is_error():
    card = _card()
    card["sources"] = [{"title": "没有 id 的来源"}]
    result = await _lint(card)
    assert result["passed"] is False
    assert "source_missing_id" in _codes(result)


async def test_evidence_without_fact_is_error():
    """只有预测/观点、没有一条事实 = 无事实基础的推测。"""
    card = _card()
    card["position"]["evidence"] = [
        item for item in card["position"]["evidence"] if item["kind"] != "fact"
    ]
    result = await _lint(card)
    assert result["passed"] is False
    assert "evidence_no_fact" in _codes(result)


# ── WARN（不阻断）───────────────────────────────────────────────────────


async def test_too_many_tunable_params_is_warning_only():
    card = _card()
    card["position"]["parameters"] = {f"knob_{i}": i for i in range(7)}
    result = await _lint(card)
    assert result["passed"] is True
    assert "too_many_tunable_params" in _warn_codes(result)


async def test_low_risk_reward_is_warning_only():
    card = _card()
    card["position"]["target"] = 20.00  # (20.0-19.2)/(19.2-17.3) = 0.42
    result = await _lint(card)
    assert result["passed"] is True
    assert "low_risk_reward" in _warn_codes(result)


async def test_short_quote_is_warning_only():
    """过短的引用通常是「概括」而非逐字原文——提醒，不阻断。"""
    card = _card()
    card["position"]["evidence"][0]["quote"] = "47.3 亿"
    result = await _lint(card)
    assert result["passed"] is True, result["errors"]
    assert "evidence_quote_too_short" in _warn_codes(result)


async def test_duplicate_evidence_is_warning_only():
    card = _card()
    card["position"]["evidence"].append(dict(card["position"]["evidence"][0]))
    result = await _lint(card)
    assert result["passed"] is True, result["errors"]
    assert "evidence_duplicate" in _warn_codes(result)


async def test_target_without_forecast_is_warning_only():
    """目标价是「关于未来的数」，正常应由预测/观点支撑；缺了只提醒。"""
    card = _card()
    card["position"]["evidence"] = [
        item for item in card["position"]["evidence"] if item["kind"] not in ("forecast", "opinion")
    ]
    result = await _lint(card)
    assert result["passed"] is True, result["errors"]
    assert "target_without_forecast" in _warn_codes(result)


async def test_source_without_locator_is_warning_only():
    """来源既无 url 也无 title = 溯源在最后一环断掉。"""
    card = _card()
    card["sources"][0] = {"id": "stub:R01"}
    result = await _lint(card)
    assert result["passed"] is True, result["errors"]
    assert "source_missing_locator" in _warn_codes(result)


# ── 入参合法性 ──────────────────────────────────────────────────────────


async def test_invalid_json_returns_error_without_raising():
    result = json.loads(await strategy_lint.func("这不是 JSON"))
    assert result["passed"] is False
    assert _codes(result) == {"invalid_json"}


async def test_missing_position_is_error():
    result = json.loads(await strategy_lint.func(json.dumps({"version": 1})))
    assert result["passed"] is False
    assert "missing_position" in _codes(result)


async def test_non_object_json_is_error():
    result = json.loads(await strategy_lint.func("[1, 2, 3]"))
    assert result["passed"] is False
    assert "not_an_object" in _codes(result)


# ── 与 schema 模块的一致性（issue 07）───────────────────────────────────


async def test_card_built_from_schema_passes_lint():
    """schema 常量、build_strategy_card、strategy_lint 三处必须是同一套定义。"""
    card = build_strategy_card(
        symbol="LHXC.SH",
        thesis="产能爬坡打开第二成长曲线",
        evidence=[
            {
                "source_ref": "stub:R01",
                "page": 1,
                "quote": "公司 2025 年全年营业收入为 47.3 亿元，同比增长 18.6%。",
                "kind": "fact",
            },
            {
                "source_ref": "stub:R01",
                "page": 1,
                "quote": "目标价 24.50 元",
                "kind": "forecast",
            },
        ],
        entry_low=18.60,
        entry_high=19.20,
        stop_loss=17.30,
        target=24.50,
        invalidation="若季度营收同比转负则逻辑失效",
        horizon="3-6M",
        capital_total=1_000_000,
        sizing={
            "risk_budget_pct": 1.0,
            "shares": 5_200,
            "amount": 99_840.0,
            "weight_pct": 9.984,
            "max_weight_pct": 40.0,
            "lot_size": 100,
            "computed_by": POSITION_SIZING_ID,
        },
        sources=[
            {
                "id": "stub:R01",
                "title": "蓝海新材（LHXC.SH）首次覆盖（stub）",
                "url": "file://tests/fixtures/stub_reports/R01_看多.md",
            },
        ],
    )
    result = json.loads(await strategy_lint.func(json.dumps(card, ensure_ascii=False)))
    assert result["passed"] is True
    assert card["disclaimer"]
