"""T2.5 — LLM injection chain (decrypt default config -> worker env).

Maps to the T2.5 checklist:
    * decrypt the user's default config and inject OPENAI_API_KEY / OPENAI_BASE_URL
      / OPENAI_MODEL into the worker environment — NEVER via argv
    * all three present or all absent (no partial injection; worker rejects it)
    * fallback to server .env when the user has no usable config
    * llm_snapshot_json (no key) is derivable for the runs table
    * startup preflight refuses a partial injection

Run with::
    uv run pytest tests/test_inject_t25.py -q
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from server.orchestrator import Orchestrator
from server.store import (
    create_llm_config,
    create_user,
    init_db,
    reset_engine,
)
from server.worker import _assert_llm_env


# ── store-level resolution ────────────────────────────────────────
@pytest.fixture
async def user_with_config(tmp_path):
    from server.config import get_config

    db = tmp_path / "test.db"
    cfg = get_config()
    orig_url, orig_key = cfg.database_url, cfg.master_key
    cfg.database_url = f"sqlite+aiosqlite:///{db}"
    cfg.master_key = f"test-master-{uuid.uuid4().hex}"
    await reset_engine()
    await init_db()

    alice = await create_user(username="alice", password_hash="x")
    await create_llm_config(
        user_id=alice.id,
        name="glm",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-4.5-flash",
        api_key="sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ987654",
        is_default=True,
    )
    yield alice

    cfg.database_url, cfg.master_key = orig_url, orig_key
    await reset_engine()


@pytest.mark.asyncio
async def test_resolve_user_llm_env_returns_all_three(user_with_config):
    from server.store import resolve_user_llm_env

    env = await resolve_user_llm_env(user_id=user_with_config.id)
    assert env is not None
    assert env["OPENAI_API_KEY"] == "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ987654"
    assert env["OPENAI_BASE_URL"] == "https://open.bigmodel.cn/api/paas/v4"
    assert env["OPENAI_MODEL"] == "glm-4.5-flash"
    # The key is the decrypted plaintext, ready for the env (not the ciphertext).
    assert env["OPENAI_API_KEY"].startswith("sk-")


@pytest.mark.asyncio
async def test_resolve_none_when_no_default_config(tmp_path):
    from server.config import get_config
    from server.store import resolve_user_llm_env

    db = tmp_path / "test.db"
    cfg = get_config()
    orig_url, orig_key = cfg.database_url, cfg.master_key
    cfg.database_url = f"sqlite+aiosqlite:///{db}"
    cfg.master_key = f"test-master-{uuid.uuid4().hex}"
    await reset_engine()
    await init_db()
    bob = await create_user(username="bob", password_hash="x")

    assert await resolve_user_llm_env(user_id=bob.id) is None

    cfg.database_url, cfg.master_key = orig_url, orig_key
    await reset_engine()


@pytest.mark.asyncio
async def test_resolve_none_when_partial_config(user_with_config):
    from server.store import resolve_user_llm_env

    # A decryption failure (e.g. key rotation, corrupted ciphertext) must surface
    # as "no usable config" so the run falls back to the server .env rather than
    # injecting a broken partial set.
    with patch(
        "server.store.get_decrypted_api_key",
        new=AsyncMock(side_effect=Exception("decrypt failed")),
    ):
        assert await resolve_user_llm_env(user_id=user_with_config.id) is None


@pytest.mark.asyncio
async def test_build_snapshot_is_key_free(user_with_config):
    from server.store import build_llm_snapshot

    snap = await build_llm_snapshot(user_id=user_with_config.id)
    assert snap["source"] == "user-config"
    assert "api_key" not in snap
    assert "OPENAI_API_KEY" not in snap
    assert snap["model"] == "glm-4.5-flash"
    assert snap["config_id"]

    # No user -> server default marker, still no key.
    server_snap = await build_llm_snapshot(user_id=None)
    assert server_snap == {"source": "server-default"}


# ── orchestrator resolution ───────────────────────────────────────
@pytest.mark.asyncio
async def test_orchestrator_resolves_env_for_user(user_with_config):
    orch = Orchestrator()
    env = await orch._resolve_llm_env(user_with_config.id)
    assert env is not None
    assert env["OPENAI_MODEL"] == "glm-4.5-flash"


@pytest.mark.asyncio
async def test_orchestrator_no_env_when_user_none():
    orch = Orchestrator()
    assert await orch._resolve_llm_env(None) is None


@pytest.mark.asyncio
async def test_orchestrator_falls_back_on_store_error(user_with_config):
    orch = Orchestrator()
    with patch(
        "server.orchestrator.resolve_user_llm_env",
        new=AsyncMock(side_effect=RuntimeError("db down")),
    ):
        # Must not raise; falls back to None (server .env).
        assert await orch._resolve_llm_env(user_with_config.id) is None


# ── worker preflight: all-or-nothing ──────────────────────────────
def test_worker_rejects_partial_injection():
    # Two present, one missing -> must exit, never silently route a key elsewhere.
    with pytest.raises(SystemExit):
        _assert_llm_env(model="m", base_url="", api_key="k")
    with pytest.raises(SystemExit):
        _assert_llm_env(model="", base_url="b", api_key="k")
    with pytest.raises(SystemExit):
        _assert_llm_env(model="m", base_url="b", api_key="")


def test_worker_accepts_all_present_or_all_absent():
    # All present: no exit.
    _assert_llm_env(model="m", base_url="b", api_key="k")
    # All absent: no exit (falls back to server .env).
    _assert_llm_env(model="", base_url="", api_key="")


# ── runs route no longer accepts a plaintext key ──────────────────
@pytest.mark.asyncio
async def test_runs_request_rejects_plaintext_key():
    from server.routes.runs import RunRequest

    # The plaintext-key field must no longer exist on the request model — the
    # server resolves credentials from the store by user_id, never from the client.
    assert "api_key" not in RunRequest.model_fields
    assert "model" not in RunRequest.model_fields
    assert "base_url" not in RunRequest.model_fields
    assert "user_id" in RunRequest.model_fields
    # user_id is the only identity knob now.
    req = RunRequest(message="hi", user_id=str(uuid.uuid4()))
    assert req.user_id is not None
    # Extra/credential fields in the payload are simply ignored (Pydantic default),
    # so a client cannot smuggle an api_key into the run request.
    ignored = RunRequest(message="hi", api_key="sk-should-not-be-accepted")
    assert not hasattr(ignored, "api_key")
