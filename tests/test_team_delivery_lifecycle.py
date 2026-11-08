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
    "receipt,error,accepted",
    [
        ("Final answer and task dispositions accepted.", False, True),
        ("Unrelated success", False, False),
        ("Final answer and task dispositions accepted.", True, False),
    ],
)
async def test_only_successful_delivery_receipt_accepts(receipt, error, accepted):
    ctx = SimpleNamespace(metadata={})
    observer = TeamDeliveryObserver(TeamPhaseBudget(0, None, None, None, None, {}))
    await observer.on_tool_result(
        ctx, ToolResult("deliver_answer", {"content": "Final content"}, receipt, 1, "call", error)
    )
    assert bool(ctx.metadata.get("team_delivery_accepted")) is accepted


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
