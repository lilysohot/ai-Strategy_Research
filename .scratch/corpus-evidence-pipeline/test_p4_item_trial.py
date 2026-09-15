# ruff: noqa: ANN001, ANN201
from __future__ import annotations

import hashlib
import json

import p4_item_trial as trial
import pytest


@pytest.fixture(scope="module")
def plan():
    return trial.prepare()


@pytest.fixture(scope="module")
def projection():
    return json.loads(trial.PROJECTION.read_text(encoding="utf-8"))


def perfect_rows(plan, projection):
    rows = []
    for obligation, target in zip(plan.obligations, projection["records"], strict=True):
        expected = target["projected_fields"]
        speaker = target["speaker_projection"]
        rows.append(
            {
                "protocol_version": trial.FILL_PROTOCOL,
                "plan_id": plan.plan_id,
                "obligation_id": obligation.obligation_id,
                "terminal": "extracted",
                "fields": {
                    "semantic_type": expected["semantic_type"],
                    "speaker_role": speaker["speaker_role"],
                    "identity_status": speaker["identity_status"],
                    "perspective": expected["perspective"],
                    "speech_role": expected["speech_role"],
                    "polarity": expected["polarity"],
                    "behavior_status": expected["behavior_status"],
                    "temporal_frame": expected["temporal_frame"],
                    "value": expected["value"],
                    "unit": expected["unit"],
                    "statement_role": expected["statement_role"],
                    "unknown_fields": [value.removeprefix("unknown_field:") for value in target["constraints"]],
                },
                "reason": None,
            }
        )
    return rows


def batch_raws(plan, rows):
    by_id = {row["obligation_id"]: row for row in rows}
    return tuple(
        "\n".join(
            json.dumps(by_id[obligation.obligation_id], ensure_ascii=False)
            for obligation in plan.obligations[index:index + plan.max_batch_size]
            if obligation.obligation_id in by_id
        )
        for index in range(0, len(plan.obligations), plan.max_batch_size)
    )


def test_plan_is_finite_and_five_batches(plan):
    assert len(plan.obligations) == 35
    assert len(plan.scope_ids) == 6
    assert plan.empty_scope_ids == ("micro-copper-audio",)
    assert len(trial.request_batches(plan)) == 5
    assert plan.unknown_field_vocabulary


def test_requests_do_not_contain_evaluation_fields(plan):
    forbidden = ('"projected_fields"', '"target_id"', '"expected"', '"human_decision"')
    for _, request in trial.request_batches(plan):
        assert not any(value in request for value in forbidden)


def test_requests_bind_source_and_context(plan):
    payloads = [json.loads(request.split("INPUT_JSON=", 1)[1]) for _, request in trial.request_batches(plan)]
    inputs = {
        row["obligation_id"]: row
        for payload in payloads
        for row in payload["obligations"]
    }
    for obligation in plan.obligations:
        assert inputs[obligation.obligation_id]["source_text"] == obligation.source_text
        assert inputs[obligation.obligation_id]["context_text"] == obligation.context_text


def test_requests_supply_finite_field_vocabulary(plan):
    for _, request in trial.request_batches(plan):
        payload = json.loads(request.split("INPUT_JSON=", 1)[1])
        assert tuple(payload["unknown_field_vocabulary"]) == plan.unknown_field_vocabulary
        assert tuple(payload["field_enums"]["semantic_type"]) == trial.SEMANTIC_TYPES


def test_perfect_response_passes_all_item_gates(plan, projection):
    result = trial.score(plan, batch_raws(plan, perfect_rows(plan, projection)), audit_complete=True)
    assert result["passed"] is True
    assert result["gates"]["G1_terminal_capacity"] == "passed"
    assert result["gates"]["G2_system_text_and_constraints"] == "passed"
    assert result["gates"]["G3_field_semantics"] == "passed"
    assert result["gates"]["G6_per_scope_non_regression"] == "passed"
    assert result["scope_status"]["micro-copper-audio"] == "not_applicable_approved_exclusion"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("speaker_role", "bad"),
        ("identity_status", "bad"),
        ("perspective", "bad"),
        ("speech_role", "bad"),
        ("polarity", "bad"),
        ("temporal_frame", "bad"),
        ("statement_role", "bad"),
    ],
)
def test_invalid_enums_fail_protocol(plan, projection, field, value):
    rows = perfect_rows(plan, projection)
    rows[0]["fields"][field] = value
    result = trial.score(plan, batch_raws(plan, rows), audit_complete=True)
    assert result["passed"] is False
    assert result["gates"]["G0_identity"] == "failed"


def test_wrong_plan_id_fails_closed(plan, projection):
    rows = perfect_rows(plan, projection)
    rows[0]["plan_id"] = "wrong"
    assert trial.score(plan, batch_raws(plan, rows), audit_complete=True)["passed"] is False


def test_missing_terminal_fails_closed(plan, projection):
    rows = perfect_rows(plan, projection)[:-1]
    assert trial.score(plan, batch_raws(plan, rows), audit_complete=True)["gates"]["G1_terminal_capacity"] == "failed"


def test_duplicate_terminal_fails_closed(plan, projection):
    rows = perfect_rows(plan, projection)
    raws = list(batch_raws(plan, rows))
    raws[0] += "\n" + json.dumps(rows[0], ensure_ascii=False)
    assert trial.score(plan, tuple(raws), audit_complete=True)["passed"] is False


def test_markdown_fence_is_not_repaired(plan, projection):
    raws = list(batch_raws(plan, perfect_rows(plan, projection)))
    raws[0] = "```json\n" + raws[0] + "\n```"
    assert trial.score(plan, tuple(raws), audit_complete=True)["passed"] is False


def test_no_supported_item_does_not_fake_completion(plan, projection):
    rows = perfect_rows(plan, projection)
    rows[0].update(terminal="no_supported_item", fields=None, reason="not supported")
    result = trial.score(plan, batch_raws(plan, rows), audit_complete=True)
    assert result["gates"]["G1_terminal_capacity"] == "failed"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("semantic_type", "fact"),
        ("speaker_role", "source_author"),
        ("identity_status", "unknown"),
        ("value", "wrong"),
        ("unit", "wrong"),
        ("unknown_fields", []),
    ],
)
def test_semantic_mutations_fail_g3(plan, projection, field, value):
    rows = perfect_rows(plan, projection)
    index = next(
        index for index, row in enumerate(rows)
        if row["fields"][field] != value
    )
    rows[index]["fields"][field] = value
    result = trial.score(plan, batch_raws(plan, rows), audit_complete=True)
    assert result["passed"] is False
    if field == "semantic_type":
        assert result["gates"]["G6_per_scope_non_regression"] == "failed"
    else:
        assert result["gates"]["G3_field_semantics"] == "failed"


def test_incomplete_audit_fails_g1(plan, projection):
    result = trial.score(plan, batch_raws(plan, perfect_rows(plan, projection)), audit_complete=False)
    assert result["gates"]["G1_terminal_capacity"] == "failed"


def test_journal_reserves_before_send_and_halts_on_error(tmp_path, plan):
    path = tmp_path / "audit.sqlite3"
    journal = trial.Journal.create(path, plan_id=plan.plan_id, budget_sha256="budget", max_calls=1)
    try:
        number = journal.reserve("one", "request")
        assert journal.snapshot()["attempts"][0]["status"] == "reserved"
        journal.failed(number, "adapter_failure")
        with pytest.raises(ValueError, match="journal_halted_or_exhausted"):
            journal.reserve("two", "request")
    finally:
        journal.close()


def test_invalid_first_batch_halts_without_spending_remaining_calls(tmp_path, plan):
    batches = trial.request_batches(plan)
    responses = {
        hashlib.sha256(request.encode()).hexdigest(): "not-json"
        for _, request in batches
    }
    journal = trial.Journal.create(
        tmp_path / "audit.sqlite3",
        plan_id=plan.plan_id,
        budget_sha256="budget",
        max_calls=5,
    )
    try:
        result = trial.execute(plan, trial.FakeAdapter(responses), journal)
        audit = journal.snapshot()
        assert result["passed"] is False
        assert len(audit["attempts"]) == 1
        assert audit["metadata"]["halted"] == "true"
        assert audit["metadata"]["halt_reason"] == "invalid_batch_response"
    finally:
        journal.close()


def test_fake_adapter_runs_through_same_interface(tmp_path, plan, projection):
    batches = trial.request_batches(plan)
    raws = batch_raws(plan, perfect_rows(plan, projection))
    responses = {hashlib.sha256(request.encode()).hexdigest(): raw for (_, request), raw in zip(batches, raws, strict=True)}
    journal = trial.Journal.create(tmp_path / "audit.sqlite3", plan_id=plan.plan_id, budget_sha256="budget", max_calls=5)
    try:
        result = trial.execute(plan, trial.FakeAdapter(responses), journal)
        assert result["passed"] is True
        assert journal.complete(5) is True
    finally:
        journal.close()
