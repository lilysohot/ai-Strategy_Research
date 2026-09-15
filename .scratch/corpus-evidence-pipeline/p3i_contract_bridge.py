"""P3-I development-only projection from approved material gold to the P1 item axes.

The projection is evaluator input only. It is never included in a model request and
does not alter the frozen production R2 modules, source gold, or P3 denominator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import p3_replay_review as p3
import p3h_review
import p3r_review
import p3s_review

from plugins.corpus._r2_plan import digest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
P3S_REVIEW = HERE / "r2-p3s-denominator-review-completed.json"
P3H_REVIEW = HERE / "r2-p3h-remediation-review-completed.json"
P3H_MANIFEST = HERE / "r2-p3h-manifest.json"
P2_EVALUATOR = HERE / "r2_evaluation_v1.py"
P2_RUNTIME = ROOT / "plugins/corpus/_r2_runtime.py"
P1_AXES = (
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
DIRECT_AXES = (
    "semantic_type",
    "perspective",
    "speech_role",
    "polarity",
    "behavior_status",
    "temporal_frame",
    "statement_role",
)
PINS = {
    P3S_REVIEW: "e171ce7b02bb11b77a86d08a0880d9d42da7990fedf94b3976fe931b5c79a609",
    P3H_REVIEW: "5fe77427e1fc0727ccd16bc8542f26a0f9619161cfad40f1c22e3270a9f46275",
    P3H_MANIFEST: "d2282d831c6bc069a1819f2fae64b2d68336c9dbbf97eb02fcc47f79747533c3",
    p3.MICRO_GOLD: "214b1f49f82e36c7c2b59496ada20228730439d0bc4b6f17fc51ff87122077c5",
    p3h_review.AMENDMENT: "f60f1e9fa5050065c947158dd134e4cdb9f9055a591b46d17d084e495f6c36b1",
    P2_EVALUATOR: "2a6b138a7d3720335b585f4c0760c51f4768a571eca3652c538be759562c0aeb",
    P2_RUNTIME: "2f8f025177721b74038ea469ee34b55120ce7ac9bf7b35419b9d801f8bd0546b",
}
EFFECTIVE_SHA256 = "3f5e972425074dc3640be8f7b9d80617e7cd78d89034b75b089b03d3dea1577d"
TRANSFORM_RULES = {
    "mc-eps-forecast": "compose_explicit_year_range_and_eps_values_v1",
    "mt-added-shares": "drop_nonsemantic_more_token_v1",
    "mt-sold-calls": "normalize_trade_price_preposition_and_omit_unresolved_date_v1",
}
UNIT_PROPOSALS = {
    "mc-eps-forecast": "元",
    "mc-target-price": "元",
    "mt-sold-calls": "$",
    "mt-below-ceo-level": "$",
    "mt-ceo-bought": "$",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def normalized(value: object) -> str:
    return "".join(str(value or "").lower().split())


def _verify_pins() -> None:
    for path, expected in PINS.items():
        if sha(path) != expected:
            raise ValueError(f"frozen_pin_changed:{path.name}")


def _effective() -> dict[str, Any]:
    base = json.loads(p3.MICRO_GOLD.read_text(encoding="utf-8"))
    amendment = json.loads(p3h_review.AMENDMENT.read_text(encoding="utf-8"))
    effective = p3h_review.apply_amendment(base, amendment)
    if json_sha(effective) != EFFECTIVE_SHA256:
        raise ValueError("effective_denominator_binding")
    return effective


def _approved_records(effective_ids: set[str]) -> dict[str, dict[str, Any]]:
    old = json.loads(P3S_REVIEW.read_text(encoding="utf-8"))
    p3s_review.validate_human_review(old)
    replacement = json.loads(P3H_REVIEW.read_text(encoding="utf-8"))
    status = p3h_review.validate_remediation_review(replacement)
    if not status["all_approved"]:
        raise ValueError("replacement_review_not_approved")
    records = {
        record["target_id"]: record
        for record in (*old["records"], *replacement["records"])
        if record["target_id"] in effective_ids and record["human_decision"] == "approve"
    }
    if set(records) != effective_ids or len(records) != 35:
        raise ValueError("approved_target_set")
    return records


def _speaker_ref(scope_id: str, role: str, identity_status: str) -> str:
    return "spk-" + digest(["p3i-speaker-registry-1", scope_id, role, identity_status])[:20]


def _number_tokens(value: str) -> tuple[str, ...]:
    return tuple(re.findall(r"(?<![\d.,])\d+(?:,\d{3})*(?:\.\d+)?|(?<!\d)\.\d+", value))


def _value_projection(item: dict[str, Any]) -> dict[str, Any]:
    value = item["value"]
    if value is None:
        return {
            "value": None,
            "value_origin": "unknown",
            "transform_rule_id": None,
            "value_binding": "not_applicable_qualitative_item",
            "unit": None,
            "unit_origin": "unknown",
            "unit_treatment": "no_scalar_value",
        }
    quote = item["quote"]
    literal = normalized(value) in normalized(quote)
    rule = TRANSFORM_RULES.get(item["item_id"])
    if not literal:
        if rule is None or any(token not in quote for token in _number_tokens(value)):
            raise ValueError(f"unbound_value_projection:{item['item_id']}")
        origin = "validated_transform"
        binding = "all_numeric_tokens_source_bound_transform_pending_human_review"
    else:
        if rule is not None:
            raise ValueError(f"unnecessary_transform:{item['item_id']}")
        origin = "source_observed"
        binding = "normalized_literal_substring"
    unit = UNIT_PROPOSALS.get(item["item_id"])
    if unit is not None and unit not in quote:
        raise ValueError(f"unit_not_source_observed:{item['item_id']}")
    numeric_count = len(_number_tokens(value))
    if unit is None:
        treatment = "no_single_explicit_scalar_unit"
        unit_origin = "unknown"
    else:
        treatment = (
            "explicit_unit_with_composite_value"
            if numeric_count > 1
            else "explicit_unit_single_value"
        )
        unit_origin = "source_observed"
    return {
        "value": value,
        "value_origin": origin,
        "transform_rule_id": rule,
        "value_binding": binding,
        "unit": unit,
        "unit_origin": unit_origin,
        "unit_treatment": treatment,
    }


def _project_record(
    scope: dict[str, Any],
    item: dict[str, Any],
    node_row: dict[str, Any],
    approval: dict[str, Any],
) -> dict[str, Any]:
    if node_row["mapping_status"] != "unique_minimum" or len(node_row["candidate_nodes"]) != 1:
        raise ValueError(f"node_mapping:{item['item_id']}")
    node = node_row["candidate_nodes"][0]
    if approval["proposed_clause_nodes"] != node_row["candidate_nodes"]:
        raise ValueError(f"human_node_binding:{item['item_id']}")
    if normalized(item["quote"]) not in normalized(node["text"]):
        raise ValueError(f"quote_node_binding:{item['item_id']}")
    speaker_ref = _speaker_ref(scope["scope_id"], item["speaker_role"], item["identity_status"])
    value = _value_projection(item)
    fields = {axis: item[axis] for axis in DIRECT_AXES}
    fields.update(speaker_ref=speaker_ref, value=value["value"], unit=value["unit"])
    if tuple(fields) != P1_AXES:
        fields = {axis: fields[axis] for axis in P1_AXES}
    constraints = [f"unknown_field:{name}" for name in item["unknown_fields"]]
    return {
        "target_id": item["item_id"],
        "scope_id": scope["scope_id"],
        "sample_id": scope["sample_id"],
        "source_quote": item["quote"],
        "approved_node": node,
        "projected_fields": fields,
        "speaker_projection": {
            "speaker_ref": speaker_ref,
            "speaker_role": item["speaker_role"],
            "identity_status": item["identity_status"],
            "rule": "scope_role_identity_registry_v1",
        },
        "value_projection": value,
        "constraints": constraints,
        "constraint_rule": "unknown_fields_to_prefixed_constraints_v1",
        "evaluation_only": True,
        "human_atomic_review_sha256": sha(P3H_REVIEW)
        if item["item_id"] in p3h_review.PENDING_IDS
        else sha(P3S_REVIEW),
    }


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the complete projection and the smaller bridge-specific review interface."""
    _verify_pins()
    effective = _effective()
    items = {item["item_id"] for scope in effective["scopes"] for item in scope["items"]}
    approvals = _approved_records(items)
    _, node_queue = p3r_review.micro_review(effective["scopes"])
    nodes = {record["target_id"]: record for record in node_queue}
    if set(nodes) != items:
        raise ValueError("node_target_set")
    records = [
        _project_record(scope, item, nodes[item["item_id"]], approvals[item["item_id"]])
        for scope in effective["scopes"]
        for item in scope["items"]
    ]
    registry_by_ref: dict[str, dict[str, str]] = {}
    for record in records:
        speaker = record["speaker_projection"]
        entry = {
            "speaker_ref": speaker["speaker_ref"],
            "scope_id": record["scope_id"],
            "speaker_role": speaker["speaker_role"],
            "identity_status": speaker["identity_status"],
        }
        old = registry_by_ref.setdefault(speaker["speaker_ref"], entry)
        if old != entry:
            raise ValueError("speaker_registry_collision")
    transforms = Counter(record["value_projection"]["value_origin"] for record in records)
    units = Counter(record["value_projection"]["unit_treatment"] for record in records)
    inventory = {
        "version": "r2-p3i-field-contract-projection-1",
        "split": "development",
        "purpose": "evaluation_target_projection_only_never_model_input",
        "bindings": {
            "effective_denominator_sha256": EFFECTIVE_SHA256,
            "p3s_review_sha256": sha(P3S_REVIEW),
            "p3h_review_sha256": sha(P3H_REVIEW),
            "p2_evaluator_sha256": sha(P2_EVALUATOR),
            "p2_runtime_sha256": sha(P2_RUNTIME),
        },
        "contract": {
            "base_protocol": "r2-obligation-item-1",
            "projection_version": "p3i-field-projection-1",
            "axes": list(P1_AXES),
            "speaker_rule": "scope_role_identity_registry_v1",
            "value_rule": "literal_expression_or_three_allowlisted_transforms_v1",
            "unit_rule": "explicit_source_symbol_else_unknown_v1",
            "constraint_rule": "unknown_fields_to_prefixed_constraints_v1",
            "runtime_change_required_after_human_approval": True,
        },
        "counts": {
            "records": len(records),
            "speaker_registry_entries": len(registry_by_ref),
            "non_null_values": sum(record["projected_fields"]["value"] is not None for record in records),
            "value_origins": dict(transforms),
            "unit_treatments": dict(units),
            "unknown_constraints": sum(len(record["constraints"]) for record in records),
        },
        "speaker_registry": sorted(registry_by_ref.values(), key=lambda row: row["speaker_ref"]),
        "records": records,
        "gates": {
            "I0_frozen_inputs": "passed",
            "I1_approved_35_target_identity": "passed",
            "I2_speaker_projection_reversible": "passed",
            "I3_value_and_unit_source_binding": "passed",
            "I4_unknown_constraints_lossless": "passed",
            "I5_production_and_old_flow_isolation": "passed",
            "I6_bridge_human_approval": "not_evaluated",
        },
        "model_calls": 0,
        "postgres_access": 0,
        "holdout_reads": 0,
        "ingestion_runs": 0,
        "p4_budget_authorized": False,
    }
    review = {
        "version": "r2-p3i-field-bridge-human-review-1",
        "split": "development",
        "projection_sha256": json_sha(inventory),
        "reviewer_name": None,
        "reviewed_at": None,
        "policy_decision": None,
        "policy_reason": None,
        "policy_checks": {
            "speaker_reference_preserves_role_and_identity_status": None,
            "unknown_fields_are_losslessly_preserved_as_constraints": None,
            "projection_is_evaluation_only_and_must_not_enter_model_prompts": None,
        },
        "approved_speaker_entries": 0,
        "speaker_entries": [
            {
                **entry,
                "human_decision": None,
                "human_reason": None,
                "reversible_mapping_ok": None,
            }
            for entry in inventory["speaker_registry"]
        ],
        "approved_value_records": 0,
        "value_records": [
            {
                "target_id": record["target_id"],
                "scope_id": record["scope_id"],
                "source_quote": record["source_quote"],
                **record["value_projection"],
                "human_decision": None,
                "human_reason": None,
                "value_expression_lossless": None,
                "unit_treatment_acceptable": None,
            }
            for record in records
            if record["projected_fields"]["value"] is not None
        ],
        "allowed_decisions": ["approve", "needs_revision", "reject"],
        "instructions": "Review only the bridge rules and eight value/unit projections; direct semantic axes and atomicity are already frozen inputs.",
    }
    return inventory, review


def validate_review(review: dict[str, Any], projection: dict[str, Any]) -> dict[str, Any]:
    allowed = {"approve", "needs_revision", "reject"}
    if review.get("projection_sha256") != json_sha(projection):
        raise ValueError("review_projection_binding")
    if set(review.get("allowed_decisions", ())) != allowed:
        raise ValueError("review_decision_contract")
    if not isinstance(review.get("reviewer_name"), str) or not review["reviewer_name"].strip():
        raise ValueError("reviewer")
    if not isinstance(review.get("reviewed_at"), str) or not review["reviewed_at"].strip():
        raise ValueError("reviewed_at")
    checks = review.get("policy_checks")
    if not isinstance(checks, dict) or set(checks) != {
        "speaker_reference_preserves_role_and_identity_status",
        "unknown_fields_are_losslessly_preserved_as_constraints",
        "projection_is_evaluation_only_and_must_not_enter_model_prompts",
    } or any(type(value) is not bool for value in checks.values()):
        raise ValueError("policy_checks")
    if review.get("policy_decision") not in allowed or not isinstance(review.get("policy_reason"), str) or not review["policy_reason"].strip():
        raise ValueError("policy_decision")
    if review["policy_decision"] == "approve" and not all(checks.values()):
        raise ValueError("policy_approve_contradiction")
    expected_speakers = {row["speaker_ref"] for row in projection["speaker_registry"]}
    speakers = review.get("speaker_entries")
    if not isinstance(speakers, list) or {row.get("speaker_ref") for row in speakers} != expected_speakers or len(speakers) != len(expected_speakers):
        raise ValueError("speaker_review_identity")
    expected_values = {
        row["target_id"] for row in projection["records"] if row["projected_fields"]["value"] is not None
    }
    values = review.get("value_records")
    if not isinstance(values, list) or {row.get("target_id") for row in values} != expected_values or len(values) != len(expected_values):
        raise ValueError("value_review_identity")
    speaker_approved = 0
    for row in speakers:
        if row.get("human_decision") not in allowed or not isinstance(row.get("human_reason"), str) or not row["human_reason"].strip() or type(row.get("reversible_mapping_ok")) is not bool:
            raise ValueError(f"speaker_review:{row.get('speaker_ref')}")
        if row["human_decision"] == "approve":
            if not row["reversible_mapping_ok"]:
                raise ValueError(f"speaker_approve_contradiction:{row['speaker_ref']}")
            speaker_approved += 1
    value_approved = 0
    for row in values:
        if row.get("human_decision") not in allowed or not isinstance(row.get("human_reason"), str) or not row["human_reason"].strip() or type(row.get("value_expression_lossless")) is not bool or type(row.get("unit_treatment_acceptable")) is not bool:
            raise ValueError(f"value_review:{row.get('target_id')}")
        if row["human_decision"] == "approve":
            if not row["value_expression_lossless"] or not row["unit_treatment_acceptable"]:
                raise ValueError(f"value_approve_contradiction:{row['target_id']}")
            value_approved += 1
    if review.get("approved_speaker_entries") != speaker_approved:
        raise ValueError("speaker_approved_count")
    if review.get("approved_value_records") != value_approved:
        raise ValueError("value_approved_count")
    all_approved = (
        review["policy_decision"] == "approve"
        and speaker_approved == len(speakers)
        and value_approved == len(values)
    )
    return {
        "status": "complete",
        "policy_decision": review["policy_decision"],
        "speaker_entries": len(speakers),
        "approved_speaker_entries": speaker_approved,
        "value_records": len(values),
        "approved_value_records": value_approved,
        "all_approved": all_approved,
    }


def write_once(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--review-template", type=Path)
    parser.add_argument("--validate-review", type=Path)
    args = parser.parse_args()
    projection, template = build()
    if args.validate_review:
        completed = json.loads(args.validate_review.read_text(encoding="utf-8"))
        print(json.dumps(validate_review(completed, projection), ensure_ascii=False, indent=2))
    elif args.inventory is not None and args.review_template is not None:
        write_once(args.inventory, projection)
        write_once(args.review_template, template)
        print(json.dumps({"status": "projection_built_human_review_required", "counts": projection["counts"], "gates": projection["gates"]}, ensure_ascii=False, indent=2))
    else:
        parser.error("provide --validate-review or both --inventory and --review-template")
