"""监控规则：持久化、版本与生命周期（DATA-09 / PR-WATCH-01）。

规则是用户预先保存的监控指令：属于一个研究、可选绑定该研究所属计划、每次编辑产生一条
不可变 ``WatchRuleRevision``。阈值、方向、有效期、触发资格策略在版本行冻结；计划改版、
暂停/恢复都不改写既有版本（契约 §9）。

C 阶段只开放 ``trigger_mode=single``；重复模式及其冷却/重新布防参数在 D 阶段开放，
本阶段收到即明确拒绝，不静默接受。
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server import business_service as biz
from server import store

ACTIVE = "active"
PAUSED = "paused"
CANCELLED = "cancelled"

DIRECTIONS = frozenset({"up", "down", "range"})
ACTIONS = frozenset({"notify", "auto_analyze"})
#: C 阶段只开放单次触发；repeat 及其冷却/重新布防参数属 D 阶段。
TRIGGER_MODES = frozenset({"single"})
ON_CREATE_POLICIES = frozenset({"trigger_now", "wait_requalify"})
DISCONNECT_POLICIES = frozenset({"trigger_once", "wait_requalify"})
BUDGET_KEYS = frozenset({"max_runs"})

#: 规则配置可提交的顶层键；编辑额外允许 ``plan_id``（指针行绑定，随版本可追溯）。
SPEC_KEYS = frozenset(
    {
        "symbol",
        "market",
        "currency",
        "quote_basis",
        "direction",
        "threshold",
        "expires_at",
        "trigger_mode",
        "action",
        "task",
        "budget",
        "on_create_already_met",
        "disconnect_recovery",
    }
)
PATCH_KEYS = SPEC_KEYS | {"plan_id"}

DECIMAL_TEXT = re.compile(r"^(0|[1-9]\d*)(\.\d+)?$")
CURRENCY_TEXT = re.compile(r"^[A-Z]{3}$")


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _append_audit(
    session: AsyncSession, *, user_id: Any, action: str, detail: dict[str, Any]
) -> None:
    """审计只记对象标识与变更字段名，不写行情正文以外的敏感明细。"""
    session.add(store.AuditLog(user_id=user_id, action=action, detail_json=detail))


def _parse_decimal(name: str, value: Any) -> Decimal:
    if not isinstance(value, str) or not DECIMAL_TEXT.match(value):
        raise biz.ValidationError("阈值格式不正确", fields={name: "需要非负十进制文本"})
    return Decimal(value)


def _parse_dt(value: Any, name: str = "expires_at") -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise biz.ValidationError("时间格式不正确", fields={name: "需要 ISO 8601 时间"})
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise biz.ValidationError("时间格式不正确", fields={name: "需要 ISO 8601 时间"}) from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _parse_budget(value: Any) -> dict[str, Any]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        raise biz.ValidationError("预算格式不正确", fields={"budget": "需要对象"})
    unknown = set(value) - BUDGET_KEYS
    if unknown:
        raise biz.UnknownFieldError(
            "预算包含未知字段", fields={key: "预算键不在契约内" for key in sorted(unknown)}
        )
    max_runs = value.get("max_runs")
    if max_runs is not None and (type(max_runs) is not int or max_runs < 1):
        raise biz.ValidationError("预算格式不正确", fields={"budget.max_runs": "需要 >= 1 的整数"})
    return {"max_runs": max_runs} if max_runs is not None else {}


def _parse_fields(patch: dict[str, Any], *, allow_plan_id: bool) -> tuple[dict[str, Any], Any]:
    """把用户提交的规则配置规范化为版本行列值。

    返回 ``(columns, threshold_raw)``：``columns`` 不含阈值列（阈值依赖方向合并后再算），
    ``threshold_raw`` 为 ``"threshold"`` 的原始值；未提供时用哨兵。
    创建不允许 ``plan_id`` 出现在配置里（绑定是独立参数）；编辑允许，但由上层单独处理。
    """
    allowed = PATCH_KEYS if allow_plan_id else SPEC_KEYS
    unknown = set(patch) - allowed
    if unknown:
        raise biz.UnknownFieldError(
            "规则配置包含未知字段", fields={key: "字段不属于监控契约" for key in sorted(unknown)}
        )
    columns: dict[str, Any] = {}
    for key in SPEC_KEYS:
        if key not in patch:
            continue
        value = patch[key]
        if key == "threshold":
            columns["_threshold"] = value
        elif key == "symbol":
            text = str(value or "").strip()
            if not text:
                raise biz.ValidationError("标的不能为空", fields={"symbol": "请填写标的代码"})
            columns[key] = text
        elif key == "market":
            text = str(value or "").strip()
            if not text:
                raise biz.ValidationError("市场不能为空", fields={"market": "请选择市场"})
            columns[key] = text
        elif key == "currency":
            text = str(value or "").strip()
            if not CURRENCY_TEXT.match(text):
                raise biz.ValidationError(
                    "币种不正确", fields={"currency": "需要三位大写 ISO 4217 币种代码"}
                )
            columns[key] = text
        elif key == "quote_basis":
            text = str(value or "").strip()
            if not text:
                raise biz.ValidationError(
                    "行情口径不能为空", fields={"quote_basis": "请选择行情口径"}
                )
            columns[key] = text
        elif key == "direction":
            text = str(value or "").strip()
            if text not in DIRECTIONS:
                raise biz.ValidationError(
                    "方向不正确", fields={"direction": "请选择 up / down / range"}
                )
            columns[key] = text
        elif key == "trigger_mode":
            text = str(value or "").strip()
            if text not in TRIGGER_MODES:
                raise biz.ValidationError(
                    "触发模式未开放",
                    fields={"trigger_mode": "C 阶段仅支持 single，重复模式在 D 阶段开放"},
                )
            columns[key] = text
        elif key == "action":
            text = str(value or "").strip()
            if text not in ACTIONS:
                raise biz.ValidationError(
                    "分析意图不正确", fields={"action": "请选择 notify 或 auto_analyze"}
                )
            columns[key] = text
        elif key == "task":
            text = str(value or "").strip()
            columns[key] = text if text else None
        elif key == "budget":
            columns["budget_json"] = _parse_budget(value)
        elif key == "expires_at":
            columns[key] = _parse_dt(value)
        elif key == "on_create_already_met":
            text = str(value or "").strip()
            if text not in ON_CREATE_POLICIES:
                raise biz.ValidationError(
                    "创建时已达标策略不正确",
                    fields={"on_create_already_met": "请选择 trigger_now 或 wait_requalify"},
                )
            columns[key] = text
        elif key == "disconnect_recovery":
            text = str(value or "").strip()
            if text not in DISCONNECT_POLICIES:
                raise biz.ValidationError(
                    "断线恢复策略不正确",
                    fields={"disconnect_recovery": "请选择 trigger_once 或 wait_requalify"},
                )
            columns[key] = text
    threshold_raw = columns.pop("_threshold", _UNSET)
    return columns, threshold_raw


class _Unset:
    pass


_UNSET = _Unset()


def _defaults() -> dict[str, Any]:
    return {
        "quote_basis": "last",
        "trigger_mode": "single",
        "budget_json": {},
        "on_create_already_met": "trigger_now",
        "disconnect_recovery": "trigger_once",
    }


def _finalize_threshold(
    direction: str, threshold_raw: Any
) -> tuple[Decimal | None, Decimal | None]:
    if direction == "range":
        if not isinstance(threshold_raw, dict):
            raise biz.ValidationError(
                "区间阈值格式不正确", fields={"threshold": "区间方向需要 {low, high} 对象"}
            )
        unknown = set(threshold_raw) - {"low", "high"}
        if unknown:
            raise biz.UnknownFieldError(
                "区间阈值包含未知字段", fields={key: "仅支持 low / high" for key in sorted(unknown)}
            )
        low = _parse_decimal("threshold.low", threshold_raw.get("low"))
        high = _parse_decimal("threshold.high", threshold_raw.get("high"))
        if not low < high:
            raise biz.ValidationError(
                "区间阈值顺序不正确", fields={"threshold": "low 必须小于 high"}
            )
        return low, high
    low = _parse_decimal("threshold", threshold_raw)
    return low, None


def _revision_columns(rev: store.WatchRuleRevision | None) -> dict[str, Any]:
    if rev is None:
        return {}
    return {
        "symbol": rev.symbol,
        "market": rev.market,
        "currency": rev.currency,
        "quote_basis": rev.quote_basis,
        "direction": rev.direction,
        "threshold_low": rev.threshold_low,
        "threshold_high": rev.threshold_high,
        "expires_at": rev.expires_at,
        "trigger_mode": rev.trigger_mode,
        "action": rev.action,
        "task": rev.task,
        "budget_json": dict(rev.budget_json or {}),
        "on_create_already_met": rev.on_create_already_met,
        "disconnect_recovery": rev.disconnect_recovery,
    }


def _threshold_view(rev: store.WatchRuleRevision) -> Any:
    if rev.direction == "range":
        return {"low": _decimal_text(rev.threshold_low), "high": _decimal_text(rev.threshold_high)}
    return _decimal_text(rev.threshold_low)


def _config_view(rev: store.WatchRuleRevision) -> dict[str, Any]:
    return {
        "symbol": rev.symbol,
        "market": rev.market,
        "currency": rev.currency,
        "quote_basis": rev.quote_basis,
        "direction": rev.direction,
        "threshold": _threshold_view(rev),
        "expires_at": _iso(rev.expires_at),
        "trigger_mode": rev.trigger_mode,
        "action": rev.action,
        "task": rev.task,
        "budget": dict(rev.budget_json or {}),
        "on_create_already_met": rev.on_create_already_met,
        "disconnect_recovery": rev.disconnect_recovery,
    }


def rule_view(rule: store.WatchRule, rev: store.WatchRuleRevision | None) -> dict[str, Any]:
    return {
        "id": str(rule.id),
        "research_id": str(rule.research_id),
        "plan_id": str(rule.plan_id) if rule.plan_id else None,
        "name": rule.name,
        "status": rule.status,
        "version": rule.current_version,
        **(_config_view(rev) if rev else {}),
        "last_check_at": _iso(rule.last_check_at),
        "last_valid_quote_at": _iso(rule.last_valid_quote_at),
        "last_valid_quote_price": _decimal_text(rule.last_valid_quote_price),
        # DATA-10 触发状态：资格是否可用、最近基线价、最近触发/抑制原因。
        "armed": rule.armed,
        "baseline_price": _decimal_text(rule.baseline_price),
        "last_triggered_at": _iso(rule.last_triggered_at),
        "last_suppressed_reason": rule.last_suppressed_reason,
        "created_at": _iso(rule.created_at),
        "updated_at": _iso(rule.updated_at),
    }


async def _load_rule(
    session: AsyncSession, *, user_id: Any, rule_id: Any
) -> store.WatchRule | None:
    return (
        await session.execute(
            select(store.WatchRule).where(
                store.WatchRule.id == rule_id, store.WatchRule.user_id == user_id
            )
        )
    ).scalar_one_or_none()


async def _load_plan(
    session: AsyncSession, *, plan_id: Any, user_id: Any, research_id: Any
) -> store.InvestmentPlan | None:
    return (
        await session.execute(
            select(store.InvestmentPlan).where(
                store.InvestmentPlan.id == plan_id,
                store.InvestmentPlan.user_id == user_id,
                store.InvestmentPlan.research_id == research_id,
            )
        )
    ).scalar_one_or_none()


async def _ensure_research(session: AsyncSession, *, user_id: Any, research_id: Any) -> None:
    research = (
        await session.execute(
            select(store.Session).where(
                store.Session.id == research_id, store.Session.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if research is None:
        raise biz.NotFoundOrForbiddenError("研究不存在或无权访问")


async def create_rule(
    session: AsyncSession,
    *,
    user_id: Any,
    research_id: Any,
    plan_id: Any,
    name: str,
    spec: dict[str, Any],
    idempotency_key: str,
    source_kind: str = "form",
    source_ref: str | None = None,
) -> biz.WriteOutcome:
    name = str(name or "").strip()
    if not name:
        raise biz.ValidationError("规则名称不能为空", fields={"name": "请填写可识别的规则名称"})
    payload = {
        "research_id": str(research_id),
        "plan_id": str(plan_id) if plan_id else None,
        "name": name,
        "spec": spec,
    }

    async def _execute() -> dict[str, Any]:
        await _ensure_research(session, user_id=user_id, research_id=research_id)
        if plan_id is not None:
            plan = await _load_plan(
                session, plan_id=plan_id, user_id=user_id, research_id=research_id
            )
            if plan is None:
                raise biz.NotFoundOrForbiddenError("计划不存在或不属于该研究")
        columns, threshold_raw = _parse_fields(spec, allow_plan_id=False)
        merged = {**_defaults(), **columns}
        missing = [
            key
            for key in ("symbol", "market", "currency", "direction", "action")
            if merged.get(key) in (None, "")
        ]
        if missing:
            raise biz.ValidationError(
                "规则配置不完整", fields={key: "该字段为必填" for key in missing}
            )
        if threshold_raw is _UNSET:
            raise biz.ValidationError("缺少阈值", fields={"threshold": "请填写触发阈值（价格）"})
        low, high = _finalize_threshold(merged["direction"], threshold_raw)
        rule = store.WatchRule(
            user_id=user_id, research_id=research_id, plan_id=plan_id, name=name, status=ACTIVE
        )
        session.add(rule)
        await session.flush()
        session.add(
            store.WatchRuleRevision(
                rule_id=rule.id,
                version=1,
                threshold_low=low,
                threshold_high=high,
                source_kind=source_kind,
                source_ref=source_ref,
                changed_fields={"fields": sorted(columns)},
                **merged,
            )
        )
        rule.current_version = 1
        await session.flush()
        _append_audit(
            session,
            user_id=user_id,
            action="watch_rule.create",
            detail={"rule_id": str(rule.id), "version": 1},
        )
        await session.flush()
        return {"rule_id": str(rule.id), "version": 1, "status": ACTIVE}

    return await biz.run_write(
        session,
        user_id=user_id,
        scope="watch_rule.create",
        idempotency_key=idempotency_key,
        payload=payload,
        execute=_execute,
    )


async def update_rule(
    session: AsyncSession,
    *,
    user_id: Any,
    rule_id: Any,
    expected_version: int | None,
    patch: dict[str, Any],
    idempotency_key: str,
    source_kind: str = "form",
    source_ref: str | None = None,
) -> biz.WriteOutcome:
    payload = {
        "rule_id": str(rule_id),
        "expected_version": expected_version,
        "patch": patch,
    }

    async def _execute() -> dict[str, Any]:
        rule = (
            await session.execute(
                select(store.WatchRule)
                .where(store.WatchRule.id == rule_id, store.WatchRule.user_id == user_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if rule is None:
            raise biz.NotFoundOrForbiddenError("监控规则不存在或无权访问")
        if rule.status == CANCELLED:
            raise biz.RuleCancelledError("规则已取消，不能修改", current={"status": CANCELLED})
        if expected_version is None:
            raise biz.ValidationError(
                "缺少预期版本", fields={"expected_version": "修改必须携带当前版本号"}
            )
        if expected_version != rule.current_version:
            raise biz.RevisionConflictError(
                "规则已被其他窗口修改",
                current={"version": rule.current_version},
                fields={"expected_version": f"当前版本为 {rule.current_version}"},
            )
        prev = await _latest_revision(session, rule.id, rule.current_version)
        columns, threshold_raw = _parse_fields(patch, allow_plan_id=True)
        merged = {**(_revision_columns(prev) if prev else {}), **columns}

        plan_id = rule.plan_id
        if "plan_id" in patch:
            plan_id = _as_optional_uuid(patch["plan_id"], "plan_id")
            if plan_id is not None:
                plan = await _load_plan(
                    session, plan_id=plan_id, user_id=user_id, research_id=rule.research_id
                )
                if plan is None:
                    raise biz.NotFoundOrForbiddenError("计划不存在或不属于该研究")
        # 阈值依赖合并后的方向：只有本次提交触碰 threshold 才重新换算，
        # 否则沿用旧版本的已冻结阈值（计划改版等无关修改不静默改变阈值）。
        direction = merged["direction"]
        if threshold_raw is _UNSET:
            low, high = (prev.threshold_low, prev.threshold_high) if prev else (None, None)
            if direction == "range":
                # 切换为区间方向但未同时提交 low/high：旧值可能是 up/down 遗留，
                # 不得静默复用出非法区间（low 缺失或 low >= high）。
                if low is None or high is None or not low < high:
                    raise biz.ValidationError(
                        "区间阈值不完整",
                        fields={
                            "threshold": "切换为区间方向后需同时提供 {low, high} 且 low < high"
                        },
                    )
            else:
                # up/down 只保留单阈值；range 遗留的 high 不进入 up/down 版本。
                high = None
        else:
            low, high = _finalize_threshold(direction, threshold_raw)
        # 版本行的阈值列由显式参数给出，不再从 merged 展开，避免重复关键字。
        merged.pop("threshold_low", None)
        merged.pop("threshold_high", None)

        changed = sorted(set(patch) & SPEC_KEYS)
        new_version = rule.current_version + 1
        session.add(
            store.WatchRuleRevision(
                rule_id=rule.id,
                version=new_version,
                threshold_low=low,
                threshold_high=high,
                source_kind=source_kind,
                source_ref=source_ref,
                changed_fields={
                    "fields": changed,
                    "plan_id": str(plan_id) if plan_id else None,
                },
                **merged,
            )
        )
        rule.current_version = new_version
        if rule.plan_id != plan_id:
            rule.plan_id = plan_id
        # 改版不复用旧版报价基线与触发资格：新版本重新布防（DATA-10 消费）。
        rule.armed = True
        rule.baseline_price = None
        rule.last_suppressed_reason = None
        await session.flush()
        _append_audit(
            session,
            user_id=user_id,
            action="watch_rule.update",
            detail={
                "rule_id": str(rule.id),
                "version": new_version,
                "changed_fields": changed,
            },
        )
        await session.flush()
        return {
            "rule_id": str(rule.id),
            "version": new_version,
            "status": rule.status,
            "changed_fields": changed,
        }

    return await biz.run_write(
        session,
        user_id=user_id,
        scope="watch_rule.update",
        idempotency_key=idempotency_key,
        payload=payload,
        execute=_execute,
    )


_TRANSITIONS: dict[str, frozenset[str]] = {
    ACTIVE: frozenset({PAUSED, CANCELLED}),
    PAUSED: frozenset({ACTIVE, CANCELLED}),
}


async def set_rule_status(
    session: AsyncSession,
    *,
    user_id: Any,
    rule_id: Any,
    expected_version: int | None,
    target: str,
    idempotency_key: str,
    scope: str,
    source_kind: str = "form",
    source_ref: str | None = None,
) -> biz.WriteOutcome:
    payload = {"rule_id": str(rule_id), "expected_version": expected_version, "target": target}

    async def _execute() -> dict[str, Any]:
        rule = (
            await session.execute(
                select(store.WatchRule)
                .where(store.WatchRule.id == rule_id, store.WatchRule.user_id == user_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if rule is None:
            raise biz.NotFoundOrForbiddenError("监控规则不存在或无权访问")
        if expected_version is None:
            raise biz.ValidationError(
                "缺少预期版本", fields={"expected_version": "操作必须携带当前版本号"}
            )
        if expected_version != rule.current_version:
            raise biz.RevisionConflictError(
                "规则已被其他窗口修改",
                current={"version": rule.current_version},
                fields={"expected_version": f"当前版本为 {rule.current_version}"},
            )
        if rule.status == target:
            return {
                "rule_id": str(rule.id),
                "version": rule.current_version,
                "status": rule.status,
                "unchanged": True,
            }
        if rule.status == CANCELLED:
            raise biz.RuleCancelledError(
                "规则已取消，不能恢复或暂停", current={"status": CANCELLED}
            )
        if target not in _TRANSITIONS.get(rule.status, frozenset()):
            raise biz.ValidationError(
                "状态流转不合法", fields={"status": f"不能从 {rule.status} 变为 {target}"}
            )
        rule.status = target
        await session.flush()
        _append_audit(
            session,
            user_id=user_id,
            action=f"watch_rule.{target}",
            detail={"rule_id": str(rule.id), "version": rule.current_version},
        )
        await session.flush()
        return {
            "rule_id": str(rule.id),
            "version": rule.current_version,
            "status": target,
            "unchanged": False,
        }

    return await biz.run_write(
        session,
        user_id=user_id,
        scope=scope,
        idempotency_key=idempotency_key,
        payload=payload,
        execute=_execute,
    )


async def _latest_revision(
    session: AsyncSession, rule_id: Any, version: int
) -> store.WatchRuleRevision | None:
    return (
        await session.execute(
            select(store.WatchRuleRevision).where(
                store.WatchRuleRevision.rule_id == rule_id,
                store.WatchRuleRevision.version == version,
            )
        )
    ).scalar_one_or_none()


def _as_optional_uuid(value: Any, field: str) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        raise biz.NotFoundOrForbiddenError("对象不存在或无权访问") from None


async def record_check(
    session: AsyncSession,
    *,
    rule_id: Any,
    checked_at: datetime | None = None,
    quote_at: datetime | None = None,
    price: Decimal | None = None,
) -> bool:
    """记录最近检查与有效行情时间（DATA-10 判定侧写入，不开放 HTTP 入口）。

    无可靠观测时调用方不应传 ``quote_at``：不能把本地 now 冒充实时新行情。
    返回 ``False`` 表示规则不存在或已取消。
    """
    rule = (
        await session.execute(
            select(store.WatchRule).where(store.WatchRule.id == rule_id).with_for_update()
        )
    ).scalar_one_or_none()
    if rule is None or rule.status == CANCELLED:
        return False
    rule.last_check_at = checked_at or _now()
    if quote_at is not None:
        rule.last_valid_quote_at = quote_at
    if price is not None:
        rule.last_valid_quote_price = price
    await session.flush()
    return True


async def list_rules(
    session: AsyncSession,
    *,
    user_id: Any,
    research_id: Any | None = None,
    status: str | None = None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    stmt = select(store.WatchRule).where(store.WatchRule.user_id == user_id)
    if research_id is not None:
        stmt = stmt.where(store.WatchRule.research_id == research_id)
    if status is not None:
        stmt = stmt.where(store.WatchRule.status == status)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(store.WatchRule.created_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    items = []
    for rule in rows:
        rev = await _latest_revision(session, rule.id, rule.current_version)
        items.append(rule_view(rule, rev))
    return items, total


async def get_rule(session: AsyncSession, *, user_id: Any, rule_id: Any) -> dict[str, Any] | None:
    rule = await _load_rule(session, user_id=user_id, rule_id=rule_id)
    if rule is None:
        return None
    rev = await _latest_revision(session, rule.id, rule.current_version)
    return rule_view(rule, rev)


async def list_rule_revisions(
    session: AsyncSession,
    *,
    user_id: Any,
    rule_id: Any,
    limit: int,
    offset: int,
) -> list[dict[str, Any]] | None:
    rule = await _load_rule(session, user_id=user_id, rule_id=rule_id)
    if rule is None:
        return None
    rows = (
        (
            await session.execute(
                select(store.WatchRuleRevision)
                .where(store.WatchRuleRevision.rule_id == rule.id)
                .order_by(store.WatchRuleRevision.version.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "version": row.version,
            "created_at": _iso(row.created_at),
            "source_kind": row.source_kind,
            "changed_fields": (row.changed_fields or {}).get("fields", []),
            "config": _config_view(row),
        }
        for row in rows
    ]
