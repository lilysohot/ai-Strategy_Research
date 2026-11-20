"""Durable Super-link event ledger.

Business transactions stage redacted changes, then seal them at the outer transaction
end. Drafts are savepoint-scoped through :func:`savepoint`; listeners only clean up
root transactions and reject unsealed or post-seal business writes. Redis carries a
head hint only: PostgreSQL remains the authoritative event store.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import event as sa_event
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as SyncSession

from server import store
from server.config import get_config
from server.super_link import models as sl
from server.super_link.contracts import CollaborationError

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
CURSOR_PREFIX = "sl1"
PAYLOAD_LIMIT_BYTES = 16 * 1024

VIEWS = frozenset({"space", "participants", "runs", "deliveries", "interventions", "actions"})

EVENT_TYPES = frozenset(
    {
        "sl.space.created",
        "sl.space.control_changed",
        "sl.space.budget_changed",
        "sl.action.recorded",
        "sl.run.changed",
        "sl.dispatch.changed",
        "sl.finalization.changed",
        "sl.delivery.registered",
        "sl.delivery.published",
        "sl.delivery.received",
        "sl.delivery.quarantined",
        "sl.review.changed",
        "sl.admission.changed",
        "sl.feedback.changed",
        "sl.intervention.changed",
        "sl.artifacts.changed",
        "sl.continuity.changed",
        "sl.participant.availability_changed",
    }
)

_STATE_KEY = "super_link_event_state"
_INSTALLED = False


@dataclass(frozen=True, slots=True)
class Change:
    type: str
    space_id: uuid.UUID
    change_key: str
    data: Mapping[str, Any] = field(default_factory=dict)
    invalidate: tuple[str, ...] = ()
    source_kind: str = "space"
    source_id: str | None = None
    participant_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class Notification:
    space_id: uuid.UUID
    stream_epoch: uuid.UUID
    head_seq: int


@dataclass(frozen=True, slots=True)
class ReadPage:
    events: list[dict]
    next_cursor: str | None
    stream_epoch: uuid.UUID
    head_seq: int


@dataclass
class _Scope:
    transaction: Any | None
    parent: _Scope | None
    managed: bool = False
    releasing: bool = False
    drafts: list[Change] = field(default_factory=list)
    by_key: dict[tuple[uuid.UUID, str], Change] = field(default_factory=dict)


@dataclass
class _SessionState:
    scopes: list[_Scope] = field(default_factory=list)
    sealed: bool = False
    transaction_id: uuid.UUID | None = None
    notifications: list[Notification] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Validation


def _normalise(change: Change) -> Change:
    if not isinstance(change.type, str) or change.type not in EVENT_TYPES:
        raise CollaborationError("invalid_event_type")
    key = change.change_key
    if not isinstance(key, str) or not key or len(key) > 200:
        raise CollaborationError("invalid_change_key")
    if change.data is None:
        data: dict[str, Any] = {}
    elif not isinstance(change.data, Mapping):
        raise CollaborationError("invalid_event_payload")
    else:
        data = dict(change.data)
    try:
        encoded = json.dumps(data, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise CollaborationError("invalid_event_payload") from exc
    if len(encoded.encode("utf-8")) > PAYLOAD_LIMIT_BYTES:
        raise CollaborationError("event_payload_too_large")
    invalidate = tuple(change.invalidate)
    unknown = set(invalidate) - VIEWS
    if unknown:
        raise CollaborationError("invalid_event_invalidate")
    if len(change.type) > 64:
        raise CollaborationError("invalid_event_type")
    if len(change.source_kind) > 32:
        raise CollaborationError("invalid_event_source")
    if change.source_id is not None and len(change.source_id) > 64:
        raise CollaborationError("invalid_event_source")
    return Change(
        type=change.type,
        space_id=change.space_id,
        change_key=key,
        data=data,
        invalidate=invalidate,
        source_kind=change.source_kind,
        source_id=change.source_id,
        participant_id=change.participant_id,
        session_id=change.session_id,
        run_id=change.run_id,
    )


def _same_change(left: Change, right: Change) -> bool:
    return (
        left.type == right.type
        and left.source_kind == right.source_kind
        and left.source_id == right.source_id
        and left.participant_id == right.participant_id
        and left.session_id == right.session_id
        and left.run_id == right.run_id
        and dict(left.data) == dict(right.data)
        and tuple(left.invalidate) == tuple(right.invalidate)
    )


def _event_matches(row: sl.SuperLinkEvent, change: Change) -> bool:
    return (
        row.type == change.type
        and row.schema_version == SCHEMA_VERSION
        and row.source_kind == change.source_kind
        and row.source_id == change.source_id
        and row.participant_id == change.participant_id
        and row.session_id == change.session_id
        and row.run_id == change.run_id
        and (row.data_json or {}) == dict(change.data)
        and list(row.invalidate_json or []) == list(change.invalidate)
    )


# ---------------------------------------------------------------------------
# Session scopes and listeners


def _state(session: SyncSession, *, create: bool = False) -> _SessionState | None:
    state = session.info.get(_STATE_KEY)
    if state is None and create:
        state = _SessionState()
        session.info[_STATE_KEY] = state
    return state


def _root_scope(session: SyncSession, state: _SessionState) -> _Scope:
    root = state.scopes[0] if state.scopes else None
    if root is None or root.transaction is not session.get_transaction():
        # A new root transaction invalidates every scope of the previous one.
        state.scopes.clear()
        root = _Scope(transaction=session.get_transaction(), parent=None)
        state.scopes.append(root)
    return root


def _discard_scope(state: _SessionState, scope: _Scope) -> None:
    if scope in state.scopes:
        state.scopes.remove(scope)


def _merge_scope(state: _SessionState, scope: _Scope) -> None:
    if scope in state.scopes:
        state.scopes.remove(scope)
    if not scope.drafts:
        return
    parent = scope.parent
    if parent is None or parent not in state.scopes:
        return
    for change in scope.drafts:
        parent.drafts.append(change)
        parent.by_key.setdefault((change.space_id, change.change_key), change)


def _before_flush(session: SyncSession, flush_context: Any, instances: Any) -> None:
    state = _state(session)
    if state is None or not state.sealed:
        return
    if session.new or session.dirty or session.deleted:
        raise CollaborationError("event_seal_business_writes")


def _before_commit(session: SyncSession) -> None:
    state = _state(session)
    if state is None:
        return
    top = state.scopes[-1] if state.scopes else None
    if top is not None and top.managed and top.releasing:
        return
    if session.get_nested_transaction() is not None:
        return
    if not state.sealed and any(scope.drafts for scope in state.scopes):
        raise CollaborationError("unsealed_event_drafts")
    if state.sealed and (session.new or session.dirty or session.deleted):
        raise CollaborationError("event_seal_business_writes")


def _after_transaction_end(session: SyncSession, transaction: Any) -> None:
    # ``Session._flush`` opens and commits an internal subtransaction; only a
    # true root transaction (no parent) ends the event scope.
    if transaction.parent is not None:
        return
    session.info.pop(_STATE_KEY, None)


def _after_soft_rollback(session: SyncSession, previous_transaction: Any) -> None:
    if previous_transaction.parent is not None:
        return
    session.info.pop(_STATE_KEY, None)


def install_listeners() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    if not sa_event.contains(SyncSession, "before_flush", _before_flush):
        sa_event.listen(SyncSession, "before_flush", _before_flush)
    if not sa_event.contains(SyncSession, "before_commit", _before_commit):
        sa_event.listen(SyncSession, "before_commit", _before_commit)
    if not sa_event.contains(SyncSession, "after_transaction_end", _after_transaction_end):
        sa_event.listen(SyncSession, "after_transaction_end", _after_transaction_end)
    if not sa_event.contains(SyncSession, "after_soft_rollback", _after_soft_rollback):
        sa_event.listen(SyncSession, "after_soft_rollback", _after_soft_rollback)
    _INSTALLED = True


install_listeners()


@asynccontextmanager
async def savepoint(session: AsyncSession) -> AsyncIterator[None]:
    """Managed savepoint whose draft outcome never depends on listener ordering."""

    sync = session.sync_session
    state = _state(sync, create=True)
    assert state is not None
    if state.sealed:
        raise CollaborationError("event_seal_closed")
    if not state.scopes:
        state.scopes.append(_Scope(transaction=sync.get_transaction(), parent=None))
    parent = state.scopes[-1]
    scope = _Scope(transaction=None, parent=parent, managed=True)
    state.scopes.append(scope)
    try:
        async with session.begin_nested():
            # ``begin_nested`` auto-begins a root transaction; adopt it so a
            # later root lookup does not mistake the scope for a stale one.
            parent.transaction = parent.transaction or sync.get_transaction()
            scope.transaction = sync.get_nested_transaction()
            scope.releasing = True
            yield
    except BaseException:
        _discard_scope(state, scope)
        raise
    else:
        scope.releasing = False
        _merge_scope(state, scope)


# ---------------------------------------------------------------------------
# Staging


async def tracking(
    session: AsyncSession,
    *,
    session_id: uuid.UUID | None = None,
    run: store.Run | None = None,
) -> bool:
    if not get_config().super_link_enabled:
        return False
    if run is not None:
        session_id = run.session_id
    if session_id is None:
        return False
    return await _space_for_session(session, session_id) is not None


async def _space_for_session(
    session: AsyncSession, session_id: uuid.UUID
) -> uuid.UUID | None:
    return await session.scalar(
        select(sl.SuperLinkParticipant.space_id).where(
            sl.SuperLinkParticipant.session_id == session_id
        )
    )


async def stage_change(session: AsyncSession, change: Change) -> bool:
    if not get_config().super_link_enabled:
        return False
    item = _normalise(change)
    sync = session.sync_session
    state = _state(sync, create=True)
    assert state is not None
    if state.sealed:
        raise CollaborationError("event_seal_closed")
    nested = sync.get_nested_transaction()
    scope: _Scope
    if nested is not None:
        top = state.scopes[-1] if state.scopes else None
        if top is None or not top.managed or top.transaction is not nested:
            raise CollaborationError("event_unmanaged_savepoint")
        scope = top
    else:
        root = _root_scope(sync, state)
        if root.transaction is None:
            raise CollaborationError("event_stage_requires_transaction")
        scope = root
    previous = scope.by_key.get((item.space_id, item.change_key))
    if previous is not None:
        if not _same_change(previous, item):
            raise CollaborationError("change_key_conflict")
        return True
    scope.by_key[(item.space_id, item.change_key)] = item
    scope.drafts.append(item)
    return True


async def stage_for_space(
    session: AsyncSession,
    space_id: uuid.UUID,
    *,
    type: str,
    change_key: str,
    data: Mapping[str, Any],
    invalidate: tuple[str, ...] = (),
    source_kind: str = "space",
    source_id: str | None = None,
    participant_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
) -> bool:
    return await stage_change(
        session,
        Change(
            type=type,
            space_id=space_id,
            change_key=change_key,
            data=data,
            invalidate=invalidate,
            source_kind=source_kind,
            source_id=source_id,
            participant_id=participant_id,
            session_id=session_id,
            run_id=run_id,
        ),
    )


async def stage_for_session(
    session: AsyncSession,
    session_id: uuid.UUID,
    *,
    type: str,
    change_key: str,
    data: Mapping[str, Any],
    invalidate: tuple[str, ...] = (),
    source_kind: str = "run",
    source_id: str | None = None,
    participant_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
) -> bool:
    if not get_config().super_link_enabled:
        return False
    space_id = await _space_for_session(session, session_id)
    if space_id is None:
        return False
    return await stage_for_space(
        session,
        space_id,
        type=type,
        change_key=change_key,
        data=data,
        invalidate=invalidate,
        source_kind=source_kind,
        source_id=source_id,
        participant_id=participant_id,
        session_id=session_id,
        run_id=run_id,
    )


async def stage_for_run(
    session: AsyncSession,
    run: store.Run,
    *,
    type: str,
    change_key: str,
    data: Mapping[str, Any],
    invalidate: tuple[str, ...] = (),
    source_kind: str = "run",
    source_id: str | None = None,
    participant_id: uuid.UUID | None = None,
) -> bool:
    return await stage_for_session(
        session,
        run.session_id,
        type=type,
        change_key=change_key,
        data=data,
        invalidate=invalidate,
        source_kind=source_kind,
        source_id=source_id or str(run.id),
        participant_id=participant_id,
        run_id=run.id,
    )


# ---------------------------------------------------------------------------
# Sealing


async def seal_changes(session: AsyncSession) -> list[Notification]:
    sync = session.sync_session
    if sync.get_nested_transaction() is not None:
        raise CollaborationError("event_seal_inside_savepoint")
    state = _state(sync)
    if state is None:
        return []
    if state.sealed:
        return list(state.notifications)
    drafts: list[Change] = []
    for scope in state.scopes:
        drafts.extend(scope.drafts)
    if not drafts:
        return []
    await session.flush()

    ordered: list[Change] = []
    seen: dict[tuple[uuid.UUID, str], Change] = {}
    for change in drafts:
        key = (change.space_id, change.change_key)
        previous = seen.get(key)
        if previous is not None:
            if not _same_change(previous, change):
                raise CollaborationError("change_key_conflict")
            continue
        seen[key] = change
        ordered.append(change)

    grouped: dict[uuid.UUID, list[Change]] = {}
    for change in ordered:
        grouped.setdefault(change.space_id, []).append(change)

    heads: dict[uuid.UUID, sl.SuperLinkEventHead] = {}
    for space_id in sorted(grouped, key=str):
        head = await session.get(sl.SuperLinkEventHead, space_id, with_for_update=True)
        if head is None:
            raise CollaborationError("event_head_missing")
        heads[space_id] = head

    transaction_id = state.transaction_id or uuid.uuid4()
    state.transaction_id = transaction_id
    notifications: list[Notification] = []
    for space_id in sorted(grouped, key=str):
        head = heads[space_id]
        batch = grouped[space_id]
        existing_rows = (
            await session.scalars(
                select(sl.SuperLinkEvent).where(
                    sl.SuperLinkEvent.space_id == space_id,
                    sl.SuperLinkEvent.stream_epoch == head.stream_epoch,
                    sl.SuperLinkEvent.change_key.in_([c.change_key for c in batch]),
                )
            )
        ).all()
        existing = {row.change_key: row for row in existing_rows}
        advanced = False
        seq = head.last_seq
        for change in batch:
            previous = existing.get(change.change_key)
            if previous is not None:
                if not _event_matches(previous, change):
                    raise CollaborationError("change_key_conflict")
                continue
            seq += 1
            session.add(
                sl.SuperLinkEvent(
                    space_id=space_id,
                    stream_epoch=head.stream_epoch,
                    seq=seq,
                    event_id=uuid.uuid4(),
                    transaction_id=transaction_id,
                    change_key=change.change_key,
                    type=change.type,
                    schema_version=SCHEMA_VERSION,
                    source_kind=change.source_kind,
                    source_id=change.source_id,
                    participant_id=change.participant_id,
                    session_id=change.session_id,
                    run_id=change.run_id,
                    data_json=dict(change.data),
                    invalidate_json=list(change.invalidate),
                )
            )
            advanced = True
        if advanced:
            head.last_seq = seq
            notifications.append(
                Notification(
                    space_id=space_id,
                    stream_epoch=head.stream_epoch,
                    head_seq=seq,
                )
            )
    await session.flush()
    state.sealed = True
    state.notifications = notifications
    return list(notifications)


# ---------------------------------------------------------------------------
# Cursor and read API


def format_cursor(space_id: uuid.UUID, stream_epoch: uuid.UUID, seq: int) -> str:
    return f"{CURSOR_PREFIX}:{space_id}:{stream_epoch}:{int(seq)}"


def parse_cursor(cursor: str) -> tuple[uuid.UUID, uuid.UUID, int]:
    if not isinstance(cursor, str):
        raise CollaborationError("invalid_cursor")
    parts = cursor.split(":")
    if len(parts) != 4 or parts[0] != CURSOR_PREFIX:
        raise CollaborationError("invalid_cursor")
    try:
        space_id = uuid.UUID(parts[1])
        stream_epoch = uuid.UUID(parts[2])
        seq = int(parts[3])
    except (ValueError, AttributeError) as exc:
        raise CollaborationError("invalid_cursor") from exc
    if seq < 0:
        raise CollaborationError("invalid_cursor")
    return space_id, stream_epoch, seq


def event_envelope(event: sl.SuperLinkEvent) -> dict:
    recorded_at = event.recorded_at.isoformat() if event.recorded_at is not None else None
    return {
        "schema_version": event.schema_version,
        "event_id": str(event.event_id),
        "type": event.type,
        "space_id": str(event.space_id),
        "stream_epoch": str(event.stream_epoch),
        "seq": str(event.seq),
        "cursor": format_cursor(event.space_id, event.stream_epoch, event.seq),
        "transaction_id": str(event.transaction_id),
        "recorded_at": recorded_at,
        "source": {"kind": event.source_kind, "id": event.source_id},
        "participant_id": str(event.participant_id) if event.participant_id else None,
        "session_id": str(event.session_id) if event.session_id else None,
        "run_id": str(event.run_id) if event.run_id else None,
        "data": event.data_json or {},
        "invalidate": list(event.invalidate_json or []),
    }


async def read_events(
    *,
    user_id: uuid.UUID,
    space_id: uuid.UUID,
    after: str | None,
    limit: int = 200,
) -> ReadPage:
    if limit < 1 or limit > 200:
        raise CollaborationError("invalid_limit")
    async with store.get_sessionmaker()() as session:
        owned = await session.scalar(
            select(sl.SuperLinkSpace.id).where(
                sl.SuperLinkSpace.id == space_id,
                sl.SuperLinkSpace.user_id == user_id,
            )
        )
        if owned is None:
            raise CollaborationError("not_found")
        head = await session.get(sl.SuperLinkEventHead, space_id)
        if head is None:
            raise CollaborationError("event_head_missing")
        after_seq = head.min_after
        if after is not None:
            cursor_space, cursor_epoch, cursor_seq = parse_cursor(after)
            if cursor_space != space_id:
                raise CollaborationError("invalid_cursor")
            if cursor_epoch != head.stream_epoch or cursor_seq < head.min_after:
                raise CollaborationError("resync_required")
            if cursor_seq > head.last_seq:
                raise CollaborationError("invalid_cursor")
            after_seq = cursor_seq
        rows = (
            await session.scalars(
                select(sl.SuperLinkEvent)
                .where(
                    sl.SuperLinkEvent.space_id == space_id,
                    sl.SuperLinkEvent.stream_epoch == head.stream_epoch,
                    sl.SuperLinkEvent.seq > after_seq,
                    sl.SuperLinkEvent.seq <= head.last_seq,
                )
                .order_by(sl.SuperLinkEvent.seq)
                .limit(limit)
            )
        ).all()
        events = [event_envelope(row) for row in rows]
        next_cursor = after
        if rows:
            next_cursor = format_cursor(space_id, head.stream_epoch, rows[-1].seq)
        return ReadPage(
            events=events,
            next_cursor=next_cursor,
            stream_epoch=head.stream_epoch,
            head_seq=head.last_seq,
        )


# ---------------------------------------------------------------------------
# Notification publisher


class EventNotifier:
    """Publish committed head hints; the durable watermark lives in PostgreSQL."""

    def __init__(
        self,
        sessions: Any,
        redis: Any,
        *,
        channel: str,
        batch: int = 200,
    ) -> None:
        self.sessions = sessions
        self.redis = redis
        self.channel = channel
        self.batch = batch

    async def publish_once(self) -> int:
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(
                        sl.SuperLinkEvent.space_id,
                        sl.SuperLinkEvent.stream_epoch,
                        func.max(sl.SuperLinkEvent.seq).label("head_seq"),
                    )
                    .where(sl.SuperLinkEvent.notified_at.is_(None))
                    .group_by(sl.SuperLinkEvent.space_id, sl.SuperLinkEvent.stream_epoch)
                    .order_by(sl.SuperLinkEvent.space_id, sl.SuperLinkEvent.stream_epoch)
                    .limit(self.batch)
                )
            ).all()
        if not rows:
            return 0
        published: list[tuple[uuid.UUID, uuid.UUID, int]] = []
        for space_id, stream_epoch, head_seq in rows:
            message = json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "space_id": str(space_id),
                    "stream_epoch": str(stream_epoch),
                    "head_seq": int(head_seq),
                },
                separators=(",", ":"),
            )
            try:
                await self.redis.publish(self.channel, message)
            except Exception:  # Redis is a hint; the DB event remains authoritative.
                logger.warning("super-link event notification failed", exc_info=True)
                return len(published) if published else 0
            published.append((space_id, stream_epoch, int(head_seq)))
        if not published:
            return 0
        async with self.sessions.begin() as session:
            for space_id, stream_epoch, head_seq in published:
                await session.execute(
                    update(sl.SuperLinkEvent)
                    .where(
                        sl.SuperLinkEvent.space_id == space_id,
                        sl.SuperLinkEvent.stream_epoch == stream_epoch,
                        sl.SuperLinkEvent.seq <= head_seq,
                        sl.SuperLinkEvent.notified_at.is_(None),
                    )
                    .values(notified_at=func.now())
                )
        return len(published)

    async def run_forever(self, interval_seconds: float = 1.0) -> None:
        while True:
            try:
                await self.publish_once()
            except Exception:
                logger.warning("super-link event notifier cycle failed", exc_info=True)
            await _sleep(interval_seconds)


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


def event_channel(cfg: Any) -> str:
    return f"{cfg.super_link_event_env}:{cfg.super_link_namespace}:ui-events:v1"


def notifier_should_start(*, ready: bool) -> bool:
    cfg = get_config()
    return bool(ready and cfg.super_link_enabled and not cfg.restore_mode)
