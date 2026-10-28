"""Normal text-only completion must not masquerade as a partial/stopped run."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from server import store
from server.bridge import BridgeObserver
from server.orchestrator import Orchestrator


@pytest.mark.parametrize("reason", ["no_tool", "final_answer", "wall_deadline", "user_stop", "response_truncated"])
async def test_bridge_captures_loop_outcome_without_emitting_run_terminal(reason):
    queue = asyncio.Queue()
    bridge = BridgeObserver(queue)
    await bridge.on_loop_end(SimpleNamespace(stopped_by=reason, final_content="你好"))
    assert bridge.stopped_by == reason  # retain the engine's audit fact
    assert queue.empty(), "workflow finalization owns the product-Run terminal event"


@pytest.mark.parametrize(("reason", "ok", "error", "status", "tag"), [
    ("no_tool", True, "", "completed", ""),
    ("final_answer", True, "", "completed", ""),
    ("final_answer", False, "provider failed", "failed", "error"),
    ("final_answer", True, "provider failed", "failed", "error"),
    ("no_tool", False, "provider failed", "failed", "error"),
    ("no_tool", True, "provider failed", "failed", "error"),
    ("no_tool", False, "", "failed", "error"),
    ("wall_deadline", True, "", "stopped", "wall_deadline"),
    ("user_stop", True, "", "stopped", "user_stop"),
    ("response_truncated", True, "", "stopped", "response_truncated"),
])
async def test_message_database_status_and_live_event_agree(monkeypatch, reason, ok, error, status, tag):
    orch = Orchestrator()
    handle = SimpleNamespace(run_id=uuid.uuid4().hex, _params={"session_uuid": uuid.uuid4()})
    append = AsyncMock()
    update = AsyncMock()
    publish = Mock()
    monkeypatch.setattr("server.orchestrator.append_turn", append)
    monkeypatch.setattr("server.orchestrator.update_run_result", update)
    monkeypatch.setattr(orch, "_materialize_input_intent", AsyncMock())
    monkeypatch.setattr(orch, "_publish", publish)
    frame = {"ok": ok, "stopped_by": reason, "error": error, "final_answer": "你好"}
    await orch._backfill_assistant_turn(handle, frame)
    await orch._persist_run_result(handle, frame)
    expected = "你好" if not tag else f"你好\n\n_[partial: {tag}]_"
    assert append.call_args.kwargs["content"] == expected
    assert update.call_args.kwargs["status"] == status
    assert publish.call_args.args[1]["type"] == f"run_{status}"
    if status == "stopped":
        assert publish.call_args.args[1]["stopped_by"] == reason
        assert publish.call_args.args[1]["final_answer"] == "你好"
    else:
        assert update.call_args.kwargs["stopped_by"] is None


async def test_normal_completion_still_reports_trajectory_storage_loss(monkeypatch):
    orch = Orchestrator()
    handle = SimpleNamespace(run_id=uuid.uuid4().hex, _params={"session_uuid": uuid.uuid4()})
    append = AsyncMock()
    monkeypatch.setattr("server.orchestrator.append_turn", append)
    monkeypatch.setattr(orch, "_trajectory_degraded", lambda _: True)
    await orch._backfill_assistant_turn(handle, {
        "ok": True, "stopped_by": "no_tool", "final_answer": "你好",
    })
    assert "存储降级" in append.call_args.kwargs["content"]
    assert "partial" not in append.call_args.kwargs["content"]


async def test_recovered_normal_answer_has_no_partial_marker(monkeypatch):
    orch = Orchestrator()
    append = AsyncMock()
    monkeypatch.setattr(orch, "_materialize_input_intent", AsyncMock())
    monkeypatch.setattr(orch, "_usage_with_replay", lambda _: {})
    monkeypatch.setattr("server.orchestrator.list_turns", AsyncMock(return_value=[]))
    monkeypatch.setattr("server.orchestrator.append_turn", append)
    monkeypatch.setattr("server.orchestrator.scan_outputs", lambda _: [])
    monkeypatch.setattr("server.orchestrator.update_run_usage", AsyncMock())
    monkeypatch.setattr("server.orchestrator.is_watch_run", AsyncMock(return_value=True))
    await orch._recover_finished_run(
        run_id=uuid.uuid4(), session_id=uuid.uuid4(), final_answer="你好",
        stopped_by="no_tool", error="",
    )
    assert append.call_args.kwargs["content"] == "你好"


@pytest.mark.parametrize("error", [None, "provider failed"])
async def test_history_corrects_only_verified_legacy_markers_without_rewriting_storage(error):
    await store.init_db()
    user = await store.create_user(username="normal-completion", password_hash="test-no-login")
    sid, rid = uuid.uuid4(), uuid.uuid4()
    await store.ensure_session(session_id=sid, user_id=user.id, title="test")
    await store.create_run(
        run_id=rid, session_id=sid, user_id=user.id, prompt="hi",
        pipeline_id="stateful-react-agent", run_dir="unused-test-run",
    )
    await store.update_run_result(
        run_id=rid, status="stopped", stopped_by="no_tool", final_answer="你好", error=error,
    )
    original = "你好\n\n_[partial: no_tool]_"
    await store.append_turn(session_id=sid, role="assistant", content=original, run_id=rid)
    await store.append_turn(session_id=sid, role="user", content=original, run_id=rid)
    turns = await store.list_turns(session_id=sid)
    assert turns[0].content == (original if error else "你好")
    assert turns[1].content == original
    paged = await store.list_turns(session_id=sid, limit=1, before_seq=turns[1].seq)
    assert paged[0].content == turns[0].content
    run = await store.get_run(run_id=rid, user_id=user.id)
    assert run.status == ("stopped" if error else "completed")
    async with store.get_sessionmaker()() as session:
        raw = await session.get(store.Run, rid)
        assert raw.status == "stopped"
        raw_turn = await session.get(store.Turn, turns[0].id)
        assert raw_turn.content == original


async def test_materialized_input_request_controls_terminal_event_and_answer(monkeypatch):
    orch = Orchestrator()
    handle = SimpleNamespace(run_id=uuid.uuid4().hex, _params={"session_uuid": uuid.uuid4()})
    request = {"request_id": str(uuid.uuid4()), "status": "pending"}
    monkeypatch.setattr(orch, "_materialize_input_intent", AsyncMock(return_value=request))
    update, append, publish = AsyncMock(), AsyncMock(), Mock()
    monkeypatch.setattr("server.orchestrator.update_run_result", update)
    monkeypatch.setattr("server.orchestrator.append_turn", append)
    monkeypatch.setattr(orch, "_publish", publish)
    frame = {"ok": True, "stopped_by": "no_tool", "final_answer": "研究正文"}
    await orch._persist_run_result(handle, frame)
    await orch._backfill_assistant_turn(handle, frame)
    assert update.call_args.kwargs["stopped_by"] == "input_required"
    assert publish.call_args.args[1]["type"] == "run_stopped"
    assert publish.call_args.args[1]["stopped_by"] == "input_required"
    assert "已创建待补资料请求" in update.call_args.kwargs["final_answer"]
    assert "已创建待补资料请求" in append.call_args.kwargs["content"]
    assert frame["input_request"] == request
