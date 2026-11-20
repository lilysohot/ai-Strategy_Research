"""Opt-in owner-only diagnostics and recovery. No force-approval or execution API."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask
from starlette.types import Message, Send

from server import dispatch_outbox, store
from server.config import get_config, run_dir_for
from server.deps import get_current_user
from server.readiness import probe_data_root
from server.routes.runs import (
    ApproveRequest,
    SteerRequest,
    _require_team_mode_available,
    run_approve,
    run_steer,
)
from server.super_link import controls, events, management, observability, service, stream
from server.super_link import models as sl
from server.super_link.contracts import CollaborationError
from server.super_link.coordination import automatic_budget

logger = logging.getLogger(__name__)


def _enabled() -> None:
    if not get_config().super_link_enabled:
        raise HTTPException(404, "super_link_disabled")


router = APIRouter(prefix="/api/super-link", tags=["super-link"], dependencies=[Depends(_enabled)])


def _creation_gate() -> None:
    cfg = get_config()
    if cfg.restore_mode or not cfg.dispatch_enabled:
        raise HTTPException(503, "当前服务暂不接收新的协作任务")
    _require_team_mode_available(cfg)
    if probe_data_root() is not None:
        raise HTTPException(503, "运行存储暂不可写，请稍后重试")


@router.get("/capabilities")
async def capabilities(user: store.User = Depends(get_current_user)) -> dict:
    del user
    try:
        _creation_gate()
    except HTTPException as exc:
        return {"can_create": False, "reason": exc.detail}
    return {"can_create": True, "reason": None}


class CreateSpaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    creation_key: uuid.UUID
    goal: str = Field(min_length=1, max_length=16000)

    @field_validator("goal")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("请输入共同研究目标")
        return value.strip()


@router.post("/spaces", status_code=201)
async def create_space(
    request: CreateSpaceRequest, user: store.User = Depends(get_current_user)
) -> dict:
    _creation_gate()
    if await store.user_llm_cred_state(user_id=user.id) == "error":
        raise HTTPException(503, "模型凭据不可用，请先检查模型配置")
    snapshot = await store.build_llm_snapshot(user_id=user.id)
    try:
        async with store.get_sessionmaker().begin() as session:
            pair = await service.create_pair(
                session, user_id=user.id, creation_key=request.creation_key, goal=request.goal
            )
            # Stable per-space identity; creating the pair, first human turn and
            # durable dispatch is one transaction, including lost-response retries.
            rid = uuid.uuid5(pair.space_id, "initial-team-run")
            if await session.get(store.Run, rid) is None:
                prompt = (
                    f"共同研究目标：{request.goal}\n"
                    "你负责首轮研究与策略分析。依据可用资料开展研究，保留证据和局限。"
                    "形成可交接成果后，通过正式交付工具交给 Single；"
                    "是否请求后续执行由你根据目标和成果决定。"
                )
                session.add(
                    store.Run(
                        id=rid,
                        user_id=user.id,
                        session_id=pair.team_session_id,
                        status="queued",
                        pipeline_id="agent_team",
                        prompt=prompt,
                        run_dir=str(run_dir_for(rid.hex)),
                        llm_snapshot_json=snapshot,
                        llm_config_id=uuid.UUID(snapshot["config_id"])
                        if snapshot.get("config_id")
                        else None,
                    )
                )
                await session.flush()
                await store.append_turn_in(
                    session,
                    session_id=pair.team_session_id,
                    run_id=rid,
                    role="user",
                    content=request.goal,
                )
                await dispatch_outbox.enqueue(
                    session,
                    run_id=rid,
                    user_id=user.id,
                    research_id=pair.team_session_id,
                    session_key=str(pair.team_session_id),
                    prompt=prompt,
                )
                await events.stage_for_space(
                    session,
                    pair.space_id,
                    type="sl.run.changed",
                    change_key=f"run:{rid}:created",
                    data={
                        "status": "queued",
                        "pipeline_id": "agent_team",
                        "started": False,
                        "finished": False,
                        "stopped": False,
                        "error_code": None,
                    },
                    invalidate=("runs", "deliveries", "interventions", "actions"),
                    source_kind="run",
                    source_id=str(rid),
                    session_id=pair.team_session_id,
                    run_id=rid,
                )
            await events.seal_changes(session)
            return {"space_id": str(pair.space_id), "initial_run_id": str(rid)}
    except CollaborationError as exc:
        raise HTTPException(409, str(exc)) from None


async def _space(session: AsyncSession, user: store.User, space_id: uuid.UUID) -> sl.SuperLinkSpace:
    try:
        return await management.owned_space(session, user.id, space_id)
    except CollaborationError as exc:
        raise HTTPException(404, str(exc)) from None


def _stream_http_error(exc: CollaborationError) -> HTTPException:
    code = str(exc)
    if code == "not_found":
        return HTTPException(404, "not_found")
    if code in {"invalid_cursor", "invalid_limit"}:
        return HTTPException(400, code)
    if code == "resync_required":
        return HTTPException(410, code)
    return HTTPException(503, "event_chain_unavailable")


class _DeadlineSend:
    """Apply a per-chunk and total-lifetime deadline to every ASGI send."""

    def __init__(self, send: Send, *, send_timeout: float, deadline: float) -> None:
        self._send = send
        self._send_timeout = send_timeout
        self._deadline = deadline
        self.started = False

    async def __call__(self, message: Message) -> None:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        await asyncio.wait_for(
            self._send(message), timeout=min(self._send_timeout, remaining)
        )
        if message["type"] == "http.response.start":
            self.started = True


class SSEStreamingResponse(StreamingResponse):
    """Close the body iterator when a send or a database read is stuck.

    ``StreamingResponse`` cannot finish its generator while an ASGI send or
    the next database read blocks, so max-age alone would leave the lease and
    the hub subscription held. The total deadline cancels the whole iteration
    (not only sends), and ``aclose`` runs the generator's ``finally`` (quota,
    hub membership, producer task).
    """

    def __init__(
        self,
        content: AsyncIterator[str],
        *,
        send_timeout: float,
        max_age: float,
        **kwargs: Any,
    ) -> None:
        super().__init__(content, **kwargs)
        self._send_timeout = send_timeout
        self._max_age = max_age

    async def stream_response(self, send: Send) -> None:
        deadline = time.monotonic() + self._max_age
        wrapped = _DeadlineSend(
            send, send_timeout=self._send_timeout, deadline=deadline
        )
        try:
            # The deadline covers the whole response iteration, including a
            # database read that never returns. Cancelling it propagates into
            # the generator and unblocks ``aclose``.
            await asyncio.wait_for(
                super().stream_response(wrapped), timeout=self._max_age
            )
        except TimeoutError:
            logger.warning("super-link SSE exceeded its maximum lifetime")
            if wrapped.started:
                # Still emit the terminal marker so a responsive server can
                # finish the response; a genuinely stuck send is abandoned.
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(
                        send(
                            {
                                "type": "http.response.body",
                                "body": b"",
                                "more_body": False,
                            }
                        ),
                        timeout=0.1,
                    )
        finally:
            aclose = getattr(self.body_iterator, "aclose", None)
            if aclose is not None:
                with contextlib.suppress(Exception):
                    await aclose()


async def _space_cursor(session: AsyncSession, space_id: uuid.UUID) -> str | None:
    head = await session.get(sl.SuperLinkEventHead, space_id)
    if head is None:
        return None
    return events.format_cursor(space_id, head.stream_epoch, head.last_seq)


@router.get("/spaces/{space_id}/diagnostics")
async def space_diagnostics(
    space_id: uuid.UUID,
    user: store.User = Depends(get_current_user),
) -> dict:
    """Owner-only, read-only view of process counters and DB notification backlog."""
    try:
        async with store.get_sessionmaker()() as session:
            await _space(session, user, space_id)
            head = await session.get(sl.SuperLinkEventHead, space_id)
            unnotified_count = 0
            oldest = None
            if head is not None:
                backlog = (
                    sl.SuperLinkEvent.space_id == space_id,
                    sl.SuperLinkEvent.stream_epoch == head.stream_epoch,
                    sl.SuperLinkEvent.notified_at.is_(None),
                )
                unnotified_count = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(sl.SuperLinkEvent)
                        .where(*backlog)
                    )
                    or 0
                )
                oldest = await session.scalar(
                    select(func.min(sl.SuperLinkEvent.recorded_at)).where(*backlog)
                )
    except SQLAlchemyError:
        raise HTTPException(503, "event_chain_unavailable") from None

    now = datetime.now(UTC)
    oldest_age = 0.0
    if oldest is not None:
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=UTC)
        oldest_age = max(0.0, (now - oldest).total_seconds())
    process = observability.snapshot()
    process["sse"]["active_for_user"] = await stream.LIMITER.count(user.id)
    process["sse"]["limit"] = get_config().super_link_sse_max_connections
    return {
        "schema_version": 1,
        "scope": "process",
        "generated_at": now.isoformat(),
        "process": process,
        "events": {
            "stream_epoch": str(head.stream_epoch) if head is not None else None,
            "head_seq": int(head.last_seq) if head is not None else 0,
            "unnotified_count": unnotified_count,
            "oldest_unnotified_age_seconds": round(oldest_age, 3),
        },
    }


@router.get("/spaces")
async def spaces(
    after: uuid.UUID | None = None,
    limit: int = Query(20, ge=1, le=50),
    user: store.User = Depends(get_current_user),
) -> dict:
    async with store.get_sessionmaker()() as session:
        query = select(sl.SuperLinkSpace).where(sl.SuperLinkSpace.user_id == user.id)
        if after:
            query = query.where(sl.SuperLinkSpace.id > after)
        rows = list(await session.scalars(query.order_by(sl.SuperLinkSpace.id).limit(limit + 1)))
        return {
            "items": [
                {
                    "space_id": str(s.id),
                    "goal": s.goal,
                    "goal_version": s.goal_version,
                    "paused": s.paused,
                    "control_state": s.control_state,
                    "control_version": s.control_version,
                }
                for s in rows[:limit]
            ],
            "next_after": str(rows[limit - 1].id) if len(rows) > limit else None,
        }


@router.get("/spaces/{space_id}")
async def space_detail(space_id: uuid.UUID, user: store.User = Depends(get_current_user)) -> dict:
    async with store.get_sessionmaker()() as session:
        space = await _space(session, user, space_id)
        used, limit = await automatic_budget(session, space)
        peers = list(
            await session.scalars(
                select(sl.SuperLinkParticipant).where(sl.SuperLinkParticipant.space_id == space_id)
            )
        )
        return {
            "space_id": str(space.id),
            "goal": space.goal,
            "goal_version": space.goal_version,
            "paused": space.paused,
            "control_state": space.control_state,
            "control_version": space.control_version,
            "can_control": not get_config().restore_mode,
            "automatic_budget": {"used": used, "limit": limit, "remaining": max(0, limit - used)},
            "participants": [
                {"participant_id": str(p.id), "session_id": str(p.session_id), "role": p.role}
                for p in peers
            ],
        }


@router.get("/spaces/{space_id}/snapshot")
async def space_snapshot(
    space_id: uuid.UUID,
    min_cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    runs_after: uuid.UUID | None = None,
    deliveries_after: uuid.UUID | None = None,
    pending_after: uuid.UUID | None = None,
    actions_after: uuid.UUID | None = None,
    user: store.User = Depends(get_current_user),
) -> dict:
    try:
        return await stream.read_snapshot(
            user_id=user.id,
            space_id=space_id,
            min_cursor=min_cursor,
            limit=limit,
            runs_after=runs_after,
            deliveries_after=deliveries_after,
            pending_after=pending_after,
            actions_after=actions_after,
        )
    except CollaborationError as exc:
        raise _stream_http_error(exc) from None
    except SQLAlchemyError:
        logger.warning("super-link snapshot read failed", exc_info=True)
        raise HTTPException(503, "event_chain_unavailable") from None


@router.get("/spaces/{space_id}/events")
async def space_events(
    space_id: uuid.UUID,
    after: str | None = None,
    user: store.User = Depends(get_current_user),
) -> StreamingResponse:
    if after is None:
        raise HTTPException(400, "invalid_cursor")
    session_ids: list[uuid.UUID] = []
    try:
        # Reject a disabled owner or a foreign space before a 200 stream; the
        # cursor read alone only checks space ownership.
        async with store.get_sessionmaker()() as session:
            await management.owned_space(session, user.id, space_id)
            session_ids = await management.participant_session_ids(session, space_id)
        # Reuse T02 cursor semantics before committing to a 200 stream.
        await events.read_events(
            user_id=user.id, space_id=space_id, after=after, limit=1
        )
    except CollaborationError as exc:
        raise _stream_http_error(exc) from None
    except SQLAlchemyError:
        logger.warning("super-link stream connect failed", exc_info=True)
        raise HTTPException(503, "event_chain_unavailable") from None
    lease = await stream.acquire_connection(user.id)
    if lease is None:
        observability.inc("sse.rejected")
        raise HTTPException(
            429, "too_many_connections", headers={"Retry-After": "5"}
        )
    cfg = get_config()
    return SSEStreamingResponse(
        stream.event_stream(
            user_id=user.id,
            space_id=space_id,
            after=after,
            lease=lease,
            session_ids=session_ids,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        background=BackgroundTask(lease.release),
        send_timeout=cfg.super_link_sse_send_timeout_seconds,
        max_age=cfg.super_link_sse_max_age_seconds,
    )


@router.get("/spaces/{space_id}/deliveries")
async def deliveries(
    space_id: uuid.UUID,
    after: uuid.UUID | None = None,
    limit: int = Query(20, ge=1, le=50),
    newest_first: bool = False,
    user: store.User = Depends(get_current_user),
) -> dict:
    async with stream.snapshot_session() as session:
        await _space(session, user, space_id)
        boundary = await _space_cursor(session, space_id)
        query = select(sl.SuperLinkMessage).where(sl.SuperLinkMessage.space_id == space_id)
        if newest_first:
            if after:
                anchor = await session.scalar(query.where(sl.SuperLinkMessage.id == after))
                if anchor is None:
                    raise HTTPException(404, "cursor_not_found")
                query = query.where(
                    stream.page_cursor(
                        session, sl.SuperLinkMessage, anchor, newest_first=True
                    )
                )
            query = query.order_by(
                *stream.page_order(session, sl.SuperLinkMessage, newest_first=True)
            )
        else:
            if after:
                query = query.where(sl.SuperLinkMessage.id > after)
            query = query.order_by(sl.SuperLinkMessage.id)
        rows = list(await session.scalars(query.limit(limit + 1)))
        return {
            "items": [await management.delivery_status(session, m) for m in rows[:limit]],
            "next_after": str(rows[limit - 1].id) if len(rows) > limit else None,
            "cursor": boundary,
        }


@router.get("/spaces/{space_id}/deliveries/{message_id}")
async def delivery_detail(
    space_id: uuid.UUID, message_id: uuid.UUID, user: store.User = Depends(get_current_user)
) -> dict:
    async with store.get_sessionmaker()() as session:
        await _space(session, user, space_id)
        message = await session.get(sl.SuperLinkMessage, message_id)
        if message is None or message.space_id != space_id:
            raise HTTPException(404, "not_found")
        return await management.delivery_status(session, message, detail=True)


@router.get("/spaces/{space_id}/runs")
async def runs(
    space_id: uuid.UUID,
    after: uuid.UUID | None = None,
    limit: int = Query(20, ge=1, le=50),
    newest_first: bool = False,
    user: store.User = Depends(get_current_user),
) -> dict:
    async with stream.snapshot_session() as session:
        await _space(session, user, space_id)
        boundary = await _space_cursor(session, space_id)
        query = (
            select(store.Run)
            .join(
                sl.SuperLinkParticipant, sl.SuperLinkParticipant.session_id == store.Run.session_id
            )
            .where(sl.SuperLinkParticipant.space_id == space_id)
        )
        if after:
            anchor = await session.scalar(query.where(store.Run.id == after))
            if anchor is None:
                raise HTTPException(404, "cursor_not_found")
            query = query.where(
                stream.page_cursor(
                    session, store.Run, anchor, newest_first=newest_first
                )
            )
        rows = list(
            await session.scalars(
                query.order_by(
                    *stream.page_order(
                        session, store.Run, newest_first=newest_first
                    )
                ).limit(limit + 1)
            )
        )
        return {
            "items": [await management.run_status(session, r.id) for r in rows[:limit]],
            "next_after": str(rows[limit - 1].id) if len(rows) > limit else None,
            "cursor": boundary,
        }


@router.get("/spaces/{space_id}/recovery-actions")
async def recovery_actions(
    space_id: uuid.UUID,
    after: uuid.UUID | None = None,
    limit: int = Query(20, ge=1, le=50),
    newest_first: bool = False,
    user: store.User = Depends(get_current_user),
) -> dict:
    async with stream.snapshot_session() as session:
        await _space(session, user, space_id)
        boundary = await _space_cursor(session, space_id)
        query = select(sl.SuperLinkRecoveryAction).where(
            sl.SuperLinkRecoveryAction.space_id == space_id
        )
        model = sl.SuperLinkRecoveryAction
        if newest_first:
            if after:
                anchor = await session.scalar(query.where(model.id == after))
                if anchor is None:
                    raise HTTPException(404, "cursor_not_found")
                query = query.where(
                    stream.page_cursor(session, model, anchor, newest_first=True)
                )
            query = query.order_by(
                *stream.page_order(session, model, newest_first=True)
            )
        else:
            if after:
                query = query.where(model.id > after)
            query = query.order_by(model.id)
        rows = list(await session.scalars(query.limit(limit + 1)))
        return {
            "items": [
                {
                    "id": str(r.id),
                    "actor_id": str(r.user_id),
                    "request": r.request_json,
                    "result": r.result_json,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows[:limit]
            ],
            "next_after": str(rows[limit - 1].id) if len(rows) > limit else None,
            "cursor": boundary,
        }


@router.post("/spaces/{space_id}/recovery")
async def recovery(
    space_id: uuid.UUID,
    request: management.RecoveryRequest,
    user: store.User = Depends(get_current_user),
) -> dict:
    try:
        return await management.recover(user.id, space_id, request)
    except CollaborationError as exc:
        raise HTTPException(404 if str(exc) == "not_found" else 409, str(exc)) from None


@router.post("/spaces/{space_id}/control")
async def space_control(
    space_id: uuid.UUID,
    request: controls.ControlRequest,
    user: store.User = Depends(get_current_user),
) -> dict:
    if request.action == "continue":
        _creation_gate()
        if await store.user_llm_cred_state(user_id=user.id) == "error":
            raise HTTPException(503, "模型凭据不可用")
    try:
        return await controls.control(user.id, space_id, request)
    except CollaborationError as exc:
        raise HTTPException(404 if str(exc) == "not_found" else 409, str(exc)) from None


@router.get("/spaces/{space_id}/interventions")
async def interventions(
    space_id: uuid.UUID,
    pending_after: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    user: store.User = Depends(get_current_user),
) -> dict:
    async with stream.snapshot_session() as session:
        await _space(session, user, space_id)
        # Read the boundary first: every list read below must not be newer
        # than the cursor returned with it.
        boundary = await _space_cursor(session, space_id)
        base = (
            select(store.ControlRecord)
            .join(store.Run, store.Run.id == store.ControlRecord.run_id)
            .join(
                sl.SuperLinkParticipant,
                sl.SuperLinkParticipant.session_id == store.Run.session_id,
            )
            .where(sl.SuperLinkParticipant.space_id == space_id)
        )
        pending_query = base.where(
            store.ControlRecord.kind == "approval",
            store.ControlRecord.status == "pending",
            store.Run.status == "running",
        )
        pending_total = (
            await session.scalar(
                select(func.count()).select_from(pending_query.subquery())
            )
            or 0
        )
        if pending_after is not None:
            anchor = await session.scalar(
                base.where(
                    store.ControlRecord.id == pending_after,
                    store.ControlRecord.kind == "approval",
                )
            )
            if anchor is None:
                raise HTTPException(400, "invalid_cursor")
            pending_query = pending_query.where(
                stream.page_cursor(
                    session, store.ControlRecord, anchor, newest_first=False
                )
            )
        pending_rows = list(
            await session.scalars(
                pending_query.order_by(
                    *stream.page_order(
                        session, store.ControlRecord, newest_first=False
                    )
                ).limit(limit + 1)
            )
        )
        pending_next = (
            str(pending_rows[limit - 1].id)
            if len(pending_rows) > limit
            else None
        )
        recent = list(
            await session.scalars(
                base.order_by(store.ControlRecord.created_at.desc()).limit(100)
            )
        )
        active = await controls.active_runs(session, space_id)
        return {
            "pending": [store.control_to_dict(r) for r in pending_rows[:limit]],
            "pending_total": int(pending_total),
            "pending_next_after": pending_next,
            "recent": [store.control_to_dict(r) for r in recent],
            "active_runs": [await management.run_status(session, r.id) for r in active],
            "cursor": boundary,
        }


async def _controlled_run(
    session: AsyncSession,
    user: store.User,
    space_id: uuid.UUID,
    run_id: uuid.UUID,
) -> None:
    if get_config().restore_mode:
        raise HTTPException(409, "control_unavailable")
    space = await _space(session, user, space_id)
    if space.control_state in {"stopping", "stopped"}:
        raise HTTPException(409, "space_stopped")
    run = await session.scalar(
        select(store.Run)
        .join(
            sl.SuperLinkParticipant,
            sl.SuperLinkParticipant.session_id == store.Run.session_id,
        )
        .where(store.Run.id == run_id, sl.SuperLinkParticipant.space_id == space_id)
    )
    if run is None:
        raise HTTPException(404, "not_found")
    if run.status != "running":
        raise HTTPException(409, "run_not_running")


@router.post("/spaces/{space_id}/runs/{run_id}/approve")
async def approve(
    space_id: uuid.UUID,
    run_id: uuid.UUID,
    request: ApproveRequest,
    user: store.User = Depends(get_current_user),
) -> dict:
    async with store.get_sessionmaker()() as session:
        await _controlled_run(session, user, space_id, run_id)
        record = await session.scalar(
            select(store.ControlRecord).where(
                store.ControlRecord.run_id == run_id,
                store.ControlRecord.kind == "approval",
                store.ControlRecord.external_id == request.approval_id,
                store.ControlRecord.status == "pending",
            )
        )
        if record is None:
            raise HTTPException(409, "approval_not_pending")
    return await run_approve(run_id.hex, request, user)


@router.post("/spaces/{space_id}/runs/{run_id}/steer")
async def steer(
    space_id: uuid.UUID,
    run_id: uuid.UUID,
    request: SteerRequest,
    user: store.User = Depends(get_current_user),
) -> dict:
    async with store.get_sessionmaker()() as session:
        await _controlled_run(session, user, space_id, run_id)
    return await run_steer(run_id.hex, request, user)
