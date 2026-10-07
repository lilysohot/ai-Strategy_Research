"""监控事件的自动分析调度（DATA-11 / PR-WATCH-02/03）。

消费 ``watch_events``（pending）→ 校验规则/研究/有效期/预算 → 按**执行时**最新有效业务版本
冻结快照 → 创建 Run + outbox 派发意图（同一事务）→ 事件状态流转。自动 Run 与手动 Run 共用
``dispatch_outbox`` 的研究级串行与租约恢复；事件→Run 幂等（每事件每代次唯一）。

状态机（契约 §9）：
``pending → dispatching``（已建 Run）→ ``completed/failed``（Run 终态对账写入）
``pending → needs_input``（缺业务字段 → DATA-07 补数请求，事件可回研究回答）
``pending → blocked_budget``（预算达限，保留事件并说明原因）
``pending → merged``（同研究同标的同意图的待派发事件合并到最早一条）
``pending → expired``（规则取消/改版/暂停/过期，或超过最大排队延迟）

监控链不调用 LLM：调度只做数据库与快照工作，模型执行由 worker 侧完成。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server import (
    business_events,
    dispatch_outbox,
    input_requests,
    investment_snapshot,
    store,
    watch_rules,
)
from server import business_service as biz
from server.config import get_config, run_dir_for
from server.store import build_llm_snapshot, get_default_llm_config

logger = logging.getLogger(__name__)

PENDING = "pending"
DISPATCHING = "dispatching"
COMPLETED = "completed"
FAILED = "failed"
EXPIRED = "expired"
MERGED = "merged"
BLOCKED_BUDGET = "blocked_budget"
NEEDS_INPUT = "needs_input"

#: 调度消费的状态。
SCHEDULABLE = frozenset({PENDING})


def _now() -> datetime:
    return datetime.now(UTC)


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


async def _expire(
    session: AsyncSession, event: store.WatchEvent, now: datetime, reason: str
) -> None:
    event.status = EXPIRED
    event.completed_at = now
    detail = dict(event.detail_json or {})
    detail["expire_reason"] = reason
    event.detail_json = detail
    # 状态事件（DATA-12）：规则失效等可追溯、可提示用户；同事件不重复通知。
    await business_events.add_event(
        session,
        user_id=event.user_id,
        research_id=event.research_id,
        kind="watch_rule_inactive",
        level="low",
        title="监控规则未启动自动分析",
        summary=f"原因：{reason}",
        detail={"event_id": str(event.id), "expire_reason": reason},
        dedup_key=f"watch_rule_inactive:{event.id}",
    )


async def _budget_usage(
    session: AsyncSession, *, rule_id: Any, rule_version: int, user_id: Any, now: datetime
) -> store.WatchBudgetUsage:
    row = (
        await session.execute(
            select(store.WatchBudgetUsage)
            .where(
                store.WatchBudgetUsage.rule_id == rule_id,
                store.WatchBudgetUsage.rule_version == rule_version,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is not None:
        return row
    row = store.WatchBudgetUsage(rule_id=rule_id, rule_version=rule_version, user_id=user_id)
    session.add(row)
    await session.flush()
    return row


def _normalize_request_fields(fields: dict[str, str]) -> list[dict[str, str]]:
    """把用途缺字段（可能含 ``|`` 候选项）规范成补数请求的字段清单。"""
    items: list[dict[str, str]] = []
    for name, reason in fields.items():
        first = name.split("|", 1)[0]
        if "." not in first:
            continue
        items.append({"name": first, "reason": reason})
    return items


async def _needs_input(
    session: AsyncSession,
    event: store.WatchEvent,
    now: datetime,
    fields: dict[str, str],
    spec: investment_snapshot.InvestmentInputSpec,
    prompt: str,
) -> None:
    """缺业务字段：转 DATA-07 补数请求（关联事件、无来源 Run），事件置 needs_input。

    无来源 Run 的请求必须携带续接信息（message + investment_input），回答后据此重建分析。
    """
    requested = _normalize_request_fields(fields)
    continuation = {
        "message": prompt,
        "investment_input": {
            "use_case": spec.use_case,
            "account": {"id": str(spec.account.id)} if spec.account else None,
            "plan": {"id": str(spec.plan.id)} if spec.plan else None,
            "idempotency_key": spec.idempotency_key,
        },
    }
    await input_requests.create_request(
        session,
        user_id=event.user_id,
        research_id=event.research_id,
        use_case="plan_analysis",
        fields=requested,
        idempotency_key=f"watch:{event.id}:input:{event.generation}",
        watch_event_id=event.id,
        source_run_id=None,
        continuation=continuation,
    )
    event.status = NEEDS_INPUT
    event.attempted_at = now
    detail = dict(event.detail_json or {})
    detail["missing_fields"] = sorted(fields)
    event.detail_json = detail


async def schedule_event(
    session: AsyncSession, *, event_id: Any, now: datetime | None = None
) -> dict[str, Any]:
    """处理一个待调度事件；返回状态与结果。调用方持有事务（失败整体回滚）。"""
    now = now or _now()
    cfg = get_config()
    event = (
        await session.execute(
            select(store.WatchEvent).where(store.WatchEvent.id == event_id).with_for_update()
        )
    ).scalar_one_or_none()
    if event is None:
        return {"status": "not_found"}
    if event.status != PENDING:
        return {
            "status": event.status,
            "replayed": True,
            "run_id": str(event.run_id) if event.run_id else None,
            "generation": event.generation,
        }

    rule = (
        await session.execute(
            select(store.WatchRule).where(store.WatchRule.id == event.rule_id).with_for_update()
        )
    ).scalar_one_or_none()
    if rule is None:
        await _expire(session, event, now, "rule_missing")
        return {"status": EXPIRED, "reason": "rule_missing"}
    if rule.status != watch_rules.ACTIVE:
        await _expire(session, event, now, "rule_inactive")
        return {"status": EXPIRED, "reason": "rule_inactive"}
    if rule.current_version != event.rule_version:
        # 改版/暂停/取消使旧版未启动的派发失效（契约 §9），不补发积压旧触发。
        await _expire(session, event, now, "rule_obsoleted")
        return {"status": EXPIRED, "reason": "rule_obsoleted"}
    rev = await _latest_revision(session, rule.id, rule.current_version)
    if rev is None:
        await _expire(session, event, now, "rule_missing")
        return {"status": EXPIRED, "reason": "rule_missing"}
    if rev.expires_at is not None and now > rev.expires_at:
        await _expire(session, event, now, "rule_expired")
        return {"status": EXPIRED, "reason": "rule_expired"}
    if event.analysis_expires_at is not None and now > event.analysis_expires_at:
        await _expire(session, event, now, "max_delay")
        return {"status": EXPIRED, "reason": "max_delay"}
    if rev.action != "auto_analyze":
        # 仅要求提醒（notify）：不擅自开启模型分析（契约 §9 / PRD §7.1）。
        # 触发事件本身就是通知事实，置 completed 并标记 notify_only，不建 Run。
        event.status = COMPLETED
        event.completed_at = now
        detail = dict(event.detail_json or {})
        detail["notify_only"] = True
        event.detail_json = detail
        await session.flush()
        return {"status": COMPLETED, "notify_only": True}

    # 预算：每规则版本原子预留并记账；达限保留事件并说明原因。
    usage = await _budget_usage(
        session,
        rule_id=rule.id,
        rule_version=rule.current_version,
        user_id=event.user_id,
        now=now,
    )
    budget = dict(rev.budget_json or {})
    max_runs = budget.get("max_runs")
    if max_runs and usage.runs_created >= max_runs:
        event.status = BLOCKED_BUDGET
        event.budget_reason = "max_runs_exceeded"
        event.attempted_at = now
        await session.flush()
        # 预算达限通知（DATA-12）：保留事件并说明原因，不建 Run；同事件只通知一次。
        await business_events.add_event(
            session,
            user_id=event.user_id,
            research_id=event.research_id,
            kind="watch_budget_blocked",
            level="high",
            title=f"自动分析未启动：预算达限（{event.symbol}）",
            summary=f"该规则版本已达自动分析次数上限（{max_runs}）",
            detail={
                "event_id": str(event.id),
                "rule_id": str(event.rule_id),
                "rule_version": event.rule_version,
                "max_runs": max_runs,
            },
            dedup_key=f"watch_budget:{event.id}",
        )
        return {
            "status": BLOCKED_BUDGET,
            "reason": "max_runs_exceeded",
            "runs_created": usage.runs_created,
            "max_runs": max_runs,
        }

    # 研究绑定：自动分析需要该研究已绑定的账户与当前主计划。
    link = (
        await session.execute(
            select(store.ResearchInvestmentLink).where(
                store.ResearchInvestmentLink.research_id == event.research_id,
                store.ResearchInvestmentLink.user_id == event.user_id,
            )
        )
    ).scalar_one_or_none()
    if link is None or link.account_id is None or link.primary_plan_id is None:
        event.status = FAILED
        event.budget_reason = None
        event.attempted_at = now
        detail = dict(event.detail_json or {})
        detail["failure_reason"] = "research_binding_missing"
        event.detail_json = detail
        await session.flush()
        return {"status": FAILED, "reason": "research_binding_missing"}

    spec = investment_snapshot.InvestmentInputSpec(
        use_case="plan_analysis",
        account=investment_snapshot.ObjectRef(id=link.account_id),
        plan=investment_snapshot.ObjectRef(id=link.primary_plan_id),
        idempotency_key=f"watch:{event.id}:{event.generation}",
    )
    try:
        resolution = await investment_snapshot.resolve_for_run(
            session, user_id=event.user_id, research_id=event.research_id, spec=spec
        )
    except biz.PurposeRequirementError as exc:
        prompt = rev.task or f"监控触发：{event.symbol} {event.trigger_reason}"
        await _needs_input(session, event, now, fields=exc.fields, spec=spec, prompt=prompt)
        await session.flush()
        return {"status": NEEDS_INPUT, "fields": exc.fields}

    # 队列上限：同研究待执行任务达限时本次不建 Run，留 pending 下轮再试。
    depth = await dispatch_outbox.research_queue_depth(session, event.research_id)
    if depth >= cfg.dispatch_research_queue_limit:
        return {"status": "queued_full", "queue_depth": depth}

    prompt = rev.task or f"监控触发：{event.symbol} {event.trigger_reason}"
    run_id = uuid.uuid4()
    default_llm = await get_default_llm_config(user_id=event.user_id)
    llm_snapshot = await build_llm_snapshot(user_id=event.user_id)
    await store.ensure_session_in(
        session, session_id=event.research_id, user_id=event.user_id, title=prompt[:80]
    )
    store.add_run(
        session,
        run_id=run_id,
        session_id=event.research_id,
        user_id=event.user_id,
        prompt=prompt,
        pipeline_id=cfg.pipeline_id,
        run_dir=str(run_dir_for(run_id.hex)),
        status="queued",
        llm_config_id=default_llm.id if default_llm is not None else None,
        llm_snapshot_json=llm_snapshot,
    )
    snap = investment_snapshot.build_snapshot(
        run_id=run_id,
        user_id=event.user_id,
        research_id=event.research_id,
        spec=spec,
        resolution=resolution,
        source="watch_event",
    )
    session.add(snap)
    # 事件触发的自动分析：用户消息即规则的分析指令；派发意图与 Run/快照同一事务。
    await store.append_turn_in(
        session, session_id=event.research_id, role="user", content=prompt, run_id=run_id
    )
    await dispatch_outbox.enqueue(
        session,
        run_id=run_id,
        user_id=event.user_id,
        research_id=event.research_id,
        session_key=str(event.research_id),
        prompt=prompt,
    )
    session.add(store.WatchEventRun(event_id=event.id, generation=event.generation, run_id=run_id))
    event.run_id = run_id
    event.status = DISPATCHING
    event.scheduled_at = now
    event.attempted_at = now
    usage.runs_created += 1
    usage.runs_attempted += 1
    await session.flush()
    # 排队通知（DATA-12）：同一事件同代次只通知一次。
    await business_events.add_event(
        session,
        user_id=event.user_id,
        research_id=event.research_id,
        kind="auto_analysis_queued",
        level="medium",
        title=f"自动分析已排队：{event.symbol}",
        summary=prompt[:120],
        run_id=run_id,
        detail={
            "rule_id": str(event.rule_id),
            "rule_version": event.rule_version,
            "event_id": str(event.id),
            "generation": event.generation,
        },
        dedup_key=f"watch_analysis:{event.id}:{event.generation}",
    )
    return {
        "status": DISPATCHING,
        "run_id": str(run_id),
        "snapshot_id": str(snap.id),
        "generation": event.generation,
    }


async def merge_pending(session: AsyncSession, *, limit: int, now: datetime) -> int:
    """同研究同标的同意图的待派发事件合并到最早一条，其余置 merged（不跨用户/研究）。

    合并键 =（研究, 标的, 规则意图 action）；意图从规则版本读取，事件本身不存 action。
    """
    rows = (
        await session.execute(
            select(store.WatchEvent, store.WatchRuleRevision)
            .join(
                store.WatchRuleRevision,
                (store.WatchRuleRevision.rule_id == store.WatchEvent.rule_id)
                & (store.WatchRuleRevision.version == store.WatchEvent.rule_version),
            )
            .where(store.WatchEvent.status == PENDING)
            .order_by(store.WatchEvent.received_at_ms.asc())
            .limit(limit * 4)
        )
    ).all()
    leads: dict[tuple[Any, str, str], store.WatchEvent] = {}
    merged = 0
    for event, rev in rows:
        key = (event.research_id, event.symbol, rev.action)
        lead = leads.get(key)
        if lead is None:
            leads[key] = event
            continue
        event.status = MERGED
        event.merged_into_id = lead.id
        event.completed_at = now
        detail = dict(event.detail_json or {})
        detail["merged_into"] = str(lead.id)
        event.detail_json = detail
        merged += 1
    if merged:
        await session.flush()
    return merged


async def reconcile_event_runs(session: AsyncSession, *, limit: int, now: datetime) -> int:
    """把已建 Run 的事件按 Run 终态对账：completed / failed（保留旧终态，不覆盖代次）。"""
    rows = (
        await session.execute(
            select(store.WatchEvent, store.Run)
            .join(store.Run, store.WatchEvent.run_id == store.Run.id)
            .where(store.WatchEvent.status == DISPATCHING)
            .limit(limit)
        )
    ).all()
    changed = 0
    for event, run in rows:
        if run.status == "completed":
            event.status = COMPLETED
            event.completed_at = now
            changed += 1
            # 结果通知（DATA-12）：完成/失败共用同一终态去重键，同代次只通知一次。
            await business_events.add_event(
                session,
                user_id=event.user_id,
                research_id=event.research_id,
                kind="watch_analysis_completed",
                level="low",
                title=f"自动分析完成：{event.symbol}",
                summary=f"触发原因：{event.trigger_reason}",
                run_id=run.id,
                detail={
                    "event_id": str(event.id),
                    "rule_id": str(event.rule_id),
                    "rule_version": event.rule_version,
                    "generation": event.generation,
                    "run_id": str(run.id),
                },
                dedup_key=f"watch_analysis:{event.id}:{event.generation}:done",
            )
        elif run.status in ("failed", "stopped"):
            event.status = FAILED
            event.completed_at = now
            detail = dict(event.detail_json or {})
            detail["failure_reason"] = f"run_{run.status}"
            detail["run_status"] = run.status
            event.detail_json = detail
            changed += 1
            # 错误通知（DATA-12）：同一事件同代次的终态只通知一次，不因重试重复。
            await business_events.add_event(
                session,
                user_id=event.user_id,
                research_id=event.research_id,
                kind="watch_analysis_failed",
                level="high",
                title=f"自动分析失败：{event.symbol}",
                summary=f"原因：run_{run.status}",
                run_id=run.id,
                detail={
                    "event_id": str(event.id),
                    "rule_id": str(event.rule_id),
                    "rule_version": event.rule_version,
                    "generation": event.generation,
                    "run_id": str(run.id),
                    "failure_reason": f"run_{run.status}",
                },
                dedup_key=f"watch_analysis:{event.id}:{event.generation}:done",
            )
    if changed:
        await session.flush()
    return changed


async def schedule_cycle(
    session: AsyncSession, *, limit: int, now: datetime | None = None
) -> dict[str, int]:
    """一轮调度：合并 → 处理待派发事件 → 按 Run 终态对账。"""
    now = now or _now()
    merged = await merge_pending(session, limit=limit, now=now)
    counters: dict[str, int] = {"merged": merged}
    events = (
        (
            await session.execute(
                select(store.WatchEvent)
                .where(store.WatchEvent.status == PENDING)
                .order_by(store.WatchEvent.received_at_ms.asc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    for event in events:
        outcome = await schedule_event(session, event_id=event.id, now=now)
        status = outcome.get("status", "unknown")
        counters[status] = counters.get(status, 0) + 1
    reconciled = await reconcile_event_runs(session, limit=limit, now=now)
    counters["reconciled"] = reconciled
    return counters


async def scheduler_loop(*, poll_seconds: float, batch: int) -> None:
    """常驻调度主循环；异常不退出，记录后等待下一轮。"""
    while True:
        try:
            async with biz.business_transaction() as session:
                counters = await schedule_cycle(session, limit=batch)
            if counters:
                logger.debug("watch scheduler cycle: %s", counters)
        except Exception:
            logger.exception("watch scheduler cycle failed")
        await asyncio.sleep(poll_seconds)
