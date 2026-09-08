"""position_sizing — 确定性仓位计算（「算术不出 LLM」的地基）。

Agent 只做定性判断（选什么、为什么），**任何仓位/金额/占比数字都必须由本工具
产出**。返回体恒带 ``computed_by``，而 ``strategy_lint`` 把它列为硬 ERROR——
于是「绕过工具自己编一个仓位」在机制上无法通过校验，而不只是靠提示词自觉。

保守口径：风险与资金占用**都按入场区间上沿**计算。上沿是最差成交价，
按它算出的仓位在任何更优成交价下都不会超预算。
"""

from __future__ import annotations

import json
import math

from frontier_agent.core.tool import tool
from plugins.corpus.strategy_schema import (
    DEFAULT_LOT_SIZE,
    DEFAULT_MAX_WEIGHT_PCT,
    POSITION_SIZING_ID,
    RISK_BUDGET_MAX_PCT,
    RISK_BUDGET_MIN_PCT,
)

# 金额保留到分，比例保留到万分之一（0.01bp）。不取整到整数是为了让
# 离线校验脚本能逐位比对，同时不引入浮点噪声（0.1+0.2 那种）。
_MONEY_DP = 2
_RATIO_DP = 4


def _round(value: float, digits: int) -> float:
    return round(float(value) + 0.0, digits)


def _as_number(value: object) -> float | None:
    """把入参转成有限 float；失败返回 ``None``。

    ``bool`` 被显式拒绝：它是 ``int`` 的子类，不挡的话 ``stop_loss=True``
    会静默变成 1.0。NaN / inf 同样拒绝——它们会让后续所有比较返回 False，
    把「止损位置不对」这类真实错误吞掉。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _validate(
    capital_total: float,
    risk_budget_pct: float,
    entry_low: float,
    entry_high: float,
    stop_loss: float,
    lot_size: int,
    max_weight_pct: float,
) -> str | None:
    """返回第一条错误描述，全部合法时返回 ``None``。

    校验顺序刻意固定：先类型/有限性，再量级，最后才是价格关系。
    这样「止损设在了入场价之上」报的是价格错误，而不是某个 NaN 污染出的
    无关信息——错误信息必须可执行，否则 Agent 只会瞎改。
    """
    for name, value in (
        ("capital_total", capital_total),
        ("risk_budget_pct", risk_budget_pct),
        ("entry_low", entry_low),
        ("entry_high", entry_high),
        ("stop_loss", stop_loss),
        ("max_weight_pct", max_weight_pct),
    ):
        if value <= 0:
            return f"{name} 必须为正数，实际 {value}"

    if lot_size < 1:
        return f"lot_size 必须为 >= 1 的整数，实际 {lot_size}"

    if not RISK_BUDGET_MIN_PCT <= risk_budget_pct <= RISK_BUDGET_MAX_PCT:
        return (
            f"risk_budget_pct 必须在 [{RISK_BUDGET_MIN_PCT}, {RISK_BUDGET_MAX_PCT}] "
            f"之间，实际 {risk_budget_pct}"
        )

    if max_weight_pct > 100:
        return f"max_weight_pct 不得超过 100，实际 {max_weight_pct}"

    if entry_low > entry_high:
        return f"entry_low 必须 <= entry_high，实际 {entry_low} > {entry_high}"

    if stop_loss >= entry_low:
        return (
            f"stop_loss 必须 < entry_low，实际 {stop_loss} >= {entry_low}"
            "（止损不在入场区间下方，本策略无风险敞口可言）"
        )
    return None


@tool
async def position_sizing(
    capital_total: float,
    risk_budget_pct: float,
    entry_low: float,
    entry_high: float,
    stop_loss: float,
    lot_size: int = DEFAULT_LOT_SIZE,
    max_weight_pct: float = DEFAULT_MAX_WEIGHT_PCT,
) -> str:
    """计算单笔仓位：风险预算与资金上限取小，向下取整到最小交易单位。

    采用保守口径：风险与资金占用均按入场区间上沿（最差成交价）计算。
    这是唯一允许产出仓位数字的途径——禁止自行计算或估算 shares / amount /
    weight_pct。返回的 ``computed_by`` 是硬闸②的校验依据，组装策略卡时
    必须原样带入 ``sizing`` 段，不得改写。

    计算过程::

        risk_per_share    = entry_high - stop_loss
        risk_amount       = capital_total * risk_budget_pct / 100
        shares_by_risk    = floor(risk_amount / risk_per_share)
        shares_by_capital = floor(capital_total * max_weight_pct / 100 / entry_high)
        shares            = min(shares_by_risk, shares_by_capital)
        shares            = floor(shares / lot_size) * lot_size

    当 ``shares_by_risk == shares_by_capital`` 时两者同时收紧，``constrained_by``
    取 ``"risk"``（风险预算是本设计的第一约束）。

    Args:
        capital_total: 总资金（元），必须为正数。
        risk_budget_pct: 单笔风险预算，占总资金的百分比（如 1.0 表示 1%）。
            必填，无默认值——缺失时必须向用户追问，不得假设。
        entry_low: 入场区间下沿（元）。
        entry_high: 入场区间上沿（元）；保守口径下按此价计算资金占用。
        stop_loss: 止损价（元），必须严格小于 entry_low。
        lot_size: 最小交易单位（股）；A 股一手为 100 股。
        max_weight_pct: 单票权重上限，占总资金的百分比。

    Returns:
        JSON 字符串。成功含 shares / amount / weight_pct / risk_per_share /
        risk_amount / constrained_by / computed_by；失败含 error。
        两种情形都带 ``ok`` 与 ``computed_by``。
    """
    raw = {
        "capital_total": capital_total,
        "risk_budget_pct": risk_budget_pct,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop_loss": stop_loss,
        "max_weight_pct": max_weight_pct,
    }
    # lot_size 先校验：它是下面所有数值校验的错误返回体里都要回显的字段，
    # 先定下来才不用在每条错误分支里重复判断它的类型。
    if isinstance(lot_size, bool) or not isinstance(lot_size, int):
        return _fail(f"lot_size 必须为整数，实际 {lot_size!r}", DEFAULT_LOT_SIZE)

    values: dict[str, float] = {}
    for name, value in raw.items():
        number = _as_number(value)
        if number is None:
            return _fail(f"{name} 必须是有限数字，实际 {value!r}", lot_size)
        values[name] = number

    error = _validate(
        values["capital_total"],
        values["risk_budget_pct"],
        values["entry_low"],
        values["entry_high"],
        values["stop_loss"],
        lot_size,
        values["max_weight_pct"],
    )
    if error:
        return _fail(error, lot_size)

    risk_per_share = values["entry_high"] - values["stop_loss"]
    risk_amount = values["capital_total"] * values["risk_budget_pct"] / 100
    capital_budget = values["capital_total"] * values["max_weight_pct"] / 100
    shares_by_risk = math.floor(risk_amount / risk_per_share)
    shares_by_capital = math.floor(capital_budget / values["entry_high"])

    if shares_by_risk <= shares_by_capital:
        constrained_by = "risk"
        shares = shares_by_risk
    else:
        constrained_by = "capital"
        shares = shares_by_capital

    shares = math.floor(shares / lot_size) * lot_size

    result: dict[str, object] = {
        "ok": True,
        "shares": shares,
        "constrained_by": constrained_by,
        "risk_per_share": _round(risk_per_share, _RATIO_DP),
        "risk_amount": _round(risk_amount, _MONEY_DP),
        "capital_budget": _round(capital_budget, _MONEY_DP),
        # 入参回显。strategy_lint 要校验风险预算区间与权重上限，而它只读
        # strategy.json——不在返回体里带上，Agent 就得自己抄一遍，
        # 那正是「数字经手一次就可能出错」的地方。
        "risk_budget_pct": values["risk_budget_pct"],
        "entry_high": values["entry_high"],
        "stop_loss": values["stop_loss"],
        "lot_size": lot_size,
        "max_weight_pct": values["max_weight_pct"],
        "computed_by": POSITION_SIZING_ID,
    }

    if shares < lot_size:
        # 不是错误，是一个合法的「仓位为零」结论。Agent 应把它报告为
        # 「当前风险预算下无法建仓」，而不是自己调大预算绕过去。
        result["constrained_by"] = "lot"
        result["reason"] = (
            f"风险预算不足以买入一手：可买 {shares_by_risk} 股（按风险）/"
            f"{shares_by_capital} 股（按资金），均不足一手 {lot_size} 股"
        )

    amount = shares * values["entry_high"]
    result["amount"] = _round(amount, _MONEY_DP)
    result["weight_pct"] = _round(
        amount / values["capital_total"] * 100 if values["capital_total"] else 0.0,
        _RATIO_DP,
    )
    return json.dumps(result, ensure_ascii=False)


def _fail(message: str, lot_size: int) -> str:
    """错误返回体。

    即使在错误路径也带上 ``computed_by``：契约是「返回体恒含 computed_by」，
    让调用方不必先判断 ok 再决定读哪个字段。错误体**不含** sizing 数值，
    所以 Agent 无法从一次失败的调用里捡到可用的数字。
    """
    return json.dumps(
        {
            "ok": False,
            "error": message,
            "shares": 0,
            "lot_size": lot_size,
            "computed_by": POSITION_SIZING_ID,
        },
        ensure_ascii=False,
    )
