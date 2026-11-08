"""Further research needs a board gap; checks retain their own exact binding."""

import pytest

from plugins.tools.assign_task import agent_team_assign_task
from plugins.tools.task_board import add_task, snapshot_tasks, update_task
from tests.test_agent_team_inherited_publish_directive import TASK_ID
from tests.test_team_assignment_board_binding import board_dispatch as _board_dispatch

board_dispatch = _board_dispatch


async def dispatch():
    return await agent_team_assign_task.func(tasks=[{
        "agent": "researcher", "prompt": "Gather observations", "work_item_ids": ["t1"],
    }])


@pytest.mark.parametrize("gap", [None, "", "   "])
async def test_research_redispatch_without_gap_is_atomic_rejection(board_dispatch, gap):
    await add_task.func([{"description": "Answer requested question", "kind": "research"}])
    assert not (await dispatch()).startswith("Error")
    if gap is not None:
        await update_task.func(updates=[{"id": "t1", "gap": gap}])
    before = snapshot_tasks(TASK_ID)
    reply = await dispatch()
    assert "recorded gap" in reply
    assert len(board_dispatch.submitted) == 1
    assert snapshot_tasks(TASK_ID) == before


async def test_required_gap_allows_repair_and_preserves_dispatch_snapshot(board_dispatch):
    await add_task.func([{"description": "Answer requested question", "kind": "research"}])
    await dispatch()
    await update_task.func(updates=[{"id": "t1", "gap": "Second requested observation missing"}])
    reply = await dispatch()
    assert not reply.startswith("Error"), reply
    metadata = board_dispatch.submitted[1][2]
    assert metadata["work_item_gaps"] == {
        "t1": {"gap": "Second requested observation missing", "prior_job_ids": ["job-1"]},
    }
    await update_task.func(updates=[{"id": "t1", "gap": "Another observed condition"}])
    assert metadata["work_item_gaps"]["t1"]["gap"] == "Second requested observation missing"


async def test_resolved_item_cannot_restart_research_from_stale_gap(board_dispatch):
    await add_task.func([{"description": "Answer requested question", "kind": "research"}])
    await dispatch()
    reply = await update_task.func(updates=[{
        "id": "t1", "resolution": "resolved", "notes": "Supported by collected evidence",
        "gap": "Stale gap text",
    }])
    assert "Updated" in reply
    assert "recorded gap" in await dispatch()
    assert len(board_dispatch.submitted) == 1
