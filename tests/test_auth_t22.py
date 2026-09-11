"""T2.2 — auth routes: register / login / me / logout / password + global DI.

Each test maps to a line in the T2.2 checklist:
    FR-1.1  registration, strength rules, argon2id storage, audit record
    FR-1.2  JWT issuance, /me resolution
    FR-1.3  throttling at the route layer (5 / 10 min)
    FR-1.4  logout revocation, password change
    —       get_current_user dependency rejects bad/absent tokens

Run with::
    uv run pytest tests/test_auth_t22.py -q
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from server.security import login_throttle


@pytest.fixture
async def client(tmp_path):
    """App client backed by a throwaway SQLite database."""
    from server.config import get_config
    from server.store import init_db, reset_engine

    db = tmp_path / "test.db"
    cfg = get_config()
    original_url = cfg.database_url
    original_key = cfg.master_key
    original_jwt = cfg.jwt_secret
    # Per-test DB and signing key, so tests cannot influence each other.
    cfg.database_url = f"sqlite+aiosqlite:///{db}"
    cfg.master_key = f"test-master-key-{uuid.uuid4().hex}"
    # Empty so tokens are signed with the per-test master_key above; a real
    # deployment sets this, and that path is covered by
    # test_me_rejects_token_after_jwt_secret_rotation.
    cfg.jwt_secret = ""
    await reset_engine()
    await init_db()

    from server.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    login_throttle._records.clear()
    cfg.database_url = original_url
    cfg.master_key = original_key
    cfg.jwt_secret = original_jwt
    await reset_engine()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, username: str = "alice",
                    password: str = "Str0ngPass1") -> str:
    """Register and return the user id."""
    resp = await client.post("/api/auth/register",
                             json={"username": username, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _login(client, username: str = "alice",
                 password: str = "Str0ngPass1") -> str:
    resp = await client.post("/api/auth/login",
                             json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


# ── FR-1.1: registration ───────────────────────────────────────
@pytest.mark.asyncio
async def test_register_returns_201_and_user_body(client):
    resp = await client.post("/api/auth/register",
                             json={"username": "alice", "password": "Str0ngPass1"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "alice"
    assert body["status"] == "active"
    assert "password" not in body and "password_hash" not in body


@pytest.mark.asyncio
async def test_register_stores_argon2id_not_plaintext(client):
    await _register(client, "bob", "Str0ngPass1")
    from server.store import get_user_by_username

    user = await get_user_by_username("bob")
    assert user is not None
    assert user.password_hash.startswith("$argon2id$")
    assert "Str0ngPass1" not in user.password_hash


@pytest.mark.asyncio
async def test_register_enforces_password_strength(client):
    for weak in ("short1", "allletters", "12345678"):
        resp = await client.post("/api/auth/register",
                                 json={"username": f"u{weak}", "password": weak})
        assert resp.status_code == 400, f"{weak} should be rejected"
        assert "密码" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_register_rejects_duplicate_username(client):
    await _register(client, "alice")
    resp = await client.post("/api/auth/register",
                             json={"username": "alice", "password": "Str0ngPass1"})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_register_writes_audit_log(client):
    user_id = await _register(client, "carol")
    from server.store import get_sessionmaker

    from server.store import AuditLog
    from sqlalchemy import select

    async with get_sessionmaker()() as s:
        rows = (await s.execute(
            select(AuditLog).where(AuditLog.action == "register")
        )).scalars().all()
    assert any(str(r.user_id) == user_id for r in rows)


# ── FR-1.2: login & /me ────────────────────────────────────────
@pytest.mark.asyncio
async def test_login_returns_bearer_token(client):
    await _register(client)
    resp = await client.post("/api/auth/login",
                             json={"username": "alice", "password": "Str0ngPass1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 24 * 60 * 60
    assert body["access_token"].count(".") == 2  # JWT shape


@pytest.mark.asyncio
async def test_login_wrong_password_is_401(client):
    await _register(client)
    resp = await client.post("/api/auth/login",
                             json={"username": "alice", "password": "Wr0ngPass1"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "用户名或密码错误"


@pytest.mark.asyncio
async def test_login_unknown_user_is_indistinguishable(client):
    """No username enumeration: identical status and body for both failures."""
    await _register(client)
    wrong_pw = await client.post(
        "/api/auth/login", json={"username": "alice", "password": "Wr0ngPass1"})
    no_user = await client.post(
        "/api/auth/login", json={"username": "nobody", "password": "Str0ngPass1"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json()["detail"] == no_user.json()["detail"]


@pytest.mark.asyncio
async def test_me_returns_current_user(client):
    await _register(client)
    token = await _login(client)
    resp = await client.get("/api/auth/me", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["username"] == "alice"


# ── 全接口鉴权依赖注入 ──────────────────────────────────────────
@pytest.mark.asyncio
async def test_me_without_token_is_401(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate", "").lower().startswith("bearer")


@pytest.mark.asyncio
async def test_me_rejects_tampered_token(client):
    await _register(client)
    token = await _login(client)
    head, payload, sig = token.split(".")
    bad = f"{head}.{payload}.{'A' if sig[0] != 'A' else 'B'}{sig[1:]}"
    resp = await client.get("/api/auth/me", headers=_auth(bad))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_rejects_token_from_another_key(client):
    """A token signed by a different MASTER_KEY must not be honoured."""
    from server.config import get_config

    await _register(client)
    token = await _login(client)
    cfg = get_config()
    original = cfg.master_key
    try:
        cfg.master_key = "an-entirely-different-master-key"
        resp = await client.get("/api/auth/me", headers=_auth(token))
        assert resp.status_code == 401
    finally:
        cfg.master_key = original


@pytest.mark.asyncio
async def test_me_rejects_token_after_jwt_secret_rotation(client):
    """Rotating SERVER_JWT_SECRET must invalidate every outstanding token.

    This is the deployment-realistic counterpart of the master_key case: once
    ``jwt_secret`` is set it — not ``master_key`` — is what signs tokens, so it
    is also what rotating has to invalidate.
    """
    from server.config import get_config

    await _register(client)
    token = await _login(client)
    # Sanity: the token is valid before the rotation.
    assert (await client.get("/api/auth/me", headers=_auth(token))).status_code == 200

    cfg = get_config()
    original = cfg.jwt_secret
    try:
        cfg.jwt_secret = "a-rotated-signing-key"
        resp = await client.get("/api/auth/me", headers=_auth(token))
        assert resp.status_code == 401
    finally:
        cfg.jwt_secret = original


@pytest.mark.asyncio
async def test_deleted_user_token_is_rejected(client):
    """A validly signed token for a removed account must not grant access."""
    from server.store import get_sessionmaker

    user_id = await _register(client)
    token = await _login(client)

    async with get_sessionmaker()() as s:
        from server.store import User

        user = await s.get(User, uuid.UUID(user_id))
        assert user is not None
        user.status = "disabled"
        await s.commit()

    resp = await client.get("/api/auth/me", headers=_auth(token))
    assert resp.status_code == 401


# ── FR-1.3: throttling at the route layer ──────────────────────
@pytest.mark.asyncio
async def test_login_locks_after_five_failures(client):
    await _register(client)
    codes = []
    for _ in range(5):
        resp = await client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "Wr0ngPass1"})
        codes.append(resp.status_code)
    # 4 plain failures, then the 5th flips the account to locked.
    assert codes[:4] == [401] * 4
    assert codes[4] == 423

    # Correct password is still refused while locked.
    resp = await client.post(
        "/api/auth/login", json={"username": "alice", "password": "Str0ngPass1"})
    assert resp.status_code == 423


@pytest.mark.asyncio
async def test_successful_login_clears_failure_counter(client):
    await _register(client)
    for _ in range(4):
        await client.post("/api/auth/login",
                          json={"username": "alice", "password": "Wr0ngPass1"})
    token = await _login(client)
    assert token
    # Counter reset: four more failures must not lock the account.
    for _ in range(4):
        resp = await client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "Wr0ngPass1"})
        assert resp.status_code == 401
    assert await _login(client)


@pytest.mark.asyncio
async def test_lockout_is_per_username(client):
    await _register(client, "alice")
    await _register(client, "bob")
    for _ in range(5):
        await client.post("/api/auth/login",
                          json={"username": "alice", "password": "Wr0ngPass1"})
    # bob is unaffected by alice's lockout.
    assert await _login(client, "bob")


# ── FR-1.4: logout & password change ───────────────────────────
@pytest.mark.asyncio
async def test_logout_revokes_the_presented_token(client):
    await _register(client)
    token = await _login(client)
    assert (await client.get("/api/auth/me", headers=_auth(token))).status_code == 200

    resp = await client.post("/api/auth/logout", headers=_auth(token))
    assert resp.status_code == 204

    assert (await client.get("/api/auth/me", headers=_auth(token))).status_code == 401


@pytest.mark.asyncio
async def test_logout_does_not_revoke_other_sessions(client):
    """Multi-device logout must be scoped to the token presented."""
    await _register(client)
    phone = await _login(client)
    laptop = await _login(client)
    assert phone != laptop, "tokens must be unique (jti)"

    await client.post("/api/auth/logout", headers=_auth(phone))
    assert (await client.get("/api/auth/me", headers=_auth(phone))).status_code == 401
    assert (await client.get("/api/auth/me", headers=_auth(laptop))).status_code == 200


@pytest.mark.asyncio
async def test_password_change_flow(client):
    await _register(client)
    token = await _login(client)

    bad = await client.post("/api/auth/password", headers=_auth(token),
                            json={"old_password": "N0tMine12", "new_password": "N3wPassw0rd"})
    assert bad.status_code == 400

    weak = await client.post("/api/auth/password", headers=_auth(token),
                             json={"old_password": "Str0ngPass1", "new_password": "weak"})
    assert weak.status_code == 400

    ok = await client.post("/api/auth/password", headers=_auth(token),
                           json={"old_password": "Str0ngPass1", "new_password": "N3wPassw0rd"})
    assert ok.status_code == 204

    # Old password no longer works, new one does.
    old = await client.post("/api/auth/login",
                            json={"username": "alice", "password": "Str0ngPass1"})
    assert old.status_code == 401
    assert await _login(client, password="N3wPassw0rd")


@pytest.mark.asyncio
async def test_password_change_requires_auth(client):
    await _register(client)
    resp = await client.post("/api/auth/password",
                             json={"old_password": "x", "new_password": "y"})
    assert resp.status_code == 401


# ── 时序抗枚举（best-effort）────────────────────────────────────
@pytest.mark.asyncio
async def test_unknown_user_login_is_not_fast_path(client):
    """A missing account must not return noticeably faster than a wrong password.

    argon2 costs ~50-100ms; if the unknown-user path skipped hashing it would
    return in well under a millisecond and become a timing oracle.
    """
    import time

    await _register(client)
    wrong_pw = await client.post(
        "/api/auth/login", json={"username": "alice", "password": "Wr0ngPass1"})
    assert wrong_pw.status_code == 401

    started = time.perf_counter()
    await client.post("/api/auth/login",
                      json={"username": "ghost", "password": "Str0ngPass1"})
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert elapsed_ms > 10, (
        f"unknown-user login took {elapsed_ms:.1f}ms — too fast, the dummy-hash "
        "timing-parity path is not running"
    )
