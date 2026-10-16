"""Durable HTTP → quotes → decisions → triggers → scheduler pipeline.

Network I/O never holds a rule lock. Streams carry only durable message IDs;
consumers read authoritative payloads from PostgreSQL. A commit before XACK is
safe, and losing Redis is repaired by replaying unfinished outbox rows.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from server import business_service as biz
from server import store, watch_eval, watch_scheduler
from server.config import get_config
from server.monitor_source import PriceSource

GROUP = "workers-v1"


def utcnow() -> datetime:
    return datetime.now(UTC)


async def online(session: Any, user_id: uuid.UUID, now: datetime) -> bool:
    return bool(
        await session.scalar(
            select(store.MonitorPresence.user_id).where(
                store.MonitorPresence.user_id == user_id,
                store.MonitorPresence.expires_at > now,
            )
        )
    )


async def heartbeat(session: Any, user_id: uuid.UUID, *, now: datetime | None = None) -> datetime:
    now = now or utcnow()
    # Lock the owner, not an absent presence row; multiple first tabs are safe.
    await session.execute(select(store.User.id).where(store.User.id == user_id).with_for_update())
    row = await session.get(store.MonitorPresence, user_id)
    expires = now + timedelta(seconds=get_config().monitor_presence_seconds)
    if row is None:
        session.add(store.MonitorPresence(user_id=user_id, expires_at=expires, started_at=now))
    else:
        if row.expires_at <= now:
            row.started_at = now
            rules = (
                await session.scalars(
                    select(store.WatchRule)
                    .where(
                        store.WatchRule.user_id == user_id,
                        store.WatchRule.status == "active",
                    )
                    .with_for_update()
                )
            ).all()
            for rule in rules:
                rule.last_suppressed_reason = "browser_reconnected"
                await request_check(session, rule)
        row.expires_at = expires
    return expires


def target_key(rev: store.WatchRuleRevision) -> str:
    # One deployment service credential/permission scope, no user secrets in keys.
    return f"fuyao:service:{rev.market}:{rev.symbol}:{rev.currency}:{rev.quote_basis}"


async def request_check(session: Any, rule: store.WatchRule) -> None:
    """Bring an existing target forward after a user changes a configuration."""
    rev = await watch_eval._latest_revision(session, rule.id, rule.current_version)
    if rev is None:
        return
    target = await session.scalar(
        select(store.MonitorTarget)
        .where(
            store.MonitorTarget.key == target_key(rev),
        )
        .with_for_update(skip_locked=True)
    )
    if target is not None:
        target.next_poll_at = utcnow()


async def collect_once(source: PriceSource, *, now: datetime | None = None) -> int:
    cfg = get_config()
    now = now or utcnow()
    async with biz.business_transaction() as session:
        backlog = await session.scalar(
            select(func.count())
            .select_from(store.MonitorMessage)
            .where(
                store.MonitorMessage.state.in_(["pending", "accepted"]),
            )
        )
        if backlog >= cfg.monitor_queue_limit:
            raise RuntimeError("monitor_backpressure")
        rows = (
            await session.execute(
                select(store.WatchRule, store.WatchRuleRevision)
                .join(
                    store.WatchRuleRevision,
                    (store.WatchRuleRevision.rule_id == store.WatchRule.id)
                    & (store.WatchRuleRevision.version == store.WatchRule.current_version),
                )
                .join(
                    store.MonitorPresence, store.MonitorPresence.user_id == store.WatchRule.user_id
                )
                .where(
                    store.WatchRule.status == "active",
                    store.MonitorPresence.expires_at > now,
                    or_(
                        store.WatchRuleRevision.expires_at.is_(None),
                        store.WatchRuleRevision.expires_at > now,
                    ),
                )
                .order_by(store.WatchRule.last_check_at.asc().nullsfirst(), store.WatchRule.id)
                .limit(cfg.monitor_batch_rules)
            )
        ).all()
        targets: dict[str, list[Any]] = {}
        for rule, rev in rows:
            targets.setdefault(target_key(rev), []).append((rule, rev))
        claimed = []
        for key, items in targets.items():
            await session.execute(
                insert(store.MonitorTarget)
                .values(key=key, next_poll_at=now)
                .on_conflict_do_nothing(index_elements=["key"])
            )
            target = await session.scalar(
                select(store.MonitorTarget)
                .where(
                    store.MonitorTarget.key == key,
                    store.MonitorTarget.next_poll_at <= now,
                    or_(
                        store.MonitorTarget.lease_until.is_(None),
                        store.MonitorTarget.lease_until < now,
                    ),
                )
                .with_for_update(skip_locked=True)
            )
            if target is None:
                continue
            token = str(uuid.uuid4())
            target.lease_token = token
            target.lease_until = now + timedelta(seconds=60)
            rev = items[0][1]
            claimed.append(
                (
                    key,
                    token,
                    (rev.symbol, rev.market, rev.currency, rev.quote_basis),
                    [
                        {
                            "id": str(rule.id),
                            "version": rule.current_version,
                            "epoch": rule.lifecycle_epoch,
                        }
                        for rule, _ in items
                    ],
                )
            )
            if len(claimed) >= cfg.monitor_max_symbols:
                break

    async def acquire(item: Any) -> bool:
        key, token, args, rules = item
        quote = None
        error = None
        try:
            quote = await asyncio.wait_for(source.fetch(*args), timeout=15)
        except Exception as exc:
            # Never persist credential-bearing HTTP exception URLs/headers.
            error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            error = error[:180]
        async with biz.business_transaction() as session:
            target = await session.scalar(
                select(store.MonitorTarget)
                .where(
                    store.MonitorTarget.key == key,
                    store.MonitorTarget.lease_token == token,
                    store.MonitorTarget.lease_until > utcnow(),
                )
                .with_for_update()
            )
            if target is None:
                return False  # Fenced: a late response cannot overwrite another owner.
            target.lease_token = None
            target.lease_until = None
            target.last_poll_at = now
            target.last_error = error
            refresh_requested = target.next_poll_at > now
            target.next_poll_at = (
                utcnow()
                if refresh_requested
                else now + timedelta(seconds=max(15, cfg.monitor_poll_seconds))
            )
            for frozen in rules:
                rule = await session.get(store.WatchRule, uuid.UUID(frozen["id"]))
                if rule and (
                    rule.current_version != frozen["version"]
                    or rule.lifecycle_epoch != frozen.get("epoch", 0)
                ):
                    target.next_poll_at = utcnow()
                if rule and rule.current_version == frozen["version"]:
                    rule.last_check_at = now
                    if error:
                        rule.last_suppressed_reason = error
            if quote is not None:
                payload = asdict(quote)
                payload["price"] = str(quote.price)
                session.add(
                    store.MonitorMessage(
                        channel="quotes",
                        payload={"quote": payload, "rules": rules},
                        state="pending",
                        available_at=now,
                    )
                )
        return quote is not None

    # Bounded HTTP requests; none share the Run worker pool.
    gate = asyncio.Semaphore(4)

    async def bounded(item: Any) -> bool:
        async with gate:
            return await acquire(item)

    return sum(await asyncio.gather(*(bounded(item) for item in claimed)))


class Delivery:
    def __init__(self, redis: Redis, *, consumer: str | None = None) -> None:
        self.redis = redis
        self.consumer = consumer or str(uuid.uuid4())

    def stream(self, channel: str) -> str:
        return f"{get_config().monitor_stream_prefix}:{channel}"

    async def ensure(self, channel: str) -> None:
        try:
            await self.redis.xgroup_create(self.stream(channel), GROUP, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def relay(self, channel: str) -> int:
        cfg = get_config()
        now = utcnow()
        await self.ensure(channel)
        async with biz.business_transaction() as session:
            messages = (
                await session.scalars(
                    select(store.MonitorMessage)
                    .where(
                        store.MonitorMessage.channel == channel,
                        store.MonitorMessage.state == "pending",
                        store.MonitorMessage.available_at <= now,
                        or_(
                            store.MonitorMessage.published_at.is_(None),
                            store.MonitorMessage.published_at
                            < now - timedelta(seconds=cfg.monitor_replay_seconds),
                        ),
                    )
                    .order_by(store.MonitorMessage.available_at)
                    .limit(100)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for message in messages:
                # Commit failure after XADD produces a duplicate, never a lost event.
                await self.redis.xadd(
                    self.stream(channel),
                    {"id": str(message.id)},
                    maxlen=cfg.monitor_queue_limit,
                    approximate=False,
                )
                message.published_at = now
            return len(messages)

    async def consume(self, channel: str) -> int:
        await self.ensure(channel)
        stream = self.stream(channel)
        recovered = await self.redis.xautoclaim(
            stream, GROUP, self.consumer, min_idle_time=30_000, start_id="0-0", count=25
        )
        entries = recovered[1]
        if not entries:
            data = await self.redis.xreadgroup(
                GROUP, self.consumer, {stream: ">"}, count=25, block=100
            )
            entries = data[0][1] if data else []
        for entry_id, fields in entries:
            identifier = fields.get("id")
            try:
                mid = uuid.UUID(identifier or "")
            except (ValueError, TypeError):
                # Only durable IDs are accepted. Untrusted transport payloads cannot run tasks.
                await self.redis.xack(stream, GROUP, entry_id)
                await self.redis.xdel(stream, entry_id)
                continue
            try:
                await process_message(mid, channel=channel)
            except Exception as exc:
                await record_failure(mid, type(exc).__name__)
            # Failures are retried by the durable outbox, bounded and visible in PG.
            await self.redis.xack(stream, GROUP, entry_id)
            await self.redis.xdel(stream, entry_id)
        return len(entries)


async def process_message(mid: uuid.UUID, *, channel: str) -> None:
    now = utcnow()
    async with biz.business_transaction() as session:
        message = await session.scalar(
            select(store.MonitorMessage).where(store.MonitorMessage.id == mid).with_for_update()
        )
        if (
            message is None
            or message.channel != channel
            or message.state != "pending"
            or message.available_at > now
        ):
            return
        if channel == "triggers":
            # Receipt is durable before ACK. Scheduling and Run execution happen later.
            message.state = "accepted"
            message.result = {"accepted_at": now.isoformat()}
            return
        raw = dict(message.payload["quote"])
        raw["price"] = Decimal(raw["price"])
        observation = watch_eval.MonitoringObservation(**raw)
        results = []
        for frozen in sorted(message.payload["rules"], key=lambda row: row["id"]):
            rule = await session.scalar(
                select(store.WatchRule)
                .where(store.WatchRule.id == uuid.UUID(frozen["id"]))
                .with_for_update()
            )
            if (
                rule is None
                or rule.current_version != frozen["version"]
                or rule.lifecycle_epoch != frozen.get("epoch", 0)
            ):
                results.append({"id": frozen["id"], "status": "obsolete"})
                continue
            if not await online(session, rule.user_id, now):
                rule.last_suppressed_reason = "browser_offline"
                results.append({"id": frozen["id"], "status": "offline"})
                continue
            presence = await session.get(store.MonitorPresence, rule.user_id)
            if observation.received_at_ms < int(presence.started_at.timestamp() * 1000):
                results.append({"id": frozen["id"], "status": "prior_online_period"})
                continue
            if rule.last_valid_quote_at and rule.last_valid_quote_at < presence.started_at:
                rule.last_suppressed_reason = "browser_reconnected"
            result = await watch_eval.evaluate(
                session,
                rule_id=rule.id,
                obs=observation,
                now=now,
                max_gap=timedelta(seconds=get_config().monitor_max_gap_seconds),
            )
            results.append({"id": frozen["id"], **result})
            if result.get("event_id"):
                eid = uuid.UUID(result["event_id"])
                session.add(
                    store.MonitorMessage(
                        id=eid,
                        channel="triggers",
                        payload={"event_id": str(eid)},
                        state="pending",
                        available_at=now,
                    )
                )
        message.state = "completed"
        message.completed_at = now
        message.result = {"decisions": results}


async def record_failure(mid: uuid.UUID, error: str) -> None:
    async with biz.business_transaction() as session:
        row = await session.scalar(
            select(store.MonitorMessage).where(store.MonitorMessage.id == mid).with_for_update()
        )
        if row is None or row.state != "pending":
            return
        row.attempts += 1
        row.result = {"error": error}
        row.available_at = utcnow() + timedelta(seconds=min(300, 2**row.attempts))
        row.published_at = None
        if row.attempts >= get_config().monitor_max_attempts:
            row.state = "quarantined"
            row.completed_at = utcnow()
            for frozen in row.payload.get("rules", []):
                rule = await session.get(store.WatchRule, uuid.UUID(frozen["id"]))
                if rule and rule.current_version == frozen["version"]:
                    rule.last_suppressed_reason = "consumer_quarantined"


async def retry_quarantined(mid: uuid.UUID) -> bool:
    """Operator retry keeps the original identity and all scheduling validity gates."""
    async with biz.business_transaction() as session:
        row = await session.scalar(
            select(store.MonitorMessage)
            .where(
                store.MonitorMessage.id == mid,
                store.MonitorMessage.state == "quarantined",
            )
            .with_for_update()
        )
        if row is None:
            return False
        row.state = "pending"
        row.attempts = 0
        row.available_at = utcnow()
        row.published_at = None
        row.completed_at = None
        row.result = {"operator_retry_at": utcnow().isoformat(), "previous_result": row.result}
        return True


async def schedule_received() -> int:
    now = utcnow()
    async with biz.business_transaction() as session:
        ids = (
            await session.scalars(
                select(store.MonitorMessage.id)
                .where(
                    store.MonitorMessage.channel == "triggers",
                    store.MonitorMessage.state == "accepted",
                    store.MonitorMessage.available_at <= now,
                )
                .order_by(store.MonitorMessage.available_at)
                .limit(get_config().auto_batch_events)
            )
        ).all()
    for mid in ids:
        # One event failure must not roll back or starve the other sessions.
        try:
            async with biz.business_transaction() as session:
                row = await session.scalar(
                    select(store.MonitorMessage)
                    .where(
                        store.MonitorMessage.id == mid,
                        store.MonitorMessage.state == "accepted",
                    )
                    .with_for_update(skip_locked=True)
                )
                if row is None:
                    continue
                result = await watch_scheduler.schedule_event(session, event_id=mid, now=now)
                row.result = result
                if result["status"] in {"deferred", "pending", "queued_full"}:
                    row.available_at = now + timedelta(seconds=5)
                else:
                    row.state = "completed"
                    row.completed_at = now
        except Exception as exc:
            async with biz.business_transaction() as session:
                row = await session.scalar(
                    select(store.MonitorMessage)
                    .where(store.MonitorMessage.id == mid)
                    .with_for_update()
                )
                if row and row.state == "accepted":
                    row.attempts += 1
                    row.result = {"error": type(exc).__name__}
                    row.available_at = now + timedelta(seconds=min(300, 2**row.attempts))
                    if row.attempts >= get_config().monitor_max_attempts:
                        row.state = "quarantined"
                        row.completed_at = now
    async with biz.business_transaction() as session:
        await watch_scheduler.reconcile_event_runs(session, limit=100, now=now)
    return len(ids)


async def worker_health(role: str, error: str | None = None) -> None:
    async with biz.business_transaction() as session:
        await session.execute(
            insert(store.MonitorWorker)
            .values(role=role, heartbeat_at=utcnow(), last_error=error)
            .on_conflict_do_update(
                index_elements=["role"], set_={"heartbeat_at": utcnow(), "last_error": error}
            )
        )


async def prune() -> None:
    # Only terminal delivery payloads expire. Trigger/Run/business audit stays durable.
    async with biz.business_transaction() as session:
        ids = (
            select(store.MonitorMessage.id)
            .where(
                store.MonitorMessage.state == "completed",
                store.MonitorMessage.completed_at
                < utcnow() - timedelta(days=get_config().monitor_retention_days),
            )
            .limit(500)
        )
        await session.execute(delete(store.MonitorMessage).where(store.MonitorMessage.id.in_(ids)))
