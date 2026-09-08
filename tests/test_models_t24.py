"""T2.4 — model config routes (/api/models CRUD + /{id}/test).

Maps to the T2.4 checklist:
    * every route guarded by get_current_user (no token -> 401)
    * create / list / read / update / delete, api_key always masked
    * POST /{id}/test connectivity preflight records last_verified_at /
      last_verify_ok and a key-free error summary
    * ownership enforced: a user cannot touch another user's config (404)
    * audit rows written for create / update / delete / test

The outbound probe is patched (no real network, no LLM quota spent); we assert
the route plumbed the right result into record_verify_result and the response.

Run with::
    uv run pytest tests/test_models_t24.py -q
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from server.store import (
    AuditLog,
    UserLLMConfig,
    get_sessionmaker,
    init_db,
    reset_engine,
)


@pytest.fixture
async def client(tmp_path):
    from server.config import get_config
    from server.routes import models as models_routes

    db = tmp_path / "test.db"
    cfg = get_config()
    orig_url = cfg.database_url
    orig_key = cfg.master_key
    cfg.database_url = f"sqlite+aiosqlite:///{db}"
    cfg.master_key = f"test-master-{uuid.uuid4().hex}"
    await reset_engine()
    await init_db()

    from server.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, models_routes

    cfg.database_url = orig_url
    cfg.master_key = orig_key
    await reset_engine()


async def _register_and_login(client, username):
    # Reuse T2.2 auth flow to get a token.
    await client.post(
        "/api/auth/register",
        json={"username": username, "password": "Str0ngPass1"},
    )
    resp = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "Str0ngPass1"},
    )
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _create_body(**over):
    base = dict(
        name="glm",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-4.5-flash",
        api_key="sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ987654",
    )
    base.update(over)
    return base


async def _create_config(client, token, **over):
    resp = await client.post(
        "/api/models", json=_create_body(**over), headers=_auth(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── auth guard ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_all_routes_require_auth(client):
    client, _ = client
    assert (await client.get("/api/models")).status_code == 401
    assert (await client.post("/api/models", json=_create_body())).status_code == 401
    assert (await client.get(f"/api/models/{uuid.uuid4()}")).status_code == 401
    assert (await client.put(f"/api/models/{uuid.uuid4()}", json={"name": "x"})).status_code == 401
    assert (await client.delete(f"/api/models/{uuid.uuid4()}")).status_code == 401
    assert (await client.post(f"/api/models/{uuid.uuid4()}/test")).status_code == 401


# ── CRUD ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_create_returns_masked_and_no_plaintext(client):
    client, _ = client
    token = await _register_and_login(client, "alice")
    body = _create_body(api_key="sk-SUPERSECRETPLAINTEXTVALUE0000000000")
    cfg = await _create_config(client, token, api_key=body["api_key"])
    assert cfg["masked_api_key"].startswith("sk-")
    assert "SUPERSECRETPLAINTEXTVALUE" not in cfg["masked_api_key"]
    assert "api_key" not in cfg  # raw field name never returned


@pytest.mark.asyncio
async def test_list_and_read(client):
    client, _ = client
    token = await _register_and_login(client, "alice")
    c1 = await _create_config(client, token, name="c1")
    c2 = await _create_config(client, token, name="c2")

    listed = (await client.get("/api/models", headers=_auth(token))).json()
    assert {c["id"] for c in listed} == {c1["id"], c2["id"]}

    one = (await client.get(f"/api/models/{c1['id']}", headers=_auth(token))).json()
    assert one["id"] == c1["id"]
    assert one["name"] == "c1"


@pytest.mark.asyncio
async def test_update_patches_fields(client):
    client, _ = client
    token = await _register_and_login(client, "alice")
    c = await _create_config(client, token, name="old", model="m1")
    resp = await client.put(
        f"/api/models/{c['id']}",
        json={"name": "new", "api_key": "sk-NEWKEY00000000000000000000000000"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["name"] == "new"
    assert updated["model"] == "m1"  # unchanged
    assert updated["masked_api_key"].endswith("0000")
    assert updated["masked_api_key"] != c["masked_api_key"]


@pytest.mark.asyncio
async def test_delete(client):
    client, _ = client
    token = await _register_and_login(client, "alice")
    c = await _create_config(client, token)
    assert (await client.delete(f"/api/models/{c['id']}", headers=_auth(token))).status_code == 204
    assert (await client.get(f"/api/models/{c['id']}", headers=_auth(token))).status_code == 404


# ── ownership / IDOR ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_user_cannot_access_others_config(client):
    client, _ = client
    a_token = await _register_and_login(client, "alice")
    b_token = await _register_and_login(client, "bob")
    c = await _create_config(client, a_token)
    # bob sees nothing and gets 404 on alice's config
    assert (await client.get("/api/models", headers=_auth(b_token))).json() == []
    assert (await client.get(f"/api/models/{c['id']}", headers=_auth(b_token))).status_code == 404
    assert (await client.delete(f"/api/models/{c['id']}", headers=_auth(b_token))).status_code == 404
    assert (await client.put(f"/api/models/{c['id']}", json={"name": "x"}, headers=_auth(b_token))).status_code == 404


# ── test preflight ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_preflight_success_records_verify_ok(client):
    client, models_routes = client
    token = await _register_and_login(client, "alice")
    c = await _create_config(client, token)

    with patch.object(
        models_routes, "_probe_connectivity", new=AsyncMock(return_value=(True, "连通正常"))
    ) as probe:
        resp = await client.post(f"/api/models/{c['id']}/test", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "detail": "连通正常"}
        # probe was called with a decrypted api_key (not the ciphertext)
        probe.assert_awaited_once()
        _user_id, _cid, api_key = probe.call_args.args
        assert api_key == "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ987654"

    # verify columns recorded
    async with get_sessionmaker()() as s:
        row = await s.get(UserLLMConfig, uuid.UUID(c["id"]))
        assert row.last_verify_ok is True
        assert row.last_verified_at is not None


@pytest.mark.asyncio
async def test_preflight_failure_records_error_summary(client):
    client, models_routes = client
    token = await _register_and_login(client, "alice")
    c = await _create_config(client, token)

    with patch.object(
        models_routes,
        "_probe_connectivity",
        new=AsyncMock(return_value=(False, "认证失败（HTTP 401）")),
    ):
        resp = await client.post(f"/api/models/{c['id']}/test", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json() == {"ok": False, "detail": "认证失败（HTTP 401）"}

    async with get_sessionmaker()() as s:
        row = await s.get(UserLLMConfig, uuid.UUID(c["id"]))
        assert row.last_verify_ok is False
        assert "认证失败" in (row.params_json or {}).get("_last_verify_error", "")


@pytest.mark.asyncio
async def test_preflight_forbidden_for_other_user(client):
    client, models_routes = client
    a_token = await _register_and_login(client, "alice")
    b_token = await _register_and_login(client, "bob")
    c = await _create_config(client, a_token)
    with patch.object(
        models_routes, "_probe_connectivity", new=AsyncMock(return_value=(True, "ok"))
    ):
        resp = await client.post(f"/api/models/{c['id']}/test", headers=_auth(b_token))
        assert resp.status_code == 404


# ── audit logging ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_audit_rows_written(client):
    client, _ = client
    token = await _register_and_login(client, "alice")
    c = await _create_config(client, token)
    await client.put(f"/api/models/{c['id']}", json={"name": "renamed"}, headers=_auth(token))
    await client.post(f"/api/models/{c['id']}/test", headers=_auth(token))
    await client.delete(f"/api/models/{c['id']}", headers=_auth(token))

    async with get_sessionmaker()() as s:
        from sqlalchemy import select

        actions = (await s.execute(select(AuditLog.action))).scalars().all()
    assert "llm_config_created" in actions
    assert "llm_config_updated" in actions
    assert "llm_config_tested" in actions
    assert "llm_config_deleted" in actions
