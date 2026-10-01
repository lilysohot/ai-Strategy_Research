"""LLM config routes (F07-KEY-2).

The store layer has always had the full CRUD (``update_llm_config`` re-encrypts
a new ``api_key`` with the *current* master key and enforces row ownership), but
none of it was exposed over HTTP — so a lost/rotated ``SERVER_MASTER_KEY`` left
exactly one recovery path: direct database surgery. This router closes that gap
with the minimal surface the recovery story needs: a PATCH endpoint that can
reset the key (and optionally the other fields), plus a masked read-back.

Scope note: list/create/delete endpoints are deliberately NOT added here —
KEY-2 is about the recovery path, not a full management UI. The store functions
exist and wiring them later is additive.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.deps import get_current_user
from server.store import (
    ConfigNotFoundError,
    get_llm_config,
    update_llm_config,
)
from server.store import (
    User as UserModel,
)

router = APIRouter(prefix="/api/llm-configs", tags=["llm-configs"])


class LLMConfigPatch(BaseModel):
    """Patch payload. ``api_key`` is write-only: accepted, never echoed."""

    name: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    is_default: bool | None = None


@router.patch("/{config_id}")
async def patch_llm_config(
    config_id: uuid.UUID,
    patch: LLMConfigPatch,
    user: UserModel = Depends(get_current_user),
) -> dict:
    """Patch the caller's own config; an ``api_key`` resets the ciphertext.

    Ownership is enforced inside ``update_llm_config`` (a foreign or missing
    config raises :class:`ConfigNotFoundError`, mapped to 404 — "not mine" and
    "does not exist" read the same, so ids stay unguessable). The response is
    the masked view; the plaintext key never leaves the process.
    """
    try:
        return await update_llm_config(
            user_id=user.id,
            config_id=config_id,
            name=patch.name,
            base_url=patch.base_url,
            model=patch.model,
            api_key=patch.api_key,
            is_default=patch.is_default,
        )
    except ConfigNotFoundError:
        raise HTTPException(status_code=404, detail="配置不存在") from None


@router.get("/{config_id}")
async def get_llm_config_view(
    config_id: uuid.UUID,
    user: UserModel = Depends(get_current_user),
) -> dict:
    """Read back one config in masked form — lets a client verify a reset."""
    try:
        return await get_llm_config(user_id=user.id, config_id=config_id)
    except ConfigNotFoundError:
        raise HTTPException(status_code=404, detail="配置不存在") from None
