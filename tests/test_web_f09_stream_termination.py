"""F09: a run's event stream must end even when the run finished elsewhere.

The first F09 fix remembered "this stream already ended" inside the orchestrator
process (``_closed_stream_ids``), so it only covered runs whose worker was pumped
by *this* process. A run that ended in another process — an API restart, a
start-up orphan sweep, an id evicted from the bounded window — still subscribed
to a queue nothing would ever publish to: the replay frames arrived and the
stream never ended.

The fix decides on authoritative facts instead of process memory: a subscriber
joins the live fan-out only when this process holds the run's worker handle or
the persisted row is still queued/running (``_live_queue_for``). Everything else
is served by replay alone, which is exactly the ending a finished run should
have — ``web/src/sse.ts`` treats a clean EOF as ``completed`` and reconciles the
outcome through ``GET /api/runs/{id}``.

Run with::
    uv run pytest tests/test_web_f09_stream_termination.py -q
"""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest

from server.config import get_config, run_dir_for
from server.store import create_run, ensure_session, init_db

_TRAJECTORY = "run/agent/trajectories/react_agent.jsonl"


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
        "/api/auth/register", json={"username": "f09-user", "password": pwd}
    )
    assert reg.status_code in (201, 409), reg.text
    login = await app_client.post("/api/auth/login", json={"username": "f09-user", "password": pwd})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
def isolated_orchestrator(monkeypatch):
    """Private orchestrator: no handle for anything this test did not create."""
    import server.orchestrator as orch_mod

    orch = orch_mod.Orchestrator()
    monkeypatch.setattr(orch_mod, "_orchestrator", orch)
    return orch


@pytest.fixture
def runs_root(tmp_path, monkeypatch):
    """Keep the replayed trajectory out of the repo's real ``server/runs`` tree."""
    root = tmp_path / "runs"
    monkeypatch.setattr(get_config(), "runs_root", root)
    return root


async def _create_owned_run(auth_headers, *, status: str) -> str:
    from server.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ").strip()
    user_id = decode_access_token(token)
    run_id = uuid.uuid4()
    session_id = uuid.uuid4()
    # The session must exist first: ``runs.session_id`` is a foreign key, which
    # PostgreSQL has always enforced (SQLite only started to with F16).
    await ensure_session(session_id=session_id, user_id=user_id, title="f09")
    await create_run(
        run_id=run_id,
        session_id=session_id,
        user_id=user_id,
        prompt="p",
        pipeline_id="stateful-react-agent",
        run_dir=str(run_dir_for(run_id.hex)),
        status=status,
    )
    return run_id.hex


def _write_finished_trajectory(run_id: str) -> None:
    """Materialise the run dir a worker that already exited left behind.

    ``summary.json`` is what stops ``trajectory_tail`` from polling, so its
    presence is what makes "the run is over on disk" unambiguous for a replay.
    """
    root = run_dir_for(run_id)
    traj = root / _TRAJECTORY
    traj.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {"t": "start", "model_name": "test-model", "tool_names": ["bash"], "max_turns": 3},
        {"t": "llm", "turn": 1, "content": "the answer", "usage": {"total_tokens": 7}},
        {"t": "end", "turns": 1},
    ]
    traj.write_text("".join(json.dumps(rec) + "\n" for rec in records), encoding="utf-8")
    (root / "summary.json").write_text(json.dumps({"final_answer": "the answer"}), encoding="utf-8")


async def _read_events(app_client, run_id: str, auth_headers) -> str:
    async with app_client.stream("GET", f"/api/runs/{run_id}/events", headers=auth_headers) as resp:
        assert resp.status_code == 200, resp.text
        chunks: list[str] = []
        async for chunk in resp.aiter_text():
            chunks.append(chunk)
    return "".join(chunks)


async def test_f09_finished_in_another_process_replays_and_ends(
    app_client, auth_headers, isolated_orchestrator, runs_root
) -> None:
    """The blind spot: the row is terminal and this process never ran the worker.

    Subscribing would park the client on a dead queue (the pre-fix behaviour:
    replay frames arrived, the stream never ended). The stream must be served by
    replay alone and close on its own.
    """
    run_id = await _create_owned_run(auth_headers, status="completed")
    _write_finished_trajectory(run_id)
    assert not isolated_orchestrator.has_worker(run_id)

    body = await asyncio.wait_for(_read_events(app_client, run_id, auth_headers), timeout=15)

    # Replayed from the trajectory, in line order, with the cursor stamped.
    assert '"type": "run_started"' in body
    assert '"type": "assistant_delta"' in body
    assert '"content": "the answer"' in body
    assert '"seq": 2' in body
    # Replay-only: no queue was created, so nothing can be left parked.
    assert isolated_orchestrator._subscribers == {}


async def test_f09_active_run_without_a_handle_still_subscribes(
    app_client, auth_headers, isolated_orchestrator, runs_root
) -> None:
    """The reverse guard: an active row must NOT be mistaken for a finished run.

    A queued/running row without a handle is a run whose worker this process has
    not registered (yet) — it can still emit frames, so the subscriber must join
    the live fan-out and end on the worker's sentinel, as before.
    """
    run_id = await _create_owned_run(auth_headers, status="running")
    _write_finished_trajectory(run_id)

    task = asyncio.create_task(_read_events(app_client, run_id, auth_headers))
    try:
        for _ in range(200):
            if isolated_orchestrator._subscribers.get(run_id):
                break
            await asyncio.sleep(0.025)
        assert isolated_orchestrator._subscribers.get(run_id), (
            "an active run must still join the live fan-out"
        )
        # The replay is exhausted (summary.json exists) and the stream is still
        # open: only the live queue can be holding it there.
        await asyncio.sleep(0.5)
        assert not task.done(), "the stream closed although the run is still live"

        isolated_orchestrator._close_streams(run_id)
        body = await asyncio.wait_for(task, timeout=15)
    finally:
        if not task.done():
            task.cancel()

    assert '"type": "assistant_delta"' in body
    assert isolated_orchestrator._subscribers == {}


async def test_f09_late_subscription_finishes(isolated_orchestrator) -> None:
    """The in-process fast path is preserved: ended here → sentinel at once."""
    isolated_orchestrator._close_streams("run-finished-here")
    assert not isolated_orchestrator.has_worker("run-finished-here")

    queue = isolated_orchestrator.subscribe("run-finished-here")
    # Queued before the generator starts, so the stream cannot hang.
    assert queue.get_nowait() is None


def test_live_queue_decision_uses_the_persisted_status(isolated_orchestrator) -> None:
    from server.routes.runs import _live_queue_for

    finished = SimpleNamespace(status="completed")
    queued = SimpleNamespace(status="queued")

    # No handle here + terminal row → replay only.
    assert _live_queue_for(isolated_orchestrator, "run-finished-elsewhere", finished) is None
    # No handle here + active row → still live (fresh submit, unregistered worker).
    assert _live_queue_for(isolated_orchestrator, "run-queued", queued) is not None
    # A handle in this process wins even on a terminal row: only we receive that
    # worker's remaining frames, and its sentinel is what closes the stream.
    isolated_orchestrator._handles["run-live-here"] = SimpleNamespace()
    assert _live_queue_for(isolated_orchestrator, "run-live-here", finished) is not None
