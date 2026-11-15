"""Verification is an explicit contract, not a task name or a member's finish."""

import pytest

from frontier_agent.components.agent_bus import AgentBus
from frontier_agent.core.execution_context import (
    ExecutionScope,
    reset_current_execution_scope,
    set_current_execution_scope,
)
from frontier_agent.core.runtime import registry
from plugins.tools._bus_scope import SWARM_SCOPE_KEY
from plugins.tools._verification import work_item_verification_status
from plugins.tools.task_board import (
    add_task,
    bind_assignment,
    clear_board,
    drain_board_ops,
    snapshot_tasks,
    update_task,
)
from tests.test_agent_team_verification import add_job, binding
from workflows.agent_team.final_report import finalize_team_report


@pytest.fixture
def explicit_checks():
    bus = AgentBus()
    saved = registry.snapshot()
    registry.register(AgentBus, bus)
    token = set_current_execution_scope(
        ExecutionScope(task_id="run", metadata={SWARM_SCOPE_KEY: object()})
    )
    yield bus
    clear_board("run")
    reset_current_execution_scope(token)
    registry.restore(saved)


def board():
    return {task["id"]: task for task in snapshot_tasks("run")}


async def test_task_name_alone_does_not_create_a_required_check(explicit_checks):
    await add_task.func([{"description": "核验关键数字"}])
    task = board()["t1"]
    assert task.get("verification_required") is not True
    assert task.get("verification_requirements", []) == []

    # Nothing registered -> the item resolves like ordinary research.
    reply = await update_task.func([{"id": "t1", "resolution": "resolved", "notes": "已复算"}])
    assert "errors:" not in reply
    assert board()["t1"]["resolution"] == "resolved"


async def test_explicit_requirement_survives_a_kind_relabel(explicit_checks):
    await add_task.func([
        {
            "description": "复核金额",
            "verification_requirements": [{"check_id": "amount", "criterion": "重算总额"}],
        },
    ])
    assert board()["t1"]["verification_required"] is True

    await update_task.func([{"id": "t1", "kind": "research"}])
    task = board()["t1"]
    assert task["verification_required"] is True
    assert [check["check_id"] for check in task["verification_requirements"]] == ["amount"]


async def test_optional_extra_review_is_not_promoted_to_required(explicit_checks):
    await add_task.func([
        {"description": "解读文章"},
        {"description": "核验外部事实", "required_for_completion": False},
    ])
    tasks = board()
    assert tasks["t1"].get("verification_required") is not True
    assert tasks["t2"].get("verification_required") is not True
    assert tasks["t2"].get("required_for_completion") is False


async def test_member_completion_is_not_a_verification_pass(explicit_checks):
    bus = explicit_checks
    await add_task.func([
        {
            "description": "复核金额",
            "verification_requirements": [{"check_id": "amount", "criterion": "重算总额"}],
        },
    ])
    # The member job completed, but recorded no verdict for the registered check.
    add_job(bus, "j1", [binding(check_id="amount")], verdicts=[])
    bind_assignment("run", ["t1"], "reviewer", "j1")
    drain_board_ops("run")

    assert work_item_verification_status(bus, "run", "t1", ["amount"]) != "passed"


async def test_parent_aggregation_cannot_drop_the_child_check(explicit_checks):
    await add_task.func([{"description": "整篇复核"}])
    await add_task.func([
        {
            "description": "前半复核",
            "parent_id": "t1",
            "verification_requirements": [{"check_id": "half_a", "criterion": "重算前半"}],
        },
    ])
    receipt = await update_task.func([{"id": "t2", "resolution": "resolved", "notes": "已完成"}])
    assert "pass" in receipt
    assert board()["t2"]["resolution"] == "open"
    assert [c["check_id"] for c in board()["t2"]["verification_requirements"]] == ["half_a"]


async def test_complete_answer_can_remain_not_assessed(explicit_checks):
    await add_task.func([{"description": "解读文章"}])
    await update_task.func([{"id": "t1", "resolution": "resolved", "notes": "已解读"}])

    out = finalize_team_report(
        "文章的核心论点是需求成立但预算受限。",
        source="agent",
        answer_status="complete",
        stopped_by="final_answer",
        tasks=snapshot_tasks("run"),
    )
    assert out["answer_status"] == "complete"
    assert out["report_contract"]["verification"] == "not_assessed"
    assert out["report_contract"]["verification_checks"] == []


async def test_input_values_and_derived_results_are_classified_separately(explicit_checks):
    await add_task.func([
        {"description": "照录原文输入参数：2025E EBITDA=175", "kind": "research"},
        {"description": "推导隐含股权价值", "kind": "research"},
        {
            "description": "复核推导结果",
            "verification_required": True,
            "verification_requirements": [{"check_id": "derived", "criterion": "按公式复算"}],
        },
    ])
    tasks = board()
    assert tasks["t1"].get("verification_required") is not True
    assert tasks["t2"].get("verification_required") is not True
    assert tasks["t3"]["verification_required"] is True


def test_prompt_makes_verification_conditional():
    from workflows.agent_team.prompts import TEAM_MANAGEMENT

    assert "only when a check is required" in TEAM_MANAGEMENT
    assert "verification=not_assessed" in TEAM_MANAGEMENT


async def test_three_completion_classes_share_one_authoritative_predicate(explicit_checks):
    """T3: required outcome, optional enrichment and registered checks stay separate."""
    from frontier_agent.components.task_board_types import task_is_required
    from plugins.tools.task_board import verification_required

    await add_task.func([
        {"description": "ordinary interpretation"},
        {"description": "optional enrichment", "required_for_completion": False},
        {
            "description": "registered check",
            "verification_required": True,
            "verification_requirements": [{"check_id": "amount", "criterion": "recompute"}],
        },
        {"description": "核验关键数字（只是名字）"},
    ])
    tasks = board()
    assert [verification_required(tasks[tid]) for tid in ("t1", "t2", "t3", "t4")] == [
        False, False, True, False,
    ]
    assert task_is_required(tasks["t1"]) is True   # a required result, not a required check
    assert task_is_required(tasks["t2"]) is False  # optional enrichment
    assert verification_required(tasks["t2"]) is False

    # A relabel cannot drop the adopted check or upgrade the name-only item.
    await update_task.func([{"id": "t3", "kind": "research", "notes": "relabelled"}])
    assert verification_required(board()["t3"]) is True
    assert [c["check_id"] for c in board()["t3"]["verification_requirements"]] == ["amount"]
    assert verification_required(board()["t4"]) is False

    # Ordinary work still completes without an independent verifier.
    reply = await update_task.func([{"id": "t1", "resolution": "resolved", "notes": "已解读"}])
    assert "errors:" not in reply
    assert verification_required(board()["t1"]) is False
