"""F07-KEY-1: an undecryptable default LLM key must refuse a run, not reroute it.

Found by the F07 ④ master-key drill (2026-10-02, audit/f07-key-ondelete-drill.json):
with a default config whose ciphertext no longer decrypts (SERVER_MASTER_KEY
rotated/lost), a run submission was accepted (202), its snapshot still claimed
``user-config``, and the worker silently ran on the server's own provider —
billing landed on the server while the audit trail said otherwise.

Fix (two lines of defence):

* the submission route now probes ``user_llm_cred_state`` and answers 503 for
  ``error`` before any side effect ("none" — no default config — is the
  legitimate server-default fallback and still passes);
* ``Orchestrator._resolve_llm_env`` re-raises ``LLMCredentialError`` instead of
  swallowing it into "inject nothing", so a key that goes bad between the gate
  and the spawn fails the run instead of rerouting it.

Every case runs against a throwaway SQLite file and a temp data root — no real
database, no network, no subprocess.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from server import store
from server.config import get_config
from server.orchestrator import Orchestrator

KEY_A = "f07-gate-key-a-0123456789abcdef"
KEY_B = "f07-gate-key-b-wrong"


@pytest.fixture
async def env(tmp_path, monkeypatch):
    """SQLite store + temp runs root + a user with a KEY_A-encrypted default key."""
    cfg = get_config()
    monkeypatch.setattr(cfg, "master_key", KEY_A)
    monkeypatch.setattr(cfg, "database_url", f"sqlite+aiosqlite:///{tmp_path}/f07gate.db")
    monkeypatch.setattr(cfg, "runs_root", tmp_path / "runs")
    await store.reset_engine()
    await store.init_db()
    a = await store.create_user(username="f07-gate", password_hash="synthetic-no-login")
    await store.create_llm_config(
        user_id=a.id,
        name="gate-cfg",
        base_url="http://127.0.0.1:9",  # unreachable on purpose; never dialed here
        model="gate-model",
        api_key="sk-gate-plaintext",
        is_default=True,
    )
    orch = Orchestrator()
    spawned: list[str] = []

    async def refusing_spawn(**params):  # signature mirrors Orchestrator._spawn
        raise AssertionError("spawn must not be reached in a refused submission")

    monkeypatch.setattr(orch, "_spawn", refusing_spawn)
    monkeypatch.setattr("server.routes.runs.get_orchestrator", lambda: orch)
    yield SimpleNamespace(
        cfg=cfg, a=a, orch=orch, spawned=spawned, monkeypatch=monkeypatch
    )
    await store.reset_engine()


def _allow_spawn(env) -> None:
    """Replace the fixture's refusing spawn with one that records and returns."""

    async def ok_spawn(**params):
        env.spawned.append(params["run_id"])
        return SimpleNamespace(run_id=params["run_id"], session_id=params["session_id"])

    env.orch._spawn = ok_spawn


async def _settle(env) -> None:
    """Let the session's drain task reach the (mocked) spawn.

    ``submit`` only enqueues; the spawn happens in a task created inside the
    orchestrator, so yield until the recorded spawn shows up.
    """
    for _ in range(20):
        await asyncio.sleep(0)
        if env.spawned:
            return


async def _submit(env) -> tuple[int, dict]:
    from server.app import app
    from server.deps import get_current_user

    app.dependency_overrides[get_current_user] = lambda: env.a
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/runs", json={"message": "gate probe", "session_id": "gate-s1"}
            )
        try:
            body = resp.json()
        except Exception:
            body = {}
        return resp.status_code, body
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def _run_rows() -> int:
    from sqlalchemy import func, select

    async with store.get_sessionmaker()() as session:
        return int((await session.execute(select(func.count()).select_from(store.Run))).scalar_one())


async def test_refused_when_default_key_undecryptable(env):
    """Rotated master key + existing default config → 503, zero side effects."""
    env.monkeypatch.setattr(env.cfg, "master_key", KEY_B)
    status, body = await _submit(env)
    assert status == 503
    assert "无法解密" in body.get("detail", "")
    assert await _run_rows() == 0  # no run row, no snapshot, nothing to clean up
    assert env.spawned == []


async def test_server_default_fallback_still_allowed_without_config(env):
    """No default config is the legitimate fallback case — must still be 202."""
    from sqlalchemy import delete

    async with store.get_sessionmaker()() as session:
        await session.execute(delete(store.UserLLMConfig))
        await session.commit()
    _allow_spawn(env)
    status, body = await _submit(env)
    assert status == 202, body
    assert body["status"] == "queued"
    await _settle(env)
    assert len(env.spawned) == 1


async def test_accepted_when_key_decrypts(env):
    """Correct master key → the gate passes and the run is submitted."""
    _allow_spawn(env)
    status, body = await _submit(env)
    assert status == 202, body
    await _settle(env)
    assert len(env.spawned) == 1


async def test_probe_states(env):
    """user_llm_cred_state distinguishes ok / none / error."""
    assert await store.user_llm_cred_state(user_id=env.a.id) == "ok"
    env.monkeypatch.setattr(env.cfg, "master_key", KEY_B)
    assert await store.user_llm_cred_state(user_id=env.a.id) == "error"
    assert await store.user_llm_cred_state(user_id=env.a.id) != "none"
    from uuid import uuid4

    assert await store.user_llm_cred_state(user_id=uuid4()) == "none"


async def test_resolve_raises_llm_credential_error(env):
    """resolve_user_llm_env raises instead of returning None on a bad key."""
    env.monkeypatch.setattr(env.cfg, "master_key", KEY_B)
    with pytest.raises(store.LLMCredentialError):
        await store.resolve_user_llm_env(user_id=env.a.id)


async def test_orchestrator_second_line_propagates(env):
    """_resolve_llm_env re-raises LLMCredentialError (no silent reroute)."""
    env.monkeypatch.setattr(env.cfg, "master_key", KEY_B)
    with pytest.raises(store.LLMCredentialError):
        await env.orch._resolve_llm_env(env.a.id)
