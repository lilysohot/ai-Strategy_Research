"""Run-bound business context tools for the Web investment worker."""

from __future__ import annotations

import contextvars
import json
import math
from decimal import Decimal, InvalidOperation
from typing import Any

from frontier_agent.core.tool import tool
from plugins.tools.position_sizing import position_sizing
from plugins.tools.strategy_lint import strategy_lint

_CONTEXT: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "investment_context", default=None
)
_METRICS: contextvars.ContextVar[dict[str, int] | None] = contextvars.ContextVar(
    "investment_context_metrics", default=None
)
_PERCENT_UNITS = frozenset({"%", "pct", "percent", "percentage"})
_CONTEXT_LINT_ID = "investment_strategy_lint@v1"


def bind_investment_context(
    context: dict[str, Any],
) -> tuple[contextvars.Token[dict[str, Any] | None], contextvars.Token[dict[str, int] | None]]:
    """Bind one immutable Run context to tool execution in this worker task."""
    return _CONTEXT.set(context), _METRICS.set(
        {"context_reads": 0, "sizing_calls": 0, "lint_calls": 0}
    )


def reset_investment_context(
    tokens: tuple[
        contextvars.Token[dict[str, Any] | None], contextvars.Token[dict[str, int] | None]
    ],
) -> None:
    _CONTEXT.reset(tokens[0])
    _METRICS.reset(tokens[1])


def investment_context_metrics() -> dict[str, int]:
    return dict(_METRICS.get() or {})


def _count(name: str) -> None:
    metrics = _METRICS.get()
    if metrics is not None:
        metrics[name] = metrics.get(name, 0) + 1


def _context() -> dict[str, Any] | None:
    return _CONTEXT.get()


def _entry_value(context: dict[str, Any], name: str) -> str | None:
    entry = (context.get("values") or {}).get(name)
    if not isinstance(entry, dict) or entry.get("status") not in {"user_provided", "resolved"}:
        return None
    value = entry.get("value")
    return str(value) if value is not None else None


def _number(context: dict[str, Any], name: str) -> float | None:
    value = _entry_value(context, name)
    if value is None:
        return None
    try:
        number = float(Decimal(value))
        return number if math.isfinite(number) else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _capital(context: dict[str, Any]) -> tuple[str | None, float | None]:
    """Select the frozen capital value required by the account's declared basis."""
    basis = (_entry_value(context, "account.capital_basis") or "").strip().lower()
    if basis in {"total", "tradable_assets"}:
        name = "account.total_capital"
        if basis == "tradable_assets" and name not in context.get("values", {}):
            name = "account.available_capital"
    elif basis == "available":
        name = "account.available_capital"
    else:
        return None, None
    return name, _number(context, name)


def _error(message: str, *, missing: list[str] | None = None) -> str:
    return json.dumps({"ok": False, "error": message, "missing": missing or []}, ensure_ascii=False)


@tool
async def investment_context() -> str:
    """读取当前 Run 的冻结业务上下文。

    返回服务端按认证用户和 Run 精确解析的最小必要快照。上下文在同一 Run 内不可变；
    需要资金、成本或计划数值时只使用此结果，不从聊天摘要或历史资料猜测。

    Returns:
        JSON 字符串；未绑定业务快照时返回 ``ok=false``。
    """
    _count("context_reads")
    context = _context()
    if context is None:
        return _error("当前 Run 未绑定业务快照")
    return json.dumps({"ok": True, "investment_context": context}, ensure_ascii=False)


async def _allocation_sizing(
    context: dict[str, Any],
    stop_loss: float,
    lot_size: int,
    entry_low: float | None,
    entry_high: float | None,
) -> str:
    """Price scenarios are analytical inputs; capital and risk remain frozen facts."""
    capital_name, capital = _capital(context)
    cash = _number(context, "account.available_capital")
    allocation = _number(context, "plan.allocated_capital")
    if any(value is None or value <= 0 for value in (capital, cash, allocation)):
        return _error("需要有效的冻结资金基数、可用资金和计划资金")
    if _entry_value(context, "plan.direction") != "buy":
        return _error("资金上限计算仅支持买入计划；卖出须使用已确认持仓数量")
    frozen_prices = {"plan.plan_price", "plan.plan_price_low", "plan.plan_price_high"}
    if frozen_prices & context.get("values", {}).keys():
        price = _number(context, "plan.plan_price")
        entry_low = price or _number(context, "plan.plan_price_low")
        entry_high = price or _number(context, "plan.plan_price_high")
    numbers = (entry_low, entry_high, stop_loss)
    if any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
        for v in numbers
    ):
        return _error("请提供有限数值的分析入场区间和止损价；无需保存为计划价格")
    assert entry_low is not None and entry_high is not None
    if not (0 < stop_loss < entry_low <= entry_high):
        return _error("分析情景必须满足 0 < 止损价 < 入场低价 <= 入场高价")
    if isinstance(lot_size, bool) or not isinstance(lot_size, int) or lot_size <= 0:
        return _error("最小交易单位必须为正整数")
    market = _entry_value(context, "plan.market")
    currency = _entry_value(context, "account.currency")
    if market != "CN" or currency != "CNY":
        return _error("当前资金上限计算要求 CN 标的与 CNY 账户；跨币种需要确认汇率")
    budget = min(Decimal(str(v)) for v in (capital, cash, allocation))
    limit = _number(context, "plan.position_limit_value")
    if "plan.position_limit_value" in context.get("values", {}):
        unit = (_entry_value(context, "plan.position_limit_unit") or "").lower()
        if limit is None or not 0 < limit <= 100 or unit not in _PERCENT_UNITS:
            return _error("已提供的仓位上限尚未确认为有效百分比，不能忽略此约束")
        budget = min(budget, Decimal(str(capital)) * Decimal(str(limit)) / 100)
    common = {
        "context_run_id": context.get("run_id"),
        "bound_inputs": [capital_name, "account.available_capital", "plan.allocated_capital"],
        "price_source": "frozen_plan"
        if frozen_prices & context.get("values", {}).keys()
        else "analysis_scenario",
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop_loss": stop_loss,
        "lot_size": lot_size,
    }
    risk = _number(context, "plan.risk_budget_value")
    if "plan.risk_budget_value" in context.get("values", {}):
        unit = (_entry_value(context, "plan.risk_budget_unit") or "").lower()
        if risk is None or unit not in _PERCENT_UNITS:
            return _error("已提供的风险预算尚未确认为有效百分比，不能忽略此约束")
        raw = await position_sizing.func(
            capital_total=capital,
            risk_budget_pct=risk,
            entry_low=entry_low,
            entry_high=entry_high,
            stop_loss=stop_loss,
            lot_size=lot_size,
            max_weight_pct=float(budget / Decimal(str(capital)) * 100),
        )
        result = json.loads(raw)
        result.update(common)
        result["risk_validated"] = bool(result.get("ok"))
        result["bound_inputs"] += ["plan.risk_budget_value", "plan.position_limit_value"]
        return json.dumps(result, ensure_ascii=False)
    shares = int(budget // (Decimal(str(entry_high)) * lot_size)) * lot_size
    return json.dumps(
        {
            **common,
            "ok": True,
            "calculation_mode": "capital_ceiling",
            "risk_validated": False,
            "computed_by": "investment_capital_ceiling@v1",
            "capital_budget": float(budget),
            "max_affordable_shares": shares,
            "max_affordable_amount": float(Decimal(str(entry_high)) * shares),
            "caveat": "仅为资金可覆盖的股数上限，未确认风险预算，不是建议仓位或风险校验结论。",
        },
        ensure_ascii=False,
    )


async def _investment_position_sizing(
    stop_loss: float,
    lot_size: int = 100,
    entry_low: float | None = None,
    entry_high: float | None = None,
) -> str:
    """使用冻结资金与约束计算仓位；未确认风险预算时仅给资金上限。

    总资金、分配资金、风险预算和仓位上限由服务端绑定，模型不能覆盖。
    新计划价格由分析情景提供；旧快照有计划价格时仍使用冻结价格。

    Args:
        stop_loss: 止损价，必须严格低于冻结的入场区间。
        lot_size: 最小交易单位；默认 100 股。
        entry_low: 分析情景入场低价，不是用户承诺价格。
        entry_high: 分析情景入场高价，不是用户承诺价格。

    Returns:
        与 ``position_sizing`` 相同的确定性 JSON，并附冻结 ``context_run_id``。
    """
    _count("sizing_calls")
    context = _context()
    if context is None:
        return _error("当前 Run 未绑定业务快照")

    if "plan.allocated_capital" in context.get("values", {}):
        return await _allocation_sizing(context, stop_loss, lot_size, entry_low, entry_high)

    capital_name, capital = _capital(context)
    risk = _number(context, "plan.risk_budget_value")
    max_weight = _number(context, "plan.position_limit_value")
    single_price = _number(context, "plan.plan_price")
    entry_low = single_price or _number(context, "plan.plan_price_low")
    entry_high = single_price or _number(context, "plan.plan_price_high")
    required = {
        capital_name or "account.capital_basis": capital,
        "plan.risk_budget_value": risk,
        "plan.position_limit_value": max_weight,
        "plan.plan_price|plan.plan_price_low": entry_low,
        "plan.plan_price|plan.plan_price_high": entry_high,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        return _error("冻结快照缺少仓位计算所需字段", missing=missing)
    assert capital_name is not None

    risk_unit = (_entry_value(context, "plan.risk_budget_unit") or "").lower()
    limit_unit = (_entry_value(context, "plan.position_limit_unit") or "").lower()
    unit_errors = []
    if risk_unit not in _PERCENT_UNITS:
        unit_errors.append("plan.risk_budget_unit")
    if limit_unit not in _PERCENT_UNITS:
        unit_errors.append("plan.position_limit_unit")
    if unit_errors:
        return _error("风险预算与仓位上限必须使用百分比单位", missing=unit_errors)

    raw = await position_sizing.func(
        capital_total=capital,
        risk_budget_pct=risk,
        entry_low=entry_low,
        entry_high=entry_high,
        stop_loss=stop_loss,
        lot_size=lot_size,
        max_weight_pct=max_weight,
    )
    result = json.loads(raw)
    result["context_run_id"] = context.get("run_id")
    result["bound_inputs"] = [
        capital_name,
        "plan.risk_budget_value",
        "plan.position_limit_value",
        "plan.plan_price|plan.plan_price_low|plan.plan_price_high",
    ]
    return json.dumps(result, ensure_ascii=False)


@tool
async def investment_position_sizing(
    stop_loss: float,
    lot_size: int = 100,
    entry_low: float | None = None,
    entry_high: float | None = None,
) -> str:
    """使用冻结资金、风险约束与分析入场情景计算仓位或资金上限。

    Args:
        stop_loss: 分析止损价，必须低于入场区间。
        lot_size: 最小交易单位，默认 100 股。
        entry_low: 新计划的分析情景入场低价，不是用户承诺价格。
        entry_high: 新计划的分析情景入场高价，不是用户承诺价格。

    Returns:
        JSON；risk_validated=false 时只得到资金上限，不能称为建议仓位。
    """
    from plugins.tools.task_board import record_verification

    raw = await _investment_position_sizing(stop_loss, lot_size, entry_low, entry_high)
    result = json.loads(raw)
    detail = "仓位计算通过"
    if not result.get("ok"):
        detail = "仓位计算未完成：" + str(result.get("error", "工具校验失败"))
    elif result.get("risk_validated") is False:
        detail = "资金股数上限计算完成；未确认风险预算，风险仓位未验证"
    record_verification("investment_position_sizing", passed=bool(result.get("ok")), detail=detail)
    return raw


@tool
async def investment_strategy_lint(strategy_json: str) -> str:
    """校验策略卡，并强制其资金、入场价和仓位结果匹配当前 Run 快照。

    Args:
        strategy_json: 完整策略卡 JSON 字符串。

    Returns:
        JSON 校验结果；上下文或绑定数字不一致时 ``passed=false``。
    """
    _count("lint_calls")
    raw_lint = json.loads(await strategy_lint.func(strategy_json=strategy_json))
    context = _context()
    if context is None:
        raw_lint.setdefault("errors", []).append(
            {
                "code": "missing_investment_context",
                "level": "error",
                "message": "当前 Run 未绑定业务快照",
            }
        )
        raw_lint["passed"] = False
        raw_lint["checked_by"] = _CONTEXT_LINT_ID
        return json.dumps(raw_lint, ensure_ascii=False)
    try:
        card = json.loads(strategy_json)
    except json.JSONDecodeError:
        raw_lint["checked_by"] = _CONTEXT_LINT_ID
        return json.dumps(raw_lint, ensure_ascii=False)
    if not isinstance(card, dict):
        raw_lint["checked_by"] = _CONTEXT_LINT_ID
        raw_lint["context_run_id"] = context.get("run_id")
        return json.dumps(raw_lint, ensure_ascii=False)

    errors = raw_lint.setdefault("errors", [])
    position = card.get("position")
    position = position if isinstance(position, dict) else {}
    sizing = position.get("sizing")
    sizing = sizing if isinstance(sizing, dict) else {}
    stop_loss = position.get("stop_loss")
    lot_size = sizing.get("lot_size", 100)
    entry = position.get("entry")
    entry = entry if isinstance(entry, dict) else {}
    if isinstance(stop_loss, bool) or not isinstance(stop_loss, (int, float)):
        expected = {"ok": False}
    else:
        expected = json.loads(
            await investment_position_sizing.func(
                stop_loss=float(stop_loss),
                lot_size=lot_size,
                entry_low=entry.get("low"),
                entry_high=entry.get("high"),
            )
        )

    mismatches: list[str] = []
    capital_name, _ = _capital(context)
    capital = _entry_value(context, capital_name) if capital_name else None
    if capital is None or not _same_number(card.get("capital_total"), capital):
        mismatches.append("capital_total")
    entry = position.get("entry")
    entry = entry if isinstance(entry, dict) else {}
    plan_price = _entry_value(context, "plan.plan_price")
    low = plan_price or _entry_value(context, "plan.plan_price_low")
    high = plan_price or _entry_value(context, "plan.plan_price_high")
    scenario = "plan.allocated_capital" in context.get("values", {}) and not any(
        name in context.get("values", {})
        for name in ("plan.plan_price", "plan.plan_price_low", "plan.plan_price_high")
    )
    if not scenario and (low is None or not _same_number(entry.get("low"), low)):
        mismatches.append("position.entry.low")
    if not scenario and (high is None or not _same_number(entry.get("high"), high)):
        mismatches.append("position.entry.high")
    if not expected.get("ok") or expected.get("risk_validated") is False:
        mismatches.append("position.sizing")
    else:
        for name in (
            "shares",
            "amount",
            "weight_pct",
            "risk_budget_pct",
            "entry_high",
            "stop_loss",
            "lot_size",
            "max_weight_pct",
            "computed_by",
        ):
            actual = sizing.get(name)
            wanted = expected.get(name)
            equal = actual == wanted if name == "computed_by" else _same_number(actual, wanted)
            if not equal:
                mismatches.append(f"position.sizing.{name}")
    if mismatches:
        errors.append(
            {
                "code": "investment_context_mismatch",
                "level": "error",
                "message": "策略卡与当前 Run 冻结快照不一致：" + ", ".join(mismatches),
            }
        )
    raw_lint["passed"] = not errors
    raw_lint["checked_by"] = _CONTEXT_LINT_ID
    raw_lint["context_run_id"] = context.get("run_id")
    return json.dumps(raw_lint, ensure_ascii=False)


def _same_number(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return False
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, ValueError, TypeError):
        return False
