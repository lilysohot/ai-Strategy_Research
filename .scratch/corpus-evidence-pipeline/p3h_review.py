"""Apply and verify the P3-H human denominator amendment without model calls."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import p3_replay_review as p3
import p3r_review
import p3s_review
import p3s_scope_provider as scope_provider

from plugins.corpus._r2_plan import source_binding

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
AMENDMENT = HERE / "r2-p3h-denominator-amendment-v1.json"
COMPLETED_REVIEW = HERE / "r2-p3s-denominator-review-completed.json"
PINS = {
    HERE / "r2-p3h-change-scope.json": (
        "b7117037a7cdeac6f91e41b7c805f167cf4d764f8bb285612ba212b3b0d24da1"
    ),
    HERE / "r2-p3s-manifest.json": (
        "c4aa7c87e6abb706ef3d8e53acfcaed54500c82e17e44ac56091647066590512"
    ),
    COMPLETED_REVIEW: "e171ce7b02bb11b77a86d08a0880d9d42da7990fedf94b3976fe931b5c79a609",
    HERE / "r2-p3s-denominator-review-template.json": (
        "443d6136e35924ff0bf2bd8c9291c3a4d5c60eed04c34a3e427344026b2f6d59"
    ),
    AMENDMENT: "f60f1e9fa5050065c947158dd134e4cdb9f9055a591b46d17d084e495f6c36b1",
    p3.MICRO_GOLD: "214b1f49f82e36c7c2b59496ada20228730439d0bc4b6f17fc51ff87122077c5",
}
EXPECTED_NON_APPROVALS = {
    "mc-rating": "needs_split",
    "mi-a-focus-spread": "needs_merge",
    "mcs-outlook": "needs_split",
    "mca-hearing-check": "reject",
}
PENDING_IDS = {
    "mc-rating-v2",
    "mi-a-focus-balance-spread-v2",
    "mcs-industry-substitution-v2",
    "mcs-taijin-growth-v2",
    "mcs-surface-treatment-v2",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def verify_pins() -> None:
    for path, expected in PINS.items():
        if sha(path) != expected:
            raise ValueError(f"frozen_pin_changed:{path.name}")


def load_human_review() -> dict[str, Any]:
    review = json.loads(COMPLETED_REVIEW.read_text(encoding="utf-8"))
    result = p3s_review.validate_human_review(review)
    decisions = {
        record["target_id"]: record["human_decision"]
        for record in review["records"]
        if record["human_decision"] != "approve"
    }
    if decisions != EXPECTED_NON_APPROVALS or result["decisions"] != {
        "approve": 31,
        "needs_split": 2,
        "needs_merge": 1,
        "reject": 1,
    }:
        raise ValueError("human_decision_binding")
    return review


def _replace_items(scope: dict[str, Any], operation: dict[str, Any]) -> None:
    remove_ids = set(operation["remove_item_ids"])
    current_ids = {item["item_id"] for item in scope["items"]}
    if not remove_ids <= current_ids:
        raise ValueError("amendment_remove_item")
    remaining = [item for item in scope["items"] if item["item_id"] not in remove_ids]
    added = copy.deepcopy(operation["add_items"])
    new_ids = [item["item_id"] for item in added]
    if len(new_ids) != len(set(new_ids)) or set(new_ids) & {item["item_id"] for item in remaining}:
        raise ValueError("amendment_add_item")
    scope["items"] = remaining + added


def apply_amendment(base: dict[str, Any], amendment: dict[str, Any]) -> dict[str, Any]:
    """Return an amended copy; the frozen base object is never mutated."""
    if amendment["base_gold_sha256"] != sha(p3.MICRO_GOLD):
        raise ValueError("amendment_base_binding")
    if amendment["human_review_sha256"] != sha(COMPLETED_REVIEW):
        raise ValueError("amendment_human_binding")
    result = copy.deepcopy(base)
    scopes = {scope["scope_id"]: scope for scope in result["scopes"]}
    for operation in amendment["operations"]:
        scope = scopes.get(operation["scope_id"])
        if scope is None:
            raise ValueError("amendment_scope")
        _replace_items(scope, operation)
        remove_relations = set(operation.get("remove_relation_ids", ()))
        if remove_relations:
            current = {relation["relation_id"] for relation in scope["relations"]}
            if not remove_relations <= current:
                raise ValueError("amendment_remove_relation")
            scope["relations"] = [
                relation
                for relation in scope["relations"]
                if relation["relation_id"] not in remove_relations
            ]
        scope["relations"].extend(copy.deepcopy(operation.get("add_relations", ())))
        scope["excluded"].extend(copy.deepcopy(operation.get("add_excluded", ())))
    all_item_ids = {
        item["item_id"] for scope in result["scopes"] for item in scope["items"]
    }
    if len(all_item_ids) != sum(len(scope["items"]) for scope in result["scopes"]):
        raise ValueError("amendment_item_identity")
    for scope in result["scopes"]:
        for relation in (*scope["relations"], *scope["negative_relations"]):
            if relation["from_item"] not in all_item_ids or relation["to_item"] not in all_item_ids:
                raise ValueError("amendment_relation_endpoint")
    counts = {
        "scopes": len(result["scopes"]),
        "items": sum(len(scope["items"]) for scope in result["scopes"]),
        "positive_relations": sum(len(scope["relations"]) for scope in result["scopes"]),
        "negative_relations": sum(
            len(scope["negative_relations"]) for scope in result["scopes"]
        ),
        "excluded_fragments": sum(len(scope["excluded"]) for scope in result["scopes"]),
        "carry_forward_approved_items": amendment["carry_forward_approved_items"],
        "pending_replacement_items": amendment["replacement_items_pending_review"],
    }
    if counts != amendment["expected_after_application"]:
        raise ValueError("amendment_counts")
    result["schema_version"] = "material-micro-gold-v1+denominator-amendment-v1"
    result["expected_counts"] = {
        key: counts[key]
        for key in (
            "scopes",
            "items",
            "positive_relations",
            "negative_relations",
            "excluded_fragments",
        )
    }
    result["denominator_amendment_sha256"] = sha(AMENDMENT)
    result["human_review_sha256"] = sha(COMPLETED_REVIEW)
    return result


def _remediation_template(
    effective_scopes: list[dict[str, Any]],
    node_queue: list[dict[str, Any]],
    scope_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    items = {
        item["item_id"]: item
        for scope in effective_scopes
        for item in scope["items"]
        if item["item_id"] in PENDING_IDS
    }
    nodes = {record["target_id"]: record for record in node_queue}
    scopes = {record["target_id"]: record for record in scope_rows}
    records = []
    for target_id in sorted(PENDING_IDS):
        records.append(
            {
                "target_id": target_id,
                "source_quote": items[target_id]["quote"],
                "proposed_fields": {
                    key: value for key, value in items[target_id].items() if key != "item_id"
                },
                "generated_scope_ids": scopes[target_id]["scope_ids"],
                "proposed_clause_nodes": nodes[target_id]["candidate_nodes"],
                "human_decision": None,
                "human_reason": None,
                "checks": {
                    "one_research_statement": None,
                    "necessary_condition_or_attribution_retained": None,
                    "no_unrelated_claim_merged": None,
                    "source_quote_and_locator_sufficient": None,
                },
            }
        )
    return {
        "version": "r2-p3h-remediation-human-review-1",
        "split": "development",
        "reviewer_name": None,
        "reviewed_at": None,
        "allowed_decisions": ["approve", "reject", "needs_split", "needs_merge"],
        "approved_records": 0,
        "carried_forward_approved_records": 30,
        "instructions": "A human reviews only these five replacement items. Agent proposals are not approvals.",
        "records": records,
    }


def amended_target_scope_review(
    sources: dict[str, Any],
    plans: dict[str, Any],
    effective_scopes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Use frozen micro context only to disambiguate repeated short quotes after generation."""
    rows, scope_ids = p3s_review.target_scope_review(sources, plans, effective_scopes)
    scopes_by_id = {
        scope.scope_id: (sample_id, scope)
        for sample_id, plan in plans.items()
        for scope in plan.scopes
    }
    micro_by_id = {scope["scope_id"]: scope for scope in effective_scopes}
    for row in rows:
        if row["status"] != "ambiguous_scope":
            continue
        micro = micro_by_id[row["micro_scope_id"]]
        target_quotes = [p3.normalized(item["quote"]) for item in micro["items"]]
        scored = []
        for scope_id in row["scope_ids"]:
            sample_id, research_scope = scopes_by_id[scope_id]
            text = p3.normalized(p3s_review.resolve_scope(sources[sample_id], research_scope))
            scored.append((sum(quote in text for quote in target_quotes), scope_id))
        best = max(score for score, _ in scored)
        selected = [scope_id for score, scope_id in scored if score == best]
        if len(selected) == 1:
            row["status"] = "unique_scope_by_frozen_micro_context"
            row["scope_ids"] = selected
            scope_ids[row["target_id"]] = selected[0]
    return rows, scope_ids


def validate_remediation_review(review: dict[str, Any]) -> dict[str, Any]:
    records = review.get("records")
    if not isinstance(records, list) or len(records) != len(PENDING_IDS):
        raise ValueError("remediation_record_count")
    ids = [record.get("target_id") for record in records if isinstance(record, dict)]
    if len(ids) != len(records) or set(ids) != PENDING_IDS or len(set(ids)) != len(ids):
        raise ValueError("remediation_target_identity")
    if not isinstance(review.get("reviewer_name"), str) or not review["reviewer_name"].strip():
        raise ValueError("remediation_reviewer")
    if not isinstance(review.get("reviewed_at"), str) or not review["reviewed_at"].strip():
        raise ValueError("remediation_reviewed_at")
    allowed = {"approve", "reject", "needs_split", "needs_merge"}
    if set(review.get("allowed_decisions", ())) != allowed:
        raise ValueError("remediation_decision_contract")
    counts: Counter[str] = Counter()
    for record in records:
        decision = record.get("human_decision")
        checks = record.get("checks")
        if decision not in allowed:
            raise ValueError(f"remediation_decision:{record['target_id']}")
        if not isinstance(record.get("human_reason"), str) or not record["human_reason"].strip():
            raise ValueError(f"remediation_reason:{record['target_id']}")
        if not isinstance(checks, dict) or any(type(value) is not bool for value in checks.values()):
            raise ValueError(f"remediation_checks:{record['target_id']}")
        if decision == "approve" and (len(checks) != 4 or not all(checks.values())):
            raise ValueError(f"remediation_approve_contradiction:{record['target_id']}")
        counts[decision] += 1
    if review.get("approved_records") != counts["approve"]:
        raise ValueError("remediation_approved_count")
    return {
        "status": "complete",
        "records": len(records),
        "decisions": dict(counts),
        "all_approved": counts["approve"] == len(records),
    }


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    verify_pins()
    human_review = load_human_review()
    base = json.loads(p3.MICRO_GOLD.read_text(encoding="utf-8"))
    amendment = json.loads(AMENDMENT.read_text(encoding="utf-8"))
    base_before = json_sha(base)
    effective = apply_amendment(base, amendment)
    if json_sha(base) != base_before:
        raise ValueError("base_gold_mutated")
    node_summaries, node_queue = p3r_review.micro_review(effective["scopes"])
    samples, _ = p3.load_inputs()
    sources = {sample_id: p3s_review.build_source(samples[sample_id]) for sample_id in p3.DEV_IDS}
    plans = {
        sample_id: scope_provider.prepare_scopes(sources[sample_id], source_binding(sources[sample_id]))
        for sample_id in p3.DEV_IDS
    }
    scope_rows, scope_ids = amended_target_scope_review(sources, plans, effective["scopes"])
    mapped_nodes = sum(
        summary["mapping_statuses"].get("unique_minimum", 0) for summary in node_summaries
    )
    distinct_nodes = sum(summary["distinct_mapped_nodes"] for summary in node_summaries)
    scoped = sum(row["status"].startswith("unique_scope") for row in scope_rows)
    positive = sum(
        relation["from_item"] in scope_ids and relation["to_item"] in scope_ids
        for scope in effective["scopes"]
        for relation in scope["relations"]
    )
    negative = sum(
        relation["from_item"] in scope_ids and relation["to_item"] in scope_ids
        for scope in effective["scopes"]
        for relation in scope["negative_relations"]
    )
    pending_node_rows = [row for row in node_queue if row["target_id"] in PENDING_IDS]
    pending_scope_rows = [row for row in scope_rows if row["target_id"] in PENDING_IDS]
    inventory = {
        "version": "r2-p3h-human-remediation-review-1",
        "split": "development",
        "human_submission": {
            "sha256": sha(COMPLETED_REVIEW),
            "reviewer_name": human_review["reviewer_name"],
            "reviewed_at": human_review["reviewed_at"],
            "decisions": {
                "approve": 31,
                "needs_split": 2,
                "needs_merge": 1,
                "reject": 1,
            },
        },
        "amendment_sha256": sha(AMENDMENT),
        "effective_denominator_sha256": json_sha(effective),
        "base_gold_mutated": False,
        "holdout_source_paths_opened": 0,
        "model_calls": 0,
        "postgres_access": 0,
        "ingestion_runs": 0,
        "counts": effective["expected_counts"],
        "carry_forward_approved_items": 30,
        "replacement_items_pending_review": 5,
        "node_results": {
            "unique_minimum_mappings": mapped_nodes,
            "distinct_mapped_nodes": distinct_nodes,
        },
        "scope_results": {
            "items_in_unique_generated_scope": scoped,
            "positive_relation_endpoints_referencable": positive,
            "negative_relation_endpoints_referencable": negative,
        },
        "gates": {
            "H0_human_submission_valid": "passed",
            "H1_amendment_deterministic_and_base_immutable": "passed",
            "H2_effective_denominator_counts_and_endpoints": (
                "passed" if (mapped_nodes, distinct_nodes, scoped, positive, negative) == (35, 35, 35, 16, 8) else "failed"
            ),
            "H3_carry_forward_approvals": "passed",
            "H4_five_replacement_human_approvals": "not_evaluated",
            "H5_production_and_old_flow_isolation": "passed",
        },
        "status": "amendment_structural_replay_passed_five_replacements_human_review_required",
        "p4_budget_authorized": False,
    }
    return inventory, _remediation_template(effective["scopes"], pending_node_rows, pending_scope_rows)


def write_once(path: Path, value: object) -> None:
    raw = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(raw)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--remediation-template", type=Path)
    parser.add_argument("--validate-remediation", type=Path)
    args = parser.parse_args()
    if args.validate_remediation:
        completed = json.loads(args.validate_remediation.read_text(encoding="utf-8"))
        print(json.dumps(validate_remediation_review(completed), ensure_ascii=False, indent=2))
        raise SystemExit(0)
    if args.inventory is None or args.remediation_template is None:
        parser.error("--inventory and --remediation-template are required for generation")
    inventory, template = build()
    write_once(args.inventory, inventory)
    write_once(args.remediation_template, template)
    print(json.dumps({"status": inventory["status"], "gates": inventory["gates"]}, indent=2))
