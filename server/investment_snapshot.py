"""Run 业务输入快照：解析、校验、冻结与读取（DATA-05）。

一个 Run 读到的业务输入必须是**提交那一刻**的事实：

* 提交时冻结账户/计划/持仓/成交的对象版本与解析后的完整有效值；
* 排队或执行中资料变化不改快照；重算是新 Run + 新快照，旧轨迹与旧快照保留；
* 旧的非业务 Run 没有快照，读取时明确报 ``404 snapshot_absent``，
  **绝不**用当前资料回填伪造（AC-06/07/26/27）。

真实输入准入仍然由 :mod:`server.business_service` 执行：假设/估计/疑问候选值在这里
同样进不了快照，用途必需字段缺失同样不放行依赖它们的计算。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server import business_service as biz
from server import store

#: 快照结构版本。读取方据此判断能否解释某份快照；升级时新增版本而不是改写旧行。
SNAPSHOT_SCHEMA_VERSION = "business-snapshot/1"

#: investment_input 允许的键；业务子结构里的未知字段一律拒绝，不静默忽略。
_ALLOWED_KEYS = frozenset(
    {
        "use_case",
        "account",
        "plan",
        "trade",
        "position",
        "declared",
        "idempotency_key",
        "rerun_of_run_id",
    }
)
#: 假设覆盖：本产品不支持“仅本次按假设值分析”（契约 §6）。
_ASSUMPTION_KEYS = frozenset(
    {"assume", "assumed", "scenario_override", "hypothetical", "what_if", "override"}
)


@dataclass(frozen=True)
class ObjectRef:
    """对某个业务对象的引用，可携带调用方已知的预期版本。"""

    id: uuid.UUID
    expected_revision: int | None = None


@dataclass(frozen=True)
class InvestmentInputSpec:
    """解析后的分析提交请求。"""

    use_case: str = "general_reading"
    account: ObjectRef | None = None
    plan: ObjectRef | None = None
    trade: ObjectRef | None = None
    position: ObjectRef | None = None
    declared: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None
    rerun_of_run_id: uuid.UUID | None = None


@dataclass
class Resolution:
    """冻结前解析出的有效值、来源与缺失项。"""

    account_id: uuid.UUID | None = None
    account_revision: int | None = None
    plan_id: uuid.UUID | None = None
    plan_revision: int | None = None
    trade_record_id: uuid.UUID | None = None
    position_snapshot_id: uuid.UUID | None = None
    #: 字段 → {value, currency, unit, as_of, status, source}
    values: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: 用途必需但缺失的字段 → 说明
    missing: dict[str, str] = field(default_factory=dict)


# ——— 请求解析 ——————————————————————————————————————————————————————————


def _object_ref(raw: Any, name: str) -> ObjectRef | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise biz.ValidationError(
            "对象引用格式不正确", fields={name: "需要 {id, expected_revision}"}
        )
    unknown = set(raw) - {"id", "expected_revision"}
    if unknown:
        raise biz.UnknownFieldError(
            "对象引用包含未知键", fields={name: f"未知键：{', '.join(sorted(unknown))}"}
        )
    raw_id = raw.get("id")
    if not raw_id:
        raise biz.ValidationError("对象引用缺少 id", fields={name: "需要对象 id"})
    try:
        object_id = uuid.UUID(str(raw_id))
    except (ValueError, AttributeError):
        raise biz.NotFoundOrForbiddenError("对象不存在或无权访问") from None
    expected = raw.get("expected_revision")
    return ObjectRef(
        id=object_id, expected_revision=int(expected) if expected is not None else None
    )


def parse_investment_input(raw: Any) -> InvestmentInputSpec | None:
    """解析并校验 ``investment_input``；``None`` 表示旧客户端请求（保持原行为）。"""
    if raw is None:
        return None
    if isinstance(raw, str):
        # multipart 里是表单字段（JSON 文本）：必须解析，不能被旧解析器忽略。
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raise biz.ValidationError(
                "investment_input 不是合法 JSON", fields={"investment_input": "需要 JSON 文本"}
            ) from None
    if not isinstance(raw, dict):
        raise biz.ValidationError(
            "investment_input 格式不正确", fields={"investment_input": "需要对象或 JSON 文本"}
        )
    if not raw:
        return None

    for key in sorted(set(raw) & _ASSUMPTION_KEYS):
        raise biz.AssumptionRejectedError(
            "本产品不支持仅本次的假设覆盖", fields={key: "假设值不能作为分析输入"}
        )
    unknown = sorted(set(raw) - _ALLOWED_KEYS)
    if unknown:
        raise biz.UnknownFieldError(
            "业务输入包含未知字段", fields={name: "该字段不属于提交契约" for name in unknown}
        )

    declared = raw.get("declared") or {}
    if not isinstance(declared, dict):
        raise biz.ValidationError("declared 格式不正确", fields={"declared": "需要对象"})
    # 声明值里的未知字段在这里就要被拒：否则它会以“本次声明”的名义绕过字段契约。
    _split_declared(declared)

    rerun_raw = raw.get("rerun_of_run_id")
    rerun_id = None
    if rerun_raw:
        try:
            rerun_id = uuid.UUID(str(rerun_raw))
        except (ValueError, AttributeError):
            raise biz.NotFoundOrForbiddenError("被重算的 Run 不存在或无权访问") from None

    return InvestmentInputSpec(
        use_case=str(raw.get("use_case") or "general_reading"),
        account=_object_ref(raw.get("account"), "account"),
        plan=_object_ref(raw.get("plan"), "plan"),
        trade=_object_ref(raw.get("trade"), "trade"),
        position=_object_ref(raw.get("position"), "position"),
        declared=declared,
        idempotency_key=raw.get("idempotency_key"),
        rerun_of_run_id=rerun_id,
    )


def _split_declared(declared: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """按字段所属对象拆分声明值；未知字段在此拒绝。"""
    groups: dict[str, dict[str, Any]] = {}
    for name, spec in declared.items():
        if name in biz.FORBIDDEN_OWNER_KEYS:
            raise biz.OwnerNotSettableError(
                "所有者由服务端绑定，不接受请求体指定", fields={name: "该字段不可由客户端设置"}
            )
        if name in biz.ACCOUNT_FIELDS:
            group = "account"
        elif name in biz.PLAN_FIELDS:
            group = "plan"
        elif name in biz.TRADE_FIELDS:
            group = "trade"
        else:
            raise biz.UnknownFieldError(
                "业务输入包含未知字段", fields={name: "该字段不属于账户/计划/成交契约"}
            )
        groups.setdefault(group, {})[name] = spec
    return groups


# ——— 解析有效值 ————————————————————————————————————————————————————————


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _entry(
    value: Any,
    *,
    status: str,
    source: dict[str, Any],
    currency: str | None = None,
    unit: str | None = None,
    as_of: Any = None,
) -> dict[str, Any]:
    return {
        "value": _text(value),
        "currency": currency,
        "unit": unit,
        "as_of": _text(as_of),
        "status": status,
        "source": source,
    }


async def _latest(session: AsyncSession, model: Any, fk: str, object_id: Any, revision: int) -> Any:
    return (
        await session.execute(
            select(model).where(getattr(model, fk) == object_id, model.revision == revision)
        )
    ).scalar_one_or_none()


def _require_revision(row: Any, expected: int | None, kind: str) -> None:
    if expected is not None and expected != row.current_revision:
        raise biz.RevisionConflictError(
            f"{kind}已被其他窗口修改",
            current={"revision": row.current_revision},
            fields={"expected_revision": f"当前版本为 {row.current_revision}"},
        )


async def resolve_for_run(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    research_id: uuid.UUID,
    spec: InvestmentInputSpec,
) -> Resolution:
    """在同一事务内读取对象、校验一致性，并解析出本次分析要用的有效值。"""
    resolution = Resolution()
    groups: dict[str, biz.AdmissionResult] = {}
    incomplete: list[str] = []

    if spec.account is not None:
        account = (
            await session.execute(
                select(store.InvestmentAccount).where(
                    store.InvestmentAccount.id == spec.account.id,
                    store.InvestmentAccount.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if account is None:
            raise biz.NotFoundOrForbiddenError("账户不存在或无权访问")
        if account.archived:
            raise biz.ObjectArchivedError(
                "账户已归档，不能被新的分析采用", current={"archived": True}
            )
        _require_revision(account, spec.account.expected_revision, "账户")
        revision = await _latest(
            session,
            store.InvestmentAccountRevision,
            "account_id",
            account.id,
            account.current_revision,
        )
        resolution.account_id = account.id
        resolution.account_revision = account.current_revision
        account_entries: dict[str, dict[str, Any]] = {}
        if revision is not None:
            if revision.record_state == "incomplete":
                incomplete.append("account")
            for name in biz.ACCOUNT_VALUE_COLUMNS:
                value = getattr(revision, name, None)
                if value is None:
                    continue
                account_entries[name] = _entry(
                    value,
                    status="user_provided",
                    source={"kind": "account_revision", "revision": account.current_revision},
                    currency=getattr(revision, "currency", None),
                    as_of=getattr(revision, "as_of", None),
                )
        resolution.values.update(account_entries)

    if spec.plan is not None:
        plan = (
            await session.execute(
                select(store.InvestmentPlan).where(
                    store.InvestmentPlan.id == spec.plan.id,
                    store.InvestmentPlan.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if plan is None:
            raise biz.NotFoundOrForbiddenError("计划不存在或无权访问")
        # 计划必须属于本次分析所属研究：借别的研究的计划来跑等于把研究结果写到别人的上下文。
        if plan.research_id != research_id:
            raise biz.NotFoundOrForbiddenError("计划不属于该研究")
        if plan.archived:
            raise biz.ObjectArchivedError("计划已归档", current={"archived": True})
        _require_revision(plan, spec.plan.expected_revision, "计划")
        revision = await _latest(
            session,
            store.InvestmentPlanRevision,
            "plan_id",
            plan.id,
            plan.current_revision,
        )
        resolution.plan_id = plan.id
        resolution.plan_revision = plan.current_revision
        if revision is not None:
            if revision.record_state == "incomplete":
                incomplete.append("plan")
            for name in biz.PLAN_VALUE_COLUMNS:
                value = getattr(revision, name, None)
                if value is None:
                    continue
                resolution.values[name] = _entry(
                    value,
                    status="user_provided",
                    source={"kind": "plan_revision", "revision": plan.current_revision},
                    unit=getattr(revision, f"{name}_unit", None)
                    if name.endswith("_value")
                    else None,
                )

    if spec.trade is not None:
        trade = (
            await session.execute(
                select(store.TradeRecord).where(
                    store.TradeRecord.id == spec.trade.id,
                    store.TradeRecord.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if trade is None:
            raise biz.NotFoundOrForbiddenError("成交记录不存在或无权访问")
        if resolution.account_id is not None and trade.account_id != resolution.account_id:
            # 混用不同账户的资料会让资金口径与成交事实互不相干。
            raise biz.ValidationError(
                "成交记录与账户不属于同一账户",
                fields={"trade": "请选择该账户自己的成交记录"},
            )
        if trade.status != "active":
            raise biz.RevisionConflictError(
                "该成交记录已被更正或取消", current={"status": trade.status}
            )
        resolution.trade_record_id = trade.id
        for name in ("side", "quantity", "price", "currency", "fees", "traded_at"):
            value = getattr(trade, name, None)
            if value is None:
                continue
            resolution.values[name] = _entry(
                value,
                status="user_provided",
                source={"kind": "trade_record", "id": str(trade.id)},
                currency=trade.currency,
            )
        resolution.values.setdefault(
            "symbol",
            _entry(
                trade.symbol,
                status="user_provided",
                source={"kind": "trade_record", "id": str(trade.id)},
            ),
        )

    if spec.position is not None:
        position = (
            await session.execute(
                select(store.PositionSnapshot).where(
                    store.PositionSnapshot.id == spec.position.id,
                    store.PositionSnapshot.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if position is None:
            raise biz.NotFoundOrForbiddenError("持仓快照不存在或无权访问")
        if resolution.account_id is not None and position.account_id != resolution.account_id:
            raise biz.ValidationError(
                "持仓快照与账户不属于同一账户",
                fields={"position": "请选择该账户自己的持仓快照"},
            )
        resolution.position_snapshot_id = position.id
        source = {"kind": "position_snapshot", "id": str(position.id)}
        resolution.values["quantity"] = _entry(
            position.quantity, status="user_provided", source=source
        )
        resolution.values["cost_basis"] = _entry(
            position.cost_basis, status="user_provided", source=source
        )
        resolution.values["currency"] = _entry(
            position.currency, status="user_provided", source=source
        )
        resolution.values["as_of"] = _entry(position.as_of, status="user_provided", source=source)
        resolution.values.setdefault(
            "symbol", _entry(position.symbol, status="user_provided", source=source)
        )

    # 本次显式声明的值：与已保存资料走同一套准入（假设值同样进不来），并覆盖旧值。
    declared_groups = _split_declared(spec.declared)
    for group, declared in declared_groups.items():
        admitted = biz.admit_group(group, declared)
        for name, value in admitted.values.items():
            resolution.values[name] = _entry(
                value.value,
                status=value.status,
                source={"kind": "declared"},
                currency=value.currency,
                unit=value.unit,
                as_of=value.as_of,
            )
        groups[group] = admitted

    # 已解析出的账户/计划值也要参与用途裁决，否则“资料已保存但字段缺失”会被当成齐了。
    account_values = {
        name: biz.AdmittedValue(value=_as_raw(entry["value"]))
        for name, entry in resolution.values.items()
        if name in biz.ACCOUNT_FIELDS and entry["value"] is not None
    }
    plan_values = {
        name: biz.AdmittedValue(value=_as_raw(entry["value"]))
        for name, entry in resolution.values.items()
        if name in biz.PLAN_FIELDS and entry["value"] is not None
    }
    trade_values = {
        name: biz.AdmittedValue(value=_as_raw(entry["value"]))
        for name, entry in resolution.values.items()
        if name in biz.TRADE_FIELDS and entry["value"] is not None
    }
    groups.setdefault("account", biz.AdmissionResult(values=account_values, incomplete={}))
    groups.setdefault("plan", biz.AdmissionResult(values=plan_values, incomplete={}))
    groups.setdefault("trade", biz.AdmissionResult(values=trade_values, incomplete={}))

    missing = biz.evaluate_purpose(spec.use_case, groups)
    if incomplete and spec.use_case != "general_reading":
        # 用户主动保存的不完整资料不是可用于依赖计算的有效资料（契约 §4）。
        for name in incomplete:
            missing[f"{name}.record_state"] = "该资料仍待补充，不能用于依赖它的分析"
    resolution.missing = missing
    if missing and spec.use_case != "general_reading":
        raise biz.PurposeRequirementError("分析所需资料未满足", fields=missing)
    return resolution


def _as_raw(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value


# ——— 冻结与读取 ————————————————————————————————————————————————————————


def build_snapshot(
    *,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    research_id: uuid.UUID,
    spec: InvestmentInputSpec,
    resolution: Resolution,
    source: str = "manual",
    rerun_of_run_id: uuid.UUID | None = None,
) -> store.RunInvestmentSnapshot:
    """构造快照行（只 INSERT，不 UPDATE；调用方持有事务）。"""
    return store.RunInvestmentSnapshot(
        run_id=run_id,
        user_id=user_id,
        research_id=research_id,
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        use_case=spec.use_case,
        source=source,
        account_id=resolution.account_id,
        account_revision=resolution.account_revision,
        plan_id=resolution.plan_id,
        plan_revision=resolution.plan_revision,
        position_snapshot_id=resolution.position_snapshot_id,
        trade_record_id=resolution.trade_record_id,
        rerun_of_run_id=rerun_of_run_id or spec.rerun_of_run_id,
        resolved_json=resolution.values,
        missing_json=resolution.missing,
        declared_json=spec.declared,
        frozen_at=datetime.now(UTC),
    )


async def get_snapshot(
    session: AsyncSession, *, user_id: uuid.UUID, run_id: uuid.UUID
) -> Any | None:
    """按 Run 所有者读取快照；不存在与他人 Run 都返回 None。"""
    return (
        await session.execute(
            select(store.RunInvestmentSnapshot).where(
                store.RunInvestmentSnapshot.run_id == run_id,
                store.RunInvestmentSnapshot.user_id == user_id,
            )
        )
    ).scalar_one_or_none()


def snapshot_view(row: Any) -> dict[str, Any]:
    return {
        "snapshot_id": str(row.id),
        # Run 标识沿用 runs 接口的 32 位十六进制形式；业务对象标识沿用业务接口的 UUID 串。
        "run_id": row.run_id.hex,
        "research_id": str(row.research_id),
        "schema_version": row.schema_version,
        "use_case": row.use_case,
        "source": row.source,
        "account": (
            {"id": str(row.account_id), "revision": row.account_revision}
            if row.account_id
            else None
        ),
        "plan": ({"id": str(row.plan_id), "revision": row.plan_revision} if row.plan_id else None),
        "trade_record_id": str(row.trade_record_id) if row.trade_record_id else None,
        "position_snapshot_id": (
            str(row.position_snapshot_id) if row.position_snapshot_id else None
        ),
        "rerun_of_run_id": row.rerun_of_run_id.hex if row.rerun_of_run_id else None,
        "values": dict(row.resolved_json or {}),
        "missing": dict(row.missing_json or {}),
        "declared": dict(row.declared_json or {}),
        "frozen_at": row.frozen_at.isoformat() if row.frozen_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def spec_from_snapshot(row: Any) -> InvestmentInputSpec:
    """由旧快照构造重算用的新请求：沿用意图与引用，但版本**不锁定**。

    重算要用当前最新有效资料生成新快照；把旧版本号带过去只会制造冲突。
    """
    declared = dict(row.declared_json or {})
    return InvestmentInputSpec(
        use_case=row.use_case,
        account=ObjectRef(id=row.account_id) if row.account_id else None,
        plan=ObjectRef(id=row.plan_id) if row.plan_id else None,
        trade=ObjectRef(id=row.trade_record_id) if row.trade_record_id else None,
        position=ObjectRef(id=row.position_snapshot_id) if row.position_snapshot_id else None,
        declared=declared,
        rerun_of_run_id=row.run_id,
    )
