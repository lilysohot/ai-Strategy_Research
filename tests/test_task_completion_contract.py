"""Completion is judged against the user's requirement, not every board row.

A live team run added an optional external-background task, was refused the
``required_for_completion=False`` field at ``add_task``, then could not say
``cancelled`` at delivery, so it declared the item ``blocked`` — and a complete,
fully verified answer was published with a "partial" banner.
"""

import json
from pathlib import Path

import pytest

from plugins.tools.task_board import (
    add_task,
    bind_assignment,
    clear_board,
    drain_board_ops,
    render_board,
    restore_board_from_messages,
    snapshot_tasks,
    update_task,
)
from tests.test_agent_team_verification import add_job
from tests.test_team_atomic_delivery import delivery_run as _delivery_run
from tests.test_team_atomic_delivery import prepare
from workflows.agent_team.delivery import deliver_answer
from workflows.agent_team.final_report import finalize_team_report

delivery_run = _delivery_run


def contract(answer: str, status: str = "complete") -> dict:
    return finalize_team_report(
        answer,
        source="agent",
        answer_status=status,
        stopped_by="final_answer",
        tasks=snapshot_tasks("run"),
    )


async def test_optional_work_can_be_declared_at_add_task(delivery_run):
    await add_task.func(
        [
            {"description": "Explain the report"},
            {"description": "Cross-check external background", "required_for_completion": False},
        ]
    )
    tasks = {task["id"]: task for task in snapshot_tasks("run")}
    assert "required_for_completion" not in tasks["t1"]
    assert tasks["t2"]["required_for_completion"] is False
    board = render_board("run")
    assert "[optional]" in next(line for line in board.splitlines() if "t2" in line)


async def test_optional_flag_frozen_after_dispatch(delivery_run):
    await add_task.func([{"description": "Explain the report"}])
    await update_task.func([{"id": "t1", "required_for_completion": False}])
    assert snapshot_tasks("run")[0]["required_for_completion"] is False

    await add_task.func([{"description": "Second item"}])
    bind_assignment("run", ["t2"], "worker", "job-x")
    drain_board_ops("run")
    receipt = await update_task.func([{"id": "t2", "required_for_completion": False}])
    assert "派发前" in receipt
    assert snapshot_tasks("run")[1].get("required_for_completion") is not False


async def test_optional_gap_is_recorded_without_downgrading_the_answer(delivery_run):
    content = "The report plans 143 launches on the stated assumptions."
    await add_task.func(
        [
            {"description": "Interpret the report"},
            {
                "description": "Compare with public external coverage",
                "required_for_completion": False,
            },
        ]
    )
    await deliver_answer.func(
        content=content,
        updates=[
            {"id": "t1", "resolution": "resolved", "notes": "Interpretation delivered"},
            {
                "id": "t2",
                "resolution": "blocked",
                "notes": "Optional external check not performed",
                "gap": "No public sources were read for the optional comparison",
            },
        ],
    )
    result = contract(content)
    assert result["answer_status"] == "complete"
    assert result["report_contract"]["kind"] == "complete"
    assert result["report_contract"]["gaps"] == []
    optional = result["report_contract"]["optional_work"]
    assert [item["task_id"] for item in optional] == ["t2"]
    # Recorded, visible and non-blocking.
    assert "Compare with public external coverage" in result["final_answer"]
    assert "No public sources were read" in result["final_answer"]
    assert "Partial result" not in result["final_answer"]


async def test_required_gap_still_makes_the_answer_partial(delivery_run):
    content = "The report plans 143 launches on the stated assumptions."
    await add_task.func([{"description": "Interpret the report"}])
    await deliver_answer.func(
        content=content,
        updates=[
            {
                "id": "t1",
                "resolution": "blocked",
                "notes": "Only part of the report was readable",
                "gap": "Pages 7-9 were not extracted",
            }
        ],
    )
    result = contract(content)
    assert result["answer_status"] == "partial"
    assert "task_evidence_gap" in [gap["code"] for gap in result["report_contract"]["gaps"]]


async def test_delivery_accepts_cancelled_without_turning_it_into_a_gap(delivery_run):
    content = "The interpretation covers every requested dimension."
    await add_task.func(
        [
            {"description": "Interpret the report"},
            {"description": "Optional external context", "required_for_completion": False},
        ]
    )
    await deliver_answer.func(
        content=content,
        updates=[
            {"id": "t1", "resolution": "resolved", "notes": "Delivered"},
            {"id": "t2", "resolution": "cancelled", "notes": "Optional, not pursued"},
        ],
    )
    tasks = {task["id"]: task for task in snapshot_tasks("run")}
    assert tasks["t2"]["resolution"] == "cancelled"
    assert contract(content)["answer_status"] == "complete"


async def test_cancelled_cannot_carry_a_blocking_gap(delivery_run):
    await add_task.func([{"description": "Interpret the report"}])
    with pytest.raises(ValueError, match="cancelled"):
        await deliver_answer.func(
            content="The interpretation is incomplete.",
            updates=[
                {
                    "id": "t1",
                    "resolution": "cancelled",
                    "notes": "Stopped",
                    "gap": "The report body was never read",
                }
            ],
        )


async def test_required_item_cannot_be_cancelled_to_hide_an_incomplete_dispatch(delivery_run):
    bus, _ = delivery_run
    await prepare(bus)
    bus._jobs["j1"].result.metadata["stopped_by"] = "wall_deadline"
    with pytest.raises(ValueError, match="member work incomplete"):
        await deliver_answer.func(
            content="The amount is 50.",
            updates=[{"id": "t1", "resolution": "cancelled", "notes": "Withdrawn"}],
        )


async def test_optional_item_may_be_cancelled_after_a_failed_dispatch(delivery_run):
    bus, _ = delivery_run
    await add_task.func(
        [{"description": "Optional external context", "required_for_completion": False}]
    )
    add_job(bus, "j2", [])
    bind_assignment("run", ["t1"], "worker", "j2")
    bus._jobs["j2"].result.metadata["stopped_by"] = "wall_deadline"

    await deliver_answer.func(
        content="The interpretation is complete.",
        updates=[{"id": "t1", "resolution": "cancelled", "notes": "Optional, abandoned"}],
    )
    assert contract("The interpretation is complete.")["answer_status"] == "complete"


async def test_delivery_cannot_relabel_required_work_as_optional(delivery_run):
    await add_task.func([{"description": "Interpret the report"}])
    with pytest.raises(ValueError, match="required_for_completion"):
        await deliver_answer.func(
            content="The interpretation is complete.",
            updates=[
                {
                    "id": "t1",
                    "resolution": "resolved",
                    "notes": "Delivered",
                    "required_for_completion": False,
                }
            ],
        )


@pytest.mark.parametrize("cancel_before_delivery", [False, True])
async def test_required_undispatched_cancellation_cannot_bypass_delivery(
    delivery_run, cancel_before_delivery,
):
    await add_task.func([{"description": "Interpret the report"}])
    cancelled = {"id": "t1", "resolution": "cancelled", "notes": "Report was never read"}
    if cancel_before_delivery:
        await update_task.func([cancelled])
    with pytest.raises(ValueError, match="required_task_cancelled"):
        await deliver_answer.func(
            content="Interpretation not performed.",
            updates=[] if cancel_before_delivery else [cancelled],
        )
    expected = "cancelled" if cancel_before_delivery else "open"
    assert snapshot_tasks("run")[0]["resolution"] == expected

    # A forced/recovery finalization must not upgrade the same board to complete.
    await update_task.func([cancelled])
    assert contract("Interpretation not performed.")["answer_status"] == "partial"

    # The correction can still deliver an honest partial result in one call.
    await deliver_answer.func(content="Interpretation not performed.", updates=[{
        "id": "t1", "resolution": "blocked", "notes": "Report was never read",
        "gap": "Report interpretation remains outstanding",
    }])
    assert contract("Interpretation not performed.")["answer_status"] == "partial"


def replay_call(call_id, name, args, receipt):
    return [
        {"role": "assistant", "tool_calls": [{
            "id": call_id, "function": {"name": name, "arguments": json.dumps(args)},
        }]},
        {"role": "tool", "tool_call_id": call_id, "content": receipt},
    ]


@pytest.mark.parametrize("declaration", ["initial", "duplicate", "update"])
async def test_optional_declaration_survives_replay(delivery_run, declaration):
    task = {"description": "Optional external context"}
    if declaration == "initial":
        task["required_for_completion"] = False
    receipt = await add_task.func([task])
    messages = replay_call("a", "add_task", {"tasks": [task]}, receipt)
    if declaration == "duplicate":
        task = {**task, "required_for_completion": False}
        receipt = await add_task.func([task])
        messages += replay_call("b", "add_task", {"tasks": [task]}, receipt)
    elif declaration == "update":
        update = {"id": "t1", "required_for_completion": False}
        receipt = await update_task.func([update])
        messages += replay_call("b", "update_task", {"updates": [update]}, receipt)
    before = snapshot_tasks("run")
    try:
        restore_board_from_messages("replayed", messages)
        assert snapshot_tasks("replayed") == before
    finally:
        clear_board("replayed")


@pytest.mark.parametrize("rejection", ["dispatched", "terminal", "progress_only"])
async def test_replay_does_not_accept_rejected_optional_flag(delivery_run, rejection):
    task = {"description": "Interpret report"}
    if rejection == "progress_only":
        task["verification_required"] = True
    receipt = await add_task.func([task])
    messages = replay_call("a", "add_task", {"tasks": [task]}, receipt)
    if rejection == "dispatched":
        bind_assignment("run", ["t1"], "worker", "job-x")
    elif rejection == "terminal":
        update = {"id": "t1", "resolution": "resolved", "notes": "Delivered"}
        receipt = await update_task.func([update])
        messages += replay_call("b", "update_task", {"updates": [update]}, receipt)
    update = {"id": "t1", "required_for_completion": False}
    if rejection == "progress_only":
        update.update(resolution="resolved", notes="Attempted without verification")
    receipt = await update_task.func([update])
    assert snapshot_tasks("run")[0].get("required_for_completion", True) is True
    messages += replay_call("c", "update_task", {"updates": [update]}, receipt)
    try:
        restore_board_from_messages("replayed", messages)
        assert snapshot_tasks("replayed")[0].get("required_for_completion", True) is True
    finally:
        clear_board("replayed")

def _real_run() -> dict:
    path = Path(__file__).parent / "fixtures" / "optional_work_board.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_replay_of_the_live_case_is_complete_once_the_item_is_optional():
    """The recorded board of the run that published a complete answer as partial."""
    run = _real_run()
    board = [dict(task) for task in run["task_board"]]
    optional = next(task for task in board if task["resolution"] == "blocked")
    # The interface now accepts the declaration the coordinator attempted and was
    # refused, so the same item no longer gates the requested result.
    optional["required_for_completion"] = False

    # The checked passages must still be in the published body verbatim.
    body = "\n".join(check["subject"]["text"] for check in run["verification_checks"])
    result = finalize_team_report(
        body,
        source="agent",
        answer_status="complete",
        stopped_by="final_answer",
        wind_down={
            "status": "complete",
            "run_status": "complete",
            **run["wind_down"],
            "job_outcomes": run["job_outcomes"],
        },
        tasks=board,
    )
    assert result["answer_status"] == "complete"
    assert result["report_contract"]["gaps"] == []
    # The undone optional work is still on the record.
    assert optional["id"] in [
        item["task_id"] for item in result["report_contract"]["optional_work"]
    ]
