"""FastAPI dependency injection for the web platform.

The centrepiece is :func:`get_current_user`: a single dependency that every
authenticated route declares, so "who is calling" is resolved in exactly one
place. Routes never parse the ``Authorization`` header themselves — a route that
forgets to declare the dependency is a route that is public, which is visible at
a glance during review.

Failure policy: anything wrong with the token yields 401 with one generic
message. The caller cannot distinguish "expired" from "malformed" from "revoked"
from "user deleted", because each of those distinctions is a small oracle for an
attacker probing accounts.
"""

from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from server.security import TokenError, decode_access_token
from server.store import User, get_user_by_id

# auto_error=False: we raise our own 401 with a uniform shape and a
# WWW-Authenticate challenge, rather than FastAPI's default two-variant error.
_bearer = HTTPBearer(auto_error=False, description="JWT obtained from /api/auth/login")


def _client_ip(request: Request) -> str | None:
    """Best-effort client IP for audit records.

    ``X-Forwarded-For`` is only trusted as a hint: behind Caddy the header is
    attacker-controllable unless the proxy overwrites it, so it is recorded for
    diagnostics rather than used for any security decision.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    """Resolve the caller's user record from the bearer token.

    Raises 401 for every failure mode. Declaring this dependency is what makes a
    route authenticated.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证凭据",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id: uuid.UUID = decode_access_token(credentials.credentials)
    except TokenError:
        # Deliberately one message for expired / tampered / revoked / malformed.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证凭据无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    user = await get_user_by_id(user_id)
    if user is None or user.status != "active":
        # A validly-signed token for a deleted or disabled account must not
        # grant access, and must not confirm the account ever existed.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证凭据无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_current_user_id(user: User = Depends(get_current_user)) -> uuid.UUID:
    """Convenience variant for routes that only need the id."""
    return user.id
