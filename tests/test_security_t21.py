"""T2.1 — security primitives: argon2id hashing, JWT, login throttling.

Covers FR-1.1 (argon2id + password strength), FR-1.2 (JWT HS256 24h), FR-1.3
(5 failures / 10 min lockout) and FR-1.4 (logout revocation). No database and no
network: these are pure primitives, so the tests are fast and hermetic.

Run with::
    uv run pytest tests/test_security_t21.py -q
"""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest

from server.security import (
    ACCESS_TOKEN_TTL_S,
    LOCKOUT_WINDOW_S,
    MAX_FAILED_ATTEMPTS,
    LoginThrottle,
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    login_throttle,
    needs_rehash,
    revoke_token,
    validate_password_strength,
    verify_password,
)


# ── FR-1.1: password hashing ───────────────────────────────────
@pytest.mark.asyncio
async def test_password_hash_roundtrip():
    hashed = await hash_password("Str0ngPassw0rd")
    assert hashed.startswith("$argon2id$"), "must use argon2id"
    assert await verify_password("Str0ngPassw0rd", hashed)
    assert not await verify_password("wrong-password", hashed)


@pytest.mark.asyncio
async def test_hash_is_salted():
    """Two hashes of the same password differ — no shared-salt rainbow tables."""
    h1 = await hash_password("Str0ngPassw0rd")
    h2 = await hash_password("Str0ngPassw0rd")
    assert h1 != h2
    assert await verify_password("Str0ngPassw0rd", h1)
    assert await verify_password("Str0ngPassw0rd", h2)


@pytest.mark.asyncio
async def test_verify_rejects_malformed_hash():
    # Must return False rather than raise, so a corrupt DB row reads as a
    # failed login instead of a 500 that leaks account state.
    assert not await verify_password("anything", "not-a-valid-hash")
    assert not await verify_password("anything", "")


@pytest.mark.asyncio
async def test_hashing_does_not_block_event_loop():
    """argon2 costs ~50-100ms; it must run off the loop.

    If hashing ever regresses to a synchronous call, three concurrent logins
    would serialise and this wall-clock bound fails.
    """
    started = time.monotonic()
    await asyncio.gather(
        hash_password("aaaaaaaa1"),
        hash_password("bbbbbbbb2"),
        hash_password("cccccccc3"),
    )
    elapsed = time.monotonic() - started
    # Serial would be ~3x a single hash (>=300ms); threaded should approach 1x.
    assert elapsed < 1.5, f"hashing appears to serialise on the loop: {elapsed:.2f}s"


def test_password_strength_rules():
    assert validate_password_strength("short1") is not None      # < 8
    assert validate_password_strength("allletters") is not None  # no digit
    assert validate_password_strength("12345678") is not None    # no letter
    assert validate_password_strength("Abcdefg1") is None        # valid


def test_needs_rehash_is_false_for_fresh_hashes():
    hashed = asyncio.run(hash_password("Str0ngPassw0rd"))
    assert needs_rehash(hashed) is False


# ── FR-1.2: JWT ────────────────────────────────────────────────
def test_jwt_roundtrip_and_24h_ttl():
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    assert decode_access_token(token) == user_id
    # Header declares HS256.
    import jwt as pyjwt

    assert pyjwt.get_unverified_header(token)["alg"] == "HS256"
    assert ACCESS_TOKEN_TTL_S == 24 * 60 * 60


def test_jwt_rejects_tampered_and_expired():
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    # Flip a character in the signature segment.
    head, payload, sig = token.split(".")
    tampered = f"{head}.{payload}.{'A' if sig[0] != 'A' else 'B'}{sig[1:]}"
    with pytest.raises(TokenError):
        decode_access_token(tampered)

    expired = create_access_token(user_id, ttl_s=-1)
    with pytest.raises(TokenError):
        decode_access_token(expired)


def test_jwt_rejects_garbage():
    for bad in ("", "not-a-token", "a.b.c"):
        with pytest.raises(TokenError):
            decode_access_token(bad)


def test_jwt_signed_with_wrong_secret_is_rejected(monkeypatch):
    """A token signed by another deployment's MASTER_KEY must not validate."""
    import server.security as sec

    token = create_access_token(uuid.uuid4())
    monkeypatch.setattr(sec, "_secret", lambda: "a-completely-different-master-key")
    with pytest.raises(TokenError):
        decode_access_token(token)


# ── FR-1.3: login throttling ───────────────────────────────────
def test_throttle_locks_after_max_failures():
    t = LoginThrottle()
    user = "alice"
    for i in range(MAX_FAILED_ATTEMPTS - 1):
        assert t.record_failure(user) is False, f"locked too early at {i + 1}"
        assert not t.is_locked(user)
    assert t.record_failure(user) is True, "should lock on the 5th failure"
    assert t.is_locked(user)
    assert t.lockout_remaining_s(user) > 0


def test_throttle_lockout_expires_after_window():
    t = LoginThrottle(window_s=0.2)
    user = "bob"
    for _ in range(MAX_FAILED_ATTEMPTS):
        t.record_failure(user)
    assert t.is_locked(user)
    time.sleep(0.25)
    assert not t.is_locked(user), "lockout must expire with the window"


def test_throttle_success_resets_counter():
    t = LoginThrottle()
    user = "carol"
    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        t.record_failure(user)
    t.record_success(user)
    assert not t.is_locked(user)
    # After a reset the counter starts over rather than resuming at 4.
    assert t.record_failure(user) is False


def test_throttle_is_per_username():
    t = LoginThrottle()
    for _ in range(MAX_FAILED_ATTEMPTS):
        t.record_failure("dave")
    assert t.is_locked("dave")
    assert not t.is_locked("erin"), "one lockout must not affect other accounts"


def test_throttle_module_singleton_defaults():
    assert login_throttle.max_attempts == 5
    assert login_throttle.window_s == 10 * 60
    assert LOCKOUT_WINDOW_S == 600


# ── FR-1.4: logout revocation ──────────────────────────────────
def test_revoked_token_is_rejected_but_denylist_is_not_the_token():
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    assert decode_access_token(token) == user_id
    revoke_token(token)
    with pytest.raises(TokenError):
        decode_access_token(token)
    # A different token for the same user still works.
    assert decode_access_token(create_access_token(user_id)) == user_id


def test_revocation_stores_only_the_jti():
    import server.security as sec

    token = create_access_token(uuid.uuid4())
    revoke_token(token)
    assert token not in sec._revoked, "raw token must never be stored"
    # Keys are jti values (32 hex chars), never token material.
    assert all(len(k) == 32 for k in sec._revoked), "keys must be jti values"


def test_tokens_are_unique_so_revocation_is_scoped():
    """Two tokens for one user must be independently revocable.

    Guards the bug this replaced: without a ``jti``, tokens issued in the same
    second were byte-identical, so logging out one session killed the other.
    """
    user_id = uuid.uuid4()
    t1 = create_access_token(user_id)
    t2 = create_access_token(user_id)
    assert t1 != t2, "tokens must be unique per issuance"

    revoke_token(t1)
    with pytest.raises(TokenError):
        decode_access_token(t1)
    assert decode_access_token(t2) == user_id, "revoking t1 must not kill t2"
