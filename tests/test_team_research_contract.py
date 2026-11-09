"""Research consumes its board contract at the actual member-loop boundary."""

import asyncio
import json
from dataclasses import replace

import pytest

from frontier_agent.core.execution_context import get_current_execution_scope
from frontier_agent.core.messages import assistant_msg, user_msg
from plugins.tools._bus_scope import SWARM_SCOPE_KEY
from plugins.tools.assign_task import agent_team_assign_task
from plugins.tools.collect_reports import collect_reports
from plugins.tools.corpus_fetch import corpus_fetch
from plugins.tools.corpus_search import corpus_search
from plugins.tools.submit_report import submit_report
from plugins.tools.task_board import add_task, update_task
from tests.test_team_verification_admission import admission_run as _admission_run

admission_run = _admission_run


@pytest.fixture
def captured_loop(monkeypatch):
    from frontier_agent.components.agent_bus import bus as bus_module

    captured = []
    previous = bus_module.run_agent_loop

    async def capture(**kwargs):
        captured.append(kwargs)
        return await previous(**kwargs)

    monkeypatch.setattr(bus_module, "run_agent_loop", capture)
    return captured


@pytest.mark.parametrize("criterion", [
    "Return one supported route within the requested budget",
    "Read every supplied section and identify all incompatible conditions",
])
async def test_bound_research_uses_contract_without_proposal_role_or_history(
    admission_run, captured_loop, criterion,
):
    bus, runtime = admission_run
    original = "Evaluate the supplied material under my stated coverage requirements"
    get_current_execution_scope().metadata[SWARM_SCOPE_KEY] = replace(
        runtime, original_question=original, sub_prompt_suffix="RUNTIME_INPUTS /inputs/source.txt",
    )
    session = bus.get_session("run::reviewer")
    session.system_prompt = "ROLE_EXPANSION: Always rank all alternatives"
    session.tools = [corpus_fetch, corpus_search, submit_report]
    session.messages = [user_msg("HISTORICAL_EXPANSION"), assistant_msg("Old plan")]
    session.task_boundaries = [(0, 1)]
    session.last_report = "ATTACHED_SOURCE: measured duration is 25 minutes"
    await add_task.func([{
        "description": "Evaluate the supplied material", "kind": "research",
        "done_when": criterion,
        "notes": "METHOD_INPUT: sum durations from /inputs/source.txt",
        "evidence_refs": ["source-observation-1"],
    }])
    proposal = 'DISPATCH_EXPANSION: Rank every alternative. <attach agent="reviewer"/>'
    reply = await agent_team_assign_task.func(tasks=[{
        "agent": "reviewer", "prompt": proposal, "work_item_ids": ["t1"],
    }])
    assert not reply.startswith("Error"), reply
    await collect_reports.func(timeout=2)
    assert len(captured_loop) == 1
    call = captured_loop[0]
    visible = json.dumps(
        [call["system_prompt"], call["user_message"], call["initial_messages"]],
        ensure_ascii=False,
    )
    assert criterion in call["user_message"]
    assert original in call["user_message"]
    assert "METHOD_INPUT" in call["user_message"]
    assert "source-observation-1" in call["user_message"]
    assert "ATTACHED_SOURCE" in call["user_message"]
    assert "RUNTIME_INPUTS" in call["system_prompt"]
    for marker in ("DISPATCH_EXPANSION", "ROLE_EXPANSION", "HISTORICAL_EXPANSION"):
        assert marker not in visible
    assert {tool.name for tool in call["tools"]} == {
        "corpus_fetch", "corpus_search", "submit_report",
    }, "Research still needs acquisition and full-document access"
    metadata = bus.list_task_jobs("run")[0].item.metadata
    assert metadata["proposed_prompt"] == proposal
    assert "ROLE_EXPANSION" in metadata["proposed_system_prompt"]
    assert metadata["work_item_contracts"][0]["done_when"] == criterion


async def test_boardless_assignment_keeps_existing_input_path(admission_run, captured_loop):
    bus, _ = admission_run
    session = bus.get_session("run::reviewer")
    session.system_prompt = "Existing role"
    reply = await agent_team_assign_task.func(tasks=[{
        "agent": "reviewer", "prompt": "Existing task without a board",
    }])
    assert not reply.startswith("Error"), reply
    await collect_reports.func(timeout=2)
    assert "Existing task without a board" in captured_loop[0]["user_message"]
    assert captured_loop[0]["system_prompt"] == "Existing role"


async def test_queued_research_keeps_dispatch_inputs_after_board_and_role_changes(
    admission_run, captured_loop, monkeypatch,
):
    from frontier_agent.components.agent_bus import bus as bus_module

    bus, _ = admission_run
    started, release, second_finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    previous = bus_module.run_agent_loop
    calls = 0

    async def hold_first(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
            return await previous(**kwargs)
        result = await previous(**kwargs)
        second_finished.set()
        return result

    monkeypatch.setattr(bus_module, "run_agent_loop", hold_first)
    await add_task.func([
        {"description": "First observation", "done_when": "First supported observation"},
        {"description": "Second observation", "done_when": "Second supported observation",
         "notes": "INPUT_AT_DISPATCH"},
    ])
    try:
        for tid in ("t1", "t2"):
            result = await agent_team_assign_task.func(tasks=[{
                "agent": "reviewer", "prompt": "FREE_PROPOSAL", "work_item_ids": [tid],
            }])
            assert not result.startswith("Error"), result
            if tid == "t1":
                await asyncio.wait_for(started.wait(), 2)
        assert bus.list_task_jobs("run")[1].status == "queued"
        await update_task.func(updates=[{"id": "t2", "notes": "LATER_BOARD_CHANGE"}])
        bus.get_session("run::reviewer").system_prompt = "LATER_ROLE_CHANGE"
        release.set()
        await asyncio.wait_for(second_finished.wait(), 2)
        await collect_reports.func(timeout=2)
        second = captured_loop[1]
        assert "Second supported observation" in second["user_message"]
        assert "INPUT_AT_DISPATCH" in second["user_message"]
        assert "LATER_BOARD_CHANGE" not in second["user_message"]
        assert "LATER_ROLE_CHANGE" not in second["system_prompt"]
        assert not any(m.get("role") == "user" for m in second["initial_messages"])
    finally:
        release.set()


async def test_bound_research_can_submit_through_real_member_loop(admission_run, monkeypatch):
    from frontier_agent.core.llm import LLMResponse
    from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
    from workflows.agent_team.subagent_runtime import build_swarm_session_runtime_spec

    bus, runtime = admission_run

    class Client:
        model = "scripted"
        calls = 0

        async def chat(self, messages, **kwargs):
            self.calls += 1
            assert self.calls == 1
            visible = json.dumps(messages, ensure_ascii=False)
            assert "Report the supplied observation" in visible
            assert "25 minutes" in visible
            assert "UNBOUND_EXPANSION" not in visible
            names = {tool["function"]["name"] for tool in kwargs["tools"]}
            assert {"corpus_fetch", "corpus_search", "submit_report"} <= names
            return LLMResponse(content="", tool_calls=[{
                "id": "report", "type": "function", "function": {
                    "name": "submit_report",
                    "arguments": json.dumps({"content": "The recorded duration is 25 minutes."}),
                },
            }], finish_reason="tool_calls")

    monkeypatch.setattr("frontier_agent.components.agent_bus.bus.run_agent_loop", run_agent_loop)
    session = bus.get_session("run::reviewer")
    client = Client()
    session.llm = client
    session.tools = [corpus_fetch, corpus_search, submit_report]
    runtime = replace(runtime, sub_agent_tools=session.tools)
    get_current_execution_scope().metadata[SWARM_SCOPE_KEY] = runtime
    session.runtime_spec = build_swarm_session_runtime_spec(
        runtime, session_name="reviewer", task_id="run",
    )
    session.system_prompt = "UNBOUND_EXPANSION: compare all sources before reporting"
    await add_task.func([{
        "description": "Report the supplied observation", "done_when": "Give the duration",
        "notes": "Supplied observation: 25 minutes",
    }])
    reply = await agent_team_assign_task.func(tasks=[{
        "agent": "reviewer", "prompt": "UNBOUND_EXPANSION: collect alternative measurements",
        "work_item_ids": ["t1"],
    }])
    assert not reply.startswith("Error"), reply
    await collect_reports.func(timeout=2)
    result = bus.list_task_jobs("run")[0].result
    assert result.success
    assert result.metadata["stopped_by"] == "final_answer"
    assert result.final_content == "The recorded duration is 25 minutes."
    assert client.calls == 1
