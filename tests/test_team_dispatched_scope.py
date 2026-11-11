"""Dispatch freezes acceptance criteria, not progress or legitimate gap repair."""

import asyncio
from types import SimpleNamespace

import pytest

from plugins.tools.task_board import add_task, bind_assignment, snapshot_tasks, update_task
from tests.test_agent_team_inherited_publish_directive import TASK_ID
from tests.test_team_assignment_board_binding import board_dispatch as _board_dispatch
from tests.test_team_atomic_delivery import delivery_run as _delivery_run

delivery_run = _delivery_run
board_dispatch = _board_dispatch


@pytest.fixture
def budgeted_dispatch():
    """Board dispatch with a declared research-job cap in the execution scope."""
    from frontier_agent.components.agent_bus import AgentBus
    from frontier_agent.core.execution_context import (
        ExecutionScope,
        reset_current_execution_scope,
        set_current_execution_scope,
    )
    from frontier_agent.core.runtime import registry
    from plugins.tools._bus_scope import SWARM_SCOPE_KEY
    from plugins.tools.task_board import clear_board
    from tests.test_agent_team_inherited_publish_directive import _FakeBus, _session

    bus = _FakeBus({f"{TASK_ID}::researcher": _session("researcher")})
    jobs: list[SimpleNamespace] = []
    bus.list_task_jobs = lambda *_: jobs
    bus.get_job_result = lambda *_args, **_kwargs: (
        f"{TASK_ID}::researcher",
        SimpleNamespace(final_content="Revenue was 162.9", metadata={}),
    )
    runtime = SimpleNamespace(
        publication_state={},
        publication_lock=asyncio.Lock(),
        verification_lock=asyncio.Lock(),
        sub_binds=(),
        original_question="",
    )
    saved = registry.snapshot()
    registry.register(AgentBus, bus)
    token = set_current_execution_scope(
        ExecutionScope(
            task_id=TASK_ID,
            metadata={SWARM_SCOPE_KEY: runtime, "research_job_budget": 1},
        )
    )
    yield bus, jobs
    clear_board(TASK_ID)
    reset_current_execution_scope(token)
    registry.restore(saved)


async def test_research_dispatch_budget_rejects_batch_before_dispatch(budgeted_dispatch):
    """A declared research-job cap is enforced at dispatch time, fail-closed.

    The budget arrives as an operational cap in the execution scope, never as
    model-visible acceptance criteria. Exceeding it must reject the whole batch
    before anything is submitted, instead of failing the run after the fact.
    """
    from plugins.tools.assign_task import agent_team_assign_task

    bus, _jobs = budgeted_dispatch
    await add_task.func(
        [
            {"description": "First segment", "kind": "research"},
            {"description": "Second segment", "kind": "research"},
        ]
    )
    reply = await agent_team_assign_task.func(
        tasks=[
            {"agent": "researcher", "prompt": "Read the first segment", "work_item_ids": ["t1"]},
            {"agent": "researcher", "prompt": "Read the second segment", "work_item_ids": ["t2"]},
        ]
    )
    assert reply.startswith("Error"), reply
    assert "budget" in reply
    assert not bus.submitted


async def test_accepted_research_jobs_consume_budget_but_checks_do_not(budgeted_dispatch):
    """Already-accepted research jobs count toward the cap; verification checks
    (and rechecks) are checks, not research, and never consume the quota."""
    from plugins.tools.assign_task import agent_team_assign_task

    bus, jobs = budgeted_dispatch
    await add_task.func([{"description": "Read a document", "kind": "research"}])
    await update_task.func(
        updates=[
            {
                "id": "t1",
                "verification_requirements": [
                    {"check_id": "numbers", "criterion": "Each number matches the source text"}
                ],
            }
        ]
    )
    jobs.append(
        SimpleNamespace(
            job_id="job-0", status="completed", result=None, item=SimpleNamespace(metadata={})
        )
    )
    reply = await agent_team_assign_task.func(
        tasks=[{"agent": "researcher", "prompt": "Read again", "work_item_ids": ["t1"]}]
    )
    assert reply.startswith("Error"), reply
    assert not bus.submitted

    reply = await agent_team_assign_task.func(
        tasks=[
            {
                "agent": "researcher",
                "prompt": "Check the reported numbers",
                "work_item_ids": ["t1"],
                "verification_checks": [
                    {
                        "check_id": "numbers",
                        "work_item_id": "t1",
                        "criterion": "Each number matches the source text",
                        "subject": {"text": "Revenue was 162.9"},
                        "evidence": [{"job_id": "job-0"}],
                    }
                ],
            }
        ]
    )
    assert not reply.startswith("Error"), reply


@pytest.mark.parametrize("replacement", ["Read every available item", "Accept a preview", ""])
@pytest.mark.parametrize("via_add", [False, True])
async def test_dispatched_criterion_cannot_be_expanded_weakened_or_cleared(
    delivery_run,
    replacement,
    via_add,
):
    await add_task.func(
        [{"description": "Answer requested question", "done_when": "Support the answer"}]
    )
    bind_assignment("run", ["t1"], "reader", "job-1")
    before = snapshot_tasks("run")
    if via_add:
        result = await add_task.func(
            [
                {
                    "description": "Answer requested question",
                    "done_when": replacement,
                }
            ]
        )
    else:
        result = await update_task.func(
            updates=[
                {
                    "id": "t1",
                    "done_when": replacement,
                    "notes": "also must not be applied",
                }
            ]
        )
    assert "dispatched done_when is immutable" in result
    assert snapshot_tasks("run") == before


async def test_plan_can_change_before_dispatch_and_progress_can_change_after(delivery_run):
    await add_task.func([{"description": "Answer question", "done_when": "Initial draft"}])
    await update_task.func(updates=[{"id": "t1", "done_when": "Required outcome"}])
    bind_assignment("run", ["t1"], "reader", "job-1")
    result = await update_task.func(
        updates=[
            {
                "id": "t1",
                "done_when": "Required outcome",
                "notes": "One fact found",
                "gap": "Second required fact missing",
                "limitations": "Optional comparison omitted",
            }
        ]
    )
    assert "Updated" in result
    task = snapshot_tasks("run")[0]
    assert task["done_when"] == "Required outcome"
    assert task["gap"] == "Second required fact missing"
    assert task["resolution"] == "in_progress"


async def test_parallel_research_assignments_cannot_share_one_work_item(board_dispatch):
    from plugins.tools.assign_task import agent_team_assign_task

    await add_task.func([{"description": "Read a long document", "kind": "research"}])
    reply = await agent_team_assign_task.func(
        tasks=[
            {"agent": "researcher", "prompt": "Read units 0-99", "work_item_ids": ["t1"]},
            {"agent": "researcher", "prompt": "Read units 100-199", "work_item_ids": ["t1"]},
        ]
    )
    assert reply.startswith("Error"), reply
    assert "cannot be split across assignments" in reply
    assert not board_dispatch.submitted


async def test_distinct_work_items_may_be_dispatched_together(board_dispatch):
    from plugins.tools.assign_task import agent_team_assign_task

    await add_task.func(
        [
            {"description": "Read the first segment", "kind": "research"},
            {"description": "Read the second segment", "kind": "research"},
        ]
    )
    reply = await agent_team_assign_task.func(
        tasks=[
            {"agent": "researcher", "prompt": "Read the first segment", "work_item_ids": ["t1"]},
            {"agent": "researcher", "prompt": "Read the second segment", "work_item_ids": ["t2"]},
        ]
    )
    assert not reply.startswith("Error"), reply


async def test_planned_check_may_share_a_research_item(board_dispatch):
    from plugins.tools.assign_task import agent_team_assign_task

    await add_task.func([{"description": "Read a document", "kind": "research"}])
    reply = await agent_team_assign_task.func(
        tasks=[
            {"agent": "researcher", "prompt": "Read the document", "work_item_ids": ["t1"]},
            {
                "agent": "researcher",
                "prompt": "Check the reported numbers",
                "verification_checks": [
                    {
                        "check_id": "numbers",
                        "work_item_id": "t1",
                        "criterion": "Each number matches the source text",
                        "subject": {"text": "Revenue was 162.9"},
                        "evidence": [{"job_id": "job-1"}],
                    }
                ],
            },
        ]
    )
    assert not reply.startswith("Error"), reply


async def test_unit_range_is_validated_and_reaches_job_metadata(board_dispatch):
    """c010c5e1: the 0-99/100-199/200-298 split lived only in board notes and
    every member read the whole document. The dispatched range must survive
    into job metadata so corpus_fetch can enforce it mechanically."""
    from plugins.tools.assign_task import agent_team_assign_task

    await add_task.func(
        [
            {"description": "Read the first segment", "kind": "research"},
            {"description": "Read the second segment", "kind": "research"},
        ]
    )
    reply = await agent_team_assign_task.func(
        tasks=[
            {
                "agent": "researcher",
                "prompt": "Read the first segment",
                "work_item_ids": ["t1"],
                "unit_range": [1, 99],
            },
            {
                "agent": "researcher",
                "prompt": "Read the second segment",
                "work_item_ids": ["t2"],
                "unit_range": [100, 199],
            },
        ]
    )
    assert not reply.startswith("Error"), reply
    assert board_dispatch.submitted[0][2]["unit_range"] == [1, 99]
    assert board_dispatch.submitted[1][2]["unit_range"] == [100, 199]


def test_unit_range_must_be_a_wellformed_inclusive_span():
    import pytest
    from pydantic import ValidationError

    from plugins.tools.assign_task import AgentTeamAssignmentSpec

    with pytest.raises(ValidationError):
        AgentTeamAssignmentSpec(agent="a", prompt="p", unit_range=[199, 100])
    with pytest.raises(ValidationError):
        AgentTeamAssignmentSpec(agent="a", prompt="p", unit_range=[0, 99])
    spec = AgentTeamAssignmentSpec(agent="a", prompt="p", unit_range=[100, 199])
    assert spec.unit_range == [100, 199]


async def test_publish_handoff_promise_without_output_paths_is_flagged(board_dispatch):
    """c010c5e1: board notes promised publish_handoff but the assignments
    carried no output_paths, so every extract agent's /outputs was read-only
    and the handoffs never landed (scratch/handoffs empty). The dispatch reply
    must flag the mismatch instead of silently promising an impossible write."""
    from plugins.tools.assign_task import agent_team_assign_task

    await add_task.func(
        [
            {
                "description": "Extract the document segment",
                "kind": "research",
                "notes": "逐单元抽取并 publish_handoff 原文抽取件",
            }
        ]
    )
    reply = await agent_team_assign_task.func(
        tasks=[
            {
                "agent": "researcher",
                "prompt": "Read the segment",
                "work_item_ids": ["t1"],
            }
        ]
    )
    assert not reply.startswith("Error"), reply
    assert "publish_handoff" in reply and "output_paths" in reply

    await add_task.func([{"description": "Plain research", "kind": "research"}])
    plain = await agent_team_assign_task.func(
        tasks=[
            {
                "agent": "researcher",
                "prompt": "Read the source",
                "work_item_ids": ["t2"],
            }
        ]
    )
    assert not plain.startswith("Error"), plain
    assert "publish_handoff" not in plain


async def test_job_keeps_dispatch_contract_when_board_progress_changes(board_dispatch):
    from plugins.tools.assign_task import agent_team_assign_task

    await add_task.func(
        [
            {
                "description": "Gather the requested observations",
                "kind": "research",
                "done_when": "Support both requested observations",
            }
        ]
    )
    reply = await agent_team_assign_task.func(
        tasks=[
            {
                "agent": "researcher",
                "prompt": "Read the source",
                "work_item_ids": ["t1"],
            }
        ]
    )
    assert not reply.startswith("Error"), reply
    metadata = board_dispatch.submitted[0][2]
    contract = metadata["work_item_contracts"][0]
    assert contract == {
        "id": "t1",
        "description": "Gather the requested observations",
        "done_when": "Support both requested observations",
        "verification_requirements": [],
    }
    assert "original_question" in metadata
    await update_task.func(updates=[{"id": "t1", "gap": "One observation still missing"}])
    assert snapshot_tasks(TASK_ID)[0]["gap"]
    assert "gap" not in contract
