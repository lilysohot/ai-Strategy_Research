"""M2 milestone acceptance (T2.12).

This is the milestone gate plan.md §进度规则 requires before M3 starts. It is
deliberately written as a user-visible contract check rather than a unit test of
any single module — each test maps to one acceptance line:

  1. **双用户互不可见** — Alice's sessions / runs / artifacts / LLM configs are
     invisible to Bob across every route, and every cross-tenant access is 404
     (never 403, so ownership is not an existence oracle).
  2. **错误 key 预检报错且可改正** — a wrong api_key fails ``POST /{id}/test``
     with a key-free error summary; correcting the key makes the same endpoint
     pass and clears the recorded error.
  3. **服务重启后历史 run 可回放** — after the in-process state is torn down
     (DB engine disposed, orchestrator replaced, new app client) a historical
     run's trajectory still replays identically, because the file on disk — not
     process memory — is the source of truth.
  4. **全库无明文 key** — a full scan of every table proves no plaintext
     credential is ever persisted, and no API response echoes one.
"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from deploy.huggingface.mock_llm import MockLLMServer, text_turn
from server.config import get_config
from server.store import (
    Base,
    create_run,
    get_run,
    init_db,
    record_artifacts,
)

# A recognisable plaintext credential. If this string ever reaches the database
# or a response body, the encryption-at-rest contract is broken.
SECRET_KEY = "sk-acceptance-plaintext-KEY-9876543210"
WRONG_KEY = "sk-acceptance-WRONG-key-0000000000"


# ── fixtures ────────────────────────────────────────────────────


@pytest.fixture
async def app_client():
    from httpx import ASGITransport, AsyncClient

    from server.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _register(client, username: str) -> dict:
    await init_db()
    pwd = "Str0ngPass1"
    reg = await client.post("/api/auth/register", json={"username": username, "password": pwd})
    assert reg.status_code in (201, 409), reg.text
    login = await client.post("/api/auth/login", json={"username": username, "password": pwd})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
async def alice(app_client):
    return await _register(app_client, "t212-alice")


@pytest.fixture
async def bob(app_client):
    return await _register(app_client, "t212-bob")


def _uid(headers: dict) -> uuid.UUID:
    from server.security import decode_access_token

    return decode_access_token(headers["Authorization"].removeprefix("Bearer ").strip())


@pytest.fixture
def isolated_orchestrator(monkeypatch):
    """Swap in a private Orchestrator so a leftover run from another test file
    cannot occupy the concurrency slot this test's run needs."""
    import server.orchestrator as orch_mod

    orch = orch_mod.Orchestrator()
    monkeypatch.setattr(orch_mod, "_orchestrator", orch)
    return orch


# ── 1. 双用户互不可见 ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_users_cannot_see_each_other(app_client, alice, bob):
    """Alice's sessions, runs, artifacts and LLM configs are invisible to Bob.

    Every cross-tenant read must be 404 — never 403, which would confirm the
    resource exists and turn ownership into an existence oracle.
    """
    await init_db()
    a_uid, b_uid = _uid(alice), _uid(bob)

    # Alice creates a session (with a first message), a run and an artifact.
    sess = await app_client.post(
        "/api/sessions",
        json={"title": "Alice private", "first_message": "hello"},
        headers=alice,
    )
    assert sess.status_code == 201, sess.text
    session_id = sess.json()["id"]
    session_uuid = uuid.UUID(session_id)

    run_id = uuid.uuid4()
    await create_run(
        run_id=run_id,
        session_id=session_uuid,
        user_id=a_uid,
        prompt="alice prompt",
        pipeline_id="stateful-react-agent",
        run_dir="/tmp/alice-run",
        status="completed",
    )
    await record_artifacts(
        run_id=run_id,
        artifacts=[{"rel_path": "alice.md", "size": 5, "sha256": "a" * 64}],
    )

    # Alice creates an LLM config carrying a real (encrypted) key.
    cfg = await app_client.post(
        "/api/models",
        json={
            "name": "alice-cfg",
            "base_url": "https://api.example.com/v1",
            "model": "m",
            "api_key": SECRET_KEY,
        },
        headers=alice,
    )
    assert cfg.status_code == 201, cfg.text
    cfg_id = cfg.json()["id"]

    # Bob's listings contain none of it.
    bob_sessions = await app_client.get("/api/sessions", headers=bob)
    assert bob_sessions.status_code == 200
    assert session_id not in [s["id"] for s in bob_sessions.json()["sessions"]]

    bob_models = await app_client.get("/api/models", headers=bob)
    assert bob_models.status_code == 200
    assert cfg_id not in [c["id"] for c in bob_models.json()]

    # Every cross-tenant route is a 404.
    for method, path, kwargs in (
        ("get", f"/api/sessions/{session_id}", {}),
        ("get", f"/api/sessions/{session_id}/turns", {}),
        ("delete", f"/api/sessions/{session_id}", {}),
        ("get", f"/api/runs/{run_id.hex}/trace", {}),
        ("get", f"/api/runs/{run_id.hex}/artifacts", {}),
        ("post", f"/api/runs/{run_id.hex}/control", {"json": {"action": "stop"}}),
        ("get", f"/api/models/{cfg_id}", {}),
        ("put", f"/api/models/{cfg_id}", {"json": {"name": "hijacked"}}),
        ("delete", f"/api/models/{cfg_id}", {}),
        ("post", f"/api/models/{cfg_id}/test", {}),
    ):
        resp = await getattr(app_client, method)(path, headers=bob, **kwargs)
        assert resp.status_code == 404, f"{method} {path} leaked: {resp.status_code}"

    # Bob cannot reach it via the download endpoint either.
    dl = await app_client.get(
        f"/api/runs/{run_id.hex}/artifacts/download",
        params={"path": "alice.md"},
        headers=bob,
    )
    assert dl.status_code == 404

    # Alice still sees everything she owns (the isolation is not a global deny).
    assert (await app_client.get(f"/api/sessions/{session_id}", headers=alice)).status_code == 200
    assert (
        await app_client.get(f"/api/runs/{run_id.hex}/artifacts", headers=alice)
    ).status_code == 200
    assert (await app_client.get(f"/api/models/{cfg_id}", headers=alice)).status_code == 200
    # Sanity: the two users really are different principals.
    assert a_uid != b_uid


# ── 2. 错误 key 预检报错且可改正 ────────────────────────────────


class _KeyedHandler(BaseHTTPRequestHandler):
    """A tiny OpenAI-shaped endpoint that accepts exactly one api_key.

    Authentic to the acceptance criterion: the SAME base_url returns 401 for a
    wrong key and 200 for the right one, so "报错且可改正" is exercised by
    changing only the credential — not by pointing at a different server.
    """

    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        auth = self.headers.get("Authorization") or ""
        if auth == f"Bearer {SECRET_KEY}":
            body = json.dumps(
                {
                    "object": "list",
                    "data": [{"id": "keyed-model", "object": "model"}],
                }
            ).encode()
            self.send_response(200)
        else:
            body = json.dumps({"error": {"message": "invalid api key"}}).encode()
            self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _KeyedEndpoint:
    def __init__(self) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _KeyedHandler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
            name="keyed-endpoint",
        )

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[0], self._server.server_address[1]
        return f"http://{host}:{port}/v1"

    def start(self) -> _KeyedEndpoint:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread.is_alive():
            self._thread.join(timeout=5)


@pytest.fixture
def keyed_endpoint():
    server = _KeyedEndpoint().start()
    yield server
    server.stop()


@pytest.mark.asyncio
async def test_bad_key_preflight_fails_then_is_correctable(app_client, alice, keyed_endpoint):
    """A wrong key fails the preflight; correcting the key clears the error."""
    await init_db()

    # Create the config with the WRONG key.
    cfg = await app_client.post(
        "/api/models",
        json={
            "name": "preflight",
            "base_url": keyed_endpoint.base_url,
            "model": "keyed-model",
            "api_key": WRONG_KEY,
        },
        headers=alice,
    )
    assert cfg.status_code == 201, cfg.text
    cfg_id = cfg.json()["id"]

    # Preflight must fail and say why — without echoing the key.
    bad = await app_client.post(f"/api/models/{cfg_id}/test", headers=alice)
    assert bad.status_code == 200, bad.text
    assert bad.json()["ok"] is False
    assert "401" in bad.json()["detail"]
    assert SECRET_KEY not in bad.text and WRONG_KEY not in bad.text

    listed = await app_client.get("/api/models", headers=alice)
    entry = next(c for c in listed.json() if c["id"] == cfg_id)
    assert entry["last_verify_ok"] is False
    # The failure is recorded as a key-free summary the UI can show. The store
    # serializes params_json under the public name "params".
    err = (entry.get("params") or {}).get("_last_verify_error") or ""
    assert err, "failure summary was not recorded"
    assert WRONG_KEY not in err and SECRET_KEY not in err

    # Correct the key — the same endpoint must now pass.
    upd = await app_client.put(
        f"/api/models/{cfg_id}",
        json={"api_key": SECRET_KEY},
        headers=alice,
    )
    assert upd.status_code == 200, upd.text

    good = await app_client.post(f"/api/models/{cfg_id}/test", headers=alice)
    assert good.status_code == 200, good.text
    assert good.json()["ok"] is True, good.json()
    assert SECRET_KEY not in good.text

    listed = await app_client.get("/api/models", headers=alice)
    entry = next(c for c in listed.json() if c["id"] == cfg_id)
    assert entry["last_verify_ok"] is True
    assert entry["last_verified_at"] is not None
    # A successful probe clears the previous error.
    assert not ((entry.get("params") or {}).get("_last_verify_error") or "")


# ── 3. 服务重启后历史 run 可回放 ────────────────────────────────


@pytest.fixture
async def mock_llm_quick():
    server = MockLLMServer(script=[text_turn("Acceptance answer from the mock.")]).start()
    yield server
    server.stop()


@pytest.mark.asyncio
async def test_historical_run_replays_after_restart(
    mock_llm_quick, app_client, isolated_orchestrator, monkeypatch
):
    """A finished run still replays after all in-process state is torn down.

    "Restart" is simulated in-process: dispose the DB engine (forcing a fresh
    connection), install a brand-new Orchestrator (dropping every in-memory run
    handle), and serve through a brand-new HTTP client. Replay then has to come
    from the trajectory file on disk, which is the property being verified.

    This test uses its OWN user rather than ``alice``: a user with a default LLM
    config makes the T2.5 injection chain override ``OPENAI_BASE_URL`` with that
    config's endpoint, which would send the worker somewhere other than the mock
    (a test-isolation leak, not a product defect).
    """
    carol = await _register(app_client, "t212-carol")
    alice = carol
    monkeypatch.setenv("OPENAI_BASE_URL", mock_llm_quick.base_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-spike-mock")
    monkeypatch.setenv("OPENAI_MODEL", mock_llm_quick.model)

    # Lock the worker onto the mock explicitly: give carol a default LLM config
    # that points at ``mock_llm_quick``. This makes the T2.5 injection chain
    # resolve to the mock deterministically instead of falling back to the
    # process-wide OPENAI_* env — which a sibling server test (test_inject_t25,
    # test_llm_config_t23, …) can leave in a different state because they mutate
    # the shared ``get_config()`` lru_cache singleton. A run that fell back to a
    # polluted global would end in llm_error and record no usage, flaking the
    # ``llm_calls >= 1`` assertion below.
    cfg_create = await app_client.post(
        "/api/models",
        json={
            "name": "carol-mock",
            "base_url": mock_llm_quick.base_url,
            "model": mock_llm_quick.model,
            "api_key": "sk-spike-mock",
            "is_default": True,
        },
        headers=alice,
    )
    assert cfg_create.status_code == 201, cfg_create.text

    cfg = get_config()
    monkeypatch.setattr(cfg, "wall_timeout_s", 120)
    monkeypatch.setattr(cfg, "worker_pool_size", 1)
    await init_db()

    from httpx import ASGITransport, AsyncClient

    from server.app import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/runs",
            json={"message": "answer in one sentence", "session_id": "t212-restart"},
            headers=alice,
        )
        assert resp.status_code == 202, resp.text
        run_id = resp.json()["run_id"]

        # Wait for the run to reach a terminal state AND for metering to
        # land: usage is recorded *after* finished_at (best-effort, 15s
        # budget), so waiting on finished_at alone races with _record_usage.
        for _ in range(120):
            await asyncio.sleep(0.5)
            row = await get_run(run_id=uuid.UUID(run_id), user_id=_uid(alice))
            if row is not None and row.finished_at is not None and row.llm_calls:
                break
        assert row is not None and row.finished_at is not None, "run never finished"
        assert row.llm_calls, "usage was never metered"

        before = await client.get(f"/api/runs/{run_id}/trace", headers=alice)
        assert before.status_code == 200
        records_before = before.json()["records"]
        assert records_before, "no trajectory was recorded"

    # ── restart: drop every piece of in-process state ────────────
    from server.store import reset_engine

    await reset_engine()
    import server.orchestrator as orch_mod

    orch_mod._orchestrator = None  # in-memory run handles are gone
    monkeypatch.setattr(orch_mod, "_orchestrator", orch_mod.Orchestrator())

    # ── after restart: the historical run still replays ──────────
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        after = await client.get(f"/api/runs/{run_id}/trace", headers=alice)
        assert after.status_code == 200, after.text
        records_after = after.json()["records"]
        assert len(records_after) == len(records_before)
        assert records_after == records_before

        # Cursor-based resume still works against the replayed file.
        cursor = await client.get(
            f"/api/runs/{run_id}/trace?after={len(records_before)}", headers=alice
        )
        assert cursor.status_code == 200
        assert cursor.json()["records"] == []

        # The run's terminal state and metering survived too (the DB is the
        # store, not process memory). Re-read it fresh: the pre-restart ORM
        # object was detached by reset_engine, and a restart-proof check must
        # read back through a brand-new connection.
        row = await get_run(run_id=uuid.UUID(run_id), user_id=_uid(alice))
        assert row is not None
        assert row.finished_at is not None
        assert row.llm_calls and row.llm_calls >= 1
        assert row.prompt_tokens is not None


# ── 4. 全库无明文 key ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_plaintext_key_anywhere_in_database(app_client, alice):
    """A full table-by-table scan proves no plaintext credential is persisted."""
    await init_db()
    uid = _uid(alice)

    cfg = await app_client.post(
        "/api/models",
        json={
            "name": "secret-holder",
            "base_url": "https://api.example.com/v1",
            "model": "m",
            "api_key": SECRET_KEY,
        },
        headers=alice,
    )
    assert cfg.status_code == 201, cfg.text

    # Also exercise the paths that touch the key at runtime: decrypting it for
    # injection must not leave a copy behind.
    from server.store import get_decrypted_api_key, resolve_user_llm_env

    cfg_uuid = uuid.UUID(cfg.json()["id"])
    await app_client.put(f"/api/models/{cfg_uuid}", json={"is_default": True}, headers=alice)
    assert await get_decrypted_api_key(user_id=uid, config_id=cfg_uuid) == SECRET_KEY
    env = await resolve_user_llm_env(user_id=uid)
    assert env is not None and env["OPENAI_API_KEY"] == SECRET_KEY

    # Scan every row of every table for the plaintext credential.
    from sqlalchemy import select

    from server.store import get_sessionmaker

    async with get_sessionmaker()() as session:
        for table in Base.metadata.sorted_tables:
            rows = (await session.execute(select(table))).all()
            for row in rows:
                for value in row:
                    if value is None:
                        continue
                    if isinstance(value, (bytes, bytearray)):
                        rendered = bytes(value)
                    else:
                        rendered = str(value).encode("utf-8", "replace")
                    assert SECRET_KEY.encode() not in rendered, (
                        f"plaintext key found in {table.name}"
                    )
                    assert SECRET_KEY not in rendered.decode("utf-8", "replace"), (
                        f"plaintext key found in {table.name}"
                    )

    # The API never echoes it either — only a masked form is returned.
    body = (await app_client.get("/api/models", headers=alice)).text
    assert SECRET_KEY not in body
    assert "masked_api_key" in body
    one = (await app_client.get(f"/api/models/{cfg_uuid}", headers=alice)).json()
    assert one["masked_api_key"] != SECRET_KEY
    assert SECRET_KEY not in json.dumps(one)
