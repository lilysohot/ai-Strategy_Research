"""Read-only, run-scoped access to reviewed informational deliveries."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Uuid, func, insert, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from server import store
from server.super_link import models as sl
from server.super_link.contracts import (
    CollaborationError,
    SenderBinding,
    content_digest,
    parse_content,
)
from server.super_link.coordination import evidence_for


async def freeze_access(session: AsyncSession, binding: SenderBinding, goal_version: int) -> int:
    """Pin the eligible set at launch; later arrivals wait for a later run."""
    candidates = (
        select(literal(binding.run_id, type_=Uuid()), sl.SuperLinkMessage.id)
        .join(sl.SuperLinkReceipt, sl.SuperLinkReceipt.message_id == sl.SuperLinkMessage.id)
        .join(sl.SuperLinkReview, sl.SuperLinkReview.message_id == sl.SuperLinkMessage.id)
        .where(
            sl.SuperLinkMessage.recipient_id == binding.participant_id,
            sl.SuperLinkMessage.space_id == binding.space_id,
            sl.SuperLinkMessage.state == "published",
            sl.SuperLinkMessage.content_json["requests_execution"].as_boolean().is_(False),
            sl.SuperLinkMessage.goal_version == goal_version,
            sl.SuperLinkReview.goal_version == goal_version,
            sl.SuperLinkReview.content_sha256 == sl.SuperLinkMessage.content_sha256,
            sl.SuperLinkReview.verdict.in_(["pass", "caveat"]),
        )
    )
    await session.execute(
        insert(sl.SuperLinkInboxAccess).from_select(["run_id", "message_id"], candidates)
    )
    return int(
        await session.scalar(
            select(func.count())
            .select_from(sl.SuperLinkInboxAccess)
            .where(sl.SuperLinkInboxAccess.run_id == binding.run_id)
        )
        or 0
    )


async def read_from_worker(run_id: uuid.UUID, payload: dict[str, Any]) -> dict[str, Any]:
    """The capability fixes recipient identity; no peer history or queue access."""
    from server.super_link.runtime import binding_for

    if set(payload) - {"message_id", "after", "limit"}:
        raise CollaborationError("unknown_inbox_field")
    limit = payload.get("limit", 10)
    if type(limit) is not int or not 1 <= limit <= 20:
        raise CollaborationError("invalid_inbox_limit")
    message_id = uuid.UUID(payload["message_id"]) if payload.get("message_id") else None
    after = uuid.UUID(payload["after"]) if payload.get("after") else None
    async with store.get_sessionmaker()() as session:
        binding = await binding_for(session, run_id)
        final = await session.get(sl.SuperLinkFinalization, run_id)
        run = await session.get(store.Run, run_id)
        if (
            binding is None
            or run is None
            or final is None
            or run.status not in {"queued", "running"}
            or final.state != "executing"
            or final.worker_exited_at is not None
        ):
            raise CollaborationError("inbox_closed")
        space = await session.get(sl.SuperLinkSpace, binding.space_id)
        owner = await session.get(store.User, binding.user_id)
        research = await session.get(store.Session, run.session_id)
        if (
            space is None
            or space.control_state in {"stopping", "stopped"}
            or owner is None
            or owner.status != "active"
            or research is None
            or research.deleted_at is not None
        ):
            raise CollaborationError("inbox_closed")
        query = (
            select(sl.SuperLinkMessage, sl.SuperLinkReview)
            .join(
                sl.SuperLinkInboxAccess,
                sl.SuperLinkInboxAccess.message_id == sl.SuperLinkMessage.id,
            )
            .join(sl.SuperLinkReview, sl.SuperLinkReview.message_id == sl.SuperLinkMessage.id)
            .where(
                sl.SuperLinkInboxAccess.run_id == run_id,
                sl.SuperLinkMessage.recipient_id == binding.participant_id,
                sl.SuperLinkMessage.space_id == binding.space_id,
            )
        )
        if message_id:
            query = query.where(sl.SuperLinkMessage.id == message_id)
        elif after:
            query = query.where(sl.SuperLinkMessage.id > after)
        rows = (
            await session.execute(query.order_by(sl.SuperLinkMessage.id).limit(limit + 1))
        ).all()
        if message_id and not rows:
            raise CollaborationError("delivery_not_visible")
        items = []
        for message, review in rows[:limit]:
            content = parse_content(message.content_json)
            if (
                message.state != "published"
                or content.requests_execution
                or content_digest(content) != message.content_sha256
                or review.content_sha256 != message.content_sha256
                or review.verdict not in {"pass", "caveat"}
                or review.goal_version != space.goal_version
                or message.goal_version != space.goal_version
            ):
                raise CollaborationError("stale_or_invalid_review")
            item = {
                "message_id": str(message.id),
                "source_run_id": str(message.source_run_id),
                "sender_id": str(message.sender_id),
                "request_id": str(message.request_id),
                "in_reply_to": str(message.in_reply_to) if message.in_reply_to else None,
                "goal_version": message.goal_version,
                "content_sha256": message.content_sha256,
                "published_at": message.published_at.isoformat() if message.published_at else None,
                "inspection": {"verdict": review.verdict, "explanation": review.explanation},
            }
            if message_id:
                item.update(
                    content=content.model_dump(), evidence=await evidence_for(session, message)
                )
            else:
                item["summary"] = content.body[:200]
            items.append(item)
        return {
            "ok": True,
            "items": items,
            "next_after": str(rows[limit - 1][0].id) if len(rows) > limit else None,
            "note": "正式信息交付，不是人工授权；读取不代表采纳、验证或执行。新交付下一轮可读。",
        }
