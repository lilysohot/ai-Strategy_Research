"""Synthetic output mutations. No real gold, documents or human approvals."""

from dataclasses import replace

import pytest
from p1_planner_spec import Packet, Plan, Scope, Source, prepare, source_binding
from r2_evaluation_v1 import (
    AXES,
    CONTRACT_SHA,
    POLICY,
    Decision,
    EvaluationReport,
    Gold,
    Item,
    Pins,
    Record,
    Result,
    Reviews,
    SemanticField,
    Target,
    digest,
    evaluate,
    metric,
    model_hash,
    seal_result,
)


def example(
    *, quantitative: bool = False, repeated_quote: bool = False
) -> tuple[Source, Plan, Result, Gold, Reviews, Pins]:
    texts = (
        "甲公司产量为100吨。" if quantitative else "在需求回升时甲公司不扩产。",
        "我计划增持。",
        "专家：欢迎各位。",
    )
    source = Source(
        "synthetic",
        "rev",
        "parse",
        tuple(
            Packet(f"p{i}", f"line:{i + 1}", text * 2 if repeated_quote and i == 0 else text)
            for i, text in enumerate(texts)
        ),
    )
    plan = prepare(
        source,
        source_binding(source),
        tuple(Scope(p.packet_id, 0, len(texts[i])) for i, p in enumerate(source.packets)),
    )
    values = [
        ("forecast", None, "source_explicit", "statement", "negated", None, None, None, None),
        ("behavior", None, "source_explicit", "statement", "affirmed", "intent", None, None, None),
    ]
    records, targets, decisions = [], [], []
    if quantitative:
        values[0] = (
            "fact",
            None,
            "source_explicit",
            "statement",
            "affirmed",
            None,
            None,
            "100",
            "吨",
        )
    values = [
        (*row, "condition" if index == 0 and not quantitative else "claim")
        for index, row in enumerate(values)
    ]
    for i, obligation in enumerate(plan.obligations):
        evidence = (obligation.focus.span_id,)
        fields = (
            tuple(
                SemanticField(
                    name=axis,
                    value=value,
                    origin="unknown"
                    if value is None
                    else ("source_observed" if axis in ("value", "unit") else "model_interpreted"),
                    support_span_ids=evidence,
                    unknown_reason="source_unspecified" if value is None else None,
                )
                for axis, value in zip(AXES, values[i], strict=True)
            )
            if i < 2
            else ()
        )
        item = (
            Item(
                item_id=f"i{i}",
                text=texts[i],
                constraints=("需求回升", "不扩产") if i == 0 and not quantitative else (),
                fields=fields,
                evidence_span_ids=evidence,
            )
            if i < 2
            else None
        )
        record = Record(
            obligation_id=obligation.obligation_id,
            terminal="extracted" if item else "no_supported_item",
            item=item,
            reason=None if item else "greeting_only",
            evidence_span_ids=evidence,
            response_received=True,
        )
        records.append(record)
        if item:
            targets.append(
                Target(
                    target_id=f"t{i}",
                    evidence_span_ids=evidence,
                    fields=tuple(zip(AXES, values[i], strict=True)),
                )
            )
        decisions.append(
            Decision(
                record_sha256=model_hash(record),
                reviewer_id="test-fixture",
                reviewer_kind="synthetic_fixture",
                status="approved",
                reviewed_at="synthetic-fixed-time",
                reason="explicit synthetic oracle",
                target_id=f"t{i}" if item else None,
                fidelity="faithful" if item else "not_applicable",
                atomicity="single" if item else "not_applicable",
                constraints_retained=True if item else None,
                no_supported_item_confirmed=item is None,
                critical_errors=(),
            )
        )
    result = seal_result(
        Result(
            protocol_version="r2-obligation-item-1",
            plan_id=plan.plan_id,
            result_id="",
            records=tuple(records),
            protocol_errors=(),
            audit_complete=True,
        )
    )
    gold = Gold(
        version="synthetic-gold-1",
        source_binding=source_binding(source),
        atomic_denominator_approved=True,
        targets=tuple(targets),
    )
    reviews = Reviews(
        source_binding=source_binding(source),
        plan_id=plan.plan_id,
        contract_sha256=CONTRACT_SHA,
        gold_sha256=model_hash(gold),
        result_sha256=model_hash(result),
        decisions=tuple(decisions),
    )
    pins = Pins(
        "synthetic-case",
        "company",
        "synthetic",
        source_binding(source),
        plan.plan_id,
        model_hash(result),
        model_hash(gold),
        model_hash(reviews),
        CONTRACT_SHA,
        digest(POLICY),
    )
    return source, plan, result, gold, reviews, pins


def replace_record(result: Result, index: int, **changes: object) -> Result:
    records = list(result.records)
    records[index] = records[index].model_copy(update=changes)
    return seal_result(result.model_copy(update={"records": tuple(records)}))


def refresh_synthetic_decisions(
    result: Result, reviews: Reviews, **first_changes: object
) -> Reviews:
    """New synthetic oracle only, never an automatic human-review operation."""
    decisions = tuple(
        d.model_copy(
            update={"record_sha256": model_hash(record), **(first_changes if i == 0 else {})}
        )
        for i, (d, record) in enumerate(zip(reviews.decisions, result.records, strict=True))
    )
    return reviews.model_copy(update={"result_sha256": model_hash(result), "decisions": decisions})


def run_changed(
    result: Result, reviews: Reviews | None = None, gold: Gold | None = None, **pin_changes: object
) -> EvaluationReport:
    source, plan, _, original_gold, original_reviews, pins = example()
    gold = gold or original_gold
    reviews = reviews or original_reviews
    pins = replace(
        pins,
        result_sha256=model_hash(result),
        reviews_sha256=model_hash(reviews),
        gold_sha256=model_hash(gold),
        **pin_changes,
    )
    return evaluate(source, plan, result, gold, reviews, pins)


def test_positive_control_has_real_denominators_and_no_budget() -> None:
    report = evaluate(*example())
    assert report.local_item_gates_passed
    assert not report.budget_authorized
    assert report.gates == {
        "G0": "passed",
        "G1": "passed",
        "G2": "passed",
        "G3": "passed",
        "G4": "not_evaluated",
        "G5": "not_evaluated",
        "G6": "not_evaluated",
        "G7": "not_evaluated",
    }
    assert report.metrics["item_recall"].numerator == report.metrics["item_recall"].denominator == 2
    assert report.metrics["unresolved_content"].numerator == 0
    assert report.metrics["critical_errors"].status == "passed"


@pytest.mark.parametrize(
    "change",
    [
        "fabrication",
        "negation",
        "condition",
        "scope",
        "constraints",
        "intent",
        "speaker",
        "unknown",
        "number",
        "origin",
        "time",
    ],
)
def test_rehashed_output_cannot_reuse_old_review(change: str) -> None:
    _, _, result, _, _, _ = example()
    index = 1 if change == "intent" else 0
    item = result.records[index].item
    updates = {
        "fabrication": {"text": "乙公司已经全面停产。"},
        "negation": {"text": "在需求回升时甲公司扩产。"},
        "condition": {"text": "甲公司不扩产。"},
        "scope": {"text": "所有公司都不会扩产。"},
        "constraints": {"constraints": ()},
    }
    if change in updates:
        item = item.model_copy(update=updates[change])
    else:
        axis, value = {
            "intent": ("behavior_status", "claimed_executed"),
            "speaker": ("speaker_ref", "expert"),
            "unknown": ("polarity", None),
            "number": ("value", "999"),
            "origin": ("speech_role", "answer"),
            "time": ("temporal_frame", "contemporaneous"),
        }[change]
        fields = tuple(
            f.model_copy(update={"value": value}) if f.name == axis else f for f in item.fields
        )
        item = item.model_copy(update={"fields": fields})
    changed = replace_record(result, index, item=item)
    report = run_changed(changed)
    assert report.gates["G0"] == "passed"  # Output is newly and legitimately hashed.
    assert not report.local_item_gates_passed
    assert report.needs_review


@pytest.mark.parametrize(
    "changes",
    [
        {"fidelity": "unsupported"},
        {"constraints_retained": False},
        {"atomicity": "multiple"},
        {"fidelity": "unknown"},
        {"atomicity": "unknown"},
        {"critical_errors": ("negation_flip",)},
    ],
)
def test_explicit_adverse_semantic_judgments_block(changes: dict[str, object]) -> None:
    _, _, result, _, reviews, _ = example()
    reviews = refresh_synthetic_decisions(result, reviews, **changes)
    report = run_changed(result, reviews)
    assert report.gates["G2"] != "passed"
    assert not report.local_item_gates_passed


def test_error_count_uses_max_not_min() -> None:
    assert metric(0, 1, "max", 0).status == "passed"
    assert metric(1, 1, "max", 0).status == "failed"
    assert metric(35, 1, "max", 0).status == "failed"
    _, _, result, _, reviews, _ = example()
    reviews = refresh_synthetic_decisions(
        result, reviews, critical_errors=("unsupported_relation",)
    )
    report = run_changed(result, reviews)
    assert report.metrics["critical_errors"].numerator == 1
    assert report.metrics["critical_errors"].status == "failed"


@pytest.mark.parametrize("terminal", ["unresolved", "failed", "deferred", "no_supported_item"])
def test_terminal_count_is_not_content_completion(terminal: str) -> None:
    _, _, result, _, reviews, _ = example()
    changed = replace_record(result, 0, terminal=terminal, item=None, reason="cannot_resolve")
    reviews = refresh_synthetic_decisions(
        changed,
        reviews,
        target_id=None,
        fidelity="not_applicable",
        atomicity="not_applicable",
        no_supported_item_confirmed=False,
    )
    report = run_changed(changed, reviews)
    assert report.metrics["unresolved_content"].numerator > 0
    assert report.gates["G1"] == "failed"


@pytest.mark.parametrize(
    "change",
    [
        "duplicate",
        "missing",
        "unknown_id",
        "truncation",
        "lost_response",
        "audit",
        "item_with_no_supported",
        "duplicate_item_id",
    ],
)
def test_protocol_mutations(change: str) -> None:
    _, _, result, _, _, _ = example()
    if change == "duplicate":
        changed = result.model_copy(update={"records": (*result.records, result.records[0])})
    elif change == "missing":
        changed = result.model_copy(update={"records": result.records[1:]})
    elif change == "unknown_id":
        changed = replace_record(result, 0, obligation_id="invented")
    elif change == "truncation":
        changed = result.model_copy(update={"protocol_errors": ("truncated_line",)})
    elif change == "lost_response":
        changed = replace_record(result, 0, response_received=False)
    elif change == "audit":
        changed = result.model_copy(update={"audit_complete": False})
    elif change == "item_with_no_supported":
        changed = replace_record(result, 0, terminal="no_supported_item", reason="nothing")
    else:
        item = result.records[1].item.model_copy(update={"item_id": result.records[0].item.item_id})
        changed = replace_record(result, 1, item=item)
    report = run_changed(seal_result(changed))
    assert report.gates["G1"] == "failed"
    assert not report.local_item_gates_passed


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_sha256", "wrong"),
        ("plan_id", "wrong"),
        ("result_sha256", "wrong"),
        ("gold_sha256", "wrong"),
        ("reviews_sha256", "wrong"),
        ("contract_sha256", "wrong"),
        ("policy_sha256", "wrong"),
    ],
)
def test_binding_mutations(field: str, value: str) -> None:
    source, plan, result, gold, reviews, pins = example()
    report = evaluate(source, plan, result, gold, reviews, replace(pins, **{field: value}))
    assert report.gates["G0"] == "failed"
    assert not report.local_item_gates_passed


@pytest.mark.parametrize(
    "change",
    [
        "wrong_evidence",
        "sibling_evidence",
        "field_evidence",
        "unknown_contradiction",
        "label_origin",
        "numeric",
        "transform",
    ],
)
def test_fields_and_evidence_checked_without_trusting_review(change: str) -> None:
    _, plan, result, _, reviews, _ = example()
    item = result.records[0].item
    if change in ("wrong_evidence", "sibling_evidence"):
        refs = ("wrong",) if change == "wrong_evidence" else (plan.obligations[1].focus.span_id,)
        item = item.model_copy(update={"evidence_span_ids": refs})
    else:
        changes = {
            "field_evidence": {"support_span_ids": ("wrong",)},
            "unknown_contradiction": {
                "origin": "unknown",
                "value": "forecast",
                "unknown_reason": "unknown",
            },
            "label_origin": {"origin": "source_observed"},
            "numeric": {"name": "value", "origin": "model_interpreted", "value": "999"},
            "transform": {"origin": "validated_transform", "transform_rule_id": "invented"},
        }[change]
        item = item.model_copy(
            update={"fields": (item.fields[0].model_copy(update=changes), *item.fields[1:])}
        )
    changed = replace_record(result, 0, item=item)
    reviews = refresh_synthetic_decisions(changed, reviews)
    report = run_changed(changed, reviews)
    assert not report.local_item_gates_passed
    assert report.gates["G0"] == "failed" or report.gates["G3"] == "failed"


def test_semantic_recall_denominator_includes_missed_targets() -> None:
    _, _, result, _, _, _ = example()
    changed = seal_result(result.model_copy(update={"records": result.records[1:]}))
    report = run_changed(changed)
    assert report.metrics["semantic/forecast/recall"].denominator == 1
    assert report.metrics["semantic/forecast/recall"].numerator == 0
    assert report.metrics["item_recall"].denominator == 2


def test_wrong_semantic_label_has_both_false_positive_and_false_negative() -> None:
    _, _, result, _, reviews, _ = example()
    item = result.records[0].item
    item = item.model_copy(
        update={
            "fields": tuple(
                f.model_copy(update={"value": "opinion"}) if f.name == "semantic_type" else f
                for f in item.fields
            )
        }
    )
    changed = replace_record(result, 0, item=item)
    report = run_changed(changed, refresh_synthetic_decisions(changed, reviews))
    assert report.metrics["semantic/forecast/recall"].status == "failed"
    assert report.metrics["semantic/opinion/precision"].status == "failed"
    assert report.gates["G3"] == "failed"


@pytest.mark.parametrize(
    "kind,status,mode",
    [
        ("agent_proposal", "approved", "synthetic"),
        ("agent_proposal", "proposed", "development"),
        ("synthetic_fixture", "approved", "development"),
        ("human", "approved", "development"),
        ("human", "proposed", "development"),
    ],
)
def test_untrusted_or_proposed_review_never_approves(kind: str, status: str, mode: str) -> None:
    _, _, result, _, reviews, _ = example()
    reviews = refresh_synthetic_decisions(result, reviews, reviewer_kind=kind, status=status)
    report = run_changed(result, reviews, mode=mode)
    assert report.needs_review
    assert not report.local_item_gates_passed


def test_human_allowlist_path_on_synthetic_data_only() -> None:
    source, plan, result, gold, reviews, pins = example()
    reviews = reviews.model_copy(
        update={
            "decisions": tuple(
                d.model_copy(update={"reviewer_kind": "human", "reviewer_id": "unit-test-human"})
                for d in reviews.decisions
            )
        }
    )
    pins = replace(
        pins,
        mode="development",
        human_reviewers=("unit-test-human",),
        reviews_sha256=model_hash(reviews),
    )
    assert evaluate(source, plan, result, gold, reviews, pins).local_item_gates_passed


def test_unapproved_atomic_denominator_blocks() -> None:
    _, _, result, gold, reviews, _ = example()
    gold = gold.model_copy(update={"atomic_denominator_approved": False})
    reviews = reviews.model_copy(update={"gold_sha256": model_hash(gold)})
    report = run_changed(result, reviews, gold)
    assert "atomic_gold_denominator_not_approved" in report.needs_review
    assert not report.local_item_gates_passed


def test_duplicate_mapping_cannot_inflate_recall() -> None:
    _, _, result, _, reviews, _ = example()
    changed = reviews.decisions[1].model_copy(update={"target_id": "t0"})
    reviews = reviews.model_copy(
        update={"decisions": (reviews.decisions[0], changed, reviews.decisions[2])}
    )
    report = run_changed(result, reviews)
    assert report.metrics["item_recall"].numerator == 1
    assert not report.local_item_gates_passed


@pytest.mark.parametrize("value", ["partial", "COMPLETED", "invented"])
def test_unknown_terminal_is_schema_error(value: str) -> None:
    _, _, result, _, _, _ = example()
    changed = replace_record(result, 0, terminal=value)
    report = run_changed(changed)
    assert report.gates["G0"] == "failed"


def test_zero_denominator_not_success() -> None:
    assert metric(0, 0, "min", 1).status == "not_applicable"


@pytest.mark.parametrize(
    "args",
    [
        (True, 1, "max", 0),
        (-1, 1, "max", 0),
        (0, -1, "max", 0),
        (0, 1, "wrong", 0),
        (0, 1, "max", float("nan")),
    ],
)
def test_invalid_metric_fails_closed(args: tuple[object, ...]) -> None:
    with pytest.raises(ValueError):
        metric(*args)


def test_invalid_records_remain_in_semantic_precision_denominator() -> None:
    _, _, result, _, _, _ = example()
    changed = seal_result(
        result.model_copy(update={"records": (*result.records, result.records[0])})
    )
    report = run_changed(changed)
    assert report.metrics["semantic/forecast/precision"].denominator == 2
    assert report.metrics["item_precision"].denominator == 3


def test_runtime_policy_mutation_cannot_be_rehashed_into_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, plan, result, gold, reviews, pins = example()
    monkeypatch.setitem(POLICY, "critical_errors_max", 35)
    report = evaluate(
        source, plan, result, gold, reviews, replace(pins, policy_sha256=digest(POLICY))
    )
    assert report.gates["G0"] == "failed"


def test_schema_error_does_not_leak_private_payload() -> None:
    _, _, result, _, _, _ = example()
    changed = replace_record(result, 0, terminal="private-secret-output-not-a-terminal")
    report = run_changed(changed)
    assert report.gates["G0"] == "failed"
    assert "private-secret-output" not in str(report.errors)


def test_literal_numeric_positive_and_substring_negative() -> None:
    source, plan, result, gold, reviews, pins = example(quantitative=True)
    assert evaluate(source, plan, result, gold, reviews, pins).local_item_gates_passed
    item = result.records[0].item
    assert item is not None
    changed = replace_record(
        result,
        0,
        item=item.model_copy(
            update={
                "fields": tuple(
                    f.model_copy(update={"value": "1"}) if f.name == "value" else f
                    for f in item.fields
                )
            }
        ),
    )
    reviews = refresh_synthetic_decisions(changed, reviews)
    report = evaluate(
        source,
        plan,
        changed,
        gold,
        reviews,
        replace(pins, result_sha256=model_hash(changed), reviews_sha256=model_hash(reviews)),
    )
    assert report.metrics["field_constraints"].status == "failed"
    assert not report.local_item_gates_passed


def test_evaluation_has_no_implicit_io(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins
    import socket
    from pathlib import Path

    arguments = example()

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("evaluation attempted I/O")

    with monkeypatch.context() as guard:
        guard.setattr(builtins, "open", forbidden)
        guard.setattr(Path, "read_text", forbidden)
        guard.setattr(Path, "read_bytes", forbidden)
        guard.setattr(socket.socket, "connect", forbidden)
        report = evaluate(*arguments)
    assert report.local_item_gates_passed


def test_duplicate_quote_in_same_packet_is_legal_at_fixed_coordinates() -> None:
    arguments = example(repeated_quote=True)
    source, _, result, _, _, _ = arguments
    assert result.records[0].item is not None
    assert source.packets[0].text.count(result.records[0].item.text) == 2
    assert evaluate(*arguments).local_item_gates_passed


def test_all_rejections_cannot_hide_positive_targets() -> None:
    _, _, result, _, reviews, _ = example()
    changed = result
    for index in range(2):
        changed = replace_record(
            changed, index, terminal="no_supported_item", item=None, reason="no item"
        )
    reviews = refresh_synthetic_decisions(changed, reviews)
    reviews = reviews.model_copy(
        update={
            "decisions": tuple(
                d.model_copy(
                    update={
                        "target_id": None,
                        "fidelity": "not_applicable",
                        "atomicity": "not_applicable",
                        "constraints_retained": None,
                        "no_supported_item_confirmed": True,
                    }
                )
                for d in reviews.decisions
            )
        }
    )
    report = run_changed(changed, reviews)
    assert report.metrics["item_recall"].numerator == 0
    assert report.metrics["item_recall"].denominator == 2
    assert not report.local_item_gates_passed


def test_empty_output_cannot_pass_with_empty_precision_denominator() -> None:
    _, _, result, _, _, _ = example()
    changed = seal_result(result.model_copy(update={"records": ()}))
    report = run_changed(changed)
    assert report.metrics["item_precision"].status == "not_applicable"
    assert report.gates["G1"] == "failed"
    assert report.gates["G2"] == "failed"


def test_statement_role_is_not_silently_omitted_from_semantic_axes() -> None:
    _, _, result, _, reviews, _ = example()
    item = result.records[0].item
    assert item is not None
    changed = replace_record(
        result,
        0,
        item=item.model_copy(
            update={
                "fields": tuple(
                    f.model_copy(update={"value": "claim"}) if f.name == "statement_role" else f
                    for f in item.fields
                )
            }
        ),
    )
    report = run_changed(changed, refresh_synthetic_decisions(changed, reviews))
    assert report.metrics["axis/statement_role"].numerator == 1
    assert report.metrics["axis/statement_role"].denominator == 2
    assert report.gates["G3"] == "failed"
