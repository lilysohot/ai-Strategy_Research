"""P3.2 approval-gate tests (plan cli-web-parity.md §6.1 / §7).

Chain under test::

    ApprovalObserver.on_tool_call  →  assess_with_rules (apodex semantics)
    →  deny: hard block, no event  /  confirm: approval_requested event
    →  ApprovalGate.wait (suspends the agent loop)  →  stdin
    {"action":"approve","approval_id":...,"decision":...}  →  resolve

Hard rules (§6.1): a deny never reaches the user prompt (cannot be bypassed by
any decision), a pending approval times out fail-closed (→ reject), and the
synthetic skip texts must match server.bridge._SYNTHETIC_RESULT_MARKERS so the
terminal renders them as skipped.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import threading
import uuid
from types import SimpleNamespace

import pytest

# — slice 1: ApprovalGate core (open / wait / resolve) ——————————————————


async def test_gate_open_ids_are_unique_and_wait_blocks_until_resolved() -> None:
    from server.approval import ApprovalDecision, ApprovalGate

    gate = ApprovalGate()
    a1 = gate.open()
    a2 = gate.open()
    assert a1 and a2 and a1 != a2

    waiter = asyncio.create_task(gate.wait(a1, timeout=5.0))
    await asyncio.sleep(0)
    assert not waiter.done()

    assert gate.resolve(a1, ApprovalDecision(decision="once")) is True
    decision = await asyncio.wait_for(waiter, timeout=2.0)
    assert decision.decision == "once"
    assert decision.replacement_command is None


async def test_gate_wait_times_out_fail_closed_to_reject() -> None:
    from server.approval import ApprovalGate

    gate = ApprovalGate()
    aid = gate.open()
    decision = await gate.wait(aid, timeout=0.05)
    assert decision.decision == "reject"


async def test_gate_resolve_unknown_id_returns_false() -> None:
    from server.approval import ApprovalDecision, ApprovalGate

    gate = ApprovalGate()
    assert gate.resolve("missing", ApprovalDecision(decision="once")) is False


async def test_gate_resolve_from_another_thread_wakes_waiter() -> None:
    from server.approval import ApprovalDecision, ApprovalGate

    # The stdin watcher runs in a plain reader thread; the decision must wake
    # the loop-side waiter via call_soon_threadsafe.
    gate = ApprovalGate()
    aid = gate.open()
    waiter = asyncio.create_task(gate.wait(aid, timeout=5.0))
    await asyncio.sleep(0)

    t = threading.Thread(
        target=gate.resolve,
        args=(aid, ApprovalDecision(decision="reject")),
    )
    t.start()
    t.join()

    decision = await asyncio.wait_for(waiter, timeout=2.0)
    assert decision.decision == "reject"


async def test_gate_second_resolve_for_same_id_returns_false() -> None:
    from server.approval import ApprovalDecision, ApprovalGate

    gate = ApprovalGate()
    aid = gate.open()
    assert gate.resolve(aid, ApprovalDecision(decision="once")) is True
    assert gate.resolve(aid, ApprovalDecision(decision="reject")) is False


async def test_gate_resolve_after_wait_timeout_returns_false() -> None:
    from server.approval import ApprovalDecision, ApprovalGate

    # A late click on an already-timed-out dialog must not pretend success.
    gate = ApprovalGate()
    aid = gate.open()
    assert (await gate.wait(aid, timeout=0.05)).decision == "reject"
    assert gate.resolve(aid, ApprovalDecision(decision="once")) is False


async def test_gate_session_memory_scopes() -> None:
    from server.approval import ApprovalGate

    # session_all/persist remember the tool name; session_bash remembers the
    # exact command (prefix matching would leak "pytest -q" into "pytest -q -x").
    gate = ApprovalGate()
    gate.remember("bash", {"command": "pytest -q"}, scope="session_bash")
    gate.remember("create_file", {"path": "/outputs/a.md"}, scope="session_all")
    assert gate.is_allowed("bash", {"command": "pytest -q"})
    assert not gate.is_allowed("bash", {"command": "pytest -q -x"})
    assert not gate.is_allowed("bash", {"command": "ls"})
    assert gate.is_allowed("create_file", {"path": "/outputs/b.md"})


async def _wait_for_event(events: list[dict]) -> dict:
    for _ in range(500):
        if events:
            return events[0]
        await asyncio.sleep(0.01)
    raise AssertionError("no approval_requested event emitted")


# — slice 2: ApprovalObserver semantics (apodex assess_with_rules reused) —


async def test_observer_deny_is_hard_blocked_without_event(tmp_path) -> None:
    from server.approval import ApprovalGate, ApprovalObserver

    events: list[dict] = []
    obs = ApprovalObserver(ApprovalGate(), events.append, cwd=str(tmp_path))
    out = await obs.on_tool_call(
        None,
        {"id": "c1", "name": "write_file", "args": {"path": "/etc/passwd", "content": "x"}},
    )
    # §6.1 hard rule: a deny never reaches the approval flow at all, so no user
    # decision can bypass it — the only visible effect is the skipped result.
    assert out is not None
    assert out.skip_with_result.startswith("[blocked by safety policy")
    assert events == []


async def test_observer_confirm_emits_request_and_once_allows(tmp_path) -> None:
    from server.approval import ApprovalDecision, ApprovalGate, ApprovalObserver

    events: list[dict] = []
    gate = ApprovalGate()
    obs = ApprovalObserver(gate, events.append, cwd=str(tmp_path), timeout=5.0)
    task = asyncio.create_task(
        obs.on_tool_call(
            None,
            {
                "id": "c2",
                "name": "create_file",
                "args": {"path": "/outputs/report.md", "content": "hi"},
            },
        )
    )
    req = await _wait_for_event(events)
    assert req["type"] == "approval_requested"
    assert req["tool_name"] == "create_file"
    assert req["target"] == "/outputs/report.md"
    assert req["risk"] == "normal"
    assert req["approval_id"]

    assert gate.resolve(req["approval_id"], ApprovalDecision(decision="once")) is True
    out = await asyncio.wait_for(task, timeout=2.0)
    assert out is None  # approved → the call executes
    resolved = events[-1]
    assert resolved["type"] == "approval_resolved"
    assert resolved["approval_id"] == req["approval_id"]
    assert resolved["decision"] == "once"


async def test_observer_pure_reject_uses_marker_text(tmp_path) -> None:
    from server.approval import ApprovalDecision, ApprovalGate, ApprovalObserver

    events: list[dict] = []
    gate = ApprovalGate()
    obs = ApprovalObserver(gate, events.append, cwd=str(tmp_path), timeout=5.0)
    task = asyncio.create_task(
        obs.on_tool_call(
            None,
            {"id": "c3", "name": "create_file", "args": {"path": "/outputs/a.md", "content": "hi"}},
        )
    )
    req = await _wait_for_event(events)
    gate.resolve(req["approval_id"], ApprovalDecision(decision="reject"))
    out = await asyncio.wait_for(task, timeout=2.0)
    # Must match bridge._SYNTHETIC_RESULT_MARKERS so the terminal renders it
    # as skipped, and apodex's plain-reject wording (stop the task).
    assert out is not None
    assert out.skip_with_result == "[user rejected this create_file call — task stopped]"


async def test_observer_reject_with_replacement_redirects(tmp_path) -> None:
    from server.approval import ApprovalDecision, ApprovalGate, ApprovalObserver

    events: list[dict] = []
    gate = ApprovalGate()
    obs = ApprovalObserver(gate, events.append, cwd=str(tmp_path), timeout=5.0)
    task = asyncio.create_task(
        obs.on_tool_call(
            None,
            {"id": "c4", "name": "create_file", "args": {"path": "/outputs/a.md", "content": "hi"}},
        )
    )
    req = await _wait_for_event(events)
    gate.resolve(
        req["approval_id"],
        ApprovalDecision(decision="reject", replacement_command="write the tests first"),
    )
    out = await asyncio.wait_for(task, timeout=2.0)
    assert out is not None
    assert out.skip_with_result.startswith("[The user declined to run this create_file call. ")
    assert "write the tests first" in out.skip_with_result


async def test_observer_safe_tool_passes_through_without_event(tmp_path) -> None:
    from server.approval import ApprovalGate, ApprovalObserver

    events: list[dict] = []
    obs = ApprovalObserver(ApprovalGate(), events.append, cwd=str(tmp_path))
    out = await obs.on_tool_call(
        None,
        {"id": "c5", "name": "glob_search", "args": {"pattern": "**/*.py"}},
    )
    assert out is None
    assert events == []


async def test_observer_danger_call_marks_risk_high(tmp_path) -> None:
    from server.approval import ApprovalDecision, ApprovalGate, ApprovalObserver

    events: list[dict] = []
    gate = ApprovalGate()
    target = tmp_path / "a.txt"
    target.write_text("x", encoding="utf-8")
    obs = ApprovalObserver(gate, events.append, cwd=str(tmp_path), timeout=5.0)
    task = asyncio.create_task(
        obs.on_tool_call(
            None,
            {"id": "c6", "name": "delete_file", "args": {"path": str(target)}},
        )
    )
    req = await _wait_for_event(events)
    assert req["risk"] == "high"
    gate.resolve(req["approval_id"], ApprovalDecision(decision="once"))
    assert await asyncio.wait_for(task, timeout=2.0) is None


async def test_observer_persists_session_all_for_rest_of_run(tmp_path) -> None:
    from server.approval import ApprovalDecision, ApprovalGate, ApprovalObserver

    events: list[dict] = []
    gate = ApprovalGate()
    call = {"id": "c7", "name": "create_file", "args": {"path": "/outputs/a.md", "content": "hi"}}
    obs = ApprovalObserver(gate, events.append, cwd=str(tmp_path), timeout=5.0)
    task = asyncio.create_task(obs.on_tool_call(None, call))
    req = await _wait_for_event(events)
    gate.resolve(req["approval_id"], ApprovalDecision(decision="session_all"))
    assert await asyncio.wait_for(task, timeout=2.0) is None

    # Second identical tool: remembered in-memory → no new approval round-trip.
    out = await obs.on_tool_call(None, call)
    assert out is None
    assert len([e for e in events if e["type"] == "approval_requested"]) == 1


async def test_observer_timeout_fails_closed(tmp_path) -> None:
    from server.approval import ApprovalGate, ApprovalObserver

    events: list[dict] = []
    obs = ApprovalObserver(ApprovalGate(), events.append, cwd=str(tmp_path), timeout=0.05)
    out = await obs.on_tool_call(
        None,
        {"id": "c8", "name": "create_file", "args": {"path": "/outputs/a.md", "content": "hi"}},
    )
    assert out is not None
    assert out.skip_with_result == "[user rejected this create_file call — task stopped]"
    assert events[-1]["decision"] == "reject"


async def test_observer_event_strings_are_redacted(tmp_path) -> None:
    from server.approval import ApprovalDecision, ApprovalGate, ApprovalObserver

    # §7 出口统一脱敏: even a secret smuggled into an argument that reaches the
    # event payload (here the create_file target) must leave masked.
    events: list[dict] = []
    gate = ApprovalGate()
    secret_path = "/outputs/a.md?api_key=supersecret123"
    obs = ApprovalObserver(gate, events.append, cwd=str(tmp_path), timeout=5.0)
    task = asyncio.create_task(
        obs.on_tool_call(
            None,
            {"id": "c9", "name": "create_file", "args": {"path": secret_path}},
        )
    )
    req = await _wait_for_event(events)
    assert "supersecret123" not in json.dumps(events)
    gate.resolve(req["approval_id"], ApprovalDecision(decision="once"))
    assert await asyncio.wait_for(task, timeout=2.0) is None


# — slice 3: stdin approve branch + orchestrator.approve + control route ——


async def test_stdin_watch_resolves_approval(monkeypatch) -> None:
    from server.approval import ApprovalGate
    from server.worker import _stdin_watch, _StopFlag

    gate = ApprovalGate()
    stop = _StopFlag()
    aid = gate.open()
    payload = "\n".join(
        [
            json.dumps(
                {
                    "action": "approve",
                    "approval_id": aid,
                    "decision": "reject",
                    "replacement_command": "use the sandbox path",
                }
            ),
            json.dumps({"action": "stop"}),
            "",
        ]
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))

    waiter = asyncio.create_task(gate.wait(aid, timeout=5.0))
    task = asyncio.create_task(_stdin_watch(stop, None, gate))
    decision = await asyncio.wait_for(waiter, timeout=2.0)
    assert decision.decision == "reject"
    assert decision.replacement_command == "use the sandbox path"
    task.cancel()


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
    handle = RunHandle(run_id=run_id, session_id="p3-approval", proc=proc)
    orch._handles[run_id] = handle
    return handle


async def test_orchestrator_approve_writes_stdin() -> None:
    import server.orchestrator as orch_mod

    orch = orch_mod.Orchestrator()
    handle = _live_handle(orch, "run-approve-live")
    ok = await orch.approve(
        handle.run_id,
        "aid-1",
        "reject",
        replacement_command="do it in /outputs",
    )
    assert ok is True
    line = json.loads(handle.proc.stdin.data.decode().strip())
    assert line == {
        "action": "approve",
        "approval_id": "aid-1",
        "decision": "reject",
        "replacement_command": "do it in /outputs",
    }

    # Unknown or dead worker → not approvable (route maps this to 409).
    assert await orch.approve("no-such-run", "aid", "once") is False
    handle.proc.returncode = 0
    assert await orch.approve(handle.run_id, "aid", "once") is False


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
        "/api/auth/register", json={"username": "p3-approve-user", "password": pwd}
    )
    assert reg.status_code in (201, 409), reg.text
    login = await app_client.post(
        "/api/auth/login", json={"username": "p3-approve-user", "password": pwd}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
def isolated_orchestrator(monkeypatch):
    import server.orchestrator as orch_mod

    orch = orch_mod.Orchestrator()
    monkeypatch.setattr(orch_mod, "_orchestrator", orch)
    return orch


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
        run_dir="/tmp/p3-approval-test",
        status=status,
    )
    return run_id.hex


async def test_approve_route_requires_owned_run(app_client, auth_headers) -> None:
    resp = await app_client.post(
        f"/api/runs/{uuid.uuid4()}/approve",
        json={"approval_id": "a", "decision": "once"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_approve_route_409_when_worker_gone(
    app_client, auth_headers, isolated_orchestrator
) -> None:
    run_id = await _create_owned_run(auth_headers)
    resp = await app_client.post(
        f"/api/runs/{run_id}/approve",
        json={"approval_id": "a", "decision": "once"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


async def test_approve_route_rejects_bad_decision(
    app_client, auth_headers, isolated_orchestrator
) -> None:
    run_id = await _create_owned_run(auth_headers)
    _live_handle(isolated_orchestrator, run_id)
    resp = await app_client.post(
        f"/api/runs/{run_id}/approve",
        json={"approval_id": "a", "decision": "always"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    # A missing approval id is equally unusable.
    resp = await app_client.post(
        f"/api/runs/{run_id}/approve",
        json={"decision": "once"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_approve_route_forwards_to_worker(
    app_client, auth_headers, isolated_orchestrator
) -> None:
    run_id = await _create_owned_run(auth_headers)
    handle = _live_handle(isolated_orchestrator, run_id)
    resp = await app_client.post(
        f"/api/runs/{run_id}/approve",
        json={"approval_id": "aid-9", "decision": "session_all"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    line = json.loads(handle.proc.stdin.data.decode().strip())
    assert line == {"action": "approve", "approval_id": "aid-9", "decision": "session_all"}


async def test_completed_run_releases_worker_slot(monkeypatch) -> None:
    """A normally-finished run must give its pool slot back.

    A finished worker exits on its own, so ``_kill_handle`` early-returns on
    ``returncode is not None``; if the slot release lives only there, every
    completed run leaks one slot and (with pool size 1) the next run is wedged
    forever at ``_acquire_slot`` — the run never spawns and no SSE sentinel
    ever arrives.
    """
    import asyncio
    from types import SimpleNamespace

    import server.orchestrator as orch_mod

    orch = orch_mod.Orchestrator()
    cfg = orch._cfg
    monkeypatch.setattr(cfg, "worker_pool_size", 1)

    launches: list[str] = []

    async def fake_launch(run_id: str, params: dict, *, history: str = ""):
        launches.append(run_id)
        proc = SimpleNamespace(returncode=0, pid=0)  # already-exited worker
        return orch_mod.RunHandle(run_id=run_id, session_id="s", proc=proc)

    async def fake_pump(handle) -> None:
        return None

    monkeypatch.setattr(orch, "_launch", fake_launch)
    monkeypatch.setattr(orch, "_pump_frames", fake_pump)

    await asyncio.wait_for(orch._spawn(run_id="r1", session_id="s"), timeout=5)
    await asyncio.wait_for(orch._spawn(run_id="r2", session_id="s"), timeout=5)
    assert launches == ["r1", "r2"]


# — slice 4: end-to-end — approve once executes; reject feeds the refusal —


@pytest.fixture
async def mock_llm_approval():
    """One scripted server for two serial runs (worker pool is size 1):
    turns 1-2 for the approved run, turns 3-4 for the rejected run."""
    from deploy.huggingface.mock_llm import (
        MockLLMServer,
        text_turn,
        tool_call_turn,
    )

    script = [
        tool_call_turn(
            "create_file",
            {"path": "/outputs/approval-once.md", "content": "approved work"},
        ),
        text_turn("done once"),
        tool_call_turn(
            "create_file",
            {"path": "/outputs/approval-reject.md", "content": "rejected work"},
        ),
        text_turn("done reject"),
    ]
    server = MockLLMServer(script=script).start()
    yield server
    server.stop()


@pytest.mark.asyncio
async def test_approval_end_to_end(
    mock_llm_approval, app_client, auth_headers, isolated_orchestrator, monkeypatch
) -> None:
    """§6.1 acceptance: the requested approval suspends the run, the decision
    arrives over stdin, and once/reject produce the documented effects."""
    from server.config import build_run_paths, get_config
    from server.security import decode_access_token
    from server.store import get_run, init_db

    monkeypatch.setenv("OPENAI_BASE_URL", mock_llm_approval.base_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-spike-mock")
    monkeypatch.setenv("OPENAI_MODEL", mock_llm_approval.model)
    cfg = get_config()
    monkeypatch.setattr(cfg, "wall_timeout_s", 240)
    monkeypatch.setattr(cfg, "worker_pool_size", 1)
    await init_db()

    user_id = decode_access_token(auth_headers["Authorization"].removeprefix("Bearer ").strip())

    async def _drive(marker: str, decision: str) -> str:
        resp = await app_client.post(
            "/api/runs",
            json={
                "message": "start the work",
                "session_id": f"p3-approve-{marker}",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 202, resp.text
        run_id = resp.json()["run_id"]

        events: list[dict] = []
        q = isolated_orchestrator.subscribe(run_id)

        async def _until_requested() -> None:
            while True:
                ev = await q.get()
                if ev is None:
                    raise AssertionError(f"stream ended; saw {[e['type'] for e in events]}")
                events.append(ev)
                if ev.get("type") == "approval_requested":
                    return

        await asyncio.wait_for(_until_requested(), timeout=120)
        req = events[-1]
        assert req["tool_name"] == "create_file"
        assert req["target"] == f"/outputs/{marker}.md"
        assert req["risk"] == "normal"  # plain sandbox write: no danger flag

        approve = await app_client.post(
            f"/api/runs/{run_id}/approve",
            json={"approval_id": req["approval_id"], "decision": decision},
            headers=auth_headers,
        )
        assert approve.status_code == 200, approve.text

        run = None
        for _ in range(240):
            run = await get_run(run_id=uuid.UUID(run_id), user_id=user_id)
            if run is not None and run.status in ("completed", "failed", "stopped"):
                break
            await asyncio.sleep(0.5)
        assert run is not None
        assert run.status in ("completed", "stopped"), run.status
        assert run.stopped_by != "user_stop"
        return run_id

    # Run 1: approve → the sandbox write executes and the file lands.
    run1 = await _drive("approval-once", "once")
    paths = build_run_paths(run1)
    landed = [
        p for root in (paths["outputs"], paths["workspace"]) for p in root.rglob("approval-once.md")
    ]
    assert landed, "approved create_file never wrote the deliverable"

    # Run 2: reject → the declined result text flows back to the model.
    run2 = await _drive("approval-reject", "reject")
    paths2 = build_run_paths(run2)
    landed2 = [
        p
        for root in (paths2["outputs"], paths2["workspace"])
        for p in root.rglob("approval-reject.md")
    ]
    assert not landed2, "rejected create_file must not have executed"

    refusals = [
        r
        for r in mock_llm_approval.requests
        if "[user rejected this create_file call" in json.dumps(r.get("messages", []))
    ]
    assert refusals, "the rejection never reached a follow-up LLM request"
