"""A failed completed verifier must leave room to correct and recheck its subject."""

from dataclasses import replace

import pytest

from plugins.tools._verification import VerificationCheck, bind_checks, project_bus_checks
from plugins.tools.task_board import snapshot_tasks, update_task
from tests.test_agent_team_verification import add_job, binding
from tests.test_team_atomic_delivery import delivery_run as _delivery_run
from tests.test_team_atomic_delivery import prepare, turn_context
from workflows.agent_team.delivery import TeamDeliveryObserver, deliver_answer

delivery_run = _delivery_run


@pytest.mark.parametrize("verdict", ["fail", "unchecked"])
async def test_completed_defect_gets_correction_before_delivery(delivery_run, monkeypatch, verdict):
    bus, budget = delivery_run
    await prepare(bus, verdict)
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 600)
    observer = TeamDeliveryObserver(budget)
    ctx = turn_context()
    intervention = await observer.on_before_llm(ctx)
    assert not observer.active, "a finished failed check is not a reason to close coordination"
    assert intervention is not None
    assert intervention.allowed_tool_names != ("deliver_answer",)
    prompt = " ".join(intervention.inject_messages)
    assert "replaces_job_id" in prompt and "j1" in prompt and "amount" in prompt


@pytest.mark.parametrize("now,verification_deadline", [(700, None), (600, 680), (790, None)])
async def test_repair_respects_verifier_and_publication_reserves(
    delivery_run,
    monkeypatch,
    now,
    verification_deadline,
):
    bus, budget = delivery_run
    await prepare(bus, "fail")
    budget = replace(budget, verification_deadline_s=verification_deadline)
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: now)
    observer = TeamDeliveryObserver(budget)
    iv = await observer.on_before_llm(turn_context())
    assert observer.active
    assert iv.allowed_tool_names == ("deliver_answer",)


async def test_repair_cannot_loop_without_dispatch(delivery_run, monkeypatch):
    bus, budget = delivery_run
    await prepare(bus, "fail")
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 600)
    observer = TeamDeliveryObserver(budget)
    for turn in [21, 22, 23]:
        await observer.on_before_llm(turn_context(turn=turn))
        assert not observer.active
    await observer.on_before_llm(turn_context(turn=24))
    assert observer.active


@pytest.mark.parametrize("verdict", ["pass", "fail", "unchecked"])
async def test_one_recheck_finishes_without_reusing_previous_verdict(
    delivery_run,
    monkeypatch,
    verdict,
):
    bus, budget = delivery_run
    await prepare(bus, "fail")
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 600)
    observer = TeamDeliveryObserver(budget)
    await observer.on_before_llm(turn_context())
    add_job(bus, "recheck", [binding(version="v2", replaces="j1")], verdicts=[verdict])
    await observer.on_before_llm(turn_context(turn=22))
    assert observer.active
    assert project_bus_checks(bus, "run")["checks"][0]["verdict"] == verdict


async def test_running_recheck_is_not_preempted(delivery_run, monkeypatch):
    bus, budget = delivery_run
    await prepare(bus, "fail")
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 600)
    observer = TeamDeliveryObserver(budget)
    await observer.on_before_llm(turn_context())
    add_job(bus, "recheck", [binding(version="v2", replaces="j1")])
    bus._jobs["recheck"].status = "running"
    assert await observer.on_before_llm(turn_context(turn=25)) is None
    assert not observer.active


@pytest.mark.parametrize("stop", ["blocked", "publishing", "last_turn"])
async def test_repair_does_not_reopen_closed_work_or_last_turn(delivery_run, monkeypatch, stop):
    bus, budget = delivery_run
    await prepare(bus, "fail")
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 600)
    if stop == "blocked":
        await update_task.func(
            [
                {
                    "id": "t1",
                    "resolution": "blocked",
                    "notes": "Evidence unavailable",
                    "gap": "No source",
                }
            ]
        )
    elif stop == "publishing":
        budget.state["phase"] = "publishing"
    ctx = turn_context(turn=199 if stop == "last_turn" else 21)
    iv = await TeamDeliveryObserver(budget).on_before_llm(ctx)
    assert iv.allowed_tool_names == ("deliver_answer",)


async def test_repaired_publication_must_use_the_checked_passage(delivery_run, tmp_path):
    bus, _ = delivery_run
    await prepare(bus, "fail")
    add_job(bus, "source", [])
    text = "The September release has this result; inheritance by October is unverified."
    spec = VerificationCheck(
        check_id="amount",
        work_item_id="t1",
        criterion="Recompute the amount",
        subject={"text": text},
        evidence=[{"job_id": "source"}],
        publication_excerpt=True,
        replaces_job_id="j1",
        revision_kind="subject",
        revision_reason="Restrict the release attribution",
    )
    checks, _ = bind_checks(
        [spec],
        bus=bus,
        task_id="run",
        work_items=snapshot_tasks("run"),
        required=True,
        outputs_root=tmp_path,
    )
    add_job(bus, "recheck", checks, verdicts=["pass"])
    updates = [{"id": "t1", "resolution": "resolved", "notes": "Corrected scope passed"}]
    with pytest.raises(ValueError, match="checked publication excerpt"):
        await deliver_answer.func(content="The October release has this result.", updates=updates)
    assert snapshot_tasks("run")[0]["resolution"] == "in_progress"
    await deliver_answer.func(content="Findings: " + text, updates=updates)
    assert snapshot_tasks("run")[0]["resolution"] == "resolved"
