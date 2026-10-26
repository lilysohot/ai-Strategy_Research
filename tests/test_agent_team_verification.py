"""Versioned checks and explicit rechecks through the real finalization seam."""

from copy import deepcopy

import pytest

from frontier_agent.components.agent_bus import AgentBus, JobEntry, SubAgentResult, SubTask
from plugins.tools._verification import (
    VerificationCheck,
    bind_checks,
    commit_results,
    project_checks,
    reset_verification_scope,
    set_verification_scope,
    validate_results,
)
from workflows.agent_team.final_report import finalize_team_report
from workflows.agent_team.lifecycle import wind_down_team


def binding(check_id="amount", version="v1", replaces=""):
    return {
        "check_id": check_id,
        "work_item_id": "t1",
        "criterion": "Recompute the amount",
        "binding_id": version,
        "required": True,
        "replaces_job_id": replaces,
        "revision_reason": "updated source" if version != "v1" else "",
        "subject": {"job_id": "draft", "ref": "", "sha256": "d" * 64, "key": "draft"},
        "evidence": [{"job_id": "source", "ref": "", "sha256": "e" * 64, "key": "source"}],
    }


def add_job(bus, job_id, checks, *, stop="submit_report", verdicts=None):
    events = [
        {
            "check_id": check["check_id"],
            "binding_id": check["binding_id"],
            "verdict": verdict,
            "method": "recompute",
            "detail": "42 + 8 = 50",
            "evidence_keys": ["source"],
        }
        for check, verdict in zip(checks, verdicts or [], strict=False)
    ]
    bus._jobs[job_id] = JobEntry(
        job_id=job_id,
        parent_task_id="run",
        session_id="run::reviewer",
        status="completed",
        item=SubTask(
            question="Review",
            metadata={
                "required_for_completion": True,
                "verification_checks": deepcopy(checks),
                "verification_events": events,
            },
        ),
        result=SubAgentResult(
            question="Review",
            role_id="researcher",
            final_content="report",
            success=True,
            job_id=job_id,
            metadata={"stopped_by": stop},
        ),
    )


async def test_recheck_closes_old_gap_without_erasing_timeout():
    bus = AgentBus()
    add_job(bus, "j1", [binding()], stop="wall_deadline")
    add_job(bus, "j2", [binding(replaces="j1")], verdicts=["pass"])
    wind = await wind_down_team(bus=bus, task_id="run", wait_s=0)
    assert wind.run_status == "complete"
    old = wind.job_outcomes[0]
    assert old["status"] == "incomplete"
    assert old["coverage_status"] == "complete"
    assert old["coverage_resolved_by"][0]["job_id"] == "j2"
    out = finalize_team_report(
        "The checked amount is 50.",
        source="agent",
        answer_status="complete",
        stopped_by="final_answer",
        wind_down=wind.as_dict(),
    )
    assert out["answer_status"] == "complete"
    assert out["report_contract"]["verification"] == "passed_for_declared_checks"
    assert "not the entire report" in out["final_answer"]


async def test_verification_board_item_cannot_resolve_before_its_bound_check_passes():
    from frontier_agent.core.execution_context import (
        ExecutionScope,
        reset_current_execution_scope,
        set_current_execution_scope,
    )
    from frontier_agent.core.runtime import registry
    from plugins.tools._bus_scope import SWARM_SCOPE_KEY
    from plugins.tools.task_board import add_task, clear_board, snapshot_tasks, update_task

    bus = AgentBus()
    saved = registry.snapshot()
    registry.register(AgentBus, bus)
    # Web inherits planning_mode=false from the team profile. The coordinator's
    # runtime marker, not Planning Mode, must therefore activate this gate.
    token = set_current_execution_scope(
        ExecutionScope(task_id="run", metadata={SWARM_SCOPE_KEY: object()})
    )
    try:
        await add_task.func([{
            "description": "核验所有提炼观点",
            "verification_requirements": [{
                "check_id": "amount",
                "criterion": "Recompute the amount",
            }],
        }])
        assert snapshot_tasks("run")[0]["verification_required"] is True
        assert snapshot_tasks("run")[0]["verification_requirements"] == [{
            "check_id": "amount",
            "criterion": "Recompute the amount",
        }]

        rejected = await update_task.func([{"id": "t1", "resolution": "resolved"}])
        assert rejected.startswith("Error:")
        assert "尚未登记版本绑定检查" in rejected
        assert snapshot_tasks("run")[0]["resolution"] == "open"

        add_job(bus, "j1", [binding()], verdicts=["pass"])
        accepted = await update_task.func([{"id": "t1", "resolution": "resolved"}])
        assert "errors:" not in accepted
        assert snapshot_tasks("run")[0]["resolution"] == "resolved"
    finally:
        clear_board("run")
        reset_current_execution_scope(token)
        registry.restore(saved)


async def test_planned_verification_gets_a_stable_default_check_identity():
    from frontier_agent.core.execution_context import (
        ExecutionScope,
        reset_current_execution_scope,
        set_current_execution_scope,
    )
    from plugins.tools._bus_scope import SWARM_SCOPE_KEY
    from plugins.tools.task_board import add_task, clear_board, snapshot_tasks

    token = set_current_execution_scope(
        ExecutionScope(task_id="planned-run", metadata={SWARM_SCOPE_KEY: object()})
    )
    try:
        await add_task.func([{"description": "核验关键数字"}])
        assert snapshot_tasks("planned-run")[0]["verification_requirements"] == [{
            "check_id": "t1.required",
            "criterion": "核验关键数字",
        }]
    finally:
        clear_board("planned-run")
        reset_current_execution_scope(token)


async def test_duplicate_plan_item_can_be_enriched_with_explicit_checks():
    from frontier_agent.core.execution_context import (
        ExecutionScope,
        reset_current_execution_scope,
        set_current_execution_scope,
    )
    from plugins.tools._bus_scope import SWARM_SCOPE_KEY
    from plugins.tools.task_board import add_task, clear_board, snapshot_tasks

    token = set_current_execution_scope(
        ExecutionScope(task_id="enriched-run", metadata={SWARM_SCOPE_KEY: object()})
    )
    try:
        await add_task.func([{"description": "核验关键数字"}])
        await add_task.func([{
            "description": "核验关键数字",
            "verification_requirements": [{
                "check_id": "amount.total", "criterion": "按原始行复算总额",
            }],
        }])

        assert snapshot_tasks("enriched-run")[0]["verification_requirements"] == [{
            "check_id": "amount.total", "criterion": "按原始行复算总额",
        }]
    finally:
        clear_board("enriched-run")
        reset_current_execution_scope(token)


async def test_verification_task_gate_does_not_change_single_agent_board_semantics():
    from frontier_agent.core.execution_context import (
        ExecutionScope,
        reset_current_execution_scope,
        set_current_execution_scope,
    )
    from plugins.tools.task_board import add_task, clear_board, snapshot_tasks, update_task

    token = set_current_execution_scope(ExecutionScope(task_id="single-run"))
    try:
        await add_task.func([{"description": "Verify the requested value"}])
        reply = await update_task.func([{"id": "t1", "resolution": "resolved"}])

        assert "errors:" not in reply
        assert snapshot_tasks("single-run")[0]["resolution"] == "resolved"
    finally:
        clear_board("single-run")
        reset_current_execution_scope(token)


@pytest.mark.parametrize("verdict", ["fail", "unchecked", None])
async def test_execution_success_is_not_a_check_pass(verdict):
    bus = AgentBus()
    add_job(bus, "j1", [binding()], verdicts=[verdict] if verdict else [])
    wind = await wind_down_team(bus=bus, task_id="run", wait_s=0)
    assert wind.run_status == "partial"
    out = finalize_team_report(
        "Only a draft is available.",
        source="agent",
        answer_status="complete",
        stopped_by="final_answer",
        wind_down=wind.as_dict(),
    )
    assert out["answer_status"] == "partial"


async def test_changed_version_only_invalidates_affected_check_and_preserves_late_old_result():
    bus = AgentBus()
    add_job(bus, "j1", [binding(), binding("units")], verdicts=["pass", "pass"])
    add_job(bus, "j2", [binding(version="v2", replaces="j1")], stop="wall_deadline")
    wind = await wind_down_team(bus=bus, task_id="run", wait_s=0)
    checks = {c["check_id"]: c for c in wind.verification["checks"]}
    assert wind.run_status == "partial"
    assert checks["amount"]["verdict"] == "unchecked"
    assert checks["units"]["verdict"] == "pass"
    add_job(bus, "j3", [binding(version="v2", replaces="j2")], verdicts=["pass"])
    wind = await wind_down_team(bus=bus, task_id="run", wait_s=0)
    assert wind.run_status == "complete"
    assert len(wind.verification["checks"][0]["attempts"]) == 3


async def test_rollback_does_not_resurrect_old_pass():
    bus = AgentBus()
    add_job(bus, "j1", [binding()], verdicts=["pass"])
    add_job(bus, "j2", [binding(version="v2", replaces="j1")])
    back = binding(replaces="j2")
    back["revision_reason"] = "revert to original"
    add_job(bus, "j3", [back])
    wind = await wind_down_team(bus=bus, task_id="run", wait_s=0)
    assert wind.verification["checks"][0]["verdict"] == "unchecked"


async def test_partial_results_survive_timeout_and_targeted_recheck():
    bus = AgentBus()
    add_job(bus, "j1", [binding(), binding("units")], stop="wall_deadline", verdicts=["pass"])
    wind = await wind_down_team(bus=bus, task_id="run", wait_s=0)
    assert wind.verification["status"] == "partial"
    assert wind.run_status == "partial"
    add_job(bus, "j2", [binding("units", replaces="j1")], verdicts=["pass"])
    wind = await wind_down_team(bus=bus, task_id="run", wait_s=0)
    assert wind.run_status == "complete"
    assert wind.job_outcomes[0]["status"] == "incomplete"
    add_job(bus, "research", [], stop="wall_deadline")
    wind = await wind_down_team(bus=bus, task_id="run", wait_s=0)
    assert wind.run_status == "partial"  # ordinary research gaps are independent


async def test_optional_failed_check_is_disclosed_without_downgrading_required_work():
    bus = AgentBus()
    optional = binding()
    optional["required"] = False
    add_job(bus, "optional", [optional], verdicts=["fail"])
    bus._jobs["optional"].item.metadata["required_for_completion"] = False
    wind = await wind_down_team(bus=bus, task_id="run", wait_s=0)
    assert wind.run_status == "complete"
    assert wind.verification["checks"][0]["verdict"] == "fail"
    assert wind.verification["status"] == "not_assessed"


async def test_same_version_new_failure_overrides_old_pass():
    bus = AgentBus()
    add_job(bus, "old", [binding()], verdicts=["pass"])
    add_job(bus, "new", [binding(replaces="old")], verdicts=["fail"])
    wind = await wind_down_team(bus=bus, task_id="run", wait_s=0)
    assert wind.run_status == "partial"
    assert wind.verification["checks"][0]["verdict_job_id"] == "new"
    assert wind.verification["status"] == "failed"


def test_persistence_failure_is_not_closed_by_a_pass():
    jobs = [
        {
            "job_id": "j1",
            "status": "failed",
            "reason": "checkpoint_error",
            "verification_checks": [binding()],
            "verification_events": [
                {
                    "check_id": "amount",
                    "binding_id": "v1",
                    "verdict": "pass",
                }
            ],
        }
    ]
    project_checks(jobs)
    assert jobs[0]["coverage_status"] == "incomplete"


def make_bound(tmp_path):
    bus = AgentBus()
    add_job(bus, "draft", [])
    add_job(bus, "source", [])
    spec = VerificationCheck(
        check_id="amount",
        work_item_id="t1",
        criterion="Recompute the amount",
        subject={"job_id": "draft"},
        evidence=[{"job_id": "source"}],
    )
    bound, prompt = bind_checks(
        [spec],
        bus=bus,
        task_id="run",
        work_item_ids={"t1"},
        required=True,
        outputs_root=tmp_path,
    )
    assert "SOURCE source" in prompt
    return bus, spec, bound


def verdict_for(check, **kwargs):
    return {
        "check_id": check["check_id"],
        "binding_id": check["binding_id"],
        "verdict": "pass",
        "method": "recompute",
        "detail": "42 + 8 = 50",
        "evidence_keys": ["source"],
        **kwargs,
    }


@pytest.mark.parametrize(
    "change", ["stale", "criterion", "work_item", "optional", "version", "crossrun"]
)
def test_dispatch_rejects_invalid_recheck_relationship(tmp_path, change):
    bus, spec, bound = make_bound(tmp_path)
    add_job(bus, "review", bound)
    spec.replaces_job_id = "review"
    required = True
    if change == "stale":
        spec.replaces_job_id = "older"
    elif change == "criterion":
        spec.criterion = "Only inspect formatting"
    elif change == "work_item":
        spec.work_item_id = "t2"
    elif change == "optional":
        required = False
    elif change == "version":
        add_job(bus, "newdraft", [])
        spec.subject.job_id = "newdraft"
    else:
        bus._jobs["source"].parent_task_id = "other-run"
    with pytest.raises(ValueError):
        bind_checks(
            [spec],
            bus=bus,
            task_id="run",
            work_item_ids={"t1", "t2"},
            required=required,
            outputs_root=tmp_path,
        )


def test_binding_versions_are_content_derived_and_scope_stable(tmp_path):
    bus, spec, bound = make_bound(tmp_path)
    assert len(bound[0]["binding_id"]) == 64
    add_job(bus, "review", bound)
    spec.replaces_job_id = "review"
    same, _ = bind_checks(
        [spec], bus=bus, task_id="run", work_item_ids={"t1"}, required=True, outputs_root=tmp_path
    )
    assert same[0]["binding_id"] == bound[0]["binding_id"]
    add_job(bus, "newdraft", [])
    spec.subject.job_id = "newdraft"
    spec.revision_reason = "corrected candidate"
    new, _ = bind_checks(
        [spec], bus=bus, task_id="run", work_item_ids={"t1"}, required=True, outputs_root=tmp_path
    )
    assert new[0]["binding_id"] != bound[0]["binding_id"]


@pytest.mark.parametrize(
    "invalid",
    [
        {"binding_id": "0" * 64},
        {"check_id": "other"},
        {"evidence_keys": []},
        {"evidence_keys": ["unbound"]},
        {"method": " "},
        {"verdict": "probably"},
    ],
)
def test_submission_validation_is_atomic(tmp_path, invalid):
    _, _, bound = make_bound(tmp_path)
    metadata = {"verification_checks": bound}
    token = set_verification_scope("review", metadata)
    try:
        with pytest.raises(ValueError):
            validate_results([verdict_for(bound[0], **invalid)])
        with pytest.raises(ValueError):
            validate_results([verdict_for(bound[0]), verdict_for(bound[0], **invalid)])
        assert metadata["verification_events"] == []
        accepted = validate_results([verdict_for(bound[0])])
        assert metadata["verification_events"] == []
        commit_results(accepted)
        assert metadata["verification_events"][0]["job_id"] == "review"
    finally:
        reset_verification_scope(token)


def test_handoff_bytes_and_provenance_are_checked_at_dispatch_and_submission(tmp_path):
    from plugins.tools._handoff import publish_file, reset_handoff_scope, set_handoff_scope

    workspace, outputs = tmp_path / "workspace", tmp_path / "outputs"
    workspace.mkdir()
    outputs.mkdir()
    (workspace / "source.txt").write_text("42 + 8 = 50")
    handoff = set_handoff_scope(
        producer="source", job_id="source", workspace_root=workspace, outputs_root=outputs
    )
    try:
        manifest = publish_file("/workspace/source.txt")
        bus, spec, _ = make_bound(outputs)
        spec.evidence[0].ref = manifest["ref"]
        with pytest.raises(ValueError, match="not submitted"):
            bind_checks(
                [spec],
                bus=bus,
                task_id="run",
                work_item_ids={"t1"},
                required=True,
                outputs_root=outputs,
            )
        bus._jobs["source"].result.metadata["report_attachments"] = [manifest["ref"]]
        bound, _ = bind_checks(
            [spec],
            bus=bus,
            task_id="run",
            work_item_ids={"t1"},
            required=True,
            outputs_root=outputs,
        )
        assert bound[0]["evidence"][0]["sha256"] == manifest["sha256"]
        metadata = {"verification_checks": bound}
        token = set_verification_scope("review", metadata)
        try:
            result = verdict_for(bound[0], evidence_keys=[bound[0]["evidence"][0]["key"]])
            assert validate_results([result])
            file = outputs / manifest["ref"].removeprefix("/outputs/")
            file.chmod(0o600)
            file.write_text("changed behind the immutable handoff")
            with pytest.raises(ValueError, match="digest"):
                validate_results([result])
            assert metadata["verification_events"] == []
        finally:
            reset_verification_scope(token)
    finally:
        reset_handoff_scope(handoff)


async def test_real_dispatch_timeout_recheck_race_and_snapshot(tmp_path, monkeypatch):
    import asyncio
    import json

    from frontier_agent.components.agent_bus.models import SubAgentRuntimeSpec
    from frontier_agent.core.execution_context import (
        ExecutionScope,
        reset_current_execution_scope,
        set_current_execution_scope,
    )
    from frontier_agent.core.loop_types import AgentLoopResult
    from frontier_agent.core.messages import assistant_msg, system_msg, user_msg
    from frontier_agent.core.runtime import registry
    from plugins.tools._bus_scope import SWARM_SCOPE_KEY
    from plugins.tools.assign_task import agent_team_assign_task
    from plugins.tools.submit_report import submit_report
    from plugins.tools.task_board import add_task, clear_board
    from workflows.agent_team.subagent_runtime import (
        SwarmSubagentRuntime,
        build_swarm_session_runtime_spec,
    )

    bus, spec, _ = make_bound(tmp_path)
    bus.configure_task_result_store("run", tmp_path / "snapshots")
    runtime = SwarmSubagentRuntime(sandbox_mode="native")
    context = build_swarm_session_runtime_spec(runtime, session_name="reviewer", task_id="run")
    calls = 0

    async def loop(**kwargs):
        nonlocal calls
        calls += 1
        prompt = kwargs["user_message"]
        checks, _ = json.JSONDecoder().raw_decode(prompt.split("# Bound verification checks\n")[1])
        result = await submit_report.func(
            "Checked the first item",
            finish=calls != 1,
            verification_results=[verdict_for(checks[0])],
        )
        assert isinstance(result, str), result
        if calls == 1:
            await asyncio.Event().wait()  # cancelled by the actual per-job deadline
        return AgentLoopResult(
            messages=[system_msg("test"), user_msg(prompt), assistant_msg("Checked")],
            final_content="Checked",
            stopped_by="final_answer",
        )

    monkeypatch.setattr("frontier_agent.components.agent_bus.bus.run_agent_loop", loop)
    await bus.create_session(
        task_id="run",
        name="reviewer",
        role_id="researcher",
        system_prompt="test",
        tools_override=[],
        llm_override=object(),
        runtime_spec=SubAgentRuntimeSpec(
            context_setup=context.context_setup,
            run_timeout_builder=lambda _item: 0.15,
        ),
    )
    saved = registry.snapshot()
    registry.register(AgentBus, bus)
    token = set_current_execution_scope(
        ExecutionScope(
            task_id="run",
            metadata={SWARM_SCOPE_KEY: runtime},
        )
    )
    try:
        await add_task.func(tasks=[{"description": "Recompute"}])
        units = spec.model_copy(update={"check_id": "units"})
        first = await agent_team_assign_task.func(
            tasks=[
                {
                    "agent": "reviewer",
                    "prompt": "Check both items",
                    "verification_checks": [spec.model_dump(), units.model_dump()],
                }
            ]
        )
        assert not first.startswith("Error"), first
        assert await bus.wait_any_session("run", timeout=2)
        old = bus.list_task_jobs("run")[-1]
        assert old.result.success is False
        assert len(old.item.metadata["verification_events"]) == 1
        snapshot = json.loads(next((tmp_path / "snapshots").glob("*.json")).read_text())
        assert snapshot["assignment_metadata"]["verification_events"][0]["verdict"] == "pass"
        units.replaces_job_id = old.job_id
        assignment = {
            "agent": "reviewer",
            "prompt": "Finish remaining check",
            "verification_checks": [units.model_dump()],
        }
        # Two racing rechecks of one predecessor cannot both establish a new head.
        results = await asyncio.gather(
            *[agent_team_assign_task.func(tasks=[assignment]) for _ in range(2)]
        )
        assert sum(r.startswith("Error") for r in results) == 1, results
        assert await bus.wait_any_session("run", timeout=2)
        wind = await wind_down_team(bus=bus, task_id="run", wait_s=0)
        assert wind.run_status == "complete"
        assert wind.verification["status"] == "passed_for_declared_checks"
        # The serialized Reporter boundary projects the same result.
        out = finalize_team_report(
            "Both declared checks passed.",
            source="agent",
            answer_status="complete",
            stopped_by="final_answer",
            wind_down=json.loads(json.dumps(wind.as_dict())),
        )
        assert out["report_contract"]["kind"] == "complete"
    finally:
        await bus.cleanup_task("run")
        clear_board("run")
        reset_current_execution_scope(token)
        registry.restore(saved)


async def test_checkpoint_tool_keeps_loop_running_then_terminal_report_finishes(tmp_path):
    from frontier_agent.core.loop_types import TurnContext
    from frontier_agent.core.runtime.loop.tool_exec import execute_tools
    from plugins.tools.submit_report import submit_report
    from workflows._shared.research.observers.finalize_answer_observer import FinalizeAnswerObserver

    _, _, bound = make_bound(tmp_path)
    metadata = {"verification_checks": bound}
    token = set_verification_scope("review", metadata)
    observer = FinalizeAnswerObserver(tool_names=["submit_report"])
    ctx = TurnContext(
        turn=1,
        max_turns=3,
        task_id="run",
        role_id="swarm_sub",
        ai_text="",
        thinking="",
        tool_calls=[],
        messages=[],
        usage=None,
        metadata={},
    )
    try:
        args = {
            "content": "Amount checked",
            "finish": False,
            "verification_results": [verdict_for(bound[0])],
        }
        result = (
            await execute_tools(
                [{"name": "submit_report", "args": args, "id": "c1"}],
                {"submit_report": submit_report},
                timeout=5,
                turn=1,
                count_offset=0,
            )
        )[0]
        assert not result.is_error, result.result
        await observer.on_tool_result(ctx, result)
        assert await observer.on_turn_end(ctx) is None
        assert len(metadata["verification_events"]) == 1
        assert "final_answer" not in ctx.metadata
        result = (
            await execute_tools(
                [{"name": "submit_report", "args": {"content": "Done"}, "id": "c2"}],
                {"submit_report": submit_report},
                timeout=5,
                turn=2,
                count_offset=0,
            )
        )[0]
        await observer.on_tool_result(ctx, result)
        assert (await observer.on_turn_end(ctx)).stop_reason == "final_answer"
    finally:
        reset_verification_scope(token)
