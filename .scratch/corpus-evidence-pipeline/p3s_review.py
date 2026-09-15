"""Build the P3-S full-development scope-provider evidence package."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import p3_replay_review as p3
import p3r_clause_lattice as lattice
import p3s_scope_provider as provider

from plugins.corpus._r2_plan import Packet, Scope, Source, source_binding
from plugins.corpus.evidence_pipeline import build_evidence_run

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PINS = {
    HERE / "r2-p3s-change-scope.json": (
        "e2a809aadda60921059506290e26830682a28b68e5fc9a3977c83eccfb307d5a"
    ),
    HERE / "r2-p3r-manifest.json": (
        "a79ad421df11933f4360d264a60b4856aeded9273c4277af0c4f03d03b0d18b3"
    ),
    HERE / "p3r_clause_lattice.py": (
        "c49c4d867ba5702c29b3d11bb2e695e0b4e2336ec567c46d9f1fe1f9cf36c7ce"
    ),
    HERE / "r2-p3r-review-queue.json": (
        "48fdc362a9e017746ed58eaeb8c43f2d7fd16d1f90d55c36ecfee03d785435b6"
    ),
    p3.GOLD: "e8b541a6557189898bd8b86beab66af4b294cec19bc89c7d81e069f70ff0ac1b",
    p3.MICRO_GOLD: "214b1f49f82e36c7c2b59496ada20228730439d0bc4b6f17fc51ff87122077c5",
}
CLAUSE_KINDS = {"prose", "turn", "heading_context"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_pins() -> None:
    for path, expected in PINS.items():
        if sha(path) != expected:
            raise ValueError(f"frozen_pin_changed:{path.name}")


def build_source(sample: dict[str, Any]) -> Source:
    path = (ROOT / sample["source_path"]).resolve()
    if not path.is_relative_to((ROOT / "data/corpus").resolve()) or sha(path) != sample[
        "source_sha256"
    ]:
        raise ValueError("source_boundary")
    evidence = build_evidence_run(
        path,
        pages=tuple(sample.get("scoped_pages", ())) or None,
        packet_chars=3000,
    )
    document = evidence.document
    return Source(
        evidence.run_id,
        document.source_rev,
        document.parse_rev,
        tuple(
            Packet(packet.packet_id, packet.locator, packet.text, packet.kind, packet.status)
            for packet in document.packets
        ),
    )


def resolve_scope(source: Source, scope: provider.ResearchScope) -> str:
    packets = [packet for packet in source.packets if packet.packet_id == scope.packet_id]
    if len(packets) != 1:
        raise ValueError("packet_identity")
    packet = packets[0]
    if not 0 <= scope.start < scope.end <= len(packet.text):
        raise ValueError("scope_coordinate")
    return packet.text[scope.start : scope.end]


def review_source(sample_id: str, source: Source) -> tuple[dict[str, Any], provider.ScopePlan]:
    plan = provider.prepare_scopes(source, source_binding(source))
    provider.verify_scope_plan(source, source_binding(source), plan, plan.plan_id)
    scope_kinds = Counter(scope.kind for scope in plan.scopes)
    lattice_statuses: Counter[str] = Counter()
    lattice_nodes = 0
    lattice_edges = 0
    clause_scope_count = 0
    for research_scope in plan.scopes:
        if research_scope.state != "candidate" or research_scope.kind not in CLAUSE_KINDS:
            continue
        clause_scope_count += 1
        clause_plan = lattice.prepare_lattice(
            source,
            source_binding(source),
            (Scope(research_scope.packet_id, research_scope.start, research_scope.end),),
        )
        lattice.verify_lattice(source, source_binding(source), clause_plan, clause_plan.plan_id)
        lattice_statuses.update(root.status for root in clause_plan.roots)
        lattice_nodes += len(clause_plan.nodes)
        lattice_edges += len(clause_plan.edges)
    table_scopes = [scope for scope in plan.scopes if scope.kind == "table_row"]
    row = {
        "sample_id": sample_id,
        "packets": len(source.packets),
        "packet_kinds": dict(Counter(packet.kind for packet in source.packets)),
        "planned_packets": plan.planned_packets,
        "unresolved_packets": plan.unresolved_packets,
        "candidate_scopes": plan.candidate_scopes,
        "unresolved_scopes": plan.unresolved_scopes,
        "scope_kinds": dict(scope_kinds),
        "source_chars": sum(packet.source_chars for packet in plan.packets),
        "covered_chars": sum(packet.covered_chars for packet in plan.packets),
        "source_non_whitespace_chars": sum(packet.non_whitespace_chars for packet in plan.packets),
        "covered_non_whitespace_chars": sum(
            packet.covered_non_whitespace_chars for packet in plan.packets
        ),
        "context_edges": len(plan.edges),
        "clause_lattice_scopes": clause_scope_count,
        "table_scopes": len(table_scopes),
        "table_scopes_sent_to_clause_lattice": 0,
        "clause_lattice_root_statuses": dict(lattice_statuses),
        "clause_lattice_nodes": lattice_nodes,
        "clause_lattice_edges": lattice_edges,
        "calls_authorized": plan.calls_authorized,
    }
    return row, plan


def target_scope_review(
    sources: dict[str, Source],
    plans: dict[str, provider.ScopePlan],
    micro_scopes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    rows = []
    target_scope_ids: dict[str, str] = {}
    for micro in micro_scopes:
        source = sources[micro["sample_id"]]
        plan = plans[micro["sample_id"]]
        frozen_text = p3.scope_text(micro)
        block_matches = [
            (packet.packet_id, offset, offset + len(frozen_text))
            for packet in source.packets
            for offset in [packet.text.find(frozen_text)]
            if offset >= 0
        ]
        candidates = [
            (scope, resolve_scope(source, scope))
            for scope in plan.scopes
            if scope.state == "candidate" and scope.kind in CLAUSE_KINDS
        ]
        if len(block_matches) == 1:
            packet_id, block_start, block_end = block_matches[0]
            candidates = [
                (scope, text)
                for scope, text in candidates
                if scope.packet_id == packet_id
                and scope.start < block_end
                and scope.end > block_start
            ]
        for item in micro["items"]:
            target = p3.normalized(item["quote"])
            matches = [
                (scope, text) for scope, text in candidates if target in p3.normalized(text)
            ]
            status = "unique_scope" if len(matches) == 1 else (
                "missing" if not matches else "ambiguous_scope"
            )
            if status == "unique_scope":
                target_scope_ids[item["item_id"]] = matches[0][0].scope_id
            rows.append(
                {
                    "sample_id": micro["sample_id"],
                    "micro_scope_id": micro["scope_id"],
                    "target_id": item["item_id"],
                    "status": status,
                    "scope_ids": [scope.scope_id for scope, _ in matches],
                }
            )
    return rows, target_scope_ids


def human_template(scope_rows: list[dict[str, Any]]) -> dict[str, Any]:
    frozen = json.loads((HERE / "r2-p3r-review-queue.json").read_text(encoding="utf-8"))
    scope_by_target = {row["target_id"]: row for row in scope_rows}
    records = []
    for record in frozen["records"]:
        scope_row = scope_by_target[record["target_id"]]
        records.append(
            {
                "sample_id": record["sample_id"],
                "micro_scope_id": record["scope_id"],
                "target_id": record["target_id"],
                "source_quote": record["target_quote"],
                "scope_status": scope_row["status"],
                "generated_scope_ids": scope_row["scope_ids"],
                "proposed_clause_nodes": record["candidate_nodes"],
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
        "version": "r2-p3s-denominator-human-review-1",
        "split": "development",
        "reviewer_name": None,
        "reviewed_at": None,
        "allowed_decisions": ["approve", "reject", "needs_split", "needs_merge"],
        "approved_records": 0,
        "instructions": "A human fills every decision, reason, and check. Agent proposals are not approvals.",
        "records": records,
    }


def validate_human_review(review: dict[str, Any]) -> dict[str, Any]:
    """Validate a completed human decision file without interpreting its decisions."""
    frozen = json.loads((HERE / "r2-p3r-review-queue.json").read_text(encoding="utf-8"))
    expected_ids = {record["target_id"] for record in frozen["records"]}
    records = review.get("records")
    if not isinstance(records, list) or len(records) != len(expected_ids):
        raise ValueError("human_record_count")
    observed_ids = [record.get("target_id") for record in records if isinstance(record, dict)]
    if len(observed_ids) != len(records) or set(observed_ids) != expected_ids:
        raise ValueError("human_target_identity")
    if len(set(observed_ids)) != len(observed_ids):
        raise ValueError("human_target_duplicate")
    if not isinstance(review.get("reviewer_name"), str) or not review["reviewer_name"].strip():
        raise ValueError("human_reviewer")
    if not isinstance(review.get("reviewed_at"), str) or not review["reviewed_at"].strip():
        raise ValueError("human_reviewed_at")
    allowed = set(review.get("allowed_decisions", ()))
    if allowed != {"approve", "reject", "needs_split", "needs_merge"}:
        raise ValueError("human_decision_contract")
    counts: Counter[str] = Counter()
    for record in records:
        decision = record.get("human_decision")
        reason = record.get("human_reason")
        checks = record.get("checks")
        if decision not in allowed:
            raise ValueError(f"human_decision:{record['target_id']}")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"human_reason:{record['target_id']}")
        if not isinstance(checks, dict) or set(checks) != {
            "one_research_statement",
            "necessary_condition_or_attribution_retained",
            "no_unrelated_claim_merged",
            "source_quote_and_locator_sufficient",
        }:
            raise ValueError(f"human_checks:{record['target_id']}")
        if any(type(value) is not bool for value in checks.values()):
            raise ValueError(f"human_check_value:{record['target_id']}")
        if decision == "approve" and not all(checks.values()):
            raise ValueError(f"human_approve_contradiction:{record['target_id']}")
        counts[decision] += 1
    if review.get("approved_records") != counts["approve"]:
        raise ValueError("human_approved_count")
    return {
        "status": "complete",
        "reviewer_name": review["reviewer_name"],
        "reviewed_at": review["reviewed_at"],
        "records": len(records),
        "decisions": dict(counts),
        "all_approved": counts["approve"] == len(records),
    }


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    verify_pins()
    samples, micro_scopes = p3.load_inputs()
    sources = {sample_id: build_source(samples[sample_id]) for sample_id in p3.DEV_IDS}
    plans = {}
    source_rows = []
    for sample_id in p3.DEV_IDS:
        row, plan = review_source(sample_id, sources[sample_id])
        source_rows.append(row)
        plans[sample_id] = plan
    target_rows, target_scope_ids = target_scope_review(sources, plans, micro_scopes)
    positive = sum(
        relation["from_item"] in target_scope_ids and relation["to_item"] in target_scope_ids
        for scope in micro_scopes
        for relation in scope["relations"]
    )
    negative = sum(
        relation["from_item"] in target_scope_ids and relation["to_item"] in target_scope_ids
        for scope in micro_scopes
        for relation in scope["negative_relations"]
    )
    packets = sum(row["packets"] for row in source_rows)
    unresolved_packets = sum(row["unresolved_packets"] for row in source_rows)
    lattice_failures = sum(
        count
        for row in source_rows
        for status, count in row["clause_lattice_root_statuses"].items()
        if status != "planned"
    )
    contained = sum(row["status"] == "unique_scope" for row in target_rows)
    inventory = {
        "version": "r2-p3s-development-scope-review-1",
        "split": "development",
        "development_sample_ids": list(p3.DEV_IDS),
        "source_paths_opened": [samples[sample_id]["source_path"] for sample_id in p3.DEV_IDS],
        "holdout_source_paths_opened": 0,
        "model_calls": 0,
        "judge_calls": 0,
        "postgres_access": 0,
        "market_calls": 0,
        "ingestion_runs": 0,
        "sources": source_rows,
        "target_scope_review": target_rows,
        "totals": {
            "packets": packets,
            "unresolved_packets": unresolved_packets,
            "candidate_scopes": sum(row["candidate_scopes"] for row in source_rows),
            "unresolved_scopes": sum(row["unresolved_scopes"] for row in source_rows),
            "table_scopes": sum(row["table_scopes"] for row in source_rows),
            "table_scopes_sent_to_clause_lattice": 0,
            "clause_lattice_capacity_or_kind_failures": lattice_failures,
            "items": 35,
            "items_in_unique_generated_scope": contained,
            "positive_relation_endpoints_referencable": positive,
            "negative_relation_endpoints_referencable": negative,
            "human_approved": 0,
        },
        "gates": {
            "S0_source_identity_and_gold_independence": "passed",
            "S1_all_packets_accounted_and_covered": (
                "passed" if packets == 14 and unresolved_packets == 0 else "failed"
            ),
            "S2_table_type_preserved": (
                "passed"
                if sum(row["table_scopes"] for row in source_rows) == 7
                and all(row["table_scopes_sent_to_clause_lattice"] == 0 for row in source_rows)
                else "failed"
            ),
            "S3_all_prose_scopes_within_clause_lattice_capacity": (
                "passed" if lattice_failures == 0 else "failed"
            ),
            "S4_fixed_development_target_scope_coverage": (
                "passed" if contained == 35 else "failed"
            ),
            "S5_relation_endpoint_scope_references": (
                "passed" if (positive, negative) == (17, 8) else "failed"
            ),
            "S6_human_atomic_denominator_approval": "not_evaluated",
            "S7_production_and_old_flow_isolation": "passed",
        },
        "status": "scope_provider_structural_gate_passed_human_denominator_review_required",
        "p4_budget_authorized": False,
    }
    return inventory, human_template(target_rows)


def write_once(path: Path, value: object) -> None:
    raw = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(raw)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--human-template", type=Path)
    parser.add_argument("--validate-human", type=Path)
    args = parser.parse_args()
    if args.validate_human:
        completed = json.loads(args.validate_human.read_text(encoding="utf-8"))
        print(json.dumps(validate_human_review(completed), ensure_ascii=False, indent=2))
        raise SystemExit(0)
    if args.inventory is None or args.human_template is None:
        parser.error("--inventory and --human-template are required for generation")
    inventory, template = build()
    write_once(args.inventory, inventory)
    write_once(args.human_template, template)
    print(
        json.dumps(
            {"status": inventory["status"], "totals": inventory["totals"]},
            ensure_ascii=False,
            indent=2,
        )
    )
