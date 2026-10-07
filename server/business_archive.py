"""业务对象归档与删除级联（DATA-13 / PR-BIZ-06、PR-WATCH-04）。

软删除 ≠ 擦除：业务事实、快照、审计与事件引用一律保留；归档/删除只改变"能否被新采用/
继续派发"。账户/计划归档停止新采用并暂停引用它们的监控规则；删除研究在**同一事务**内
取消规则、过期待派发事件、取消待补数、作废待派发 outbox、归档该研究所属计划，并软删除
会话。共享账户与成交不随单一研究删除（AC-17）。所有写操作带幂等键 + 归属校验，重试不复活
已取消任务。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from server import business_service as biz
from server import dispatch_outbox, input_requests, store, watch_rules, watch_scheduler


def _now() -> datetime:
    return datetime.now(UTC)


def _append_audit(
    session: AsyncSession, *, user_id: Any, action: str, detail: dict[str, Any]
) -> None:
    session.add(store.AuditLog(user_id=user_id, action=action, detail_json=detail))


async def _pause_rules(session: AsyncSession, *, user_id: Any, predicate: Any) -> list[uuid.UUID]:
    """把满足条件的活动规则置为暂停；返回被暂停的规则 id 列表。"""
    rows = (
        (
            await session.execute(
                select(store.WatchRule).where(
                    store.WatchRule.user_id == user_id,
                    store.WatchRule.status == watch_rules.ACTIVE,
                    predicate,
                )
            )
        )
        .scalars()
        .all()
    )
    paused: list[uuid.UUID] = []
    for rule in rows:
        rule.status = watch_rules.PAUSED
        rule.last_suppressed_reason = "object_archived"
        paused.append(rule.id)
    return paused


async def archive_account(
    session: AsyncSession,
    *,
    user_id: Any,
    account_id: Any,
    idempotency_key: str,
    source_kind: str = "form",
    source_ref: str | None = None,
) -> biz.WriteOutcome:
    payload = {"account_id": str(account_id), "source_kind": source_kind}

    async def _execute() -> dict[str, Any]:
        account = (
            await session.execute(
                select(store.InvestmentAccount)
                .where(
                    store.InvestmentAccount.id == account_id,
                    store.InvestmentAccount.user_id == user_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if account is None:
            raise biz.NotFoundOrForbiddenError("账户不存在或无权访问")
        if account.archived:
            return {
                "account_id": str(account.id),
                "archived": True,
                "already_archived": True,
                "paused_rules": [],
            }
        account.archived = True
        # 暂停通过研究绑定引用该账户的所有活动监控规则（停止新采用）。
        linked_research = select(store.ResearchInvestmentLink.research_id).where(
            store.ResearchInvestmentLink.user_id == user_id,
            store.ResearchInvestmentLink.account_id == account.id,
        )
        paused = await _pause_rules(
            session,
            user_id=user_id,
            predicate=store.WatchRule.research_id.in_(linked_research),
        )
        await session.flush()
        _append_audit(
            session,
            user_id=user_id,
            action="account.archive",
            detail={"account_id": str(account.id), "paused_rules": [str(r) for r in paused]},
        )
        await session.flush()
        return {
            "account_id": str(account.id),
            "archived": True,
            "paused_rules": [str(r) for r in paused],
        }

    return await biz.run_write(
        session,
        user_id=user_id,
        scope="account.archive",
        idempotency_key=idempotency_key,
        payload=payload,
        execute=_execute,
    )


async def archive_plan(
    session: AsyncSession,
    *,
    user_id: Any,
    plan_id: Any,
    idempotency_key: str,
    source_kind: str = "form",
    source_ref: str | None = None,
) -> biz.WriteOutcome:
    payload = {"plan_id": str(plan_id), "source_kind": source_kind}

    async def _execute() -> dict[str, Any]:
        plan = (
            await session.execute(
                select(store.InvestmentPlan)
                .where(store.InvestmentPlan.id == plan_id, store.InvestmentPlan.user_id == user_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if plan is None:
            raise biz.NotFoundOrForbiddenError("计划不存在或无权访问")
        if plan.archived:
            return {
                "plan_id": str(plan.id),
                "archived": True,
                "already_archived": True,
                "paused_rules": [],
            }
        plan.archived = True
        # 暂停直接绑定该计划、或该研究主计划为该计划的监控规则。
        bound = (store.WatchRule.plan_id == plan.id) | (
            (store.WatchRule.research_id == plan.research_id)
            & (
                store.WatchRule.research_id.in_(
                    select(store.ResearchInvestmentLink.research_id).where(
                        store.ResearchInvestmentLink.user_id == user_id,
                        store.ResearchInvestmentLink.primary_plan_id == plan.id,
                    )
                )
            )
        )
        paused = await _pause_rules(session, user_id=user_id, predicate=bound)
        await session.flush()
        _append_audit(
            session,
            user_id=user_id,
            action="plan.archive",
            detail={"plan_id": str(plan.id), "paused_rules": [str(r) for r in paused]},
        )
        await session.flush()
        return {"plan_id": str(plan.id), "archived": True, "paused_rules": [str(r) for r in paused]}

    return await biz.run_write(
        session,
        user_id=user_id,
        scope="plan.archive",
        idempotency_key=idempotency_key,
        payload=payload,
        execute=_execute,
    )


async def delete_research(
    session: AsyncSession,
    *,
    user_id: Any,
    research_id: Any,
    idempotency_key: str,
    source_kind: str = "form",
    source_ref: str | None = None,
) -> biz.WriteOutcome:
    payload = {"research_id": str(research_id), "source_kind": source_kind}

    async def _execute() -> dict[str, Any]:
        research = (
            await session.execute(
                select(store.Session).where(store.Session.id == research_id).with_for_update()
            )
        ).scalar_one_or_none()
        if research is None or research.user_id != user_id:
            raise biz.NotFoundOrForbiddenError("研究不存在或无权访问")
        if research.deleted_at is not None:
            return {"research_id": str(research.id), "deleted": True, "already_deleted": True}

        # 1) 取消该研究所有活动监控规则（终态，调度不再启动）。
        rules = (
            (
                await session.execute(
                    select(store.WatchRule).where(
                        store.WatchRule.user_id == user_id,
                        store.WatchRule.research_id == research.id,
                        store.WatchRule.status != watch_rules.CANCELLED,
                    )
                )
            )
            .scalars()
            .all()
        )
        for rule in rules:
            rule.status = watch_rules.CANCELLED
            rule.last_suppressed_reason = "research_deleted"

        # 2) 过期该研究待派发的监控事件（不补发积压触发）。
        events = (
            (
                await session.execute(
                    select(store.WatchEvent).where(
                        store.WatchEvent.user_id == user_id,
                        store.WatchEvent.research_id == research.id,
                        store.WatchEvent.status == watch_scheduler.PENDING,
                    )
                )
            )
            .scalars()
            .all()
        )
        now = _now()
        for event in events:
            event.status = watch_scheduler.EXPIRED
            event.completed_at = now
            detail = dict(event.detail_json or {})
            detail["expire_reason"] = "research_deleted"
            event.detail_json = detail

        # 3) 取消该研究待补数请求（引用保留，不写死）。
        await session.execute(
            update(store.InputRequest)
            .where(
                store.InputRequest.user_id == user_id,
                store.InputRequest.research_id == research.id,
                store.InputRequest.status == input_requests.PENDING,
            )
            .values(status=input_requests.CANCELLED, cancelled_at=now)
        )

        # 4) 作废待派发 outbox（不再启动新的自动/手动任务；运行中 worker 让其完成）。
        await session.execute(
            update(store.RunDispatch)
            .where(
                store.RunDispatch.user_id == user_id,
                store.RunDispatch.research_id == research.id,
                store.RunDispatch.status.in_(
                    (dispatch_outbox.PENDING, dispatch_outbox.RETRYABLE_FAILED)
                ),
            )
            .values(status=dispatch_outbox.ABANDONED, last_error="research_deleted")
        )

        # 5) 归档该研究所属计划（保留历史、停止新采用）；共享账户不随研究删除（AC-17）。
        plans = (
            (
                await session.execute(
                    select(store.InvestmentPlan).where(
                        store.InvestmentPlan.user_id == user_id,
                        store.InvestmentPlan.research_id == research.id,
                        store.InvestmentPlan.archived.is_(False),
                    )
                )
            )
            .scalars()
            .all()
        )
        for plan in plans:
            plan.archived = True

        # 6) 软删除研究（软删除≠擦除）。
        research.deleted_at = now
        await session.flush()
        _append_audit(
            session,
            user_id=user_id,
            action="research.delete",
            detail={
                "research_id": str(research.id),
                "cancelled_rules": len(rules),
                "expired_events": len(events),
                "archived_plans": len(plans),
            },
        )
        await session.flush()
        return {
            "research_id": str(research.id),
            "deleted": True,
            "cancelled_rules": len(rules),
            "expired_events": len(events),
            "archived_plans": len(plans),
        }

    return await biz.run_write(
        session,
        user_id=user_id,
        scope="research.delete",
        idempotency_key=idempotency_key,
        payload=payload,
        execute=_execute,
    )
