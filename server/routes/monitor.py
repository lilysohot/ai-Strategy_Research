"""Authenticated workbench presence and session-scoped monitoring status."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from server import business_service as biz
from server import monitor_pipeline as pipeline
from server import store, watch_eval, watch_rules
from server.config import get_config
from server.deps import get_current_user
from server.store import User as UserModel

router = APIRouter(prefix="/api/business/monitor", tags=["monitor"])


@router.post("/heartbeat")
async def heartbeat(user: UserModel = Depends(get_current_user)) -> dict[str, Any]:
    async with biz.business_transaction() as session:
        expires = await pipeline.heartbeat(session, user.id)
    return {"expires_at": expires.isoformat(), "heartbeat_seconds": 30}


@router.get("/sessions/{research_id}")
async def session_status(
    research_id: uuid.UUID, user: UserModel = Depends(get_current_user)
) -> dict[str, Any]:
    now = pipeline.utcnow()
    cfg = get_config()
    async with biz.business_transaction() as session:
        owned = await session.scalar(
            select(store.Session.id).where(
                store.Session.id == research_id,
                store.Session.user_id == user.id,
                store.Session.deleted_at.is_(None),
            )
        )
        if not owned:
            raise biz.NotFoundOrForbiddenError("研究不存在或无权访问")
        rows = (
            await session.scalars(
                select(store.WatchRule)
                .where(
                    store.WatchRule.research_id == research_id,
                    store.WatchRule.status != "cancelled",
                )
                .order_by(store.WatchRule.created_at)
            )
        ).all()
        rules = []
        for row in rows:
            rev = await watch_eval._latest_revision(session, row.id, row.current_version)
            view = watch_rules.rule_view(row, rev)
            if rev:
                target = await session.get(store.MonitorTarget, pipeline.target_key(rev))
                view["next_poll_at"] = target.next_poll_at.isoformat() if target else None
                view["source_error"] = target.last_error if target else None
            rules.append(view)
        events, total = await watch_eval.list_events(
            session, user_id=user.id, research_id=research_id, limit=20, offset=0
        )
        event_views = []
        for event in events:
            view = watch_eval.event_view(event)
            receipt = await session.get(store.MonitorMessage, event.id)
            view["delivery_state"] = receipt.state if receipt else None
            view["delivery_result"] = receipt.result if receipt else None
            event_views.append(view)
        workers = (await session.scalars(select(store.MonitorWorker))).all()
        return {
            "rules": rules,
            "events": event_views,
            "event_total": total,
            "session_limit": cfg.monitor_session_limit,
            "online": await pipeline.online(session, user.id, now),
            "enabled": cfg.monitor_enabled and cfg.monitor_streams_enabled,
            "source_verified": cfg.monitor_vendor_time_verified,
            "poll_seconds": cfg.monitor_poll_seconds,
            "workers": [
                {
                    "role": row.role,
                    "healthy": row.heartbeat_at > now - timedelta(seconds=60)
                    and not row.last_error,
                    "last_error": row.last_error,
                    "heartbeat_at": row.heartbeat_at.isoformat(),
                }
                for row in workers
            ],
        }
