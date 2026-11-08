"""Task completion must not be inferred from a topic, source type or idle roster."""

import json
from types import SimpleNamespace

import pytest

from frontier_agent.core.loop_types import ToolResult
from plugins.tools.assign_task import AgentTeamAssignmentSpec, agent_team_assign_task
from plugins.tools.finalize_answer import finalize_gate
from plugins.tools.task_board import add_task, bind_assignment, update_task
from tests.test_agent_team_verification import add_job, binding
from tests.test_team_atomic_delivery import delivery_run as _delivery_run
from tests.test_team_atomic_delivery import prepare, turn_context
from workflows.agent_team.delivery import TeamDeliveryObserver
from workflows.agent_team.observers.member_progress import MemberProgressObserver
from workflows.agent_team.observers.no_progress_guard import NoProgressGuard
from workflows.agent_team.observers.unassigned_nudge import UnassignedAgentNudge

delivery_run = _delivery_run


def test_legacy_lookup_hint_is_accepted_but_not_advertised_or_serialized():
    spec = AgentTeamAssignmentSpec(
        agent="worker", prompt="Complete the requested result",
        find_one_published_on="2026-11-06",
    )
    assert "find_one_published_on" not in spec.model_dump()
    assert "find_one_published_on" not in json.dumps(AgentTeamAssignmentSpec.model_json_schema())
    assert "find_one_published_on" not in json.dumps(agent_team_assign_task.parameters)


@pytest.mark.parametrize("source", ["corpus_search", "web_fetch", "read_file"])
@pytest.mark.parametrize("legacy_hint", [None, "2026-11-06"])
async def test_source_discovery_does_not_decide_completion(source, legacy_hint):
    metadata = {"find_one_published_on": legacy_hint} if legacy_hint else {}
    observer = MemberProgressObserver(metadata)
    ctx = SimpleNamespace(metadata={"corpus_evidence": [{}, {}], "web_evidence": [{}]})
    payload = {"ok": True, "hits": [{
        "doc_id": "cv2:" + "a" * 64, "published": "2026-11-06",
        "evidence_contract": "native-search-evidence-v2",
        "excerpts": [{"text": "A partial result, without the necessary fact.",
                      "ref": "eref:" + "b" * 64 + ":0"}],
    }]}
    await observer.on_tool_result(ctx, ToolResult(source, {}, json.dumps(payload), 1, "r", False))
    assert await observer.on_before_llm(ctx) is None
    assert await observer.on_tool_call(ctx, {"name": source, "args": {}}) is None
    assert "first_date_match" not in metadata


async def test_legacy_lookup_hint_cannot_preempt_required_verification():
    check = binding()
    observer = MemberProgressObserver({
        "find_one_published_on": "2026-11-06", "verification_checks": [check],
    })
    ctx = turn_context()
    await observer.on_tool_result(ctx, ToolResult("corpus_search", {}, json.dumps({
        "ok": True, "hits": [{
            "doc_id": "cv2:" + "a" * 64, "published": "2026-11-06",
            "evidence_contract": "native-search-evidence-v2",
            "excerpts": [{"text": "A matching date", "ref": "eref:" + "b" * 64 + ":0"}],
        }],
    }), 1, "candidate", False))
    notice = await observer.on_before_llm(ctx)
    assert check["binding_id"] in " ".join(notice.inject_messages)
    rejected = await observer.on_tool_call(ctx, {
        "name": "submit_report", "args": {"content": "Done without the required check"},
    })
    assert rejected.skip_is_error


async def idle_member(bus):
    await bus.create_session(
        task_id="run", name="unused", role_id="researcher", system_prompt="Available worker",
        tools_override=[], llm_override=object(),
    )


async def test_idle_member_does_not_block_completed_work(delivery_run, monkeypatch):
    bus, budget = delivery_run
    await prepare(bus)
    await idle_member(bus)
    try:
        ctx = turn_context()
        notice = await UnassignedAgentNudge().on_turn_end(ctx)
        assert "do not create empty assignments" in " ".join(notice.inject_messages)
        monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 500)
        observer = TeamDeliveryObserver(budget)
        decision = await observer.on_before_llm(ctx)
        assert observer.active
        assert decision.allowed_tool_names == ("deliver_answer",)
        assert bus.get_session("run::unused").total_task_count == 0
    finally:
        await bus.cleanup_task("run")


async def test_idle_member_does_not_waive_unassigned_required_work(delivery_run, monkeypatch):
    bus, budget = delivery_run
    await prepare(bus)
    await idle_member(bus)
    try:
        await add_task.func([{"description": "A necessary requirement remains unassigned"}])
        monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 500)
        observer = TeamDeliveryObserver(budget)
        await observer.on_before_llm(turn_context())
        assert not observer.active
        assert "unresolved" in finalize_gate("run", "Incomplete answer")
    finally:
        await bus.cleanup_task("run")


async def test_management_stall_is_not_a_completion_verdict(delivery_run):
    await add_task.func([{"description": "Required work still missing"}])
    observer = NoProgressGuard(soft_streak=2, hard_streak=4, min_repeated_creates=2)
    ctx = turn_context()
    ctx.tool_calls = [{"name": "create_subagent", "args": {}}]
    for turn in range(1, 5):
        ctx.turn = turn
        decision = await observer.on_turn_end(ctx)
        if turn == 2:
            notice = " ".join(decision.inject_messages)
            assert "does not establish" in notice
            assert "without claiming completion or bypassing verification" in notice
    assert decision.stop_reason == "thrash_no_progress"
    assert "unresolved" in finalize_gate("run", "No new evidence")


async def test_member_return_needs_goal_assessment_before_delivery(delivery_run, monkeypatch):
    bus, budget = delivery_run
    await add_task.func([{"description": "Read and assess the requested result"}])
    add_job(bus, "research", [])
    bind_assignment("run", ["t1"], "reader", "research")
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 500)
    observer = TeamDeliveryObserver(budget)
    await observer.on_before_llm(turn_context())
    assert not observer.active
    await update_task.func(updates=[{
        "id": "t1", "resolution": "resolved", "notes": "The returned findings meet the request",
    }])
    decision = await observer.on_before_llm(turn_context())
    assert observer.active
    assert decision.allowed_tool_names == ("deliver_answer",)
