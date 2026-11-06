"""Failure shapes from 3b30: evidence starvation, verdict labels and schema recovery."""

import hashlib
from copy import deepcopy

import pytest

from plugins.tools._verification import (
    commit_results,
    project_checks,
    reset_verification_scope,
    set_verification_scope,
    validate_results,
)
from plugins.tools._web_handoff import render_web_handoff
from plugins.tools.task_board import drain_board_ops, snapshot_tasks
from tests.test_agent_team_verification import add_job, binding, make_bound, verdict_for
from tests.test_team_atomic_delivery import delivery_run as _delivery_run
from tests.test_team_atomic_delivery import prepare, turn_context
from workflows.agent_team.delivery import TeamDeliveryObserver, deliver_answer

delivery_run = _delivery_run


def record(source, text):
    return {
        "source": source,
        "text": text,
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "content_kind": "tool_delivered_text",
        "status": "success",
    }


def test_short_direct_evidence_survives_high_scoring_long_pages():
    short = "DGS2\n2026-11-03: 4.61 | Percent\n" + "Source metadata. " * 32
    other = "DGS10\n2026-11-03: 4.95 | Percent\n"
    sources = {
        "market": [
            record("https://example.test/broad", "stocks earnings volatility inflation " * 1000),
            record("https://fred.stlouisfed.org/series/DGS2", short),
            record("https://fred.stlouisfed.org/series/DGS10", other),
        ]
    }
    text = render_web_handoff(
        sources,
        focus_text="stocks earnings volatility inflation DGS2 DGS10 4.61 4.891",
        body_budget=2400,
        reference_budget=1000,
    )
    assert short in text and other in text
    assert "4.891 | Percent" not in text, "handoff must not silently repair the source date/value"
    assert len(text) < 4500


@pytest.mark.parametrize(
    "label", ["【答案中作为已核验事实引用的市场数据】", "以下为逐项核对过的数据："]
)
async def test_unchecked_data_cannot_be_published_under_verified_label(delivery_run, label):
    bus, _ = delivery_run
    await prepare(bus, "unchecked")
    bus._jobs["j1"].item.metadata["verification_checks"][0]["subject"]["text"] = (
        "两年期收益率4.61%。"
    )
    before = snapshot_tasks("run")
    with pytest.raises(ValueError, match="verification_label"):
        await deliver_answer.func(
            content=label + "\n两年期收益率4.61%。\n\n部分数据尚未完成核验。",
            updates=[
                {
                    "id": "t1",
                    "resolution": "blocked",
                    "notes": "Review ended",
                    "gap": "Missing evidence",
                }
            ],
        )
    assert snapshot_tasks("run") == before
    assert drain_board_ops("run") == []


async def test_scoped_passage_can_keep_label_beside_an_explicit_gap(delivery_run):
    bus, _ = delivery_run
    await prepare(bus, "pass")
    bus._jobs["j1"].item.metadata["verification_checks"][0]["subject"]["text"] = (
        "已核验：样本成本为50元。"
    )
    # Another check is not certified; its omission must not invalidate the exact passed passage.
    add_job(bus, "other", [binding("missing")], verdicts=["unchecked"])
    await deliver_answer.func(
        content="已核验：样本成本为50元。\n\n其他数据未完成核验，不作为确定结论。",
        updates=[
            {"id": "t1", "resolution": "blocked", "notes": "Partial", "gap": "Other data missing"}
        ],
    )


def assessment():
    return {
        key: {"status": "match", "detail": "Same scope"}
        for key in ("entity", "version", "date", "units", "conditions", "attribution")
    }


@pytest.mark.parametrize("verdict", ["fail", "unchecked"])
def test_misnested_issues_recover_losslessly_before_checkpoint(tmp_path, verdict):
    _, _, bound = make_bound(tmp_path)
    metadata = {"verification_checks": bound}
    token = set_verification_scope("review", metadata)
    raw = verdict_for(
        bound[0],
        verdict=verdict,
        scope_assessment={
            **assessment(),
            "unresolved_issues": ["Observation date differs from the claim"],
        },
    )
    original = deepcopy(raw)
    try:
        accepted = validate_results([raw])
        assert raw == original
        assert accepted[0]["unresolved_issues"] == raw["scope_assessment"]["unresolved_issues"]
        commit_results(accepted)
        assert len(metadata["verification_events"]) == 1
    finally:
        reset_verification_scope(token)


def test_misnested_issues_cannot_hide_a_failed_obligation(tmp_path):
    _, _, bound = make_bound(tmp_path)
    metadata = {"verification_checks": bound}
    token = set_verification_scope("review", metadata)
    try:
        raw = verdict_for(
            bound[0], scope_assessment={**assessment(), "unresolved_issues": ["Missing date"]}
        )
        with pytest.raises(ValueError, match=r"pass.*unresolved"):
            validate_results([raw])
        raw["unresolved_issues"] = []
        with pytest.raises(ValueError, match="conflicting unresolved_issues"):
            validate_results([raw])
        assert metadata["verification_events"] == []
    finally:
        reset_verification_scope(token)


async def test_partial_verifier_timeout_retries_only_unfinished_check(delivery_run, monkeypatch):
    bus, budget = delivery_run
    await prepare(bus)
    add_job(bus, "j1", [binding(), binding("pending")], verdicts=["pass"], stop="llm_error")
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 600)
    ctx = turn_context()
    decision = await TeamDeliveryObserver(budget).on_before_llm(ctx)
    assert ctx.metadata["team_verification_repair_offered"] == ["pending"]
    assert '"check_id": "amount"' not in " ".join(decision.inject_messages)
    assert '"revision_kind": "retry"' in " ".join(decision.inject_messages)


def test_replayed_factual_pass_cannot_hide_misnested_issues():
    check = {**binding(), "factual_scope": True}
    check["binding_id"] = "a" * 64
    event = verdict_for(
        check, scope_assessment={**assessment(), "unresolved_issues": ["Missing date"]}
    )
    projected = project_checks(
        [
            {
                "job_id": "review",
                "status": "completed",
                "verification_checks": [check],
                "verification_events": [event],
            }
        ]
    )
    assert projected["checks"][0]["verdict"] == "unchecked"


def test_explicit_label_gate_allows_negative_status_explanations():
    from plugins.tools._verification import verification_label_findings

    checks = [{**binding(), "verdict": "unchecked"}]
    assert not verification_label_findings(checks, "不能将缺少日期的数据称为已核验事实。")
    assert not verification_label_findings(checks, "这些数据不构成已核验事实。")
    assert not verification_label_findings(
        checks, "已通过独立核验的部分：成本检查PASS；其他检查未完成。"
    )
    assert not verification_label_findings(checks, "These are not independently verified data.")
    assert verification_label_findings(checks, "【已核验事实】\n两年期收益率4.61%。")


async def test_legacy_finalize_path_also_checks_certification_labels(delivery_run):
    from plugins.tools.finalize_answer import finalize_gate
    from plugins.tools.task_board import update_task

    bus, _ = delivery_run
    await prepare(bus, "unchecked")
    await update_task.func(
        [{"id": "t1", "resolution": "blocked", "notes": "Partial", "gap": "Missing"}]
    )
    assert "verification_label" in finalize_gate("run", "【已核验事实】\n两年期收益率4.61%。")
