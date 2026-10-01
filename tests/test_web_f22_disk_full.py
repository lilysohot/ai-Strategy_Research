"""F22 (F06 run-level disk-full findings): launch failure closure + submission gate.

Three defects found by the run-level disk-full injection (2026-10-01,
audit/f06-run-disk-full.json) are fixed and covered here:

* F06-RUN-1  a run submitted while the run-data root is full used to be
             accepted (202 queued) and then wedged at "queued" forever —
             ``_launch``'s history write raised ENOSPC and ``_drain_session``
             swallowed it without closing the row. Fixes: the submission route
             refuses work it cannot persist (503), and the drain task closes a
             run whose launch failed.
* F06-RUN-2  trajectory loss on a full root was silent — the row read as a
             normal completion. Fix: a cleanly-finished run whose trajectory
             file exists but is empty gets a visible degradation marker on its
             assistant turn.
* F06-RUN-3  partial writes left 0-byte sidecars; the summary write is now
             atomic (covered by code; this file covers the run-row signals).

Every case runs against a throwaway SQLite file and a temp data root — no real
database, no network, no subprocess.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from server import readiness, store
from server.config import build_run_paths, get_config
from server.orchestrator import Orchestrator


@pytest.fixture
async def env(tmp_path, monkeypatch):
    """SQLite store + temp runs root + one owned queued run (no HTTP client)."""
    cfg = get_config()
    monkeypatch.setattr(cfg, "database_url", f"sqlite+aiosqlite:///{tmp_path}/f22.db")
    monkeypatch.setattr(cfg, "runs_root", tmp_path / "runs")
    await store.reset_engine()
    await store.init_db()
    a = await store.create_user(username="f22-a", password_hash="synthetic-no-login")
    sid = uuid.uuid4()
    await store.ensure_session(session_id=sid, user_id=a.id, title="f22")
    rid = uuid.uuid4()
    await store.create_run(
        run_id=rid,
        session_id=sid,
        user_id=a.id,
        prompt="f22",
        pipeline_id="stateful-react-agent",
        run_dir=str(build_run_paths(rid.hex)["root"]),
    )
    orch = Orchestrator()
    monkeypatch.setattr("server.routes.runs.get_orchestrator", lambda: orch)
    yield SimpleNamespace(cfg=cfg, a=a, sid=sid, rid=rid, orch=orch)
    await store.reset_engine()


async def _trajectory_file(rid_hex: str):
    path = build_run_paths(rid_hex)["run"] / "agent" / "trajectories" / "react_agent.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


async def test_submit_rejected_when_data_root_unwritable(env, monkeypatch):
    """A full/read-only run-data root must refuse new runs before any side effect."""
    from server.app import app
    from server.deps import get_current_user

    monkeypatch.setattr(
        "server.routes.runs.probe_data_root",
        lambda: readiness.DATA_ROOT_UNWRITABLE,
    )
    app.dependency_overrides[get_current_user] = lambda: env.a
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://f22",
        ) as client:
            response = await client.post(
                "/api/runs",
                json={"session_id": str(env.sid), "message": "should-not-accept"},
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    # Zero side effects: the request was rejected before the session row or any
    # turn/run mutation that a full root could not persist.
    turns = await store.list_turns(session_id=env.sid)
    assert not turns, f"rejected submission still wrote {len(turns)} turns"
    run = await store.get_run(run_id=env.rid, user_id=env.a.id)
    assert run.status == "queued", "rejected submission must not touch existing runs"


async def test_launch_failure_closes_run_instead_of_wedging(env, monkeypatch):
    """A run whose launch raises (e.g. ENOSPC writing history) must not stay queued."""

    async def boom(**params):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(env.orch, "_spawn", boom)
    queue: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(env.orch._drain_session(str(env.sid), queue))
    await queue.put(
        {
            "run_id": env.rid.hex,
            "session_id": str(env.sid),
            "session_uuid": env.sid,
            "prompt": "f22",
        }
    )
    await queue.put(None)
    await asyncio.wait_for(task, timeout=5)

    run = await store.get_run(run_id=env.rid, user_id=env.a.id)
    assert run.status == "failed", f"launch failure left run {run.status}"
    assert run.finished_at is not None, "launch failure must stamp finished_at"
    assert "launch failed" in (run.error or ""), run.error
    assert "No space left" in (run.error or ""), run.error


async def test_launch_failure_never_overwrites_terminal_run(env, monkeypatch):
    """A launch error for an already-finished run must not clobber its outcome."""
    run = await store.get_run(run_id=env.rid, user_id=env.a.id)
    run.status = "completed"
    run.final_answer = "real answer"
    await store.update_run_result(
        run_id=env.rid, status="completed", final_answer="real answer"
    )
    closed = await store.mark_run_failed_if_active(
        run_id=env.rid, error="launch failed: synthetic"
    )
    assert closed is False
    run = await store.get_run(run_id=env.rid, user_id=env.a.id)
    assert run.status == "completed"
    assert run.final_answer == "real answer"


async def test_clean_completion_with_empty_trajectory_gets_degradation_marker(env):
    """A completed run with an existing-but-empty trajectory is surfaced, not silent."""
    path = await _trajectory_file(env.rid.hex)
    path.write_bytes(b"")  # 0-byte: every observer write failed (ENOSPC signature)
    handle = SimpleNamespace(run_id=env.rid.hex, _params={"session_uuid": env.sid})
    frame = {"ok": True, "stopped_by": "", "error": "", "final_answer": "synthetic answer"}
    await env.orch._backfill_assistant_turn(handle, frame)
    turns = await store.list_turns(session_id=env.sid)
    assert any("存储降级" in t.content for t in turns), turns


async def test_clean_completion_with_records_gets_no_degradation_marker(env):
    """A completed run with a real trajectory is tagged partial/degraded never."""
    path = await _trajectory_file(env.rid.hex)
    path.write_text('{"t": "start"}\n{"t": "end"}\n', encoding="utf-8")
    handle = SimpleNamespace(run_id=env.rid.hex, _params={"session_uuid": env.sid})
    frame = {"ok": True, "stopped_by": "", "error": "", "final_answer": "synthetic answer"}
    await env.orch._backfill_assistant_turn(handle, frame)
    turns = await store.list_turns(session_id=env.sid)
    assert not any("存储降级" in t.content for t in turns), turns
    assert any(t.content == "synthetic answer" for t in turns), turns


async def test_missing_trajectory_file_is_not_marked_degraded(env):
    """No file at all means recording was disabled — not a storage loss."""
    handle = SimpleNamespace(run_id=env.rid.hex, _params={"session_uuid": env.sid})
    frame = {"ok": True, "stopped_by": "", "error": "", "final_answer": "synthetic answer"}
    await env.orch._backfill_assistant_turn(handle, frame)
    turns = await store.list_turns(session_id=env.sid)
    assert not any("存储降级" in t.content for t in turns), turns
