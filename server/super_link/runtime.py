"""Small host adapter around existing runs, tools and post-process finalization.

No workflow imports. Worker identity is resolved from persisted ownership, never
accepted in a model payload. Recovery requires a recorded process-exit witness.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server import artifacts, store
from server.run_modes import pipeline_for_mode
from server.super_link import events, service
from server.super_link import models as sl
from server.super_link.contracts import (
    CollaborationError,
    EvidenceDelivery,
    SenderBinding,
    parse_content,
)


async def binding_for(session: AsyncSession, run_id: uuid.UUID) -> SenderBinding | None:
    run = await session.get(store.Run, run_id)
    if run is None:
        return None
    member = await session.scalar(
        select(sl.SuperLinkParticipant).where(sl.SuperLinkParticipant.session_id == run.session_id)
    )
    if member is None:
        return None
    space = await session.get(sl.SuperLinkSpace, member.space_id)
    if space is None or space.user_id != run.user_id:
        raise CollaborationError("invalid_sender_binding")
    if run.pipeline_id != pipeline_for_mode(member.role):
        raise CollaborationError("participant_mode_mismatch")
    return SenderBinding(run.user_id, member.space_id, member.id, run.id)


async def prepare(run_id: uuid.UUID, expected_head: uuid.UUID | None) -> dict[str, Any] | None:
    """Persist execution before launching the process; provide public peer metadata."""
    async with store.get_sessionmaker().begin() as session:
        binding = await binding_for(session, run_id)
        if binding is None:
            return None
        run = await session.get(store.Run, run_id)
        if run is None or run.status not in {"queued", "running"}:
            raise CollaborationError("run_not_launchable")
        space = await session.get(sl.SuperLinkSpace, binding.space_id, with_for_update=True)
        dispatch = await session.scalar(select(store.RunDispatch).where(store.RunDispatch.run_id == run_id))
        # A pause drains work already handed to the orchestrator. The dispatch
        # fence serializes that handoff with pause; stop never grants this exception.
        admitted = dispatch is not None and dispatch.status in {"claimed", "dispatched"}
        if space is None or space.control_state in {"stopping", "stopped"} or (space.paused and not admitted):
            raise CollaborationError("space_paused")
        old = await session.get(sl.SuperLinkFinalization, run_id)
        if old is not None:
            raise CollaborationError("run_already_prepared")
        finalization = sl.SuperLinkFinalization(run_id=run_id, expected_head_run_id=expected_head)
        session.add(finalization)
        from server.super_link.inbox import freeze_access

        inbox_count = await freeze_access(session, binding, space.goal_version)
        peers = list(
            await session.scalars(
                select(sl.SuperLinkParticipant).where(
                    sl.SuperLinkParticipant.space_id == binding.space_id,
                    sl.SuperLinkParticipant.id != binding.participant_id,
                )
            )
        )
        await _stage_finalization(session, binding, finalization, phase="prepared")
        await events.seal_changes(session)
        return {
            "goal": space.goal,
            "goal_version": space.goal_version,
            "participant_id": str(binding.participant_id),
            "peers": [{"participant_id": str(peer.id), "role": peer.role} for peer in peers],
            "informational_inbox": {
                "count": inbox_count,
                "tool": "read_super_link_inbox",
                "note": "可按需读取本轮启动前已通过检查的信息交付；读取不等于采纳或执行。",
            },
        }


async def require_session_mode(session_id: uuid.UUID, pipeline_id: str) -> None:
    """Reject a wrong-mode human request before uploads or a queued Run is created."""
    async with store.get_sessionmaker()() as session:
        member = await session.scalar(
            select(sl.SuperLinkParticipant).where(
                sl.SuperLinkParticipant.session_id == session_id,
            )
        )
        if member is not None and pipeline_id != pipeline_for_mode(member.role):
            raise CollaborationError("participant_mode_mismatch")


async def register_from_worker(run_id: uuid.UUID, payload: dict[str, Any]) -> dict[str, Any]:
    """Only explicit delivery registration is exposed; no publish/review/launch RPC."""
    if set(payload) - {
        "recipient_id",
        "registration_key",
        "content",
        "in_reply_to",
        "revises_message_id",
    }:
        raise CollaborationError("unknown_delivery_field")
    async with store.get_sessionmaker().begin() as session:
        binding = await binding_for(session, run_id)
        if binding is None:
            raise CollaborationError("run_not_bound")
        space = await session.get(sl.SuperLinkSpace, binding.space_id, with_for_update=True)
        finalization = await session.get(sl.SuperLinkFinalization, run_id)
        run = await session.get(store.Run, run_id)
        if (
            space is None
            or space.control_state in {"stopping", "stopped"}
            or finalization is None
            or finalization.state != "executing"
            or finalization.worker_exited_at is not None
            or run is None
            or run.status not in {"queued", "running"}
        ):
            raise CollaborationError("registration_closed")
        row = await service.register(
            session,
            binding=binding,
            recipient_id=uuid.UUID(payload["recipient_id"]),
            registration_key=uuid.UUID(payload["registration_key"]),
            content=parse_content(payload["content"]),
            in_reply_to=uuid.UUID(payload["in_reply_to"]) if payload.get("in_reply_to") else None,
            revises_message_id=uuid.UUID(payload["revises_message_id"])
            if payload.get("revises_message_id")
            else None,
        )
        await events.seal_changes(session)
        return {
            "ok": True,
            "message_id": str(row.id),
            "state": row.state,
            "published": False,
            "note": "登记成功；收尾、旁路和执行受理尚未完成",
        }


async def witness_exit(run_id: uuid.UUID, exit_code: int | None) -> None:
    """Called only after the parent observed process exit; safe to retry."""
    if exit_code is None:
        return
    async with store.get_sessionmaker().begin() as session:
        row = await session.get(sl.SuperLinkFinalization, run_id, with_for_update=True)
        if row is not None and row.worker_exited_at is None:
            row.worker_exited_at = datetime.now(UTC)
            row.exit_code = exit_code
            if row.state not in {"ready", "failed"}:
                row.state = "pending"
            binding = await binding_for(session, run_id)
            if binding is not None:
                await _stage_finalization(
                    session, binding, row, phase="witness_exit", version="1"
                )
                await events.seal_changes(session)


async def launch_failed(run_id: uuid.UUID) -> None:
    """No process was created; release the queue without publishing anything."""
    async with store.get_sessionmaker().begin() as session:
        row = await session.get(sl.SuperLinkFinalization, run_id, with_for_update=True)
        if row is not None and row.state == "executing":
            row.state, row.error_code = "failed", "worker_launch_failed"
            binding = await binding_for(session, run_id)
            if binding is not None:
                await _stage_finalization(
                    session, binding, row, phase="launch_failed", version="1"
                )
                await events.seal_changes(session)


async def _stage_finalization(
    session: AsyncSession,
    binding: SenderBinding,
    row: sl.SuperLinkFinalization,
    *,
    phase: str,
    version: str | None = None,
) -> None:
    await events.stage_for_space(
        session,
        binding.space_id,
        type="sl.finalization.changed",
        change_key=f"finalization:{row.run_id}:{phase}:{version or row.recovery_attempts}",
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
        participant_id=binding.participant_id,
        run_id=row.run_id,
    )


def _read_evidence(run_id: uuid.UUID, rel_path: str, digest: str) -> str:
    path = artifacts.resolve_artifact_path(run_id.hex, rel_path)
    if path is None:
        raise CollaborationError("evidence_not_accessible")
    # Bound memory before reading, then verify the bytes actually read.
    with path.open("rb") as stream:
        data = stream.read(64_001)
    if len(data) > 64_000:
        raise CollaborationError("evidence_too_large")
    if hashlib.sha256(data).hexdigest() != digest:
        raise CollaborationError("evidence_digest_mismatch")
    try:
        return data.decode("utf-8")
    except UnicodeError as exc:
        raise CollaborationError("evidence_not_utf8") from exc


async def snapshot_evidence(
    session: AsyncSession, message: sl.SuperLinkMessage, content: EvidenceDelivery
) -> None:
    """Snapshot registered final outputs into immutable delivery-owned text."""
    if len({item.rel_path for item in content.artifacts}) != len(content.artifacts):
        raise CollaborationError("duplicate_evidence")
    for ref in content.artifacts:
        artifact = await session.get(store.Artifact, (message.source_run_id, ref.rel_path))
        if artifact is None or artifact.sha256 != ref.sha256:
            raise CollaborationError("evidence_not_archived")
        text = await asyncio.to_thread(
            _read_evidence, message.source_run_id, ref.rel_path, ref.sha256
        )
        session.add(
            sl.SuperLinkEvidence(
                message_id=message.id,
                rel_path=ref.rel_path,
                sha256=ref.sha256,
                text=text,
            )
        )


@asynccontextmanager
async def continuity_guard(run_id: uuid.UUID) -> AsyncIterator[bool]:
    """Serialize native ingestion with owner abandonment, including late callbacks."""
    async with store.get_sessionmaker().begin() as session:
        binding = await binding_for(session, run_id)
        if binding is None:
            yield False
            return
        await service._space(session, binding.user_id, binding.space_id)
        row = await session.get(sl.SuperLinkFinalization, run_id, with_for_update=True)
        yield row is not None and row.state not in {"failed", "ready"}


async def finalize(run_id: uuid.UUID) -> bool:
    """Publish all registered deliveries atomically, or retain a retryable reason."""
    async with store.get_sessionmaker().begin() as session:
        binding = await binding_for(session, run_id)
        if binding is None:
            return False
        # Same lock order as registration/publication.
        await service._space(session, binding.user_id, binding.space_id)
        row = await session.get(sl.SuperLinkFinalization, run_id, with_for_update=True)
        if row is None or row.worker_exited_at is None:
            return False
        if row.state in {"ready", "failed"}:
            return row.state == "ready"
        run = await session.get(store.Run, run_id)
        if run is None or run.status in {"queued", "running"}:
            return False
        if (
            row.exit_code != 0
            or run.status != "completed"
            or run.error
            or run.stopped_by
            not in {
                None,
                "",
                "no_tool",
                "final_answer",
            }
        ):
            row.state, row.error_code = "failed", "source_run_not_complete"
            row.retry_at = None
            await _stage_finalization(session, binding, row, phase=f"finalize:{row.error_code}")
            await events.seal_changes(session)
            return False
        source = await session.get(store.RunContextSource, run_id)
        if (
            source is None
            or source.session_id != run.session_id
            or source.pipeline_id != run.pipeline_id
            or not source.native_payload
            or (hashlib.sha256(source.native_payload.encode()).hexdigest() != source.native_sha256)
        ):
            row.error_code = "continuity_not_saved"
            await _stage_finalization(session, binding, row, phase=f"finalize:{row.error_code}")
            await events.seal_changes(session)
            return False
        try:
            await service.require_continuity_head(session, run, source)
            async with events.savepoint(session):
                messages = list(
                    await session.scalars(
                        select(sl.SuperLinkMessage).where(
                            sl.SuperLinkMessage.source_run_id == run_id,
                            sl.SuperLinkMessage.state == "registered",
                        )
                    )
                )
                for message in messages:
                    await service.publish(session, binding=binding, message_id=message.id)
        except (ValueError, OSError) as exc:
            row.error_code = str(exc) if isinstance(exc, CollaborationError) else "invalid_delivery"
            await _stage_finalization(session, binding, row, phase=f"finalize:{row.error_code}")
            await events.seal_changes(session)
            return False
        row.state, row.error_code = "ready", None
        row.retry_at = None
        await _stage_finalization(session, binding, row, phase="finalize:ready")
        await events.seal_changes(session)
        return True
