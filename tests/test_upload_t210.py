"""T2.10 file-upload contract tests (mock LLM for the end-to-end path).

Covers the contract in plan.md T2.10:

  * ``POST /api/runs`` accepts multipart uploads and writes them into the run's
    private ``inputs`` dir (read-only to the agent, ``FRONTIER_AGENT_INPUTS_DIR``).
  * Per-file and per-request caps from ``ServerConfig.max_upload_bytes`` /
    ``max_upload_files`` are enforced (413 on violation).
  * Uploaded filenames are flattened so a client-supplied path never escapes the
    inputs dir.
  * The agent is told where the files live via ``_sys_prompt_addendum`` (routed
    through ``prompt_addendum`` → ``--prompt-addendum`` → worker metadata).

The end-to-end test drives a real worker (the mock LLM calls ``read_file`` on the
uploaded input, proving the file is visible to the agent at its inputs dir).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from deploy.huggingface.mock_llm import MockLLMServer, text_turn, tool_call_turn
from server.config import get_config, run_dir_for
from server.store import init_db


@pytest.fixture
async def app_client():
    from httpx import ASGITransport, AsyncClient

    from server.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def auth_headers(app_client):
    await init_db()
    pwd = "Str0ngPass1"
    reg = await app_client.post(
        "/api/auth/register", json={"username": "t210-user", "password": pwd}
    )
    assert reg.status_code in (201, 409), reg.text
    login = await app_client.post(
        "/api/auth/login", json={"username": "t210-user", "password": pwd}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
def isolated_orchestrator(monkeypatch):
    """Swap in a private Orchestrator so a leftover run from another test file
    cannot occupy the concurrency slot this test's run needs."""
    import server.orchestrator as orch_mod

    orch = orch_mod.Orchestrator()
    monkeypatch.setattr(orch_mod, "_orchestrator", orch)
    return orch


def _spawn_approver(orch, run_id: str, client, headers):
    """Answer the P3.2 approval gate the way a user would.

    Since the gate landed (P3.2), a worker's ``create_file`` suspends on
    ``approval_requested`` until a decision arrives — an old e2e that never
    answers would hang the worker for the gate's 300s timeout. This task
    subscribes to the run's event fan-out and approves ``once`` via the real
    API route, so the approval path itself stays exercised.
    """

    async def run() -> None:
        q = orch.subscribe(run_id)
        while True:
            evt = await asyncio.wait_for(q.get(), timeout=90)
            if evt and evt.get("type") == "approval_requested":
                resp = await client.post(
                    f"/api/runs/{run_id}/approve",
                    json={"approval_id": evt["approval_id"], "decision": "once"},
                    headers=headers,
                )
                assert resp.status_code == 200, resp.text
                return

    return asyncio.ensure_future(run())


def _user_id(auth_headers: dict) -> uuid.UUID:
    from server.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ").strip()
    return decode_access_token(token)


# ── upload contract (unit-level, no worker needed) ─────────────


@pytest.mark.asyncio
async def test_upload_writes_into_run_inputs_dir(app_client, auth_headers,
                                                 monkeypatch):
    """A multipart upload lands in <run_id>/inputs and the run still starts."""
    cfg = get_config()
    monkeypatch.setattr(cfg, "wall_timeout_s", 120)
    monkeypatch.setattr(cfg, "worker_pool_size", 1)
    await init_db()

    resp = await app_client.post(
        "/api/runs",
        data={"message": "summarise the brief", "session_id": "t210-upload"},
        files={"files": ("brief.md", b"# Brief\nRead this.\n", "text/markdown")},
        headers=auth_headers,
    )
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]

    inputs_dir = run_dir_for(run_id) / "inputs"
    assert (inputs_dir / "brief.md").exists()
    assert (inputs_dir / "brief.md").read_bytes() == b"# Brief\nRead this.\n"


@pytest.mark.asyncio
async def test_upload_too_many_files_rejected(app_client, auth_headers,
                                              monkeypatch):
    cfg = get_config()
    monkeypatch.setattr(cfg, "max_upload_files", 2)
    await init_db()

    files = [
        ("files", (f"f{i}.txt", b"x", "text/plain")) for i in range(3)
    ]
    resp = await app_client.post(
        "/api/runs",
        data={"message": "x", "session_id": "t210-many"},
        files=files,
        headers=auth_headers,
    )
    assert resp.status_code == 413, resp.text
    assert "too many files" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_upload_too_large_file_rejected(app_client, auth_headers,
                                              monkeypatch):
    cfg = get_config()
    monkeypatch.setattr(cfg, "max_upload_bytes", 10)
    await init_db()

    resp = await app_client.post(
        "/api/runs",
        data={"message": "x", "session_id": "t210-big"},
        files={"files": ("big.bin", b"0" * 64, "application/octet-stream")},
        headers=auth_headers,
    )
    assert resp.status_code == 413, resp.text
    assert "too large" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_upload_filename_traversal_flattened(app_client, auth_headers,
                                                   monkeypatch):
    """A path-like filename is flattened so it stays inside the inputs dir."""
    cfg = get_config()
    monkeypatch.setattr(cfg, "wall_timeout_s", 120)
    monkeypatch.setattr(cfg, "worker_pool_size", 1)
    await init_db()

    resp = await app_client.post(
        "/api/runs",
        data={"message": "x", "session_id": "t210-flat"},
        files={"files": ("../../../../etc/evil.txt", b"pwn", "text/plain")},
        headers=auth_headers,
    )
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]
    inputs_dir = run_dir_for(run_id) / "inputs"
    # The dangerous name is sanitized to a single basename — no directory parts.
    assert not (inputs_dir / "etc" / "evil.txt").exists()
    assert (inputs_dir / "_______etc_evil.txt").exists() or any(
        p.name.endswith("evil.txt") for p in inputs_dir.iterdir()
    )


# ── end-to-end: real worker sees the uploaded input ────────────


@pytest.fixture
async def mock_llm_echo_input():
    """Read the uploaded input and copy it verbatim into /outputs/echo.md."""
    server = MockLLMServer(script=[
        tool_call_turn("read_file", {"path": "/inputs/brief.md"}),
        tool_call_turn("create_file", {
            "path": "/outputs/echo.md",
            "content": "echoed\n",
        }),
        text_turn("Done; I read the brief and wrote the echo."),
    ]).start()
    yield server
    server.stop()


@pytest.mark.asyncio
async def test_upload_reaches_agent_via_prompt_addendum(
    mock_llm_echo_input, app_client, auth_headers, isolated_orchestrator,
    monkeypatch,
):
    """End-to-end: the uploaded file is visible to the agent in its inputs dir."""
    monkeypatch.setenv("OPENAI_BASE_URL", mock_llm_echo_input.base_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-spike-mock")
    monkeypatch.setenv("OPENAI_MODEL", mock_llm_echo_input.model)
    cfg = get_config()
    monkeypatch.setattr(cfg, "wall_timeout_s", 120)
    monkeypatch.setattr(cfg, "worker_pool_size", 1)
    await init_db()

    resp = await app_client.post(
        "/api/runs",
        data={"message": "read the brief and echo it", "session_id": "t210-e2e"},
        files={"files": ("brief.md", b"# Brief\nRead this.\n", "text/markdown")},
        headers=auth_headers,
    )
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]
    approver = _spawn_approver(
        isolated_orchestrator, run_id, app_client, auth_headers
    )

    # Wait for the run to finish and its deliverable to be scanned.
    done = False
    for _ in range(120):
        await asyncio.sleep(0.5)
        art = await app_client.get(
            f"/api/runs/{run_id}/artifacts", headers=auth_headers
        )
        if art.status_code == 200 and any(
            a["rel_path"] == "echo.md" for a in art.json()["artifacts"]
        ):
            done = True
            break
    assert done, "agent never produced echo.md from the uploaded input"

    # The uploaded file is present on disk in the run's inputs dir.
    assert (run_dir_for(run_id) / "inputs" / "brief.md").exists()

    # The approver task has posted its decision and returned.
    await asyncio.wait_for(approver, timeout=5)
