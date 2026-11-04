"""A correction in dispatch prose must not become a verdict on old report bytes."""

import hashlib

import pytest

from plugins.tools._verification import (
    VerificationCheck,
    bind_checks,
    project_checks,
    reset_verification_scope,
    set_verification_scope,
    validate_results,
)
from tests.test_agent_team_verification import add_job, make_bound, planned_items, verdict_for


def dispatch(bus, spec, tmp_path):
    return bind_checks(
        [spec],
        bus=bus,
        task_id="run",
        work_items=planned_items(),
        required=True,
        outputs_root=tmp_path,
    )


def test_repaired_paragraph_is_the_immutable_subject(tmp_path):
    bus, old_spec, old = make_bound(tmp_path)
    add_job(bus, "review", old, verdicts=["fail"])
    text = "L223 is a caption containing experimental settings; measured values are in prose."
    spec = VerificationCheck.model_validate(
        {
            **old_spec.model_dump(),
            "subject": {"text": text},
            "replaces_job_id": "review",
            "revision_kind": "subject",
            "revision_reason": "Correct the caption classification",
        }
    )
    bound, prompt = dispatch(bus, spec, tmp_path)
    subject = bound[0]["subject"]
    assert subject["text"] == text
    assert subject["sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert prompt.count(text) == 1
    assert bound[0]["binding_id"] != old[0]["binding_id"]
    # Submission acknowledges the actual candidate, independently of evidence IDs.
    token = set_verification_scope("recheck", {"verification_checks": bound})
    try:
        with pytest.raises(ValueError, match="subject"):
            validate_results([verdict_for(bound[0], subject_sha256=old[0]["subject"]["sha256"])])
        assert validate_results([verdict_for(bound[0], subject_sha256=subject["sha256"])])
    finally:
        reset_verification_scope(token)

    add_job(bus, "recheck", bound, verdicts=["pass"])
    from plugins.tools._verification import project_bus_checks

    projected = project_bus_checks(bus, "run")["checks"][0]
    assert projected["verdict"] == "pass"
    assert projected["subject"]["text"] == text
    assert [attempt["verdict"] for attempt in projected["attempts"]] == ["fail", "pass"]


def test_changing_evidence_does_not_repair_candidate_bytes(tmp_path):
    bus, spec, old = make_bound(tmp_path)
    add_job(bus, "review", old, verdicts=["fail"])
    add_job(bus, "reviewer-evidence", [])
    revised = VerificationCheck.model_validate(
        {
            **spec.model_dump(),
            "replaces_job_id": "review",
            "revision_kind": "subject",
            "revision_reason": "Corrected paragraph in task prose; old report retained",
            "evidence": [{"job_id": "reviewer-evidence"}],
        }
    )
    with pytest.raises(ValueError, match="subject bytes"):
        dispatch(bus, revised, tmp_path)


def test_current_protocol_requires_subject_acknowledgement_but_keeps_legacy_readable(tmp_path):
    _, _, checks = make_bound(tmp_path)
    token = set_verification_scope("review", {"verification_checks": checks})
    result = verdict_for(checks[0])
    result.pop("subject_sha256")
    try:
        with pytest.raises(ValueError, match="subject_sha256"):
            validate_results([result])
        checks[0].pop("protocol_version")
        assert validate_results([result])[0]["verdict"] == "pass"
    finally:
        reset_verification_scope(token)


@pytest.mark.parametrize("kind", ["subject", "evidence", "retry", ""])
def test_recheck_kind_cannot_disguise_unchanged_subject(tmp_path, kind):
    bus, spec, old = make_bound(tmp_path)
    add_job(bus, "review", old)
    data = {
        **spec.model_dump(),
        "replaces_job_id": "review",
        "revision_kind": kind,
        "revision_reason": "The assignment prompt contains a corrected paragraph",
    }
    spec = VerificationCheck.model_validate(data)
    if kind == "retry":
        bound, _ = dispatch(bus, spec, tmp_path)
        assert bound[0]["subject"] == old[0]["subject"]
    else:
        with pytest.raises(ValueError, match=r"revision_kind|subject|evidence"):
            dispatch(bus, spec, tmp_path)


def test_new_evidence_can_recheck_the_same_subject(tmp_path):
    bus, spec, old = make_bound(tmp_path)
    add_job(bus, "review", old, verdicts=["fail"])
    add_job(bus, "new-evidence", [])
    revised = VerificationCheck.model_validate(
        {
            **spec.model_dump(),
            "replaces_job_id": "review",
            "revision_kind": "evidence",
            "revision_reason": "Independent measurement now available",
            "evidence": [{"job_id": "new-evidence"}],
        }
    )
    bound, _ = dispatch(bus, revised, tmp_path)
    assert bound[0]["subject"] == old[0]["subject"]
    assert bound[0]["binding_id"] != old[0]["binding_id"]


def test_projection_does_not_accept_a_verdict_for_different_bytes(tmp_path):
    _, _, checks = make_bound(tmp_path)
    jobs = [
        {
            "job_id": "review",
            "status": "completed",
            "verification_checks": checks,
            "verification_events": [verdict_for(checks[0], subject_sha256="0" * 64)],
        }
    ]
    assert project_checks(jobs)["checks"][0]["verdict"] == "unchecked"


@pytest.mark.parametrize("subject", [{"text": " "}, {"text": "candidate", "job_id": "draft"}])
def test_ambiguous_or_blank_inline_subject_is_rejected(tmp_path, subject):
    bus, spec, _ = make_bound(tmp_path)
    with pytest.raises(ValueError):
        dispatch(
            bus,
            VerificationCheck.model_validate({**spec.model_dump(), "subject": subject}),
            tmp_path,
        )
