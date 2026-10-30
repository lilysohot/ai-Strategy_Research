"""Authenticated workbench presence and session-scoped monitoring status."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, StrictBool
from sqlalchemy import func, select

from server import business_service as biz
from server import monitor_pipeline as pipeline
from server import store, watch_eval, watch_rules
from server.config import get_config
from server.deps import get_current_user
from server.store import User as UserModel

router = APIRouter(prefix="/api/business/monitor", tags=["monitor"])


class MonitorSettings(BaseModel):
    auto_manage: StrictBool


@router.put("/sessions/{research_id}/settings")
async def update_settings(
    research_id: uuid.UUID, body: MonitorSettings, user: UserModel = Depends(get_current_user)
) -> dict[str, Any]:
    from server.monitor_longterm import settings

    async with biz.business_transaction() as session:
        await watch_rules._ensure_research(session, user_id=user.id, research_id=research_id)
        state = await settings(session, research_id)
        state.auto_manage = body.auto_manage
        session.add(
            store.AuditLog(
                user_id=user.id,
                action="monitor.auto_manage",
                detail_json={"research_id": str(research_id), "enabled": body.auto_manage},
            )
        )
    return {"auto_manage": body.auto_manage}


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
                if rev.trigger_mode in {"continuous", "crossing"}:
                    state = await session.get(store.MonitorSession, research_id)
                    view["next_poll_at"] = (
                        state.next_poll_at.isoformat() if state and state.next_poll_at else None
                    )
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
        state = await session.get(store.MonitorSession, research_id)
        queued, oldest = (
            await session.execute(
                select(func.count(), func.min(store.WatchEvent.received_at_ms))
                .select_from(store.WatchEvent)
                .outerjoin(store.Run, store.Run.id == store.WatchEvent.run_id)
                .where(
                    store.WatchEvent.research_id == research_id,
                    store.WatchEvent.round_id.is_not(None),
                    (store.WatchEvent.status == "pending")
                    | ((store.WatchEvent.status == "dispatching") & (store.Run.status == "queued")),
                )
            )
        ).one()
        return {
            "auto_manage": state.auto_manage if state else False,
            "queued_signals": queued,
            "oldest_queued_at_ms": oldest,
            "rules": rules,
            "events": event_views,
            "event_total": total,
            "session_limit": min(3, cfg.monitor_session_limit),
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
