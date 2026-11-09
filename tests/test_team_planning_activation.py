"""A phase transition must not opt a run into additional completion obligations."""

import pytest

from plugins.tools.finalize_answer import finalize_gate, planning_requirement_error
from plugins.tools.task_board import (
    add_task,
    drain_board_ops,
    finish_planning,
    in_planning,
    planning_enabled,
    start_planning,
    update_task,
)
from tests.test_team_atomic_delivery import delivery_run as _delivery_run
from tests.test_team_atomic_delivery import turn_context
from workflows.agent_team.observers.bare_text_finalize import BareTextFinalizeObserver

delivery_run = _delivery_run


@pytest.mark.parametrize("with_task", [False, True])
async def test_finish_does_not_enable_planning_or_block_supported_answer(delivery_run, with_task):
    assert not planning_enabled("run")
    if with_task:
        await add_task.func([{"description": "Answer from supplied evidence"}])
    drain_board_ops("run")
    await finish_planning.func()
    assert not planning_enabled("run")
    assert not drain_board_ops("run"), "An inactive phase cannot produce a transition event"
    if with_task:
        assert "unresolved" in finalize_gate("run", "Supported answer")
        await update_task.func([{"id": "t1", "resolution": "resolved", "notes": "Supported"}])
    ctx = turn_context()
    ctx.ai_text = "Supported answer"
    intervention = await BareTextFinalizeObserver().on_llm_response(ctx)
    assert intervention.stop_reason == "final_answer"
    assert ctx.metadata["final_answer"] == "Supported answer"


async def test_explicit_planning_keeps_required_delegation_and_review(delivery_run):
    bus, _ = delivery_run
    start_planning("run")
    await finish_planning.func()
    assert in_planning("run"), "The empty-board guard still applies in planning mode"
    await add_task.func([{"description": "Answer from supplied evidence"}])
    await finish_planning.func()
    assert planning_enabled("run") and not in_planning("run")
    await update_task.func([{"id": "t1", "resolution": "resolved", "notes": "Supported"}])
    assert "no sub-agent" in finalize_gate("run", "Supported answer")
    session_id = await bus.create_session(
        task_id="run", name="reader", role_id="researcher", system_prompt="Read",
        tools_override=[], llm_override=object(),
    )
    bus.get_session(session_id).total_task_count = 1
    assert "independent review" in planning_requirement_error("run", "run")
