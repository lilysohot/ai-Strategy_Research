"""Real execution receipts, cancellation and recovered obligations at delivery."""

import json
from types import SimpleNamespace

import pytest

from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.loop_types import (
    BaseObserver,
    LoopConfig,
    ToolCallIntervention,
    ToolResult,
)
from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
from server.approval import ApprovalGate, ApprovalObserver
from workflows.agent_team.delivery import TeamDeliveryObserver, deliver_answer
from workflows.agent_team.phase_budget import TeamPhaseBudget


@pytest.mark.parametrize("kind", ["stopped", "skipped"])
async def test_synthetic_delivery_is_not_accepted(kind):
    gate = ApprovalGate()
    gate.reject_pending()

    class Skip(BaseObserver):
        async def on_tool_call(self, ctx, call):
            return ToolCallIntervention(
                skip_with_result="Final answer and task dispositions accepted."
            )

    class Client:
        model = "fixture"

        async def chat(self, messages, **kwargs):
            return LLMResponse(
                content="",
                tool_calls=[
                    {
                        "id": "delivery",
                        "type": "function",
                        "function": {
                            "name": "deliver_answer",
                            "arguments": json.dumps(
                                {
                                    "content": "Uncommitted draft",
                                    "updates": [],
                                }
                            ),
                        },
                    }
                ],
                finish_reason="tool_calls",
            )

    observer = ApprovalObserver(gate, lambda _: None, "/tmp") if kind == "stopped" else Skip()
    result = await run_agent_loop(
        llm=Client(),
        system_prompt="Test",
        user_message="Test",
        config=LoopConfig(task_id="stop-check", max_turns=1),
        tools=[deliver_answer],
        observers=[observer, TeamDeliveryObserver(TeamPhaseBudget(0, None, None, None, None, {}))],
    )
    assert result.stopped_by != "final_answer"
    assert not result.metadata.get("team_delivery_accepted")
    assert not result.metadata.get("final_answer")


@pytest.mark.parametrize(
    "receipt,error,with_record,accepted",
    [
        ("Final answer and task dispositions accepted.", False, True, True),
        # A synthetic success receipt with tool arguments but no accepted
        # delivery record must not publish: the body is never rebuilt from args.
        ("Final answer and task dispositions accepted.", False, False, False),
        ("Unrelated success", False, True, False),
        ("Final answer and task dispositions accepted.", True, True, False),
    ],
)
async def test_only_successful_delivery_receipt_accepts(receipt, error, with_record, accepted):
    from frontier_agent.core.execution_context import (
        ExecutionScope,
        reset_current_execution_scope,
        set_current_execution_scope,
    )
    from workflows.agent_team.delivery import (
        _DELIVERY_RECORD_KEY,
        DELIVERY_PROTOCOL_VERSION,
    )

    ctx = SimpleNamespace(metadata={})
    observer = TeamDeliveryObserver(TeamPhaseBudget(0, None, None, None, None, {}))
    token = None
    if with_record:
        token = set_current_execution_scope(ExecutionScope(
            task_id="run",
            metadata={_DELIVERY_RECORD_KEY: {
                "protocol_version": DELIVERY_PROTOCOL_VERSION,
                "status": "accepted",
                "published": True,
                "content": "Final content",
            }},
        ))
    try:
        await observer.on_tool_result(
            ctx, ToolResult("deliver_answer", {"content": "Final content"}, receipt, 1, "call", error)
        )
        assert bool(ctx.metadata.get("team_delivery_accepted")) is accepted
        assert ctx.metadata.get("final_answer") == ("Final content" if accepted else None)
    finally:
        if token is not None:
            reset_current_execution_scope(token)


async def test_failed_delivery_hands_its_candidate_to_recovery():
    """A repairable failure keeps the body for the recovery path, not a new draft."""
    from frontier_agent.core.execution_context import (
        ExecutionScope,
        reset_current_execution_scope,
        set_current_execution_scope,
    )
    from workflows.agent_team.delivery import _CANDIDATE_KEY

    ctx = SimpleNamespace(metadata={})
    observer = TeamDeliveryObserver(TeamPhaseBudget(0, None, None, None, None, {}))
    token = set_current_execution_scope(ExecutionScope(
        task_id="run",
        metadata={_CANDIDATE_KEY: {"version": 1, "content": "Retained usable body."}},
    ))
    try:
        await observer.on_tool_result(ctx, ToolResult(
            "deliver_answer", {"content": ""},
            "Delivery preflight failed (candidate v1 stored; nothing committed)",
            1, "call", True,
        ))
        assert ctx.metadata["final_answer_candidate"] == "Retained usable body."
        assert not ctx.metadata.get("final_answer")
        assert not ctx.metadata.get("team_delivery_accepted")
    finally:
        reset_current_execution_scope(token)


@pytest.mark.parametrize("reason", ["user_stop", "deadline", "cancelled"])
def test_interrupted_report_is_not_published(reason):
    from workflows.agent_team.final_report import finalize_team_report

    result = finalize_team_report(
        "Retained partial findings.",
        source="agent",
        answer_status="complete",
        stopped_by=reason,
        wind_down={},
    )
    assert result["report_contract"]["publication"]["status"] == "interrupted"
    assert result["answer_status"] != "complete"


def test_late_worker_stop_reconciles_report_without_erasing_history():
    from server.run_outcome import reconcile_team_termination

    outcome = {
        "answer_status": "complete",
        "report_contract": {
            "stopped_by": "final_answer",
            "answer_status": "complete",
            "kind": "complete",
            "publication": {"status": "published"},
            "gaps": [],
        },
    }
    reconcile_team_termination(outcome, "user_stop")
    contract = outcome["report_contract"]
    assert contract["stopped_by"] == "user_stop"
    assert contract["workflow_stopped_by"] == "final_answer"
    assert contract["publication"]["status"] == "interrupted"
    assert outcome["answer_status"] == contract["answer_status"] == "partial"
    reconcile_team_termination(outcome, "user_stop")
    assert len(contract["gaps"]) == 1


@pytest.mark.parametrize("state", ["failed", "skipped", "cancelled"])
async def test_non_successful_execution_cannot_accept_receipt(state):
    ctx = SimpleNamespace(metadata={})
    observer = TeamDeliveryObserver(TeamPhaseBudget(0, None, None, None, None, {}))
    result = ToolResult(
        "deliver_answer",
        {"content": "Uncommitted"},
        "Final answer and task dispositions accepted.",
        0,
        "call",
        False,
        execution_status=state,
    )
    await observer.on_tool_result(ctx, result)
    assert not ctx.metadata.get("team_delivery_accepted")
