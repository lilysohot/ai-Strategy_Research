"""Run-bound business context tools for the Web investment worker."""

from __future__ import annotations

import contextvars
import json
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
        return float(Decimal(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _capital(context: dict[str, Any]) -> tuple[str | None, float | None]:
    """Select the frozen capital value required by the account's declared basis."""
    basis = (_entry_value(context, "account.capital_basis") or "").strip().lower()
    if basis == "total":
        name = "account.total_capital"
    elif basis == "available":
        name = "account.available_capital"
    else:
        return None, None
    return name, _number(context, name)


def _error(message: str, *, missing: list[str] | None = None) -> str:
    return json.dumps(
        {"ok": False, "error": message, "missing": missing or []}, ensure_ascii=False
    )


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


@tool
async def investment_position_sizing(stop_loss: float, lot_size: int = 100) -> str:
    """使用当前 Run 冻结的资金、计划价和仓位约束计算仓位。

    总资金、风险预算、仓位上限及入场价格由服务端绑定，模型不能通过工具参数覆盖。
    任一必要字段缺失、待澄清或单位不是百分比时拒绝计算。

    Args:
        stop_loss: 止损价，必须严格低于冻结的入场区间。
        lot_size: 最小交易单位；默认 100 股。

    Returns:
        与 ``position_sizing`` 相同的确定性 JSON，并附冻结 ``context_run_id``。
    """
    _count("sizing_calls")
    context = _context()
    if context is None:
        return _error("当前 Run 未绑定业务快照")

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
            {"code": "missing_investment_context", "level": "error", "message": "当前 Run 未绑定业务快照"}
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
    if isinstance(stop_loss, bool) or not isinstance(stop_loss, (int, float)):
        expected = {"ok": False}
    else:
        expected = json.loads(
            await investment_position_sizing.func(stop_loss=float(stop_loss), lot_size=lot_size)
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
    if low is None or not _same_number(entry.get("low"), low):
        mismatches.append("position.entry.low")
    if high is None or not _same_number(entry.get("high"), high):
        mismatches.append("position.entry.high")
    if not expected.get("ok"):
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
