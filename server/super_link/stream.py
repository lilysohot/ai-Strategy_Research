"""Space snapshot and SSE stream for Super-link (SSE-T03).

The event ledger in :mod:`server.super_link.events` is authoritative. This
module adds two read surfaces on top of it:

* a consistent snapshot read in one short ``REPEATABLE READ`` transaction, and
* an SSE response that catches up from a cursor and then follows committed
  facts until the connection is closed.

Neither surface holds a database transaction for the lifetime of a browser
connection. Redis Pub/Sub and the shared head poll only wake a connection;
every frame is read back from PostgreSQL first.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from server import store
from server.config import get_config
from server.super_link import controls, events, management, observability
from server.super_link import models as sl
from server.super_link import output as sl_output
from server.super_link.contracts import CollaborationError
from server.super_link.coordination import automatic_budget

logger = logging.getLogger(__name__)

SNAPSHOT_SCHEMA_VERSION = 1
FACT_EVENT = "sl.fact"
PREVIEW_EVENT = sl_output.PREVIEW_EVENT
OUTPUT_RESET_EVENT = sl_output.OUTPUT_RESET_EVENT
AUTH_REQUIRED_EVENT = "sl.auth_required"
RESYNC_REQUIRED_EVENT = "sl.resync_required"
UNAVAILABLE_EVENT = "sl.unavailable"
HEARTBEAT_FRAME = ": heartbeat\n\n"
BATCH_LIMIT = 200
MAX_SNAPSHOT_PAGE = 200


# ---------------------------------------------------------------------------
# Snapshot


@asynccontextmanager
async def snapshot_session() -> AsyncIterator[AsyncSession]:
    """Open the short read-only transaction used by one snapshot response.

    PostgreSQL starts in ``REPEATABLE READ`` so the event head and every space
    view in :func:`snapshot_payload` see one commit boundary. SQLite (tests and
    local installs) keeps its normal single-transaction read semantics.
    """

    async with store.get_sessionmaker()() as session, session.begin():
        bind = session.get_bind()
        dialect = getattr(getattr(bind, "dialect", None), "name", "")
        if dialect == "postgresql":
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            )
        yield session


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _page(items: list[dict], total: int, next_after: str | None) -> dict:
    return {"items": items, "total": int(total), "next_after": next_after}


async def _bounded_rows(
    session: AsyncSession,
    query: Select[Any],
    limit: int,
    *,
    cursor: Any | None = None,
) -> tuple[list[Any], int, str | None]:
    """Return ``(rows, total, next_after)`` for a current-state list.

    ``total`` counts the whole list; ``cursor`` only narrows the page so a
    continuation still reports the exact cardinality.
    """

    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    if cursor is not None:
        query = query.where(cursor)
    rows = list(await session.scalars(query.limit(limit + 1)))
    next_after = str(rows[limit - 1].id) if len(rows) > limit else None
    return rows[:limit], int(total), next_after


def _is_sqlite(session: AsyncSession) -> bool:
    return getattr(session.get_bind().dialect, "name", "") == "sqlite"


def _created_at_key(sqlite: bool, model: Any) -> Any:
    """Return a timestamp expression whose ordering is stable on this dialect.

    SQLite's ``CURRENT_TIMESTAMP`` has whole-second precision while SQLAlchemy
    binds Python datetimes with microseconds. Comparing the two lets a row
    order as older than its own cursor, so the page repeats forever.
    Millisecond strings keep both the ``ORDER BY`` and the cursor predicate on
    the same footing; PostgreSQL keeps native microsecond precision.
    """

    if sqlite:
        return func.strftime("%Y-%m-%d %H:%M:%f", model.created_at)
    return model.created_at


def page_order(
    session: AsyncSession, model: Any, *, newest_first: bool
) -> tuple[Any, ...]:
    """Return ``ORDER BY`` expressions matching :func:`page_cursor`."""

    key = _created_at_key(_is_sqlite(session), model)
    if newest_first:
        return (key.desc(), model.id.desc())
    return (key, model.id)


def page_cursor(
    session: AsyncSession, model: Any, anchor: Any, *, newest_first: bool
) -> Any:
    """Return the continuation condition for a ``(created_at, id)`` page."""

    sqlite = _is_sqlite(session)
    current = _created_at_key(sqlite, model)
    previous = _created_at_key(sqlite, anchor)
    if newest_first:
        return (current < previous) | ((current == previous) & (model.id < anchor.id))
    return (current > previous) | ((current == previous) & (model.id > anchor.id))


async def snapshot_payload(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    space_id: uuid.UUID,
    min_cursor: str | None,
    limit: int,
    runs_after: uuid.UUID | None = None,
    deliveries_after: uuid.UUID | None = None,
    pending_after: uuid.UUID | None = None,
    actions_after: uuid.UUID | None = None,
) -> dict:
    """Read one consistent space view on the caller's transaction.

    The caller owns transaction lifetime. Every query below must stay on this
    session; opening a second session would silently break snapshot
    consistency.
    """

    if limit < 1 or limit > MAX_SNAPSHOT_PAGE:
        raise CollaborationError("invalid_limit")

    # Ownership is checked before touching the event head so an unknown space
    # cannot be distinguished from one whose head is missing.
    space = await management.owned_space(session, user_id, space_id)
    head = await session.get(sl.SuperLinkEventHead, space_id)
    if head is None:
        raise CollaborationError("event_head_missing")

    if min_cursor is not None:
        cursor_space, cursor_epoch, cursor_seq = events.parse_cursor(min_cursor)
        if cursor_space != space_id:
            raise CollaborationError("invalid_cursor")
        if cursor_epoch != head.stream_epoch or cursor_seq < head.min_after:
            raise CollaborationError("resync_required")
        if cursor_seq > head.last_seq:
            raise CollaborationError("invalid_cursor")

    used, budget_limit = await automatic_budget(session, space)

    participant_rows = (
        await session.execute(
            select(
                sl.SuperLinkParticipant.id,
                sl.SuperLinkParticipant.session_id,
                sl.SuperLinkParticipant.role,
                store.Session.deleted_at,
            )
            .outerjoin(store.Session, store.Session.id == sl.SuperLinkParticipant.session_id)
            .where(sl.SuperLinkParticipant.space_id == space_id)
            .order_by(sl.SuperLinkParticipant.role, sl.SuperLinkParticipant.id)
        )
    ).all()
    participants = [
        {
            "participant_id": str(pid),
            "session_id": str(session_id),
            "role": role,
            "available": deleted_at is None,
        }
        for pid, session_id, role, deleted_at in participant_rows
    ]

    run_query = (
        select(store.Run)
        .join(
            sl.SuperLinkParticipant,
            sl.SuperLinkParticipant.session_id == store.Run.session_id,
        )
        .where(sl.SuperLinkParticipant.space_id == space_id)
    )
    run_query = run_query.order_by(*page_order(session, store.Run, newest_first=True))
    run_cursor = None
    if runs_after is not None:
        anchor = await session.scalar(
            select(store.Run)
            .join(
                sl.SuperLinkParticipant,
                sl.SuperLinkParticipant.session_id == store.Run.session_id,
            )
            .where(
                store.Run.id == runs_after,
                sl.SuperLinkParticipant.space_id == space_id,
            )
        )
        if anchor is None:
            raise CollaborationError("invalid_cursor")
        run_cursor = page_cursor(session, store.Run, anchor, newest_first=True)
    run_rows, run_total, run_next = await _bounded_rows(
        session, run_query, limit, cursor=run_cursor
    )
    runs = [
        status
        for run in run_rows
        if (status := await management.run_status(session, run.id)) is not None
    ]

    message_query = select(sl.SuperLinkMessage).where(
        sl.SuperLinkMessage.space_id == space_id
    )
    message_query = message_query.order_by(
        *page_order(session, sl.SuperLinkMessage, newest_first=True)
    )
    message_cursor = None
    if deliveries_after is not None:
        anchor = await session.get(sl.SuperLinkMessage, deliveries_after)
        if anchor is None or anchor.space_id != space_id:
            raise CollaborationError("invalid_cursor")
        message_cursor = page_cursor(
            session, sl.SuperLinkMessage, anchor, newest_first=True
        )
    message_rows, message_total, message_next = await _bounded_rows(
        session, message_query, limit, cursor=message_cursor
    )
    deliveries = [
        await management.delivery_status(session, message) for message in message_rows
    ]

    pending_query = (
        select(store.ControlRecord)
        .join(store.Run, store.Run.id == store.ControlRecord.run_id)
        .join(
            sl.SuperLinkParticipant,
            sl.SuperLinkParticipant.session_id == store.Run.session_id,
        )
        .where(
            sl.SuperLinkParticipant.space_id == space_id,
            store.ControlRecord.kind == "approval",
            store.ControlRecord.status == "pending",
            store.Run.status == "running",
        )
        .order_by(*page_order(session, store.ControlRecord, newest_first=False))
    )
    pending_cursor = None
    if pending_after is not None:
        # The anchor may have been approved between pages, so it is resolved
        # against the space's approvals rather than the pending subset.
        anchor = await session.scalar(
            select(store.ControlRecord)
            .join(store.Run, store.Run.id == store.ControlRecord.run_id)
            .join(
                sl.SuperLinkParticipant,
                sl.SuperLinkParticipant.session_id == store.Run.session_id,
            )
            .where(
                store.ControlRecord.id == pending_after,
                store.ControlRecord.kind == "approval",
                sl.SuperLinkParticipant.space_id == space_id,
            )
        )
        if anchor is None:
            raise CollaborationError("invalid_cursor")
        pending_cursor = page_cursor(
            session, store.ControlRecord, anchor, newest_first=False
        )
    pending_rows, pending_total, pending_next = await _bounded_rows(
        session, pending_query, limit, cursor=pending_cursor
    )
    pending = [store.control_to_dict(row) for row in pending_rows]

    action_query = (
        select(sl.SuperLinkRecoveryAction)
        .where(sl.SuperLinkRecoveryAction.space_id == space_id)
        .order_by(
            *page_order(session, sl.SuperLinkRecoveryAction, newest_first=True)
        )
    )
    action_cursor = None
    if actions_after is not None:
        anchor = await session.get(sl.SuperLinkRecoveryAction, actions_after)
        if anchor is None or anchor.space_id != space_id:
            raise CollaborationError("invalid_cursor")
        action_cursor = page_cursor(
            session, sl.SuperLinkRecoveryAction, anchor, newest_first=True
        )
    action_rows, action_total, action_next = await _bounded_rows(
        session, action_query, limit, cursor=action_cursor
    )
    actions = [
        {
            "id": str(row.id),
            "actor_id": str(row.user_id),
            "request": row.request_json,
            "result": row.result_json,
            "created_at": _iso(row.created_at),
        }
        for row in action_rows
    ]

    active = await controls.active_runs(session, space_id)

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "cursor": events.format_cursor(space_id, head.stream_epoch, head.last_seq),
        "as_of": _iso(datetime.now(UTC)),
        "durability_scope": "committed_records",
        "space": {
            "space_id": str(space.id),
            "goal": space.goal,
            "goal_version": space.goal_version,
            "paused": space.paused,
            "control_state": space.control_state,
            "control_version": space.control_version,
            "delivery_cutoff": _iso(space.delivery_cutoff),
            "can_control": not get_config().restore_mode,
            "automatic_budget": {
                "used": used,
                "limit": budget_limit,
                "remaining": max(0, budget_limit - used),
            },
        },
        "participants": participants,
        "runs": _page(runs, run_total, run_next),
        "deliveries": _page(deliveries, message_total, message_next),
        "pending_interventions": _page(pending, pending_total, pending_next),
        "actions": _page(actions, action_total, action_next),
        "active_run_ids": [str(run.id) for run in active],
        "capabilities": {
            "replay": True,
            "live_output": "local_owner_only",
        },
    }


async def read_snapshot(
    *,
    user_id: uuid.UUID,
    space_id: uuid.UUID,
    min_cursor: str | None = None,
    limit: int = 50,
    runs_after: uuid.UUID | None = None,
    deliveries_after: uuid.UUID | None = None,
    pending_after: uuid.UUID | None = None,
    actions_after: uuid.UUID | None = None,
) -> dict:
    async with snapshot_session() as session:
        return await snapshot_payload(
            session,
            user_id=user_id,
            space_id=space_id,
            min_cursor=min_cursor,
            limit=limit,
            runs_after=runs_after,
            deliveries_after=deliveries_after,
            pending_after=pending_after,
            actions_after=actions_after,
        )


# ---------------------------------------------------------------------------
# SSE framing and bounded output


def sse_frame(event: str, data: dict | None = None, *, frame_id: str | None = None) -> str:
    lines: list[str] = []
    if frame_id is not None:
        lines.append(f"id: {frame_id}")
    lines.append(f"event: {event}")
    if data is not None:
        lines.append(
            "data: " + json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        )
    return "\n".join(lines) + "\n\n"


def fact_frame(envelope: dict) -> str:
    return sse_frame(FACT_EVENT, envelope, frame_id=envelope.get("cursor"))


def control_frame(event: str, reason: str) -> str:
    return sse_frame(
        event, {"schema_version": SNAPSHOT_SCHEMA_VERSION, "reason": reason}
    )


def output_reset_frame(space_id: uuid.UUID, run_ids: Sequence[str]) -> str:
    """Tell the client that live preview for these runs has a gap.

    The frame carries no ``id``: previews never advance the durable cursor.
    """

    return sse_frame(
        OUTPUT_RESET_EVENT,
        {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "space_id": str(space_id),
            "run_ids": list(run_ids),
            "reason": "preview_overflow",
        },
    )


class FrameBuffer:
    """Per-connection output buffer with a hard frame and byte ceiling.

    A full buffer is a slow consumer: the producer gives up, the response
    closes, and the client reconnects from its last processed cursor. Facts are
    never silently dropped in normal operation because the client can always
    replay them from PostgreSQL.
    """

    def __init__(self, *, max_frames: int, max_bytes: int) -> None:
        self.max_frames = max_frames
        self.max_bytes = max_bytes
        self._frames: deque[str] = deque()
        self._bytes = 0
        self._closed = False
        self._condition = asyncio.Condition()

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def pending_bytes(self) -> int:
        return self._bytes

    @property
    def pending_frames(self) -> int:
        return len(self._frames)

    async def put(self, frame: str, *, timeout: float) -> bool:
        """Enqueue one frame, waiting for the consumer up to ``timeout``.

        Waiting instead of failing at the first byte over the ceiling is what
        lets a large catch-up batch make progress: the producer pauses, the
        response loop drains a few frames, and the producer resumes. A client
        that never drains still hits the deadline and the connection closes.
        """

        size = len(frame.encode("utf-8"))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        async with self._condition:
            while not self._closed and (
                len(self._frames) >= self.max_frames
                or self._bytes + size > self.max_bytes
            ):
                remaining = deadline - loop.time()
                if remaining <= 0:
                    self._close_locked()
                    return False
                try:
                    await asyncio.wait_for(self._condition.wait(), remaining)
                except TimeoutError:
                    self._close_locked()
                    return False
            if self._closed:
                return False
            self._frames.append(frame)
            self._bytes += size
            self._condition.notify()
            return True

    async def put_preview(self, frame: str) -> bool:
        """Try to enqueue a display-only frame without waiting.

        Preview frames must never delay or displace facts.  They may use at
        most half of the connection buffer; when that quota is exhausted the
        frame is dropped and the caller reports a reset so the client can
        rebuild from the archived trace.
        """

        size = len(frame.encode("utf-8"))
        frame_cap = max(1, self.max_frames // 2)
        byte_cap = max(1024, self.max_bytes // 2)
        async with self._condition:
            if self._closed:
                return False
            if len(self._frames) >= frame_cap or self._bytes + size > byte_cap:
                return False
            self._frames.append(frame)
            self._bytes += size
            self._condition.notify()
            return True

    async def wait_preview_space(self, *, size: int = 0) -> None:
        """Wait until a preview frame of ``size`` bytes fits, or we close.

        A dropped preview needs a reset even when the run has gone quiet. The
        response loop signals this condition whenever ``get`` frees a frame,
        so reset delivery does not depend on new model output arriving.
        """

        frame_cap = max(1, self.max_frames // 2)
        byte_cap = max(1024, self.max_bytes // 2)
        async with self._condition:
            await self._condition.wait_for(
                lambda: self._closed
                or (
                    len(self._frames) < frame_cap
                    and self._bytes + size <= byte_cap
                )
            )

    def _close_locked(self) -> None:
        self._frames.clear()
        self._bytes = 0
        self._closed = True
        self._condition.notify_all()

    async def terminate(self, frame: str | None = None) -> None:
        async with self._condition:
            self._frames.clear()
            self._bytes = 0
            if frame is not None:
                self._frames.append(frame)
                self._bytes = len(frame.encode("utf-8"))
            self._closed = True
            self._condition.notify_all()

    async def get(self) -> str | None:
        async with self._condition:
            await self._condition.wait_for(lambda: self._frames or self._closed)
            if self._frames:
                frame = self._frames.popleft()
                self._bytes -= len(frame.encode("utf-8"))
                self._condition.notify_all()
                return frame
            return None


# ---------------------------------------------------------------------------
# Connection quota


class ConnectionLease:
    def __init__(self, limiter: ConnectionLimiter, user_id: uuid.UUID) -> None:
        self._limiter = limiter
        self.user_id = user_id
        self._released = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        await self._limiter.release(self.user_id)


class ConnectionLimiter:
    """Process-local per-user quota; first release is authoritative."""

    def __init__(self) -> None:
        self._counts: dict[uuid.UUID, int] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, user_id: uuid.UUID) -> ConnectionLease | None:
        async with self._lock:
            limit = get_config().super_link_sse_max_connections
            count = self._counts.get(user_id, 0)
            if count >= limit:
                return None
            self._counts[user_id] = count + 1
            return ConnectionLease(self, user_id)

    async def release(self, user_id: uuid.UUID) -> None:
        async with self._lock:
            count = self._counts.get(user_id, 0) - 1
            if count > 0:
                self._counts[user_id] = count
            else:
                self._counts.pop(user_id, None)

    async def count(self, user_id: uuid.UUID) -> int:
        async with self._lock:
            return self._counts.get(user_id, 0)

    async def reset(self) -> None:
        async with self._lock:
            self._counts.clear()


LIMITER = ConnectionLimiter()


async def acquire_connection(user_id: uuid.UUID) -> ConnectionLease | None:
    return await LIMITER.acquire(user_id)


# ---------------------------------------------------------------------------
# Hint hub: Redis Pub/Sub and one shared head poll per active space


@dataclass(eq=False)
class Subscription:
    space_id: uuid.UUID
    closed: bool = False
    _pending: bool = False
    _condition: asyncio.Condition = field(default_factory=asyncio.Condition)

    async def notify(self) -> None:
        async with self._condition:
            if self.closed:
                return
            # Sticky until the producer consumes it. A notification that lands
            # while a drain is running must still force one more drain, so the
            # wake-up cannot be lost between reading and waiting.
            self._pending = True
            self._condition.notify_all()

    async def consume(self) -> None:
        async with self._condition:
            self._pending = False

    async def close(self) -> None:
        async with self._condition:
            if self.closed:
                return
            self.closed = True
            self._pending = True
            self._condition.notify_all()

    async def wait(self, timeout: float) -> bool:
        async with self._condition:
            try:
                await asyncio.wait_for(
                    self._condition.wait_for(lambda: self._pending or self.closed),
                    timeout=timeout,
                )
                return True
            except TimeoutError:
                return False


class SpaceHintHub:
    """Wake connections when a space head may have advanced.

    Redis messages are the fast path. The shared poll is the correctness floor:
    it queries the event head once per active space, regardless of how many
    connections observe that space. Neither path carries business payloads.
    """

    def __init__(self, *, listen: bool = True, poll: bool = True) -> None:
        self.listen = listen
        self.poll = poll
        self._subs: dict[uuid.UUID, set[Subscription]] = {}
        self._known: dict[uuid.UUID, tuple[uuid.UUID, int]] = {}
        self._lock = asyncio.Lock()
        self._tasks: list[asyncio.Task] = []

    async def subscribe(self, space_id: uuid.UUID) -> Subscription:
        subscription = Subscription(space_id)
        async with self._lock:
            self._subs.setdefault(space_id, set()).add(subscription)
            self._ensure_tasks_locked()
        return subscription

    async def unsubscribe(self, subscription: Subscription) -> None:
        await subscription.close()
        tasks: list[asyncio.Task] = []
        async with self._lock:
            peers = self._subs.get(subscription.space_id)
            if peers is not None:
                peers.discard(subscription)
                if not peers:
                    self._subs.pop(subscription.space_id, None)
                    self._known.pop(subscription.space_id, None)
            if not self._subs and self._tasks:
                tasks = self._tasks
                self._tasks = []
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def mark_synced(
        self, space_id: uuid.UUID, stream_epoch: uuid.UUID, head_seq: int
    ) -> None:
        async with self._lock:
            if space_id in self._subs:
                self._known.setdefault(space_id, (stream_epoch, int(head_seq)))

    async def dispatch(
        self, space_id: uuid.UUID, stream_epoch: uuid.UUID, head_seq: int
    ) -> bool:
        async with self._lock:
            subscribers = list(self._subs.get(space_id, ()))
            if not subscribers:
                # No observer means no reason to remember this head; caching it
                # would grow with every space mentioned on the channel.
                return False
            known = self._known.get(space_id)
            if known is not None and known[0] == stream_epoch and known[1] >= head_seq:
                return False
            self._known[space_id] = (stream_epoch, int(head_seq))
        for subscription in subscribers:
            await subscription.notify()
        return True

    async def poll_once(self) -> int:
        async with self._lock:
            space_ids = list(self._subs)
        if not space_ids:
            return 0
        try:
            async with store.get_sessionmaker()() as session:
                rows = (
                    await session.execute(
                        select(
                            sl.SuperLinkEventHead.space_id,
                            sl.SuperLinkEventHead.stream_epoch,
                            sl.SuperLinkEventHead.last_seq,
                        ).where(sl.SuperLinkEventHead.space_id.in_(space_ids))
                    )
                ).all()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("super-link head poll failed", exc_info=True)
            await self._notify_failure(space_ids)
            return 0
        found = {space_id: (epoch, int(last_seq)) for space_id, epoch, last_seq in rows}
        for space_id in space_ids:
            state = found.get(space_id)
            if state is None:
                await self._notify_failure([space_id])
            else:
                await self.dispatch(space_id, *state)
        return len(space_ids)

    async def _notify_failure(self, space_ids: list[uuid.UUID]) -> None:
        async with self._lock:
            subscribers = [
                subscription
                for space_id in space_ids
                for subscription in self._subs.get(space_id, ())
            ]
        for subscription in subscribers:
            await subscription.notify()

    def _ensure_tasks_locked(self) -> None:
        if any(not task.done() for task in self._tasks):
            return
        self._tasks = []
        if self.listen:
            self._tasks.append(asyncio.create_task(self._listen_loop()))
        if self.poll:
            self._tasks.append(asyncio.create_task(self._poll_loop()))

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("super-link head poll loop failed", exc_info=True)
            await asyncio.sleep(get_config().super_link_sse_poll_seconds)

    async def _listen_loop(self) -> None:
        from redis.asyncio import Redis

        cfg = get_config()
        while True:
            client: Any = None
            pubsub: Any = None
            try:
                client = Redis.from_url(
                    cfg.super_link_redis_url,
                    socket_timeout=5,
                    socket_connect_timeout=5,
                    decode_responses=True,
                )
                pubsub = client.pubsub()
                await pubsub.subscribe(events.event_channel(cfg))
                while True:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=1.0
                    )
                    if not message:
                        continue
                    try:
                        payload = json.loads(message["data"])
                        space_id = uuid.UUID(str(payload["space_id"]))
                        stream_epoch = uuid.UUID(str(payload["stream_epoch"]))
                        head_seq = int(payload["head_seq"])
                    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                        continue
                    await self.dispatch(space_id, stream_epoch, head_seq)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("super-link hint listener failed", exc_info=True)
                await asyncio.sleep(get_config().super_link_sse_poll_seconds)
            finally:
                if pubsub is not None:
                    with contextlib.suppress(Exception):
                        await pubsub.aclose()
                if client is not None:
                    with contextlib.suppress(Exception):
                        await client.aclose()


HUB = SpaceHintHub()


# ---------------------------------------------------------------------------
# SSE producer


class _Expired(Exception):
    pass


class _AuthLost(Exception):
    pass


class _SlowConsumer(Exception):
    pass


async def _still_authorized(user_id: uuid.UUID, space_id: uuid.UUID) -> bool:
    try:
        async with store.get_sessionmaker()() as session:
            await management.owned_space(session, user_id, space_id)
        return True
    except CollaborationError:
        return False
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("super-link stream auth recheck failed", exc_info=True)
        return True


def _wait_timeout(
    *,
    started: float,
    last_sent: float,
    last_auth: float,
) -> float:
    cfg = get_config()
    now = time.monotonic()
    remaining = [
        cfg.super_link_sse_poll_seconds,
        max(0.0, cfg.super_link_sse_heartbeat_seconds - (now - last_sent)),
        max(0.0, cfg.super_link_sse_auth_recheck_seconds - (now - last_auth)),
        max(0.0, cfg.super_link_sse_max_age_seconds - (now - started)),
    ]
    return max(0.05, min(remaining))


async def _produce(
    buffer: FrameBuffer,
    subscription: Subscription,
    *,
    user_id: uuid.UUID,
    space_id: uuid.UUID,
    after: str,
) -> None:
    cfg = get_config()
    cursor = after
    started = time.monotonic()
    last_sent = started
    last_auth = started

    async def guard() -> None:
        nonlocal last_auth
        now = time.monotonic()
        if now - started >= cfg.super_link_sse_max_age_seconds:
            raise _Expired
        if now - last_auth >= cfg.super_link_sse_auth_recheck_seconds:
            if not await _still_authorized(user_id, space_id):
                raise _AuthLost
            last_auth = now

    def put_timeout() -> float:
        remaining = cfg.super_link_sse_max_age_seconds - (time.monotonic() - started)
        return max(0.05, min(cfg.super_link_sse_send_timeout_seconds, remaining))

    async def send(page: events.ReadPage) -> None:
        nonlocal cursor, last_sent
        for envelope in page.events:
            if not await buffer.put(fact_frame(envelope), timeout=put_timeout()):
                raise _SlowConsumer
            last_sent = time.monotonic()
        if page.events:
            cursor = page.next_cursor or cursor

    async def drain() -> events.ReadPage:
        while True:
            await guard()
            page = await events.read_events(
                user_id=user_id, space_id=space_id, after=cursor, limit=BATCH_LIMIT
            )
            await send(page)
            if not page.events:
                return page
            if len(page.events) < BATCH_LIMIT:
                # Close the window between the last page and entering the wait:
                # re-read once after the cursor has advanced.
                await guard()
                check = await events.read_events(
                    user_id=user_id, space_id=space_id, after=cursor, limit=BATCH_LIMIT
                )
                await send(check)
                if not check.events:
                    return check
            # A full page means there may be more; keep going.

    try:
        await subscription.consume()
        page = await drain()
        await HUB.mark_synced(space_id, page.stream_epoch, page.head_seq)

        while True:
            await guard()
            notified = await subscription.wait(
                _wait_timeout(
                    started=started, last_sent=last_sent, last_auth=last_auth
                )
            )
            if subscription.closed:
                return
            if notified:
                await subscription.consume()
                page = await drain()
                await HUB.mark_synced(space_id, page.stream_epoch, page.head_seq)
                continue
            if time.monotonic() - last_sent >= cfg.super_link_sse_heartbeat_seconds:
                if not await buffer.put(HEARTBEAT_FRAME, timeout=put_timeout()):
                    return
                last_sent = time.monotonic()
    except _Expired:
        observability.inc("sse.max_age_closed")
        await buffer.terminate()
    except _AuthLost:
        observability.inc("sse.auth_revoked")
        await buffer.terminate(control_frame(AUTH_REQUIRED_EVENT, "auth_lost"))
    except _SlowConsumer:
        observability.inc("sse.slow_closed")
        await buffer.terminate()
    except CollaborationError as exc:
        code = str(exc)
        if code in {"invalid_cursor", "resync_required"}:
            await buffer.terminate(
                control_frame(RESYNC_REQUIRED_EVENT, "cursor_expired")
            )
        elif code == "not_found":
            observability.inc("sse.auth_revoked")
            await buffer.terminate(control_frame(AUTH_REQUIRED_EVENT, "auth_lost"))
        else:
            await buffer.terminate(
                control_frame(UNAVAILABLE_EVENT, "event_chain_unavailable")
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("super-link stream producer failed", exc_info=True)
        await buffer.terminate(
            control_frame(UNAVAILABLE_EVENT, "event_chain_unavailable")
        )


async def _produce_previews(
    buffer: FrameBuffer,
    subscription: sl_output.OutputSubscription,
    *,
    space_id: uuid.UUID,
    output_epoch: str,
) -> None:
    """Forward process-local run previews without touching the fact cursor.

    Preview frames are best effort.  When one cannot be delivered, the run is
    marked for a reset and later frames for that run are withheld until the
    reset has been sent, so the client never splices a gap.
    """

    sequences: dict[str, int] = {}
    pending_reset: set[str] = set()
    try:
        while True:
            if pending_reset:
                frame = output_reset_frame(space_id, sorted(pending_reset))
                if await buffer.put_preview(frame):
                    observability.inc("preview.resets")
                    pending_reset.clear()
                    continue
                if buffer.closed:
                    return
                # Dropping the reset is not an option: without new model
                # output nothing would ever wake this producer again. Wait for
                # the response loop to drain a frame, then retry immediately.
                await buffer.wait_preview_space(size=len(frame.encode("utf-8")))
                continue

            item = await subscription.next()
            if item is None:
                return
            if isinstance(item, sl_output.OutputReset):
                pending_reset.update(item.run_ids)
                continue
            run_id = item.run_id
            seq = sequences.get(run_id, 0) + 1
            sequences[run_id] = seq
            envelope = {
                "schema_version": SNAPSHOT_SCHEMA_VERSION,
                "space_id": str(space_id),
                "run_id": run_id,
                "output_epoch": output_epoch,
                "output_seq": seq,
                "kind": item.kind.value,
                **item.data,
            }
            if await buffer.put_preview(sse_frame(PREVIEW_EVENT, envelope)):
                observability.inc("preview.frames")
            else:
                observability.inc("preview.dropped")
                pending_reset.add(run_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("super-link preview producer failed", exc_info=True)


async def event_stream(
    *,
    user_id: uuid.UUID,
    space_id: uuid.UUID,
    after: str,
    lease: ConnectionLease,
    session_ids: Sequence[uuid.UUID] = (),
) -> AsyncIterator[str]:
    cfg = get_config()
    buffer = FrameBuffer(
        max_frames=cfg.super_link_sse_buffer_frames,
        max_bytes=cfg.super_link_sse_buffer_bytes,
    )
    subscription = await HUB.subscribe(space_id)
    producer = asyncio.create_task(
        _produce(
            buffer,
            subscription,
            user_id=user_id,
            space_id=space_id,
            after=after,
        )
    )
    preview_subscription: sl_output.OutputSubscription | None = None
    preview_producer: asyncio.Task[None] | None = None
    if session_ids:
        preview_subscription = sl_output.HUB.subscribe(
            session_ids,
            max_frames=cfg.super_link_sse_output_queue_frames,
        )
        preview_producer = asyncio.create_task(
            _produce_previews(
                buffer,
                preview_subscription,
                space_id=space_id,
                output_epoch=str(uuid.uuid4()),
            )
        )
    logger.info(
        "super-link stream opened space=%s user=%s", space_id, user_id
    )
    observability.inc("sse.opened")
    observability.inc("sse.active_total")
    try:
        while True:
            frame = await buffer.get()
            if frame is None:
                break
            yield frame
    finally:
        observability.inc("sse.closed")
        observability.inc("sse.active_total", -1)
        producer.cancel()
        if preview_producer is not None:
            preview_producer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await producer
        if preview_producer is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await preview_producer
        if preview_subscription is not None:
            sl_output.HUB.unsubscribe(preview_subscription)
        await HUB.unsubscribe(subscription)
        await lease.release()
        logger.info(
            "super-link stream closed space=%s user=%s slow=%s",
            space_id,
            user_id,
            buffer.closed and buffer.pending_frames > 0,
        )
