"""Explicitly constructed Redis transport. Importing it starts no consumers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.super_link import models as sl
from server.super_link.service import receive

GROUP = "super-link-receivers-v1"


class Delivery:
    def __init__(
        self,
        redis: Redis,
        sessions: async_sessionmaker[AsyncSession],
        *,
        namespace: str,
        consumer: str | None = None,
        replay_seconds: int = 60,
        reclaim_ms: int = 30_000,
    ) -> None:
        if not namespace.startswith(("super-link:", "test:super-link:")):
            raise ValueError("dedicated_super_link_namespace_required")
        if replay_seconds < 1 or reclaim_ms < 1:
            raise ValueError("positive_retry_intervals_required")
        self.redis = redis
        self.sessions = sessions
        self.stream = f"{namespace}:deliveries-v1"
        self.consumer = consumer or uuid.uuid4().hex
        self.replay_seconds = replay_seconds
        self.reclaim_ms = reclaim_ms

    async def ensure(self) -> None:
        try:
            await self.redis.xgroup_create(self.stream, GROUP, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def relay(self) -> int:
        """Replay pending durable records; duplicates after any crash are harmless."""
        await self.ensure()
        now = datetime.now(UTC)
        async with self.sessions() as session:
            identifiers = list(
                await session.scalars(
                    select(sl.SuperLinkOutbox.message_id)
                    .where(
                        sl.SuperLinkOutbox.state == "pending",
                        or_(
                            sl.SuperLinkOutbox.notified_at.is_(None),
                            sl.SuperLinkOutbox.notified_at
                            <= now - timedelta(seconds=self.replay_seconds),
                        ),
                    )
                    .order_by(sl.SuperLinkOutbox.message_id)
                    .limit(100)
                )
            )
        for mid in identifiers:
            # No DB transaction/row lock spans Redis I/O. A crash before the
            # timestamp commit causes another notification, never a lost message.
            await self.redis.xadd(self.stream, {"id": str(mid)}, maxlen=10_000, approximate=True)
            async with self.sessions.begin() as session:
                await session.execute(
                    update(sl.SuperLinkOutbox)
                    .where(
                        sl.SuperLinkOutbox.message_id == mid,
                        sl.SuperLinkOutbox.state == "pending",
                    )
                    .values(notified_at=now)
                )
        return len(identifiers)

    async def consume(self) -> int:
        """Accept at most 25 notices, ACK only after durable receive commits."""
        await self.ensure()
        recovered = await self.redis.xautoclaim(
            self.stream,
            GROUP,
            self.consumer,
            min_idle_time=self.reclaim_ms,
            start_id="0-0",
            count=25,
        )
        entries = recovered[1]
        if not entries:
            data = await self.redis.xreadgroup(
                GROUP, self.consumer, {self.stream: ">"}, count=25, block=100
            )
            entries = data[0][1] if data else []
        for entry_id, fields in entries:
            identifier = fields.get("id", fields.get(b"id"))
            if isinstance(identifier, bytes):
                identifier = identifier.decode("ascii", errors="replace")
            try:
                mid = uuid.UUID(identifier or "")
            except (ValueError, TypeError, AttributeError):
                mid = None  # Transport text is never treated as an agent task.
            if mid is not None:
                async with self.sessions.begin() as session:
                    await receive(session, mid)
            # DB errors propagate and leave the notice pending for recovery.
            await self.redis.xack(self.stream, GROUP, entry_id)
            await self.redis.xdel(self.stream, entry_id)
        return len(entries)
