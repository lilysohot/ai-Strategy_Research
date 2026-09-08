"""T2.7 — session CRUD + turns query + run-route auth + Run persistence.

Maps to the T2.7 checklist:
    * session CRUD: POST/GET/list/DELETE /api/sessions
    * turns query: GET /api/sessions/{id}/turns
    * title derived from first message when absent
    * ownership filtering: another user's session reads as 404 (anti-IDOR)
    * runs routes now require auth (get_current_user); Run row is persisted and
      scoped to the caller

Run with::
    uv run pytest tests/test_sessions_t27.py -q
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from server.config import get_config
from server.orchestrator import Orchestrator, _session_uuid
from server.store import (
    create_run,
    get_run,
    init_db,
    reset_engine,
    update_run_result,
)


@pytest.fixture
async def client(tmp_path):
    cfg = get_config()
    orig_url, orig_key = cfg.database_url, cfg.master_key
    db = tmp_path / "test.db"
    cfg.database_url = f"sqlite+aiosqlite:///{db}"
    cfg.master_key = f"test-master-{uuid.uuid4().hex}"
    await reset_engine()
    await init_db()
    from server.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    cfg.database_url, cfg.master_key = orig_url, orig_key
    await reset_engine()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, username: str, password: str = "Str0ngPass1") -> str:
    resp = await client.post(
        "/api/auth/register", json={"username": username, "password": password}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _login(client, username: str, password: str = "Str0ngPass1") -> str:
    resp = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


# ── auth on runs routes ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_runs_require_auth(client):
    # No token -> 401 on every run surface.
    assert (await client.post("/api/runs", json={"message": "hi"})).status_code == 401
    assert (await client.get("/api/runs/123/events")).status_code == 401
    assert (await client.get("/api/runs/123/trace")).status_code == 401
    assert (await client.post("/api/runs/123/control", json={"action": "stop"})).status_code == 401


# ── session CRUD ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_create_session_with_explicit_title(client):
    await _register(client, "alice")
    token = await _login(client, "alice")
    resp = await client.post("/api/sessions", json={"title": "My research"},
                             headers=_auth(token))
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "My research"
    assert uuid.UUID(body["id"])


@pytest.mark.asyncio
async def test_create_session_derives_title_from_first_message(client):
    await _register(client, "alice")
    token = await _login(client, "alice")
    resp = await client.post(
        "/api/sessions",
        json={"first_message": "What is the PE ratio of AAPL?\n  and more context"},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    body = resp.json()
    # Newlines/extra spaces collapsed; truncated to one line.
    assert body["title"] == "What is the PE ratio of AAPL? and more context"
    assert len(body["title"]) <= 60


@pytest.mark.asyncio
async def test_create_session_default_title(client):
    await _register(client, "alice")
    token = await _login(client, "alice")
    resp = await client.post("/api/sessions", json={}, headers=_auth(token))
    assert resp.status_code == 201
    assert resp.json()["title"] == "新对话"


@pytest.mark.asyncio
async def test_list_sessions_scoped_to_user(client):
    await _register(client, "alice")
    token_a = await _login(client, "alice")
    await _register(client, "bob")
    token_b = await _login(client, "bob")

    await client.post("/api/sessions", json={"title": "A1"}, headers=_auth(token_a))
    await client.post("/api/sessions", json={"title": "A2"}, headers=_auth(token_a))
    await client.post("/api/sessions", json={"title": "B1"}, headers=_auth(token_b))

    list_a = await client.get("/api/sessions", headers=_auth(token_a))
    list_b = await client.get("/api/sessions", headers=_auth(token_b))
    assert [s["title"] for s in list_a.json()["sessions"]] == ["A1", "A2"]
    assert [s["title"] for s in list_b.json()["sessions"]] == ["B1"]


@pytest.mark.asyncio
async def test_get_session_ownership_404(client):
    await _register(client, "alice")
    token_a = await _login(client, "alice")
    await _register(client, "bob")
    token_b = await _login(client, "bob")

    sid = await client.post("/api/sessions", json={"title": "secret"},
                            headers=_auth(token_a))
    sid_str = sid.json()["id"]

    # Bob (not owner) must get 404, never 200 or 403 (no oracle).
    resp = await client.get(f"/api/sessions/{sid_str}", headers=_auth(token_b))
    assert resp.status_code == 404
    # Unknown id also 404.
    assert (await client.get(f"/api/sessions/{uuid.uuid4().hex}",
                             headers=_auth(token_b))).status_code == 404
    # Owner sees it.
    assert (await client.get(f"/api/sessions/{sid_str}",
                             headers=_auth(token_a))).status_code == 200


@pytest.mark.asyncio
async def test_delete_session_soft_and_ownership(client):
    await _register(client, "alice")
    token_a = await _login(client, "alice")
    await _register(client, "bob")
    token_b = await _login(client, "bob")

    sid = await client.post("/api/sessions", json={"title": "to-delete"},
                            headers=_auth(token_a))
    sid_str = sid.json()["id"]

    # Bob cannot delete Alice's session.
    assert (await client.delete(f"/api/sessions/{sid_str}",
                                headers=_auth(token_b))).status_code == 404
    # Alice deletes it.
    assert (await client.delete(f"/api/sessions/{sid_str}",
                                headers=_auth(token_a))).status_code == 204
    # Now invisible to both (soft-deleted => 404 for owner too).
    assert (await client.get(f"/api/sessions/{sid_str}",
                             headers=_auth(token_a))).status_code == 404


# ── turns query ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_turns_query_requires_ownership(client):
    await _register(client, "alice")
    token_a = await _login(client, "alice")
    await _register(client, "bob")
    token_b = await _login(client, "bob")

    sid = await client.post(
        "/api/sessions",
        json={"first_message": "hello"},
        headers=_auth(token_a),
    )
    sid_str = sid.json()["id"]

    # Bob cannot read Alice's turns (404).
    assert (await client.get(f"/api/sessions/{sid_str}/turns",
                             headers=_auth(token_b))).status_code == 404
    # Alice sees the seeded user turn.
    turns = await client.get(f"/api/sessions/{sid_str}/turns", headers=_auth(token_a))
    assert turns.status_code == 200
    body = turns.json()["turns"]
    assert len(body) == 1
    assert body[0]["role"] == "user"
    assert body[0]["content"] == "hello"
    assert "seq" in body[0]


# ── Run row persistence (store layer) ──────────────────────────────
@pytest.mark.asyncio
async def test_run_row_persisted_and_scoped(client, tmp_path):
    cfg = get_config()
    orig_url, orig_key = cfg.database_url, cfg.master_key
    db = tmp_path / "t2.db"
    cfg.database_url = f"sqlite+aiosqlite:///{db}"
    cfg.master_key = f"test-master-{uuid.uuid4().hex}"
    await reset_engine()
    await init_db()

    uid_a = uuid.uuid4()
    uid_b = uuid.uuid4()
    sid = uuid.uuid4()
    run_id = uuid.uuid4()

    await create_run(run_id=run_id, session_id=sid, user_id=uid_a,
                    prompt="do the thing", pipeline_id="stateful-react-agent",
                    run_dir="/tmp/x", status="queued")

    # Owner can fetch it; non-owner cannot (anti-IDOR).
    assert (await get_run(run_id=run_id, user_id=uid_a)) is not None
    assert (await get_run(run_id=run_id, user_id=uid_b)) is None

    await update_run_result(run_id=run_id, status="completed",
                            final_answer="here is the answer")
    row = await get_run(run_id=run_id, user_id=uid_a)
    assert row.status == "completed"
    assert row.final_answer == "here is the answer"
    assert row.finished_at is not None

    cfg.database_url, cfg.master_key = orig_url, orig_key
    await reset_engine()


# ── orchestrator: run_finished persists the run row ────────────────
@pytest.mark.asyncio
async def test_orchestrator_persists_run_result_on_finished(client, tmp_path):
    cfg = get_config()
    orig_url, orig_key = cfg.database_url, cfg.master_key
    db = tmp_path / "t3.db"
    cfg.database_url = f"sqlite+aiosqlite:///{db}"
    cfg.master_key = f"test-master-{uuid.uuid4().hex}"
    await reset_engine()
    await init_db()

    uid = uuid.uuid4()
    sid = uuid.uuid4()
    run_id = uuid.uuid4()
    await create_run(run_id=run_id, session_id=sid, user_id=uid,
                    prompt="p", pipeline_id="stateful-react-agent",
                    run_dir="/tmp/y", status="queued")

    orch = Orchestrator()
    handle = type("H", (), {
        "run_id": run_id.hex,
        "_params": {"session_id": "s", "session_uuid": sid},
        "session_id": "s",
    })()
    await orch._persist_run_result(handle, {
        "type": "run_finished", "ok": True, "final_answer": "the answer",
        "stopped_by": "", "error": "",
    })
    row = await get_run(run_id=run_id, user_id=uid)
    assert row.status == "completed"
    assert row.final_answer == "the answer"

    # Failure path (no stop) keeps status failed and records error + partial answer.
    await orch._persist_run_result(handle, {
        "type": "run_finished", "ok": False, "final_answer": "partial",
        "stopped_by": "", "error": "boom",
    })
    row = await get_run(run_id=run_id, user_id=uid)
    assert row.status == "failed"
    assert row.error == "boom"
    assert row.stopped_by is None
    assert row.final_answer == "partial"

    # T2.8: a non-empty stopped_by records the run as "stopped" (not failed),
    # preserving the partial answer so the UI can show a partial result.
    await orch._persist_run_result(handle, {
        "type": "run_finished", "ok": False, "final_answer": "partial",
        "stopped_by": "user_stop", "error": "",
    })
    row = await get_run(run_id=run_id, user_id=uid)
    assert row.status == "stopped"
    assert row.stopped_by == "user_stop"
    assert row.final_answer == "partial"

    cfg.database_url, cfg.master_key = orig_url, orig_key
    await reset_engine()


# ── runs route writes a Run row bound to the caller ────────────────
@pytest.mark.asyncio
async def test_runs_route_creates_owned_run_row(client, monkeypatch):
    # Avoid spawning a real worker; just ensure the Run row is written and owned.
    captured = {}

    async def fake_submit(self, **params):
        captured.update(params)

    monkeypatch.setattr(Orchestrator, "submit", fake_submit)

    await _register(client, "alice")
    token = await _login(client, "alice")
    resp = await client.post("/api/runs", json={"message": "my prompt"},
                             headers=_auth(token))
    assert resp.status_code == 202
    run_id_hex = resp.json()["run_id"]

    # The Run row exists and is owned by alice (resolve her id from the DB).
    from server.store import get_user_by_username
    alice = await get_user_by_username("alice")
    row = await get_run(run_id=uuid.UUID(run_id_hex), user_id=alice.id)
    assert row is not None
    assert row.prompt == "my prompt"
    assert row.status == "queued"
    # A second user cannot see it.
    await _register(client, "bob")
    token_b = await _login(client, "bob")
    assert (await get_run(run_id=uuid.UUID(run_id_hex),
                          user_id=(await get_user_by_username("bob")).id)) is None
    # And the SSE/trace endpoints return 404 for bob.
    assert (await client.get(f"/api/runs/{run_id_hex}/trace",
                             headers=_auth(token_b))).status_code == 404
    assert (await client.get(f"/api/runs/{run_id_hex}/trace",
                             headers=_auth(token))).status_code == 200


@pytest.mark.asyncio
async def test_session_uuid_mapping_stable():
    a = _session_uuid("default")
    b = _session_uuid("default")
    assert a == b
    assert isinstance(a, uuid.UUID)
