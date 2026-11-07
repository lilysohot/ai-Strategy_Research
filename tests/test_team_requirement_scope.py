"""Completion depends on required outcomes; optional boundaries remain auditable."""

import pytest

from plugins.tools.task_board import add_task, snapshot_tasks
from tests.test_team_atomic_delivery import delivery_run as _delivery_run
from tests.test_team_atomic_delivery import prepare, turn_context
from workflows.agent_team.delivery import TeamDeliveryObserver, deliver_answer
from workflows.agent_team.final_report import finalize_team_report

delivery_run = _delivery_run


@pytest.mark.parametrize(
    "user_goal,answer,limitation",
    [
        (
            "Translate the supplied sentence",
            "The meeting starts at nine.",
            "No stylistic variants requested.",
        ),
        (
            "Compute the supplied invoice total",
            "The total is 50.",
            "No market-price comparison performed.",
        ),
        (
            "Give one feasible route",
            "Take route A within the stated budget.",
            "Other routes were not exhaustively ranked.",
        ),
    ],
)
async def test_nonblocking_boundaries_survive_delivery_without_partial_status(
    delivery_run, user_goal, answer, limitation
):
    await add_task.func([{"description": user_goal, "done_when": user_goal}])
    await deliver_answer.func(
        content=answer,
        updates=[
            {
                "id": "t1",
                "resolution": "resolved",
                "notes": "Requested outcome supported",
                "limitations": limitation,
            }
        ],
    )
    tasks = snapshot_tasks("run")
    assert tasks[0]["limitations"] == limitation
    result = finalize_team_report(
        answer, source="agent", answer_status="complete", stopped_by="final_answer", tasks=tasks
    )
    assert result["answer_status"] == "complete"
    assert result["final_answer"] == answer
    assert result["report_contract"]["task_board"][0]["limitations"] == limitation


async def test_resolved_with_blocking_gap_rejected_atomically(delivery_run):
    await add_task.func([{"description": "Compare the two prices"}])
    before = snapshot_tasks("run")
    with pytest.raises(ValueError, match="gap"):
        await deliver_answer.func(
            content="A is cheaper.",
            updates=[
                {
                    "id": "t1",
                    "resolution": "resolved",
                    "notes": "Only A known",
                    "gap": "Required price of B missing",
                }
            ],
        )
    assert snapshot_tasks("run") == before


@pytest.mark.parametrize("verdict", ["fail", "unchecked"])
async def test_limitations_cannot_waive_required_verification(delivery_run, verdict):
    bus, _ = delivery_run
    await prepare(bus, verdict)
    before = snapshot_tasks("run")
    with pytest.raises(ValueError):
        await deliver_answer.func(
            content="The amount is 50.",
            updates=[
                {
                    "id": "t1",
                    "resolution": "resolved",
                    "notes": "Ready",
                    "limitations": "Required arithmetic review did not pass",
                }
            ],
        )
    assert snapshot_tasks("run") == before


async def test_required_missing_evidence_stays_partial_with_optional_boundary(delivery_run):
    bus, _ = delivery_run
    await prepare(bus, "unchecked")
    await deliver_answer.func(
        content="The amount cannot yet be confirmed.",
        updates=[
            {
                "id": "t1",
                "resolution": "blocked",
                "notes": "Evidence unavailable",
                "gap": "Required arithmetic evidence missing",
                "limitations": "No optional sensitivity scenarios computed",
            }
        ],
    )
    result = finalize_team_report(
        "The amount cannot yet be confirmed.",
        source="agent",
        answer_status="complete",
        stopped_by="final_answer",
        tasks=snapshot_tasks("run"),
    )
    assert result["answer_status"] == "partial"
    assert any(g["code"] == "task_evidence_gap" for g in result["report_contract"]["gaps"])


async def test_runtime_required_review_keeps_coordination_open(delivery_run, monkeypatch):
    from plugins.tools.task_board import force_finish_planning, start_planning

    bus, budget = delivery_run
    await prepare(bus)
    session = await bus.create_session(
        task_id="run",
        name="reader",
        role_id="researcher",
        system_prompt="Read",
        tools_override=[],
        llm_override=object(),
    )
    bus.get_session(session).total_task_count = 1
    start_planning("run")
    force_finish_planning("run")
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 100)
    observer = TeamDeliveryObserver(budget)
    intervention = await observer.on_before_llm(turn_context())
    assert not observer.active, "Do not close dispatch while runtime-required review is missing"
    assert intervention is None or not intervention.allowed_tool_names

    verifier = await bus.create_session(
        task_id="run",
        name="final_verifier",
        role_id="researcher",
        system_prompt="Review",
        tools_override=[],
        llm_override=object(),
    )
    bus.get_session(verifier).total_task_count = 1
    ready = await observer.on_before_llm(turn_context())
    assert observer.active and ready.allowed_tool_names == ("deliver_answer",)
