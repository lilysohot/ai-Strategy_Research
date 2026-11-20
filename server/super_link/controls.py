"""Space controls around native runs. Durable intent, independent stop reconciliation."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server import dispatch_outbox, store
from server.config import get_config, run_dir_for
from server.orchestrator import Orchestrator
from server.super_link import models as sl
from server.super_link.contracts import CollaborationError
from server.super_link.management import owned_space

logger = logging.getLogger(__name__)


class ControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["pause", "stop", "resume", "continue"]
    idempotency_key: uuid.UUID
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=2000)
    participant_id: uuid.UUID | None = None
    message: str = Field(default="", max_length=16000)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason_required")
        return value.strip()


def delivery_cancelled(space: sl.SuperLinkSpace, message: sl.SuperLinkMessage) -> bool:
    return bool(
        space.delivery_cutoff
        and message.created_at.replace(tzinfo=UTC) <= space.delivery_cutoff.replace(tzinfo=UTC)
    )


async def active_runs(session: AsyncSession, space_id: uuid.UUID) -> list[store.Run]:
    return list(
        await session.scalars(
            select(store.Run)
            .join(
                sl.SuperLinkParticipant, sl.SuperLinkParticipant.session_id == store.Run.session_id
            )
            .where(
                sl.SuperLinkParticipant.space_id == space_id,
                store.Run.status.in_(["queued", "running"]),
            )
            .order_by(store.Run.created_at, store.Run.id)
        )
    )


async def unfinished(session: AsyncSession, space_id: uuid.UUID) -> bool:
    return (
        await session.scalar(
            select(sl.SuperLinkFinalization.run_id)
            .join(store.Run, store.Run.id == sl.SuperLinkFinalization.run_id)
            .join(
                sl.SuperLinkParticipant, sl.SuperLinkParticipant.session_id == store.Run.session_id
            )
            .where(
                sl.SuperLinkParticipant.space_id == space_id,
                sl.SuperLinkFinalization.state.in_(["executing", "pending"]),
            )
            .limit(1)
        )
        is not None
    )


async def control(user_id: uuid.UUID, space_id: uuid.UUID, request: ControlRequest) -> dict:
    cfg = get_config()
    if not cfg.super_link_enabled or cfg.restore_mode:
        raise CollaborationError("control_unavailable")
    command = request.model_dump(mode="json")
    async with store.get_sessionmaker().begin() as session:
        space = await owned_space(session, user_id, space_id, lock=True)
        old = await session.scalar(
            select(sl.SuperLinkRecoveryAction).where(
                sl.SuperLinkRecoveryAction.space_id == space_id,
                sl.SuperLinkRecoveryAction.idempotency_key == request.idempotency_key,
            )
        )
        if old:
            if old.request_json != command:
                raise CollaborationError("idempotency_conflict")
            return old.result_json
        if request.expected_version != space.control_version:
            raise CollaborationError("control_version_conflict")
        if request.action != "continue" and (request.participant_id or request.message):
            raise CollaborationError("unexpected_target")
        result: dict = {"action": request.action}
        if request.action == "pause":
            if space.control_state != "active":
                raise CollaborationError("space_not_active")
            space.paused, space.control_state = True, "paused"
        elif request.action == "stop":
            if space.control_state in {"stopping", "stopped"}:
                raise CollaborationError("space_already_stopped")
            space.paused, space.control_state = True, "stopping"
            space.delivery_cutoff = datetime.now(UTC)
        elif request.action == "resume":
            if space.control_state not in {"paused", "stopped"}:
                raise CollaborationError("space_not_resumable")
            if space.control_state == "stopped" and (
                await active_runs(session, space_id) or await unfinished(session, space_id)
            ):
                raise CollaborationError("stop_not_finished")
            space.paused, space.control_state = False, "active"
        else:
            if space.paused or not cfg.dispatch_enabled:
                raise CollaborationError("space_not_active")
            peer = (
                await session.get(sl.SuperLinkParticipant, request.participant_id)
                if request.participant_id
                else None
            )
            if peer is None or peer.space_id != space_id:
                raise CollaborationError("not_found")
            if not request.message.strip():
                raise CollaborationError("message_required")
            # An explicit human continuation is a new FIFO item, never a resurrection
            # of a stopped run or an automatic replay of its external side effects.
            from server.run_modes import pipeline_for_mode

            research = await session.get(store.Session, peer.session_id, with_for_update=True)
            if research is None or research.deleted_at is not None:
                raise CollaborationError("session_not_available")
            if (
                await dispatch_outbox.research_queue_depth(session, peer.session_id)
                >= cfg.dispatch_research_queue_limit
            ):
                raise CollaborationError("queue_full")
            rid = uuid.uuid5(request.idempotency_key, str(space_id))
            snapshot = await store.build_llm_snapshot(user_id=user_id)
            session.add(
                store.Run(
                    id=rid,
                    user_id=user_id,
                    session_id=peer.session_id,
                    status="queued",
                    prompt=request.message.strip(),
                    pipeline_id=pipeline_for_mode(peer.role),
                    run_dir=str(run_dir_for(rid.hex)),
                    llm_snapshot_json=snapshot,
                    llm_config_id=uuid.UUID(snapshot["config_id"])
                    if snapshot.get("config_id")
                    else None,
                )
            )
            await session.flush()
            await dispatch_outbox.enqueue(
                session,
                run_id=rid,
                user_id=user_id,
                research_id=peer.session_id,
                session_key=str(peer.session_id),
                prompt=request.message.strip(),
            )
            await store.append_turn_in(
                session,
                session_id=peer.session_id,
                run_id=rid,
                role="user",
                content=request.message.strip(),
            )
            result["run_id"] = str(rid)
        space.control_version += 1
        result.update(control_state=space.control_state, control_version=space.control_version)
        session.add(
            sl.SuperLinkRecoveryAction(
                space_id=space_id,
                user_id=user_id,
                idempotency_key=request.idempotency_key,
                request_json=command,
                result_json=result,
            )
        )
        return result


async def reconcile_stops(orch: Orchestrator) -> None:
    """Retry durable stops after disconnect/restart; never infer remote process exit."""
    async with store.get_sessionmaker()() as session:
        spaces = list(
            await session.scalars(
                select(sl.SuperLinkSpace.id).where(
                    sl.SuperLinkSpace.control_state.in_(["stopping", "stopped"]),
                )
            )
        )
    for space_id in spaces:
        async with store.get_sessionmaker().begin() as session:
            # A page may resume a stopped space after the scan above. Never
            # collect a later generation's runs using an old stop intent.
            current = await session.get(sl.SuperLinkSpace, space_id, with_for_update=True)
            if current is None or current.control_state not in {"stopping", "stopped"}:
                continue
            runs = [(r.id, r.status) for r in await active_runs(session, space_id)]
        for rid, status in runs:
            try:
                async with asyncio.timeout(5):
                    if status == "queued" and await dispatch_outbox.stop_queued_run(run_id=rid):
                        continue
                    # Only the owning API instance delivers stdin stop.
                    await orch.stop(rid.hex)
            except Exception:
                logger.warning("Super-link stop deferred for run %s", rid)
        async with store.get_sessionmaker().begin() as session:
            space = await session.get(sl.SuperLinkSpace, space_id, with_for_update=True)
            if (
                space
                and space.control_state == "stopping"
                and not (
                    await active_runs(session, space_id) or await unfinished(session, space_id)
                )
            ):
                space.control_state = "stopped"
                space.control_version += 1
