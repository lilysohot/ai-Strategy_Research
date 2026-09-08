"""position_sizing 单测：锁死算术与边界行为。

这些用例的价值不在「算得对」——手工验算一遍就够了——而在于**防止后续改动
静默破坏仓位计算**。仓位数字是硬闸②唯一信任的东西，一旦它可被悄悄改掉，
整个 P0a 的意义就没了。

手算基准（保守口径，按 entry_high 计价）::

    capital_total=1_000_000, risk_budget_pct=1.0,
    entry_low=18.60, entry_high=19.20, stop_loss=17.30, lot_size=100

    risk_per_share     = 19.20 - 17.30          = 1.90
    risk_amount        = 1_000_000 * 1%         = 10_000
    shares_by_risk     = floor(10_000 / 1.9)    = 5_263
    capital_budget     = 1_000_000 * 40%        = 400_000
    shares_by_capital  = floor(400_000 / 19.2)  = 20_833
    shares             = floor(5_263 / 100)*100 = 5_200
    amount             = 5_200 * 19.20          = 99_840
    weight_pct         = 99_840 / 1_000_000*100 = 9.984
"""

from __future__ import annotations

import json

from plugins.tools.position_sizing import position_sizing

# 基准入参；每个用例只覆盖它需要改的那一项。
BASE: dict[str, float | int] = {
    "capital_total": 1_000_000,
    "risk_budget_pct": 1.0,
    "entry_low": 18.60,
    "entry_high": 19.20,
    "stop_loss": 17.30,
}


async def _run(**overrides: object) -> dict:
    args = {**BASE, **overrides}
    # ``position_sizing`` 是 @tool 装饰出的 Tool 对象；``.func`` 才是裸协程。
    return json.loads(await position_sizing.func(**args))  # type: ignore[arg-type]


# ── 基准 ────────────────────────────────────────────────────────────────


async def test_baseline_matches_hand_calculation():
    out = await _run()
    assert out["ok"] is True
    assert out["shares"] == 5_200
    assert out["amount"] == 99_840.0
    assert out["weight_pct"] == 9.984
    assert out["risk_per_share"] == 1.9
    assert out["risk_amount"] == 10_000.0
    assert out["constrained_by"] == "risk"


async def test_risk_is_the_binding_constraint():
    out = await _run(risk_budget_pct=1.0)
    assert out["constrained_by"] == "risk"
    # 风险口径买得比资金口径少，取小值
    assert out["shares"] < 20_800


async def test_capital_is_the_binding_constraint():
    out = await _run(risk_budget_pct=5.0)
    assert out["constrained_by"] == "capital"
    # floor(400_000 / 19.2) = 20_833 → 取整到手 = 20_800
    assert out["shares"] == 20_800
    assert out["amount"] == 399_360.0
    assert out["weight_pct"] == 39.936


async def test_shares_are_rounded_down_to_whole_lots():
    out = await _run()
    assert out["shares"] % 100 == 0
    # 未取整前是 5_263 股，向下取到 5_200；绝不能向上取到 5_300
    assert out["shares"] == 5_200


async def test_custom_lot_size_is_honoured():
    out = await _run(lot_size=500)
    assert out["shares"] % 500 == 0
    assert out["shares"] == 5_000


# ── 边界 ────────────────────────────────────────────────────────────────


async def test_shares_below_one_lot_returns_zero():
    # risk_amount = 10_000 * 0.1% = 10 元 → 只够 5 股，不足一手
    out = await _run(capital_total=10_000, risk_budget_pct=0.1)
    assert out["ok"] is True
    assert out["shares"] == 0
    assert out["amount"] == 0.0
    assert out["weight_pct"] == 0.0
    assert out["constrained_by"] == "lot"
    assert "不足一手" in out["reason"]


async def test_stop_loss_at_or_above_entry_low_is_rejected():
    for stop in (18.60, 19.50):  # == entry_low / > entry_low
        out = await _run(stop_loss=stop)
        assert out["ok"] is False
        assert "stop_loss" in out["error"]
        # 关键：错误返回体里不能带任何可用数字
        assert "shares" in out and out["shares"] == 0


async def test_risk_budget_below_floor_is_rejected():
    out = await _run(risk_budget_pct=0.05)
    assert out["ok"] is False
    assert "risk_budget_pct" in out["error"]


async def test_risk_budget_above_ceiling_is_rejected():
    out = await _run(risk_budget_pct=7.5)
    assert out["ok"] is False
    assert "risk_budget_pct" in out["error"]


async def test_inverted_entry_range_is_rejected():
    out = await _run(entry_low=20.0, entry_high=18.0)
    assert out["ok"] is False
    assert "entry_low" in out["error"]


async def test_non_positive_inputs_are_rejected():
    for field in ("capital_total", "entry_low", "entry_high", "stop_loss"):
        out = await _run(**{field: 0})
        assert out["ok"] is False, field
        assert field in out["error"]


async def test_non_numeric_input_is_rejected():
    out = await _run(capital_total="一百万")
    assert out["ok"] is False
    assert "capital_total" in out["error"]


async def test_nan_input_is_rejected():
    # NaN 会让所有比较返回 False，若不挡会把真正的价格错误吞掉
    out = await _run(stop_loss=float("nan"))
    assert out["ok"] is False


async def test_invalid_lot_size_is_rejected():
    out = await _run(lot_size=0)
    assert out["ok"] is False
    assert "lot_size" in out["error"]


# ── 契约 ────────────────────────────────────────────────────────────────


async def test_result_always_carries_computed_by():
    """硬闸②依赖它：成功与失败两条路径都必须带。"""
    success = await _run()
    failure = await _run(stop_loss=99.0)
    assert success["computed_by"] == "position_sizing@v1"
    assert failure["computed_by"] == "position_sizing@v1"


async def test_same_input_gives_identical_output():
    first = await _run()
    second = await _run()
    assert first == second


async def test_max_weight_pct_cap_is_applied():
    tight = await _run(risk_budget_pct=5.0, max_weight_pct=10.0)
    loose = await _run(risk_budget_pct=5.0, max_weight_pct=40.0)
    # floor(100_000 / 19.2) = 5_208 → 5_200 股
    assert tight["shares"] == 5_200
    assert tight["shares"] < loose["shares"]
    assert tight["max_weight_pct"] == 10.0
