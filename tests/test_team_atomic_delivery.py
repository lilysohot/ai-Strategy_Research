"""Final prose and board dispositions must fit in one coordinator generation."""

import json
from types import SimpleNamespace

import pytest

from frontier_agent.components.agent_bus import AgentBus
from frontier_agent.core.execution_context import (
    ExecutionScope,
    reset_current_execution_scope,
    set_current_execution_scope,
)
from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.loop_types import LoopConfig, TurnContext
from frontier_agent.core.runtime import registry
from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
from plugins.tools._bus_scope import SWARM_SCOPE_KEY
from plugins.tools.task_board import (
    add_task,
    bind_assignment,
    clear_board,
    drain_board_ops,
    snapshot_tasks,
)
from tests.test_agent_team_verification import add_job, binding
from workflows.agent_team.delivery import TeamDeliveryObserver, deliver_answer
from workflows.agent_team.phase_budget import TeamPhaseBudget


@pytest.fixture
def delivery_run():
    bus = AgentBus()
    saved = registry.snapshot()
    registry.register(AgentBus, bus)
    budget = TeamPhaseBudget(0, 495, 720, 900, 1200, {})
    runtime = SimpleNamespace(
        phase_budget=budget, publication_state={}, original_question="Explain the evidence"
    )
    token = set_current_execution_scope(
        ExecutionScope(task_id="run", metadata={SWARM_SCOPE_KEY: runtime})
    )
    yield bus, budget
    clear_board("run")
    reset_current_execution_scope(token)
    registry.restore(saved)


async def prepare(bus, verdict="pass"):
    await add_task.func(
        [
            {
                "description": "Check amount",
                "verification_requirements": [
                    {"check_id": "amount", "criterion": "Recompute the amount"},
                ],
            },
            {"description": "Answer the question", "kind": "delivery"},
        ]
    )
    add_job(bus, "j1", [binding()], verdicts=[verdict])
    bind_assignment("run", ["t1"], "reviewer", "j1")
    drain_board_ops("run")


async def test_one_generation_commits_dispositions_and_final_prose(delivery_run, monkeypatch):
    bus, budget = delivery_run
    await prepare(bus)
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 786.6)
    answer = "The independently checked amount is 50."

    class Client:
        model = "scripted"
        calls = 0

        async def chat(self, messages, **kwargs):
            self.calls += 1
            assert self.calls == 1, "board updates must not cost a second generation"
            assert [t["function"]["name"] for t in kwargs["tools"]] == ["deliver_answer"]
            assert any("[team delivery]" in str(m.get("content")) for m in messages)
            return LLMResponse(
                content="",
                tool_calls=[
                    {
                        "id": "finish",
                        "type": "function",
                        "function": {
                            "name": "deliver_answer",
                            "arguments": json.dumps(
                                {
                                    "content": answer,
                                    "updates": [
                                        {
                                            "id": "t1",
                                            "resolution": "resolved",
                                            "notes": "Bound check passed",
                                        }
                                    ],
                                }
                            ),
                        },
                    }
                ],
                finish_reason="tool_calls",
            )

    client = Client()
    result = await run_agent_loop(
        llm=client,
        system_prompt="Answer with evidence",
        user_message="What is the amount?",
        config=LoopConfig(task_id="run", max_turns=200),
        scope_metadata={SWARM_SCOPE_KEY: SimpleNamespace(original_question="What is the amount?")},
        tools=[deliver_answer],
        observers=[TeamDeliveryObserver(budget)],
    )
    assert result.final_content == answer
    assert result.stopped_by == "final_answer"
    assert [t["resolution"] for t in snapshot_tasks("run")] == ["resolved", "resolved"]


async def test_rejected_verification_rolls_back_entire_submission(delivery_run):
    bus, _ = delivery_run
    await prepare(bus, "unchecked")
    before = snapshot_tasks("run")
    with pytest.raises(ValueError):
        await deliver_answer.func(
            content="Amount is 50.",
            updates=[
                {
                    "id": "t2",
                    "resolution": "blocked",
                    "notes": "No file",
                    "gap": "File unavailable",
                },
                {"id": "t1", "resolution": "resolved", "notes": "Assumed complete"},
            ],
        )
    assert snapshot_tasks("run") == before
    assert drain_board_ops("run") == []


async def test_unchecked_work_can_be_submitted_as_explicit_partial(delivery_run):
    bus, _ = delivery_run
    await prepare(bus, "unchecked")
    await deliver_answer.func(
        content="The amount remains unverified.",
        updates=[
            {
                "id": "t1",
                "resolution": "blocked",
                "notes": "Review ended",
                "gap": "Amount unverified",
            },
        ],
    )
    assert snapshot_tasks("run")[0]["resolution"] == "blocked"
    assert snapshot_tasks("run")[0]["verification_status"] != "passed"


async def test_missing_required_check_does_not_trigger_early_delivery(delivery_run, monkeypatch):
    bus, budget = delivery_run
    await prepare(bus)
    bus._jobs.clear()
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 500)
    ctx = TurnContext(
        turn=21,
        max_turns=200,
        task_id="run",
        role_id="agent_team_main",
        ai_text="",
        thinking="",
        tool_calls=[],
        messages=[],
        usage=None,
        metadata={},
    )
    assert await TeamDeliveryObserver(budget).on_before_llm(ctx) is None


async def test_time_reserve_allows_partial_without_waiting_for_turn_192(delivery_run, monkeypatch):
    bus, budget = delivery_run
    await prepare(bus)
    bus._jobs.clear()
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 786.6)
    ctx = TurnContext(
        turn=21,
        max_turns=200,
        task_id="run",
        role_id="agent_team_main",
        ai_text="",
        thinking="",
        tool_calls=[],
        messages=[],
        usage=None,
        metadata={},
    )
    iv = await TeamDeliveryObserver(budget).on_before_llm(ctx)
    assert iv.allowed_tool_names == ("deliver_answer",)
    assert "blocked" in " ".join(iv.inject_messages)
    assert snapshot_tasks("run")[0]["resolution"] == "in_progress"


def turn_context(turn=21, max_turns=200, calls=None):
    return TurnContext(
        turn=turn,
        max_turns=max_turns,
        task_id="run",
        role_id="agent_team_main",
        ai_text="",
        thinking="",
        tool_calls=calls or [],
        messages=[],
        usage=None,
        metadata={},
    )


async def test_collected_checks_trigger_delivery_before_time_reserve(delivery_run, monkeypatch):
    bus, budget = delivery_run
    await prepare(bus)
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 100)
    ctx = turn_context()
    iv = await TeamDeliveryObserver(budget).on_before_llm(ctx)
    assert iv.allowed_tool_names == ("deliver_answer",)
    assert ctx.metadata["team_delivery_reason"] == "work_collected"


async def test_final_turn_retains_atomic_tool_in_real_request(delivery_run, monkeypatch):
    from frontier_agent.core.runtime.loop._bind import bind_tools
    from frontier_agent.core.runtime.loop.agent_loop import _prepare_llm_request

    bus, budget = delivery_run
    await prepare(bus)
    bus._jobs.clear()
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 100)
    client = object()
    bound = bind_tools(client, [deliver_answer.to_openai_schema()])
    meta = {"_llm_strip_tools": True}
    llm, _, _ = await _prepare_llm_request(
        LoopConfig(task_id="run", max_turns=22),
        [TeamDeliveryObserver(budget)],
        client,
        bound,
        [],
        meta,
        22,
    )
    assert [s["function"]["name"] for s in llm.tools] == ["deliver_answer"]
    assert meta["team_delivery_reason"] == "turn_reserve"


async def test_mixed_submission_rejects_all_mutations(delivery_run):
    _, budget = delivery_run
    calls = [{"name": "update_task"}, {"name": "deliver_answer"}]
    observer = TeamDeliveryObserver(budget)
    for call in calls:
        iv = await observer.on_tool_call(turn_context(calls=calls), call)
        assert iv.skip_is_error


async def test_unknown_task_rolls_back_valid_disposition(delivery_run):
    bus, _ = delivery_run
    await prepare(bus)
    before = snapshot_tasks("run")
    with pytest.raises(ValueError, match="no such task"):
        await deliver_answer.func(
            content="Amount is 50.",
            updates=[
                {"id": "t1", "resolution": "resolved", "notes": "Checked"},
                {"id": "unknown", "resolution": "resolved", "notes": "Checked"},
            ],
        )
    assert snapshot_tasks("run") == before
    assert drain_board_ops("run") == []


async def test_incomplete_member_cannot_be_marked_resolved(delivery_run):
    bus, _ = delivery_run
    await prepare(bus)
    bus._jobs["j1"].result.metadata["stopped_by"] = "wall_deadline"
    with pytest.raises(ValueError, match="member work incomplete"):
        await deliver_answer.func(
            content="Amount is 50.",
            updates=[
                {"id": "t1", "resolution": "resolved", "notes": "Assumed complete"},
            ],
        )


async def test_pending_file_publication_is_not_preempted(delivery_run, monkeypatch):
    bus, budget = delivery_run
    await prepare(bus)
    from frontier_agent.core.execution_context import get_current_execution_scope

    scope = get_current_execution_scope()
    scope.metadata[
        SWARM_SCOPE_KEY
    ].original_question = "Write the final report to /outputs/report.md"
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 100)
    assert await TeamDeliveryObserver(budget).on_before_llm(turn_context()) is None


@pytest.mark.parametrize(
    "receipt,expected",
    [
        ("Final answer and task dispositions accepted.", ["blocked", "resolved"]),
        ("Error: rejected submission", ["open", "open"]),
        (None, ["open", "open"]),
    ],
)
def test_continuation_replays_only_accepted_atomic_submission(delivery_run, receipt, expected):
    from plugins.tools.task_board import restore_board_from_messages

    def call(cid, name, args):
        return {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": cid,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }
            ],
        }

    messages = [
        call(
            "plan",
            "add_task",
            {
                "tasks": [
                    {"description": "Research"},
                    {"description": "Deliver", "kind": "delivery"},
                ]
            },
        ),
        {"role": "tool", "tool_call_id": "plan", "content": "Added ['t1', 't2']."},
        call(
            "finish",
            "deliver_answer",
            {
                "content": "Available evidence is limited.",
                "updates": [
                    {
                        "id": "t1",
                        "resolution": "blocked",
                        "notes": "Source unavailable",
                        "gap": "Missing original",
                    },
                ],
            },
        ),
    ]
    if receipt is not None:
        messages.append({"role": "tool", "tool_call_id": "finish", "content": receipt})
    restore_board_from_messages("run", messages)
    assert [t["resolution"] for t in snapshot_tasks("run")] == expected


async def test_delivery_phase_does_not_ask_for_new_assignments(delivery_run):
    from workflows.agent_team.observers.unassigned_nudge import UnassignedAgentNudge

    ctx = turn_context()
    ctx.metadata["team_delivery_started"] = True
    assert await UnassignedAgentNudge().on_turn_end(ctx) is None
