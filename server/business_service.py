"""统一业务写入服务（DATA-03 / PR-BIZ-02/04）。

表单、聊天命令和 JSON/multipart 提交共用这一层；它是归属、真实输入准入、版本、
幂等和审计的强制方。契约见 docs/design/web-business-data-contract.md。

三条不可协商的规则：

1. **owner 由调用方（认证）传入**，请求体里的 ``user_id`` 一律拒绝——模型与客户端
   都不能指定他人的身份（PR-BIZ-04）。
2. **假设、估计和疑问中的候选值不是有效输入**。它们不写入有效字段，也不触发依赖
   这些字段的计算；用户明确提供的值才落库（PR-BIZ-02、§3.4）。
3. **版本只追加**：每次修改写一个新的 ``revision`` 行；``expected_revision`` 与当前
   版本不一致时返回冲突和当前值，绝不静默覆盖。

本模块的函数**不自行 commit**：它们假设调用方持有事务（见 :func:`business_transaction`），
这样“业务变更 + 版本 + 审计 + 幂等记录”要么一起生效，要么一起消失（DATA-06 的前提）。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from server import store

# ——— 契约常量 ——————————————————————————————————————————————————————————

#: 十进制文本：不接受科学计数法、千分位、前导 +、NaN/Infinity（契约 §1.1）。
DECIMAL_TEXT = re.compile(r"^-?(0|[1-9]\d*)(\.\d+)?$")

#: 幂等结果与操作记录的保留期；清理只影响“还能查多久”，不影响已发生的事实。
IDEMPOTENCY_TTL = timedelta(hours=24)

#: 请求体中出现的这些键一律拒绝：所有者只能来自认证上下文。
FORBIDDEN_OWNER_KEYS = frozenset({"user_id", "owner_id", "owner"})

#: 只接受“用户明确提供”与“外部观测”作为可计算输入。
EFFECTIVE_STATUSES = frozenset({"user_provided", "external_observed"})

#: 假设 / 估计 / 疑问候选：一律拒绝写入有效字段（AC-02、AC-25、AC-28）。
REJECTED_STATUSES: dict[str, str] = {
    "assumed": "假设值不能作为真实资料，请填写实际值",
    "estimated": "估计值不能作为真实资料，请填写实际值",
    "questioned": "疑问中的候选值需要先明确，不能先写入再追问",
}

ACCOUNT_FIELDS = frozenset(
    {"total_capital", "available_capital", "capital_basis", "currency", "as_of"}
)
PLAN_FIELDS = frozenset(
    {
        "symbol",
        "market",
        "asset_type",
        "direction",
        "plan_price",
        "plan_price_low",
        "plan_price_high",
        "target_price",
        "risk_budget_value",
        "risk_budget_unit",
        "position_limit_value",
        "position_limit_unit",
        "time_window",
        "invalidation",
        "profit_loss_ratio",
        "profit_loss_ratio_definition",
        "currency",
        "as_of",
    }
)
TRADE_FIELDS = frozenset(
    {"symbol", "market", "side", "quantity", "price", "currency", "fees", "traded_at"}
)

#: 需要十进制校验并按精确数值存储的字段。
NUMERIC_FIELDS = frozenset(
    {
        "total_capital",
        "available_capital",
        "plan_price",
        "plan_price_low",
        "plan_price_high",
        "target_price",
        "risk_budget_value",
        "position_limit_value",
        "profit_loss_ratio",
        "quantity",
        "price",
        "fees",
    }
)
#: 时间字段：业务时点与成交时间，统一 UTC 存储（契约 §1.3）。
DATETIME_FIELDS = frozenset({"as_of", "traded_at"})

#: 数值必须带单位，否则 2% 与 2 无法区分（契约 §1.1）。
UNIT_REQUIRED_FIELDS = frozenset({"risk_budget_value", "position_limit_value"})
UNIT_BY_FIELD = {
    "risk_budget_value": "risk_budget_unit",
    "position_limit_value": "position_limit_unit",
}

GROUP_FIELDS: dict[str, frozenset[str]] = {
    "account": ACCOUNT_FIELDS,
    "plan": PLAN_FIELDS,
    "trade": TRADE_FIELDS,
}

_ACCOUNT_VALUE_COLUMNS = (
    "total_capital",
    "available_capital",
    "capital_basis",
    "currency",
    "as_of",
)
_PLAN_VALUE_COLUMNS = (
    "symbol",
    "market",
    "asset_type",
    "direction",
    "plan_price",
    "plan_price_low",
    "plan_price_high",
    "target_price",
    "risk_budget_value",
    "risk_budget_unit",
    "position_limit_value",
    "position_limit_unit",
    "time_window",
    "invalidation",
    "profit_loss_ratio",
    "profit_loss_ratio_definition",
    "currency",
    "as_of",
)
_TRADE_COLUMNS = ("symbol", "market", "side", "quantity", "price", "currency", "fees", "traded_at")

#: 供快照/解析器复用的版本值列名（见 :mod:`server.investment_snapshot`）。
ACCOUNT_VALUE_COLUMNS = _ACCOUNT_VALUE_COLUMNS
PLAN_VALUE_COLUMNS = _PLAN_VALUE_COLUMNS


# ——— 错误模型 ——————————————————————————————————————————————————————————


class BusinessError(Exception):
    """业务错误基类；``to_payload`` 即契约 §2 的错误信封。"""

    code = "validation_error"
    http_status = 400
    retryable = False
    remedy = "fix_fields"

    def __init__(
        self,
        message: str,
        *,
        fields: dict[str, str] | None = None,
        current: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.fields = fields or {}
        self.current = current or {}

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "fields": self.fields,
                "current": self.current,
                "retryable": self.retryable,
                "remedy": self.remedy,
            }
        }


class ValidationError(BusinessError):
    code = "validation_error"


class UnknownFieldError(BusinessError):
    code = "unknown_field_rejected"
    remedy = "fix_fields"


class OwnerNotSettableError(BusinessError):
    code = "unknown_field_rejected"
    remedy = "fix_fields"


class PurposeRequirementError(BusinessError):
    """用途必需的真实字段缺失或尚未明确。"""

    code = "purpose_requirement_unmet"
    remedy = "clarify_value"


class AssumptionRejectedError(BusinessError):
    """假设 / 估计 / 疑问候选值：不写入有效字段，也不执行依赖计算。"""

    code = "assumption_rejected"
    remedy = "clarify_value"


class RevisionConflictError(BusinessError):
    """expected_revision 与当前版本不一致：返回当前版本，不静默覆盖。"""

    code = "revision_conflict"
    http_status = 409
    retryable = True
    remedy = "reload_and_resubmit"


class IdempotencyReuseError(BusinessError):
    code = "idempotency_key_reuse"
    http_status = 409
    remedy = "fix_fields"


class OperationPendingError(BusinessError):
    """同一幂等键的上一次写入还在进行：先查询，不盲目重发。"""

    code = "operation_pending"
    http_status = 409
    retryable = True
    remedy = "wait"


class ObjectArchivedError(BusinessError):
    code = "archived"
    http_status = 409
    remedy = "reload_and_resubmit"


class NotFoundOrForbiddenError(BusinessError):
    """不存在与无权一律同一结果，不泄漏差异（契约 §1.4）。"""

    code = "not_found"
    http_status = 404
    remedy = "contact_support"


class SnapshotAbsentError(BusinessError):
    """Run 没有业务快照（旧的非业务 Run）：明确报缺，不用当前资料回填。"""

    code = "snapshot_absent"
    http_status = 404
    remedy = "contact_support"


class QueueFullError(BusinessError):
    """同一研究的待执行队列已达上限：拒绝新建，先消化已有任务（DATA-06）。"""

    code = "quota_exceeded"
    http_status = 429
    retryable = True
    remedy = "wait"


# ——— 输入准入 ——————————————————————————————————————————————————————————


@dataclass(frozen=True)
class AdmittedValue:
    value: Decimal | str | datetime | None
    currency: str | None = None
    unit: str | None = None
    as_of: datetime | None = None
    status: str = "user_provided"


@dataclass(frozen=True)
class AdmissionResult:
    values: dict[str, AdmittedValue]
    #: 用户主动保存但字段缺失的项（field → 说明）。它们不进入有效字段。
    incomplete: dict[str, str]


def _normalise_spec(field: str, spec: Any) -> dict[str, Any]:
    if isinstance(spec, dict):
        unknown = set(spec) - {"value", "currency", "unit", "as_of", "status"}
        if unknown:
            raise UnknownFieldError(
                "字段声明包含未知键", fields={field: f"未知键：{', '.join(sorted(unknown))}"}
            )
        return spec
    if spec is None or isinstance(spec, str | int | float):
        return {"value": spec}
    raise ValidationError("字段声明格式无法识别", fields={field: "需要字符串或 {value,...} 对象"})


def _parse_datetime(field: str, raw: str) -> datetime:
    """时间统一按 UTC 解析；没有时区标记的输入按 UTC 处理并明确记录。"""
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValidationError(
            "时间格式不正确", fields={field: "请使用 ISO 8601，例如 2026-10-02T00:00:00Z"}
        ) from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def admit_group(group: str, declared: dict[str, Any] | None) -> AdmissionResult:
    """按契约校验一组字段：未知字段、假设/估计值、十进制格式与单位。"""
    allowed = GROUP_FIELDS.get(group)
    if allowed is None:
        raise UnknownFieldError(f"未知字段组：{group}")

    declared = declared or {}
    # 所有者键先判：它是“不允许客户端设定”，而不是“字段不存在”。
    for name in FORBIDDEN_OWNER_KEYS:
        if name in declared:
            raise OwnerNotSettableError(
                "所有者由服务端绑定，不接受请求体指定", fields={name: "该字段不可由客户端设置"}
            )
    unknown = sorted(set(declared) - allowed)
    if unknown:
        raise UnknownFieldError(
            "业务结构包含未知字段", fields={name: "该字段不属于本对象的契约" for name in unknown}
        )

    values: dict[str, AdmittedValue] = {}
    incomplete: dict[str, str] = {}

    for name in sorted(declared):
        if name in FORBIDDEN_OWNER_KEYS:
            raise OwnerNotSettableError(
                "所有者由服务端绑定，不接受请求体指定", fields={name: "该字段不可由客户端设置"}
            )
        spec = _normalise_spec(name, declared[name])
        status = str(spec.get("status") or "user_provided")
        if status in REJECTED_STATUSES:
            # 假设/估计/疑问候选：拒绝写入，并说明需要什么。
            raise AssumptionRejectedError(
                REJECTED_STATUSES[status], fields={name: REJECTED_STATUSES[status]}
            )
        raw = spec.get("value")
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            incomplete[name] = "该字段尚未填写"
            continue
        if not isinstance(raw, str):
            # JS Number 直传在这里被挡住：浮点往返已经改变了用户输入的数字。
            raise ValidationError(
                "数值必须作为十进制字符串传输", fields={name: "请以字符串形式提交，不要使用 Number"}
            )
        text = raw.strip()
        if name in NUMERIC_FIELDS:
            if not DECIMAL_TEXT.match(text):
                raise ValidationError(
                    "数值格式不正确",
                    fields={name: "请填写非负十进制文本，不使用千分位或科学计数法"},
                )
            if text.startswith("-"):
                raise ValidationError("金额/价格/数量不接受负数", fields={name: "请填写非负数值"})
            value: Decimal | str | datetime = Decimal(text)
        elif name in DATETIME_FIELDS:
            value = _parse_datetime(name, text)
        else:
            value = text
        if name in UNIT_REQUIRED_FIELDS:
            unit_key = UNIT_BY_FIELD[name]
            if not str(declared.get(unit_key) or "").strip():
                raise ValidationError(
                    "数值缺少单位", fields={unit_key: "请说明该数值的单位（百分比 / 金额 / 比例）"}
                )
        values[name] = AdmittedValue(
            value=value,
            currency=spec.get("currency"),
            unit=spec.get("unit") or declared.get(UNIT_BY_FIELD.get(name, "")),
            as_of=spec.get("as_of"),
            status=status,
        )
    return AdmissionResult(values=values, incomplete=incomplete)


def evaluate_purpose(
    use_case: str,
    groups: dict[str, AdmissionResult],
    *,
    only_groups: tuple[str, ...] | None = None,
) -> dict[str, str]:
    """按用途检查必需字段；返回 ``字段 → 说明``，空表示满足。

    ``only_groups`` 用于对象级写入：创建账户时只裁决账户字段，计划字段由创建计划
    时裁决；完整分析准入在提交 Run 时一次校验全部组（DATA-05）。
    """
    missing: dict[str, str] = {}

    def need(group: str, name: str, message: str) -> None:
        admission = groups.get(group)
        if admission is None or name not in admission.values:
            missing[f"{group}.{name}"] = message

    def need_any(group: str, names: tuple[str, ...], message: str) -> None:
        admission = groups.get(group)
        if admission is None or not any(n in admission.values for n in names):
            missing["|".join(f"{group}.{n}" for n in names)] = message

    if use_case == "general_reading":
        return missing

    need("account", "currency", "请选择账户币种")
    need("account", "capital_basis", "请说明资金口径（总资金 / 可用资金）")
    need("account", "as_of", "请选择资金数据时点")
    need_any(
        "account",
        ("total_capital", "available_capital"),
        "请如实填写当前账户总资金或可用资金",
    )

    if use_case in {"plan_analysis", "holding_cost"}:
        need("plan", "symbol", "请填写标的")
        need("plan", "market", "请选择市场")
        need("plan", "direction", "请选择方向")
        need_any(
            "plan",
            ("plan_price", "plan_price_low", "plan_price_high"),
            "请填写计划买入价或价格区间",
        )
        need("plan", "target_price", "计划分析需要目标价")

    if use_case == "holding_cost":
        # 依赖实际成本的计算必须拿到用户明确提供的成交事实（AC-25、AC-26）。
        need("trade", "side", "请说明成交方向")
        need("trade", "quantity", "请填写成交数量")
        need("trade", "price", "已买入时请填写实际成交价，不能用现价或计划价替代")
        need("trade", "traded_at", "请填写成交时间")

    if only_groups:
        allowed = set(only_groups)
        missing = {key: message for key, message in missing.items() if key.split(".")[0] in allowed}
    return missing


# ——— 幂等与事务 ————————————————————————————————————————————————————————


def _digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class WriteOutcome:
    operation_id: str
    replayed: bool
    result: dict[str, Any]


@asynccontextmanager
async def business_transaction() -> AsyncIterator[AsyncSession]:
    """提供一个已开启事务的业务会话；异常即回滚，不留下半个写入。"""
    session = await store.session_scope()
    async with session, session.begin():
        yield session


async def _claim_operation(
    session: AsyncSession,
    *,
    user_id: Any,
    scope: str,
    idempotency_key: str,
    payload: dict[str, Any],
) -> tuple[store.BusinessOperation | None, dict[str, Any] | None]:
    """占用幂等键。返回 ``(新记录, 命中重放的结果)``。

    插入放在 SAVEPOINT 里：唯一冲突时只需回滚保存点，外层事务仍可用于读旧结果。
    """
    digest = _digest(payload)
    row = store.BusinessOperation(
        user_id=user_id,
        scope=scope,
        idempotency_key=idempotency_key,
        request_digest=digest,
        status="in_progress",
        expires_at=datetime.now(UTC) + IDEMPOTENCY_TTL,
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        existing = (
            await session.execute(
                select(store.BusinessOperation).where(
                    store.BusinessOperation.user_id == user_id,
                    store.BusinessOperation.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise
        if existing.request_digest != digest:
            raise IdempotencyReuseError(
                "同一幂等键携带了不同内容",
                current={"operation_id": str(existing.id), "scope": existing.scope},
            ) from None
        if existing.status != "succeeded":
            raise OperationPendingError(
                "上一次提交仍在处理或尚未确定结果，请先查询操作结果",
                current={"operation_id": str(existing.id)},
            ) from None
        return None, dict(existing.result_json or {})
    return row, None


async def run_write(
    session: AsyncSession,
    *,
    user_id: Any,
    scope: str,
    idempotency_key: str,
    payload: dict[str, Any],
    execute: Callable[[], Awaitable[dict[str, Any]]],
) -> WriteOutcome:
    """在一个事务内执行写入，并把结果记入幂等台账。

    ``execute`` 抛 :class:`BusinessError` 时调用方回滚：本次业务变更、版本、审计与
    幂等记录一起消失，客户端可修正后重新提交（DATA-06 的原子前提）。
    """
    row, replayed_result = await _claim_operation(
        session, user_id=user_id, scope=scope, idempotency_key=idempotency_key, payload=payload
    )
    if replayed_result is not None:
        return WriteOutcome(
            operation_id=str(replayed_result.get("operation_id", "")),
            replayed=True,
            result=replayed_result,
        )
    if row is None:  # pragma: no cover — _claim_operation 必返回记录或重放结果之一
        raise RuntimeError("幂等记录缺失，拒绝在无记录的情况下完成写入")
    result = await execute()
    result = dict(result)
    result["operation_id"] = str(row.id)
    row.status = "succeeded"
    row.result_json = result
    await session.flush()
    return WriteOutcome(operation_id=str(row.id), replayed=False, result=result)


async def get_operation(
    session: AsyncSession, *, user_id: Any, operation_id: Any
) -> dict[str, Any] | None:
    """按所有者读取操作结果；不存在与他人操作都返回 None（不泄漏差异）。"""
    row = (
        await session.execute(
            select(store.BusinessOperation).where(
                store.BusinessOperation.id == operation_id,
                store.BusinessOperation.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None or row.status != "succeeded":
        return None
    return dict(row.result_json or {})


async def list_recent_operations(
    session: AsyncSession, *, user_id: Any, scope: str | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    stmt = select(store.BusinessOperation).where(store.BusinessOperation.user_id == user_id)
    if scope:
        stmt = stmt.where(store.BusinessOperation.scope == scope)
    rows = (
        (
            await session.execute(
                stmt.order_by(store.BusinessOperation.created_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "operation_id": str(r.id),
            "scope": r.scope,
            "status": r.status,
            "result": dict(r.result_json or {}),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


# ——— 版本与审计辅助 ——————————————————————————————————————————————————————


def _column_values(admission: AdmissionResult, columns: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in columns:
        value = admission.values.get(name)
        if value is None:
            continue
        out[name] = value.value
    return out


async def _load_revision_values(
    session: AsyncSession, model: type[Any], fk_column: str, object_id: Any, revision: int
) -> dict[str, Any]:
    row = (
        await session.execute(
            select(model).where(getattr(model, fk_column) == object_id, model.revision == revision)
        )
    ).scalar_one_or_none()
    if row is None:
        return {}
    # 注意用列名而不是列对象：Column.__eq__ 返回 SQL 表达式，直接做集合比较会抛 TypeError。
    return {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
        if column.name not in {"id", fk_column, "revision", "created_at"}
    }


def _changed_fields(prev: dict[str, Any], nxt: dict[str, Any]) -> list[str]:
    keys = set(prev) | set(nxt)
    changed = []
    for key in sorted(keys):
        before, after = prev.get(key), nxt.get(key)
        if before == after:
            continue
        # Decimal("20") 与 Decimal("20.0000000000") 数值相等，不算变更。
        if (
            (isinstance(before, Decimal) or isinstance(after, Decimal))
            and before is not None
            and after is not None
            and Decimal(before) == Decimal(after)
        ):
            continue
        changed.append(key)
    return changed


def _append_audit(
    session: AsyncSession, *, user_id: Any, action: str, detail: dict[str, Any]
) -> None:
    """审计只记对象标识与变更字段名，不写资金/持仓正文（DATA-14）。"""
    session.add(store.AuditLog(user_id=user_id, action=action, detail_json=detail))


def _require_complete(
    admission: AdmissionResult, *, allow_incomplete: bool, missing: dict[str, str] | None = None
) -> tuple[str, list[str]]:
    """裁定本次保存是完整资料还是待补充记录。

    “用户主动保存的不完整资料”必须可读，但不得显示为可用于依赖计算的有效资料：
    因此它落成持久记录并带 ``record_state='incomplete'``，UI 不得把它当完整资料用。
    """
    pending: dict[str, str] = dict(admission.incomplete)
    pending.update(missing or {})
    if pending and not allow_incomplete:
        raise PurposeRequirementError("存在未填写的必要字段", fields=pending)
    return ("incomplete" if pending else "submitted"), sorted(pending)


# ——— 写入入口 ————————————————————————————————————————————————————————


async def create_account(
    session: AsyncSession,
    *,
    user_id: Any,
    name: str,
    base_currency: str,
    declared: dict[str, Any],
    idempotency_key: str,
    source_kind: str = "form",
    source_ref: str | None = None,
    use_case: str = "general_reading",
    allow_incomplete: bool = False,
) -> WriteOutcome:
    if not name.strip():
        raise ValidationError("账户名称不能为空", fields={"name": "请填写可识别的账户名称"})
    if not base_currency.strip():
        raise ValidationError("币种不能为空", fields={"base_currency": "请选择基础币种"})

    admission = admit_group("account", declared)
    missing = evaluate_purpose(use_case, {"account": admission}, only_groups=("account",))
    if missing and not allow_incomplete:
        raise PurposeRequirementError("用途必需字段未满足", fields=missing)

    payload = {
        "name": name,
        "base_currency": base_currency,
        "declared": declared,
        "use_case": use_case,
    }

    async def _execute() -> dict[str, Any]:
        record_state, pending = _require_complete(
            admission, allow_incomplete=allow_incomplete, missing=missing
        )
        account = store.InvestmentAccount(
            user_id=user_id, name=name.strip(), base_currency=base_currency.strip()
        )
        session.add(account)
        await session.flush()
        values = _column_values(admission, _ACCOUNT_VALUE_COLUMNS)
        values.setdefault("currency", base_currency.strip())
        session.add(
            store.InvestmentAccountRevision(
                account_id=account.id,
                revision=1,
                record_state=record_state,
                source_kind=source_kind,
                source_ref=source_ref,
                changed_fields={"fields": sorted(admission.values)},
                **values,
            )
        )
        account.current_revision = 1
        await session.flush()
        _append_audit(
            session,
            user_id=user_id,
            action="business.account.create",
            detail={"account_id": str(account.id), "revision": 1, "record_state": record_state},
        )
        await session.flush()
        return {
            "account_id": str(account.id),
            "revision": 1,
            "record_state": record_state,
            "incomplete": pending,
        }

    return await run_write(
        session,
        user_id=user_id,
        scope="account.create",
        idempotency_key=idempotency_key,
        payload=payload,
        execute=_execute,
    )


async def update_account(
    session: AsyncSession,
    *,
    user_id: Any,
    account_id: Any,
    expected_revision: int | None,
    declared: dict[str, Any],
    idempotency_key: str,
    source_kind: str = "form",
    source_ref: str | None = None,
    allow_incomplete: bool = True,
) -> WriteOutcome:
    admission = admit_group("account", declared)
    payload = {
        "account_id": str(account_id),
        "declared": declared,
        "expected_revision": expected_revision,
    }

    async def _execute() -> dict[str, Any]:
        account = (
            await session.execute(
                select(store.InvestmentAccount).where(
                    store.InvestmentAccount.id == account_id,
                    store.InvestmentAccount.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if account is None:
            raise NotFoundOrForbiddenError("账户不存在或无权访问")
        if account.archived:
            raise ObjectArchivedError("账户已归档，不能被新的分析采用", current={"archived": True})
        if expected_revision is None:
            raise ValidationError(
                "缺少预期版本", fields={"expected_revision": "修改必须携带当前版本号"}
            )
        if expected_revision != account.current_revision:
            raise RevisionConflictError(
                "账户已被其他窗口修改",
                current={"revision": account.current_revision},
                fields={"expected_revision": f"当前版本为 {account.current_revision}"},
            )
        record_state, pending = _require_complete(admission, allow_incomplete=allow_incomplete)
        prev = await _load_revision_values(
            session,
            store.InvestmentAccountRevision,
            "account_id",
            account.id,
            account.current_revision,
        )
        merged = {k: v for k, v in prev.items() if k in _ACCOUNT_VALUE_COLUMNS}
        merged.update(_column_values(admission, _ACCOUNT_VALUE_COLUMNS))
        changed = _changed_fields(
            {k: v for k, v in prev.items() if k in _ACCOUNT_VALUE_COLUMNS}, merged
        )
        new_revision = account.current_revision + 1
        session.add(
            store.InvestmentAccountRevision(
                account_id=account.id,
                revision=new_revision,
                record_state=record_state,
                source_kind=source_kind,
                source_ref=source_ref,
                changed_fields={"fields": changed},
                **merged,
            )
        )
        account.current_revision = new_revision
        await session.flush()
        _append_audit(
            session,
            user_id=user_id,
            action="business.account.update",
            detail={
                "account_id": str(account.id),
                "revision": new_revision,
                "changed_fields": changed,
                "record_state": record_state,
            },
        )
        await session.flush()
        return {
            "account_id": str(account.id),
            "revision": new_revision,
            "changed_fields": changed,
            "record_state": record_state,
            "incomplete": pending,
        }

    return await run_write(
        session,
        user_id=user_id,
        scope="account.update",
        idempotency_key=idempotency_key,
        payload=payload,
        execute=_execute,
    )


async def create_plan(
    session: AsyncSession,
    *,
    user_id: Any,
    research_id: Any,
    name: str,
    declared: dict[str, Any],
    idempotency_key: str,
    source_kind: str = "form",
    source_ref: str | None = None,
    allow_incomplete: bool = True,
) -> WriteOutcome:
    """在**指定研究**内创建计划：归属来自会话，不接受客户端选择研究。"""
    if not name.strip():
        raise ValidationError("计划名称不能为空", fields={"name": "请填写可识别的计划名称"})
    admission = admit_group("plan", declared)
    missing = evaluate_purpose("plan_analysis", {"plan": admission}, only_groups=("plan",))
    if missing and not allow_incomplete:
        raise PurposeRequirementError("用途必需字段未满足", fields=missing)
    payload = {"research_id": str(research_id), "name": name, "declared": declared}

    async def _execute() -> dict[str, Any]:
        research = (
            await session.execute(
                select(store.Session).where(
                    store.Session.id == research_id, store.Session.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        if research is None:
            raise NotFoundOrForbiddenError("研究不存在或无权访问")
        record_state, pending = _require_complete(
            admission, allow_incomplete=allow_incomplete, missing=missing
        )
        plan = store.InvestmentPlan(research_id=research.id, user_id=user_id, name=name.strip())
        session.add(plan)
        await session.flush()
        session.add(
            store.InvestmentPlanRevision(
                plan_id=plan.id,
                revision=1,
                record_state=record_state,
                source_kind=source_kind,
                source_ref=source_ref,
                changed_fields={"fields": sorted(admission.values)},
                **_column_values(admission, _PLAN_VALUE_COLUMNS),
            )
        )
        plan.current_revision = 1
        await session.flush()
        _append_audit(
            session,
            user_id=user_id,
            action="business.plan.create",
            detail={
                "plan_id": str(plan.id),
                "research_id": str(research.id),
                "revision": 1,
                "record_state": record_state,
            },
        )
        await session.flush()
        return {
            "plan_id": str(plan.id),
            "research_id": str(research.id),
            "revision": 1,
            "record_state": record_state,
            "incomplete": pending,
        }

    return await run_write(
        session,
        user_id=user_id,
        scope="plan.create",
        idempotency_key=idempotency_key,
        payload=payload,
        execute=_execute,
    )


async def update_plan(
    session: AsyncSession,
    *,
    user_id: Any,
    plan_id: Any,
    expected_revision: int | None,
    declared: dict[str, Any],
    idempotency_key: str,
    source_kind: str = "form",
    source_ref: str | None = None,
    allow_incomplete: bool = True,
) -> WriteOutcome:
    admission = admit_group("plan", declared)
    payload = {
        "plan_id": str(plan_id),
        "declared": declared,
        "expected_revision": expected_revision,
    }

    async def _execute() -> dict[str, Any]:
        plan = (
            await session.execute(
                select(store.InvestmentPlan).where(
                    store.InvestmentPlan.id == plan_id,
                    store.InvestmentPlan.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if plan is None:
            raise NotFoundOrForbiddenError("计划不存在或无权访问")
        if plan.archived:
            raise ObjectArchivedError("计划已归档", current={"archived": True})
        if expected_revision is None:
            raise ValidationError(
                "缺少预期版本", fields={"expected_revision": "修改必须携带当前版本号"}
            )
        if expected_revision != plan.current_revision:
            raise RevisionConflictError(
                "计划已被其他窗口修改",
                current={"revision": plan.current_revision},
                fields={"expected_revision": f"当前版本为 {plan.current_revision}"},
            )
        record_state, pending = _require_complete(admission, allow_incomplete=allow_incomplete)
        prev = await _load_revision_values(
            session, store.InvestmentPlanRevision, "plan_id", plan.id, plan.current_revision
        )
        merged = {k: v for k, v in prev.items() if k in _PLAN_VALUE_COLUMNS}
        merged.update(_column_values(admission, _PLAN_VALUE_COLUMNS))
        changed = _changed_fields(
            {k: v for k, v in prev.items() if k in _PLAN_VALUE_COLUMNS}, merged
        )
        new_revision = plan.current_revision + 1
        session.add(
            store.InvestmentPlanRevision(
                plan_id=plan.id,
                revision=new_revision,
                record_state=record_state,
                source_kind=source_kind,
                source_ref=source_ref,
                changed_fields={"fields": changed},
                **merged,
            )
        )
        plan.current_revision = new_revision
        await session.flush()
        _append_audit(
            session,
            user_id=user_id,
            action="business.plan.update",
            detail={
                "plan_id": str(plan.id),
                "revision": new_revision,
                "changed_fields": changed,
                "record_state": record_state,
            },
        )
        await session.flush()
        return {
            "plan_id": str(plan.id),
            "revision": new_revision,
            "changed_fields": changed,
            "record_state": record_state,
            "incomplete": pending,
        }

    return await run_write(
        session,
        user_id=user_id,
        scope="plan.update",
        idempotency_key=idempotency_key,
        payload=payload,
        execute=_execute,
    )


async def register_trade(
    session: AsyncSession,
    *,
    user_id: Any,
    account_id: Any,
    declared: dict[str, Any],
    idempotency_key: str,
    source_kind: str = "form",
    source_ref: str | None = None,
) -> WriteOutcome:
    """登记用户提供的成交：不生成持仓推算，也不触发任何交易动作。"""
    admission = admit_group("trade", declared)
    required = {"side", "quantity", "price", "currency"}
    absent = sorted(required - set(admission.values))
    if absent:
        raise PurposeRequirementError(
            "成交记录缺少必要字段",
            fields={name: "请填写该项真实成交信息" for name in absent},
        )
    payload = {"account_id": str(account_id), "declared": declared}

    async def _execute() -> dict[str, Any]:
        account = (
            await session.execute(
                select(store.InvestmentAccount).where(
                    store.InvestmentAccount.id == account_id,
                    store.InvestmentAccount.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if account is None:
            raise NotFoundOrForbiddenError("账户不存在或无权访问")
        values = _column_values(admission, _TRADE_COLUMNS)
        trade = store.TradeRecord(
            user_id=user_id,
            account_id=account.id,
            symbol=str(values.get("symbol") or ""),
            market=values.get("market"),
            side=str(values["side"]),
            quantity=values["quantity"],
            price=values["price"],
            currency=str(values["currency"]),
            fees=values.get("fees"),
            traded_at=values.get("traded_at"),
            source_kind=source_kind,
            source_ref=source_ref,
        )
        session.add(trade)
        await session.flush()
        _append_audit(
            session,
            user_id=user_id,
            action="business.trade.register",
            detail={"trade_id": str(trade.id), "account_id": str(account.id)},
        )
        await session.flush()
        return {"trade_id": str(trade.id), "status": "active"}

    return await run_write(
        session,
        user_id=user_id,
        scope="trade.register",
        idempotency_key=idempotency_key,
        payload=payload,
        execute=_execute,
    )


async def correct_trade(
    session: AsyncSession,
    *,
    user_id: Any,
    trade_id: Any,
    declared: dict[str, Any],
    idempotency_key: str,
    source_kind: str = "form",
    source_ref: str | None = None,
) -> WriteOutcome:
    """更正成交：新建一行并保留原值，旧行标记为 corrected（AC-22）。"""
    admission = admit_group("trade", declared)
    if not admission.values:
        raise PurposeRequirementError("更正内容为空", fields={"declared": "请填写更正后的字段"})
    payload = {"trade_id": str(trade_id), "declared": declared}

    async def _execute() -> dict[str, Any]:
        original = (
            await session.execute(
                select(store.TradeRecord).where(
                    store.TradeRecord.id == trade_id,
                    store.TradeRecord.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if original is None:
            raise NotFoundOrForbiddenError("成交记录不存在或无权访问")
        if original.status != "active":
            raise RevisionConflictError(
                "该成交记录已被更正或取消", current={"status": original.status}
            )
        values = _column_values(admission, _TRADE_COLUMNS)
        corrected = store.TradeRecord(
            user_id=user_id,
            account_id=original.account_id,
            symbol=values.get("symbol") or original.symbol,
            market=values.get("market") or original.market,
            side=str(values.get("side") or original.side),
            quantity=values.get("quantity") or original.quantity,
            price=values.get("price") or original.price,
            currency=str(values.get("currency") or original.currency),
            fees=values.get("fees") if "fees" in values else original.fees,
            traded_at=values.get("traded_at") if "traded_at" in values else original.traded_at,
            source_kind=source_kind,
            source_ref=source_ref,
            corrects_id=original.id,
        )
        session.add(corrected)
        original.status = "corrected"
        await session.flush()
        _append_audit(
            session,
            user_id=user_id,
            action="business.trade.correct",
            detail={
                "trade_id": str(corrected.id),
                "corrects_id": str(original.id),
                "changed_fields": sorted(admission.values),
            },
        )
        await session.flush()
        return {
            "trade_id": str(corrected.id),
            "corrects_id": str(original.id),
            "status": "active",
        }

    return await run_write(
        session,
        user_id=user_id,
        scope="trade.correct",
        idempotency_key=idempotency_key,
        payload=payload,
        execute=_execute,
    )


async def set_research_link(
    session: AsyncSession,
    *,
    user_id: Any,
    research_id: Any,
    account_id: Any | None = None,
    primary_plan_id: Any | None = None,
    idempotency_key: str,
) -> WriteOutcome:
    """设置研究引用的账户与当前主计划；跨用户账户与跨研究计划在此被拦下。"""
    payload = {
        "research_id": str(research_id),
        "account_id": str(account_id) if account_id else None,
        "primary_plan_id": str(primary_plan_id) if primary_plan_id else None,
    }

    async def _execute() -> dict[str, Any]:
        research = (
            await session.execute(
                select(store.Session).where(
                    store.Session.id == research_id, store.Session.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        if research is None:
            raise NotFoundOrForbiddenError("研究不存在或无权访问")
        if account_id is not None:
            account = (
                await session.execute(
                    select(store.InvestmentAccount).where(
                        store.InvestmentAccount.id == account_id,
                        store.InvestmentAccount.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
            if account is None:
                raise NotFoundOrForbiddenError("账户不存在或无权访问")
        if primary_plan_id is not None:
            plan = (
                await session.execute(
                    select(store.InvestmentPlan).where(
                        store.InvestmentPlan.id == primary_plan_id,
                        store.InvestmentPlan.research_id == research.id,
                        store.InvestmentPlan.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
            if plan is None:
                # 跨研究计划：不允许把别的研究的计划选为本研究主计划（AC-01）。
                raise NotFoundOrForbiddenError("计划不属于该研究或无权访问")

        link = (
            await session.execute(
                select(store.ResearchInvestmentLink).where(
                    store.ResearchInvestmentLink.research_id == research.id
                )
            )
        ).scalar_one_or_none()
        if link is None:
            link = store.ResearchInvestmentLink(research_id=research.id, user_id=user_id)
            session.add(link)
        if account_id is not None:
            link.account_id = account_id
        if primary_plan_id is not None:
            link.primary_plan_id = primary_plan_id
        await session.flush()
        _append_audit(
            session,
            user_id=user_id,
            action="business.research_link.set",
            detail=payload,
        )
        await session.flush()
        return {
            "research_id": str(research.id),
            "account_id": str(link.account_id) if link.account_id else None,
            "primary_plan_id": str(link.primary_plan_id) if link.primary_plan_id else None,
        }

    return await run_write(
        session,
        user_id=user_id,
        scope="research_link.set",
        idempotency_key=idempotency_key,
        payload=payload,
        execute=_execute,
    )
