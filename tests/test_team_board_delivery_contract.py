"""Regression for dcf84a9: register -> dispatch -> verdict -> partial delivery."""

from copy import deepcopy

import pytest

from frontier_agent.components.agent_bus import AgentBus
from frontier_agent.core.execution_context import (
    ExecutionScope,
    reset_current_execution_scope,
    set_current_execution_scope,
)
from frontier_agent.core.loop_types import AgentLoopResult, TurnContext
from frontier_agent.core.messages import tool_msg
from frontier_agent.core.runtime import registry
from plugins.tools._verification import VerificationCheck, bind_checks
from plugins.tools.task_board import add_task, clear_board, snapshot_tasks, update_task
from tests.test_agent_team_verification import add_job, binding
from workflows.agent_team.final_report import finalize_team_report
from workflows.agent_team.lifecycle import wind_down_team
from workflows.agent_team.observers.bare_text_finalize import BareTextFinalizeObserver
from workflows.agent_team.subagent_runtime import force_final_answer


@pytest.fixture
def board_bus():
    bus = AgentBus()
    saved = registry.snapshot()
    registry.register(AgentBus, bus)
    token = set_current_execution_scope(
        ExecutionScope(task_id="run", metadata={"swarm_subagent_runtime": object()})
    )
    yield bus
    clear_board("run")
    reset_current_execution_scope(token)
    registry.restore(saved)


def requirement(check_id="amount"):
    return {"check_id": check_id, "criterion": "Recompute the amount"}


async def test_update_registers_checks_and_dispatch_uses_same_definition(board_bus, tmp_path):
    await add_task.func([{"description": "独立核验关键事实"}])
    reply = await update_task.func([{
        "id": "t1", "resolution": "in_progress",
        "verification_requirements": [requirement()],
    }])
    tasks = snapshot_tasks("run")
    assert tasks[0]["verification_requirements"] == [requirement()], reply
    add_job(board_bus, "draft", [])
    spec = VerificationCheck(
        **requirement(), work_item_id="t1", subject={"job_id": "draft"},
        evidence=[{"job_id": "draft"}],
    )
    bound, _ = bind_checks(
        [spec], bus=board_bus, task_id="run", work_items=tasks,
        required=True, outputs_root=tmp_path,
    )
    add_job(board_bus, "verify", bound, verdicts=["pass"])
    reply = await update_task.func([{"id": "t1", "resolution": "resolved"}])
    assert snapshot_tasks("run")[0]["resolution"] == "resolved", reply


@pytest.mark.parametrize("change", ["id", "criterion", "optional"])
async def test_dispatch_rejects_plan_mismatch_before_enqueuing(board_bus, tmp_path, change):
    await add_task.func([{
        "description": "Verify amount", "verification_requirements": [requirement()],
    }])
    add_job(board_bus, "draft", [])
    spec = VerificationCheck(
        **requirement(), work_item_id="t1", subject={"job_id": "draft"},
        evidence=[{"job_id": "draft"}],
    )
    if change == "id":
        spec.check_id = "different"
    elif change == "criterion":
        spec.criterion = "Just inspect formatting"
    with pytest.raises(ValueError, match=r"planned|requirement"):
        bind_checks(
            [spec], bus=board_bus, task_id="run", work_items=snapshot_tasks("run"),
            required=change != "optional", outputs_root=tmp_path,
        )


@pytest.mark.parametrize("tool_name", ["add", "update"])
async def test_dispatched_requirement_cannot_be_overwritten(board_bus, tool_name):
    await add_task.func([{
        "description": "Verify amount", "verification_requirements": [requirement()],
    }])
    add_job(board_bus, "verify", [binding()], verdicts=["unchecked"])
    before = deepcopy(snapshot_tasks("run"))
    args = {"verification_requirements": [requirement("replacement")]}
    if tool_name == "add":
        reply = await add_task.func([{"description": "Verify amount", **args}])
    else:
        reply = await update_task.func([{"id": "t1", **args}])
    assert reply.startswith("Error:"), reply
    assert snapshot_tasks("run") == before


async def test_unknown_update_field_is_rejected_without_mutation(board_bus):
    await add_task.func([{"description": "Research"}])
    reply = await update_task.func([{
        "id": "t1", "resolution": "resolved", "verification_requirement": [],
    }])
    assert reply.startswith("Error:"), reply
    assert "verification_requirement" in reply
    assert snapshot_tasks("run")[0]["resolution"] == "open"


async def test_rejected_resolution_preserves_honest_progress(board_bus):
    await add_task.func([{
        "description": "Verify amount", "verification_requirements": [requirement()],
    }])
    add_job(board_bus, "verify", [binding()], verdicts=["unchecked"])
    reply = await update_task.func([{
        "id": "t1", "resolution": "resolved", "notes": "Review finished",
        "gap": "Independent source unavailable",
    }])
    task = snapshot_tasks("run")[0]
    assert task["resolution"] != "resolved"
    assert task["notes"] == "Review finished", reply
    assert task["gap"] == "Independent source unavailable"
    assert "blocked" in reply


@pytest.mark.parametrize("verdicts", [["unchecked"], ["fail"], ["pass", "unchecked", "unchecked", "unchecked"]])
async def test_blocked_check_delivers_answer_without_fabricating_pass(board_bus, verdicts):
    keys = [f"check.{i}" for i in range(len(verdicts))]
    await add_task.func([{
        "description": "Verify amount", "verification_requirements": [requirement(key) for key in keys],
    }])
    add_job(board_bus, "verify", [binding(key) for key in keys], verdicts=verdicts)
    reply = await update_task.func([{
        "id": "t1", "resolution": "blocked", "notes": "Review finished",
        "gap": "Independent source unavailable",
    }])
    task = snapshot_tasks("run")[0]
    assert task["resolution"] == "blocked", reply
    expected_status = "partial" if len(verdicts) > 1 else "failed" if verdicts == ["fail"] else "unchecked"
    assert task["verification_status"] == expected_status
    assert task["verification_execution_status"] == "complete"
    text = "已有证据支持这个优势；相关数字尚未得到独立确认。"
    ctx = TurnContext(
        turn=16, max_turns=200, task_id="run", role_id="main", ai_text=text,
        thinking="", tool_calls=[], messages=[], usage=None, metadata={},
    )
    intervention = await BareTextFinalizeObserver().on_llm_response(ctx)
    assert intervention.stop_reason == "final_answer"
    wind = await wind_down_team(bus=board_bus, task_id="run", wait_s=0)
    # The production node finalizes after bus cleanup. The persisted wind-down
    # contract must preserve verdicts even when the live projection disappears.
    await board_bus.cleanup_task("run")
    result = AgentLoopResult(messages=[], final_content=text, stopped_by="final_answer", metadata=ctx.metadata)
    await force_final_answer(
        result, object(), 1, force_recovery=wind.should_refresh_answer(result),
        prefer_collected_reports=wind.requires_resynthesis, run_recovery_llm=False,
    )
    out = finalize_team_report(
        result.final_content, source="agent", answer_status="complete",
        stopped_by=result.stopped_by, question="有哪些优势？",
        wind_down=wind.as_dict(), tasks=snapshot_tasks("run"),
    )
    assert text in out["final_answer"]
    assert "Independent source unavailable" in out["final_answer"]
    assert out["answer_status"] == "partial"
    assert [c["verdict"] for c in out["report_contract"]["verification_checks"]] == verdicts
    assert out["report_contract"]["task_board"][0]["verification_execution_status"] == "complete"
    assert out["report_contract"]["task_board"][0]["verification_status"] == expected_status


async def test_blocked_requires_reason_and_gap(board_bus):
    await add_task.func([{"description": "Research"}])
    reply = await update_task.func([{"id": "t1", "resolution": "blocked"}])
    assert reply.startswith("Error:"), reply
    assert snapshot_tasks("run")[0]["resolution"] == "open"


async def test_delivery_is_completed_by_accepted_answer_not_board_claim(board_bus):
    await add_task.func([{"description": "Write answer", "kind": "delivery"}])
    await update_task.func([{"id": "t1", "resolution": "resolved", "notes": "Draft ready"}])
    assert snapshot_tasks("run")[0]["resolution"] == "in_progress"
    ctx = TurnContext(
        turn=4, max_turns=200, task_id="run", role_id="main", ai_text="The answer.",
        thinking="", tool_calls=[], messages=[], usage=None, metadata={},
    )
    outcome = await BareTextFinalizeObserver().on_llm_response(ctx)
    assert outcome.stop_reason == "final_answer"
    assert snapshot_tasks("run")[0]["resolution"] == "resolved"


async def test_invalid_add_batch_has_no_partial_writes(board_bus):
    reply = await add_task.func([
        {"description": "Research"}, {"description": "Verify", "unknown_field": True},
    ])
    assert reply.startswith("Error:")
    assert snapshot_tasks("run") == []


async def test_reused_task_receipt_and_global_check_ids(board_bus):
    item = {"description": "Verify amount", "verification_requirements": [requirement()]}
    await add_task.func([item])
    reply = await add_task.func([item])
    assert "Reused existing IDs ['t1']" in reply
    assert len(snapshot_tasks("run")) == 1
    reply = await add_task.func([{**item, "description": "Verify another amount"}])
    assert reply.startswith("Error:")
    assert len(snapshot_tasks("run")) == 1


async def test_plan_and_rejected_resolution_replay_preserve_actual_state(board_bus):
    import json

    from frontier_agent.core.messages import assistant_msg
    from plugins.tools.task_board import restore_board_from_messages

    messages = []
    calls = [
        (add_task, {"tasks": [{"description": "Verify amount"}]}),
        (update_task, {"updates": [{"id": "t1", "verification_requirements": [requirement()]}]}),
        (update_task, {"updates": [{"id": "t1", "resolution": "resolved", "gap": "No source"}]}),
    ]
    for index, (tool, args) in enumerate(calls):
        call_id = f"c{index}"
        messages.append(assistant_msg("", tool_calls=[{
            "id": call_id, "type": "function",
            "function": {"name": tool.name, "arguments": json.dumps(args)},
        }]))
        messages.append(tool_msg(await tool.func(**args), call_id))
    expected = snapshot_tasks("run")
    restore_board_from_messages("run", messages)
    assert snapshot_tasks("run") == expected


async def test_deadline_keeps_candidate_even_when_gate_blocked(board_bus):
    await add_task.func([{"description": "Research"}])
    text = "已有证据支持这个优势；仍有待核实事项。"
    ctx = TurnContext(
        turn=16, max_turns=200, task_id="run", role_id="main", ai_text=text,
        thinking="", tool_calls=[], messages=[], usage=None, metadata={},
    )
    intervention = await BareTextFinalizeObserver().on_llm_response(ctx)
    assert intervention.continue_to_next_turn
    assert "final_answer" not in ctx.metadata
    result = AgentLoopResult(
        messages=[tool_msg('<report agent="researcher">Internal evidence</report>', "c1")],
        final_content="", stopped_by="wall_deadline", metadata=ctx.metadata,
    )
    await force_final_answer(
        result, object(), 1, prefer_collected_reports=True, run_recovery_llm=False,
    )
    assert result.final_content == text
    assert result.metadata["final_answer_source"] == "existing_partial"
    ctx.tool_calls = [{"id": "new-work", "name": "collect_reports", "args": {}}]
    await BareTextFinalizeObserver().on_llm_response(ctx)
    assert "final_answer_candidate" not in ctx.metadata


def test_update_schema_exposes_check_definition_and_rejects_unknown_fields():
    parameters = update_task.to_openai_schema()["function"]["parameters"]
    item = parameters["properties"]["updates"]["items"]
    assert item["additionalProperties"] is False
    assert "verification_requirements" in item["properties"]
