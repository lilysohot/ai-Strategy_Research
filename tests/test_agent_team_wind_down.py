from __future__ import annotations

import asyncio

import pytest

from frontier_agent.components.agent_bus import (
    AgentBus,
    JobEntry,
    SubAgentResult,
    SubTask,
)
from frontier_agent.core.loop_types import AgentLoopResult
from frontier_agent.core.messages import assistant_msg, system_msg, user_msg
from workflows.agent_team.lifecycle import (
    append_team_wind_down_checkpoint,
    wind_down_team,
)
from workflows.agent_team.nodes.main_agent import (
    _publication_manifest_complete,
    _soft_wall_publication_finalized,
)
from workflows.agent_team.subagent_runtime import force_final_answer


@pytest.mark.asyncio
async def test_freeze_aborts_queue_and_never_dispatches_successor(
    monkeypatch,
) -> None:
    release = asyncio.Event()
    started: list[str] = []

    async def fake_run_agent_loop(**kwargs):
        started.append(kwargs["user_message"])
        await release.wait()
        return AgentLoopResult(
            messages=[
                system_msg(kwargs["system_prompt"]),
                user_msg(kwargs["user_message"]),
                assistant_msg("complete result"),
            ],
            final_content="complete result",
            stopped_by="final_answer",
        )

    monkeypatch.setattr(
        "frontier_agent.components.agent_bus.bus.run_agent_loop",
        fake_run_agent_loop,
    )
    bus = AgentBus()
    session_id = await bus.create_session(
        task_id="root",
        name="worker",
        role_id="researcher",
        system_prompt="test",
        tools_override=[],
        llm_override=object(),
    )
    await bus.submit_task_to_session(session_id, "current task")
    queued_id = await bus.submit_task_to_session(session_id, "too-late task")

    assert bus.freeze_task_dispatch("root") == 1
    assert bus._jobs[queued_id].status == "aborted"
    with pytest.raises(RuntimeError, match="dispatch is frozen"):
        await bus.submit_task_to_session(session_id, "new task")

    release.set()
    assert await bus.wait_any_session("root", timeout=1) is not None
    await asyncio.sleep(0)

    assert started == ["current task"]
    await bus.cleanup_task("root")


@pytest.mark.asyncio
async def test_deadline_wind_down_replaces_preview_with_member_full_result() -> None:
    """Regression: a full member report must outrank the main's grep preview."""
    bus = AgentBus()
    session_id = await bus.create_session(
        task_id="root",
        name="csv_auditor",
        role_id="researcher",
        system_prompt="test",
        tools_override=[],
        llm_override=object(),
    )
    session = bus.get_session(session_id)
    assert session is not None
    session.total_task_count = 1
    session.pending_results.append(SubAgentResult(
        question="count the complete CSV",
        role_id="researcher",
        final_content="Verified full CSV totals: 7 / 941 / 138 / 803.",
        success=True,
        job_id="root.job.1",
        metadata={"stopped_by": "submit_report"},
    ))
    result = AgentLoopResult(
        messages=[user_msg("count the CSV"), assistant_msg("Preview: 2 / 380 / 0 / 380")],
        final_content="Preview: 2 / 380 / 0 / 380",
        stopped_by="final_answer",
        metadata={
            "final_answer": "Preview: 2 / 380 / 0 / 380",
            "final_answer_source": "agent",
        },
    )

    wind_down = await wind_down_team(bus=bus, task_id="root", wait_s=0)
    append_team_wind_down_checkpoint(result, wind_down)
    await force_final_answer(
        result,
        llm=object(),
        timeout=1,
        task_description="count the CSV",
        run_recovery_llm=False,
        force_recovery=wind_down.requires_resynthesis,
        prefer_collected_reports=True,
    )

    assert wind_down.status == "complete"
    assert wind_down.collected_count == 1
    assert "7 / 941 / 138 / 803" in result.final_content
    assert "2 / 380 / 0 / 380" not in result.final_content
    assert result.metadata["final_answer_source"] == "collected_reports"
    await bus.cleanup_task("root")


@pytest.mark.asyncio
async def test_wind_down_waits_for_a_member_already_finishing(monkeypatch) -> None:
    async def fake_run_agent_loop(**kwargs):
        await asyncio.sleep(0.02)
        return AgentLoopResult(
            messages=[assistant_msg("verified late result")],
            final_content="verified late result",
            stopped_by="final_answer",
        )

    monkeypatch.setattr(
        "frontier_agent.components.agent_bus.bus.run_agent_loop",
        fake_run_agent_loop,
    )
    bus = AgentBus()
    session_id = await bus.create_session(
        task_id="root",
        name="finishing_worker",
        role_id="researcher",
        system_prompt="test",
        tools_override=[],
        llm_override=object(),
    )
    await bus.submit_task_to_session(session_id, "finish current calculation")

    wind_down = await wind_down_team(bus=bus, task_id="root", wait_s=1)

    assert wind_down.status == "complete"
    assert wind_down.collected_count == 1
    assert "verified late result" in wind_down.checkpoint
    await bus.cleanup_task("root")


@pytest.mark.asyncio
async def test_wind_down_marks_unresolved_member_as_partial() -> None:
    bus = AgentBus()
    session_id = await bus.create_session(
        task_id="root",
        name="slow_worker",
        role_id="researcher",
        system_prompt="test",
        tools_override=[],
        llm_override=object(),
    )
    session = bus.get_session(session_id)
    assert session is not None
    task = asyncio.create_task(asyncio.sleep(60))
    session.current_job_id = "root.job.1"
    bus._jobs["root.job.1"] = JobEntry(
        job_id="root.job.1",
        parent_task_id="root",
        item=SubTask(question="slow", role_id="researcher"),
        task=task,  # type: ignore[arg-type]
        status="running",
    )

    wind_down = await wind_down_team(bus=bus, task_id="root", wait_s=0)

    assert wind_down.status == "partial"
    assert wind_down.unresolved_count == 1
    assert "do not claim exhaustive coverage" in wind_down.checkpoint
    await bus.cleanup_task("root", cancel_timeout_s=0.1)


@pytest.mark.asyncio
async def test_reporter_preserves_partial_team_completeness(monkeypatch) -> None:
    from workflows.agent_team.nodes.reporter import agent_team_reporter

    async def fake_report(state, ctx):
        return "Report generated from partial team coverage."

    monkeypatch.setattr(
        "workflows.agent_team.nodes.fast_reporter_v1._run_fast_reporter",
        fake_report,
    )
    result = await agent_team_reporter(
        {
            "reporter_backend": "fast",
            "team_completeness": "partial",
            "metadata": {},
        },
        object(),  # type: ignore[arg-type]
    )

    assert result["answer_status"] == "partial"


def test_soft_wall_can_finish_only_after_publisher_report_and_manifest(
    tmp_path,
) -> None:
    """The team research wall is a phase boundary, not the external Web wall.
    A publisher that finishes inside wind-down may turn the Run into a normal
    completion, but only when every manifest file really exists.
    """
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    state = {
        "phase": "publishing",
        "publisher_agent_name": "report_publisher",
        "deliverable_manifest": (
            "/outputs/summary.json",
            "/outputs/report.md",
        ),
    }

    assert _publication_manifest_complete(state, outputs) is False

    (outputs / "summary.json").write_text("{}", encoding="utf-8")
    (outputs / "report.md").write_text("verified", encoding="utf-8")

    assert _publication_manifest_complete(state, outputs) is True
    assert _publication_manifest_complete(
        {**state, "phase": "research"}, outputs,
    ) is False
    assert _soft_wall_publication_finalized(
        stopped_by="wall_deadline",
        team_status="complete",
        answer_source="clean_context_llm",
        publication_state=state,
        outputs_dir=outputs,
    ) is True
    assert _soft_wall_publication_finalized(
        stopped_by="wall_deadline",
        team_status="partial",
        answer_source="clean_context_llm",
        publication_state=state,
        outputs_dir=outputs,
    ) is False
