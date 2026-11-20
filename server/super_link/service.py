"""Transactional registration, publication and durable receipt.

Callers own commit/rollback. No method starts a model, rewrites continuity, or
marks content adopted. The host must bind identities before calling this API.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server import store
from server.run_modes import pipeline_for_mode
from server.super_link import events
from server.super_link import models as sl
from server.super_link.contracts import (
    CollaborationError,
    DeliveryContent,
    EvidenceDelivery,
    Pair,
    SenderBinding,
    content_digest,
    parse_content,
)


async def _space(
    session: AsyncSession, user_id: uuid.UUID, space_id: uuid.UUID
) -> sl.SuperLinkSpace:
    space = await session.scalar(
        select(sl.SuperLinkSpace)
        .where(sl.SuperLinkSpace.id == space_id, sl.SuperLinkSpace.user_id == user_id)
        .with_for_update()
    )
    if space is None:
        raise CollaborationError("space_not_found")
    return space


async def _pair(session: AsyncSession, space_id: uuid.UUID) -> Pair:
    members = {
        row.role: row
        for row in await session.scalars(
            select(sl.SuperLinkParticipant).where(sl.SuperLinkParticipant.space_id == space_id)
        )
    }
    return Pair(
        space_id,
        members["team"].id,
        members["team"].session_id,
        members["single"].id,
        members["single"].session_id,
    )


async def create_pair(
    session: AsyncSession, *, user_id: uuid.UUID, creation_key: uuid.UUID, goal: str
) -> Pair:
    """Atomically create two new, exclusive sessions; retry returns the same pair."""
    if not goal.strip() or len(goal) > 16_000:
        raise CollaborationError("invalid_goal")
    owner = await session.scalar(
        select(store.User).where(store.User.id == user_id).with_for_update()
    )
    if owner is None or owner.status != "active":
        raise CollaborationError("owner_not_available")
    old = await session.scalar(
        select(sl.SuperLinkSpace).where(
            sl.SuperLinkSpace.user_id == user_id,
            sl.SuperLinkSpace.creation_key == creation_key,
        )
    )
    if old is not None:
        if old.goal != goal:
            raise CollaborationError("creation_key_conflict")
        return await _pair(session, old.id)
    space = sl.SuperLinkSpace(user_id=user_id, creation_key=creation_key, goal=goal)
    session.add(space)
    await session.flush()
    for role in ("team", "single"):
        research = store.Session(user_id=user_id, title=f"{role}: {goal[:80]}")
        session.add(research)
        await session.flush()
        session.add(sl.SuperLinkParticipant(space_id=space.id, session_id=research.id, role=role))
    await session.flush()
    session.add(sl.SuperLinkEventHead(space_id=space.id, stream_epoch=uuid.uuid4()))
    pair = await _pair(session, space.id)
    await events.stage_for_space(
        session,
        space.id,
        type="sl.space.created",
        change_key=f"space:{space.id}:created",
        data={"goal_version": space.goal_version, "roles": ["team", "single"]},
        invalidate=("space", "participants", "runs", "deliveries", "actions", "interventions"),
        source_kind="space",
        source_id=str(space.id),
    )
    return pair


async def _bound_run(
    session: AsyncSession, binding: SenderBinding
) -> tuple[sl.SuperLinkParticipant, store.Run]:
    sender = await session.get(sl.SuperLinkParticipant, binding.participant_id)
    run = await session.scalar(
        select(store.Run).where(store.Run.id == binding.run_id).with_for_update()
    )
    if (
        sender is None
        or sender.space_id != binding.space_id
        or run is None
        or run.session_id != sender.session_id
        or run.user_id != binding.user_id
        or run.pipeline_id != pipeline_for_mode(sender.role)
    ):
        raise CollaborationError("invalid_sender_binding")
    research = await session.get(store.Session, sender.session_id)
    if research is None or research.user_id != binding.user_id or research.deleted_at is not None:
        raise CollaborationError("session_not_available")
    return sender, run


async def register(
    session: AsyncSession,
    *,
    binding: SenderBinding,
    recipient_id: uuid.UUID,
    registration_key: uuid.UUID,
    content: DeliveryContent | EvidenceDelivery,
    in_reply_to: uuid.UUID | None = None,
    revises_message_id: uuid.UUID | None = None,
) -> sl.SuperLinkMessage:
    """Register fixed content, without publishing it or waking another session."""
    space = await _space(session, binding.user_id, binding.space_id)
    sender, run = await _bound_run(session, binding)
    recipient = await session.get(sl.SuperLinkParticipant, recipient_id)
    if recipient is None or recipient.space_id != space.id or recipient.id == sender.id:
        raise CollaborationError("invalid_recipient")
    research = await session.get(store.Session, recipient.session_id)
    if research is None or research.user_id != binding.user_id or research.deleted_at is not None:
        raise CollaborationError("session_not_available")
    digest = content_digest(content)
    revision_parent = None
    if revises_message_id is not None:
        revision_parent = await session.get(sl.SuperLinkMessage, revises_message_id)
        if (
            revision_parent is None
            or revision_parent.space_id != space.id
            or revision_parent.sender_id != sender.id
            or revision_parent.recipient_id != recipient_id
            or revision_parent.source_run_id == run.id
            or revision_parent.state != "published"
            or (in_reply_to is not None and in_reply_to != revision_parent.in_reply_to)
        ):
            raise CollaborationError("invalid_revision")
        in_reply_to = revision_parent.in_reply_to
    old = await session.scalar(
        select(sl.SuperLinkMessage).where(
            sl.SuperLinkMessage.source_run_id == run.id,
            sl.SuperLinkMessage.registration_key == registration_key,
        )
    )
    if old is not None:
        if (
            old.sender_id != sender.id
            or old.recipient_id != recipient_id
            or old.content_sha256 != digest
            or old.in_reply_to != in_reply_to
            or old.revises_message_id != revises_message_id
        ):
            raise CollaborationError("registration_key_conflict")
        await _stage_registered(session, old, sender=sender, run=run)
        return old
    message_id = uuid.uuid4()
    request_id = message_id
    if revision_parent is not None:
        review = await session.get(sl.SuperLinkReview, revision_parent.id)
        if review is None or review.verdict not in {"block", "incomplete"} or review.lease_until:
            raise CollaborationError("revision_not_requested")
        if review.failure_kind not in {"business", "validation", None}:
            raise CollaborationError("technical_recovery_required")
        request_id = revision_parent.request_id
    if in_reply_to is not None:
        parent = await session.get(sl.SuperLinkMessage, in_reply_to)
        receipt = await session.get(sl.SuperLinkReceipt, in_reply_to)
        if (
            parent is None
            or parent.space_id != space.id
            or parent.sender_id != recipient_id
            or parent.recipient_id != sender.id
            or parent.state != "published"
            or receipt is None
        ):
            raise CollaborationError("invalid_reply")
        request_id = parent.request_id
    message = sl.SuperLinkMessage(
        id=message_id,
        space_id=space.id,
        sender_id=sender.id,
        recipient_id=recipient_id,
        source_run_id=run.id,
        registration_key=registration_key,
        request_id=request_id,
        in_reply_to=in_reply_to,
        revises_message_id=revises_message_id,
        goal_version=space.goal_version,
        content_json=content.model_dump(),
        content_sha256=digest,
    )
    session.add(message)
    await session.flush()
    await _stage_registered(session, message, sender=sender, run=run)
    return message


async def _stage_registered(
    session: AsyncSession,
    message: sl.SuperLinkMessage,
    *,
    sender: sl.SuperLinkParticipant,
    run: store.Run,
) -> None:
    await events.stage_for_space(
        session,
        message.space_id,
        type="sl.delivery.registered",
        change_key=f"delivery:{message.id}:registered",
        data={
            "message_id": str(message.id),
            "request_id": str(message.request_id),
            "recipient_id": str(message.recipient_id),
            "in_reply_to": str(message.in_reply_to) if message.in_reply_to else None,
            "revises_message_id": (
                str(message.revises_message_id) if message.revises_message_id else None
            ),
            "goal_version": message.goal_version,
            "content_sha256": message.content_sha256,
        },
        invalidate=("deliveries", "runs"),
        source_kind="delivery",
        source_id=str(message.id),
        participant_id=sender.id,
        session_id=sender.session_id,
        run_id=run.id,
    )


async def publish(
    session: AsyncSession, *, binding: SenderBinding, message_id: uuid.UUID
) -> sl.SuperLinkMessage:
    """Publish after successful Run termination and archived native continuity.

    Host API, never a model tool. Runtime-bound runs additionally require the
    parent's process-exit witness; V2 snapshots selected final evidence. No
    private continuity payload crosses the boundary, only its audit digest.
    """
    space = await _space(session, binding.user_id, binding.space_id)
    sender, run = await _bound_run(session, binding)
    message = await session.get(sl.SuperLinkMessage, message_id)
    if (
        message is None
        or message.space_id != space.id
        or message.sender_id != sender.id
        or message.source_run_id != run.id
    ):
        raise CollaborationError("message_not_found")
    if message.state == "published":
        return message
    if (
        run.status != "completed"
        or run.finished_at is None
        or run.error
        or run.stopped_by not in {None, "", "no_tool", "final_answer"}
    ):
        raise CollaborationError("source_run_not_complete")
    source = await session.get(store.RunContextSource, run.id)
    if (
        source is None
        or source.session_id != run.session_id
        or source.pipeline_id != run.pipeline_id
        or not source.native_payload
        or hashlib.sha256(source.native_payload.encode()).hexdigest() != source.native_sha256
    ):
        raise CollaborationError("continuity_not_saved")
    # Unknown versions or mutated registered content never silently become V1.
    content = parse_content(message.content_json)
    if content_digest(content) != message.content_sha256:
        raise CollaborationError("content_digest_mismatch")
    finalization = await session.get(sl.SuperLinkFinalization, run.id)
    if finalization is not None and (
        finalization.worker_exited_at is None
        or finalization.exit_code != 0
        or finalization.state == "failed"
    ):
        raise CollaborationError("worker_not_cleanly_exited")
    if finalization is not None:
        await require_continuity_head(session, run, source)
    if isinstance(content, EvidenceDelivery):
        if finalization is None or finalization.worker_exited_at is None:
            raise CollaborationError("worker_not_cleanly_exited")
        from server.super_link.runtime import snapshot_evidence

        await snapshot_evidence(session, message, content)
    message.state = "published"
    message.published_at = datetime.now(UTC)
    message.continuity_sha256 = source.native_sha256
    session.add(sl.SuperLinkOutbox(message_id=message.id))
    await session.flush()
    await events.stage_for_space(
        session,
        message.space_id,
        type="sl.delivery.published",
        change_key=f"delivery:{message.id}:published",
        data={
            "message_id": str(message.id),
            "request_id": str(message.request_id),
            "source_run_id": str(run.id),
            "content_sha256": message.content_sha256,
        },
        invalidate=("deliveries", "runs"),
        source_kind="delivery",
        source_id=str(message.id),
        participant_id=sender.id,
        session_id=sender.session_id,
        run_id=run.id,
    )
    return message


async def require_continuity_head(
    session: AsyncSession, run: store.Run, source: store.RunContextSource
) -> None:
    """An immutable archive can survive a failed CAS; require the active carrier too."""
    await session.get(store.Session, run.session_id, with_for_update=True)
    head = await session.scalar(
        select(store.SessionConversation).where(
            store.SessionConversation.session_id == run.session_id
        )
    )
    if (
        head is None
        or head.updated_by_run_id != run.id
        or hashlib.sha256(head.payload.encode()).hexdigest() != source.native_sha256
    ):
        raise CollaborationError("continuity_head_not_committed")


async def receive(session: AsyncSession, message_id: uuid.UUID) -> None:
    """Commit a transport receipt before ACK. No inspection or run dispatch here."""
    outbox = await session.scalar(
        select(sl.SuperLinkOutbox)
        .where(sl.SuperLinkOutbox.message_id == message_id)
        .with_for_update()
    )
    if outbox is None or outbox.state != "pending":
        return
    message = await session.get(sl.SuperLinkMessage, message_id)
    error = None
    if message is None or message.state != "published":
        error = "message_not_published"
    else:
        try:
            content = parse_content(message.content_json)
            if content_digest(content) != message.content_sha256:
                error = "content_digest_mismatch"
        except ValidationError:
            error = "unsupported_or_invalid_content"
    if error:
        outbox.state = "quarantined"
        outbox.error_code = error
        if message is not None:
            await events.stage_for_space(
                session,
                message.space_id,
                type="sl.delivery.quarantined",
                change_key=f"receipt:{message_id}:quarantined:{error}",
                data={"message_id": str(message_id), "error_code": error},
                invalidate=("deliveries", "runs"),
                source_kind="delivery",
                source_id=str(message_id),
            )
        return
    session.add(sl.SuperLinkReceipt(message_id=message_id))
    outbox.state = "received"
    await session.flush()
    assert message is not None
    await events.stage_for_space(
        session,
        message.space_id,
        type="sl.delivery.received",
        change_key=f"receipt:{message_id}:received",
        data={"message_id": str(message_id), "transport_state": "received"},
        invalidate=("deliveries", "runs"),
        source_kind="delivery",
        source_id=str(message_id),
    )


async def inbox(
    session: AsyncSession, *, user_id: uuid.UUID, participant_id: uuid.UUID, limit: int = 50
) -> list[sl.SuperLinkMessage]:
    """Host inspection query, not an agent execution-input interface.

    Results still await independent review. They must not be injected into an
    agent run as accepted work; review and queue acceptance belong to P2/P3.
    """
    if not 1 <= limit <= 100:
        raise CollaborationError("invalid_limit")
    participant = await session.get(sl.SuperLinkParticipant, participant_id)
    if participant is None:
        raise CollaborationError("participant_not_found")
    await _space(session, user_id, participant.space_id)
    return list(
        await session.scalars(
            select(sl.SuperLinkMessage)
            .join(sl.SuperLinkReceipt)
            .where(sl.SuperLinkMessage.recipient_id == participant_id)
            .order_by(sl.SuperLinkReceipt.received_at, sl.SuperLinkMessage.id)
            .limit(limit)
        )
    )
