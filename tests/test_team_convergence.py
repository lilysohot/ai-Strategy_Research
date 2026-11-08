"""Candidate discovery must not preempt necessary work; delivery ends expansion."""

import json
from types import SimpleNamespace

import pytest

from frontier_agent.core.loop_types import ToolResult
from plugins.tools.corpus_manifest import corpus_submit_manifest
from plugins.tools.corpus_search import corpus_search
from tests.test_team_atomic_delivery import delivery_run as _delivery_run
from tests.test_team_atomic_delivery import prepare, turn_context
from workflows.agent_team.delivery import TeamDeliveryObserver
from workflows.agent_team.observers.member_progress import MemberProgressObserver
from workflows.agent_team.subagent_runtime import SwarmSubagentRuntime, _sub_tools

delivery_run = _delivery_run


async def candidate_observer():
    observer = MemberProgressObserver({"find_one_published_on": "2026-11-06"})
    ctx = SimpleNamespace(metadata={})
    payload = {"ok": True, "hits": [{
        "doc_id": "cv2:" + "a" * 64, "published": "2026-11-06",
        "evidence_contract": "native-search-evidence-v2",
        "excerpts": [{"text": "A dated heading", "ref": "eref:" + "b" * 64 + ":0"}],
    }]}
    await observer.on_tool_result(ctx, ToolResult(
        "corpus_search", {}, json.dumps(payload), 1, "match", False,
    ))
    return observer, ctx


async def test_candidate_does_not_block_missing_necessary_evidence_or_manifest():
    observer, ctx = await candidate_observer()
    decision = await observer.on_before_llm(ctx)
    # A date match cannot decide whether the requested object/content is suitable.
    assert decision is None
    for name, args in [
        ("corpus_search", {"query": "identify the requested report, not a dated notice"}),
        ("corpus_submit_manifest", {"conclusions": []}),
    ]:
        assert await observer.on_tool_call(ctx, {"name": name, "args": args}) is None


def test_saved_member_tools_match_actual_companion_binding():
    from plugins.tools.create_subagent import _runtime_tools_override

    runtime = SwarmSubagentRuntime(sub_agent_tools=[corpus_search])
    actual = _runtime_tools_override(runtime)
    assert corpus_submit_manifest in actual
    assert {t.name for t in _sub_tools(runtime)} == {t.name for t in actual}


@pytest.mark.parametrize("tool_name", ["assign_task", "create_subagent", "web_search"])
async def test_completed_work_delivers_before_any_expansion(delivery_run, monkeypatch, tool_name):
    bus, budget = delivery_run
    await prepare(bus)
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 500)
    observer = TeamDeliveryObserver(budget)
    ctx = turn_context()
    decision = await observer.on_before_llm(ctx)
    assert observer.active
    assert decision.allowed_tool_names == ("deliver_answer",)
    denied = await observer.on_tool_call(ctx, {"name": tool_name, "args": {}})
    assert denied.skip_is_error


async def test_required_failed_check_remains_open_for_repair(delivery_run, monkeypatch):
    bus, budget = delivery_run
    await prepare(bus, "fail")
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 500)
    observer = TeamDeliveryObserver(budget)
    decision = await observer.on_before_llm(turn_context())
    assert not observer.active
    assert "team verification repair" in " ".join(decision.inject_messages)
