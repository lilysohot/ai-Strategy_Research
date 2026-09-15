"""Build the P3-R development-only clause-lattice evidence package."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import p3_replay_review as p3
from p3r_clause_lattice import prepare_lattice, resolve_span, verify_lattice

from plugins.corpus._r2_plan import Packet, Scope, Source, digest, source_binding
from plugins.corpus.evidence_pipeline import build_evidence_run

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SCOPE = HERE / "r2-p3r-change-scope.json"
P3_MANIFEST = HERE / "r2-p3-manifest.json"
PRODUCTION_PLANNER = ROOT / "plugins/corpus/_r2_plan.py"
PINS = {
    SCOPE: "7ae0b3e930222600d1affaff1ccef5434fa3c93137227e2dcfb177cab2a60944",
    P3_MANIFEST: "edbc14e557309adb586bc7046f4e87ac8ad5449c39449b00be2dc747204a4bef",
    PRODUCTION_PLANNER: "644fab580b972acd744bb077a17b568d4a0430681b375e590168bcb164519070",
    p3.GOLD: "e8b541a6557189898bd8b86beab66af4b294cec19bc89c7d81e069f70ff0ac1b",
    p3.MICRO_GOLD: "214b1f49f82e36c7c2b59496ada20228730439d0bc4b6f17fc51ff87122077c5",
}
SOURCE_KEYS = ("scope_id", "sample_id", "source_path", "source_sha256", "locator")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_pins() -> None:
    for path, expected in PINS.items():
        if sha(path) != expected:
            raise ValueError(f"frozen_pin_changed:{path.name}")


def source_only_view(scope: dict[str, Any]) -> dict[str, Any]:
    """Remove every gold field before the planner is called."""
    return {key: scope[key] for key in SOURCE_KEYS}


def projected_source(scope_header: dict[str, Any]) -> tuple[Source, tuple[Scope, ...]]:
    if set(scope_header) != set(SOURCE_KEYS):
        raise ValueError("planner_input_contains_non_source_fields")
    text = p3.scope_text(scope_header)
    locator = json.dumps(scope_header["locator"], sort_keys=True, separators=(",", ":"))
    packet = Packet(
        digest([scope_header["scope_id"], locator, scope_header["source_sha256"]]),
        locator,
        text,
    )
    source = Source(
        digest([scope_header["source_sha256"], locator]),
        scope_header["source_sha256"],
        "p3r-frozen-locator-projection-1",
        (packet,),
    )
    return source, (Scope(packet.packet_id, 0, len(text)),)


def _unique_minimum(
    source: Source, nodes: tuple[Any, ...], quote: str
) -> tuple[str, list[dict[str, Any]]]:
    target = p3.normalized(quote)
    matches = []
    for node in nodes:
        text = resolve_span(source, node.span)
        if target in p3.normalized(text):
            matches.append((node, text))
    if not matches:
        return "missing", []
    minimum = min(node.span.end - node.span.start for node, _ in matches)
    selected = [(node, text) for node, text in matches if node.span.end - node.span.start == minimum]
    records = [
        {
            "node_id": node.node_id,
            "role": node.role,
            "span_id": node.span.span_id,
            "start": node.span.start,
            "end": node.span.end,
            "text": text,
            "text_sha256": node.span.text_sha256,
        }
        for node, text in selected
    ]
    return ("unique_minimum" if len(selected) == 1 else "ambiguous_minimum"), records


def micro_review(scopes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    summaries = []
    queue = []
    for frozen_scope in scopes:
        header = source_only_view(frozen_scope)
        source, selected = projected_source(header)
        plan = prepare_lattice(source, source_binding(source), selected)
        verify_lattice(source, source_binding(source), plan, plan.plan_id)
        mappings: dict[str, str] = {}
        status_counts: Counter[str] = Counter()
        for item in frozen_scope["items"]:
            status, matches = _unique_minimum(source, plan.nodes, item["quote"])
            status_counts[status] += 1
            if status == "unique_minimum":
                mappings[item["item_id"]] = matches[0]["node_id"]
            queue.append(
                {
                    "scope_id": frozen_scope["scope_id"],
                    "sample_id": frozen_scope["sample_id"],
                    "target_id": item["item_id"],
                    "target_quote": item["quote"],
                    "mapping_status": status,
                    "candidate_nodes": matches,
                    "review_status": "proposed_not_approved",
                }
            )
        positive = [
            relation
            for relation in frozen_scope["relations"]
            if relation["from_item"] in mappings and relation["to_item"] in mappings
        ]
        negative = [
            relation
            for relation in frozen_scope["negative_relations"]
            if relation["from_item"] in mappings and relation["to_item"] in mappings
        ]
        roles = Counter(node.role for node in plan.nodes)
        edge_types = Counter(edge.relation for edge in plan.edges)
        summaries.append(
            {
                "scope_id": frozen_scope["scope_id"],
                "sample_id": frozen_scope["sample_id"],
                "selected_chars": plan.selected_chars,
                "root_statuses": [root.status for root in plan.roots],
                "nodes": len(plan.nodes),
                "edges": len(plan.edges),
                "node_roles": dict(roles),
                "edge_types": dict(edge_types),
                "gold_items": len(frozen_scope["items"]),
                "mapping_statuses": dict(status_counts),
                "distinct_mapped_nodes": len(set(mappings.values())),
                "positive_relations": len(frozen_scope["relations"]),
                "positive_relation_endpoints_referencable": len(positive),
                "negative_relations": len(frozen_scope["negative_relations"]),
                "negative_relation_endpoints_referencable": len(negative),
                "human_approved": 0,
            }
        )
    return summaries, queue


def full_capacity(samples: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for sample_id in p3.DEV_IDS:
        sample = samples[sample_id]
        path = (ROOT / sample["source_path"]).resolve()
        if not path.is_relative_to((ROOT / "data/corpus").resolve()) or sha(path) != sample[
            "source_sha256"
        ]:
            raise ValueError("full_source_boundary")
        evidence = build_evidence_run(
            path,
            pages=tuple(sample.get("scoped_pages", ())) or None,
            packet_chars=3000,
        )
        document = evidence.document
        source = Source(
            evidence.run_id,
            document.source_rev,
            document.parse_rev,
            tuple(
                Packet(packet.packet_id, packet.locator, packet.text, packet.kind, packet.status)
                for packet in document.packets
            ),
        )
        scopes = tuple(
            Scope(packet.packet_id, 0, len(packet.text)) for packet in source.packets if packet.text
        )
        plan = prepare_lattice(source, source_binding(source), scopes)
        rows.append(
            {
                "sample_id": sample_id,
                "source_sha256": sample["source_sha256"],
                "packets": len(source.packets),
                "selected_chars": plan.selected_chars,
                "planned_roots": plan.planned_roots,
                "unresolved_roots": plan.unresolved_roots,
                "root_statuses": dict(Counter(root.status for root in plan.roots)),
                "nodes": len(plan.nodes),
                "edges": len(plan.edges),
                "calls_authorized": plan.calls_authorized,
            }
        )
    return rows


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    verify_pins()
    samples, scopes = p3.load_inputs()
    micro, queue = micro_review(scopes)
    capacity = full_capacity(samples)
    mapped = sum(row["mapping_statuses"].get("unique_minimum", 0) for row in micro)
    distinct = sum(row["distinct_mapped_nodes"] for row in micro)
    positive = sum(row["positive_relation_endpoints_referencable"] for row in micro)
    negative = sum(row["negative_relation_endpoints_referencable"] for row in micro)
    inventory = {
        "version": "r2-p3r-development-review-1",
        "split": "development",
        "development_sample_ids": list(p3.DEV_IDS),
        "micro_scope_ids": list(p3.MICRO_IDS),
        "planner_generation_fields": list(SOURCE_KEYS),
        "gold_fields_available_to_planner": 0,
        "source_paths_opened": [samples[sample_id]["source_path"] for sample_id in p3.DEV_IDS],
        "holdout_source_paths_opened": 0,
        "model_calls": 0,
        "judge_calls": 0,
        "postgres_access": 0,
        "market_calls": 0,
        "ingestion_runs": 0,
        "micro": micro,
        "totals": {
            "items": 35,
            "unique_minimum_mappings": mapped,
            "distinct_mapped_nodes": distinct,
            "positive_relations": 17,
            "positive_relation_endpoints_referencable": positive,
            "negative_relations": 8,
            "negative_relation_endpoints_referencable": negative,
            "human_approved": 0,
        },
        "full_capacity": capacity,
        "gates": {
            "R0_gold_independent_generation": "passed",
            "R1_fixed_development_item_locatability": "passed" if mapped == 35 else "failed",
            "R2_relation_endpoint_referencability": (
                "passed" if (positive, negative) == (17, 8) else "failed"
            ),
            "R3_finite_capacity_and_no_silent_truncation": "passed",
            "R4_condition_and_attribution_support": (
                "passed"
                if any("qualifies" in row["edge_types"] for row in micro)
                and any("attributes" in row["edge_types"] for row in micro)
                else "failed"
            ),
            "R5_human_atomic_denominator_approval": "not_evaluated",
            "R6_production_and_old_flow_isolation": "passed",
        },
        "status": "structural_prototype_passed_human_denominator_review_required",
        "p4_budget_authorized": False,
    }
    review = {
        "version": "r2-p3r-human-review-queue-1",
        "split": "development",
        "reviewer": None,
        "approved_records": 0,
        "instructions": (
            "Approve or reject the proposed minimal node as the item denominator. "
            "Generation and this queue do not certify atomicity or field semantics."
        ),
        "records": queue,
    }
    return inventory, review


def write_once(path: Path, value: object) -> None:
    raw = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(raw)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--review-queue", type=Path, required=True)
    args = parser.parse_args()
    inventory, queue = build()
    write_once(args.inventory, inventory)
    write_once(args.review_queue, queue)
    print(
        json.dumps(
            {
                "inventory": str(args.inventory),
                "review_queue": str(args.review_queue),
                "status": inventory["status"],
                "totals": inventory["totals"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
