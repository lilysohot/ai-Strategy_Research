"""F07-KEY-2: an HTTP path to reset an undecryptable LLM key.

The F07 ④ drill (audit/f07-key-ondelete-drill.json) showed that after a
``SERVER_MASTER_KEY`` rotation the ONLY recovery was direct database surgery —
``update_llm_config`` existed in the store but no route exposed it. This suite
covers the new minimal router: PATCH resets the ciphertext (re-encrypted with
the *current* master key), GET reads back masked, ownership errors collapse to
404 (anti-IDOR), and a reset actually restores ``user_llm_cred_state`` to "ok"
so the F07-KEY-1 submission gate admits runs again.

All cases run on a throwaway SQLite file with a temp data root — no real DB,
no network, no subprocess.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from server import store
from server.config import get_config

KEY_A = "f07-key2-key-a-0123456789abcdef"
KEY_B = "f07-key2-key-b-wrong"


@pytest.fixture
async def env(tmp_path, monkeypatch):
    """SQLite store + temp runs root + a user whose default key was KEY_A-encrypted."""
    cfg = get_config()
    monkeypatch.setattr(cfg, "master_key", KEY_A)
    monkeypatch.setattr(cfg, "database_url", f"sqlite+aiosqlite:///{tmp_path}/f07key2.db")
    monkeypatch.setattr(cfg, "runs_root", tmp_path / "runs")
    await store.reset_engine()
    await store.init_db()
    a = await store.create_user(username="f07-key2", password_hash="synthetic-no-login")
    b = await store.create_user(username="f07-key2-b", password_hash="synthetic-no-login")
    created = await store.create_llm_config(
        user_id=a.id,
        name="key2-cfg",
        base_url="http://127.0.0.1:9",
        model="key2-model",
        api_key="sk-key2-plaintext",
        is_default=True,
    )
    cfg_id = uuid.UUID(created["id"])
    yield SimpleNamespace(cfg=cfg, a=a, b=b, cfg_id=cfg_id, monkeypatch=monkeypatch)
    await store.reset_engine()


async def _call(env, method: str, path: str, json_body: dict | None = None, *, user=None):
    from server.app import app
    from server.deps import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user or env.a
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.request(method, path, json=json_body)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_get_masks_and_hides_ciphertext(env):
    resp = await _call(env, "GET", f"/api/llm-configs/{env.cfg_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(env.cfg_id)
    assert "api_key_cipher" not in body
    assert "sk-gate" not in str(body)  # ciphertext never leaks (binary or otherwise)
    assert body["masked_api_key"]


async def test_foreign_and_missing_config_are_404(env):
    other = await store.create_llm_config(
        user_id=env.b.id, name="other", base_url="http://127.0.0.1:9",
        model="m", api_key="sk-other", is_default=True,
    )
    other_id = uuid.UUID(other["id"])
    # "Not mine" reads exactly like "does not exist" (anti-IDOR).
    resp = await _call(env, "GET", f"/api/llm-configs/{other_id}", user=env.b)
    assert resp.status_code == 200  # owner sees their own
    resp = await _call(env, "GET", f"/api/llm-configs/{other_id}", user=env.a)
    assert resp.status_code == 404  # foreign
    resp = await _call(env, "PATCH", f"/api/llm-configs/{other_id}",
                       {"api_key": "sk-hijack"}, user=env.a)
    assert resp.status_code == 404
    assert (await store.user_llm_cred_state(user_id=env.b.id)) == "ok"  # untouched
    resp = await _call(env, "PATCH", f"/api/llm-configs/{uuid.uuid4()}",
                       {"api_key": "sk-new"})
    assert resp.status_code == 404


async def test_patch_resets_key_and_restores_cred_state(env):
    """The recovery story end-to-end: rotated key → error state → reset → ok."""
    env.monkeypatch.setattr(env.cfg, "master_key", KEY_B)
    assert await store.user_llm_cred_state(user_id=env.a.id) == "error"

    resp = await _call(env, "PATCH", f"/api/llm-configs/{env.cfg_id}",
                       {"api_key": "sk-reset-via-http"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "sk-reset-via-http" not in str(body)  # write-only: never echoed

    # The new ciphertext was sealed with the CURRENT master key, so decryption
    # works and the F07-KEY-1 submission gate admits runs again.
    assert await store.user_llm_cred_state(user_id=env.a.id) == "ok"
    resolved = await store.resolve_user_llm_env(user_id=env.a.id)
    assert resolved is not None
    assert resolved["OPENAI_API_KEY"] == "sk-reset-via-http"


async def test_patch_can_reseal_old_ciphertext_after_key_recovery(env):
    """Rotating BACK to the original key + PATCH also restores usability."""
    env.monkeypatch.setattr(env.cfg, "master_key", KEY_B)
    assert await store.user_llm_cred_state(user_id=env.a.id) == "error"
    env.monkeypatch.setattr(env.cfg, "master_key", KEY_A)
    resp = await _call(env, "PATCH", f"/api/llm-configs/{env.cfg_id}",
                       {"api_key": "sk-again"})
    assert resp.status_code == 200
    assert await store.user_llm_cred_state(user_id=env.a.id) == "ok"
