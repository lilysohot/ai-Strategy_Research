"""Session + turn query routes (T2.7).

Exposes the conversation-thread surface the web UI needs:

  POST /api/sessions            create a session (optional title / first message)
  GET  /api/sessions            list the caller's non-deleted sessions
  GET  /api/sessions/{id}       session detail (404 if not owned by caller)
  GET  /api/sessions/{id}/turns chronological turns of a session
  DELETE /api/sessions/{id}     soft-delete (404 if not owned by caller)

Every route declares ``get_current_user`` so ownership is enforced in exactly one
place; a missing dependency means the route is public, which is visible at review
time. Non-owned or deleted sessions read as 404 so an attacker cannot distinguish
"exists but not yours" from "never existed" (anti-IDOR oracle).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from server.deps import get_current_user
from server.store import (
    SessionNotFoundError,
    append_turn,
    create_session,
    delete_session,
    derive_title,
    get_session,
    list_sessions,
    list_turns,
)
from server.store import User as UserModel

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class CreateSessionRequest:
    """Body-less-ish request: title optional; first_message optional.

    We use a plain class rather than a pydantic model to keep the contract
    explicit and avoid surprising extra-field behaviour.
    """

    def __init__(
        self, title: str | None = None, first_message: str | None = None
    ) -> None:
        self.title = title
        self.first_message = first_message


def _parse_create(body: dict[str, Any]) -> CreateSessionRequest:
    return CreateSessionRequest(
        title=(body.get("title") or None),
        first_message=(body.get("first_message") or None),
    )


def _session_view(s: Any) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "title": s.title,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _turn_view(t: Any) -> dict[str, Any]:
    return {
        "seq": t.seq,
        "role": t.role,
        "content": t.content,
        "run_id": str(t.run_id) if t.run_id else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@router.post("", status_code=201)
async def create_session_route(
    body: dict[str, Any], user: UserModel = Depends(get_current_user)
) -> dict[str, Any]:
    req = _parse_create(body)
    title = req.title
    # Derive the title from the first message when the client didn't supply one.
    if not title and req.first_message:
        title = derive_title(req.first_message)
    session = await create_session(user_id=user.id, title=title)
    # If a first message was provided, seed the conversation with a user turn so
    # the history renderer (T2.6) and the title derivation have something to work
    # from on the next run.
    if req.first_message:
        await append_turn(
            session_id=session.id, role="user", content=req.first_message
        )
    return _session_view(session)


@router.get("")
async def list_sessions_route(
    user: UserModel = Depends(get_current_user),
) -> dict[str, Any]:
    rows = await list_sessions(user_id=user.id)
    return {"sessions": [_session_view(s) for s in rows]}


@router.get("/{session_id}")
async def get_session_route(
    session_id: str, user: UserModel = Depends(get_current_user)
) -> dict[str, Any]:
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在"
        ) from None
    session = await get_session(session_id=sid, user_id=user.id)
    if session is None:
        # Uniform 404: never reveal that the id exists but belongs to someone else.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在"
        ) from None
    return _session_view(session)


@router.get("/{session_id}/turns")
async def get_turns_route(
    session_id: str, user: UserModel = Depends(get_current_user)
) -> dict[str, Any]:
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在"
        ) from None
    # Ownership is enforced by get_session (404 on mismatch); turns are worthless
    # without a session the caller owns.
    session = await get_session(session_id=sid, user_id=user.id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在"
        ) from None
    rows = await list_turns(session_id=sid)
    return {"turns": [_turn_view(t) for t in rows]}


@router.delete("/{session_id}", status_code=204)
async def delete_session_route(
    session_id: str, user: UserModel = Depends(get_current_user)
) -> None:
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在"
        ) from None
    try:
        await delete_session(session_id=sid, user_id=user.id)
    except SessionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在"
        ) from None
