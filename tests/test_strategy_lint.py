"""strategy_lint 单测：确保「不合规策略一定被拒」。

最重要的一条是 ``test_missing_computed_by_is_error``：它是硬闸②的回归测试。
它保证**任何绕过 position_sizing 自行编造仓位的策略都无法通过校验**——
这条测试一旦变绿，整个 P0a 的意义就没了。
"""

from __future__ import annotations

import copy
import json

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
        "evidence": [
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
    )
    result = json.loads(await strategy_lint.func(json.dumps(card, ensure_ascii=False)))
    assert result["passed"] is True
    assert card["disclaimer"]
