"""P0a 端到端（无 LLM）。

P0a 验收里只有「跑一次 TUI」这一项需要真模型；其余五条都可以**确定性**验证，
本文件就是它们的机械形式。特别是第 6 条「手工核对 sizing 数字与
position_sizing 返回一致」——手算会累，脚本每次都算。

链路::

    position_sizing → build_strategy_card → strategy_lint → strategy.json

这个顺序本身就是设计：**先算、再组装、最后校验**，反过来的任何顺序都能让
LLM 先把数字编好再去找工具背书。
"""

from __future__ import annotations

import json

from plugins.corpus.strategy_schema import (
    POSITION_SIZING_ID,
    build_strategy_card,
    dump_strategy_json,
)
from plugins.tools.position_sizing import position_sizing
from plugins.tools.strategy_lint import strategy_lint

# stub 研报 R01 的目标价（tests/fixtures/stub_reports/R01_看多.md）
TARGET = 24.50
ENTRY_LOW, ENTRY_HIGH, STOP_LOSS = 18.60, 19.20, 17.30
CAPITAL_TOTAL = 1_000_000
RISK_BUDGET_PCT = 1.0


async def _sizing() -> dict:
    payload = await position_sizing.func(  # type: ignore[attr-defined]
        capital_total=CAPITAL_TOTAL,
        risk_budget_pct=RISK_BUDGET_PCT,
        entry_low=ENTRY_LOW,
        entry_high=ENTRY_HIGH,
        stop_loss=STOP_LOSS,
    )
    return json.loads(payload)


def _card(sizing: dict) -> dict:
    return build_strategy_card(
        symbol="LHXC.SH",
        thesis="产能爬坡打开第二成长曲线；反方认为需求端已被证伪（stub:R02）。",
        evidence=[
            {
                "source_ref": "stub:R01",
                "page": 1,
                "quote": "目标价 24.50 元",
                "kind": "forecast",
            },
            {
                "source_ref": "stub:R04",
                "page": 1,
                # 必须逐字（含标点），否则硬闸①的溯源比对直接失败
                "quote": "若季度营收同比转负，则「产能爬坡 → 收入增长」这条逻辑链失效",
                "kind": "opinion",
            },
        ],
        entry_low=ENTRY_LOW,
        entry_high=ENTRY_HIGH,
        stop_loss=STOP_LOSS,
        target=TARGET,
        invalidation="若季度营收同比转负则逻辑失效",
        horizon="3-6M",
        capital_total=CAPITAL_TOTAL,
        sizing=sizing,
    )


async def test_full_chain_produces_a_lint_clean_strategy_card():
    sizing = await _sizing()
    card = _card(sizing)
    result = json.loads(await strategy_lint.func(dump_strategy_json(card)))  # type: ignore[attr-defined]

    assert result["passed"] is True, result["errors"]
    assert result["errors"] == []
    assert result["warnings"] == []


async def test_card_sizing_is_byte_identical_to_the_tool_result():
    """硬闸②：策略卡里的 sizing 必须与 position_sizing 的返回逐字段一致。

    这也是离线校验脚本会重算的那条——字段被「顺手改一下」必须能被抓到。
    """
    sizing = await _sizing()
    card = _card(sizing)

    assert card["position"]["sizing"] == sizing
    assert card["position"]["sizing"]["computed_by"] == POSITION_SIZING_ID
    # 重算一遍，不信任字段
    assert (
        card["position"]["sizing"]["shares"] * ENTRY_HIGH
        == card["position"]["sizing"]["amount"]
    )


async def test_hand_edited_shares_are_rejected_by_recomputation():
    """把工具给的 5_200 股手动加到 5_300 股 → 重算必须抓到。

    两种情况都测：只改 shares（金额对不上）与 shares+amount 一起改（权重对不上）。
    后者是「改得比较用心」的情况，正是离线脚本之外的在线校验存在的理由。
    """
    sizing = await _sizing()

    # 只改 shares：amount 还是 5_200 股的
    lazy = dict(sizing, shares=5_300)
    result = json.loads(await strategy_lint.func(dump_strategy_json(_card(lazy))))  # type: ignore[attr-defined]
    assert result["passed"] is False
    assert any(item["code"] == "amount_mismatch" for item in result["errors"])

    # shares 与 amount 一起改，但 weight_pct 忘了改
    careful = dict(sizing, shares=5_300, amount=5_300 * ENTRY_HIGH)
    result = json.loads(await strategy_lint.func(dump_strategy_json(_card(careful))))  # type: ignore[attr-defined]
    assert result["passed"] is False
    assert any(item["code"] == "weight_mismatch" for item in result["errors"])


async def test_stub_reports_back_every_number_in_the_card():
    """硬闸①（宽松版）：卡里的关键数字能在被引用 stub 原文中逐字找到。"""
    from pathlib import Path

    fixtures = Path(__file__).parent / "fixtures" / "stub_reports"
    r01 = (fixtures / "R01_看多.md").read_text(encoding="utf-8")
    r04 = (fixtures / "R04_失效条件.md").read_text(encoding="utf-8")

    card = _card(await _sizing())
    for item in card["position"]["evidence"]:
        source = r01 if item["source_ref"] == "stub:R01" else r04
        assert item["quote"] in source, item["source_ref"]
