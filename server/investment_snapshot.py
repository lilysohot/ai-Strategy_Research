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
from dataclasses import dataclass, field, replace
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
    if expected is not None and (type(expected) is not int or expected < 1):
        raise biz.ValidationError("版本号不正确", fields={name: "expected_revision 必须是正整数"})
    return ObjectRef(id=object_id, expected_revision=expected)


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
    split_declared(declared)

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


def group_declared(declared: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """按字段所属对象拆分声明值，不提前执行整组真实性准入。"""
    groups: dict[str, dict[str, Any]] = {}
    for name, spec in declared.items():
        if name in biz.GROUP_FIELDS:
            if not isinstance(spec, dict):
                raise biz.ValidationError("分组声明必须是对象", fields={name: "需要字段对象"})
            groups.setdefault(name, {}).update(spec)
            continue
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


def split_declared(declared: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """拆分并校验完整声明；任一组不能通过时拒绝本次业务写入。"""
    groups = group_declared(declared)
    for group, values in groups.items():
        biz.admit_group(group, values)
    return groups


async def declared_plan_from_capital(
    session: AsyncSession, *, user_id: uuid.UUID, research_id: uuid.UUID
) -> dict[str, dict[str, Any]] | None:
    """会话规划资金 + 其下最新一笔有效买卖价格 → ``declared`` 计划口径。

    主计划已随计划创建入口下线（2026-10-27）：无主计划的会话以**规划资金 + 实际
    买卖价格**表达计划口径——标的/市场/方向/币种取最新一笔有效（未归档）买卖价格，
    规划资金由 :func:`resolve_for_run` 注入 ``plan.allocated_capital``。不满足
    （无规划资金、资金未填、无有效买卖价格）返回 ``None``，调用方按绑定缺失处理。
    """
    capital = (
        await session.execute(
            select(store.CapitalPlan).where(
                store.CapitalPlan.research_id == research_id,
                store.CapitalPlan.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if capital is None or capital.allocated_capital is None:
        return None
    buy_sell = (
        (
            await session.execute(
                select(store.BuySellPlan)
                .where(
                    store.BuySellPlan.capital_plan_id == capital.id,
                    store.BuySellPlan.archived.is_(False),
                    store.BuySellPlan.status == "active",
                )
                .order_by(store.BuySellPlan.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if buy_sell is None:
        return None
    revision = (
        await session.execute(
            select(store.BuySellPlanRevision).where(
                store.BuySellPlanRevision.buy_sell_plan_id == buy_sell.id,
                store.BuySellPlanRevision.revision == buy_sell.current_revision,
            )
        )
    ).scalar_one_or_none()
    if revision is None:
        return None
    return {
        "plan": {
            "symbol": {"value": revision.symbol},
            "market": {"value": revision.market or "CN"},
            "direction": {"value": revision.side},
            "currency": {"value": revision.currency},
        }
    }


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
    """Resolve each object independently; only combine compatible effective facts."""
    resolution = Resolution()
    groups: dict[str, biz.AdmissionResult] = {}
    entries: dict[str, dict[str, dict[str, Any]]] = {}

    def add(
        group: str, values: dict[str, dict[str, Any]], pending: list[str] | None = None
    ) -> None:
        entries[group] = values
        groups[group] = biz.AdmissionResult(
            values={
                name: biz.AdmittedValue(value=item["value"], status=item["status"])
                for name, item in values.items()
                if name not in (pending or [])
            },
            incomplete={name: "该字段仍待补充" for name in (pending or [])},
        )

    for group, ref, model, rev_model, fk, columns in (
        (
            "account",
            spec.account,
            store.InvestmentAccount,
            store.InvestmentAccountRevision,
            "account_id",
            biz.ACCOUNT_VALUE_COLUMNS,
        ),
        (
            "plan",
            spec.plan,
            store.InvestmentPlan,
            store.InvestmentPlanRevision,
            "plan_id",
            biz.PLAN_VALUE_COLUMNS,
        ),
    ):
        if ref is None:
            continue
        obj = (
            await session.execute(
                select(model).where(model.id == ref.id, model.user_id == user_id).with_for_update()
            )
        ).scalar_one_or_none()
        if obj is None or (group == "plan" and getattr(obj, "research_id", None) != research_id):
            raise biz.NotFoundOrForbiddenError("资料不存在或不属于该研究")
        if obj.archived:
            raise biz.ObjectArchivedError("资料已归档，不能用于新的分析")
        _require_revision(obj, ref.expected_revision, group)
        revision = await _latest(session, rev_model, fk, obj.id, obj.current_revision)
        if revision is None:
            raise biz.NotFoundOrForbiddenError("资料版本不存在")
        setattr(resolution, f"{group}_id", obj.id)
        setattr(resolution, f"{group}_revision", obj.current_revision)
        metadata = revision.changed_fields or {}
        pending = metadata.get("pending_fields", [])
        if revision.record_state == "incomplete" and "pending_fields" not in metadata:
            pending = ["record_state"]
        values = {
            name: _entry(
                getattr(revision, name),
                status="user_provided",
                source={
                    "kind": f"{group}_revision",
                    "id": str(obj.id),
                    "revision": obj.current_revision,
                },
                currency=getattr(revision, "currency", None),
                unit=getattr(revision, biz.UNIT_BY_FIELD.get(name, ""), None),
                as_of=getattr(revision, "as_of", None),
            )
            for name in columns
            if getattr(revision, name, None) is not None
        }
        add(group, values, pending)

    for group, ref, model, columns in (
        (
            "trade",
            spec.trade,
            store.TradeRecord,
            ("symbol", "market", "side", "quantity", "price", "currency", "fees", "traded_at"),
        ),
        (
            "position",
            spec.position,
            store.PositionSnapshot,
            ("symbol", "market", "quantity", "cost_basis", "currency", "as_of"),
        ),
    ):
        if ref is None:
            continue
        obj = (
            await session.execute(
                select(model).where(model.id == ref.id, model.user_id == user_id).with_for_update()
            )
        ).scalar_one_or_none()
        if obj is None:
            raise biz.NotFoundOrForbiddenError("实际记录不存在或无权访问")
        if obj.status != "active":
            raise biz.RevisionConflictError(
                "实际记录已被更正或取消", current={"status": obj.status}
            )
        if resolution.account_id is not None and obj.account_id != resolution.account_id:
            raise biz.ValidationError(
                "实际记录与账户不一致", fields={group: "请选择同一账户的记录"}
            )
        setattr(
            resolution, "trade_record_id" if group == "trade" else "position_snapshot_id", obj.id
        )
        add(
            group,
            {
                name: _entry(
                    getattr(obj, name),
                    status="user_provided",
                    source={"kind": group, "id": str(obj.id)},
                    currency=obj.currency,
                    as_of=getattr(obj, "as_of", None) or getattr(obj, "traded_at", None),
                )
                for name in columns
                if getattr(obj, name, None) is not None
            },
        )

    for group, declared in split_declared(spec.declared).items():
        admitted = biz.admit_group(group, declared)
        prior = groups.get(group, biz.AdmissionResult(values={}, incomplete={}))
        values = dict(entries.get(group, {}))
        pending = dict(prior.incomplete)
        pending.update(admitted.incomplete)
        for name in admitted.incomplete:
            values.pop(name, None)
        for name, value in admitted.values.items():
            pending.pop(name, None)
            values[name] = _entry(
                value.value,
                status=value.status,
                source={"kind": "declared"},
                currency=value.currency,
                unit=value.unit,
                as_of=value.as_of,
            )
        add(group, values, list(pending))

    # 规划资金已从计划拆分到 ``capital_plans``（会话 1:1，累加/重置）：用途门禁仍以
    # ``plan.allocated_capital`` 表达"本标的规划资金"，这里把会话规划资金注入计划组，
    # 满足门禁并随快照冻结，下游仓位分析据此取数。放在 declared 合并之后：
    # 计划组既可能来自主计划引用，也可能来自监控触发的 declared（无主计划路径），
    # 两种来源都由本注入补齐资金；显式 declared 的 allocated_capital 仍然优先。
    if "plan" in entries and "allocated_capital" not in entries["plan"]:
        capital = (
            await session.execute(
                select(store.CapitalPlan).where(
                    store.CapitalPlan.research_id == research_id,
                    store.CapitalPlan.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if capital is not None and capital.allocated_capital is not None:
            entries["plan"]["allocated_capital"] = _entry(
                capital.allocated_capital,
                status="user_provided",
                source={
                    "kind": "capital_plan",
                    "id": str(capital.id),
                    "revision": capital.current_revision,
                },
                currency=capital.currency,
                as_of=capital.as_of,
            )
            groups["plan"] = biz.AdmissionResult(
                values={
                    **groups["plan"].values,
                    "allocated_capital": biz.AdmittedValue(
                        value=capital.allocated_capital, status="user_provided"
                    ),
                },
                # 规划资金已由会话资金补齐：把该字段从待补充清单里移除，
                # 否则 incomplete 会覆盖注入值，门禁依旧被拒。
                incomplete={
                    name: reason
                    for name, reason in groups["plan"].incomplete.items()
                    if name != "allocated_capital"
                },
            )

    # Shared names never manufacture another object's fields. No implicit FX or
    # borrowing a different security's trade price to satisfy plan requirements.
    for name in ("symbol", "market", "currency"):
        known = {str(group.values[name].value) for group in groups.values() if name in group.values}
        if len(known) > 1:
            raise biz.ValidationError(
                "业务资料的标的、市场或币种不一致",
                fields={name: "请采用同一标的和币种的资料；不进行隐式换汇"},
            )

    missing = biz.evaluate_purpose(spec.use_case, groups)
    for group, admission in groups.items():
        for name, reason in admission.incomplete.items():
            missing[f"{group}.{name}"] = reason
    resolution.missing = missing
    if missing and spec.use_case in {"plan_analysis", "holding_cost"}:
        raise biz.PurposeRequirementError("分析所需资料未满足", fields=missing)
    for group, values in entries.items():
        for name, item in values.items():
            if name in groups[group].incomplete:
                continue
            # Preserve object-specific times/units alongside the compatible flat
            # projection consumed by older snapshot readers.
            resolution.values[f"{group}.{name}"] = item
            resolution.values.setdefault(name, item)

    # 实际买卖价格列表（只读事实，随快照冻结）：会话规划资金下**未归档**的有效
    # 买卖价格，最新在前、最多 10 笔。软删除（archived）不进入上下文。它们不参与
    # 用途门禁，也不进入 groups——仅供模型经 ``investment_context`` 对比参考，
    # 真源仍是 trade_records / buy_sell_plans，入场区间仍是分析情景。
    capital = (
        await session.execute(
            select(store.CapitalPlan).where(
                store.CapitalPlan.research_id == research_id,
                store.CapitalPlan.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if capital is not None:
        buy_sell_rows = (
            (
                await session.execute(
                    select(store.BuySellPlan)
                    .where(
                        store.BuySellPlan.capital_plan_id == capital.id,
                        store.BuySellPlan.archived.is_(False),
                        store.BuySellPlan.status == "active",
                    )
                    .order_by(store.BuySellPlan.created_at.desc())
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
        capital_source = {
            "kind": "capital_plan",
            "id": str(capital.id),
            "revision": capital.current_revision,
        }
        resolution.values["buy_sell.count"] = _entry(
            str(len(buy_sell_rows)), status="user_provided", source=capital_source
        )
        for index, row in enumerate(buy_sell_rows, start=1):
            revision = await _latest(
                session,
                store.BuySellPlanRevision,
                "buy_sell_plan_id",
                row.id,
                row.current_revision,
            )
            if revision is None:
                continue
            row_source = {
                "kind": "capital_plan",
                "id": str(row.id),
                "revision": row.current_revision,
            }
            facts = {
                "symbol": revision.symbol,
                "market": revision.market,
                "side": revision.side,
                "price": revision.price,
                "quantity": revision.quantity,
                "traded_at": revision.traded_at,
                "currency": revision.currency,
            }
            for name, value in facts.items():
                if value is None:
                    continue
                resolution.values[f"buy_sell.{index}.{name}"] = _entry(
                    value,
                    status="user_provided",
                    source=row_source,
                    currency=revision.currency if name == "price" else None,
                )
    return resolution


async def persist_declared(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    research_id: uuid.UUID,
    spec: InvestmentInputSpec,
) -> tuple[InvestmentInputSpec, dict[str, Any]]:
    """Save explicit edits in the caller's Run transaction, then freeze saved revisions."""
    saved: dict[str, Any] = {}
    result = spec
    persisted: set[str] = set()
    for group, declared in split_declared(spec.declared).items():
        ref = getattr(spec, group)
        #: trade 允许没有既有引用：2026-10-08 口径下“回填实际成交价”就是新登记一条成交。
        #: plan 无引用时（规划资金 + 实际买卖价格路径）没有可写的计划对象——计划口径
        #: 以 declared 原样保留给解析，不做持久化、也不报错（2026-10-27）。
        if ref is None and group != "trade":
            if group == "plan":
                continue
            raise biz.ValidationError(
                "保存资料需要明确的目标对象", fields={group: "请先选择或创建资料对象"}
            )
        child_key = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"run.submit:{user_id}:{spec.idempotency_key}:{group}")
        )
        if group == "account":
            assert ref is not None
            outcome = await biz.update_account(
                session,
                user_id=user_id,
                account_id=ref.id,
                expected_revision=ref.expected_revision,
                declared=declared,
                idempotency_key=child_key,
                allow_incomplete=False,
            )
            result = replace(result, account=ObjectRef(ref.id, outcome.result["revision"]))
        elif group == "plan":
            assert ref is not None
            plan = await session.get(store.InvestmentPlan, ref.id)
            if plan is None or plan.user_id != user_id or plan.research_id != research_id:
                raise biz.NotFoundOrForbiddenError("计划不属于该研究")
            outcome = await biz.update_plan(
                session,
                user_id=user_id,
                plan_id=ref.id,
                expected_revision=ref.expected_revision,
                declared=declared,
                idempotency_key=child_key,
                allow_incomplete=False,
            )
            result = replace(result, plan=ObjectRef(ref.id, outcome.result["revision"]))
        elif ref is None:
            #: 回填实际成交价：在提交事务内新登记一条成交（每次买卖各一条，可多条）。
            if spec.account is None:
                raise biz.ValidationError(
                    "登记成交需要所属账户", fields={"account": "请先选择账户"}
                )
            outcome = await biz.register_trade(
                session,
                user_id=user_id,
                account_id=spec.account.id,
                declared=declared,
                idempotency_key=child_key,
            )
            result = replace(result, trade=ObjectRef(uuid.UUID(outcome.result["trade_id"])))
        else:
            outcome = await biz.correct_trade(
                session,
                user_id=user_id,
                trade_id=ref.id,
                declared=declared,
                idempotency_key=child_key,
            )
            result = replace(result, trade=ObjectRef(uuid.UUID(outcome.result["trade_id"])))
        persisted.add(group)
        saved[group] = outcome.result
    # 已持久化的组清空 declared（事实已落对象，解析走引用）；未持久化的组
    # （无主计划的 plan）原样保留，供随后的 resolve_for_run 使用。
    return replace(
        result,
        declared={k: v for k, v in spec.declared.items() if k not in persisted},
    ), saved


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


async def ensure_research_bound_snapshot(*, run_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Freeze a plain Run's current research binding exactly once.

    Explicit submission snapshots (manual/input_answer/watch_event) always win.
    For a Run without one, lock the Run, resolve the account and primary plan
    currently bound to its authenticated research, and insert an immutable
    ``research_bound`` snapshot.  ``unspecified`` deliberately records facts
    without applying a purpose gate; the agent declares plan_analysis or
    holding_cost later if it needs a personalised conclusion.

    Returns ``True`` only when this call inserted the inherited snapshot.
    """
    async with biz.business_transaction() as session:
        run = (
            await session.execute(
                select(store.Run)
                .where(store.Run.id == run_id, store.Run.user_id == user_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if run is None:
            return False

        existing = await get_snapshot(session, user_id=user_id, run_id=run_id)
        if existing is not None:
            return False

        link = (
            await session.execute(
                select(store.ResearchInvestmentLink).where(
                    store.ResearchInvestmentLink.research_id == run.session_id,
                    store.ResearchInvestmentLink.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if link is None or (link.account_id is None and link.primary_plan_id is None):
            return False

        spec = InvestmentInputSpec(
            use_case="unspecified",
            account=ObjectRef(link.account_id) if link.account_id else None,
            plan=ObjectRef(link.primary_plan_id) if link.primary_plan_id else None,
        )
        resolution = await resolve_for_run(
            session,
            user_id=user_id,
            research_id=run.session_id,
            spec=spec,
        )
        session.add(
            build_snapshot(
                run_id=run.id,
                user_id=user_id,
                research_id=run.session_id,
                spec=spec,
                resolution=resolution,
                source="research_bound",
            )
        )
        await session.flush()
        return True


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
    return InvestmentInputSpec(
        use_case=row.use_case,
        account=ObjectRef(id=row.account_id) if row.account_id else None,
        plan=ObjectRef(id=row.plan_id) if row.plan_id else None,
        trade=ObjectRef(id=row.trade_record_id) if row.trade_record_id else None,
        position=ObjectRef(id=row.position_snapshot_id) if row.position_snapshot_id else None,
        declared={},
        rerun_of_run_id=row.run_id,
    )
