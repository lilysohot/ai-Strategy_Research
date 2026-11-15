"""Replay restores the contract the runtime actually committed, not the last delta."""

import json

import pytest

from plugins.tools.task_board import (
    add_task,
    clear_board,
    restore_board_from_messages,
    snapshot_tasks,
)
from tests.test_team_atomic_delivery import delivery_run as _delivery_run
from workflows.agent_team.delivery import deliver_answer

delivery_run = _delivery_run
ACCEPTED = "Final answer and task dispositions accepted."


def call(call_id, name, payload):
    return {
        "role": "assistant",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(payload)},
            }
        ],
    }


def receipt(call_id, content):
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def test_replay_restores_parent_links_and_merged_delivery_dispositions():
    messages = [
        call("add1", "add_task", {"tasks": [
            {"description": "whole goal", "done_when": "cover the whole goal"},
            {"description": "first segment", "parent_id": "t1"},
        ]}),
        receipt("add1", "Added ['t1', 't2']."),
        # First delivery is rejected but becomes a repairable candidate.
        call("d1", "deliver_answer", {
            "content": "answer body",
            "updates": [
                {"id": "t1", "resolution": "resolved", "notes": "t2 covers the goal"},
                {"id": "t2", "resolution": "cancelled", "notes": "retry"},
            ],
        }),
        receipt("d1", "Delivery preflight failed (candidate v1 stored; nothing committed)"),
        # Accepted retry submits only the changed disposition and no body.
        call("d2", "deliver_answer", {
            "base_version": 1,
            "updates": [{"id": "t2", "resolution": "resolved", "notes": "done"}],
        }),
        receipt("d2", "Final answer and task dispositions accepted."),
    ]
    try:
        assert restore_board_from_messages("restore-run", messages) == 2
        tasks = {task["id"]: task for task in snapshot_tasks("restore-run")}
        assert tasks["t2"]["parent_id"] == "t1"
        assert tasks["t1"]["resolution"] == "resolved"
        assert tasks["t2"]["resolution"] == "resolved"
        assert tasks["t2"]["notes"] == "done"
    finally:
        clear_board("restore-run")


def test_replay_ignores_a_failed_delivery_that_kept_no_candidate():
    messages = [
        call("add1", "add_task", {"tasks": [{"description": "plain"}]}),
        receipt("add1", "Added ['t1']."),
        call("d1", "deliver_answer", {
            "content": "answer",
            "updates": [{"id": "t1", "resolution": "resolved", "notes": "done"}],
        }),
        receipt("d1", "No recoverable delivery candidate at version 3."),
    ]
    try:
        assert restore_board_from_messages("restore-run", messages) == 1
        assert snapshot_tasks("restore-run")[0]["resolution"] == "open"
    finally:
        clear_board("restore-run")


# --- W2: T4 runtime/replay equivalence ------------------------------------------


def projection(task_id):
    """The user-visible state both paths must agree on after an accepted repair."""
    return {
        task["id"]: (
            task.get("parent_id", ""),
            task["resolution"],
            task.get("notes", ""),
            task.get("done_when", ""),
            tuple(c["check_id"] for c in task.get("verification_requirements", [])),
        )
        for task in snapshot_tasks(task_id)
    }


async def test_runtime_and_replay_snapshots_match_after_incremental_repair(delivery_run):
    """Run a real failed submission + accepted field retry, then replay its calls."""
    add_payload = [
        {"description": "whole goal", "done_when": "cover all"},
        {"description": "segment", "parent_id": "t1"},
    ]
    add_receipt = await add_task.func(add_payload)
    body = "The requested interpretation is complete."
    first_payload = {
        "content": body,
        "updates": [
            {"id": "t1", "resolution": "resolved", "notes": "t2 covers the goal"},
            {"id": "t2", "resolution": "cancelled", "notes": "retry"},
        ],
    }
    with pytest.raises(ValueError) as first:
        await deliver_answer.func(**first_payload)
    failed_receipt = str(first.value)
    assert "candidate v1" in failed_receipt
    retry_payload = {
        "base_version": 1,
        "updates": [{"id": "t2", "resolution": "resolved", "notes": "done"}],
    }
    accepted = await deliver_answer.func(**retry_payload)
    assert accepted == ACCEPTED
    runtime_state = projection("run")

    messages = [
        call("add1", "add_task", {"tasks": add_payload}),
        receipt("add1", add_receipt),
        call("d1", "deliver_answer", first_payload),
        receipt("d1", failed_receipt),
        call("d2", "deliver_answer", retry_payload),
        receipt("d2", accepted),
    ]
    try:
        assert restore_board_from_messages("restore-run", messages) == 2
        assert projection("restore-run") == runtime_state
    finally:
        clear_board("restore-run")
