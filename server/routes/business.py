"""业务资料 HTTP 路由（DATA-03 收尾 / PR-BIZ-01—04）。

这一层只做三件事：绑定身份、解析请求、把服务层结果/错误翻译成契约信封。
准入、版本、幂等和归属判定全部在 ``server.business_service`` 里，路由不得重复实现，
也不得用自然语言或状态推断业务提交成功。

请求体刻意使用**原始 dict** 而不是 pydantic 模型：契约要求“业务子结构里的未知字段
必须明确拒绝”，而模型的默认行为是静默丢弃额外字段——那会让假设覆盖类请求悄悄通过。

  POST   /api/business/accounts                      创建账户（写）
  GET    /api/business/accounts                      自己的账户列表
  GET    /api/business/accounts/{id}                 账户详情与当前版本值
  PATCH  /api/business/accounts/{id}                 修改账户（写）
  GET    /api/business/accounts/{id}/revisions       版本历史
  POST   /api/business/sessions/{rid}/plans          在研究内创建计划（写）
  GET    /api/business/sessions/{rid}/plans          该研究的计划集合
  PATCH  /api/business/plans/{id}                    修改计划（写）
  GET    /api/business/plans/{id}/revisions          版本历史
  PUT    /api/business/sessions/{rid}/link           设置引用账户与主计划（写）
  GET    /api/business/sessions/{rid}/link           读取研究绑定
  POST   /api/business/accounts/{aid}/trades         登记成交（写）
  GET    /api/business/trades                        成交列表（按账户）
  POST   /api/business/trades/{id}/correct           更正成交（写）
  GET    /api/business/operations/{id}               按 operation_id 找回提交结果
  GET    /api/business/operations                    最近操作（刷新后恢复用）
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server import business_events, input_requests, store
from server import business_service as biz
from server.config import get_config
from server.deps import get_current_user
from server.orchestrator import get_orchestrator
from server.store import User as UserModel

router = APIRouter(prefix="/api/business", tags=["business"])

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


# ——— 错误 → HTTP 信封 ——————————————————————————————————————————————————


async def business_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """把 :class:`BusinessError` 渲染成契约 §2 的错误信封。"""
    if not isinstance(exc, biz.BusinessError):
        return JSONResponse(status_code=500, content={"error": {"code": "internal_error"}})
    return JSONResponse(status_code=exc.http_status, content=exc.to_payload())


# ——— 序列化辅助 ——————————————————————————————————————————————————————————


def _decimal_text(value: Decimal | None) -> str | None:
    """十进制以字符串出网，去掉无意义的尾随零但保留用户输入的小数位。"""
    if value is None:
        return None
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _account_values(row: Any) -> dict[str, Any]:
    return {
        "total_capital": _decimal_text(row.total_capital),
        "available_capital": _decimal_text(row.available_capital),
        "capital_basis": row.capital_basis,
        "currency": row.currency,
        "as_of": _iso(row.as_of),
        "record_state": row.record_state,
    }


def _plan_values(row: Any) -> dict[str, Any]:
    return {
        "symbol": row.symbol,
        "market": row.market,
        "asset_type": row.asset_type,
        "direction": row.direction,
        "plan_price": _decimal_text(row.plan_price),
        "plan_price_low": _decimal_text(row.plan_price_low),
        "plan_price_high": _decimal_text(row.plan_price_high),
        "target_price": _decimal_text(row.target_price),
        "risk_budget": {
            "value": _decimal_text(row.risk_budget_value),
            "unit": row.risk_budget_unit,
        },
        "position_limit": {
            "value": _decimal_text(row.position_limit_value),
            "unit": row.position_limit_unit,
        },
        "time_window": row.time_window,
        "invalidation": row.invalidation,
        "profit_loss_ratio": {
            "value": _decimal_text(row.profit_loss_ratio),
            "definition": row.profit_loss_ratio_definition,
        },
        "currency": row.currency,
        "as_of": _iso(row.as_of),
        "record_state": row.record_state,
    }


def _trade_view(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "account_id": str(row.account_id),
        "symbol": row.symbol,
        "market": row.market,
        "side": row.side,
        "quantity": _decimal_text(row.quantity),
        "price": _decimal_text(row.price),
        "currency": row.currency,
        "fees": _decimal_text(row.fees),
        "traded_at": _iso(row.traded_at),
        "status": row.status,
        "corrects_id": str(row.corrects_id) if row.corrects_id else None,
        "source_kind": row.source_kind,
        "created_at": _iso(row.created_at),
    }


async def _latest_revision(
    session: AsyncSession, model: Any, fk: str, object_id: Any, revision: int
) -> Any:
    return (
        await session.execute(
            select(model).where(getattr(model, fk) == object_id, model.revision == revision)
        )
    ).scalar_one_or_none()


def _require_key(key: str | None) -> str:
    if not key or not key.strip():
        raise biz.ValidationError(
            "缺少幂等键", fields={"Idempotency-Key": "写操作必须携带幂等键，便于超时后安全重试"}
        )
    return key.strip()


def _body_declared(body: dict[str, Any], key: str) -> dict[str, Any]:
    declared = body.get(key)
    if declared is None:
        return {}
    if not isinstance(declared, dict):
        raise biz.ValidationError("字段声明格式不正确", fields={key: "需要对象"})
    return declared


def _as_uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        # 与“不存在/无权”同结果，不泄漏 ID 是否合法以外的信息。
        raise biz.NotFoundOrForbiddenError("对象不存在或无权访问") from None


def _optional_time(value: Any, field: str) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise biz.ValidationError("时间格式不正确", fields={field: "需要 ISO 8601 时间"}) from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# ——— 账户 ————————————————————————————————————————————————————————————


@router.post("/accounts", status_code=201)
async def create_account(
    body: dict[str, Any],
    user: UserModel = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    key = _require_key(idempotency_key)
    name = str(body.get("name") or "").strip()
    base_currency = str(body.get("base_currency") or "").strip()
    async with biz.business_transaction() as session:
        outcome = await biz.create_account(
            session,
            user_id=user.id,
            name=name,
            base_currency=base_currency,
            declared=_body_declared(body, "declared"),
            idempotency_key=key,
            source_kind=str(body.get("source_kind") or "form"),
            source_ref=body.get("source_ref"),
            use_case=str(body.get("use_case") or "general_reading"),
            allow_incomplete=bool(body.get("allow_incomplete", False)),
        )
    return {"replayed": outcome.replayed, "operation_id": outcome.operation_id, **outcome.result}


@router.get("/accounts")
async def list_accounts(
    user: UserModel = Depends(get_current_user),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    async with biz.business_transaction() as session:
        total = (
            await session.execute(
                select(func.count())
                .select_from(store.InvestmentAccount)
                .where(store.InvestmentAccount.user_id == user.id)
            )
        ).scalar_one()
        rows = (
            (
                await session.execute(
                    select(store.InvestmentAccount)
                    .where(store.InvestmentAccount.user_id == user.id)
                    .order_by(store.InvestmentAccount.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        accounts = []
        for account in rows:
            revision = await _latest_revision(
                session,
                store.InvestmentAccountRevision,
                "account_id",
                account.id,
                account.current_revision,
            )
            accounts.append(
                {
                    "id": str(account.id),
                    "name": account.name,
                    "base_currency": account.base_currency,
                    "archived": account.archived,
                    "revision": account.current_revision,
                    "updated_at": _iso(account.updated_at),
                    "values": _account_values(revision) if revision else {},
                }
            )
    return {"accounts": accounts, "total": total, "has_more": offset + len(accounts) < total}


@router.get("/accounts/{account_id}")
async def get_account(
    account_id: str, user: UserModel = Depends(get_current_user)
) -> dict[str, Any]:
    async with biz.business_transaction() as session:
        account = (
            await session.execute(
                select(store.InvestmentAccount).where(
                    store.InvestmentAccount.id == _as_uuid(account_id, "account_id"),
                    store.InvestmentAccount.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if account is None:
            raise biz.NotFoundOrForbiddenError("账户不存在或无权访问")
        revision = await _latest_revision(
            session,
            store.InvestmentAccountRevision,
            "account_id",
            account.id,
            account.current_revision,
        )
        return {
            "id": str(account.id),
            "name": account.name,
            "base_currency": account.base_currency,
            "archived": account.archived,
            "revision": account.current_revision,
            "updated_at": _iso(account.updated_at),
            "values": _account_values(revision) if revision else {},
        }


@router.patch("/accounts/{account_id}")
async def update_account(
    account_id: str,
    body: dict[str, Any],
    user: UserModel = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    key = _require_key(idempotency_key)
    expected = body.get("expected_revision")
    async with biz.business_transaction() as session:
        outcome = await biz.update_account(
            session,
            user_id=user.id,
            account_id=_as_uuid(account_id, "account_id"),
            expected_revision=int(expected) if expected is not None else None,
            declared=_body_declared(body, "declared"),
            idempotency_key=key,
            source_kind=str(body.get("source_kind") or "form"),
            source_ref=body.get("source_ref"),
            allow_incomplete=bool(body.get("allow_incomplete", True)),
        )
    return {"replayed": outcome.replayed, "operation_id": outcome.operation_id, **outcome.result}


@router.get("/accounts/{account_id}/revisions")
async def list_account_revisions(
    account_id: str,
    user: UserModel = Depends(get_current_user),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    async with biz.business_transaction() as session:
        account = (
            await session.execute(
                select(store.InvestmentAccount).where(
                    store.InvestmentAccount.id == _as_uuid(account_id, "account_id"),
                    store.InvestmentAccount.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if account is None:
            raise biz.NotFoundOrForbiddenError("账户不存在或无权访问")
        rows = (
            (
                await session.execute(
                    select(store.InvestmentAccountRevision)
                    .where(store.InvestmentAccountRevision.account_id == account.id)
                    .order_by(store.InvestmentAccountRevision.revision.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
    return {
        "revisions": [
            {
                "revision": row.revision,
                "created_at": _iso(row.created_at),
                "source_kind": row.source_kind,
                "changed_fields": (row.changed_fields or {}).get("fields", []),
                "values": _account_values(row),
            }
            for row in rows
        ]
    }


# ——— 计划（从研究会话进入） ——————————————————————————————————————————————


@router.post("/sessions/{research_id}/plans", status_code=201)
async def create_plan(
    research_id: str,
    body: dict[str, Any],
    user: UserModel = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    key = _require_key(idempotency_key)
    async with biz.business_transaction() as session:
        outcome = await biz.create_plan(
            session,
            user_id=user.id,
            research_id=_as_uuid(research_id, "research_id"),
            name=str(body.get("name") or "").strip(),
            declared=_body_declared(body, "declared"),
            idempotency_key=key,
            source_kind=str(body.get("source_kind") or "form"),
            source_ref=body.get("source_ref"),
            allow_incomplete=bool(body.get("allow_incomplete", True)),
        )
    return {"replayed": outcome.replayed, "operation_id": outcome.operation_id, **outcome.result}


@router.get("/sessions/{research_id}/plans")
async def list_plans(
    research_id: str,
    user: UserModel = Depends(get_current_user),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    async with biz.business_transaction() as session:
        research = (
            await session.execute(
                select(store.Session).where(
                    store.Session.id == _as_uuid(research_id, "research_id"),
                    store.Session.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if research is None:
            raise biz.NotFoundOrForbiddenError("研究不存在或无权访问")
        rows = (
            (
                await session.execute(
                    select(store.InvestmentPlan)
                    .where(store.InvestmentPlan.research_id == research.id)
                    .order_by(store.InvestmentPlan.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        plans = []
        for plan in rows:
            revision = await _latest_revision(
                session,
                store.InvestmentPlanRevision,
                "plan_id",
                plan.id,
                plan.current_revision,
            )
            plans.append(
                {
                    "id": str(plan.id),
                    "research_id": str(plan.research_id),
                    "name": plan.name,
                    "status": plan.status,
                    "archived": plan.archived,
                    "revision": plan.current_revision,
                    "values": _plan_values(revision) if revision else {},
                }
            )
    return {"plans": plans}


@router.patch("/plans/{plan_id}")
async def update_plan(
    plan_id: str,
    body: dict[str, Any],
    user: UserModel = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    key = _require_key(idempotency_key)
    expected = body.get("expected_revision")
    async with biz.business_transaction() as session:
        outcome = await biz.update_plan(
            session,
            user_id=user.id,
            plan_id=_as_uuid(plan_id, "plan_id"),
            expected_revision=int(expected) if expected is not None else None,
            declared=_body_declared(body, "declared"),
            idempotency_key=key,
            source_kind=str(body.get("source_kind") or "form"),
            source_ref=body.get("source_ref"),
            allow_incomplete=bool(body.get("allow_incomplete", True)),
        )
    return {"replayed": outcome.replayed, "operation_id": outcome.operation_id, **outcome.result}


@router.get("/plans/{plan_id}/revisions")
async def list_plan_revisions(
    plan_id: str,
    user: UserModel = Depends(get_current_user),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    async with biz.business_transaction() as session:
        plan = (
            await session.execute(
                select(store.InvestmentPlan).where(
                    store.InvestmentPlan.id == _as_uuid(plan_id, "plan_id"),
                    store.InvestmentPlan.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if plan is None:
            raise biz.NotFoundOrForbiddenError("计划不存在或无权访问")
        rows = (
            (
                await session.execute(
                    select(store.InvestmentPlanRevision)
                    .where(store.InvestmentPlanRevision.plan_id == plan.id)
                    .order_by(store.InvestmentPlanRevision.revision.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
    return {
        "revisions": [
            {
                "revision": row.revision,
                "created_at": _iso(row.created_at),
                "source_kind": row.source_kind,
                "changed_fields": (row.changed_fields or {}).get("fields", []),
                "values": _plan_values(row),
            }
            for row in rows
        ]
    }


# ——— 研究绑定（账户引用 + 当前主计划） ——————————————————————————————————


@router.put("/sessions/{research_id}/link")
async def set_link(
    research_id: str,
    body: dict[str, Any],
    user: UserModel = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    key = _require_key(idempotency_key)
    account_raw = body.get("account_id")
    plan_raw = body.get("primary_plan_id")
    async with biz.business_transaction() as session:
        outcome = await biz.set_research_link(
            session,
            user_id=user.id,
            research_id=_as_uuid(research_id, "research_id"),
            account_id=_as_uuid(account_raw, "account_id") if account_raw else None,
            primary_plan_id=_as_uuid(plan_raw, "primary_plan_id") if plan_raw else None,
            idempotency_key=key,
        )
    return {"replayed": outcome.replayed, "operation_id": outcome.operation_id, **outcome.result}


@router.get("/sessions/{research_id}/link")
async def get_link(research_id: str, user: UserModel = Depends(get_current_user)) -> dict[str, Any]:
    async with biz.business_transaction() as session:
        link = (
            await session.execute(
                select(store.ResearchInvestmentLink).where(
                    store.ResearchInvestmentLink.research_id
                    == _as_uuid(research_id, "research_id"),
                    store.ResearchInvestmentLink.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if link is None:
            return {
                "research_id": research_id,
                "account_id": None,
                "primary_plan_id": None,
            }
        return {
            "research_id": str(link.research_id),
            "account_id": str(link.account_id) if link.account_id else None,
            "primary_plan_id": str(link.primary_plan_id) if link.primary_plan_id else None,
            "updated_at": _iso(link.updated_at),
        }


# ——— 成交 ————————————————————————————————————————————————————————————


@router.post("/accounts/{account_id}/trades", status_code=201)
async def register_trade(
    account_id: str,
    body: dict[str, Any],
    user: UserModel = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    key = _require_key(idempotency_key)
    async with biz.business_transaction() as session:
        outcome = await biz.register_trade(
            session,
            user_id=user.id,
            account_id=_as_uuid(account_id, "account_id"),
            declared=_body_declared(body, "declared"),
            idempotency_key=key,
            source_kind=str(body.get("source_kind") or "form"),
            source_ref=body.get("source_ref"),
        )
    return {"replayed": outcome.replayed, "operation_id": outcome.operation_id, **outcome.result}


@router.get("/trades")
async def list_trades(
    user: UserModel = Depends(get_current_user),
    account_id: str | None = Query(default=None),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    async with biz.business_transaction() as session:
        stmt = select(store.TradeRecord).where(store.TradeRecord.user_id == user.id)
        if account_id:
            stmt = stmt.where(store.TradeRecord.account_id == _as_uuid(account_id, "account_id"))
        rows = (
            (
                await session.execute(
                    stmt.order_by(store.TradeRecord.created_at.desc()).limit(limit).offset(offset)
                )
            )
            .scalars()
            .all()
        )
    return {"trades": [_trade_view(row) for row in rows]}


@router.post("/trades/{trade_id}/correct", status_code=201)
async def correct_trade(
    trade_id: str,
    body: dict[str, Any],
    user: UserModel = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    key = _require_key(idempotency_key)
    async with biz.business_transaction() as session:
        outcome = await biz.correct_trade(
            session,
            user_id=user.id,
            trade_id=_as_uuid(trade_id, "trade_id"),
            declared=_body_declared(body, "declared"),
            idempotency_key=key,
            source_kind=str(body.get("source_kind") or "form"),
            source_ref=body.get("source_ref"),
        )
    return {"replayed": outcome.replayed, "operation_id": outcome.operation_id, **outcome.result}


# ——— 持久补数请求与逻辑续接（DATA-07） ———————————————————————————————


@router.post("/sessions/{research_id}/input-requests", status_code=201)
async def create_input_request(
    research_id: str,
    body: dict[str, Any],
    user: UserModel = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    key = _require_key(idempotency_key)
    source = body.get("source_run_id")
    source_uuid = _as_uuid(source, "source_run_id") if source else None
    event = body.get("watch_event_id")
    continuation = body.get("continuation")
    if continuation is not None and not isinstance(continuation, dict):
        raise biz.ValidationError("续接信息格式不正确", fields={"continuation": "需要对象"})
    async with biz.business_transaction() as session:
        outcome = await input_requests.create_request(
            session,
            user_id=user.id,
            research_id=_as_uuid(research_id, "research_id"),
            use_case=str(body.get("use_case") or "general_reading"),
            fields=body.get("fields"),
            idempotency_key=key,
            source_run_id=source_uuid,
            watch_event_id=_as_uuid(event, "watch_event_id") if event else None,
            continuation=continuation,
            expires_at=_optional_time(body.get("expires_at"), "expires_at"),
        )
    stop_requested = False
    # Queued sources are already durably abandoned by create_request. Running
    # sources additionally need this process to signal and observe the worker.
    stop_confirmed = True
    if source_uuid is not None and not outcome.replayed:
        async with biz.business_transaction() as session:
            source_row = await session.get(store.Run, source_uuid)
            needs_stop = bool(
                source_row is not None
                and source_row.user_id == user.id
                and source_row.stopped_by == "input_required"
                and source_row.started_at is not None
            )
        if needs_stop:
            orchestrator = get_orchestrator()
            stop_requested = await orchestrator.stop(source_uuid.hex, stopped_by="input_required")
            if stop_requested:
                stop_confirmed = await orchestrator.wait_stopped(
                    source_uuid.hex, timeout=get_config().dispatch_stop_timeout_seconds
                )
            else:
                stop_confirmed = False
    return {
        "replayed": outcome.replayed,
        "operation_id": outcome.operation_id,
        "source_stop_requested": stop_requested,
        "source_stop_confirmed": stop_confirmed,
        **outcome.result,
    }


@router.get("/input-requests")
async def list_input_requests(
    user: UserModel = Depends(get_current_user),
    research_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    if status is not None and status not in {
        input_requests.PENDING,
        input_requests.ANSWERED,
        input_requests.CANCELLED,
        input_requests.EXPIRED,
    }:
        raise biz.ValidationError("补数状态不正确", fields={"status": "不支持该状态"})
    async with biz.business_transaction() as session:
        rows, total = await input_requests.list_requests(
            session,
            user_id=user.id,
            research_id=_as_uuid(research_id, "research_id") if research_id else None,
            status=status,
            limit=limit,
            offset=offset,
        )
        items = [input_requests.request_view(row) for row in rows]
    return {"requests": items, "total": total, "has_more": offset + len(items) < total}


@router.get("/input-requests/{request_id}")
async def get_input_request(
    request_id: str, user: UserModel = Depends(get_current_user)
) -> dict[str, Any]:
    request_uuid = _as_uuid(request_id, "request_id")
    async with biz.business_transaction() as session:
        await input_requests.expire_due(session, user_id=user.id)
        row = (
            await session.execute(
                select(store.InputRequest).where(
                    store.InputRequest.id == request_uuid,
                    store.InputRequest.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise biz.NotFoundOrForbiddenError("补数请求不存在或无权访问")
        answers = (
            (
                await session.execute(
                    select(store.InputRequestAnswer)
                    .where(store.InputRequestAnswer.request_id == row.id)
                    .order_by(store.InputRequestAnswer.revision)
                )
            )
            .scalars()
            .all()
        )
        current_versions = await input_requests.load_current_versions(session, row=row)
        return input_requests.request_view(
            row, answers=list(answers), current_versions=current_versions
        )


@router.post("/input-requests/{request_id}/answers")
async def answer_input_request(
    request_id: str,
    body: dict[str, Any],
    user: UserModel = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    key = _require_key(idempotency_key)
    expected = body.get("expected_versions") or {}
    if not isinstance(expected, dict):
        raise biz.ValidationError("资料版本格式不正确", fields={"expected_versions": "需要对象"})
    # Materialize expiry before the write transaction. An expired answer must
    # return 409 while the request stays durably expired after that transaction rolls back.
    async with biz.business_transaction() as session:
        await input_requests.expire_due(session, user_id=user.id)
    async with biz.business_transaction() as session:
        outcome = await input_requests.answer_request(
            session,
            user_id=user.id,
            request_id=_as_uuid(request_id, "request_id"),
            answer_text=str(body.get("answer") or ""),
            declared=_body_declared(body, "declared"),
            expected_versions=expected,
            idempotency_key=key,
        )
    return {"replayed": outcome.replayed, "operation_id": outcome.operation_id, **outcome.result}


@router.post("/input-requests/{request_id}/cancel")
async def cancel_input_request(
    request_id: str,
    user: UserModel = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    key = _require_key(idempotency_key)
    async with biz.business_transaction() as session:
        await input_requests.expire_due(session, user_id=user.id)
    async with biz.business_transaction() as session:
        outcome = await input_requests.cancel_request(
            session,
            user_id=user.id,
            request_id=_as_uuid(request_id, "request_id"),
            idempotency_key=key,
        )
    return {"replayed": outcome.replayed, "operation_id": outcome.operation_id, **outcome.result}


# ——— B 阶段业务通知（DATA-12 基础） ———————————————————————————————————


@router.get("/events")
async def list_business_events(
    user: UserModel = Depends(get_current_user),
    after: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
) -> dict[str, Any]:
    async with biz.business_transaction() as session:
        rows, cursor = await business_events.list_events(
            session, user_id=user.id, after=after, limit=limit
        )
    return {
        "items": [business_events.event_view(row) for row in rows],
        "cursor": cursor,
        # No retention cleanup exists in the B slice, therefore every historical
        # cursor remains replayable. DATA-12 C will set this when retention lands.
        "cursor_expired": False,
    }


@router.post("/events/{event_id}/read", status_code=204)
async def mark_business_event_read(
    event_id: str, user: UserModel = Depends(get_current_user)
) -> None:
    async with biz.business_transaction() as session:
        found = await business_events.mark_read(
            session, user_id=user.id, event_id=_as_uuid(event_id, "event_id")
        )
    if not found:
        raise biz.NotFoundOrForbiddenError("通知不存在或无权访问")


@router.post("/events/read-all", status_code=204)
async def mark_all_business_events_read(
    body: dict[str, Any], user: UserModel = Depends(get_current_user)
) -> None:
    through = body.get("through")
    if type(through) is not int or through < 0:
        raise biz.ValidationError("通知游标不正确", fields={"through": "需要非负整数"})
    async with biz.business_transaction() as session:
        await business_events.mark_all_read(session, user_id=user.id, through=through)


@router.get("/events/stream")
async def stream_business_events(
    request: Request,
    user: UserModel = Depends(get_current_user),
    after: int = Query(0, ge=0),
) -> StreamingResponse:
    """Replay committed events then wait for more; HTTP remains the recovery source."""
    user_id = user.id

    async def generate() -> AsyncIterator[str]:
        cursor = after
        idle = 0
        while not await request.is_disconnected():
            async with biz.business_transaction() as session:
                rows, cursor = await business_events.list_events(
                    session, user_id=user_id, after=cursor, limit=MAX_LIMIT
                )
            if rows:
                idle = 0
                for row in rows:
                    payload = json.dumps(
                        {
                            "type": "business_event",
                            "ts": datetime.now(UTC).timestamp(),
                            "seq": row.cursor,
                            "event": business_events.event_view(row),
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    yield f"id: {row.cursor}\nevent: business_event\ndata: {payload}\n\n"
            else:
                idle += 1
                if idle >= 15:
                    yield ": heartbeat\n\n"
                    idle = 0
            await asyncio.sleep(1)

    return StreamingResponse(
        generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


# ——— 操作结果（幂等恢复） ——————————————————————————————————————————————


@router.get("/operations/{operation_id}")
async def get_operation(
    operation_id: str, user: UserModel = Depends(get_current_user)
) -> dict[str, Any]:
    async with biz.business_transaction() as session:
        result = await biz.get_operation(
            session, user_id=user.id, operation_id=_as_uuid(operation_id, "operation_id")
        )
    if result is None:
        # 键未知或结果待核定：明确告知，不让客户端据此重发。
        raise biz.NotFoundOrForbiddenError("操作结果不存在或尚未确定")
    return result


@router.get("/operations")
async def list_operations(
    user: UserModel = Depends(get_current_user),
    scope: str | None = Query(default=None),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
) -> dict[str, Any]:
    async with biz.business_transaction() as session:
        rows = await biz.list_recent_operations(session, user_id=user.id, scope=scope, limit=limit)
    return {"operations": rows}
