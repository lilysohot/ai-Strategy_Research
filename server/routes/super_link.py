"""Opt-in owner-only diagnostics and recovery. No force-approval or execution API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from server.super_link import controls, management, service
from server.super_link import models as sl
from server.super_link.contracts import CollaborationError
from server.super_link.coordination import automatic_budget


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
            return {"space_id": str(pair.space_id), "initial_run_id": str(rid)}
    except CollaborationError as exc:
        raise HTTPException(409, str(exc)) from None


async def _space(session: AsyncSession, user: store.User, space_id: uuid.UUID) -> sl.SuperLinkSpace:
    try:
        return await management.owned_space(session, user.id, space_id)
    except CollaborationError as exc:
        raise HTTPException(404, str(exc)) from None


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


@router.get("/spaces/{space_id}/deliveries")
async def deliveries(
    space_id: uuid.UUID,
    after: uuid.UUID | None = None,
    limit: int = Query(20, ge=1, le=50),
    newest_first: bool = False,
    user: store.User = Depends(get_current_user),
) -> dict:
    async with store.get_sessionmaker()() as session:
        await _space(session, user, space_id)
        query = select(sl.SuperLinkMessage).where(sl.SuperLinkMessage.space_id == space_id)
        if newest_first:
            if after:
                cursor = await session.scalar(query.where(sl.SuperLinkMessage.id == after))
                if cursor is None:
                    raise HTTPException(404, "cursor_not_found")
                query = query.where(
                    (sl.SuperLinkMessage.created_at < cursor.created_at)
                    | (
                        (sl.SuperLinkMessage.created_at == cursor.created_at)
                        & (sl.SuperLinkMessage.id < cursor.id)
                    )
                )
            query = query.order_by(
                sl.SuperLinkMessage.created_at.desc(), sl.SuperLinkMessage.id.desc()
            )
        else:
            if after:
                query = query.where(sl.SuperLinkMessage.id > after)
            query = query.order_by(sl.SuperLinkMessage.id)
        rows = list(await session.scalars(query.limit(limit + 1)))
        return {
            "items": [await management.delivery_status(session, m) for m in rows[:limit]],
            "next_after": str(rows[limit - 1].id) if len(rows) > limit else None,
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
    async with store.get_sessionmaker()() as session:
        await _space(session, user, space_id)
        query = (
            select(store.Run)
            .join(
                sl.SuperLinkParticipant, sl.SuperLinkParticipant.session_id == store.Run.session_id
            )
            .where(sl.SuperLinkParticipant.space_id == space_id)
        )
        if after:
            cursor = await session.scalar(query.where(store.Run.id == after))
            if cursor is None:
                raise HTTPException(404, "cursor_not_found")
            query = query.where(
                (
                    (store.Run.created_at < cursor.created_at)
                    | ((store.Run.created_at == cursor.created_at) & (store.Run.id < cursor.id))
                )
                if newest_first
                else (
                    (store.Run.created_at > cursor.created_at)
                    | ((store.Run.created_at == cursor.created_at) & (store.Run.id > cursor.id))
                )
            )
        ordering = (
            (store.Run.created_at.desc(), store.Run.id.desc())
            if newest_first
            else (store.Run.created_at, store.Run.id)
        )
        rows = list(await session.scalars(query.order_by(*ordering).limit(limit + 1)))
        return {
            "items": [await management.run_status(session, r.id) for r in rows[:limit]],
            "next_after": str(rows[limit - 1].id) if len(rows) > limit else None,
        }


@router.get("/spaces/{space_id}/recovery-actions")
async def recovery_actions(
    space_id: uuid.UUID,
    after: uuid.UUID | None = None,
    limit: int = Query(20, ge=1, le=50),
    newest_first: bool = False,
    user: store.User = Depends(get_current_user),
) -> dict:
    async with store.get_sessionmaker()() as session:
        await _space(session, user, space_id)
        query = select(sl.SuperLinkRecoveryAction).where(
            sl.SuperLinkRecoveryAction.space_id == space_id
        )
        model = sl.SuperLinkRecoveryAction
        if newest_first:
            if after:
                cursor = await session.scalar(query.where(model.id == after))
                if cursor is None:
                    raise HTTPException(404, "cursor_not_found")
                query = query.where(
                    (model.created_at < cursor.created_at)
                    | ((model.created_at == cursor.created_at) & (model.id < cursor.id))
                )
            query = query.order_by(model.created_at.desc(), model.id.desc())
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
async def interventions(space_id: uuid.UUID, user: store.User = Depends(get_current_user)) -> dict:
    async with store.get_sessionmaker()() as session:
        await _space(session, user, space_id)
        query = (
            select(store.ControlRecord)
            .join(store.Run, store.Run.id == store.ControlRecord.run_id)
            .join(
                sl.SuperLinkParticipant, sl.SuperLinkParticipant.session_id == store.Run.session_id
            )
            .where(sl.SuperLinkParticipant.space_id == space_id)
        )
        pending = list(
            await session.scalars(
                query.where(
                    store.ControlRecord.kind == "approval",
                    store.ControlRecord.status == "pending",
                    store.Run.status == "running",
                ).order_by(store.ControlRecord.created_at)
            )
        )
        recent = list(
            await session.scalars(query.order_by(store.ControlRecord.created_at.desc()).limit(100))
        )
        active = await controls.active_runs(session, space_id)
        return {
            "pending": [store.control_to_dict(r) for r in pending],
            "recent": [store.control_to_dict(r) for r in recent],
            "active_runs": [await management.run_status(session, r.id) for r in active],
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
