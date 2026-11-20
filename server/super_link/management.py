"""Owner-scoped status projections and explicit, audited recovery commands."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from server import store
from server.config import get_config
from server.super_link import events
from server.super_link import models as sl
from server.super_link.contracts import CollaborationError
from server.super_link.coordination import automatic_budget
from server.super_link.process_witness import group_is_gone


class RecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "inspection_retry",
        "admission_retry",
        "feedback_retry",
        "finalization_retry",
        "abandon_finalization",
        "extend_budget",
    ]
    idempotency_key: uuid.UUID
    target_id: uuid.UUID | None = None
    reason: str = Field(min_length=1, max_length=2000)
    additional_runs: int = Field(default=1, ge=1, le=100)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason_required")
        return value.strip()


async def owned_space(
    session: AsyncSession, user_id: uuid.UUID, space_id: uuid.UUID, *, lock: bool = False
) -> sl.SuperLinkSpace:
    query = select(sl.SuperLinkSpace).where(
        sl.SuperLinkSpace.id == space_id, sl.SuperLinkSpace.user_id == user_id
    )
    if lock:
        query = query.with_for_update()
    space = await session.scalar(query)
    owner = await session.get(store.User, user_id)
    if space is None or owner is None or owner.status != "active":
        raise CollaborationError("not_found")
    return space


def _next_limit(count: int) -> int:
    if count >= 20:
        raise CollaborationError("recovery_limit_exhausted")
    return min(20, count + 3)


async def recover(user_id: uuid.UUID, space_id: uuid.UUID, request: RecoveryRequest) -> dict:
    """No action approves a delivery, forges a successful exit or rewinds continuity."""
    if not get_config().super_link_enabled or get_config().restore_mode:
        raise CollaborationError("recovery_unavailable")
    command = request.model_dump(mode="json")
    async with store.get_sessionmaker().begin() as session:
        space = await owned_space(session, user_id, space_id, lock=True)
        old = await session.scalar(
            select(sl.SuperLinkRecoveryAction).where(
                sl.SuperLinkRecoveryAction.space_id == space_id,
                sl.SuperLinkRecoveryAction.idempotency_key == request.idempotency_key,
            )
        )
        if old is not None:
            if old.request_json != command:
                raise CollaborationError("idempotency_conflict")
            return old.result_json
        now = datetime.now(UTC)
        result: dict = {
            "action": request.action,
            "target_id": str(request.target_id) if request.target_id else None,
        }
        if request.action == "extend_budget":
            if request.target_id is not None:
                raise CollaborationError("unexpected_target")
            used, limit = await automatic_budget(session, space)
            new_limit = limit + request.additional_runs
            if new_limit > 1000:
                raise CollaborationError("budget_ceiling")
            space.automatic_run_limit = new_limit
            mids = select(sl.SuperLinkMessage.id).where(sl.SuperLinkMessage.space_id == space_id)
            released_reviews = cast(
                CursorResult,
                await session.execute(
                    update(sl.SuperLinkReview)
                    .where(
                        sl.SuperLinkReview.message_id.in_(mids),
                        sl.SuperLinkReview.admission_error == "automatic_run_limit",
                    )
                    .values(admission_held=False, admission_retry_at=None)
                ),
            )
            released_feedback = cast(
                CursorResult,
                await session.execute(
                    update(sl.SuperLinkFeedback)
                    .where(
                        sl.SuperLinkFeedback.message_id.in_(mids),
                        sl.SuperLinkFeedback.error_code == "automatic_run_limit",
                    )
                    .values(held=False, retry_at=None)
                ),
            )
            result.update(before_limit=limit, limit=new_limit, used=used)
            await events.stage_for_space(
                session,
                space_id,
                type="sl.space.budget_changed",
                change_key=f"space:{space_id}:budget:{request.idempotency_key}",
                data={
                    "limit": new_limit,
                    "used": used,
                    "remaining": max(0, new_limit - used),
                    "affected_holds": max(0, released_reviews.rowcount)
                    + max(0, released_feedback.rowcount),
                },
                invalidate=("space", "deliveries", "runs", "actions", "interventions"),
                source_kind="space",
                source_id=str(space_id),
            )
        elif request.action in {"finalization_retry", "abandon_finalization"}:
            run = await session.get(store.Run, request.target_id) if request.target_id else None
            member = (
                await session.scalar(
                    select(sl.SuperLinkParticipant).where(
                        sl.SuperLinkParticipant.session_id == run.session_id,
                        sl.SuperLinkParticipant.space_id == space_id,
                    )
                )
                if run
                else None
            )
            row = (
                await session.get(sl.SuperLinkFinalization, request.target_id, with_for_update=True)
                if member
                else None
            )
            if run is None or member is None or row is None:
                raise CollaborationError("not_found")
            if run.status in {"queued", "running"} or row.state in {"ready", "failed"}:
                raise CollaborationError("run_not_recoverable")
            if request.action == "abandon_finalization":
                if row.worker_exited_at is None and not await asyncio.to_thread(
                    group_is_gone, row.process_identity
                ):
                    raise CollaborationError("worker_exit_unverified")
                row.state, row.error_code, row.retry_at = "failed", "owner_abandoned", None
                result["outcome"] = "abandoned_not_published"
            else:
                if row.worker_exited_at is None:
                    raise CollaborationError("worker_exit_unverified")
                if row.exit_code != 0 or run.status != "completed":
                    raise CollaborationError("source_run_not_complete")
                row.recovery_limit = _next_limit(row.recovery_attempts)
                row.retry_at = now
                result.update(
                    outcome="recovery_scheduled",
                    attempts=row.recovery_attempts,
                    limit=row.recovery_limit,
                )
            await events.stage_for_space(
                session,
                space_id,
                type="sl.finalization.changed",
                change_key=f"finalization:{row.run_id}:action:{request.idempotency_key}",
                data={
                    "state": row.state,
                    "worker_exited": row.worker_exited_at is not None,
                    "exit_code": row.exit_code,
                    "error_code": row.error_code,
                    "recovery_attempts": row.recovery_attempts,
                },
                invalidate=("runs", "deliveries", "actions"),
                source_kind="run",
                source_id=str(row.run_id),
                participant_id=member.id,
                session_id=run.session_id,
                run_id=row.run_id,
            )
        else:
            message = (
                await session.get(sl.SuperLinkMessage, request.target_id)
                if request.target_id
                else None
            )
            if message is None or message.space_id != space_id:
                raise CollaborationError("not_found")
            from server.super_link.controls import delivery_cancelled

            if delivery_cancelled(space, message):
                raise CollaborationError("delivery_cancelled")
            review = await session.get(sl.SuperLinkReview, message.id, with_for_update=True)
            if review is None:
                raise CollaborationError("inspection_not_started")
            if request.action == "inspection_retry":
                if review.lease_until and review.lease_until.replace(tzinfo=UTC) > now:
                    raise CollaborationError("inspection_in_progress")
                expired = review.lease_until is not None
                if review.verdict != "incomplete" or (
                    not expired and review.failure_kind not in {"technical", "configuration"}
                ):
                    raise CollaborationError("revision_required")
                if expired:
                    attempt = await session.get(
                        sl.SuperLinkReviewAttempt, (message.id, review.attempt_count)
                    )
                    if attempt and attempt.finished_at is None:
                        attempt.finished_at, attempt.failure_kind = now, "technical"
                        attempt.explanation = "inspection_lease_expired"
                review.attempt_limit = _next_limit(review.attempt_count)
                review.failure_kind, review.lease_until, review.retry_at = "technical", None, now
                result.update(
                    outcome="inspection_scheduled",
                    attempts=review.attempt_count,
                    limit=review.attempt_limit,
                )
                await events.stage_for_space(
                    session,
                    space_id,
                    type="sl.review.changed",
                    change_key=f"review:{message.id}:action:{request.idempotency_key}",
                    data={
                        "attempt": review.attempt_count,
                        "verdict": review.verdict,
                        "failure_kind": "technical",
                        "retry_scheduled": True,
                    },
                    invalidate=("deliveries", "actions"),
                    source_kind="delivery",
                    source_id=str(message.id),
                    participant_id=message.recipient_id,
                    run_id=message.source_run_id,
                )
            elif request.action == "admission_retry":
                if await session.get(sl.SuperLinkExecution, message.id) is not None:
                    raise CollaborationError("already_accepted")
                if review.verdict not in {"pass", "caveat"}:
                    raise CollaborationError("inspection_not_passed")
                if review.admission_error not in {
                    "admission_failed",
                    "automatic_run_limit",
                    "queue_full",
                    "admission_held",
                }:
                    raise CollaborationError("admission_not_retryable")
                used, limit = await automatic_budget(session, space)
                if used >= limit:
                    raise CollaborationError("automatic_run_limit")
                review.admission_limit = _next_limit(review.admission_attempts)
                review.admission_held, review.admission_retry_at = False, now
                result["outcome"] = "admission_scheduled"
                await events.stage_for_space(
                    session,
                    space_id,
                    type="sl.admission.changed",
                    change_key=f"admission:{message.id}:action:{request.idempotency_key}",
                    data={
                        "message_id": str(message.id),
                        "run_id": None,
                        "attempts": review.admission_attempts,
                        "held": False,
                        "error_code": review.admission_error,
                    },
                    invalidate=("deliveries", "runs", "actions"),
                    source_kind="delivery",
                    source_id=str(message.id),
                    participant_id=message.recipient_id,
                    run_id=message.source_run_id,
                )
            elif request.action == "feedback_retry":
                feedback = await session.get(sl.SuperLinkFeedback, message.id, with_for_update=True)
                if feedback is None or feedback.run_id is not None:
                    raise CollaborationError("feedback_not_retryable")
                used, limit = await automatic_budget(session, space)
                if used >= limit:
                    raise CollaborationError("automatic_run_limit")
                feedback.attempt_limit = _next_limit(feedback.attempts)
                feedback.held, feedback.retry_at = False, now
                result["outcome"] = "feedback_scheduled"
                await events.stage_for_space(
                    session,
                    space_id,
                    type="sl.feedback.changed",
                    change_key=f"feedback:{message.id}:action:{request.idempotency_key}",
                    data={
                        "message_id": str(message.id),
                        "review_number": feedback.review_number,
                        "run_id": None,
                        "attempts": feedback.attempts,
                        "error_code": feedback.error_code,
                    },
                    invalidate=("deliveries", "runs", "actions"),
                    source_kind="delivery",
                    source_id=str(message.id),
                    participant_id=message.recipient_id,
                    run_id=message.source_run_id,
                )
        action_id = uuid.uuid4()
        result["recovery_action_id"] = str(action_id)
        session.add(
            sl.SuperLinkRecoveryAction(
                id=action_id,
                space_id=space_id,
                user_id=user_id,
                idempotency_key=request.idempotency_key,
                request_json=command,
                result_json=result,
            )
        )
        await events.stage_for_space(
            session,
            space_id,
            type="sl.action.recorded",
            change_key=f"action:{space_id}:{request.idempotency_key}",
            data={
                "action": request.action,
                "target_id": str(request.target_id) if request.target_id else None,
                "outcome": result.get("outcome", "budget_extended"),
            },
            invalidate=("space", "deliveries", "runs", "actions", "interventions"),
            source_kind="space",
            source_id=str(space_id),
        )
        await events.seal_changes(session)
        return result


def _time(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def run_status(session: AsyncSession, run_id: uuid.UUID | None) -> dict | None:
    run = await session.get(store.Run, run_id) if run_id else None
    if run is None:
        return None
    final = await session.get(sl.SuperLinkFinalization, run.id)
    dispatch = await session.scalar(
        select(store.RunDispatch).where(store.RunDispatch.run_id == run.id)
    )
    return {
        "run_id": str(run.id),
        "session_id": str(run.session_id),
        "status": run.status,
        "pipeline_id": run.pipeline_id,
        "created_at": _time(run.created_at),
        "finished_at": _time(run.finished_at),
        "model_snapshot": run.llm_snapshot_json,
        "dispatch": {
            "status": dispatch.status,
            "attempt": dispatch.attempt,
            "retry_at": _time(dispatch.next_attempt_at),
            "error": dispatch.last_error,
        }
        if dispatch
        else None,
        "finalization": {
            "state": final.state,
            "error": final.error_code,
            "exit_witness": final.worker_exited_at is not None,
            "process_identity_available": final.process_identity is not None,
            "retry_at": _time(final.retry_at),
            "attempts": final.recovery_attempts,
            "limit": final.recovery_limit,
        }
        if final
        else None,
    }


async def delivery_status(
    session: AsyncSession, message: sl.SuperLinkMessage, *, detail: bool = False
) -> dict:
    source = await run_status(session, message.source_run_id)
    receipt = await session.get(sl.SuperLinkReceipt, message.id)
    outbox = await session.get(sl.SuperLinkOutbox, message.id)
    review = await session.get(sl.SuperLinkReview, message.id)
    execution = await session.get(sl.SuperLinkExecution, message.id)
    feedback = await session.get(sl.SuperLinkFeedback, message.id)
    recipient_run = await run_status(session, execution.run_id if execution else None)
    feedback_run = await run_status(session, feedback.run_id if feedback else None)
    phase = "registered"
    if message.state == "registered" and source and source["finalization"]:
        final = source["finalization"]
        phase = (
            "source_failed"
            if final["state"] == "failed"
            else (
                "awaiting_exit"
                if not final["exit_witness"]
                else (
                    "finalization_exhausted"
                    if final["attempts"] >= final["limit"]
                    else "finalizing"
                )
            )
        )
    elif message.state == "published":
        phase = "awaiting_receipt" if receipt is None else "awaiting_inspection"
        if outbox and outbox.state == "quarantined":
            phase = "transport_blocked"
        if review:
            if review.lease_until:
                phase = "inspecting"
            elif review.verdict in {"block", "incomplete"}:
                phase = "correction_required"
                if review.failure_kind == "technical":
                    phase = (
                        "inspection_retry"
                        if review.attempt_count < review.attempt_limit
                        else "inspection_exhausted"
                    )
                elif review.failure_kind == "configuration":
                    phase = "inspection_configuration_required"
            elif not message.content_json.get("requests_execution"):
                phase = "informational_available"
            else:
                phase = "admission_held" if review.admission_held else "awaiting_admission"
        if recipient_run:
            phase = "execution_" + recipient_run["status"]
            if (
                recipient_run["status"] == "completed"
                and recipient_run["finalization"]
                and recipient_run["finalization"]["state"] != "ready"
            ):
                phase = "execution_finalizing"
    from server.super_link.controls import delivery_cancelled

    space = await session.get(sl.SuperLinkSpace, message.space_id)
    if space and delivery_cancelled(space, message) and recipient_run is None:
        phase = "cancelled_by_stop"
    result = {
        "message_id": str(message.id),
        "space_id": str(message.space_id),
        "phase": phase,
        "sender_id": str(message.sender_id),
        "recipient_id": str(message.recipient_id),
        "request_id": str(message.request_id),
        "in_reply_to": str(message.in_reply_to) if message.in_reply_to else None,
        "revises_message_id": str(message.revises_message_id)
        if message.revises_message_id
        else None,
        "goal_version": message.goal_version,
        "content_sha256": message.content_sha256,
        "published_at": _time(message.published_at),
        "received_at": _time(receipt.received_at) if receipt else None,
        "transport_error": outbox.error_code if outbox else None,
        "source_run": source,
        "recipient_run": recipient_run,
        "inspection": {
            "verdict": review.verdict,
            "explanation": review.explanation,
            "failure_kind": review.failure_kind,
            "attempts": review.attempt_count,
            "limit": review.attempt_limit,
            "retry_at": _time(review.retry_at),
            "lease_until": _time(review.lease_until),
            "admission_error": review.admission_error,
            "admission_retry_at": _time(review.admission_retry_at),
            "admission_attempts": review.admission_attempts,
            "admission_limit": review.admission_limit,
        }
        if review
        else None,
        "feedback": {
            "review_number": feedback.review_number,
            "run": feedback_run,
            "error": feedback.error_code,
            "retry_at": _time(feedback.retry_at),
            "held": feedback.held,
            "attempts": feedback.attempts,
            "limit": feedback.attempt_limit,
        }
        if feedback
        else None,
    }
    if detail:
        result["content"] = message.content_json
        result["attempts"] = [
            {
                "number": a.number,
                "reviewer": a.reviewer,
                "input": a.input_json,
                "model_snapshot": a.model_snapshot,
                "verdict": a.verdict,
                "explanation": a.explanation,
                "failure_kind": a.failure_kind,
                "started_at": _time(a.started_at),
                "finished_at": _time(a.finished_at),
            }
            for a in await session.scalars(
                select(sl.SuperLinkReviewAttempt)
                .where(sl.SuperLinkReviewAttempt.message_id == message.id)
                .order_by(sl.SuperLinkReviewAttempt.number)
            )
        ]
        result["revisions"] = [
            str(mid)
            for mid in await session.scalars(
                select(sl.SuperLinkMessage.id)
                .where(sl.SuperLinkMessage.revises_message_id == message.id)
                .order_by(sl.SuperLinkMessage.created_at, sl.SuperLinkMessage.id)
            )
        ]
    return result
