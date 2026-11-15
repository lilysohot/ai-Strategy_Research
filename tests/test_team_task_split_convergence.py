"""Parent/segment contract: split before dispatch, converge after segments report."""

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
from plugins.tools.task_board import add_task, clear_board, snapshot_tasks, update_task
from tests.test_agent_team_inherited_publish_directive import TASK_ID, _FakeBus, _session


@pytest.fixture
def team_board():
    bus = _FakeBus({
        f"{TASK_ID}::reader_a": _session("reader_a"),
        f"{TASK_ID}::reader_b": _session("reader_b"),
    })
    bus.list_task_jobs = lambda *_: []
    bus.get_job_result = lambda *_args, **_kwargs: (
        f"{TASK_ID}::reader_a",
        SimpleNamespace(final_content="Source report", metadata={}),
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
        ExecutionScope(task_id=TASK_ID, metadata={SWARM_SCOPE_KEY: runtime})
    )
    yield bus
    clear_board(TASK_ID)
    reset_current_execution_scope(token)
    registry.restore(saved)


def board():
    return {task["id"]: task for task in snapshot_tasks(TASK_ID)}


async def test_segment_work_items_dispatch_in_parallel(team_board):
    await add_task.func([{"description": "精读全文", "done_when": "提取全文关键论断"}])
    await add_task.func([
        {"description": "精读前半", "parent_id": "t1", "done_when": "提取前半论断"},
        {"description": "精读后半", "parent_id": "t1", "done_when": "提取后半论断"},
    ])
    assert board()["t2"]["parent_id"] == "t1"

    reply = await agent_team_assign_task.func(tasks=[
        {"agent": "reader_a", "prompt": "读前半", "work_item_ids": ["t2"]},
        {"agent": "reader_b", "prompt": "读后半", "work_item_ids": ["t3"]},
    ])
    assert not reply.startswith("Error"), reply
    tasks = board()
    assert tasks["t2"]["execution_job_ids"] and tasks["t3"]["execution_job_ids"]
    assert tasks["t1"]["resolution"] == "open"
    assert not tasks["t1"].get("execution_job_ids")


async def test_one_work_item_still_cannot_be_split_by_free_text(team_board):
    await add_task.func([{"description": "精读全文"}])
    reply = await agent_team_assign_task.func(tasks=[
        {"agent": "reader_a", "prompt": "读前半", "work_item_ids": ["t1"]},
        {"agent": "reader_b", "prompt": "读后半", "work_item_ids": ["t1"]},
    ])
    assert reply.startswith("Error"), reply
    assert "cannot be split" in reply


async def test_parent_with_segments_cannot_be_cancelled(team_board):
    await add_task.func([{"description": "精读全文", "done_when": "提取全文关键论断"}])
    await add_task.func([{"description": "精读前半", "parent_id": "t1"}])

    reply = await update_task.func([{"id": "t1", "resolution": "cancelled", "notes": "已拆分"}])
    assert "不能取消" in reply
    assert board()["t1"]["resolution"] == "open"


async def test_parent_cannot_be_dispatched_on_its_own(team_board):
    await add_task.func([{"description": "精读全文"}])
    await add_task.func([{"description": "精读前半", "parent_id": "t1"}])

    reply = await agent_team_assign_task.func(tasks=[
        {"agent": "reader_a", "prompt": "读全文", "work_item_ids": ["t1"]},
    ])
    assert reply.startswith("Error"), reply
    assert "parent work item" in reply
    assert "verification_checks" in reply


async def test_parent_resolution_requires_segment_coverage(team_board):
    await add_task.func([{"description": "精读全文", "done_when": "提取全文关键论断"}])
    await add_task.func([
        {"description": "精读前半", "parent_id": "t1"},
        {"description": "精读后半", "parent_id": "t1"},
    ])
    await update_task.func([{"id": "t2", "resolution": "resolved", "notes": "已提取前半论断"}])

    reply = await update_task.func([{"id": "t1", "resolution": "resolved", "notes": "由 t2 承接"}])
    assert "t3" in reply and "尚未 resolved" in reply
    assert board()["t1"]["resolution"] == "open"

    await update_task.func([{"id": "t3", "resolution": "resolved", "notes": "已提取后半论断"}])
    reply = await update_task.func([
        {"id": "t1", "resolution": "resolved", "notes": "由 t2、t3 的结果承接原始要求"},
    ])
    assert "errors:" not in reply, reply
    assert board()["t1"]["resolution"] == "resolved"


async def test_parent_resolution_needs_a_named_basis(team_board):
    await add_task.func([{"description": "精读全文"}])
    await add_task.func([{"description": "精读前半", "parent_id": "t1"}])
    await update_task.func([{"id": "t2", "resolution": "resolved", "notes": "已提取前半论断"}])

    reply = await update_task.func([{"id": "t1", "resolution": "resolved", "notes": "都读过了"}])
    assert "notes" in reply and board()["t1"]["resolution"] == "open"


async def test_parent_first_batch_resolution_is_order_independent(team_board):
    await add_task.func([{"description": "精读全文", "done_when": "提取全文关键论断"}])
    await add_task.func([{"description": "精读前半", "parent_id": "t1"}])

    reply = await update_task.func([
        {"id": "t1", "resolution": "resolved", "notes": "由 t2 的结果承接原始要求"},
        {"id": "t2", "resolution": "resolved", "notes": "已提取前半论断"},
    ])
    assert "errors:" not in reply, reply
    tasks = board()
    assert tasks["t1"]["resolution"] == "resolved"
    assert tasks["t2"]["resolution"] == "resolved"


async def test_dispatched_segment_freezes_the_parent_definition(team_board):
    await add_task.func([{"description": "精读全文", "done_when": "提取全文关键论断"}])
    await add_task.func([{"description": "精读前半", "parent_id": "t1"}])
    await agent_team_assign_task.func(tasks=[
        {"agent": "reader_a", "prompt": "读前半", "work_item_ids": ["t2"]},
    ])

    reply = await update_task.func([{"id": "t1", "done_when": "说明为什么没有完成精读"}])
    assert "immutable" in reply
    assert board()["t1"]["done_when"] == "提取全文关键论断"


def test_planning_prompt_forbids_implicit_split():
    from workflows.agent_team.prompts import TEAM_MANAGEMENT

    assert "split across — several sub-agents" not in TEAM_MANAGEMENT
    assert "ONE execution contract" in TEAM_MANAGEMENT
    assert "parent_id" in TEAM_MANAGEMENT


def test_assembled_prompts_do_not_reintroduce_the_old_rules():
    from workflows.agent_team.prompts import get_main_system_prompt

    research = get_main_system_prompt(
        "2026-11-14", planning_mode=True, phase="execution", prompt_mode="research"
    )
    assert "For each task-board item, create_subagent" not in research
    assert "spawn a `final_verifier` sub-agent to independently re-derive" not in research
    assert "parent item with segments is a container" in research

    standard = get_main_system_prompt("2026-11-14", prompt_mode="standard")
    assert "Split one goal into segments on the board" in standard
    assert "parent_id" in standard


# --- W2: T1/T2 formal regressions ------------------------------------------------


@pytest.mark.parametrize("parent_first", [True, False])
async def test_parent_child_batch_resolution_is_order_independent(team_board, parent_first):
    """Both input permutations of one batch converge to the same committed state."""
    await add_task.func([{"description": "whole goal", "done_when": "cover all"}])
    await add_task.func([{"description": "segment", "parent_id": "t1"}])
    parent = {"id": "t1", "resolution": "resolved", "notes": "由 t2 的结果承接原始要求"}
    segment = {"id": "t2", "resolution": "resolved", "notes": "已提取前半论断"}
    batch = [parent, segment] if parent_first else [segment, parent]
    reply = await update_task.func(batch)
    assert "errors:" not in reply, reply
    tasks = board()
    assert tasks["t1"]["resolution"] == "resolved"
    assert tasks["t2"]["resolution"] == "resolved"
    assert tasks["t2"]["parent_id"] == "t1"
    assert tasks["t1"]["done_when"] == "cover all"


def committed_projection():
    return {
        task["id"]: (
            task.get("parent_id", ""),
            task["resolution"],
            task.get("done_when", ""),
            task.get("notes", ""),
        )
        for task in snapshot_tasks(TASK_ID)
    }


async def test_both_batch_orders_produce_identical_committed_snapshots():
    """Run both permutations on fresh boards and compare the committed state."""
    from frontier_agent.core.runtime import registry

    parent = {"id": "t1", "resolution": "resolved", "notes": "由 t2 的结果承接原始要求"}
    segment = {"id": "t2", "resolution": "resolved", "notes": "已提取前半论断"}
    states = []
    saved = registry.snapshot()
    try:
        for parent_first in (True, False):
            bus = _FakeBus({f"{TASK_ID}::reader_a": _session("reader_a")})
            bus.list_task_jobs = lambda *_: []
            registry.register(AgentBus, bus)
            runtime = SimpleNamespace(
                publication_state={}, publication_lock=asyncio.Lock(),
                verification_lock=asyncio.Lock(), sub_binds=(), original_question="",
            )
            token = set_current_execution_scope(
                ExecutionScope(task_id=TASK_ID, metadata={SWARM_SCOPE_KEY: runtime})
            )
            try:
                await add_task.func([{"description": "whole goal", "done_when": "cover all"}])
                await add_task.func([{"description": "segment", "parent_id": "t1"}])
                batch = [parent, segment] if parent_first else [segment, parent]
                reply = await update_task.func(batch)
                assert "errors:" not in reply, reply
                states.append(committed_projection())
            finally:
                clear_board(TASK_ID)
                reset_current_execution_scope(token)
        assert len(states[0]) == 2
        assert states[0] == states[1]
    finally:
        registry.restore(saved)


async def test_parent_required_check_is_actually_dispatched_after_segment_executes(team_board):
    """T2: a parent keeps its registered check; dispatch must really enqueue it."""
    await add_task.func([{
        "description": "whole goal", "done_when": "cover all", "verification_required": True,
    }])
    await add_task.func([{"description": "segment", "parent_id": "t1"}])

    child = await agent_team_assign_task.func(tasks=[{
        "agent": "reader_a", "prompt": "read", "work_item_ids": ["t2"],
    }])
    assert not child.startswith("Error"), child
    assert "Submitted" in child
    assert board()["t2"]["execution_job_ids"]

    dispatch = await agent_team_assign_task.func(tasks=[{
        "agent": "reader_b", "prompt": "check", "work_item_ids": ["t1"],
        "verification_checks": [{
            "check_id": "t1.required", "subject": {"text": "claim"},
            "evidence": [{"job_id": "source"}],
        }],
    }])
    assert not dispatch.startswith("Error"), dispatch
    assert "Submitted" in dispatch, "the parent check must be really enqueued"
    tasks = board()
    assert tasks["t1"]["execution_job_ids"]
    assert tasks["t1"]["done_when"] == "cover all"
    assert [c["check_id"] for c in tasks["t1"]["verification_requirements"]] == ["t1.required"]

    reply = await update_task.func([{
        "id": "t1", "kind": "research",
        "verification_requirements": [{"check_id": "weaker", "criterion": "weaker check"}],
        "done_when": "explain why not done",
    }])
    assert "immutable" in reply
    assert [c["check_id"] for c in board()["t1"]["verification_requirements"]] == ["t1.required"]


async def test_dispatch_dedup_blocks_unchanged_failure_but_allows_a_valid_fix(
    team_board, monkeypatch,
):
    """Constraint 4: only an identical, deterministic failure is suppressed."""
    from plugins.tools.assign_task import agent_team_assign_task

    await add_task.func([{"description": "Check a claim"}])
    attempts: list[int] = []

    async def deterministic_failure(*args, **kwargs):
        attempts.append(1)
        raise ValueError("bound evidence packet has 272 records (limit 160)")

    monkeypatch.setattr(
        team_board, "submit_task_to_session", deterministic_failure, raising=False,
    )
    payload = {"tasks": [{
        "agent": "reader_a", "prompt": "check", "work_item_ids": ["t1"],
    }]}
    first = await agent_team_assign_task.func(**payload)
    assert "bound evidence packet has" in first
    second = await agent_team_assign_task.func(**payload)
    assert "identical request already failed" in second
    assert len(attempts) == 1, "an unchanged deterministic failure must not re-execute"
    fixed = await agent_team_assign_task.func(tasks=[{
        "agent": "reader_a", "prompt": "check with selected refs", "work_item_ids": ["t1"],
    }])
    assert "identical request already failed" not in fixed
    assert len(attempts) == 2, "a changed request must be allowed to re-validate"
