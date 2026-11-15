"""Admission prices verification work; a denied check stays an honest gap."""

import pytest

from frontier_agent.components.agent_bus import AgentBus
from frontier_agent.core.execution_context import (
    ExecutionScope,
    reset_current_execution_scope,
    set_current_execution_scope,
)
from frontier_agent.core.loop_types import AgentLoopResult
from frontier_agent.core.runtime import registry
from plugins.tools._bus_scope import SWARM_SCOPE_KEY
from plugins.tools._verification import (
    packet_record_count,
    verification_cost_estimate,
)
from plugins.tools.assign_task import agent_team_assign_task
from plugins.tools.task_board import (
    add_task,
    clear_board,
    snapshot_tasks,
    update_task,
)
from tests.test_agent_team_verification import add_job, binding
from workflows.agent_team.final_report import finalize_team_report
from workflows.agent_team.phase_budget import TeamPhaseBudget
from workflows.agent_team.subagent_runtime import (
    SwarmSubagentRuntime,
    build_swarm_session_runtime_spec,
)

NOW = 1000.0


def budget_with_verification_remaining(remaining_s: float) -> TeamPhaseBudget:
    return TeamPhaseBudget(
        started_monotonic_s=0,
        research_dispatch_deadline_s=10_000,
        research_deadline_s=10_000,
        publication_deadline_s=None,
        finalization_deadline_s=12_000,
        state={},
        verification_deadline_s=NOW + remaining_s,
    )


@pytest.fixture
async def verification_run(monkeypatch):
    monkeypatch.setattr("workflows.agent_team.phase_budget.time.monotonic", lambda: NOW)
    bus = AgentBus()
    saved = registry.snapshot()
    registry.register(AgentBus, bus)
    runtime = SwarmSubagentRuntime(
        sandbox_mode="native",
        phase_budget=budget_with_verification_remaining(144),
        first_chunk_timeout_s=45,
    )
    token = set_current_execution_scope(
        ExecutionScope(task_id="run", metadata={SWARM_SCOPE_KEY: runtime})
    )

    async def loop(**kwargs):
        return AgentLoopResult(
            messages=[], final_content="checked", stopped_by="final_answer"
        )

    monkeypatch.setattr("frontier_agent.components.agent_bus.bus.run_agent_loop", loop)
    await bus.create_session(
        task_id="run",
        name="reviewer",
        role_id="researcher",
        system_prompt="review",
        tools_override=[],
        llm_override=object(),
        runtime_spec=build_swarm_session_runtime_spec(
            runtime, session_name="reviewer", task_id="run"
        ),
    )
    try:
        yield bus, runtime
    finally:
        await bus.cleanup_task("run")
        clear_board("run")
        reset_current_execution_scope(token)
        registry.restore(saved)


def prior_packet(records: int) -> dict:
    return {"sources": {"source": {"records": [{"text": "x"}] * records}}}


def prior_check() -> dict:
    check = binding(check_id="key-figures")
    check["criterion"] = "Confirm the key figures"
    check["work_item_id"] = "t1"
    return check


def dispatch_payload(check_id="key-figures", replaces="prev"):
    check = {
        "check_id": check_id,
        "work_item_id": "t1",
        "criterion": "Confirm the key figures",
        "subject": {"text": "The figures were corrected."},
        "evidence": [{"job_id": "source"}],
    }
    if replaces:
        check.update(
            {
                "replaces_job_id": replaces,
                "revision_kind": "subject",
                "revision_reason": "Reworded the passage",
            }
        )
    return {
        "agent": "reviewer",
        "prompt": "Recheck the revised passage",
        "work_item_ids": ["t1"],
        "verification_checks": [check],
    }


async def test_verification_cost_scales_with_the_bound_packet():
    assert verification_cost_estimate(records=272) > 144
    assert verification_cost_estimate(records=2) < 144
    assert packet_record_count(prior_packet(3)) == 3


def test_admission_remaining_uses_the_wall_cap(monkeypatch):
    monkeypatch.setattr("workflows.agent_team.phase_budget.time.monotonic", lambda: NOW)
    budget = budget_with_verification_remaining(200)
    assert (
        budget.admission_remaining_for_job(
            can_publish=False, is_verification=True, wall_remaining_s=141
        )
        == 141
    )


async def test_large_recheck_is_denied_and_recorded(verification_run):
    bus, _ = verification_run
    await add_task.func([
        {
            "description": "Check the key figures",
            "verification_requirements": [
                {"check_id": "key-figures", "criterion": "Confirm the key figures"}
            ],
        }
    ])
    add_job(bus, "prev", [])
    add_job(bus, "source", [])
    previous = bus._jobs["prev"].item.metadata
    previous["verification_checks"] = [prior_check()]
    previous["verification_packet"] = prior_packet(272)

    before = len(bus.list_task_jobs("run"))
    reply = await agent_team_assign_task.func(tasks=[dispatch_payload()])

    assert reply.startswith("Error"), reply
    assert "insufficient verification budget" in reply
    assert len(bus.list_task_jobs("run")) == before
    task = snapshot_tasks("run")[0]
    assert task["verification_admission"]["key-figures"]["status"] == "denied"
    assert task["verification_admission"]["key-figures"]["reason"] == "insufficient_budget"
    assert task["verification_admission"]["key-figures"]["required_s"] > 144


async def test_small_recheck_is_admitted_with_the_same_window(verification_run):
    bus, _ = verification_run
    await add_task.func([
        {
            "description": "Check the key figures",
            "verification_requirements": [
                {"check_id": "key-figures", "criterion": "Confirm the key figures"}
            ],
        }
    ])
    add_job(bus, "prev", [])
    add_job(bus, "source", [])
    previous = bus._jobs["prev"].item.metadata
    previous["verification_checks"] = [prior_check()]
    previous["verification_packet"] = prior_packet(2)

    reply = await agent_team_assign_task.func(tasks=[dispatch_payload()])
    assert not reply.startswith("Error"), reply
    assert len(bus.list_task_jobs("run")) == 3  # prev + source + new job
    assert "verification_admission" not in snapshot_tasks("run")[0]


async def test_oversized_bound_packet_is_rejected_before_submit(verification_run):
    bus, _ = verification_run
    await add_task.func([
        {
            "description": "Check the key figures",
            "verification_requirements": [
                {"check_id": "key-figures", "criterion": "Confirm the key figures"}
            ],
        }
    ])
    add_job(bus, "source", [])
    bus._jobs["source"].result.metadata["corpus_evidence"] = [
        {"doc_id": "doc:1", "locator": f"chunk:{index}", "text": f"record {index}"}
        for index in range(170)
    ]

    reply = await agent_team_assign_task.func(
        tasks=[dispatch_payload(replaces="")]
    )
    assert reply.startswith("Error"), reply
    assert "bound evidence packet has 170 records" in reply
    task = snapshot_tasks("run")[0]
    assert task["verification_admission"]["key-figures"]["reason"] == "packet_too_large"


async def test_registered_check_records_its_registration_estimate(verification_run):
    await add_task.func([
        {
            "description": "Check the key figures",
            "verification_requirements": [
                {"check_id": "key-figures", "criterion": "Confirm the key figures"}
            ],
        }
    ])
    task = snapshot_tasks("run")[0]
    assert task["verification_estimate_s"] == 90.0


async def test_denied_check_stays_unchecked_and_traceable_in_the_contract(
    verification_run,
):
    bus, _ = verification_run
    await add_task.func([
        {
            "description": "Check the key figures",
            "verification_requirements": [
                {"check_id": "key-figures", "criterion": "Confirm the key figures"}
            ],
        }
    ])
    add_job(bus, "prev", [])
    add_job(bus, "source", [])
    previous = bus._jobs["prev"].item.metadata
    previous["verification_checks"] = [prior_check()]
    previous["verification_packet"] = prior_packet(272)
    await agent_team_assign_task.func(tasks=[dispatch_payload()])

    await update_task.func([
        {
            "id": "t1",
            "resolution": "blocked",
            "notes": "Admission denied: the bound packet cannot be reviewed in the window",
            "gap": "Key figures were not independently rechecked",
        }
    ])
    out = finalize_team_report(
        "已给出可用结论，关键数字未完成独立复核。",
        source="agent",
        answer_status="partial",
        stopped_by="final_answer",
        tasks=snapshot_tasks("run"),
    )
    row = out["report_contract"]["task_board"][0]
    assert row["verification_admission"]["key-figures"]["status"] == "denied"
    assert row["verification_status"] != "passed"
    assert out["report_contract"]["verification"] != "passed_for_declared_checks"
