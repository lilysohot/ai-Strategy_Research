"""Dispatch freezes acceptance criteria, not progress or legitimate gap repair."""

import pytest

from plugins.tools.task_board import add_task, bind_assignment, snapshot_tasks, update_task
from tests.test_agent_team_inherited_publish_directive import TASK_ID
from tests.test_team_assignment_board_binding import board_dispatch as _board_dispatch
from tests.test_team_atomic_delivery import delivery_run as _delivery_run

delivery_run = _delivery_run
board_dispatch = _board_dispatch


@pytest.mark.parametrize("replacement", ["Read every available item", "Accept a preview", ""])
@pytest.mark.parametrize("via_add", [False, True])
async def test_dispatched_criterion_cannot_be_expanded_weakened_or_cleared(
    delivery_run, replacement, via_add,
):
    await add_task.func([{"description": "Answer requested question", "done_when": "Support the answer"}])
    bind_assignment("run", ["t1"], "reader", "job-1")
    before = snapshot_tasks("run")
    if via_add:
        result = await add_task.func([{
            "description": "Answer requested question", "done_when": replacement,
        }])
    else:
        result = await update_task.func(updates=[{
            "id": "t1", "done_when": replacement, "notes": "also must not be applied",
        }])
    assert "dispatched done_when is immutable" in result
    assert snapshot_tasks("run") == before


async def test_plan_can_change_before_dispatch_and_progress_can_change_after(delivery_run):
    await add_task.func([{"description": "Answer question", "done_when": "Initial draft"}])
    await update_task.func(updates=[{"id": "t1", "done_when": "Required outcome"}])
    bind_assignment("run", ["t1"], "reader", "job-1")
    result = await update_task.func(updates=[{
        "id": "t1", "done_when": "Required outcome", "notes": "One fact found",
        "gap": "Second required fact missing", "limitations": "Optional comparison omitted",
    }])
    assert "Updated" in result
    task = snapshot_tasks("run")[0]
    assert task["done_when"] == "Required outcome"
    assert task["gap"] == "Second required fact missing"
    assert task["resolution"] == "in_progress"


async def test_job_keeps_dispatch_contract_when_board_progress_changes(board_dispatch):
    from plugins.tools.assign_task import agent_team_assign_task

    await add_task.func([{
        "description": "Gather the requested observations", "kind": "research",
        "done_when": "Support both requested observations",
    }])
    reply = await agent_team_assign_task.func(tasks=[{
        "agent": "researcher", "prompt": "Read the source", "work_item_ids": ["t1"],
    }])
    assert not reply.startswith("Error"), reply
    metadata = board_dispatch.submitted[0][2]
    contract = metadata["work_item_contracts"][0]
    assert contract == {
        "id": "t1", "description": "Gather the requested observations",
        "done_when": "Support both requested observations", "verification_requirements": [],
    }
    assert "original_question" in metadata
    await update_task.func(updates=[{"id": "t1", "gap": "One observation still missing"}])
    assert snapshot_tasks(TASK_ID)[0]["gap"]
    assert "gap" not in contract
