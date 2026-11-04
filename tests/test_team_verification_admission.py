"""Regression for f390: planned verification must not run as an unbound prose task."""

import json

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
from plugins.tools.assign_task import agent_team_assign_task
from plugins.tools.task_board import add_task, clear_board
from workflows.agent_team.nodes.main_agent import _build_team_phase_budget
from workflows.agent_team.phase_budget import TeamPhaseBudget
from workflows.agent_team.subagent_runtime import (
    SwarmSubagentRuntime,
    build_swarm_session_runtime_spec,
)


@pytest.fixture
async def admission_run(monkeypatch):
    bus = AgentBus()
    saved = registry.snapshot()
    registry.register(AgentBus, bus)
    runtime = SwarmSubagentRuntime(sandbox_mode="native")
    token = set_current_execution_scope(
        ExecutionScope(task_id="run", metadata={SWARM_SCOPE_KEY: runtime})
    )

    async def loop(**kwargs):
        prompt = kwargs["user_message"]
        if "# Bound verification checks\n" in prompt:
            from plugins.tools.submit_report import submit_report
            from tests.test_agent_team_verification import verdict_for

            checks, _ = json.JSONDecoder().raw_decode(
                prompt.split("# Bound verification checks\n")[1]
            )
            receipt = await submit_report.func(
                "Exact subject checked",
                verification_results=[
                    verdict_for(checks[0]),
                ],
            )
            assert not receipt.startswith("Error"), receipt
        return AgentLoopResult(
            messages=[], final_content="Unchecked prose", stopped_by="final_answer"
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


@pytest.mark.parametrize("explicit_ids", [False, True])
async def test_unbound_planned_verification_is_rejected_before_dispatch(
    admission_run, explicit_ids
):
    bus, _ = admission_run
    await add_task.func(
        [
            {
                "description": "Independently verify citations",
                "kind": "verification",
                "owners": ["reviewer"],
                "verification_requirements": [
                    {"check_id": "citations", "criterion": "Check exact candidate"}
                ],
            }
        ]
    )
    assignment = {"agent": "reviewer", "prompt": "Check citations and return binding_id and PASS"}
    if explicit_ids:
        assignment["work_item_ids"] = ["t1"]
    result = await agent_team_assign_task.func(tasks=[assignment])
    assert result.startswith("Error"), result
    assert "verification_checks" in result and "citations" in result
    assert bus.list_task_jobs("run") == []


def test_wait_cannot_consume_final_answer_reserve(monkeypatch):
    budget = TeamPhaseBudget(0, 495, 720, 914, 1050, {}, verification_deadline_s=900)
    monkeypatch.setattr("workflows.agent_team.phase_budget.time.monotonic", lambda: 673)
    _, deadline = budget.wait_deadline(publication_pending=True)
    assert deadline <= 794, "blocking collect must return before the 120s delivery reserve"


def test_hard_cap_preserves_verification_and_publication_windows():
    budget = _build_team_phase_budget(
        started_monotonic_s=0,
        research_wall_s=720,
        publication_phase_timeout_s=180,
        hard_deadline_monotonic_s=1050,
        finalization_timeout_s=120,
        wind_down_timeout_s=15,
        worst_case_tool_s=165,
        publication_state={},
    )
    assert budget.publication_deadline_s - budget.verification_deadline_s >= 180
    assert budget.verification_deadline_s - budget.research_deadline_s >= 180


async def test_rejected_dispatch_can_be_corrected_checked_and_delivered(admission_run):
    from plugins.tools.collect_reports import collect_reports
    from plugins.tools.task_board import snapshot_tasks
    from tests.test_agent_team_verification import add_job
    from workflows.agent_team.delivery import deliver_answer

    bus, _ = admission_run
    await add_task.func(
        [
            {
                "description": "Check exact candidate",
                "kind": "verification",
                "owners": ["reviewer"],
                "verification_requirements": [
                    {"check_id": "citations", "criterion": "Check exact candidate"}
                ],
            },
            {"description": "Answer", "kind": "delivery"},
        ]
    )
    unbound = await agent_team_assign_task.func(tasks=[{"agent": "reviewer", "prompt": "Check"}])
    assert unbound.startswith("Error")
    add_job(bus, "source", [])
    passage = "Under the stated retention assumptions, the estimate is 20–25 TB per accelerator."
    reply = await agent_team_assign_task.func(
        tasks=[
            {
                "agent": "reviewer",
                "prompt": "Check only the bound passage",
                "verification_checks": [
                    {
                        "check_id": "citations",
                        "work_item_id": "t1",
                        "criterion": "Check exact candidate",
                        "subject": {"text": passage},
                        "evidence": [{"job_id": "source"}],
                        "publication_excerpt": True,
                    }
                ],
            }
        ]
    )
    assert not reply.startswith("Error"), reply
    await collect_reports.func(timeout=2)
    assert snapshot_tasks("run")[0]["verification_status"] == "passed"
    receipt = await deliver_answer.func(
        content=passage,
        updates=[
            {
                "id": "t1",
                "resolution": "resolved",
                "notes": "Bound candidate passed",
            }
        ],
    )
    assert "accepted" in receipt
    assert all(t["resolution"] == "resolved" for t in snapshot_tasks("run"))


async def test_check_nudge_arrives_while_other_research_is_running(admission_run, monkeypatch):
    from tests.test_agent_team_verification import add_job
    from tests.test_team_atomic_delivery import turn_context
    from workflows.agent_team.delivery import TeamDeliveryObserver

    bus, _ = admission_run
    await add_task.func(
        [
            {
                "description": "Check available findings",
                "kind": "verification",
                "verification_requirements": [
                    {"check_id": "ready", "criterion": "Check available evidence"}
                ],
            }
        ]
    )
    add_job(bus, "first-source", [])
    add_job(bus, "slow-source", [])
    bus._jobs["slow-source"].status = "running"
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 335)
    observer = TeamDeliveryObserver(
        TeamPhaseBudget(0, 329, 554, 914, 1050, {}, verification_deadline_s=734)
    )
    hint = await observer.on_before_llm(turn_context())
    assert "first-source" in hint.inject_messages[0]
    assert "required verification ready" in hint.inject_messages[0]
    assert not observer.active
    assert await observer.on_before_llm(turn_context(turn=22)) is None
