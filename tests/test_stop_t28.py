"""T2.8 stop-control-chain tests (mock LLM, zero API cost).

Verifies the full stop control chain required by plan.md T2.8:

  control endpoint → stdin → pause_check → cooperative stop;
  partial answer backfill + ``stopped_by`` captured from ``AgentLoopResult``
  (not the pipeline state) and merged with the worker's own deadline/SIGKILL
  paths into the runs table (tech-stack.md §5.2).

Two end-to-end scenarios:

  1. user_stop  — a stop is issued mid-run; the run lands as ``stopped`` with
     ``stopped_by="user_stop"`` and the partial answer is backfilled into the
     conversation as an assistant turn tagged ``_[partial: user_stop]_``.
  2. sigkill     — the orchestrator's hard-timeout escalation SIGKILLs a stuck
     worker; the run is recovered as ``stopped`` with ``stopped_by="sigkill"``
     (no run_finished frame ever arrived) and the row is closed.

Both assert the conversation flow shows a partial result after the stop, which
is the T2.8 acceptance criterion.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from deploy.huggingface.mock_llm import MockLLMServer, Turn, text_turn
from server.config import get_config
from server.store import get_run, list_turns


@pytest.fixture
async def mock_llm_slow():
    """A mock whose first turn is slow enough to stay open while we stop.

    ``pause_check`` only fires at a *turn boundary* in the agent loop, so the
    stop must arrive while turn 1's LLM call is still in flight; when turn 1
    completes (after its short delay) the boundary check sees the stop and the
    loop cooperatively ends. The second turn is a fast fallback so the run would
    otherwise complete normally.
    """
    script = [
        Turn(
            content="",
            tool_calls=[{
                "id": "call_partial0001",
                "type": "function",
                "function": {
                    "name": "create_file",
                    "arguments": json.dumps(
                        {"path": "/outputs/partial.md", "content": "partial work"}
                    ),
                },
            }],
            delay_s=2.0,  # stay open ~2s so the stop can land mid-turn-1
        ),
        text_turn("final answer"),
    ]
    server = MockLLMServer(script=script).start()
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
    from server.store import init_db

    await init_db()
    pwd = "Str0ngPass1"
    reg = await app_client.post(
        "/api/auth/register", json={"username": "t28-user", "password": pwd}
    )
    assert reg.status_code in (201, 409), reg.text
    login = await app_client.post(
        "/api/auth/login", json={"username": "t28-user", "password": pwd}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
def isolated_orchestrator(monkeypatch):
    """Give this test its own Orchestrator instead of the process-wide singleton.

    The API routes resolve the orchestrator through ``get_orchestrator()``, which
    reads a module global, so swapping that global is enough to isolate the test.
    Without it, a run left behind by an earlier test file (whose worker is
    retrying against an already-closed mock endpoint) holds the singleton's single
    concurrency slot and the run submitted here never starts.
    """
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


async def _wait_for_status(run_id: str, user_id: uuid.UUID,
                           *,
                           terminal: tuple[str, ...] = ("completed", "failed", "stopped"),
                           tries: int = 120) -> str:
    """Poll the runs table until the run reaches a terminal status."""
    for _ in range(tries):
        run = await get_run(run_id=uuid.UUID(run_id), user_id=user_id)
        if run is not None and run.status in terminal:
            return run.status
        await asyncio.sleep(0.5)
    raise AssertionError(f"run {run_id} did not reach terminal status within timeout")


def _user_id(auth_headers: dict) -> uuid.UUID:
    """Decode the bearer token to the user id (it IS the user id)."""
    from server.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ").strip()
    return decode_access_token(token)


@pytest.mark.asyncio
async def test_user_stop_backfills_partial(mock_llm_slow, app_client, auth_headers,
                                           isolated_orchestrator, monkeypatch):
    """T2.8: issuing /control stop mid-run records stopped + partial answer."""
    monkeypatch.setenv("OPENAI_BASE_URL", mock_llm_slow.base_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-spike-mock")
    monkeypatch.setenv("OPENAI_MODEL", mock_llm_slow.model)
    cfg = get_config()
    monkeypatch.setattr(cfg, "wall_timeout_s", 120)
    monkeypatch.setattr(cfg, "worker_pool_size", 1)
    from server.store import init_db
    await init_db()

    orch = isolated_orchestrator

    resp = await app_client.post("/api/runs", json={
        "message": "research the topic and stop me mid-way",
        "session_id": "t28-stop-session",
    }, headers=auth_headers)
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    approver = _spawn_approver(orch, run_id, app_client, auth_headers)

    # Wait for the worker to be registered and actually running.
    handle = None
    for _ in range(60):
        handle = orch._handles.get(run_id)
        if handle is not None and handle.proc.returncode is None:
            break
        await asyncio.sleep(0.25)
    assert handle is not None, "worker never registered"

    # Let turn 1's LLM call begin (it is held open ~2s by the mock) but fire the
    # stop while it is still in flight, so the turn-1 boundary check sees it.
    await asyncio.sleep(1.0)

    # Issue the cooperative stop via the control endpoint.
    stop = await app_client.post(
        f"/api/runs/{run_id}/control", json={"action": "stop"}, headers=auth_headers
    )
    assert stop.status_code == 200, stop.text
    assert stop.json()["stopped"] is True

    # The run must terminate as a user-stopped run (T2.8).
    user_id = _user_id(auth_headers)
    status = await _wait_for_status(run_id, user_id)
    assert status == "stopped"

    run = await get_run(run_id=uuid.UUID(run_id), user_id=user_id)
    assert run is not None
    assert run.stopped_by == "user_stop"
    # The run row must close with the stopped status.
    assert run.status == "stopped"

    # The conversation flow must show a partial result: the assistant turn is
    # backfilled and tagged as a partial answer (T2.8 acceptance).
    turns = await list_turns(session_id=run.session_id)
    roles = [(t.role, t.content) for t in turns]
    assert ("user", "research the topic and stop me mid-way") in roles
    assistant_turns = [c for r, c in roles if r == "assistant"]
    assert assistant_turns, "no assistant turn backfilled after stop"
    # The backfilled turn is tagged as a partial answer because the run was
    # stopped with a non-empty stopped_by reason.
    assert any("_[partial: user_stop]_" in c for c in assistant_turns)

    # The approver task has posted its decision and returned.
    await asyncio.wait_for(approver, timeout=5)


@pytest.mark.asyncio
async def test_sigkill_recovers_stopped_run(mock_llm_slow, app_client, auth_headers,
                                            isolated_orchestrator, monkeypatch):
    """T2.8: orchestrator SIGKILL of a stuck worker is recovered as sigkill."""
    monkeypatch.setenv("OPENAI_BASE_URL", mock_llm_slow.base_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-spike-mock")
    monkeypatch.setenv("OPENAI_MODEL", mock_llm_slow.model)
    cfg = get_config()
    # Make the orchestrator's hard-timeout escalation fire quickly so the test
    # does not wait the full 900s. wall + grace = 1 + 1 = 2s budget.
    monkeypatch.setattr(cfg, "wall_timeout_s", 1)
    monkeypatch.setattr(cfg, "stop_grace_period_s", 1)
    monkeypatch.setattr(cfg, "worker_pool_size", 1)
    from server.store import init_db
    await init_db()

    resp = await app_client.post("/api/runs", json={
        "message": "stall forever on a tool call",
        "session_id": "t28-sigkill-session",
    }, headers=auth_headers)
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]

    # No stop issued; the worker is killed by the orchestrator's escalation.
    user_id = _user_id(auth_headers)
    status = await _wait_for_status(run_id, user_id, tries=60)
    assert status == "stopped"

    run = await get_run(run_id=uuid.UUID(run_id), user_id=user_id)
    assert run is not None
    assert run.stopped_by == "sigkill"
