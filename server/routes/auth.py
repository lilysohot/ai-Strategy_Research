"""Authentication routes (T2.2).

    POST /api/auth/register   {username, password}           → 201
    POST /api/auth/login      {username, password}           → {access_token}
    GET  /api/auth/me                                        → current user
    POST /api/auth/logout                                    → revoke token
    POST /api/auth/password                                  → change password

Security decisions that are easy to get wrong and are deliberate here:

* **Login never reveals whether the username exists.** A wrong username and a
  wrong password return the identical 401 body and take a comparable amount of
  time (both run argon2 against a real hash) — otherwise the endpoint is a
  username-enumeration oracle.
* **Failed logins are throttled per username** (5 / 10 min, FR-1.3) and the
  counter is incremented on *any* failure, including "no such user", so the
  throttle cannot be used to probe which names are registered.
* **Every sensitive action writes an audit record** (register, login, failed
  login, logout, password change). Audit failures are logged but never turn a
  successful operation into an error.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from server.deps import _client_ip, get_current_user
from server.security import (
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    login_throttle,
    revoke_token,
    validate_password_strength,
    verify_password,
)
from server.store import (
    User,
    UsernameTaken,
    create_user,
    get_user_by_username,
    update_password_hash,
    write_audit_log,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# A real argon2id hash of a value nobody can supply. Verifying against it on
# "no such user" keeps the response time comparable to a genuine failed login,
# which is what stops timing-based username enumeration.
_DUMMY_HASH: str | None = None


async def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = await hash_password("unused-placeholder-for-timing-parity")
    return _DUMMY_HASH


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    id: str
    username: str
    status: str


def _user_response(user: User) -> UserResponse:
    return UserResponse(id=str(user.id), username=user.username, status=user.status)


async def _audit(action: str, *, user: User | None, request: Request,
                 detail: dict | None = None) -> None:
    """Write an audit record; never let it break the response.

    Awaited rather than fire-and-forget on purpose. A background task that
    outlives the request can be cancelled or lost when the loop winds down, and
    a dropped audit row is a compliance gap (FR-4 留痕), not a cosmetic one. The
    cost is one extra INSERT on login, which is negligible next to argon2.

    Failures are logged and swallowed: an audit-write error must not turn a
    successful login into a 500.
    """
    try:
        await write_audit_log(
            action=action,
            user_id=user.id if user else None,
            detail=detail,
            ip=_client_ip(request),
        )
    except Exception:
        logger.exception("audit_log write failed for action=%s", action)


@router.post("/register", status_code=status.HTTP_201_CREATED,
             response_model=UserResponse)
async def register(body: RegisterRequest, request: Request) -> UserResponse:
    """Create an account (FR-1.1).

    Password strength is enforced before hashing; storage is argon2id via
    :func:`server.security.hash_password`.
    """
    username = body.username.strip()
    if not username.isprintable() or "/" in username:
        raise HTTPException(status_code=400, detail="用户名含非法字符")

    strength_error = validate_password_strength(body.password)
    if strength_error:
        raise HTTPException(status_code=400, detail=strength_error)

    password_hash = await hash_password(body.password)
    try:
        user = await create_user(username=username, password_hash=password_hash)
    except UsernameTaken:
        # Registration must report the collision — there is no way to let the
        # user pick another name otherwise. Enumeration risk is accepted here
        # (unlike login) because usability demands it.
        raise HTTPException(status_code=409, detail="用户名已被占用") from None

    await _audit("register", user=user, request=request, detail={"username": username})
    return _user_response(user)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request) -> TokenResponse:
    """Authenticate and issue a 24h JWT (FR-1.2), throttled (FR-1.3)."""
    username = body.username.strip()

    # Throttle first: a locked account must be rejected before any password
    # work, and before we confirm whether it even exists.
    if login_throttle.is_locked(username):
        remaining = int(login_throttle.lockout_remaining_s(username))
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"登录失败次数过多，请 {max(1, remaining)} 秒后重试",
        )

    user = await get_user_by_username(username)

    ok = False
    if user is not None and user.status == "active":
        ok = await verify_password(body.password, user.password_hash)
    else:
        # Burn one argon2 verification against a dummy hash so a missing or
        # disabled account costs the same as a wrong password.
        await verify_password(body.password, await _dummy_hash())

    if not ok:
        locked = login_throttle.record_failure(username)
        await _audit(
            "login_failed",
            user=user,
            request=request,
            detail={"username": username, "locked": locked},
        )
        if locked:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="登录失败次数过多，账号已锁定 10 分钟",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    assert user is not None  # guaranteed by `ok`
    login_throttle.record_success(username)
    token = create_access_token(user.id)
    await _audit("login", user=user, request=request)
    return TokenResponse(access_token=token, expires_in=24 * 60 * 60)


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)) -> UserResponse:
    """Return the current user (FR-1.2)."""
    return _user_response(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    user: User = Depends(get_current_user),
) -> None:
    """Revoke the presented token (FR-1.4).

    Stateless JWTs cannot be invalidated server-side except by denylisting, so
    logout adds the token's ``jti`` to a short-lived denylist. The client is
    still expected to drop the token.
    """
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if token:
        try:
            decode_access_token(token)  # validate before trusting its claims
            revoke_token(token)
        except TokenError:
            pass
    await _audit("logout", user=user, request=request)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChangeRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> None:
    """Change the current user's password (FR-1.4)."""
    if not await verify_password(body.old_password, user.password_hash):
        await _audit("password_change_failed", user=user, request=request)
        raise HTTPException(status_code=400, detail="原密码不正确")

    strength_error = validate_password_strength(body.new_password)
    if strength_error:
        raise HTTPException(status_code=400, detail=strength_error)

    new_hash = await hash_password(body.new_password)
    await update_password_hash(user.id, new_hash)
    await _audit("password_changed", user=user, request=request)
