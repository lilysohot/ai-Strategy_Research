"""Server-owned strategy proposals, calculation provenance and bounded revisions."""

from __future__ import annotations

import contextvars
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from frontier_agent.core.loop_types import BaseObserver, Intervention, TurnContext
from plugins.tools.strategy_lint import lint_strategy

MAX_FAILED_VALIDATIONS = 3


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, allow_inf_nan=False, str_strip_whitespace=True
    )


class StrategyEvidence(_StrictModel):
    source_ref: str = Field(min_length=1)
    page: str | int
    quote: str = Field(min_length=1)
    kind: Literal["fact", "forecast", "opinion"]


class StrategySource(_StrictModel):
    id: str = Field(min_length=1)
    url: str = ""
    title: str = ""


class StrategyProposal(_StrictModel):
    calculation_id: str = Field(min_length=1, description="本 Run 仓位工具返回的 calculation_id")
    horizon: Literal["1-5D", "1-4W", "1-3M", "3-6M", "6-12M", "12M+"]
    invalidation: str = Field(min_length=1)
    evidence: list[StrategyEvidence] = Field(min_length=1)
    sources: list[StrategySource] = Field(min_length=1)
    thesis: str = ""
    target: float | None = Field(default=None, gt=0)


@dataclass
class StrategyState:
    calculations: dict[str, dict[str, Any]] = field(default_factory=dict)
    failed_validations: int = 0
    last_result: dict[str, Any] | None = None


_STATE: contextvars.ContextVar[StrategyState | None] = contextvars.ContextVar(
    "investment_strategy_state", default=None
)


def bind_strategy_state() -> contextvars.Token[StrategyState | None]:
    return _STATE.set(StrategyState())


def reset_strategy_state(token: contextvars.Token[StrategyState | None]) -> None:
    _STATE.reset(token)


def register_calculation(result: dict[str, Any]) -> dict[str, Any]:
    state = _STATE.get()
    if state is not None and result.get("ok"):
        result = deepcopy(result)
        result["calculation_id"] = uuid4().hex
        state.calculations[result["calculation_id"]] = deepcopy(result)
    return result


def validation_exhausted() -> bool:
    state = _STATE.get()
    return state is not None and state.failed_validations >= MAX_FAILED_VALIDATIONS


def validation_snapshot() -> dict[str, Any] | None:
    state = _STATE.get()
    return deepcopy(state.last_result) if state else None


def failure(code: str, message: str, path: str = "strategy") -> dict[str, Any]:
    return {
        "passed": False,
        "errors": [{"code": code, "level": "error", "field": path, "message": message}],
        "warnings": [],
    }


def finish_validation(result: dict[str, Any], run_id: Any) -> dict[str, Any]:
    from plugins.tools.task_board import record_verification

    state = _STATE.get()
    passed = bool(result.get("passed"))
    if state is not None:
        if not passed and not validation_exhausted():
            state.failed_validations += 1
        # This is a Run-wide failure budget, not a JSON-string repetition counter.
        # Success/new calculations must not let alternating bad cards reset it.
        remaining = max(0, MAX_FAILED_VALIDATIONS - state.failed_validations)
    else:
        remaining = 0
    result.update(
        {
            "checked_by": "investment_strategy_lint@v2",
            "context_run_id": run_id,
            "attempts_remaining": remaining,
            "retry_allowed": not passed and remaining > 0,
            "recommendation_allowed": passed and result.get("risk_validated") is True,
        }
    )
    if not passed:
        result["delivery_mode"] = "blocked"
        result["next_action"] = "revise_fields" if remaining else "finalize_partial"
    else:
        result["next_action"] = (
            "deliver_strategy" if result["recommendation_allowed"] else "deliver_capital_analysis"
        )
    if state is not None:
        state.last_result = deepcopy(result)
    record_verification(
        "investment_strategy_lint",
        passed=passed,
        detail=(
            "风险策略卡校验通过"
            if result["recommendation_allowed"]
            else "资金上限分析校验通过；不构成建议仓位"
            if passed
            else "策略卡校验未通过：" + "; ".join(e["message"] for e in result["errors"])
        ),
    )
    return result


def validate_proposal(
    raw: Any, *, context: dict[str, Any], capital: float | None
) -> dict[str, Any]:
    try:
        proposal = StrategyProposal.model_validate(raw)
    except ValidationError as exc:
        return {
            "passed": False,
            "warnings": [],
            "errors": [
                {
                    "code": "strategy_schema_error",
                    "level": "error",
                    "field": "strategy." + ".".join(str(p) for p in error["loc"]),
                    "message": error["msg"],
                }
                for error in exc.errors(include_input=False, include_url=False)
            ],
        }
    state = _STATE.get()
    sizing = state.calculations.get(proposal.calculation_id) if state else None
    if sizing is None or sizing.get("context_run_id") != context.get("run_id"):
        return failure(
            "unknown_calculation",
            "计算结果不属于当前 Run；请先调用 investment_position_sizing",
            "strategy.calculation_id",
        )
    sizing = deepcopy(sizing)
    position = proposal.model_dump(exclude={"calculation_id", "sources"}, exclude_none=True)
    position.update(
        {
            "entry": {"low": sizing["entry_low"], "high": sizing["entry_high"]},
            "stop_loss": sizing["stop_loss"],
            "sizing": sizing,
        }
    )
    card = {
        "schema_version": "investment-strategy/2",
        "context_run_id": context.get("run_id"),
        "snapshot_id": context.get("snapshot_id"),
        "capital_total": capital,
        "position": position,
        "sources": [s.model_dump() for s in proposal.sources],
    }
    for name in ("symbol", "market", "direction"):
        entry = context.get("values", {}).get("plan." + name, {})
        if entry.get("status") in {"resolved", "user_provided"}:
            card[name] = entry.get("value")
    risk_validated = sizing.get("risk_validated") is True
    # Only a server-registered capital ceiling can take the non-risk path.
    capital_only = (
        sizing.get("calculation_mode") == "capital_ceiling"
        and sizing.get("computed_by") == "investment_capital_ceiling@v1"
        and sizing.get("risk_validated") is False
    )
    if not risk_validated and not capital_only:
        return failure("unverified_calculation", "计算结果未完成风险或资金上限校验")
    result = lint_strategy(card, validate_sizing=not capital_only)
    result.update(
        {
            "risk_validated": risk_validated,
            "delivery_mode": "capital_analysis" if capital_only else "strategy",
        }
    )
    if result["passed"]:
        card["delivery_mode"] = result["delivery_mode"]
        result["card"] = card
        if capital_only:
            result["caveat"] = sizing["caveat"]
    return result


def publication_boundary(final_text: str, answer_status: str) -> dict[str, str]:
    """Publish a deterministic limited result when no risk strategy can be delivered.

    A disclaimer appended to unverified buy instructions is not a validation gate.
    The full research trace and model-written files remain in the Run for audit.
    """
    result = validation_snapshot()
    if result is None or result.get("recommendation_allowed"):
        return {"final_text": final_text, "answer_status": answer_status}
    if result.get("passed") and result.get("delivery_mode") == "capital_analysis":
        sizing = result["card"]["position"]["sizing"]
        text = (
            "本次完成了资金上限分析，尚未生成风险仓位建议。\n\n"
            f"分析入场区间：{sizing['entry_low']:g}–{sizing['entry_high']:g} 元；"
            f"分析止损价：{sizing['stop_loss']:g} 元。\n"
            f"按冻结资金约束，可用预算为 {sizing['capital_budget']:,.2f} 元，"
            f"按区间上沿计算，最多覆盖 {sizing['max_affordable_shares']} 股、"
            f"金额 {sizing['max_affordable_amount']:,.2f} 元。\n\n"
            "以上只是资金可覆盖上限，不是建议买入数量。"
            "本 Run 未确认风险预算，不能据此给出首仓、加仓或最终仓位建议。"
        )
    else:
        details = "\n".join(
            f"- {error.get('field', 'strategy')}：{error['message']}（{error['code']}）"
            for error in result.get("errors", [])
        )
        text = "策略卡校验未通过，本次未形成可交付的买入或仓位结论。\n\n" + details
        if validation_exhausted():
            text += "\n\n已达到三次失败上限（初次校验加两次修订），已停止重复校验。"
    return {"final_text": text, "answer_status": "partial"}


# Business behavior belongs to this plugin, not the domain-neutral loop.
class InvestmentStrategyObserver(BaseObserver):
    critical = True

    async def on_turn_end(self, ctx: TurnContext) -> Intervention | None:
        if validation_exhausted():
            return Intervention(stop_reason="strategy_validation_failed")
        return None
