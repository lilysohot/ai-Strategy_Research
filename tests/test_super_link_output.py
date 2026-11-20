from __future__ import annotations

import asyncio
import copy
import uuid
from types import SimpleNamespace

import pytest

from server import orchestrator
from server.events import EventType
from server.super_link import output


def _delta(**extra):
    return {
        "type": EventType.ASSISTANT_DELTA.value,
        "turn": 2,
        "agent_id": "member_a",
        "agent_kind": "subagent",
        **extra,
    }


def test_content_and_thinking_are_split_with_member_identity():
    items = output.preview_items(_delta(text="hello", thinking_text="hmm"))

    assert [item.kind for item in items] == [
        output.PreviewKind.THINKING,
        output.PreviewKind.CONTENT,
    ]
    assert items[0].data["block_key"] == "thinking|subagent|member_a|2"
    assert items[0].data["text"] == "hmm"
    assert items[1].data["block_key"] == "content|subagent|member_a|2"
    assert items[1].data["text"] == "hello"
    assert items[0].data["member"] == {
        "agent_id": "member_a",
        "agent_kind": "subagent",
    }


def test_missing_thinking_does_not_create_a_block():
    items = output.preview_items(_delta(text="only content"))

    assert len(items) == 1
    assert items[0].kind is output.PreviewKind.CONTENT
    assert all(item.kind is not output.PreviewKind.THINKING for item in items)


def test_single_agent_has_empty_member_and_stable_key():
    items = output.preview_items(
        {
            "type": EventType.ASSISTANT_DELTA.value,
            "turn": 1,
            "text": "hi",
        }
    )

    assert items[0].data["member"] == {"agent_id": "", "agent_kind": ""}
    assert items[0].data["block_key"] == "content|||1"


def test_long_text_is_chunked_in_order():
    items = output.preview_items(_delta(text="x" * (output.PREVIEW_TEXT_LIMIT * 2 + 5)))

    assert len(items) == 3
    assert all(len(item.data["text"]) <= output.PREVIEW_TEXT_LIMIT for item in items)
    assert "".join(item.data["text"] for item in items) == "x" * (
        output.PREVIEW_TEXT_LIMIT * 2 + 5
    )


def test_tool_frames_copy_detail_only_and_redact_secrets():
    started = output.preview_items(
        {
            "type": EventType.TOOL_STARTED.value,
            "turn": 3,
            "agent_id": "member_b",
            "agent_kind": "subagent",
            "tool_call_id": "call_1",
            "tool_name": "web_search",
        }
    )[0]
    finished = output.preview_items(
        {
            "type": EventType.TOOL_FINISHED.value,
            "turn": 3,
            "agent_id": "member_b",
            "agent_kind": "subagent",
            "tool_call_id": "call_1",
            "tool_name": "web_search",
            "ok": True,
            "detail": "used sk-abcdef123456 for auth",
            "output": "a very large body that must not enter previews",
            "ms": 42,
        }
    )[0]

    assert started.kind is output.PreviewKind.TOOL
    assert started.data["block_key"] == "tool|subagent|member_b|call_1"
    assert started.data["tool"]["state"] == "started"
    assert finished.data["tool"]["state"] == "finished"
    assert finished.data["tool"]["ok"] is True
    assert finished.data["tool"]["ms"] == 42
    assert "output" not in finished.data
    assert "sk-abcdef123456" not in finished.data["tool"]["detail"]
    assert "redacted" in finished.data["tool"]["detail"]


def test_terminal_frame_never_carries_final_answer():
    items = output.preview_items(
        {
            "type": EventType.RUN_COMPLETED.value,
            "turn": 4,
            "final_answer": "the full report body",
            "agent_id": "main",
            "agent_kind": "coordinator",
        }
    )

    assert len(items) == 1
    assert items[0].kind is output.PreviewKind.TERMINAL
    assert items[0].data["status"] == "completed"
    assert "final_answer" not in items[0].data
    assert "the full report body" not in str(items[0].data)


def test_failed_and_stopped_are_terminal_without_content():
    failed = output.preview_items(
        {"type": EventType.RUN_FAILED.value, "error": "boom sk-abcdef123456"}
    )[0]
    stopped = output.preview_items(
        {"type": EventType.RUN_STOPPED.value, "stopped_by": "user"}
    )[0]

    assert failed.data["status"] == "failed"
    assert "sk-abcdef123456" not in failed.data["error"]
    assert stopped.data["status"] == "stopped"
    assert stopped.data["stopped_by"] == "user"


def test_compaction_warning_becomes_a_notice_only():
    items = output.preview_items(
        {
            "type": EventType.WARNING.value,
            "turn": 5,
            "detail": "context compaction",
            "agent_id": "main",
            "agent_kind": "coordinator",
        }
    )

    assert len(items) == 1
    assert items[0].kind is output.PreviewKind.NOTICE
    assert items[0].data["text"] == "context compaction"


def test_unknown_frames_and_non_dict_payloads_are_ignored():
    assert output.preview_items({"type": "steer_applied", "turn": 1}) == []
    assert output.preview_items({"type": "run_started"}) == []
    assert output.preview_items(None) == []
    assert output.preview_items([]) == []


def test_preview_mapping_does_not_mutate_the_source_frame():
    payload = _delta(text="hello", thinking_text="hmm")
    original = copy.deepcopy(payload)

    output.preview_items(payload)

    assert payload == original


async def test_hub_isolates_subscriptions_by_session():
    hub = output.RunOutputHub()
    team, single = uuid.uuid4(), uuid.uuid4()
    team_sub = hub.subscribe([team], max_frames=8)
    single_sub = hub.subscribe([single], max_frames=8)

    hub.publish(team, "run-1", _delta(text="team only"))

    item = await team_sub.next()
    assert isinstance(item, output.PreviewItem)
    assert item.run_id == "run-1"
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(single_sub.next(), 0.05)
    assert hub.observed(team)
    assert not hub.observed(uuid.uuid4())

    hub.unsubscribe(team_sub)
    hub.unsubscribe(single_sub)
    assert not hub.observed(team)


async def test_overflow_collapses_into_one_reset_for_affected_runs():
    hub = output.RunOutputHub()
    session = uuid.uuid4()
    sub = hub.subscribe([session], max_frames=2)

    for index in range(5):
        hub.publish(
            session,
            "run-a" if index < 3 else "run-b",
            _delta(text=f"chunk-{index}"),
        )

    item = await sub.next()
    assert isinstance(item, output.OutputReset)
    assert item.run_ids == ("run-a", "run-b")
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(sub.next(), 0.05)


async def test_overflow_reset_is_followed_by_new_frames():
    hub = output.RunOutputHub()
    session = uuid.uuid4()
    sub = hub.subscribe([session], max_frames=1)

    hub.publish(session, "run-a", _delta(text="one"))
    hub.publish(session, "run-a", _delta(text="two"))

    first = await sub.next()
    assert isinstance(first, output.OutputReset)
    assert first.run_ids == ("run-a",)

    hub.publish(session, "run-a", _delta(text="three"))
    second = await sub.next()
    assert isinstance(second, output.PreviewItem)
    assert second.data["text"] == "three"


async def test_unsubscribe_wakes_and_stops_the_subscription():
    hub = output.RunOutputHub()
    session = uuid.uuid4()
    sub = hub.subscribe([session], max_frames=4)
    waiter = asyncio.create_task(sub.next())

    await asyncio.sleep(0)
    hub.unsubscribe(sub)

    assert await asyncio.wait_for(waiter, 1.0) is None


async def test_orchestrator_publish_keeps_the_original_stream_and_taps_preview(
    monkeypatch,
):
    hub = output.RunOutputHub()
    monkeypatch.setattr(output, "HUB", hub)
    session = uuid.uuid4()
    preview = hub.subscribe([session], max_frames=8)

    orch = object.__new__(orchestrator.Orchestrator)
    orch._subscribers = {"run-1": {}}  # replaced below with a real queue
    normal: asyncio.Queue = asyncio.Queue()
    orch._subscribers = {"run-1": {normal}}
    orch._handles = {
        "run-1": SimpleNamespace(session_id=str(session), run_id="run-1")
    }
    orch._closed_streams = []
    orch._closed_stream_ids = set()

    payload = _delta(text="visible")
    orch._publish("run-1", payload)

    assert normal.get_nowait() == payload
    item = await preview.next()
    assert isinstance(item, output.PreviewItem)
    assert item.run_id == "run-1"
    assert item.data["text"] == "visible"


async def test_orchestrator_publish_ignores_unobserved_sessions_and_unknown_runs(
    monkeypatch,
):
    hub = output.RunOutputHub()
    monkeypatch.setattr(output, "HUB", hub)

    orch = object.__new__(orchestrator.Orchestrator)
    normal: asyncio.Queue = asyncio.Queue()
    orch._subscribers = {"run-1": {normal}}
    orch._handles = {"run-1": SimpleNamespace(session_id="not-a-uuid", run_id="run-1")}
    orch._closed_streams = []
    orch._closed_stream_ids = set()

    payload = _delta(text="visible")
    orch._publish("run-1", payload)
    orch._publish("run-missing", payload)

    assert normal.get_nowait() == payload
    assert hub._subs == {}
