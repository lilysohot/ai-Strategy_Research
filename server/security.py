"""Authentication primitives: password hashing, JWT issuance, login throttling.

Covers FR-1.1 (argon2id hashing), FR-1.2 (JWT HS256, 24h) and FR-1.3 (5 failed
attempts / 10 minutes lockout). Deliberately dependency-light and synchronous at
its core, so it can be unit-tested without a database or an event loop.

Two design notes that matter under load:

* **argon2 is CPU-bound.** ``PasswordHasher`` deliberately costs ~50-100ms per
  call, which would stall the event loop for every concurrent login. All hashing
  and verification therefore runs in a worker thread via ``asyncio.to_thread``
  — see :func:`hash_password` / :func:`verify_password`.
* **Throttling state is in-process.** The platform is a single API instance
  (tech-stack.md §12), so an in-memory store is correct and dependency-free. The
  :class:`LoginThrottle` interface is kept narrow so a Redis/Postgres-backed
  implementation can replace it without touching call sites if the platform ever
  runs multi-instance.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

# ── Password hashing (FR-1.1) ─────────────────────────────────
# argon2id with the library's OWASP-recommended defaults (time_cost=3,
# memory_cost=64MiB, parallelism=4) — resistant to both GPU cracking and
# side-channel attacks. passlib is deliberately not used: it is unmaintained.
_hasher = PasswordHasher()


def _hash_sync(password: str) -> str:
    return _hasher.hash(password)


def _verify_sync(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        # Every failure mode is "wrong password" to the caller; distinguishing
        # them would leak whether an account's hash is malformed.
        return False


async def hash_password(password: str) -> str:
    """Hash ``password`` with argon2id, off the event loop."""
    return await asyncio.to_thread(_hash_sync, password)


async def verify_password(password: str, password_hash: str) -> bool:
    """Verify ``password`` against a stored hash, off the event loop."""
    return await asyncio.to_thread(_verify_sync, password, password_hash)


def needs_rehash(password_hash: str) -> bool:
    """True when a stored hash should be upgraded to current parameters."""
    return _hasher.check_needs_rehash(password_hash)


def validate_password_strength(password: str) -> str | None:
    """Return an error message if ``password`` fails FR-1.1, else ``None``.

    FR-1.1: at least 8 characters, containing both letters and digits.
    """
    if len(password) < 8:
        return "密码至少 8 位"
    if not any(c.isalpha() for c in password):
        return "密码需包含字母"
    if not any(c.isdigit() for c in password):
        return "密码需包含数字"
    return None


# ── JWT (FR-1.2) ───────────────────────────────────────────────
ALGORITHM = "HS256"
ACCESS_TOKEN_TTL_S = 24 * 60 * 60  # 24h


class TokenError(Exception):
    """Raised when a token is missing, malformed, expired or revoked."""


def _secret() -> str:
    from server.config import get_config

    return get_config().master_key


def create_access_token(user_id: uuid.UUID | str, *, ttl_s: int = ACCESS_TOKEN_TTL_S) -> str:
    """Issue an HS256 JWT for ``user_id`` valid for ``ttl_s`` seconds.

    Every token carries a unique ``jti``. Without it, two tokens issued for the
    same user within the same second are byte-identical (``iat`` has 1s
    resolution), so revoking one would revoke the other — the denylist had no
    way to tell them apart.
    """
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + ttl_s,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID:
    """Validate ``token`` and return the subject's user id.

    Raises :class:`TokenError` for any failure — callers must not distinguish
    expired from malformed, or they leak token state to an attacker.
    """
    try:
        payload = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise TokenError("invalid or expired token") from exc
    sub = payload.get("sub")
    if not sub:
        raise TokenError("token has no subject")
    if _is_revoked(token):
        raise TokenError("token revoked")
    try:
        return uuid.UUID(str(sub))
    except ValueError as exc:
        raise TokenError("token subject is not a user id") from exc


# ── Logout / token revocation (FR-1.4, optional short denylist) ──
# A denylist keyed by token id keeps logout effective without server-side
# sessions. Entries are short-lived: they only need to outlive the token's own
# expiry, which is bounded by ACCESS_TOKEN_TTL_S.
_revoked: dict[str, float] = {}


def _jti_of(token: str) -> str | None:
    """Return the token's ``jti``, or None if it is unusable.

    The denylist is keyed by ``jti`` rather than by a digest of the whole token:
    two tokens for the same user issued within the same second are byte-identical
    (``iat`` is second-resolution), so a whole-token key cannot distinguish them
    and revoking one would revoke both.
    """
    try:
        payload = jwt.decode(
            token, _secret(), algorithms=[ALGORITHM],
            options={"verify_exp": False, "verify_signature": True},
        )
    except jwt.PyJWTError:
        return None
    jti = payload.get("jti")
    return str(jti) if jti else None


def _is_revoked(token: str) -> bool:
    jti = _jti_of(token)
    if not jti:
        return False
    expires = _revoked.get(jti)
    if expires is None:
        return False
    if expires <= time.time():
        _revoked.pop(jti, None)
        return False
    return True


def revoke_token(token: str) -> None:
    """Denylist ``token`` until its natural expiry (client-side logout).

    Only the ``jti`` is retained, never the token itself: a leaked denylist must
    not hand an attacker usable credentials.
    """
    try:
        payload = jwt.decode(
            token, _secret(), algorithms=[ALGORITHM],
            options={"verify_exp": False},
        )
        exp = float(payload.get("exp", 0))
        jti = payload.get("jti")
    except jwt.PyJWTError:
        return
    if not jti:
        return
    ttl = max(0.0, exp - time.time())
    if ttl > 0:
        _revoked[str(jti)] = time.time() + ttl


# ── Login throttling (FR-1.3) ──────────────────────────────────
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_WINDOW_S = 10 * 60  # 10 minutes


@dataclass
class _AttemptRecord:
    failures: int = 0
    first_failure_at: float = 0.0
    locked_until: float = 0.0


@dataclass
class LoginThrottle:
    """In-process failed-login counter with a sliding lockout window.

    ``MAX_FAILED_ATTEMPTS`` failures inside ``LOCKOUT_WINDOW_S`` lock the
    account for the remainder of the window. A successful login clears the
    counter. Records are pruned lazily so a sweep of usernames cannot grow the
    map without bound.
    """

    max_attempts: int = MAX_FAILED_ATTEMPTS
    window_s: float = LOCKOUT_WINDOW_S
    _records: dict[str, _AttemptRecord] = field(default_factory=dict)

    def _prune(self, now: float) -> None:
        stale = [
            key for key, rec in self._records.items()
            if rec.locked_until <= now and rec.first_failure_at + self.window_s <= now
        ]
        for key in stale:
            self._records.pop(key, None)

    def is_locked(self, username: str) -> bool:
        now = time.time()
        self._prune(now)
        rec = self._records.get(username)
        return bool(rec and rec.locked_until > now)

    def lockout_remaining_s(self, username: str) -> float:
        now = time.time()
        rec = self._records.get(username)
        if not rec or rec.locked_until <= now:
            return 0.0
        return rec.locked_until - now

    def record_failure(self, username: str) -> bool:
        """Record a failed attempt. Returns True when the account is now locked."""
        now = time.time()
        rec = self._records.setdefault(username, _AttemptRecord())
        # A fresh window starts if the previous failures have aged out.
        if rec.first_failure_at + self.window_s <= now:
            rec.failures = 0
            rec.first_failure_at = now
        rec.failures += 1
        if rec.failures >= self.max_attempts:
            rec.locked_until = now + self.window_s
            return True
        return False

    def record_success(self, username: str) -> None:
        self._records.pop(username, None)


# Module-level throttle shared by the auth routes.
login_throttle = LoginThrottle()
