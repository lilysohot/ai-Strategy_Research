"""Desired contracts: failures are audit findings, not accepted behavior."""
from __future__ import annotations
import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from server import store
from server.config import get_config, build_run_paths, run_dir_for
from server.orchestrator import Orchestrator
from server.relay import sse_for_run, trajectory_records, _traj_record_to_events
from server.artifacts import resolve_artifact_path
from server.usage import usage_for_run

@pytest.fixture
async def env(tmp_path, monkeypatch):
    cfg = get_config()
    monkeypatch.setattr(cfg, "database_url", f"sqlite+aiosqlite:///{tmp_path}/audit.db")
    monkeypatch.setattr(cfg, "runs_root", tmp_path / "runs")
    # ``uploads_root`` was removed by F01 (uploads actually land under
    # ``<runs_root>/<run_id>/inputs``); setting it here made every case in this
    # file error out at setup once the migration dropped the field.
    cfg.ensure_dirs()
    await store.reset_engine()
    await store.init_db()
    a = await store.create_user(username="audit-a", password_hash="synthetic-no-login")
    b = await store.create_user(username="audit-b", password_hash="synthetic-no-login")
    sid = uuid.uuid4()
    await store.ensure_session(session_id=sid, user_id=a.id, title="synthetic")
    rid = uuid.uuid4()
    await store.create_run(run_id=rid, session_id=sid, user_id=a.id, prompt="synthetic",
                           pipeline_id="stateful-react-agent", run_dir=str(run_dir_for(rid.hex)))
    from server.app import app
    from server.deps import get_current_user
    from server.routes import runs
    orch = Orchestrator()
    async def hold(*args, **kwargs):
        await asyncio.Event().wait()
    monkeypatch.setattr(orch, "_drain_session", hold)
    monkeypatch.setattr(runs, "get_orchestrator", lambda: orch)
    app.dependency_overrides[get_current_user] = lambda: a
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://audit") as client:
        yield SimpleNamespace(cfg=cfg, a=a, b=b, sid=sid, rid=rid, client=client,
                              app=app, dep=get_current_user, orch=orch, root=tmp_path)
    app.dependency_overrides.clear()
    for task in orch._session_tasks.values():
        task.cancel()
    await asyncio.gather(*orch._session_tasks.values(), return_exceptions=True)
    await store.reset_engine()

def write_trace(rid, records):
    path = build_run_paths(rid.hex)["run"] / "agent/trajectories/react_agent.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path

async def test_f08_submit_rejects_foreign_session_without_mutation(env):
    env.app.dependency_overrides[env.dep] = lambda: env.b
    response = await env.client.post("/api/runs", json={"session_id": str(env.sid), "message": "B-marker"})
    turns = await store.list_turns(session_id=env.sid)
    assert response.status_code == 404 and not turns, (
        f"foreign submission status={response.status_code}, foreign messages={len(turns)}")

async def test_f01_uuid_returned_by_api_reads_same_trace(env):
    write_trace(env.rid, [{"t":"llm", "turn":1, "content":"synthetic"}])
    compact = await env.client.get(f"/api/runs/{env.rid.hex}/trace")
    canonical = await env.client.get(f"/api/runs/{env.rid}/trace")
    assert canonical.json()["records"] == compact.json()["records"], "hyphenated UUID loses stored trace"

async def test_f03_trace_uses_same_redaction_as_replay(env):
    fake = "sk-AuditSynthetic123456"
    write_trace(env.rid, [{"t":"llm", "turn":1, "content":fake}])
    response = await env.client.get(f"/api/runs/{env.rid.hex}/trace")
    assert fake not in response.text, "synthetic credential returned unredacted"

async def test_f04_observer_call_id_survives_jsonl(env):
    from frontier_agent.components.observers.trajectory import TrajectoryFileObserver
    observer = TrajectoryFileObserver(env.root / "observer", filename="test", formats=["jsonl"])
    ctx = SimpleNamespace(turn=1, ai_text="", tool_calls=[{"id":"vendor-id", "name":"test", "args":{}}],
                          thinking="", thinking_blocks=None, usage=None)
    await observer.on_llm_response(ctx)
    observer._close_jsonl()
    rec = json.loads((env.root / "observer/test.jsonl").read_text())
    starts = [x for x in _traj_record_to_events(rec) if x["type"] == "tool_started"]
    assert starts[0]["tool_call_id"] == "vendor-id"

async def test_f09_late_subscription_finishes(env):
    write_trace(env.rid, [{"t":"end"}])
    (run_dir_for(env.rid.hex) / "summary.json").write_text("{}")
    env.orch._close_streams(env.rid.hex)
    queue = env.orch.subscribe(env.rid.hex)
    stream = sse_for_run(env.rid.hex, queue=queue)
    async def drain():
        return [frame async for frame in stream]
    timed_out = False
    try:
        await asyncio.wait_for(drain(), timeout=0.1)
    except TimeoutError:
        timed_out = True
    finally:
        await stream.aclose()
        env.orch.unsubscribe(env.rid.hex, queue)
    assert not timed_out, "finished run's new live subscriber never receives terminal/sentinel"

async def test_f12_rejected_batch_leaves_no_uploaded_files(env, monkeypatch):
    monkeypatch.setattr(env.cfg, "max_upload_bytes", 4)
    response = await env.client.post("/api/runs",
        data={"message":"synthetic", "session_id":str(env.sid)},
        files=[("files", ("ok.txt", b"ok")), ("files", ("large.txt", b"12345"))])
    assert response.status_code == 413
    leftovers = list(env.cfg.runs_root.glob("*/inputs/*"))
    assert not leftovers, f"rejected batch left {len(leftovers)} files"

async def test_f14_queued_future_message_excluded_from_history(env, monkeypatch):
    later = uuid.uuid4()
    await store.create_run(run_id=later, session_id=env.sid, user_id=env.a.id, prompt="future",
                          pipeline_id="stateful-react-agent", run_dir=str(run_dir_for(later.hex)))
    await store.append_turn(session_id=env.sid, role="user", content="current", run_id=env.rid)
    await store.append_turn(session_id=env.sid, role="user", content="FUTURE_MARKER", run_id=later)
    captured = {}
    class EndProbe(Exception): pass
    async def fake_launch(run_id, params, *, history):
        captured["history"] = history
        raise EndProbe()
    monkeypatch.setattr(env.orch, "_launch", fake_launch)
    monkeypatch.setattr(env.orch, "_release_slot", AsyncMock())
    with pytest.raises(EndProbe):
        await env.orch._spawn(run_id=env.rid.hex, session_uuid=env.sid)
    assert "FUTURE_MARKER" not in captured["history"]

async def test_missing_trace_is_not_measured_zero_usage(env):
    usage = usage_for_run(env.rid.hex)
    assert usage.get("status") in {"unavailable", "partial"} or usage.get("total_tokens") is None, (
        "missing trace is indistinguishable from verified zero usage")

async def test_artifact_root_symlink_cannot_rebase_containment(env):
    paths = build_run_paths(env.rid.hex)
    foreign = env.root / "foreign"
    foreign.mkdir()
    (foreign / "synthetic.txt").write_text("foreign-marker")
    paths["outputs"].rmdir()
    paths["outputs"].symlink_to(foreign, target_is_directory=True)
    assert resolve_artifact_path(env.rid.hex, "synthetic.txt") is None, (
        "symlinked outputs root changes containment boundary")

async def test_orphan_recovery_restores_saved_answer_to_session(env):
    root = build_run_paths(env.rid.hex)["root"]
    (root / "summary.json").write_text(json.dumps({"run_id":env.rid.hex, "final_answer":"saved-answer",
                                                   "error":"", "stopped_by":"", "duration_s":1}))
    await env.orch.reconcile_orphan_runs()
    run = await store.get_run(run_id=env.rid, user_id=env.a.id)
    turns = await store.list_turns(session_id=env.sid)
    assert any("saved-answer" in t.content for t in turns), (
        f"saved answer only recovered to run row ({run.status}); restored messages={len(turns)}")

async def test_session_owner_read_guard_remains_enforced(env):
    env.app.dependency_overrides[env.dep] = lambda: env.b
    response = await env.client.get(f"/api/runs/{env.rid.hex}/trace")
    assert response.status_code == 404

async def test_artifact_child_traversal_guard_remains_enforced(env):
    paths = build_run_paths(env.rid.hex)
    outside = env.root / "synthetic.txt"
    outside.write_text("outside")
    (paths["outputs"] / "escape").symlink_to(outside)
    assert resolve_artifact_path(env.rid.hex, "escape") is None
    assert resolve_artifact_path(env.rid.hex, "../../../synthetic.txt") is None

async def test_terminal_frame_replay_does_not_duplicate_assistant_turn(env):
    reader = asyncio.StreamReader()
    frame = {"type":"run_finished", "ok":True, "final_answer":"answer"}
    reader.feed_data(((json.dumps(frame) + "\n") * 2).encode())
    reader.feed_eof()
    handle = SimpleNamespace(run_id=env.rid.hex, session_id=str(env.sid),
        proc=SimpleNamespace(stdout=reader), frames=[], _finished=False,
        _params={"session_uuid":env.sid})
    await env.orch._pump_frames(handle)
    turns = await store.list_turns(session_id=env.sid)
    assert len(turns) == 1, f"same terminal frame created {len(turns)} assistant turns"

async def test_orphan_recovery_rebuilds_artifact_and_usage_indexes(env):
    paths = build_run_paths(env.rid.hex)
    (paths["outputs"] / "report.txt").write_text("synthetic")
    write_trace(env.rid, [{"t":"llm", "turn":1, "usage":{"total_tokens":15, "prompt_tokens":10, "completion_tokens":5}}])
    await env.orch.reconcile_orphan_runs()
    run = await store.get_run(run_id=env.rid, user_id=env.a.id)
    artifacts = await store.list_artifacts(run_id=env.rid, user_id=env.a.id)
    assert run.total_tokens == 15 and len(artifacts) == 1, (
        f"files exist but restored usage={run.total_tokens}, artifact rows={len(artifacts)}")

async def test_queue_continues_after_launch_failure(env, monkeypatch):
    calls = []
    async def fail_first(**params):
        calls.append(params["run_id"])
        if len(calls) == 1:
            raise OSError("synthetic disk failure before launch")
    monkeypatch.setattr(env.orch, "_spawn", fail_first)
    queue = asyncio.Queue()
    for item in ({"run_id":"a"}, {"run_id":"b"}, None):
        queue.put_nowait(item)
    try:
        await Orchestrator._drain_session(env.orch, "synthetic", queue)
    except OSError:
        pass
    assert calls == ["a", "b"], f"launch failure abandoned subsequent queue: {calls}"

async def test_revert_updates_artifact_hash_index(env):
    import hashlib
    from server.artifacts import scan_outputs
    paths = build_run_paths(env.rid.hex)
    file = paths["outputs"] / "report.txt"
    file.write_bytes(b"new")
    await store.record_artifacts(run_id=env.rid, artifacts=scan_outputs(env.rid.hex))
    baseline = paths["root"] / "diff/base"
    baseline.mkdir(parents=True)
    (baseline / "0000.bin").write_bytes(b"old")
    (baseline.parent / "manifest.json").write_text(json.dumps({"/outputs/report.txt":{"snapshot":"0000.bin"}}))
    await store.update_run_result(run_id=env.rid, status="completed")
    response = await env.client.post(f"/api/runs/{env.rid.hex}/revert", json={"paths":["/outputs/report.txt"]})
    assert response.status_code == 200
    assert file.read_bytes() == b"old"
    artifacts = await store.list_artifacts(run_id=env.rid, user_id=env.a.id)
    assert artifacts[0].sha256 == hashlib.sha256(file.read_bytes()).hexdigest(), "revert left stale sha256 in DB"

async def test_sqlite_declared_foreign_keys_are_enforced(env):
    from sqlalchemy import text
    async with store.get_engine().connect() as conn:
        enabled = await conn.scalar(text("PRAGMA foreign_keys"))
    assert enabled == 1, "SQLite declares FKs but enforcement is disabled"

async def test_concurrent_message_sequence_is_unique(env):
    results = await asyncio.gather(*(store.append_turn(session_id=env.sid, role="user", content=f"m{i}")
                                     for i in range(8)), return_exceptions=True)
    assert not any(isinstance(r, Exception) for r in results), "concurrent appends failed"
    seqs = [r.seq for r in results]
    assert len(set(seqs)) == len(seqs), f"concurrent MAX(seq)+1 allocated duplicate sequences: {seqs}"

async def test_revert_rejects_symlinked_baseline(env):
    paths = build_run_paths(env.rid.hex)
    foreign = env.root / "foreign-baseline.txt"
    foreign.write_text("foreign-marker")
    (paths["outputs"] / "report.txt").write_text("current")
    baseline = paths["root"] / "diff/base"
    baseline.mkdir(parents=True)
    (baseline / "0000.bin").symlink_to(foreign)
    (baseline.parent / "manifest.json").write_text(json.dumps({"/outputs/report.txt":{"snapshot":"0000.bin"}}))
    await store.update_run_result(run_id=env.rid, status="completed")
    response = await env.client.post(f"/api/runs/{env.rid.hex}/revert", json={"paths":["/outputs/report.txt"]})
    assert response.json()["results"][0]["status"] == "rejected", "revert copied external symlink target into outputs"

async def test_submit_records_nonsecret_model_snapshot(env):
    await store.create_llm_config(user_id=env.a.id, name="audit-model", base_url="https://audit.invalid",
                                 model="synthetic-model", api_key="synthetic-not-real", is_default=True)
    response = await env.client.post("/api/runs", json={"session_id":str(env.sid), "message":"synthetic"})
    assert response.status_code == 202
    run = await store.get_run(run_id=uuid.UUID(response.json()["run_id"]), user_id=env.a.id)
    assert run.llm_snapshot_json and run.llm_snapshot_json.get("model") == "synthetic-model", (
        "configured model has no run snapshot")

async def test_health_distinguishes_unavailable_storage(env, monkeypatch):
    monkeypatch.setattr(store, "check_db", AsyncMock(return_value=False))
    response = await env.client.get("/healthz")
    assert response.status_code == 503 or response.json().get("status") != "ok", (
        "storage unavailable but health always says ok; readiness gate absent")

async def test_run_started_event_updates_persistent_status(env):
    reader = asyncio.StreamReader()
    reader.feed_data((json.dumps({"type":"run_started", "run_dir":str(run_dir_for(env.rid.hex))}) + "\n").encode())
    reader.feed_eof()
    handle = SimpleNamespace(run_id=env.rid.hex, session_id=str(env.sid), proc=SimpleNamespace(stdout=reader),
                              frames=[], _finished=False, _params={"session_uuid":env.sid})
    await env.orch._pump_frames(handle)
    run = await store.get_run(run_id=env.rid, user_id=env.a.id)
    assert run.status == "running" and run.started_at is not None, (
        f"worker start not persisted: status={run.status}, started_at={run.started_at}")

async def test_alembic_empty_database_upgrade_matches_orm_columns(env, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect
    await store.reset_engine()
    monkeypatch.setattr(env.cfg, "database_url", f"sqlite+aiosqlite:///{env.root}/migration.db")
    await asyncio.to_thread(command.upgrade, Config("server/alembic.ini"), "head")
    async with store.get_engine().connect() as conn:
        actual = await conn.run_sync(lambda c: {
            table.name: {column["name"] for column in inspect(c).get_columns(table.name)}
            for table in store.Base.metadata.sorted_tables})
    expected = {table.name: set(table.columns.keys()) for table in store.Base.metadata.sorted_tables}
    assert actual == expected

async def test_absolute_file_tool_path_can_be_reverted(env, monkeypatch):
    from server.diff import DiffRecorder
    paths = build_run_paths(env.rid.hex)
    for key, value in {"FRONTIER_AGENT_WORKSPACE_DIR":paths["workspace"],
                       "FRONTIER_AGENT_OUTPUTS_DIR":paths["outputs"],
                       "FRONTIER_AGENT_INPUTS_DIR":paths["inputs"]}.items():
        monkeypatch.setenv(key, str(value))
    monkeypatch.setenv("SANDBOX_BACKEND", "native")
    file = paths["outputs"] / "report.txt"
    file.write_text("before")
    recorder = DiffRecorder(run_root=paths["root"], outputs_root=paths["outputs"], workspace_root=paths["workspace"])
    await recorder.on_tool_call(None, {"name":"create_file", "args":{"path":str(file)}})
    file.write_text("after")
    recorder.write_diff()
    await store.update_run_result(run_id=env.rid, status="completed")
    response = await env.client.post(f"/api/runs/{env.rid.hex}/revert", json={"paths":[str(file)]})
    assert response.json()["results"][0]["status"] == "restored", "valid absolute snapshot path rejected by revert resolver"
