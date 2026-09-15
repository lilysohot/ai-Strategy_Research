"""P2-A offline item evaluator. Never import this module from production.

No source loading, network, model, database, fuzzy matching or automatic semantic
judging. Human decisions arrive as externally pinned data; synthetic decisions
are usable only in explicitly synthetic cases. A local pass NEVER grants budget.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from p1_planner_spec import Plan, Source, Span, digest, resolve, source_binding, verify_plan
from pydantic import BaseModel, ConfigDict, Field, ValidationError

VERSION = "r2-evaluation-item-1"
PROTOCOL = "r2-obligation-item-1"
CONTRACT_SHA = "feebd1fd816ff824345185f7e3d690ea25621080d9d348f7d53bb82650763776"
AXES = (
    "semantic_type",
    "speaker_ref",
    "perspective",
    "speech_role",
    "polarity",
    "behavior_status",
    "temporal_frame",
    "value",
    "unit",
    "statement_role",
)
SEMANTIC_TYPES = ("fact", "forecast", "opinion", "behavior", "unknown")
ENUMS = {
    "semantic_type": SEMANTIC_TYPES,
    "perspective": ("source_explicit", "quoted_other", "system_synthesis", "unknown"),
    "speech_role": ("question", "answer", "statement", "unknown"),
    "statement_role": (
        "claim",
        "evidence",
        "condition",
        "risk",
        "question",
        "answer",
        "other",
        "unknown",
    ),
    "polarity": ("affirmed", "negated", "mixed", "unknown"),
    "behavior_status": ("intent", "claimed_executed", "claimed_not_executed", "unknown"),
    "temporal_frame": ("contemporaneous", "retrospective", "unknown"),
}
CRITICAL_AXES = tuple(axis for axis in AXES if axis != "semantic_type")
POLICY = {
    "version": VERSION,
    "contract_sha": CONTRACT_SHA,
    "item_recall_min": 1.0,
    "item_precision_min": 1.0,
    "fidelity_min": 1.0,
    "semantic_precision_min": 0.9,
    "semantic_recall_min": 0.9,
    "critical_errors_max": 0,
    "unresolved_max": 0,
    "critical_axis_accuracy_min": 1.0,
}
POLICY_SHA256 = digest(POLICY)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SemanticField(Strict):
    name: str
    value: str | None
    origin: Literal["source_observed", "validated_transform", "model_interpreted", "unknown"]
    support_span_ids: tuple[str, ...]
    transform_rule_id: str | None = None
    unknown_reason: str | None = None


class Item(Strict):
    item_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    constraints: tuple[str, ...]
    fields: tuple[SemanticField, ...]
    evidence_span_ids: tuple[str, ...]


class Record(Strict):
    obligation_id: str = Field(min_length=1)
    terminal: Literal["extracted", "no_supported_item", "unresolved", "failed", "deferred"]
    item: Item | None
    reason: str | None
    evidence_span_ids: tuple[str, ...]
    response_received: bool


class Result(Strict):
    """Normalized evaluator input, NOT the provider wire format.

    P2-B must derive response_received/audit_complete from validated raw-response
    and attempt artifacts. P2-A only checks these assertions and never grants a
    runtime or budget pass; independent audit validation is not implemented here.
    """

    protocol_version: Literal["r2-obligation-item-1"]
    plan_id: str
    result_id: str
    records: tuple[Record, ...]
    protocol_errors: tuple[str, ...]
    audit_complete: bool


class Target(Strict):
    target_id: str = Field(min_length=1)
    evidence_span_ids: tuple[str, ...]
    # Annotation labels are independent of model output. None means required unknown.
    fields: tuple[tuple[str, str | None], ...]


class Gold(Strict):
    version: str
    source_binding: str
    atomic_denominator_approved: bool
    targets: tuple[Target, ...]


class Decision(Strict):
    record_sha256: str
    reviewer_id: str
    reviewer_kind: Literal["human", "agent_proposal", "synthetic_fixture"]
    status: Literal["approved", "proposed"]
    reviewed_at: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    target_id: str | None
    fidelity: Literal["faithful", "unsupported", "unknown", "not_applicable"]
    atomicity: Literal["single", "multiple", "unknown", "not_applicable"]
    constraints_retained: bool | None
    no_supported_item_confirmed: bool
    critical_errors: tuple[str, ...]


class Reviews(Strict):
    source_binding: str
    plan_id: str
    contract_sha256: str
    gold_sha256: str
    result_sha256: str
    decisions: tuple[Decision, ...]


@dataclass(frozen=True)
class Pins:
    """Trusted runner inputs, never taken from model output or the review file itself."""

    case_id: str
    material_class: str
    mode: Literal["synthetic", "development"]
    source_sha256: str
    plan_id: str
    result_sha256: str
    gold_sha256: str
    reviews_sha256: str
    contract_sha256: str
    policy_sha256: str
    human_reviewers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Metric:
    numerator: int
    denominator: int
    direction: str
    threshold: float
    status: str


def metric(numerator: int, denominator: int, direction: str, threshold: float) -> Metric:
    if (
        type(numerator) is not int
        or type(denominator) is not int
        or numerator < 0
        or denominator < 0
        or direction not in ("min", "max")
        or type(threshold) not in (int, float)
        or not math.isfinite(threshold)
    ):
        raise ValueError("invalid_metric")
    if denominator == 0:
        return Metric(numerator, denominator, direction, threshold, "not_applicable")
    observed, bound = Fraction(numerator, denominator), Fraction(str(threshold))
    passed = observed >= bound if direction == "min" else observed <= bound
    return Metric(numerator, denominator, direction, threshold, "passed" if passed else "failed")


@dataclass(frozen=True)
class EvaluationReport:
    version: str
    case_id: str
    material_class: str
    mode: str
    bindings: Pins
    gates: dict[str, str]
    metrics: dict[str, Metric]
    errors: tuple[str, ...]
    needs_review: tuple[str, ...]
    local_item_gates_passed: bool
    budget_authorized: bool = False


def model_hash(model: Strict) -> str:
    return digest(model.model_dump(mode="json"))


def seal_result(result: Result) -> Result:
    payload = result.model_dump(mode="json")
    payload["result_id"] = ""
    return result.model_copy(update={"result_id": digest(payload)})


def _rehydrate(model: Strict) -> Strict:
    # model_copy/update and object construction can bypass Pydantic validation.
    return type(model).model_validate_json(model.model_dump_json())


def _allowed_spans(plan: Plan) -> dict[str, Span]:
    return {
        span.span_id: span
        for obligation in plan.obligations
        for span in (obligation.focus, obligation.support, *obligation.context)
    }


def _field_errors(item: Item, spans: dict[str, Span], source: Source) -> list[str]:
    errors: list[str] = []
    if Counter(field.name for field in item.fields) != Counter(AXES):
        errors.append("field_inventory")
    for field in item.fields:
        value = field.value
        if field.name in ENUMS and value not in (*ENUMS[field.name], None):
            errors.append("field_enum")
        if any(ref not in spans for ref in field.support_span_ids):
            errors.append("field_evidence")
            continue
        if field.origin == "unknown":
            if (
                value not in (None, "unknown")
                or not field.unknown_reason
                or not field.unknown_reason.strip()
            ):
                errors.append("unknown_contradiction")
            if field.transform_rule_id:
                errors.append("unknown_transform")
            continue
        if value in (None, "unknown") or field.unknown_reason or not field.support_span_ids:
            errors.append("known_unknown_contradiction")
            continue
        if field.origin == "validated_transform":
            # No transform is implemented/approved in P2-A; do not guess a conversion.
            errors.append("unsupported_transform")
        elif field.transform_rule_id:
            errors.append("unexpected_transform")
        if field.name in ("value", "unit"):
            bodies = [resolve(source, spans[ref]) for ref in field.support_span_ids]
            if field.name == "value":
                observed = any(
                    value in re.findall(r"(?<![\d.,])[+-]?\d+(?:,\d{3})*(?:\.\d+)?", body)
                    for body in bodies
                )
            else:
                raw_value = next((f.value for f in item.fields if f.name == "value"), None)
                # Conservative literal pair, not a general unit conversion rule.
                observed = bool(
                    raw_value
                    and any(
                        re.search(
                            r"(?<![\d.,])"
                            + re.escape(raw_value)
                            + r"\s*"
                            + re.escape(value)
                            + r"(?![A-Za-z\u4e00-\u9fff%％])",
                            body,
                        )
                        for body in bodies
                    )
                )
            if field.origin != "source_observed" or not observed:
                errors.append("numeric_source_binding")
        elif field.origin != "model_interpreted":
            errors.append("semantic_origin_escalation")
    return errors


def evaluate(
    source: Source, plan: Plan, result: Result, gold: Gold, reviews: Reviews, pins: Pins
) -> EvaluationReport:
    """Evaluate G0-G3 on a pinned case; G4-G7 remain explicitly not evaluated.

    The caller authenticates Pins and human reviewer identities. Hashes ensure
    binding, not that a reviewer is honest or that arbitrary language is true.
    """
    gates = {f"G{index}": "not_evaluated" for index in range(8)}
    metrics: dict[str, Metric] = {}
    errors: list[str] = []
    pending: list[str] = []

    def report() -> EvaluationReport:
        return EvaluationReport(
            VERSION,
            pins.case_id,
            pins.material_class,
            pins.mode,
            pins,
            dict(gates),
            dict(metrics),
            tuple(errors),
            tuple(pending),
            all(gates[f"G{i}"] == "passed" for i in range(4)),
        )

    try:
        if (
            pins.mode not in ("synthetic", "development")
            or not pins.case_id
            or not pins.material_class
        ):
            raise ValueError("case_identity")
        if (
            pins.contract_sha256 != CONTRACT_SHA
            or pins.policy_sha256 != POLICY_SHA256
            or digest(POLICY) != POLICY_SHA256
        ):
            raise ValueError("contract_or_policy_binding")
        for model in (result, gold, reviews):
            _rehydrate(model)
        verify_plan(source, pins.source_sha256, plan, pins.plan_id)
        if source_binding(source) != pins.source_sha256 or result.plan_id != pins.plan_id:
            raise ValueError("source_or_plan_binding")
        if (
            seal_result(result).result_id != result.result_id
            or model_hash(result) != pins.result_sha256
        ):
            raise ValueError("result_binding")
        if model_hash(gold) != pins.gold_sha256 or model_hash(reviews) != pins.reviews_sha256:
            raise ValueError("gold_or_review_binding")
        if gold.source_binding != pins.source_sha256:
            raise ValueError("gold_source_binding")
        if (
            reviews.source_binding != pins.source_sha256
            or reviews.plan_id != pins.plan_id
            or reviews.contract_sha256 != pins.contract_sha256
            or reviews.gold_sha256 != pins.gold_sha256
        ):
            raise ValueError("review_context_binding")
        spans = _allowed_spans(plan)
        for span in spans.values():
            resolve(source, span)
        targets = {target.target_id: target for target in gold.targets}
        if len(targets) != len(gold.targets):
            raise ValueError("duplicate_gold_target")
        for target in gold.targets:
            if Counter(name for name, _ in target.fields) != Counter(AXES):
                raise ValueError("gold_field_inventory")
            if not target.evidence_span_ids or any(
                ref not in spans for ref in target.evidence_span_ids
            ):
                raise ValueError("gold_scope_binding")
        if len({d.record_sha256 for d in reviews.decisions}) != len(reviews.decisions):
            raise ValueError("duplicate_review")
    except (ValueError, TypeError, AttributeError, ValidationError) as exc:
        gates["G0"] = "failed"
        # Pydantic error strings can contain private output text; emit codes only.
        code = str(exc) if type(exc) is ValueError else type(exc).__name__
        errors.append(f"binding:{code}")
        return report()

    gates["G0"] = "passed"
    obligations = {o.obligation_id: o for o in plan.obligations}
    counts = Counter(record.obligation_id for record in result.records)
    protocol_bad = len(result.protocol_errors)
    protocol_bad += sum(count != 1 for count in counts.values())
    protocol_bad += len(set(obligations) - set(counts)) + len(set(counts) - set(obligations))
    item_ids = [record.item.item_id for record in result.records if record.item is not None]
    protocol_bad += len(item_ids) - len(set(item_ids))
    if not result.audit_complete:
        errors.append("audit_incomplete")
        protocol_bad += 1
    decisions = {decision.record_sha256: decision for decision in reviews.decisions}
    fresh_reviews = reviews.result_sha256 == pins.result_sha256
    resolved = 0
    faithful = 0
    item_total = sum(record.item is not None for record in result.records)
    critical = 0
    field_failures = 0
    mapped: set[str] = set()
    semantic_tp: Counter[str] = Counter()
    semantic_pred: Counter[str] = Counter(
        next((field.value for field in record.item.fields if field.name == "semantic_type"), None)
        or "unknown"
        for record in result.records
        if record.item is not None
    )
    semantic_gold: Counter[str] = Counter(
        dict(target.fields)["semantic_type"] or "unknown" for target in gold.targets
    )
    axis_correct: Counter[str] = Counter()
    judged_items = 0
    for record in result.records:
        oid = record.obligation_id
        obligation = obligations.get(oid)
        if obligation is None or counts[oid] != 1:
            errors.append(f"protocol:unknown_or_duplicate:{oid}")
            continue
        own_spans = {
            s.span_id: s for s in (obligation.focus, obligation.support, *obligation.context)
        }
        refs = record.evidence_span_ids
        local_bad = 0
        if (
            not refs
            or any(ref not in own_spans for ref in refs)
            or obligation.focus.span_id not in refs
        ):
            gates["G0"] = "failed"
            errors.append(f"evidence:record:{oid}")
            critical += 1
            local_bad += 1
        if record.terminal == "extracted":
            local_bad += int(record.item is None)
        else:
            local_bad += int(
                record.item is not None or not record.reason or not record.reason.strip()
            )
        if obligation.state == "unresolved" and record.terminal != "unresolved":
            local_bad += 1
            errors.append(f"protocol:planner_unresolved:{oid}")
        if record.terminal in ("extracted", "no_supported_item") and not record.response_received:
            local_bad += 1
        if record.terminal in ("failed", "deferred") or not record.response_received:
            # Even a system-supplied terminal cannot erase missing model responses.
            local_bad += 1
        protocol_bad += local_bad
        if record.item is not None:
            item = record.item
            if (
                not item.text.strip()
                or not item.evidence_span_ids
                or any(ref not in own_spans for ref in item.evidence_span_ids)
                or obligation.focus.span_id not in item.evidence_span_ids
            ):
                gates["G0"] = "failed"
                critical += 1
                errors.append(f"evidence:item:{oid}")
            item_errors = _field_errors(item, own_spans, source)
            if item_errors:
                field_failures += len(item_errors)
                errors.extend(f"field:{oid}:{code}" for code in item_errors)

        decision = decisions.get(model_hash(record)) if fresh_reviews else None
        trusted = bool(
            decision
            and decision.status == "approved"
            and (
                (pins.mode == "synthetic" and decision.reviewer_kind == "synthetic_fixture")
                or (
                    decision.reviewer_kind == "human"
                    and decision.reviewer_id in pins.human_reviewers
                )
            )
        )
        if not trusted or decision is None:
            pending.append(f"record_review:{oid}")
            continue
        critical += len(decision.critical_errors)
        if record.terminal == "no_supported_item":
            if (
                decision.no_supported_item_confirmed
                and decision.target_id is None
                and decision.fidelity == "not_applicable"
                and not decision.critical_errors
                and not local_bad
            ):
                resolved += 1
            else:
                errors.append(f"no_supported_item_not_confirmed:{oid}")
            continue
        if record.terminal != "extracted" or record.item is None:
            continue
        judged_items += 1
        if decision.fidelity == "unknown" or decision.atomicity == "unknown":
            pending.append(f"semantic_review:{oid}")
        content_ok = (
            decision.fidelity == "faithful"
            and decision.atomicity == "single"
            and decision.constraints_retained is True
            and not decision.critical_errors
        )
        if content_ok:
            faithful += 1
        else:
            errors.append(f"fidelity_or_atomicity:{oid}")
        target = targets.get(decision.target_id or "")
        if target is None or target.target_id in mapped:
            errors.append(f"unsupported_or_duplicate_mapping:{oid}")
            continue
        # A reviewed mapping cannot silently attach an unrelated source scope.
        if not set(target.evidence_span_ids).intersection(record.item.evidence_span_ids):
            errors.append(f"target_scope_mismatch:{oid}")
            critical += 1
            continue
        mapped.add(target.target_id)
        expected = dict(target.fields)
        actual = {field.name: field.value for field in record.item.fields}
        for axis in AXES:
            wanted = expected[axis]
            got = actual.get(axis)
            # Only the explicit unknown sentinel and null are equivalent, no fuzzy aliases.
            correct = got == wanted or (got in (None, "unknown") and wanted in (None, "unknown"))
            if correct:
                axis_correct[axis] += 1
                if axis == "semantic_type":
                    semantic_tp[wanted or "unknown"] += 1
            elif axis in CRITICAL_AXES:
                critical += 1
                errors.append(f"critical_axis:{oid}:{axis}")
        if content_ok and not local_bad:
            resolved += 1

    if not gold.atomic_denominator_approved:
        pending.append("atomic_gold_denominator_not_approved")
    metrics["protocol_errors"] = metric(protocol_bad, 1, "max", 0)
    metrics["unresolved_content"] = metric(len(obligations) - resolved, 1, "max", 0)
    metrics["item_recall"] = metric(len(mapped), len(targets), "min", POLICY["item_recall_min"])
    metrics["item_precision"] = metric(len(mapped), item_total, "min", POLICY["item_precision_min"])
    metrics["content_fidelity"] = metric(faithful, item_total, "min", POLICY["fidelity_min"])
    metrics["critical_errors"] = metric(critical, 1, "max", POLICY["critical_errors_max"])
    metrics["review_coverage"] = metric(judged_items, item_total, "min", 1.0)
    metrics["field_constraints"] = metric(field_failures, 1, "max", 0)
    for axis in CRITICAL_AXES:
        metrics[f"axis/{axis}"] = metric(
            axis_correct[axis], max(len(targets), item_total), "min", 1.0
        )
    for label in set(semantic_gold) | set(semantic_pred):
        metrics[f"semantic/{label}/precision"] = metric(
            semantic_tp[label], semantic_pred[label], "min", 0.9
        )
        metrics[f"semantic/{label}/recall"] = metric(
            semantic_tp[label], semantic_gold[label], "min", 0.9
        )
    gates["G1"] = "passed" if protocol_bad == 0 and resolved == len(obligations) else "failed"
    g2 = ("item_recall", "item_precision", "content_fidelity", "critical_errors", "review_coverage")
    gates["G2"] = "passed" if all(metrics[key].status == "passed" for key in g2) else "failed"
    if pending:
        gates["G2"] = "needs_review" if gates["G2"] == "passed" else gates["G2"]
        if any(
            key.startswith("record_review:") or key.startswith("semantic_review:")
            for key in pending
        ):
            errors.append("unreviewed_output_blocks_acceptance")
    if not gold.atomic_denominator_approved and gates["G2"] == "passed":
        gates["G2"] = "needs_review"
    g3_required = [key for key in metrics if key.startswith(("axis/", "semantic/"))]
    # A label absent from one side has a failing recall or precision on the other;
    # its zero-denominator counterpart is N/A, never a substitute for that failure.
    gates["G3"] = (
        "passed"
        if (
            g3_required
            and field_failures == 0
            and critical == 0
            and all(metrics[key].status in ("passed", "not_applicable") for key in g3_required)
            and any(metrics[key].status == "passed" for key in g3_required)
        )
        else "failed"
    )
    return report()
