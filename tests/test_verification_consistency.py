"""Cross-domain controls for review consistency, not a semantic truth judge."""

import pytest

from benchmarks.team_workflow.regression_probes import accept, bound_passage, result_for


@pytest.mark.parametrize(
    "detail",
    [
        "所需资格未核实，结论通过。",
        "必要的接口契约尚未取得，结论通过。",
        "The required permission has not been verified; PASS.",
        "I could not confirm the applicable condition; PASS.",
    ],
)
def test_explicit_incomplete_review_cannot_pass(tmp_path, detail):
    check = bound_passage(tmp_path, "The permission is granted.", ["Permission is granted."])
    with pytest.raises(ValueError):
        accept(check, result_for(check, detail=detail))
    assert accept(check, result_for(check, detail=detail, verdict="unchecked"))


@pytest.mark.parametrize(
    "detail",
    [
        "已核实所需资格，未发现矛盾。",
        "The applicable condition was verified against the bound evidence.",
        "The source contains the literal phrase ‘not verified’; the requested quotation matches.",
    ],
)
def test_complete_or_quoted_review_does_not_become_unknown(tmp_path, detail):
    check = bound_passage(tmp_path, "The permission is granted.", ["Permission is granted."])
    assert accept(check, result_for(check, detail=detail))


def test_comparison_details_cannot_contradict_match(tmp_path):
    check = bound_passage(tmp_path, "The permission is granted.", ["Permission is granted."])
    result = result_for(check)
    result["scope_assessment"]["conditions"]["detail"] = "必要条件未确认。"
    with pytest.raises(ValueError):
        accept(check, result)


def test_binding_prompt_has_no_domain_examples(tmp_path):
    from tests.test_agent_team_verification import make_bound
    from tests.test_team_080_regressions import dispatch

    bus, spec, _ = make_bound(tmp_path)
    _, prompt = dispatch(bus, spec, tmp_path)
    instructions = prompt.split("SOURCE ")[0]
    assert "September" not in instructions and "October" not in instructions
    assert "cache-retention" not in instructions and "demand growth" not in instructions
    assert "Evidence from different sources" in instructions


def test_persisted_inconsistent_pass_is_not_restored(tmp_path):
    from plugins.tools._verification import project_checks

    check = bound_passage(tmp_path, "The permission is granted.", ["Permission is granted."])
    event = result_for(check, detail="The required permission has not been verified.")
    projected = project_checks(
        [
            {
                "job_id": "review",
                "status": "complete",
                "verification_checks": [check],
                "verification_events": [event],
            }
        ]
    )
    assert projected["checks"][0]["verdict"] == "unchecked"


def test_persisted_unmarked_bad_receipt_is_not_restored(tmp_path):
    from plugins.tools._verification import project_checks
    from tests.test_team_080_regressions import calculation

    check = bound_passage(
        tmp_path, "The result is 100.", ["2026-11-05: close 110 points; daily change +10 points."]
    )
    check.pop("factual_scope", None)
    proof = calculation()
    proof["expression"] = "0"
    event = result_for(check, calculation_checks=[proof])
    projected = project_checks(
        [
            {
                "job_id": "review",
                "status": "complete",
                "verification_checks": [check],
                "verification_events": [event],
            }
        ]
    )
    assert projected["checks"][0]["verdict"] == "unchecked"
