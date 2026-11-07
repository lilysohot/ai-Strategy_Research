"""Minimal synthetic replays of 49e/3d877; expected defects stay red, never xfail.

These exercise production acceptance boundaries. A semantic contradiction probe
does not prescribe a regex fix: a future claim-coverage protocol may replace the
representation, but must preserve the paired acceptance/rejection requirement.
"""

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from plugins.tools._verification import (
    VerificationCheck,
    reset_verification_scope,
    set_verification_scope,
    validate_results,
)
from plugins.tools.task_board import add_task, bind_assignment, drain_board_ops, snapshot_tasks
from tests.test_agent_team_verification import add_job, binding, make_bound, verdict_for
from tests.test_team_080_regressions import calculation, dispatch, record
from tests.test_team_atomic_delivery import delivery_run as _delivery_run
from workflows.agent_team.delivery import deliver_answer
from workflows.agent_team.lifecycle import snapshot_job_outcomes

delivery_run = _delivery_run


def bound_passage(tmp_path: Path, subject: str, texts: list[str]) -> dict[str, Any]:
    bus, spec, _ = make_bound(tmp_path)
    source_result = bus._jobs["source"].result
    assert source_result is not None
    source_result.metadata["web_evidence"] = [
        record(text, "https://example.test/result" if i == 0 else f"https://example.test/{i}")
        for i, text in enumerate(texts)
    ]
    spec = VerificationCheck.model_validate(
        {**spec.model_dump(), "subject": {"text": subject}, "factual_scope": True}
    )
    checks, _ = dispatch(bus, spec, tmp_path)
    return checks[0]


def result_for(check: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return verdict_for(
        check,
        scope_assessment={
            axis: {"status": "match", "detail": "Candidate agrees with source."}
            for axis in ("entity", "version", "date", "units", "conditions", "attribution")
        },
        **kwargs,
    )


def accept(check: dict[str, Any], result: dict[str, Any]) -> list[dict[str, Any]]:
    token = set_verification_scope("review", {"verification_checks": [check]})
    try:
        return validate_results([result])
    finally:
        reset_verification_scope(token)


@pytest.mark.parametrize("defect", ["zero_formula", "unbound_key", "false_quote"])
def test_unmarked_calculation_receipt_is_still_validated(tmp_path: Path, defect: str) -> None:
    """49e supplied receipts even though no marker generated calculation_targets."""
    check = bound_passage(
        tmp_path,
        "2026-11-04 收盘100点。",
        ["2026-11-05: close 110 points; daily change +10 points."],
    )
    proof = calculation()
    if defect == "zero_formula":
        proof["expression"] = "0"
    elif defect == "unbound_key":
        proof["inputs"]["close"]["source_key"] = "a descriptive label, not a bound key"
    else:
        proof["inputs"]["close"]["quote"] = "2026-11-05: imagined close 110 points."
    with pytest.raises(ValueError):
        accept(check, result_for(check, calculation_checks=[proof]))


def test_valid_unmarked_receipt_and_direct_fact_remain_acceptable(tmp_path: Path) -> None:
    check = bound_passage(
        tmp_path,
        "2026-11-04 收盘100点。",
        ["2026-11-05: close 110 points; daily change +10 points."],
    )
    assert accept(check, result_for(check, calculation_checks=[calculation()]))
    direct = bound_passage(tmp_path, "收盘110点。", ["收盘110点。"])
    assert accept(direct, result_for(direct))


def test_admitted_required_unknown_cannot_hide_inside_pass_detail(tmp_path: Path) -> None:
    check = bound_passage(tmp_path, "2026-11-06 收盘110点、开盘105点。", ["2026-11-06 收盘110点。"])
    result = result_for(
        check,
        detail="收盘110已核实。未复核项：开盘105未取得来源，无法确认。",
        unresolved_issues=[],
    )
    with pytest.raises(ValueError):
        accept(check, result)


def test_complete_coverage_and_honest_unknown_are_accepted(tmp_path: Path) -> None:
    subject = "2026-11-06 收盘110点、开盘105点。"
    complete = bound_passage(tmp_path, subject, [subject])
    assert accept(complete, result_for(complete, detail="收盘110、开盘105均逐项核实。"))
    partial = bound_passage(tmp_path, subject, ["2026-11-06 收盘110点。"])
    assert accept(partial, result_for(partial, verdict="unchecked", unresolved_issues=["开盘未知"]))


def test_cross_document_week_cannot_complete_unknown_table_period(tmp_path: Path) -> None:
    check = bound_passage(
        tmp_path,
        "2026-08-31至09-04交易周，日均成交额120亿元。",
        ["日均成交额（亿元）\n120", "另一份报告：2026-08-31至09-04交易周指数收于100点。"],
    )
    result = result_for(
        check,
        detail="120与表体一致。该表期间标签未取回；借另一报告的交易周推定为08-31至09-04。",
    )
    with pytest.raises(ValueError):
        accept(check, result)


def test_same_table_period_and_unknown_period_controls(tmp_path: Path) -> None:
    subject = "2026-08-31至09-04交易周，日均成交额120亿元。"
    check = bound_passage(tmp_path, subject, ["统计期间2026-08-31至09-04\n日均成交额（亿元）\n120"])
    assert accept(check, result_for(check, detail="同一表的期间、单位、数值均一致。"))
    partial = bound_passage(tmp_path, subject, ["日均成交额（亿元）\n120"])
    unknown = result_for(partial, detail="缺少期间，不能认证。")
    unknown["scope_assessment"]["date"] = {"status": "unknown", "detail": "期间标签缺失"}
    with pytest.raises(ValueError):
        accept(partial, unknown)
    unknown["verdict"] = "unchecked"
    assert accept(partial, unknown)


@pytest.mark.parametrize("replacement", ["complete", "partial", "unchecked", "missing"])
async def test_replacement_settles_obligations_not_historical_attempts(
    delivery_run: Any,
    replacement: str,
) -> None:
    bus, _ = delivery_run
    await add_task.func(
        [
            {
                "description": "核验金额及期间",
                "verification_requirements": [
                    {"check_id": key, "criterion": "Recompute the amount"}
                    for key in ("amount", "period")
                ],
            }
        ]
    )
    checks = [binding(check_id=key) for key in ("amount", "period")]
    add_job(bus, "interrupted", checks, stop="llm_error")
    bind_assignment("run", ["t1"], "reviewer", "interrupted")
    if replacement != "missing":
        revised = [dict(deepcopy(c), replaces_job_id="interrupted") for c in checks]
        if replacement == "partial":
            revised = revised[:1]
        add_job(
            bus,
            "replacement",
            revised,
            verdicts=["unchecked" if replacement == "unchecked" else "pass" for _ in revised],
        )
        bind_assignment("run", ["t1"], "reviewer", "replacement")
    drain_board_ops("run")
    before = snapshot_tasks("run")
    if replacement == "complete":
        await deliver_answer.func(
            content="金额50已完成金额与期间核验。",
            updates=[{"id": "t1", "resolution": "resolved", "notes": "替代检查完整通过"}],
        )
        assert snapshot_tasks("run")[0]["resolution"] == "resolved"
        old = next(j for j in snapshot_job_outcomes(bus, "run") if j["job_id"] == "interrupted")
        assert old["status"] == "incomplete", "Recovery must not erase failed attempt history"
    else:
        with pytest.raises(ValueError):
            await deliver_answer.func(
                content="Amount is 50.",
                updates=[{"id": "t1", "resolution": "resolved", "notes": "Claim complete"}],
            )
        assert snapshot_tasks("run") == before
