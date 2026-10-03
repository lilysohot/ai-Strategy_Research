"""Durable business notifications with cursor replay and owner isolation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from server import store


async def add_event(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    research_id: uuid.UUID,
    kind: str,
    title: str,
    summary: str,
    request_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> store.BusinessEvent:
    # PostgreSQL sequences are allocated at INSERT time, not commit time. Without
    # this per-user transaction lock, event 2 can commit before event 1 and a
    # client that advances to cursor 2 will never see the later commit of 1.
    owner = (
        await session.execute(
            select(store.User.id).where(store.User.id == user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if owner is None:
        raise RuntimeError("business event owner does not exist")
    row = store.BusinessEvent(
        user_id=user_id,
        research_id=research_id,
        request_id=request_id,
        run_id=run_id,
        kind=kind,
        title=title,
        summary=summary,
        detail_json=detail or {},
    )
    session.add(row)
    await session.flush()
    return row


def event_view(row: store.BusinessEvent) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "cursor": row.cursor,
        "research_id": str(row.research_id),
        "request_id": str(row.request_id) if row.request_id else None,
        "run_id": row.run_id.hex if row.run_id else None,
        "kind": row.kind,
        "title": row.title,
        "summary": row.summary,
        "detail": dict(row.detail_json or {}),
        "read": row.read_at is not None,
        "read_at": row.read_at.isoformat() if row.read_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def list_events(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    after: int,
    limit: int,
) -> tuple[list[store.BusinessEvent], int]:
    rows = (
        (
            await session.execute(
                select(store.BusinessEvent)
                .where(store.BusinessEvent.user_id == user_id, store.BusinessEvent.cursor > after)
                .order_by(store.BusinessEvent.cursor)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    cursor = rows[-1].cursor if rows else after
    return list(rows), cursor


async def mark_read(session: AsyncSession, *, user_id: uuid.UUID, event_id: uuid.UUID) -> bool:
    row = (
        await session.execute(
            select(store.BusinessEvent)
            .where(store.BusinessEvent.id == event_id, store.BusinessEvent.user_id == user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
    await session.flush()
    return True


async def mark_all_read(session: AsyncSession, *, user_id: uuid.UUID, through: int) -> None:
    await session.execute(
        update(store.BusinessEvent)
        .where(
            store.BusinessEvent.user_id == user_id,
            store.BusinessEvent.cursor <= through,
            store.BusinessEvent.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
    )
