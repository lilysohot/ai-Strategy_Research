"""Dispatch binds exact board work items before a report can be attributed."""

import asyncio
from types import SimpleNamespace

import pytest

from frontier_agent.components.agent_bus import AgentBus
from frontier_agent.core.execution_context import (
    ExecutionScope,
    reset_current_execution_scope,
    set_current_execution_scope,
)
from frontier_agent.core.runtime import registry
from plugins.tools._bus_scope import SWARM_SCOPE_KEY
from plugins.tools.assign_task import agent_team_assign_task
from plugins.tools.task_board import add_task, clear_board, snapshot_tasks
from tests.test_agent_team_inherited_publish_directive import TASK_ID, _FakeBus, _session
from workflows.agent_team.final_report import finalize_team_report


@pytest.fixture
def board_dispatch():
    bus = _FakeBus({f"{TASK_ID}::researcher": _session("researcher")})
    bus.list_task_jobs = lambda *_: []
    runtime = SimpleNamespace(publication_state={}, publication_lock=asyncio.Lock(), original_question="")
    saved = registry.snapshot()
    registry.register(AgentBus, bus)
    token = set_current_execution_scope(ExecutionScope(task_id=TASK_ID, metadata={SWARM_SCOPE_KEY: runtime}))
    yield bus
    clear_board(TASK_ID)
    reset_current_execution_scope(token)
    registry.restore(saved)


async def test_dispatch_links_exact_jobs_without_marking_verification_passed(board_dispatch):
    await add_task.func([{"description": "核验金额"}, {"description": "解释结果"}])
    reply = await agent_team_assign_task.func(tasks=[{
        "agent": "researcher", "prompt": "Read sources", "work_item_ids": ["t1"],
    }])
    assert not reply.startswith("Error"), reply
    tasks = snapshot_tasks(TASK_ID)
    assert tasks[0]["owners"] == ["researcher"]
    assert tasks[0]["resolution"] == "in_progress"
    assert tasks[0]["execution_job_ids"] == ["job-1"]
    assert board_dispatch.submitted[0][2]["work_item_ids"] == ["t1"]
    out = finalize_team_report(
        "Sources collected; checks remain.", source="agent", answer_status="partial",
        stopped_by="final_answer", tasks=tasks,
        wind_down={"job_outcomes": [
            {"job_id": "job-1", "agent": "researcher", "status": "complete"},
            {"job_id": "job-other", "agent": "researcher", "status": "failed"},
        ]},
    )
    task = out["report_contract"]["task_board"][0]
    assert task["execution_status"] == "complete"
    assert task["execution_job_ids"] == ["job-1"]
    assert task["verification_status"] == "not_registered"
    assert out["answer_status"] == "partial"


@pytest.mark.parametrize("ids", [None, ["missing"], ["t1", "missing"]])
async def test_missing_or_invalid_board_binding_rejects_batch_before_dispatch(board_dispatch, ids):
    await add_task.func([{"description": "Read sources"}])
    task = {"agent": "researcher", "prompt": "Read sources"}
    if ids is not None:
        task["work_item_ids"] = ids
    reply = await agent_team_assign_task.func(tasks=[task])
    assert reply.startswith("Error"), reply
    assert not board_dispatch.submitted
    assert snapshot_tasks(TASK_ID)[0]["resolution"] == "open"
