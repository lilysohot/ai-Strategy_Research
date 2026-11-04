"""Quotation fidelity alone does not establish version or deployment applicability."""

import pytest

from plugins.tools._verification import (
    VerificationCheck,
    bind_checks,
    project_bus_checks,
    reset_verification_scope,
    set_verification_scope,
    validate_results,
)
from tests.test_agent_team_verification import add_job, make_bound, planned_items, verdict_for

DIMENSIONS = ("entity", "version", "date", "units", "conditions", "attribution")


def assessment(**changes):
    comparisons = {
        key: {"status": "match", "detail": f"source paragraph 1 agrees with the candidate's {key}"}
        for key in DIMENSIONS
    }
    comparisons.update(changes)
    return comparisons


def test_factual_pass_cannot_omit_applicability_assessment(tmp_path):
    _, _, checks = make_bound(tmp_path)
    checks[0]["factual_scope"] = True
    token = set_verification_scope("review", {"verification_checks": checks})
    try:
        with pytest.raises(ValueError, match="scope_assessment"):
            validate_results([verdict_for(checks[0])])
    finally:
        reset_verification_scope(token)


@pytest.mark.parametrize("dimension", DIMENSIONS)
@pytest.mark.parametrize("status", ["mismatch", "unknown"])
def test_scope_gaps_cannot_be_waived_as_pass(tmp_path, dimension, status):
    _, _, checks = make_bound(tmp_path)
    checks[0]["factual_scope"] = True
    token = set_verification_scope("review", {"verification_checks": checks})
    result = verdict_for(
        checks[0],
        scope_assessment=assessment(
            **{
                dimension: {
                    "status": status,
                    "detail": "The cited source does not establish this scope",
                },
            }
        ),
    )
    try:
        with pytest.raises(ValueError, match="scope mismatch or unknown"):
            validate_results([result])
        result["verdict"] = "fail" if status == "mismatch" else "unchecked"
        assert validate_results([result])[0]["verdict"] == result["verdict"]
    finally:
        reset_verification_scope(token)


@pytest.mark.parametrize(
    "dimension,detail",
    [
        (
            "version",
            "Source describes the September release; October inheritance is not documented",
        ),
        (
            "conditions",
            "20–25 TB per accelerator assumes a specific cache-retention and workload regime",
        ),
        (
            "date",
            "An undated unexamined record prevents asserting the latest release in this corpus",
        ),
    ],
)
def test_audited_defects_remain_failed_in_persisted_projection(tmp_path, dimension, detail):
    bus, _, checks = make_bound(tmp_path)
    checks[0]["factual_scope"] = True
    add_job(bus, "review", checks)
    bad = verdict_for(
        checks[0],
        scope_assessment=assessment(
            **{
                dimension: {"status": "mismatch", "detail": detail},
            }
        ),
    )
    events = bus._jobs["review"].item.metadata["verification_events"]
    events.append({**bad, "job_id": "review"})
    assert project_bus_checks(bus, "run")["checks"][0]["verdict"] == "unchecked"
    bad["verdict"] = "fail"
    events.append({**bad, "job_id": "review"})
    assert project_bus_checks(bus, "run")["checks"][0]["verdict"] == "fail"


def test_complete_scope_pass_survives_projection(tmp_path):
    bus, _, checks = make_bound(tmp_path)
    checks[0]["factual_scope"] = True
    add_job(bus, "review", checks)
    metadata = bus._jobs["review"].item.metadata
    token = set_verification_scope("review", metadata)
    try:
        metadata["verification_events"].extend(
            validate_results(
                [
                    verdict_for(checks[0], scope_assessment=assessment()),
                ]
            )
        )
        assert project_bus_checks(bus, "run")["checks"][0]["verdict"] == "pass"
    finally:
        reset_verification_scope(token)


@pytest.mark.parametrize("flag", ["factual_scope", "publication_excerpt"])
def test_recheck_cannot_drop_scope_contract(tmp_path, flag):
    bus, spec, checks = make_bound(tmp_path)
    checks[0][flag] = True
    add_job(bus, "review", checks)
    changed = VerificationCheck.model_validate(
        {
            **spec.model_dump(),
            "subject": {"text": "A corrected, scoped passage"},
            "replaces_job_id": "review",
            "revision_kind": "subject",
            "revision_reason": "Fix scope",
        }
    )
    with pytest.raises(ValueError, match=f"cannot downgrade {flag}"):
        bind_checks(
            [changed],
            bus=bus,
            task_id="run",
            work_items=planned_items(),
            required=True,
            outputs_root=tmp_path,
        )


def test_factual_binding_records_scope_and_requires_complete_assessment(tmp_path):
    bus, spec, _ = make_bound(tmp_path)
    changed = VerificationCheck.model_validate({**spec.model_dump(), "factual_scope": True})
    checks, prompt = bind_checks(
        [changed],
        bus=bus,
        task_id="run",
        work_items=planned_items(),
        required=True,
        outputs_root=tmp_path,
    )
    assert checks[0]["factual_scope"]
    assert "scope_assessment" in prompt
    token = set_verification_scope("review", {"verification_checks": checks})
    comparisons = assessment()
    comparisons.pop("conditions")
    try:
        with pytest.raises(ValueError, match="conditions"):
            validate_results([verdict_for(checks[0], scope_assessment=comparisons)])
    finally:
        reset_verification_scope(token)


def test_reporter_cannot_certify_a_rewritten_publication_excerpt(tmp_path):
    from workflows.agent_team.final_report import finalize_team_report

    bus, spec, _ = make_bound(tmp_path)
    passage = "This estimate applies only under the stated cache-retention assumptions."
    spec = VerificationCheck.model_validate(
        {
            **spec.model_dump(),
            "subject": {"text": passage},
            "publication_excerpt": True,
        }
    )
    checks, _ = bind_checks(
        [spec],
        bus=bus,
        task_id="run",
        work_items=planned_items(),
        required=True,
        outputs_root=tmp_path,
    )
    job = {
        "job_id": "review",
        "status": "complete",
        "required_for_completion": True,
        "verification_checks": checks,
        "verification_events": [verdict_for(checks[0])],
    }
    for content, expected in [
        (passage, []),
        ("This estimate applies to every deployment.", ["amount"]),
    ]:
        out = finalize_team_report(
            content,
            source="reporter",
            answer_status="complete",
            stopped_by="final_answer",
            wind_down={"run_status": "complete", "status": "complete", "job_outcomes": [job]},
        )
        contract = out["report_contract"]
        assert contract["publication"]["unmatched_checked_excerpts"] == expected
        if expected:
            assert out["answer_status"] == "partial"
            assert any(g["code"] == "checked_publication_excerpt_changed" for g in contract["gaps"])
        else:
            assert out["answer_status"] == "complete"
