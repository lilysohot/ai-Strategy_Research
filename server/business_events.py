"""Durable business notifications with cursor replay and owner isolation (DATA-12)."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from server import store

LEVELS = frozenset({"low", "medium", "high", "urgent"})


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
    level: str = "medium",
    dedup_key: str | None = None,
) -> store.BusinessEvent:
    # 去重：同一对象同一次触发（dedup_key）只保留一条，不重复通知。
    if dedup_key is not None:
        existing = (
            await session.execute(
                select(store.BusinessEvent).where(
                    store.BusinessEvent.user_id == user_id,
                    store.BusinessEvent.dedup_key == dedup_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
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
        level=level,
        dedup_key=dedup_key,
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        # 并发去重：另一执行者已写入同键通知，返回既有行即可。
        existing = (
            await session.execute(
                select(store.BusinessEvent).where(
                    store.BusinessEvent.user_id == user_id,
                    store.BusinessEvent.dedup_key == dedup_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        raise
    return row


def event_view(row: store.BusinessEvent) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "cursor": row.cursor,
        "research_id": str(row.research_id),
        "request_id": str(row.request_id) if row.request_id else None,
        "run_id": row.run_id.hex if row.run_id else None,
        "kind": row.kind,
        "level": row.level,
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


async def list_notifications(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kinds: list[str] | None = None,
    levels: list[str] | None = None,
    read: bool | None = None,
    limit: int,
    offset: int,
) -> tuple[list[store.BusinessEvent], int, int, int]:
    """最近未读优先的通知视图（隐藏项不返回）。

    返回 ``(rows, total, unread_count, read_progress)``。未读是视图排序（不是状态），
    已读是用户明确操作；删除/隐藏不改业务事实。
    """
    filters = [store.BusinessEvent.user_id == user_id, store.BusinessEvent.hidden.is_(False)]
    if kinds:
        filters.append(store.BusinessEvent.kind.in_(kinds))
    if levels:
        filters.append(store.BusinessEvent.level.in_(levels))
    if read is not None:
        filters.append(
            store.BusinessEvent.read_at.is_not(None)
            if read
            else store.BusinessEvent.read_at.is_(None)
        )

    unread_filters = [
        store.BusinessEvent.user_id == user_id,
        store.BusinessEvent.hidden.is_(False),
        store.BusinessEvent.read_at.is_(None),
    ]
    if kinds:
        unread_filters.append(store.BusinessEvent.kind.in_(kinds))
    if levels:
        unread_filters.append(store.BusinessEvent.level.in_(levels))

    total = (
        await session.execute(select(func.count()).select_from(store.BusinessEvent).where(*filters))
    ).scalar_one()
    unread = (
        await session.execute(
            select(func.count()).select_from(store.BusinessEvent).where(*unread_filters)
        )
    ).scalar_one()
    read_progress = (
        await session.execute(
            select(func.coalesce(func.max(store.BusinessEvent.cursor), 0)).where(
                store.BusinessEvent.user_id == user_id,
                store.BusinessEvent.read_at.is_not(None),
            )
        )
    ).scalar_one()
    rows = (
        (
            await session.execute(
                select(store.BusinessEvent)
                .where(*filters)
                .order_by(
                    store.BusinessEvent.read_at.is_(None).desc(),
                    store.BusinessEvent.cursor.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total, unread, read_progress


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


async def hide_event(session: AsyncSession, *, user_id: uuid.UUID, event_id: uuid.UUID) -> bool:
    """隐藏只影响视图，不改变业务事实（触发/分析记录仍保留）。"""
    row = (
        await session.execute(
            select(store.BusinessEvent)
            .where(store.BusinessEvent.id == event_id, store.BusinessEvent.user_id == user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    row.hidden = True
    await session.flush()
    return True


async def get_read_progress(
    session: AsyncSession, *, user_id: uuid.UUID
) -> tuple[int, datetime | None]:
    row = (
        await session.execute(
            select(
                func.coalesce(func.max(store.BusinessEvent.cursor), 0),
                func.max(store.BusinessEvent.read_at),
            ).where(
                store.BusinessEvent.user_id == user_id,
                store.BusinessEvent.read_at.is_not(None),
            )
        )
    ).one()
    return int(row[0]), row[1]


async def get_settings(session: AsyncSession, *, user_id: uuid.UUID) -> dict[str, Any]:
    row = await session.get(store.NotificationSettings, user_id)
    return {
        "muted_kinds": list(row.muted_kinds_json or []) if row else [],
        "muted_levels": list(row.muted_levels_json or []) if row else [],
    }


async def set_settings(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    muted_kinds: list[str],
    muted_levels: list[str],
) -> dict[str, Any]:
    invalid_levels = sorted(set(muted_levels) - LEVELS)
    if invalid_levels:
        raise ValueError(f"invalid notification levels: {invalid_levels}")
    row = await session.get(store.NotificationSettings, user_id, with_for_update=True)
    if row is None:
        row = store.NotificationSettings(
            user_id=user_id,
            muted_kinds_json=sorted(set(muted_kinds)),
            muted_levels_json=sorted(set(muted_levels)),
        )
        session.add(row)
    else:
        row.muted_kinds_json = sorted(set(muted_kinds))
        row.muted_levels_json = sorted(set(muted_levels))
    await session.flush()
    return {"muted_kinds": list(row.muted_kinds_json), "muted_levels": list(row.muted_levels_json)}


async def stream_events(
    user_id: uuid.UUID,
    after: int,
    *,
    poll_seconds: float = 1.0,
    idle_heartbeat: int = 15,
) -> AsyncIterator[str]:
    """SSE 生成器：游标重放已提交事件，之后轮询等待新事件（可取消/长期存活）。

    路由层持有 `request.is_disconnected()` 的退出判定；本生成器可在测试中直接消费
    （``anext`` / ``aclose``），HTTP 传输不阻塞（ASGITransport 会缓冲完整响应）。
    """
    cursor = after
    idle = 0
    while True:
        session = await store.session_scope()
        async with session, session.begin():
            rows, cursor = await list_events(session, user_id=user_id, after=cursor, limit=100)
        if rows:
            idle = 0
            for row in rows:
                payload = json.dumps(
                    {
                        "type": "business_event",
                        "ts": datetime.now(UTC).timestamp(),
                        "seq": row.cursor,
                        "event": event_view(row),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                yield f"id: {row.cursor}\nevent: business_event\ndata: {payload}\n\n"
        else:
            idle += 1
            if idle >= idle_heartbeat:
                yield ": heartbeat\n\n"
                idle = 0
        await asyncio.sleep(poll_seconds)
