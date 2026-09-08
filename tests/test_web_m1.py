"""M1 end-to-end test for the web platform run chain (mock LLM, zero API cost).

Exercises: API submit → worker subprocess → BenchmarkSession run → trajectory
written to the per-run directory → SSE/relay can replay it. Uses the scripted
mock endpoint from deploy.huggingface.mock_llm so it needs no real key.

Run with::
    uv run pytest tests/test_web_m1.py -q
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal

import pytest

from deploy.huggingface.mock_llm import MockLLMServer, text_turn, tool_call_turn
from server.config import get_config, run_dir_for
from server.relay import trajectory_records
from server.store import init_db


@pytest.fixture
async def mock_llm():
    server = MockLLMServer(script=[
        tool_call_turn("create_file", {
            "path": "/outputs/report.md",
            "content": "# Report\n\nDeliverable written by create_file.\n",
        }),
        text_turn("Report written to /outputs/report.md."),
    ]).start()
    yield server
    server.stop()


@pytest.fixture
async def app_client():
    from httpx import ASGITransport, AsyncClient

    from server.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def auth_headers(app_client):
    """Register + log in a fixture user so authed run routes can be exercised.

    T2.7 moved /api/runs behind get_current_user; M1 tests must carry a token.
    The token is bound to this fixture's user and is accepted by every run route.
    """
    from server.store import init_db

    await init_db()
    pwd = "Str0ngPass1"
    reg = await app_client.post(
        "/api/auth/register", json={"username": "m1-user", "password": pwd}
    )
    # A 409 just means a prior test in this process already created the user.
    assert reg.status_code in (201, 409), reg.text
    login = await app_client.post(
        "/api/auth/login", json={"username": "m1-user", "password": pwd}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _spawn_approver(run_id: str, client, headers):
    """Answer the P3.2 approval gate the way a user would.

    Since the gate landed (P3.2), a worker's ``create_file`` suspends on
    ``approval_requested`` until a decision arrives — an old e2e that never
    answers would hang the worker for the gate's 300s timeout. This task
    subscribes to the run's event fan-out and approves ``once`` via the real
    API route, so the approval path itself stays exercised.
    """
    from server.orchestrator import get_orchestrator

    orch = get_orchestrator()

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


@pytest.mark.asyncio
async def test_m1_run_chain_writes_trajectory(mock_llm, app_client, auth_headers, monkeypatch):
    # Point the worker's env at the mock endpoint.
    monkeypatch.setenv("OPENAI_BASE_URL", mock_llm.base_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-spike-mock")
    monkeypatch.setenv("OPENAI_MODEL", mock_llm.model)

    # Make the orchestrator fast for the test.
    cfg = get_config()
    monkeypatch.setattr(cfg, "wall_timeout_s", 120)
    monkeypatch.setattr(cfg, "worker_pool_size", 1)

    await init_db()

    prompt = (
        "Read /inputs/brief.md and write a short summary to /outputs/report.md "
        "using create_file."
    )
    resp = await app_client.post("/api/runs", json={
        "message": prompt,
        "session_id": "test-session",
    }, headers=auth_headers)
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    approver = _spawn_approver(run_id, app_client, auth_headers)

    # Poll the trajectory until the run finishes (summary.json appears).
    run_dir = run_dir_for(run_id)
    summary_path = run_dir / "summary.json"
    for _ in range(120):
        if summary_path.exists():
            break
        await asyncio.sleep(0.5)
    assert summary_path.exists(), "worker did not finish within timeout"

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["final_answer"], "final answer was empty"

    # Trajectory must be replayable and carry tool calls + usage.
    records = trajectory_records(run_id)
    types = {r.get("t") for r in records}
    assert "start" in types
    assert any(r.get("t") == "llm" and r.get("tool_calls") for r in records), \
        "no tool_call recorded in trajectory"
    assert any(r.get("t") == "llm" and r.get("usage") for r in records), \
        "no usage recorded in trajectory"
    # Tool arguments must be present (L3 参数摘要 comes from the trajectory,
    # never from on_tool_call — tech-stack.md §5.2).
    llm_with_calls = [r for r in records if r.get("t") == "llm" and r.get("tool_calls")]
    assert llm_with_calls[0]["tool_calls"][0].get("args"), \
        "tool args missing from trajectory"

    # Replay via the /trace endpoint honours the line-number cursor.
    trace = await app_client.get(f"/api/runs/{run_id}/trace", headers=auth_headers)
    assert trace.status_code == 200
    body = trace.json()
    assert len(body["records"]) == len(records)
    # A cursor past the end yields nothing (dense line-number semantics).
    tail = await app_client.get(
        f"/api/runs/{run_id}/trace?after={len(records)}", headers=auth_headers
    )
    assert tail.json()["records"] == []

    # The approver task has posted its decision and returned.
    await asyncio.wait_for(approver, timeout=5)


@pytest.mark.asyncio
async def test_worker_killed_api_survives(mock_llm, app_client, auth_headers, monkeypatch):
    """Killing a worker subprocess must not take the API down.

    This is the "worker 崩溃不影响主服务" gate (plan.md T1.11): the run-per-
    subprocess design means a dead worker is contained to that run, and the API
    keeps serving (and can still accept new runs).
    """
    monkeypatch.setenv("OPENAI_BASE_URL", mock_llm.base_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-spike-mock")
    monkeypatch.setenv("OPENAI_MODEL", mock_llm.model)
    cfg = get_config()
    monkeypatch.setattr(cfg, "wall_timeout_s", 120)
    monkeypatch.setattr(cfg, "worker_pool_size", 1)
    await init_db()

    from server.orchestrator import get_orchestrator

    resp = await app_client.post("/api/runs", json={
        "message": "write a report to /outputs/kill.md using create_file",
        "session_id": "kill-session",
    }, headers=auth_headers)
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]

    # Wait for the worker to be registered, then SIGKILL its process group.
    orch = get_orchestrator()
    handle = None
    for _ in range(40):
        handle = orch._handles.get(run_id)
        if handle is not None and handle.proc.returncode is None:
            break
        await asyncio.sleep(0.25)
    if handle is not None and handle.proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(handle.proc.pid), signal.SIGKILL)

    # The API must still be healthy and able to accept work.
    health = await app_client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    again = await app_client.post("/api/runs", json={
        "message": "a second run after the kill",
        "session_id": "kill-session-2",
    }, headers=auth_headers)
    assert again.status_code == 202
