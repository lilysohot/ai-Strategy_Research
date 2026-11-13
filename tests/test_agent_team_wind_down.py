from __future__ import annotations

import asyncio
import json
import re

import pytest

from frontier_agent.components.agent_bus import (
    AgentBus,
    JobEntry,
    SubAgentResult,
    SubTask,
)
from frontier_agent.core.loop_types import AgentLoopResult
from frontier_agent.core.messages import assistant_msg, system_msg, user_msg
from plugins.tools._verification import project_checks
from workflows.agent_team.lifecycle import (
    append_team_wind_down_checkpoint,
    render_team_status_summary,
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
    session.pending_results.append(
        SubAgentResult(
            question="count the complete CSV",
            role_id="researcher",
            final_content="Verified full CSV totals: 7 / 941 / 138 / 803.",
            success=True,
            job_id="root.job.1",
            metadata={"stopped_by": "submit_report"},
        )
    )
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
    assert result.metadata["final_answer_source"] == "collected_report_fallback"
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
    assert wind_down.unresolved_count == 0
    assert wind_down.incomplete_count == 1
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
    assert (
        _publication_manifest_complete(
            {**state, "phase": "research"},
            outputs,
        )
        is False
    )
    assert (
        _soft_wall_publication_finalized(
            stopped_by="wall_deadline",
            team_status="complete",
            answer_source="clean_context_llm",
            publication_state=state,
            outputs_dir=outputs,
        )
        is True
    )
    assert (
        _soft_wall_publication_finalized(
            stopped_by="wall_deadline",
            team_status="partial",
            answer_source="clean_context_llm",
            publication_state=state,
            outputs_dir=outputs,
        )
        is False
    )


@pytest.mark.asyncio
async def test_wind_down_salvages_cancelled_member_before_refresh(monkeypatch, tmp_path):
    """The 318a2c run lost counterevidence while a member was composing its report."""
    from types import SimpleNamespace

    from frontier_agent.components.agent_bus.models import SubAgentRuntimeSpec
    from frontier_agent.core.messages import tool_msg

    ready = asyncio.Event()
    observed = "SOURCE: https://example.org/report — some training used domestic chips"

    async def loop(**kwargs):
        ctx = SimpleNamespace(
            turn=1,
            messages=[
                system_msg(kwargs["system_prompt"]),
                user_msg(kwargs["user_message"]),
                assistant_msg(
                    "",
                    tool_calls=[
                        {
                            "id": "fetch-1",
                            "type": "function",
                            "function": {
                                "name": "web_fetch",
                                "arguments": '{"url":"https://example.org/report"}',
                            },
                        }
                    ],
                ),
                tool_msg(observed, "fetch-1"),
            ],
            metadata={
                "content_acquisition": [
                    {"source": "https://example.org/report", "obtained": True, "status": "success"}
                ]
            },
        )
        for observer in kwargs["observers"]:
            await observer.on_turn_end(ctx)
        ready.set()
        await asyncio.Event().wait()

    from workflows.agent_team.subagent_runtime import (
        SwarmSubagentRuntime,
        build_swarm_session_runtime_spec,
    )

    class NoRecoveryLLM:
        calls = 0

        async def chat(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("Cancellation salvage must not start another model call")

    llm = NoRecoveryLLM()
    runtime = build_swarm_session_runtime_spec(
        SwarmSubagentRuntime(sub_agent_llm=llm),
        session_name="worker",
        task_id="salvage",
    )

    monkeypatch.setattr("frontier_agent.components.agent_bus.bus.run_agent_loop", loop)
    bus = AgentBus()
    bus.configure_task_result_store("salvage", tmp_path)
    sid = await bus.create_session(
        task_id="salvage",
        name="worker",
        role_id="researcher",
        system_prompt="research",
        tools_override=[],
        llm_override=object(),
        runtime_spec=SubAgentRuntimeSpec(
            force_finalizer=runtime.force_finalizer, result_adapter=runtime.result_adapter
        ),
    )
    job = await bus.submit_task_to_session(sid, "Find training hardware evidence")
    await asyncio.wait_for(ready.wait(), 1)
    draft = AgentLoopResult(
        messages=[
            user_msg("Training hardware?"),
            assistant_msg("There is no evidence of domestic training."),
        ],
        final_content="There is no evidence of domestic training.",
        stopped_by="final_answer",
        metadata={"final_answer": "There is no evidence of domestic training."},
    )
    try:
        wind = await wind_down_team(bus=bus, task_id="salvage", wait_s=0)
        assert observed in wind.checkpoint
        assert bus._jobs[job].result.error == "aborted"
        assert bus._jobs[job].result.metadata["final_answer_source"] == "tool_observations"
        assert (tmp_path / f"{job}.json").exists()
        assert wind.collected_count == 1
        assert wind.incomplete_count == 1
        assert llm.calls == 0
        assert wind.run_status == "partial"
        assert wind.should_refresh_answer(draft)
        assert bus._jobs[job].result.metadata["content_acquisition"][0]["obtained"]
        append_team_wind_down_checkpoint(draft, wind)
        await force_final_answer(
            draft,
            object(),
            1,
            run_recovery_llm=False,
            force_recovery=wind.should_refresh_answer(draft),
            prefer_collected_reports=True,
        )
        assert observed in draft.final_content
        assert "There is no evidence of domestic training." not in draft.final_content
        again = await wind_down_team(bus=bus, task_id="salvage", wait_s=0)
        assert again.collected_count == 0
    finally:
        await bus.cleanup_task("salvage")


# ── bounded model-facing status summary ────────────────────────────────

_INTERNAL_LOCATOR = "ce:848f7a43e69503c22c8edf037bc1f10e"


def _evidence_fragments(count: int) -> list[dict[str, str]]:
    return [
        {
            "source_key": f"k{index}",
            "source": f"chunk:document1/unit%3A{index:04d}",
            "text": f"原文片段 {index} " + "数据" * 20,
            "doc_id": f"doc:{index}",
        }
        for index in range(count)
    ]


def _fault_checks(evidence: list[dict[str, str]]) -> list[dict[str, object]]:
    return [
        {
            "check_id": "quote_fidelity",
            "work_item_id": "t3",
            "criterion": "quote fidelity",
            "binding_id": "a" * 64,
            "required": True,
            "protocol_version": 1,
            "verdict": "fail",
            "attempts": [{"execution_status": "incomplete"}],
            "subject": {"text": "压力情形：0.1–0.25 GW", "sha256": "f" * 64},
            "evidence": evidence,
            "calculation_sources": evidence,
            "result": {
                "verdict": "fail",
                "detail": f"引文1 not verbatim at {_INTERNAL_LOCATOR}",
                "unresolved_issues": [
                    f"引文1 not verbatim: locator {_INTERNAL_LOCATOR}",
                ],
            },
        },
        {
            "check_id": "number_scope",
            "work_item_id": "t3",
            "criterion": "number scope",
            "binding_id": "b" * 64,
            "required": True,
            "protocol_version": 1,
            "verdict": "unchecked",
            "attempts": [{"execution_status": "incomplete"}],
            "subject": {"text": "6,000 柜 = 1.05 GW", "sha256": "e" * 64},
            "evidence": evidence,
            "calculation_sources": evidence,
            "result": None,
        },
    ]


def _render(
    *,
    job_gaps: list[dict[str, object]],
    checks: list[dict[str, object]],
    verification_status: str = "failed",
) -> str:
    return render_team_status_summary(
        overall="partial",
        status="complete",
        guidance="Team coverage is incomplete.",
        collected_count=0,
        incomplete_count=1,
        queued_aborted=0,
        unresolved_count=0,
        verification_status=verification_status,
        job_gaps=job_gaps,
        checks=checks,
    )


def _section_counts(block: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    def _count(label: str) -> tuple[int, int, int]:
        match = re.search(
            rf"{label}: total=(\d+); shown=(\d+); omitted=(\d+)",
            block,
        )
        assert match is not None
        return tuple(int(part) for part in match.groups())  # type: ignore[return-value]

    return _count("Whole-run required job gaps"), _count("Version-bound checks")


def test_fault_sample_keeps_verdicts_and_drops_evidence_arrays() -> None:
    evidence = _evidence_fragments(544)
    checks = _fault_checks(evidence)
    gaps = [
        {
            "job_id": "root.job.3",
            "agent": "quote_verify_verification",
            "status": "incomplete",
            "reason": "llm_error",
            "required": True,
            "verification_checks": checks,
        }
    ]

    block = _render(job_gaps=gaps, checks=checks)

    assert len(block) <= 8_000
    assert '"evidence"' not in block
    assert '"subject"' not in block
    assert '"attempts"' not in block
    assert "calculation_sources" not in block
    assert "content_acquisition" not in block
    assert "ce:" not in block and "chunk:" not in block and "doc:" not in block
    assert '"verdict":"fail"' in block
    assert '"verdict":"unchecked"' in block
    assert "a" * 64 in block and "b" * 64 in block
    assert "quote_fidelity" in block and "number_scope" in block
    assert _section_counts(block)[1] == (2, 2, 0)


def test_active_version_and_execution_status_are_projected_not_recomputed() -> None:
    old_check = {
        "check_id": "quote_fidelity",
        "work_item_id": "t3",
        "criterion": "quote fidelity",
        "binding_id": "1" * 64,
        "required": True,
        "protocol_version": 1,
        "subject": {"text": "old passage", "sha256": "1" * 64},
        "evidence": [{"key": "k-old", "sha256": "1" * 64}],
    }
    new_check = {
        **old_check,
        "binding_id": "2" * 64,
        "replaces_job_id": "root.job.1",
        "revision_reason": "subject changed",
        "revision_kind": "subject",
        "subject": {"text": "new passage", "sha256": "2" * 64},
    }
    failed_exec_check = {
        "check_id": "arithmetic_total",
        "work_item_id": "t3",
        "criterion": "arithmetic",
        "binding_id": "3" * 64,
        "required": True,
        "protocol_version": 1,
        "subject": {"text": "1.05 GW", "sha256": "3" * 64},
        "evidence": [{"key": "k-3", "sha256": "3" * 64}],
    }
    jobs = [
        {
            "job_id": "root.job.1",
            "status": "complete",
            "reason": "",
            "verification_checks": [old_check],
            "verification_events": [
                {
                    "check_id": "quote_fidelity",
                    "binding_id": "1" * 64,
                    "verdict": "pass",
                    "detail": "old version passed",
                    "job_id": "root.job.1",
                }
            ],
        },
        {
            "job_id": "root.job.2",
            "status": "incomplete",
            "reason": "llm_error",
            "verification_checks": [new_check],
            "verification_events": [],
        },
        {
            "job_id": "root.job.3",
            "status": "failed",
            "reason": "llm_error",
            "verification_checks": [failed_exec_check],
            "verification_events": [
                {
                    "check_id": "arithmetic_total",
                    "binding_id": "3" * 64,
                    "verdict": "fail",
                    "detail": "sum does not match",
                    "job_id": "root.job.3",
                }
            ],
        },
    ]

    verification = project_checks(jobs)
    block = _render(
        job_gaps=[],
        checks=list(verification["checks"]),
        verification_status=str(verification["status"]),
    )

    assert '"verdict":"unchecked"' in block
    assert "2" * 64 in block
    assert "1" * 64 not in block
    assert '"verdict":"pass"' not in block
    assert '"execution_status":"failed"' in block
    assert '"verdict":"fail"' in block
    assert '"execution_status":"incomplete"' in block


def test_budget_caps_rows_and_preserves_counts() -> None:
    gaps = [
        {
            "job_id": f"root.job.{index}",
            "agent": "worker",
            "status": "failed" if index % 2 else "incomplete",
            "reason": "llm_error " + "细节" * 500 + _INTERNAL_LOCATOR,
            "required": True,
            "verification_checks": [{"check_id": f"c{index}_{item}"} for item in range(10)],
        }
        for index in range(50)
    ]
    checks = [
        {
            "check_id": f"check_{index}",
            "work_item_id": f"t{index}",
            "binding_id": f"{index:064x}",
            "required": True,
            "verdict": "fail" if index % 3 == 0 else "unchecked",
            "attempts": [{"execution_status": "incomplete"}],
            "result": {
                "detail": "长说明" * 400 + _INTERNAL_LOCATOR,
                "unresolved_issues": ["问题" * 400 + _INTERNAL_LOCATOR],
            },
        }
        for index in range(100)
    ]

    block = _render(job_gaps=gaps, checks=checks)

    assert len(block) <= 8_000
    gaps_counts, checks_counts = _section_counts(block)
    assert gaps_counts[0] == 50 and gaps_counts[1] <= 20
    assert gaps_counts[0] == gaps_counts[1] + gaps_counts[2]
    assert checks_counts[0] == 100 and checks_counts[1] <= 30
    assert checks_counts[0] == checks_counts[1] + checks_counts[2]
    assert "ce:" not in block
    for line in block.splitlines():
        if line.startswith("- {"):
            row = json.loads(line[2:])
            if "note" in row:
                assert len(row["note"]) <= 160


@pytest.mark.asyncio
async def test_wind_down_projection_bounds_message_without_mutating_audit_data() -> None:
    bus = AgentBus()
    evidence = _evidence_fragments(544)
    checks = _fault_checks(evidence)
    bus._jobs["root.job.2"] = JobEntry(
        job_id="root.job.2",
        parent_task_id="root",
        item=SubTask(
            question="verify",
            role_id="researcher",
            metadata={
                "required_for_completion": True,
                "verification_checks": checks,
                "verification_events": [
                    {
                        "check_id": "quote_fidelity",
                        "binding_id": "a" * 64,
                        "verdict": "fail",
                        "detail": f"locator {_INTERNAL_LOCATOR}",
                        "unresolved_issues": [f"locator {_INTERNAL_LOCATOR}"],
                        "job_id": "root.job.2",
                    }
                ],
            },
        ),
        task=None,
        status="running",
    )
    session_id = await bus.create_session(
        task_id="root",
        name="worker",
        role_id="researcher",
        system_prompt="test",
        tools_override=[],
        llm_override=object(),
    )
    session = bus.get_session(session_id)
    assert session is not None
    session.total_task_count = 1
    member_report = "MEMBER REPORT " * 200
    session.pending_results.append(
        SubAgentResult(
            question="q",
            role_id="researcher",
            final_content=member_report,
            success=True,
            job_id="root.job.1",
            metadata={"stopped_by": "submit_report"},
        )
    )
    bus._jobs["root.job.1"] = JobEntry(
        job_id="root.job.1",
        parent_task_id="root",
        item=SubTask(question="q", role_id="researcher"),
        task=None,
        status="completed",
        session_id=session_id,
    )

    wind = await wind_down_team(bus=bus, task_id="root", wait_s=0)
    try:
        status_text = wind.checkpoint[wind.checkpoint.rindex('<report agent="orchestrator"') :]
        assert len(status_text) <= 8_000
        assert "ce:" not in status_text and "doc:" not in status_text
        assert '"verdict":"fail"' in status_text
        assert '"verdict":"unchecked"' in status_text
        assert wind.checkpoint.count("MEMBER REPORT") == 200
        stored = next(job for job in wind.job_outcomes if job["job_id"] == "root.job.2")
        assert len(stored["verification_checks"][0]["evidence"]) == 544
        assert stored["verification_checks"][0]["subject"]["text"]
        assert len(wind.verification["checks"][0]["evidence"]) == 544
        assert wind.status == "complete"
        assert wind.run_status == "partial"
    finally:
        await bus.cleanup_task("root")


@pytest.mark.asyncio
async def test_checkpoint_reports_the_active_check_version() -> None:
    bus = AgentBus()
    old_check = {
        "check_id": "quote_fidelity",
        "work_item_id": "t3",
        "criterion": "quote fidelity",
        "binding_id": "1" * 64,
        "required": True,
        "protocol_version": 1,
        "subject": {"text": "old passage"},
        "evidence": [{"key": "e1"}],
    }
    new_check = {
        **old_check,
        "binding_id": "2" * 64,
        "replaces_job_id": "root.job.1",
        "revision_kind": "subject",
        "revision_reason": "subject changed",
        "subject": {"text": "new passage"},
    }
    bus._jobs["root.job.1"] = JobEntry(
        job_id="root.job.1",
        parent_task_id="root",
        item=SubTask(
            question="old",
            role_id="researcher",
            metadata={"verification_checks": [old_check]},
        ),
        task=None,
        status="completed",
    )
    bus._jobs["root.job.1"].result = SubAgentResult(
        question="old",
        role_id="researcher",
        final_content="old verdict",
        success=True,
        job_id="root.job.1",
        metadata={"stopped_by": "submit_report"},
    )
    bus._jobs["root.job.2"] = JobEntry(
        job_id="root.job.2",
        parent_task_id="root",
        item=SubTask(
            question="new",
            role_id="researcher",
            metadata={
                "required_for_completion": True,
                "verification_checks": [new_check],
                "verification_events": [],
            },
        ),
        task=None,
        status="running",
    )

    wind = await wind_down_team(bus=bus, task_id="root", wait_s=0)
    try:
        checkpoint = wind.checkpoint
        assert "2" * 64 in checkpoint
        assert "1" * 64 not in checkpoint
        assert '"verdict":"unchecked"' in checkpoint
        assert "quote_fidelity" in checkpoint
    finally:
        await bus.cleanup_task("root")


@pytest.mark.asyncio
async def test_checkpoint_drops_full_verification_receipt_and_accounts_parts() -> None:
    bus = AgentBus()
    research_session = await bus.create_session(
        task_id="root",
        name="corpus_extract_research",
        role_id="researcher",
        system_prompt="test",
        tools_override=[],
        llm_override=object(),
    )
    verification_session = await bus.create_session(
        task_id="root",
        name="quote_verify_verification",
        role_id="researcher",
        system_prompt="test",
        tools_override=[],
        llm_override=object(),
    )
    research_entry = JobEntry(
        job_id="root.job.1",
        parent_task_id="root",
        item=SubTask(
            question="research",
            role_id="researcher",
            metadata={"bound_research": True, "work_item_ids": ["t1"]},
        ),
        task=None,
        status="completed",
        session_id=research_session,
    )
    research_entry.result = SubAgentResult(
        question="research",
        role_id="researcher",
        final_content="RESEARCH BODY UNIQUE",
        success=True,
        job_id="root.job.1",
        metadata={"stopped_by": "final_answer", "final_answer_source": "agent"},
    )
    bus._jobs["root.job.1"] = research_entry
    checks = [
        {
            "check_id": "quote_fidelity",
            "work_item_id": "t3",
            "criterion": "quote fidelity",
            "binding_id": "a" * 64,
            "required": True,
            "protocol_version": 1,
            "subject": {"text": "checked passage"},
            "evidence": [{"key": "e1"}],
        },
        {
            "check_id": "number_scope",
            "work_item_id": "t3",
            "criterion": "number scope",
            "binding_id": "b" * 64,
            "required": True,
            "protocol_version": 1,
            "subject": {"text": "checked number"},
            "evidence": [{"key": "e2"}],
        },
    ]
    verification_entry = JobEntry(
        job_id="root.job.2",
        parent_task_id="root",
        item=SubTask(
            question="verify",
            role_id="researcher",
            metadata={
                "verification_checks": checks,
                "verification_events": [
                    {
                        "check_id": "quote_fidelity",
                        "binding_id": "a" * 64,
                        "verdict": "fail",
                        "unresolved_issues": ["引文未逐字匹配"],
                        "job_id": "root.job.2",
                    }
                ],
            },
        ),
        task=None,
        status="running",
        session_id=verification_session,
    )
    full_verification_body = "VERIFICATION FULL BODY " + "Z" * 60_000
    verification_entry.result = SubAgentResult(
        question="verify",
        role_id="researcher",
        final_content=full_verification_body,
        success=True,
        job_id="root.job.2",
        metadata={"stopped_by": "llm_error", "final_answer_source": "tool_observations"},
    )
    bus._jobs["root.job.2"] = verification_entry
    research = bus.get_session(research_session)
    verification = bus.get_session(verification_session)
    assert research is not None and verification is not None
    research.total_task_count = 1
    verification.total_task_count = 1
    research.pending_results.append(research_entry.result)
    verification.pending_results.append(verification_entry.result)

    wind = await wind_down_team(bus=bus, task_id="root", wait_s=0)
    try:
        assert "RESEARCH BODY UNIQUE" in wind.checkpoint
        assert "VERIFICATION FULL BODY" not in wind.checkpoint
        assert "Z" * 1_000 not in wind.checkpoint
        assert "quote_fidelity" in wind.checkpoint
        assert "number_scope" in wind.checkpoint
        status_start = wind.checkpoint.index('<report agent="orchestrator"')
        member_text = wind.checkpoint[: status_start - 2]
        status_text = wind.checkpoint[status_start:]
        assert wind.checkpoint == f"{member_text}\n\n{status_text}"
        assert len(member_text) + 2 + len(status_text) == len(wind.checkpoint)
        stored = next(job for job in wind.job_outcomes if job["job_id"] == "root.job.2")
        assert len(stored["verification_checks"]) == 2
        assert bus._jobs["root.job.2"].result.final_content == full_verification_body

        result = AgentLoopResult(messages=[], stopped_by="wall_deadline")
        append_team_wind_down_checkpoint(result, wind)
        assert len(result.messages) == 2
        assert result.messages[-1]["content"] == wind.checkpoint
        assert result.messages[0]["tool_calls"][0]["function"]["name"] == "collect_reports"
    finally:
        await bus.cleanup_task("root")
