"""Recorded 17dc failure shapes at dispatch, recovery and reusable-session seams."""

import pytest

from frontier_agent.core.loop_types import AgentLoopResult
from frontier_agent.core.messages import assistant_msg, user_msg
from plugins.tools._verification import VerificationCheck, bind_checks
from plugins.tools.assign_task import agent_team_assign_task
from plugins.tools.task_board import add_task
from tests.test_agent_team_verification import add_job, binding, planned_items
from tests.test_team_atomic_delivery import delivery_run as _delivery_run
from tests.test_team_atomic_delivery import prepare, turn_context
from tests.test_team_verification_admission import admission_run as _admission_run
from workflows.agent_team.delivery import TeamDeliveryObserver

admission_run = _admission_run
delivery_run = _delivery_run


async def test_board_identity_is_resolved_before_dispatch(admission_run):
    bus, _ = admission_run
    await add_task.func([{
        "description": "Review amount", "kind": "verification",
        "verification_requirements": [{"check_id": "amount", "criterion": "Recompute the amount"}],
    }])
    add_job(bus, "source", [])
    receipt = await agent_team_assign_task.func(tasks=[{
        "agent": "reviewer", "prompt": "Check this passage",
        "verification_checks": [{"check_id": "amount", "subject": {"text": "The amount is 50."},
                                 "evidence": [{"job_id": "source"}]}],
    }])
    assert not receipt.startswith("Error"), receipt
    dispatched = bus.list_task_jobs("run")[-1].item.metadata
    assert dispatched["work_item_ids"] == ["t1"]
    check = dispatched["verification_checks"][0]
    assert check["criterion"] == "Recompute the amount"
    assert check["work_item_id"] == "t1"


async def test_explicit_wrong_criterion_still_rejected(admission_run):
    bus, _ = admission_run
    await add_task.func([{"description": "Review", "kind": "verification",
                         "verification_requirements": [{"check_id": "amount", "criterion": "Original"}]}])
    add_job(bus, "source", [])
    reply = await agent_team_assign_task.func(tasks=[{
        "agent": "reviewer", "prompt": "Check", "verification_checks": [{
            "check_id": "amount", "work_item_id": "t1", "criterion": "Silently weaken",
            "subject": {"text": "candidate"}, "evidence": [{"job_id": "source"}],
        }],
    }])
    assert "Error" in reply or "errors:" in reply
    assert len(bus.list_task_jobs("run")) == 1


async def test_empty_dispatch_returns_real_board_and_source_ids(admission_run):
    bus, _ = admission_run
    await add_task.func([{"description": "Review amount", "kind": "verification",
                         "verification_requirements": [{"check_id": "amount", "criterion": "Check"}]}])
    add_job(bus, "source", [])
    reply = await agent_team_assign_task.func(tasks=[])
    assert reply.startswith("Error")
    assert all(key in reply for key in ("reviewer", '"t1"', '"amount"', '"source"'))
    assert len(bus.list_task_jobs("run")) == 1


async def test_unfinished_attempt_does_not_consume_semantic_repair(delivery_run, monkeypatch):
    bus, budget = delivery_run
    await prepare(bus, "unchecked")
    add_job(bus, "j1", [binding()], stop="llm_error")
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 600)
    observer = TeamDeliveryObserver(budget)
    await observer.on_before_llm(turn_context(turn=21))
    add_job(bus, "review2", [binding(version="v2", replaces="j1")], verdicts=["fail"])
    iv = await observer.on_before_llm(turn_context(turn=25))
    assert not observer.active, "an uncompleted first review consumed the only useful repair"
    assert "review2" in " ".join(iv.inject_messages)
    add_job(bus, "review3", [binding(version="v3", replaces="review2")], verdicts=["fail"])
    await observer.on_before_llm(turn_context(turn=26))
    assert observer.active, "two effective failed reviews must still bound recovery"


async def test_new_source_reoffers_undispatched_check(delivery_run):
    bus, budget = delivery_run
    await add_task.func([{"description": "Review", "kind": "verification",
                         "verification_requirements": [{"check_id": "amount", "criterion": "Check"}]}])
    from plugins.tools.task_board import snapshot_tasks

    observer = TeamDeliveryObserver(budget)
    add_job(bus, "source1", [])
    first = observer._pending_verification_prompt(bus, "run", snapshot_tasks("run"))
    assert first is not None
    assert observer._pending_verification_prompt(bus, "run", snapshot_tasks("run")) is None
    add_job(bus, "source2", [])
    second = observer._pending_verification_prompt(bus, "run", snapshot_tasks("run"))
    assert second is not None, "one early incomplete evidence packet permanently silenced readiness"
    assert "source2" in " ".join(second.inject_messages)


async def test_verification_context_excludes_old_tasks_but_research_keeps_history(
    admission_run, monkeypatch,
):
    bus, _ = admission_run
    captured = []

    async def loop(**kwargs):
        captured.append(str(kwargs["initial_messages"]))
        messages = [*kwargs["initial_messages"], user_msg(kwargs["user_message"]), assistant_msg("done")]
        return AgentLoopResult(messages=messages, final_content="done", stopped_by="final_answer")

    monkeypatch.setattr("frontier_agent.components.agent_bus.bus.run_agent_loop", loop)
    session = bus.list_sessions_for_task("run")[0]
    for prompt, metadata in [
        ("OLD_CANDIDATE_AND_EVIDENCE", {}),
        ("CURRENT_CANDIDATE_AND_EVIDENCE", {"verification_checks": [{"check_id": "amount"}]}),
        ("RESEARCH_FOLLOWUP", {}),
    ]:
        job_id = await bus.submit_task_to_session(session.session_id, prompt, task_metadata=metadata)
        await bus.list_task_jobs("run")[-1].task
        assert bus.get_job_result("run", job_id) is not None
    assert "OLD_CANDIDATE_AND_EVIDENCE" not in captured[1]
    assert "OLD_CANDIDATE_AND_EVIDENCE" in captured[2]
    assert "CURRENT_CANDIDATE_AND_EVIDENCE" in captured[2]


@pytest.mark.parametrize("field,value", [("work_item_id", "wrong"), ("criterion", "wrong")])
def test_bind_checks_never_overwrites_explicit_board_conflicts(tmp_path, field, value):
    from frontier_agent.components.agent_bus import AgentBus

    bus = AgentBus()
    add_job(bus, "source", [])
    spec = VerificationCheck.model_validate({
        "check_id": "amount", "work_item_id": "t1", "criterion": "Recompute the amount",
        "subject": {"text": "candidate"}, "evidence": [{"job_id": "source"}], field: value,
    })
    with pytest.raises(ValueError):
        bind_checks([spec], bus=bus, task_id="run", work_items=planned_items(),
                    required=True, outputs_root=tmp_path)


def test_recheck_carries_prior_defects_without_old_candidate(tmp_path):
    from frontier_agent.components.agent_bus import AgentBus

    bus = AgentBus()
    add_job(bus, "source", [])
    spec = VerificationCheck(check_id="amount", subject={"text": "OLD_CANDIDATE"},
                             evidence=[{"job_id": "source"}])
    checks, _ = bind_checks([spec], bus=bus, task_id="run", work_items=planned_items(),
                           required=True, outputs_root=tmp_path)
    add_job(bus, "first", checks, verdicts=["fail"])
    bus.list_task_jobs("run")[-1].item.metadata["verification_events"][0]["unresolved_issues"] = [
        "Missing retention assumption",
    ]
    revision = VerificationCheck.model_validate({**spec.model_dump(),
        "subject": {"text": "CURRENT_CANDIDATE"}, "replaces_job_id": "first",
        "revision_kind": "subject", "revision_reason": "Restored assumptions"})
    _, prompt = bind_checks([revision], bus=bus, task_id="run", work_items=planned_items(),
                            required=True, outputs_root=tmp_path)
    assert "Missing retention assumption" in prompt
    assert "CURRENT_CANDIDATE" in prompt
    assert "OLD_CANDIDATE" not in prompt
