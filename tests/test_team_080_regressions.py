"""Frozen, synthetic counterexamples from the 080/bf9 audits; no live web facts."""

import hashlib
from copy import deepcopy

import pytest

from plugins.tools._calculation_verification import calculation_targets
from plugins.tools._verification import (
    VerificationCheck,
    bind_checks,
    project_checks,
    reset_verification_scope,
    set_verification_scope,
    validate_results,
)
from plugins.tools._web_handoff import render_web_handoff
from tests.test_agent_team_verification import add_job, make_bound, planned_items, verdict_for
from tests.test_team_verification_admission import admission_run as _admission_run

admission_run = _admission_run


def test_calculation_scope_excludes_adjacent_constraints_and_qualitative_derivation():
    text = "[计算] 11-04收盘100点。用户预算150元，门槛99.5%。DERIVED：B可能达标99.8%。"
    assert calculation_targets(text) == ["100"]
    assert calculation_targets("收盘100点，涨幅2.16%。以上均为[计算]推算值。") == ["100", "2.16%"]


def dispatch(bus, spec, path):
    return bind_checks(
        [spec],
        bus=bus,
        task_id="run",
        work_items=planned_items(),
        required=True,
        outputs_root=path,
    )


def record(text, source="https://example.test/result"):
    return {
        "source": source,
        "text": text,
        "status": "success",
        "content_kind": "tool_delivered_text",
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def computed_check(tmp_path):
    bus, spec, _ = make_bound(tmp_path)
    bus._jobs["source"].result.metadata["web_evidence"] = [
        record("2026-11-05: close 110 points; daily change +10 points.")
    ]
    spec = VerificationCheck.model_validate(
        {**spec.model_dump(), "subject": {"text": "[计算] 2026-11-04 收盘100点，单日上涨2.16%。"}}
    )
    bound, _ = dispatch(bus, spec, tmp_path)
    return bus, spec, bound


def test_calculation_label_does_not_waive_missing_basis(tmp_path):
    _, _, bound = computed_check(tmp_path)
    token = set_verification_scope("review", {"verification_checks": bound})
    try:
        with pytest.raises(ValueError, match="calculation"):
            validate_results(
                [
                    verdict_for(
                        bound[0],
                        detail=(
                            "Cannot independently derive the percentage; marked calculated, so PASS."
                        ),
                    )
                ]
            )
        assert validate_results([verdict_for(bound[0], verdict="unchecked")])
    finally:
        reset_verification_scope(token)


def test_result_table_survives_repeated_background_terms():
    background = (
        "Archive 2026-11-05: sections 44, 45, 52, 2; glossary: uncalled.\n"
        + "Before election: Orion 53, Lyra 47; 35 seats contested.\n" * 50
    )
    table = (
        "Update 2026-11-05. After election results (2 uncalled):\n"
        "| Party | Before | After |\n| Orion | 53 | 44 |\n| Lyra | 45 | 52 |\n"
    )
    text = render_web_handoff(
        {"source": [record(background + table)]},
        focus_text="2026-11-05 Orion 53→44, Lyra 45→52, 2 uncalled; 35 seats contested.",
        body_budget=1150,
    )
    assert table in text
    assert "excerpt_start" in text
    assert len(text) < 2500


def test_separated_narrative_and_table_keep_exact_slices_and_headers():
    narrative = "Update 2026-11-05: Lyra won 20 contests; 2 uncalled.\n"
    table = "| Party | Before | After |\n| Lyra | 45 | 52 |\n| Orion | 53 | 44 |\n"
    original = narrative + "Background about 35 contests.\n" * 100 + table
    rendered = render_web_handoff(
        {"source": [record(original)]},
        focus_text="Update 2026-11-05 Lyra won 20, 2 uncalled; Lyra 45→52, Orion 53→44.",
        body_budget=1500,
    )
    assert narrative in rendered and table in rendered
    assert '"additional_excerpts"' in rendered
    assert len(rendered) < 2400


def test_second_wording_only_recheck_is_rejected(tmp_path):
    bus, spec, checks = make_bound(tmp_path)
    add_job(bus, "first", checks, verdicts=["fail"])
    revised = VerificationCheck.model_validate(
        {
            **spec.model_dump(),
            "subject": {"text": "The claimed amount is 50, not independently verified."},
            "replaces_job_id": "first",
            "revision_kind": "subject",
            "revision_reason": "Add limitation",
        }
    )
    checks, _ = dispatch(bus, revised, tmp_path)
    add_job(bus, "second", checks, verdicts=["fail"])
    revised = VerificationCheck.model_validate(
        {
            **revised.model_dump(),
            "subject": {"text": "The estimated amount is 50; no direct source."},
            "replaces_job_id": "second",
            "revision_reason": "Relabel as estimate",
        }
    )
    with pytest.raises(ValueError, match="recheck budget"):
        dispatch(bus, revised, tmp_path)


def calculation(value="100", expression="close - change"):
    quote = "2026-11-05: close 110 points; daily change +10 points."
    return {
        "value": value,
        "expression": expression,
        "inputs": {
            name: {
                "value": number,
                "source_key": "source",
                "source": "https://example.test/result",
                "quote": quote,
                "as_of": "2026-11-05",
            }
            for name, number in [("close", "110"), ("change", "10")]
        },
    }


def test_complete_calculation_passes_but_cannot_cover_uncomputed_percentage(tmp_path):
    bus, spec, bound = computed_check(tmp_path)
    token = set_verification_scope("review", {"verification_checks": bound})
    try:
        with pytest.raises(ValueError, match=r"2\.16%"):
            validate_results([verdict_for(bound[0], calculation_checks=[calculation()])])
    finally:
        reset_verification_scope(token)
    corrected = VerificationCheck.model_validate(
        {**spec.model_dump(), "subject": {"text": "[计算] 2026-11-04 收盘100点。"}}
    )
    bound, _ = dispatch(bus, corrected, tmp_path)
    token = set_verification_scope("review", {"verification_checks": bound})
    try:
        assert validate_results([verdict_for(bound[0], calculation_checks=[calculation()])])
    finally:
        reset_verification_scope(token)


@pytest.mark.parametrize(
    "defect", ["invented_input", "invented_quote", "wrong_date", "wrong_math", "code"]
)
def test_calculation_proofs_reject_fabricated_or_invalid_inputs(tmp_path, defect):
    bus, spec, _ = computed_check(tmp_path)
    spec = VerificationCheck.model_validate(
        {**spec.model_dump(), "subject": {"text": "[计算] 2026-11-04 收盘100点。"}}
    )
    bound, _ = dispatch(bus, spec, tmp_path)
    proof = calculation()
    if defect == "invented_input":
        proof["inputs"]["change"]["value"] = "8"
    elif defect == "invented_quote":
        proof["inputs"]["change"]["quote"] = "2026-11-05 change 10 from an imagined source"
    elif defect == "wrong_date":
        proof["inputs"]["change"]["as_of"] = "2026-11-03"
    elif defect == "wrong_math":
        proof["expression"] = "close + change"
    else:
        proof["expression"] = "__import__('os').getcwd()"
    token = set_verification_scope("review", {"verification_checks": bound})
    try:
        with pytest.raises(ValueError, match="calculation"):
            validate_results([verdict_for(bound[0], calculation_checks=[proof])])
    finally:
        reset_verification_scope(token)


def test_persisted_pass_cannot_bypass_calculation_gate(tmp_path):
    _, _, bound = computed_check(tmp_path)
    jobs = [
        {
            "job_id": "review",
            "status": "completed",
            "verification_checks": bound,
            "verification_events": [verdict_for(bound[0])],
        }
    ]
    assert project_checks(jobs)["checks"][0]["verdict"] == "unchecked"


def test_removing_calculation_label_does_not_remove_numeric_obligation(tmp_path):
    bus, spec, checks = computed_check(tmp_path)
    add_job(bus, "review", checks, verdicts=["fail"])
    revised = VerificationCheck.model_validate(
        {
            **spec.model_dump(),
            "subject": {"text": "2026-11-04 上涨2.16%。"},
            "replaces_job_id": "review",
            "revision_kind": "subject",
            "revision_reason": "Remove calculation label",
        }
    )
    bound, _ = dispatch(bus, revised, tmp_path)
    assert bound[0]["calculation_targets"] == ["2.16%"]
    token = set_verification_scope("recheck", {"verification_checks": bound})
    try:
        with pytest.raises(ValueError, match="calculation basis"):
            validate_results([verdict_for(bound[0])])
    finally:
        reset_verification_scope(token)


def test_new_evidence_cannot_exceed_total_recheck_cap(tmp_path):
    bus, spec, checks = make_bound(tmp_path)
    for index in range(4):
        add_job(bus, f"review{index}", checks, verdicts=["fail"])
        source = f"source{index}"
        add_job(bus, source, [])
        bus._jobs[source].result.metadata["web_evidence"] = [record(f"Observation {index}")]
        revised = VerificationCheck.model_validate(
            {
                **spec.model_dump(),
                "evidence": [{"job_id": source}],
                "replaces_job_id": f"review{index}",
                "revision_kind": "evidence",
                "revision_reason": "New observation",
            }
        )
        if index == 3:
            with pytest.raises(ValueError, match="four attempts"):
                dispatch(bus, revised, tmp_path)
        else:
            checks, _ = dispatch(bus, revised, tmp_path)


def test_new_tool_evidence_allows_recheck_but_renaming_does_not(tmp_path):
    bus, spec, checks = computed_check(tmp_path)
    add_job(bus, "review", checks, verdicts=["fail"])
    add_job(bus, "renamed", [])
    bus._jobs["renamed"].result.metadata = deepcopy(bus._jobs["source"].result.metadata)
    revised = VerificationCheck.model_validate(
        {
            **spec.model_dump(),
            "evidence": [{"job_id": "renamed"}],
            "replaces_job_id": "review",
            "revision_kind": "evidence",
            "revision_reason": "New input",
        }
    )
    with pytest.raises(ValueError, match="new evidence"):
        dispatch(bus, revised, tmp_path)
    bus._jobs["renamed"].result.metadata["web_evidence"].append(
        record("2026-11-03: close 98 points.", "https://example.test/previous")
    )
    assert dispatch(bus, revised, tmp_path)[0]


def test_retry_is_not_another_vote_on_completed_failure(tmp_path):
    bus, spec, checks = make_bound(tmp_path)
    add_job(bus, "review", checks, verdicts=["fail"])
    revised = VerificationCheck.model_validate(
        {**spec.model_dump(), "replaces_job_id": "review", "revision_kind": "retry"}
    )
    with pytest.raises(ValueError, match="without a verdict"):
        dispatch(bus, revised, tmp_path)


async def test_independent_checks_run_concurrently_without_queueing(admission_run, monkeypatch):
    import asyncio

    from frontier_agent.core.loop_types import AgentLoopResult
    from plugins.tools.assign_task import agent_team_assign_task
    from plugins.tools.task_board import add_task
    from workflows.agent_team.subagent_runtime import build_swarm_session_runtime_spec

    bus, runtime = admission_run
    started = set()
    both_started, release = asyncio.Event(), asyncio.Event()

    async def blocked_loop(**kwargs):
        started.add(kwargs["user_message"])
        if len(started) == 2:
            both_started.set()
        await release.wait()
        return AgentLoopResult(messages=[], final_content="unchecked", stopped_by="final_answer")

    monkeypatch.setattr("frontier_agent.components.agent_bus.bus.run_agent_loop", blocked_loop)
    await bus.create_session(
        task_id="run",
        name="reviewer2",
        role_id="researcher",
        system_prompt="review",
        tools_override=[],
        llm_override=object(),
        runtime_spec=build_swarm_session_runtime_spec(
            runtime, session_name="reviewer2", task_id="run"
        ),
    )
    await add_task.func(
        [
            {
                "description": "Review",
                "kind": "verification",
                "verification_requirements": [
                    {"check_id": key, "criterion": "Check"} for key in ["a", "b", "c"]
                ],
            }
        ]
    )
    add_job(bus, "source", [])

    def task(agent, key):
        return {
            "agent": agent,
            "prompt": "Check " + key,
            "verification_checks": [
                {
                    "check_id": key,
                    "subject": {"text": "candidate " + key},
                    "evidence": [{"job_id": "source"}],
                }
            ],
        }

    try:
        reply = await agent_team_assign_task.func(
            tasks=[task("reviewer", "a"), task("reviewer2", "b")]
        )
        assert "errors:" not in reply and not reply.startswith("Error"), reply
        await asyncio.wait_for(both_started.wait(), timeout=2)
        reply = await agent_team_assign_task.func(tasks=[task("reviewer", "c")])
        assert "verification session is busy" in reply
        assert not bus.get_session("run::reviewer").pending_tasks
        assert len(bus.list_task_jobs("run")) == 3
    finally:
        release.set()
