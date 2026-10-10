"""Zero-call identity and target-exposure preflight for Issue 26."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[5]
CLAIMS = ROOT / ".scratch" / "claims-r2-role-isolation"
ISSUE25 = (
    CLAIMS
    / "evidence"
    / "25-final-relation-live-compliance-20261010"
    / "r0-live"
)
STORE = ISSUE25 / "live-store-v2"
EVALUATOR = (
    CLAIMS
    / "evidence"
    / "19-relation-selection-successor-20261010"
    / "r0-p14-counterfactual"
    / "audit_counterfactual.py"
)
GOLD = HERE / "utility-gold.agent-draft.json"

EXPECTED_BATCH_ID = "batch:3269051ddc97ebc979132d5110bdf923c22f28b9f87dd579717b27acb120f920"
EXPECTED_SNAPSHOT_ID = "sha256:561401b409e329fba8306c392bfc203da23ff1cc666faf9b7e919d88c2a9f080"
EXPECTED_ITEMS_PAYLOAD = "sha256:592065e674a8a0c1b2ff6764014781b029f8e22f616f0460dc921426b8a2c896"
EXPECTED_RELATIONS_PAYLOAD = (
    "sha256:a4af367954dc9a6214d3b1f87f71c6eedb85a78225d6ead9bfe5a5db18deacfb"
)
EXPECTED_RELATION_COUNT = 213
EXPECTED_CANDIDATE_COUNT = 333
EXPECTED_ITEM_COUNT = 469
EXPECTED_CANDIDATE_SET_ID = (
    "sha256:0e93746e5edf13547b7d149c90ebfa586ed48910707db5aceefac2379f100613"
)
ORIGINAL_Q4_PAIR = "pair_f88743227fb48b8b"
REPLACEMENT_Q4_PAIR = "pair_1f74637d78897251"
CONTROL_ITEM = "itm_ba3a8f228e6ab791"


def _read_mapping(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON root is not an object: {path}")
    return value


def _read_object(object_sha256: str) -> dict[str, Any]:
    digest = object_sha256.removeprefix("sha256:")
    path = STORE / "objects" / "sha256" / digest[:2] / f"{digest}.json"
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise RuntimeError(f"object hash mismatch: {object_sha256}")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError(f"stored object is not a mapping: {object_sha256}")
    return value


def _candidate_context() -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("issue26_context", EVALUATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("candidate context import failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    value: Any = module._candidate_context()
    if not isinstance(value, dict):
        raise RuntimeError("candidate context is not a mapping")
    return value


def _task_payloads() -> tuple[str, str, int]:
    connection = sqlite3.connect(
        f"file:{STORE / 'index/structured.sqlite3'}?mode=ro",
        uri=True,
    )
    connection.execute("PRAGMA query_only = ON")
    connection.row_factory = sqlite3.Row
    batch = dict(connection.execute("SELECT * FROM batches").fetchone())
    rows = {
        row["role"]: dict(row)
        for row in connection.execute("SELECT * FROM tasks ORDER BY role").fetchall()
    }
    connection.close()
    if batch["batch_id"] != EXPECTED_BATCH_ID:
        raise RuntimeError("Issue 25 batch identity drifted")
    return (
        rows["material_items"]["payload_object_sha256"],
        rows["material_relations"]["payload_object_sha256"],
        int(batch["actual_attempts"]),
    )


def main() -> None:
    gold = _read_mapping(GOLD)
    item_payload, relation_payload, actual_attempts = _task_payloads()
    if item_payload != EXPECTED_ITEMS_PAYLOAD or relation_payload != EXPECTED_RELATIONS_PAYLOAD:
        raise RuntimeError("Issue 25 task payload identity drifted")
    if actual_attempts != 4:
        raise RuntimeError("Issue 25 attempt count drifted")

    context = _candidate_context()
    candidate_set = context["candidate_set"]
    items_run = context["items"]
    if candidate_set.candidate_set_id != EXPECTED_CANDIDATE_SET_ID:
        raise RuntimeError("candidate set identity drifted")
    if len(candidate_set.candidates) != EXPECTED_CANDIDATE_COUNT:
        raise RuntimeError("candidate count drifted")
    if len(items_run.understanding.items) != EXPECTED_ITEM_COUNT:
        raise RuntimeError("item count drifted")
    if gold["source_snapshot_id"] != EXPECTED_SNAPSHOT_ID:
        raise RuntimeError("utility gold snapshot identity drifted")

    items = {item.item_id: item for item in items_run.understanding.items}
    pairs = {pair.candidate_pair_id: pair for pair in candidate_set.candidates}
    candidate_endpoints = {
        endpoint
        for pair in candidate_set.candidates
        for endpoint in (pair.from_item, pair.to_item)
    }

    relation_run = _read_object(relation_payload)
    relations = relation_run["understanding"]["relations"]
    if len(relations) != EXPECTED_RELATION_COUNT:
        raise RuntimeError("retained relation count drifted")
    retained = {
        (relation["type"], relation["from_item"], relation["to_item"]): relation["relation_id"]
        for relation in relations
    }

    target_exposure: list[dict[str, Any]] = []
    for question in gold["questions"]:
        question_id = question["question_id"]
        for anchor in question["evidence_anchors"]:
            item = items.get(anchor["item_id"])
            if item is None:
                raise RuntimeError(f"missing evidence item: {anchor['item_id']}")
            if anchor["quote"] not in {proof.quote for proof in item.evidence}:
                raise RuntimeError(f"evidence quote drifted: {anchor['item_id']}")
        actual_relation_ids: list[str] = []
        for pair_id in question["target_candidate_pair_ids"]:
            pair = pairs.get(pair_id)
            if pair is None:
                raise RuntimeError(f"missing candidate pair: {pair_id}")
            relation_id = retained.get((pair.allowed_type, pair.from_item, pair.to_item))
            if relation_id is None:
                raise RuntimeError(f"target pair is not retained in treatment: {pair_id}")
            actual_relation_ids.append(relation_id)
        if sorted(actual_relation_ids) != sorted(question["target_relation_ids"]):
            raise RuntimeError(f"target relation identity drifted: {question_id}")
        target_exposure.append(
            {
                "question_id": question_id,
                "candidate_pair_ids": question["target_candidate_pair_ids"],
                "relation_ids": actual_relation_ids,
                "treatment_edge_exposure": bool(actual_relation_ids),
            }
        )

    original_pair = pairs[ORIGINAL_Q4_PAIR]
    if (original_pair.allowed_type, original_pair.from_item, original_pair.to_item) in retained:
        raise RuntimeError("original Q4 pair unexpectedly retained")
    replacement_pair = pairs[REPLACEMENT_Q4_PAIR]
    if (replacement_pair.allowed_type, replacement_pair.from_item, replacement_pair.to_item) not in retained:
        raise RuntimeError("replacement Q4 risk edge is not retained")
    if CONTROL_ITEM in candidate_endpoints:
        raise RuntimeError("Q5 control item unexpectedly participates in candidate relations")

    if gold["status"] != "agent_draft_pending_human_signoff":
        raise RuntimeError("utility gold is not awaiting human signoff")
    if not gold["signoff"]["required"] or gold["signoff"]["reviewer"] is not None:
        raise RuntimeError("utility gold signoff state drifted")
    if any(question["human_review"]["decision"] is not None for question in gold["questions"]):
        raise RuntimeError("draft already contains a human decision")

    summary = {
        "schema_version": "relation-utility-preflight-summary-1",
        "created_on": "2026-10-10",
        "status": "passed_waiting_human_signoff",
        "model_calls": 0,
        "publication_query_delivery_context_use": 0,
        "batch_id": EXPECTED_BATCH_ID,
        "snapshot_id": EXPECTED_SNAPSHOT_ID,
        "items_payload_sha256": item_payload,
        "relations_payload_sha256": relation_payload,
        "utility_gold_sha256": f"sha256:{hashlib.sha256(GOLD.read_bytes()).hexdigest()}",
        "counts": {
            "items": len(items),
            "relation_candidates": len(candidate_set.candidates),
            "retained_relations": len(relations),
            "questions": len(gold["questions"]),
            "main_runs_executed": 0,
        },
        "q4_design_correction": {
            "removed_pair": ORIGINAL_Q4_PAIR,
            "removed_pair_retained": False,
            "replacement_pair": REPLACEMENT_Q4_PAIR,
            "replacement_pair_retained": True,
            "reason": "The removed pair cannot create A/B exposure because Issue 25 did not retain it.",
        },
        "q5_control_item": {
            "item_id": CONTROL_ITEM,
            "participates_in_candidate_relations": False,
        },
        "target_exposure": target_exposure,
        "human_signoff_required": True,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
