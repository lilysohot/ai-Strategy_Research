"""Continuous session rounds and FIFO signals, independent of model execution.

The session lock is the serialization point for rules, rounds and scheduling.
Network acquisition runs outside transactions; a renewable token fences retries.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server import business_service as biz
from server import store, watch_eval, watch_rules
from server.config import get_config
from server.monitor_source import PriceSource


class MonitorLaunchDeferred(RuntimeError):
    """The signal remains queued when online/pause state changes during dispatch."""


async def launch_block_reason(session: AsyncSession, run_id: uuid.UUID) -> str | None:
    from server.monitor_pipeline import online

    event = await session.scalar(
        select(store.WatchEvent).where(
            store.WatchEvent.run_id == run_id, store.WatchEvent.round_id.is_not(None)
        )
    )
    if event is None:
        return None
    if not await live_hits(session, event):
        for hit in event.detail_json.get("targets", []):
            rule = await session.get(store.WatchRule, uuid.UUID(hit["id"]))
            if rule and rule.status == "paused":
                return "monitor_paused"
        return "monitor_cancelled"
    if not await online(session, event.user_id, datetime.now(UTC)):
        return "browser_offline"
    return None


async def stop_cancelled_launch(session: AsyncSession, run_id: uuid.UUID) -> None:
    """Release a queued run after every triggering target was explicitly cancelled."""
    run = await session.get(store.Run, run_id, with_for_update=True)
    if run is None or run.status != "queued":
        return
    run.status, run.stopped_by = "stopped", "monitor_cancelled"
    run.finished_at = datetime.now(UTC)
    event = await session.scalar(select(store.WatchEvent).where(store.WatchEvent.run_id == run_id))
    if event:
        event.status, event.completed_at = "expired", run.finished_at
        event.detail_json = {**event.detail_json, "expire_reason": "rules_cancelled"}
    dispatch = await session.scalar(
        select(store.RunDispatch).where(store.RunDispatch.run_id == run_id)
    )
    if dispatch:
        dispatch.status, dispatch.last_error = "abandoned", "monitor_cancelled"
        dispatch.lease_expires_at, dispatch.lease_owner = None, None


async def defer_launch(run_id: uuid.UUID) -> None:
    async with biz.business_transaction() as session:
        dispatch = await session.scalar(
            select(store.RunDispatch).where(store.RunDispatch.run_id == run_id).with_for_update()
        )
        run = await session.get(store.Run, run_id)
        if dispatch is not None and run is not None and run.status == "queued":
            if await launch_block_reason(session, run_id) == "monitor_cancelled":
                await stop_cancelled_launch(session, run_id)
                return
            dispatch.status = "pending"
            dispatch.lease_expires_at = None
            dispatch.next_attempt_at = datetime.now(UTC) + timedelta(seconds=5)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


async def settings(session: AsyncSession, research_id: uuid.UUID) -> store.MonitorSession:
    """Caller holds the parent session lock, including the absent-row case."""
    row = await session.get(store.MonitorSession, research_id)
    if row is None:
        row = store.MonitorSession(research_id=research_id, sequence=0, auto_manage=False)
        session.add(row)
        await session.flush()
    return row


async def targets(session: AsyncSession, research_id: uuid.UUID) -> list[Any]:
    return list(
        (
            await session.execute(
                select(store.WatchRule, store.WatchRuleRevision)
                .join(
                    store.WatchRuleRevision,
                    (store.WatchRuleRevision.rule_id == store.WatchRule.id)
                    & (store.WatchRuleRevision.version == store.WatchRule.current_version),
                )
                .where(
                    store.WatchRule.research_id == research_id,
                    store.WatchRule.status != "cancelled",
                )
                .order_by(store.WatchRule.created_at, store.WatchRule.id)
            )
        ).all()
    )


async def collect_once(source: PriceSource, *, now: datetime | None = None) -> int:
    from server.monitor_pipeline import online

    now = now or datetime.now(UTC)
    cfg = get_config()
    async with biz.business_transaction() as session:
        ids = list(
            (
                await session.scalars(
                    select(store.Session.id)
                    .join(
                        store.MonitorPresence,
                        store.MonitorPresence.user_id == store.Session.user_id,
                    )
                    .where(
                        store.Session.deleted_at.is_(None),
                        store.MonitorPresence.expires_at > now,
                        store.Session.id.in_(
                            select(store.WatchRule.research_id)
                            .join(
                                store.WatchRuleRevision,
                                (store.WatchRuleRevision.rule_id == store.WatchRule.id)
                                & (
                                    store.WatchRuleRevision.version
                                    == store.WatchRule.current_version
                                ),
                            )
                            .where(
                                store.WatchRule.status == "active",
                                store.WatchRuleRevision.trigger_mode.in_(watch_rules.LONG_RUNNING_MODES),
                            )
                        ),
                    )
                    .order_by(store.Session.id)
                )
            ).all()
        )
    count = 0
    for research_id in ids:
        async with biz.business_transaction() as session:
            research = await session.scalar(
                select(store.Session)
                .where(store.Session.id == research_id)
                .with_for_update(skip_locked=True)
            )
            if research is None or not await online(session, research.user_id, now):
                continue
            state = await settings(session, research_id)
            round_row = await session.scalar(
                select(store.MonitorRound).where(
                    store.MonitorRound.research_id == research_id,
                    store.MonitorRound.state == "collecting",
                )
            )
            if round_row and utc(round_row.lease_until) > now:
                continue
            if not round_row and state.next_poll_at and utc(state.next_poll_at) > now:
                continue
            rows = await targets(session, research_id)
            frozen = [
                watch_rules.rule_view(rule, rev) | {"epoch": rule.lifecycle_epoch}
                for rule, rev in rows
                if rule.status == "active"
                and rev.trigger_mode in watch_rules.LONG_RUNNING_MODES
                and (rev.expires_at is None or utc(rev.expires_at) > now)
            ]
            if not frozen:
                continue
            if round_row is None:
                state.sequence += 1
                round_row = store.MonitorRound(
                    research_id=research_id,
                    user_id=research.user_id,
                    sequence=state.sequence,
                    targets=frozen,
                    results=[],
                    state="collecting",
                    lease_token="",
                    lease_until=now,
                )
                session.add(round_row)
            token = str(uuid.uuid4())
            round_row.lease_token = token
            round_row.lease_until = now + timedelta(seconds=90)
            await session.flush()
            round_id = round_row.id
            frozen = list(round_row.targets)

        async def fetch(target: dict[str, Any]) -> tuple[dict[str, Any], Any, str | None]:
            try:
                obs = await asyncio.wait_for(
                    source.fetch(
                        target["symbol"],
                        target["market"],
                        target["currency"],
                        target["quote_basis"],
                    ),
                    timeout=15,
                )
                return target, obs, None
            except Exception as exc:
                return target, None, type(exc).__name__

        keyed = {(t["symbol"], t["market"], t["currency"], t["quote_basis"]): t for t in frozen}
        acquired = await asyncio.gather(*(fetch(t) for t in keyed.values()))
        by_key = {key: result for key, result in zip(keyed, acquired, strict=True)}
        observations = [
            (t, *by_key[(t["symbol"], t["market"], t["currency"], t["quote_basis"])][1:])
            for t in frozen
        ]
        async with biz.business_transaction() as session:
            await session.scalar(
                select(store.Session).where(store.Session.id == research_id).with_for_update()
            )
            round_row = await session.get(store.MonitorRound, round_id)
            if (
                round_row is None
                or round_row.state != "collecting"
                or round_row.lease_token != token
            ):
                continue
            checked_at = datetime.now(UTC)
            if utc(round_row.lease_until) <= checked_at:
                continue
            state = await settings(session, research_id)
            state.next_poll_at = now + timedelta(seconds=max(15, cfg.monitor_poll_seconds))
            hits, decisions = [], []
            is_online = await online(session, round_row.user_id, checked_at)
            presence = await session.get(store.MonitorPresence, round_row.user_id)
            for target, obs, error in observations:
                rule = await session.get(
                    store.WatchRule, uuid.UUID(target["id"]), with_for_update=True
                )
                reason = error
                if not is_online:
                    reason = "browser_offline"
                elif (
                    rule is None
                    or rule.status != "active"
                    or rule.current_version != target["version"]
                    or rule.lifecycle_epoch != target["epoch"]
                ):
                    reason = "rule_changed"
                elif obs:
                    reason = watch_eval.quote_rejection(obs, now=checked_at)
                    if (obs.thscode, obs.market, obs.currency, obs.quote_basis) != (
                        target["symbol"],
                        target["market"],
                        target["currency"],
                        target["quote_basis"],
                    ):
                        reason = "instrument_mismatch"
                    if presence is None or obs.received_at_ms < int(
                        utc(presence.started_at).timestamp() * 1000
                    ):
                        reason = "prior_online_period"
                    if (
                        rule.last_valid_quote_at
                        and obs.observed_at_ms is not None
                        and obs.observed_at_ms
                        <= int(utc(rule.last_valid_quote_at).timestamp() * 1000)
                    ):
                        reason = "duplicate_or_stale_quote"
                if rule:
                    rule.last_check_at = checked_at
                    rule.last_suppressed_reason = reason
                if reason or obs is None or rule is None or obs.observed_at_ms is None:
                    decisions.append({"id": target["id"], "reason": reason or "no_quote"})
                    continue
                rev = await session.scalar(
                    select(store.WatchRuleRevision).where(
                        store.WatchRuleRevision.rule_id == rule.id,
                        store.WatchRuleRevision.version == target["version"],
                    )
                )
                if rev is None or (
                    rev.expires_at is not None and utc(rev.expires_at) <= checked_at
                ):
                    decisions.append({"id": target["id"], "reason": "rule_expired"})
                    continue
                previous = rule.baseline_price
                prior_period = bool(
                    presence and rule.last_valid_quote_at
                    and utc(rule.last_valid_quote_at) < utc(presence.started_at)
                )
                met = watch_eval.condition_met(
                    obs.price, rev.direction, rev.threshold_low, rev.threshold_high
                )
                trigger_reason = "round_condition_met" if met else "condition_not_met"
                if rev.trigger_mode == "crossing":
                    if previous is None:
                        trigger_reason = "initial_condition_met" if met else "waiting_for_crossing"
                    elif prior_period:
                        met = False
                        trigger_reason = "baseline_reset_after_offline"
                    else:
                        crossing = watch_eval.classify_cross(
                            previous, obs.price, rev.direction, rev.threshold_low, rev.threshold_high
                        )
                        met = crossing is not None
                        trigger_reason = crossing or "waiting_for_crossing"
                rule.baseline_price = obs.price
                rule.last_valid_quote_at = datetime.fromtimestamp(obs.observed_at_ms / 1000, UTC)
                rule.last_valid_quote_price = obs.price
                rule.last_suppressed_reason = None if met else trigger_reason
                hit = target | {
                    "price": str(obs.price),
                    "observed_at_ms": obs.observed_at_ms,
                    "received_at_ms": obs.received_at_ms,
                    "met": met,
                    "trigger_reason": trigger_reason,
                }
                decisions.append(hit)
                if met:
                    rule.last_triggered_at = checked_at
                    hits.append(hit)
            round_row.state = "completed"
            round_row.results = decisions
            if hits:
                primary = hits[0]  # frozen in created_at / ID order, not network completion order
                threshold = primary["threshold"]
                low = threshold["low"] if isinstance(threshold, dict) else threshold
                high = threshold.get("high") if isinstance(threshold, dict) else None
                event = store.WatchEvent(
                    round_id=round_id,
                    queue_sequence=round_row.sequence,
                    rule_id=uuid.UUID(primary["id"]),
                    rule_version=primary["version"],
                    user_id=round_row.user_id,
                    research_id=research_id,
                    symbol=primary["symbol"],
                    market=primary["market"],
                    currency=primary["currency"],
                    quote_basis=primary["quote_basis"],
                    direction=primary["direction"],
                    threshold_low=Decimal(low),
                    threshold_high=Decimal(high) if high else None,
                    price=Decimal(primary["price"]),
                    observed_at_ms=primary["observed_at_ms"],
                    received_at_ms=primary["received_at_ms"],
                    trigger_reason=primary["trigger_reason"],
                    status="pending",
                    detail_json={"long_running": True, "targets": hits, "round_id": str(round_id)},
                )
                session.add(event)
                await session.flush()
                # Durable queue acceptance is atomic with the signal. Redis is a wakeup only.
                session.add(
                    store.MonitorMessage(
                        id=event.id,
                        channel="triggers",
                        payload={"event_id": str(event.id)},
                        state="accepted",
                        available_at=checked_at,
                    )
                )
            count += 1
    return count


async def live_hits(session: AsyncSession, event: store.WatchEvent) -> list[dict[str, Any]]:
    hits = []
    for hit in event.detail_json.get("targets", []):
        rule = await session.get(store.WatchRule, uuid.UUID(hit["id"]))
        if rule and rule.status == "active":
            hits.append(hit)
    return hits


async def schedule(session: AsyncSession, event: store.WatchEvent, now: datetime) -> dict[str, Any]:
    from server import dispatch_outbox
    from server.config import run_dir_for
    from server.monitor_pipeline import online
    from server.run_modes import RunMode, pipeline_for_mode

    research = await session.scalar(
        select(store.Session).where(store.Session.id == event.research_id).with_for_update()
    )
    if research is None or research.deleted_at is not None:
        event.status = "expired"
        event.completed_at = now
        event.detail_json = {**event.detail_json, "expire_reason": "research_deleted"}
        return {"status": "expired", "reason": "research_deleted"}
    if not await online(session, event.user_id, now):
        return {"status": "deferred", "reason": "browser_offline"}
    earlier = await session.scalar(
        select(store.WatchEvent.id)
        .where(
            store.WatchEvent.research_id == event.research_id,
            store.WatchEvent.round_id.is_not(None),
            store.WatchEvent.queue_sequence < event.queue_sequence,
            store.WatchEvent.status == "pending",
        )
        .limit(1)
    )
    if earlier:
        return {"status": "deferred", "reason": "earlier_signal"}
    hits = await live_hits(session, event)
    if not hits:
        rules = [
            await session.get(store.WatchRule, uuid.UUID(h["id"]))
            for h in event.detail_json.get("targets", [])
        ]
        if any(r and r.status == "paused" for r in rules):
            return {"status": "deferred", "reason": "rule_paused"}
        event.status = "expired"
        event.completed_at = now
        event.detail_json = {**event.detail_json, "expire_reason": "rules_cancelled"}
        return {"status": "expired", "reason": "rules_cancelled"}
    if not any(h["action"] == "auto_analyze" for h in hits):
        from server import business_events

        await business_events.add_event(
            session,
            user_id=event.user_id,
            research_id=event.research_id,
            kind="watch_triggered",
            level="medium",
            title="价格监控达标",
            summary=json.dumps(hits, ensure_ascii=False),
            detail={"event_id": str(event.id)},
            dedup_key=f"watch:{event.id}",
        )
        event.status = "completed"
        event.completed_at = now
        return {"status": "completed", "notify_only": True}
    busy = await session.scalar(
        select(store.Run.id)
        .where(
            store.Run.session_id == event.research_id,
            store.Run.status.in_(["queued", "running", "waiting_approval", "needs_input"]),
        )
        .limit(1)
    )
    if busy:
        return {"status": "deferred", "reason": "research_busy"}
    prior = await session.scalar(
        select(func.count())
        .select_from(store.WatchEvent)
        .where(
            store.WatchEvent.research_id == event.research_id,
            store.WatchEvent.round_id.is_not(None),
            store.WatchEvent.run_id.is_not(None),
        )
    )
    from server.monitor_prompt import build_monitor_prompt

    prompt = build_monitor_prompt(
        sequence=event.queue_sequence,
        received_at_ms=event.received_at_ms,
        now=now,
        hits=hits,
        prior_analyses=prior or 0,
    )
    default_llm = await store.get_default_llm_config(user_id=event.user_id)
    snapshot = await store.build_llm_snapshot(user_id=event.user_id)
    run_id = uuid.uuid4()
    store.add_run(
        session,
        run_id=run_id,
        session_id=event.research_id,
        user_id=event.user_id,
        prompt=prompt,
        pipeline_id=pipeline_for_mode(RunMode.SINGLE),
        run_dir=str(run_dir_for(run_id.hex)),
        status="queued",
        llm_config_id=default_llm.id if default_llm else None,
        llm_snapshot_json=snapshot,
    )
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
    event.run_id, event.status = run_id, "dispatching"
    event.scheduled_at = now
    await session.flush()
    return {"status": "dispatching", "run_id": str(run_id)}
