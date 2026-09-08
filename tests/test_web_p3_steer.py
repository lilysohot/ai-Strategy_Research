"""P3.1 live-steering tests (plan cli-web-parity.md §6.2 / §7).

Chain under test::

    POST /api/runs/{id}/steer  →  orchestrator stdin JSONL
    →  worker._stdin_watch  →  SteerInbox  →  SteerObserver.on_turn_end
    →  Intervention(inject_messages)  →  next LLM request carries the text

Egress safety (§7 出口统一脱敏): the steer_queued SSE event must be redacted.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import uuid
from types import SimpleNamespace

import pytest

from frontier_agent.core.loop_types import Intervention

# — slice 1: SteerInbox + SteerObserver + worker stdin channel ——————————


def test_inbox_fifo_blank_ignored() -> None:
    from server.steer import SteerInbox

    inbox = SteerInbox()
    inbox.enqueue("")
    inbox.enqueue("   ")
    inbox.enqueue("first")
    inbox.enqueue("second")
    assert inbox.drain() == ["first", "second"]
    assert inbox.drain() == []


async def test_observer_injects_at_tool_boundary() -> None:
    from server.steer import SteerInbox, SteerObserver

    inbox = SteerInbox()
    inbox.enqueue("focus on the tests")
    obs = SteerObserver(inbox)
    # notify_observers only collects returns from critical observers, and does
    # a strict isinstance(Intervention) check — both are hard requirements.
    assert obs.critical is True
    out = await obs.on_turn_end(SimpleNamespace(tool_calls=[{"id": "call_1"}]))
    assert isinstance(out, Intervention)
    assert out.inject_messages == ["focus on the tests"]


async def test_observer_holds_steers_without_tool_calls() -> None:
    from server.steer import SteerInbox, SteerObserver

    # No tool_calls means the model is finishing; the steers stay queued
    # instead of dangling after a run that is about to stop (apodex semantics).
    inbox = SteerInbox()
    inbox.enqueue("hold me")
    obs = SteerObserver(inbox)
    out = await obs.on_turn_end(SimpleNamespace(tool_calls=None))
    assert out is None
    assert inbox.drain() == ["hold me"]


async def test_observer_empty_inbox_is_none() -> None:
    from server.steer import SteerInbox, SteerObserver

    obs = SteerObserver(SteerInbox())
    out = await obs.on_turn_end(SimpleNamespace(tool_calls=[{"id": "c"}]))
    assert out is None


async def test_stdin_watch_enqueues_steer_and_stop(monkeypatch) -> None:
    from server.steer import SteerInbox
    from server.worker import _stdin_watch, _StopFlag

    inbox = SteerInbox()
    stop = _StopFlag()
    payload = "\n".join([
        json.dumps({"action": "steer", "message": "  do X  "}),
        json.dumps({"action": "steer", "message": "   "}),  # blank → ignored
        json.dumps({"action": "stop"}),
        "",
    ])
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    task = asyncio.create_task(_stdin_watch(stop, inbox))
    for _ in range(200):
        if stop.requested:
            break
        await asyncio.sleep(0.01)
    assert stop.requested, "stop line never processed"
    # The stop line follows the steer lines, so the steer is enqueued by now.
    assert inbox.drain() == ["do X"]
    task.cancel()


# — slice 2: orchestrator.steer + control route + steer_queued fan-out —————


class _FakeStdin:
    """Minimal ``proc.stdin`` stand-in capturing written JSONL lines."""

    def __init__(self) -> None:
        self.data = b""

    def write(self, data: bytes) -> int:
        self.data += data
        return len(data)

    async def drain(self) -> None:
        return None


def _live_handle(orch, run_id: str):
    """Register a handle whose worker process is alive (fake stdin pipe)."""
    from server.orchestrator import RunHandle

    proc = SimpleNamespace(returncode=None, stdin=_FakeStdin())
    handle = RunHandle(run_id=run_id, session_id="p3-session", proc=proc)
    orch._handles[run_id] = handle
    return handle


async def test_orchestrator_steer_writes_stdin_and_publishes() -> None:
    import server.orchestrator as orch_mod

    orch = orch_mod.Orchestrator()
    handle = _live_handle(orch, "run-steer-live")
    q = orch.subscribe(handle.run_id)

    seq = await orch.steer(handle.run_id, "key sk-abcdef123456 now stop")
    assert seq == 1
    line = json.loads(handle.proc.stdin.data.decode().strip())
    assert line == {"action": "steer", "message": "key sk-abcdef123456 now stop"}

    event = await asyncio.wait_for(q.get(), timeout=1)
    assert event["type"] == "steer_queued"
    assert event["seq"] == 1
    # Egress redaction (§7): the raw secret never reaches the SSE payload.
    assert "sk-abcdef123456" not in event["message"]
    assert "(redacted)" in event["message"]

    # Per-run seq increments so clients can order queued steers.
    assert await orch.steer(handle.run_id, "second") == 2
    event2 = await asyncio.wait_for(q.get(), timeout=1)
    assert event2["seq"] == 2


async def test_orchestrator_steer_unknown_or_dead_run() -> None:
    import server.orchestrator as orch_mod

    orch = orch_mod.Orchestrator()
    assert await orch.steer("no-such-run", "x") is None
    handle = _live_handle(orch, "run-steer-dead")
    handle.proc.returncode = 0
    assert await orch.steer(handle.run_id, "x") is None


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
        "/api/auth/register", json={"username": "p3-steer-user", "password": pwd}
    )
    assert reg.status_code in (201, 409), reg.text
    login = await app_client.post(
        "/api/auth/login", json={"username": "p3-steer-user", "password": pwd}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
def isolated_orchestrator(monkeypatch):
    import server.orchestrator as orch_mod

    orch = orch_mod.Orchestrator()
    monkeypatch.setattr(orch_mod, "_orchestrator", orch)
    return orch


def _spawn_approver(orch, run_id: str, client, headers):
    """Answer the P3.2 approval gate the way a user would.

    Since the gate landed, the scripted ``create_file`` suspends the worker on
    ``approval_requested`` until a decision arrives; this task approves
    ``once`` via the real API route so the e2e keeps exercising the approval
    path instead of hanging out the gate's 300s timeout.
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


async def _create_owned_run(auth_headers, *, status: str = "running") -> str:
    from server.security import decode_access_token
    from server.store import create_run

    token = auth_headers["Authorization"].removeprefix("Bearer ").strip()
    user_id = decode_access_token(token)
    run_id = uuid.uuid4()
    await create_run(
        run_id=run_id,
        session_id=uuid.uuid4(),
        user_id=user_id,
        prompt="p",
        pipeline_id="stateful-react-agent",
        run_dir="/tmp/p3-steer-test",
        status=status,
    )
    return run_id.hex


async def test_steer_route_requires_owned_run(app_client, auth_headers) -> None:
    resp = await app_client.post(
        f"/api/runs/{uuid.uuid4()}/steer", json={"message": "x"}, headers=auth_headers
    )
    assert resp.status_code == 404


async def test_steer_route_409_when_worker_gone(
    app_client, auth_headers, isolated_orchestrator
) -> None:
    # The run row exists (owned) but no live worker handle → not steerable.
    run_id = await _create_owned_run(auth_headers)
    resp = await app_client.post(
        f"/api/runs/{run_id}/steer", json={"message": "x"}, headers=auth_headers
    )
    assert resp.status_code == 409


async def test_steer_route_rejects_blank(
    app_client, auth_headers, isolated_orchestrator
) -> None:
    run_id = await _create_owned_run(auth_headers)
    _live_handle(isolated_orchestrator, run_id)
    for message in ("", "   "):
        resp = await app_client.post(
            f"/api/runs/{run_id}/steer", json={"message": message},
            headers=auth_headers,
        )
        assert resp.status_code == 422


async def test_steer_route_queues_into_worker(
    app_client, auth_headers, isolated_orchestrator
) -> None:
    orch = isolated_orchestrator
    run_id = await _create_owned_run(auth_headers)
    handle = _live_handle(orch, run_id)
    q = orch.subscribe(run_id)

    resp = await app_client.post(
        f"/api/runs/{run_id}/steer", json={"message": "check the edge cases"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["queued"] is True
    assert body["seq"] == 1
    # stdin got the worker-side action line.
    line = json.loads(handle.proc.stdin.data.decode().strip())
    assert line == {"action": "steer", "message": "check the edge cases"}
    # SSE subscribers see the steer_queued fan-out.
    event = await asyncio.wait_for(q.get(), timeout=1)
    assert event["type"] == "steer_queued"
    assert event["message"] == "check the edge cases"


# — slice 3: end-to-end — the steer text reaches a follow-up LLM request ———


@pytest.fixture
async def mock_llm_steer():
    """Turn 1 hangs ~2s (time to steer) and makes a tool call, so its turn
    boundary is a safe injection point; turn 2 answers and ends the run."""
    from deploy.huggingface.mock_llm import MockLLMServer, Turn, text_turn

    script = [
        Turn(
            content="",
            tool_calls=[{
                "id": "call_steer00001",
                "type": "function",
                "function": {
                    "name": "create_file",
                    "arguments": json.dumps(
                        {"path": "/outputs/steer.md", "content": "work"}
                    ),
                },
            }],
            delay_s=2.0,
        ),
        text_turn("final answer"),
    ]
    server = MockLLMServer(script=script).start()
    yield server
    server.stop()


@pytest.mark.asyncio
async def test_steer_reaches_next_llm_request(
    mock_llm_steer, app_client, auth_headers, isolated_orchestrator, monkeypatch
) -> None:
    """§6.2 acceptance: a mid-run steer is injected as the next user message."""
    from server.config import get_config
    from server.security import decode_access_token
    from server.store import get_run, init_db

    monkeypatch.setenv("OPENAI_BASE_URL", mock_llm_steer.base_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-spike-mock")
    monkeypatch.setenv("OPENAI_MODEL", mock_llm_steer.model)
    cfg = get_config()
    monkeypatch.setattr(cfg, "wall_timeout_s", 120)
    monkeypatch.setattr(cfg, "worker_pool_size", 1)
    await init_db()

    resp = await app_client.post("/api/runs", json={
        "message": "start the work",
        "session_id": "p3-steer-e2e",
    }, headers=auth_headers)
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]

    orch = isolated_orchestrator

    # Turn 1's tool call (create_file) now suspends on the approval gate
    # (P3.2) — answer it while the run proceeds.
    approver = _spawn_approver(orch, run_id, app_client, auth_headers)
    for _ in range(60):
        handle = orch._handles.get(run_id)
        if handle is not None and handle.proc.returncode is None:
            break
        await asyncio.sleep(0.25)
    assert handle is not None, "worker never registered"
    await asyncio.sleep(1.0)  # let turn 1's LLM call hang open

    marker = "steer-marker-p31-XYZ"
    steer = await app_client.post(
        f"/api/runs/{run_id}/steer", json={"message": marker}, headers=auth_headers
    )
    assert steer.status_code == 200, steer.text
    assert steer.json()["queued"] is True

    user_id = decode_access_token(
        auth_headers["Authorization"].removeprefix("Bearer ").strip()
    )
    for _ in range(120):
        run = await get_run(run_id=uuid.UUID(run_id), user_id=user_id)
        if run is not None and run.status in ("completed", "failed", "stopped"):
            break
        await asyncio.sleep(0.5)
    assert run is not None
    # A canned mock never calls the workflow's terminal tool, so the stateful
    # policy ends the run with its "no_tool" stop — expected here. What
    # matters: the run was not user-stopped and the steer reached the model.
    assert run.status in ("completed", "stopped")
    assert run.stopped_by != "user_stop"
    # The gate opened — the approver's POST must have landed.
    await asyncio.wait_for(approver, timeout=5)

    # The mock records every /chat/completions payload: a follow-up request
    # must carry the steer text (injected as a user message at the boundary).
    carried = [
        r for r in mock_llm_steer.requests
        if marker in json.dumps(r.get("messages", []))
    ]
    assert carried, "steer text never reached a follow-up LLM request"
