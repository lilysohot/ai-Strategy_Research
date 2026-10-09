"""Export and score the immutable P10 formal-ledger relation execution."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from plugins.corpus.material_semantics import (
    MATERIAL_ITEMS_VALIDATION_VERSION,
    RELATION_CANDIDATE_RULE_VERSION,
    MaterialRun,
    build_relation_candidate_set,
)
from plugins.corpus.structured.roles import RoleArtifact
from plugins.corpus.structured.snapshot import EvidenceSnapshot

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[5]
STORE = HERE / "live-store"
SNAPSHOT = (
    HERE.parents[1]
    / "17-structured-extraction-convergence-closure-20261009"
    / "p1-plan-freeze/copper-items-relations/snapshot.json"
)
GOLD = ROOT / "data/corpus/.audit/r1_material_gold_v1_20260913.json"
SCORER = ROOT / ".scratch/corpus-evidence-pipeline/run_material_development.py"


def _read_object(object_sha256: str) -> dict[str, Any]:
    digest = object_sha256.removeprefix("sha256:")
    path = STORE / "objects/sha256" / digest[:2] / f"{digest}.json"
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise RuntimeError(f"object hash mismatch: {object_sha256}")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError(f"object is not a mapping: {object_sha256}")
    return value


def _write(name: str, value: object) -> None:
    (HERE / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    connection = sqlite3.connect(
        f"file:{STORE / 'index/structured.sqlite3'}?mode=ro", uri=True
    )
    connection.row_factory = sqlite3.Row
    tasks = {
        row["role"]: dict(row)
        for row in connection.execute(
            "SELECT * FROM tasks ORDER BY derived, task_id"
        ).fetchall()
    }
    attempts = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM attempts ORDER BY attempt_number"
        ).fetchall()
    ]
    batch = dict(connection.execute("SELECT * FROM batches").fetchone())
    connection.close()

    item_artifact_raw = _read_object(tasks["material_items"]["artifact_sha256"])
    item_payload_raw = _read_object(tasks["material_items"]["payload_object_sha256"])
    relation_artifact_raw = _read_object(tasks["material_relations"]["artifact_sha256"])
    relation_payload_raw = _read_object(
        tasks["material_relations"]["payload_object_sha256"]
    )
    item_artifact = RoleArtifact.model_validate(item_artifact_raw)
    relation_artifact = RoleArtifact.model_validate(relation_artifact_raw)
    items = MaterialRun.model_validate(item_payload_raw)
    relations = MaterialRun.model_validate(relation_payload_raw)
    item_artifact.verify_identity()
    relation_artifact.verify_identity()
    items.verify_identity()
    relations.verify_identity()

    snapshot = EvidenceSnapshot.model_validate_json(SNAPSHOT.read_text(encoding="utf-8"))
    endpoint_ids = tuple(
        item_ref
        for entry in items.understanding.coverage.slot_ledger
        if entry.status == "extracted"
        for item_ref in entry.item_refs
    )
    candidate_set = build_relation_candidate_set(
        snapshot,
        items,
        endpoint_item_ids=endpoint_ids,
        items_validation_version=MATERIAL_ITEMS_VALIDATION_VERSION,
        rule_version=RELATION_CANDIDATE_RULE_VERSION,
    )
    candidates_by_key = {
        (candidate.allowed_type, candidate.from_item, candidate.to_item): candidate
        for candidate in candidate_set.candidates
    }
    candidate_counts = Counter(
        candidate.packet_id for candidate in candidate_set.candidates
    )
    present_counts: Counter[str] = Counter()
    for relation in relations.understanding.relations:
        candidate = candidates_by_key[relation.type, relation.from_item, relation.to_item]
        present_counts[candidate.packet_id] += 1

    spec = importlib.util.spec_from_file_location("material_development_scorer", SCORER)
    if spec is None or spec.loader is None:
        raise RuntimeError("scorer import failed")
    scorer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scorer)
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    sample = next(
        value for value in gold["samples"] if value["sample_id"] == "dev-expert-call-copper-foil"
    )
    combined = dict(item_payload_raw["understanding"])
    combined["relations"] = relation_payload_raw["understanding"]["relations"]
    material_run = SimpleNamespace(
        understanding=SimpleNamespace(
            model_dump=lambda **_kwargs: combined,
            source=SimpleNamespace(source_rev=combined["source"]["source_rev"]),
        ),
        run_id=relation_payload_raw["run_id"],
        summary=lambda: {
            "complete": all(packet.status == "completed" for packet in relations.packet_runs),
            "packet_status": {
                status: sum(packet.status == status for packet in relations.packet_runs)
                for status in ("completed", "partial", "failed", "deferred")
            },
        },
    )
    score = scorer.score_sample(sample, material_run)

    predicted_items = item_payload_raw["understanding"]["items"]
    endpoint_map: dict[str, tuple[str, ...]] = {}
    for match in scorer.match_items(sample["items"], predicted_items):
        gold_item = sample["items"][match["gold_index"]]
        indices = scorer.relation_endpoint_indices(
            gold_item, match["predicted_indices"], predicted_items
        )
        endpoint_map[gold_item["item_id"]] = tuple(
            predicted_items[index]["item_id"] for index in indices
        )
    gold_relation_matches = []
    for gold_relation in sample["relations"]:
        accepted = [
            relation
            for relation in combined["relations"]
            if relation["type"] == gold_relation["type"]
            and relation["from_item"] in endpoint_map[gold_relation["from_item"]]
            and relation["to_item"] in endpoint_map[gold_relation["to_item"]]
            and relation["provenance"] == "source_explicit"
        ]
        gold_relation_matches.append(
            {
                "gold_relation": gold_relation["relation_id"],
                "matched": bool(accepted),
                "accepted_relation_ids": [relation["relation_id"] for relation in accepted],
                "from_endpoint_items": list(endpoint_map[gold_relation["from_item"]]),
                "to_endpoint_items": list(endpoint_map[gold_relation["to_item"]]),
            }
        )

    usage = [json.loads(attempt["usage"]) for attempt in attempts]
    usage_totals = {
        key: sum((value.get(key) or 0) for value in usage)
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "reasoning_tokens",
            "total_tokens",
        )
    }
    packet_results = [
        {
            "packet_id": packet_id,
            "candidates": candidate_counts[packet_id],
            "present": present_counts[packet_id],
            "accepted_rate": present_counts[packet_id] / candidate_counts[packet_id],
        }
        for packet_id in candidate_counts
    ]
    execution_summary = {
        "schema_version": "accepted-items-import-live-execution-1",
        "executed_on": "2026-10-10",
        "batch_id": batch["batch_id"],
        "plan_sha256": batch["plan_sha256"],
        "model_calls": len(attempts),
        "attempt_status": dict(Counter(attempt["execution_status"] for attempt in attempts)),
        "items_attempts": 0,
        "relation_attempts": len(attempts),
        "usage": usage_totals,
        "cost": None,
        "cost_status": "unavailable_not_zero",
        "tasks": {
            role: {
                "task_id": task["task_id"],
                "method": task["method"],
                "execution_status": task["execution_status"],
                "protocol_status": task["protocol_status"],
                "quality_status": task["quality_status"],
                "artifact_id": task["artifact_id"],
                "payload_sha256": task["payload_sha256"],
            }
            for role, task in tasks.items()
        },
        "candidate_set_id": candidate_set.candidate_set_id,
        "candidate_rule_version": candidate_set.rule_version,
        "candidate_relations": len(candidate_set.candidates),
        "present_relations": len(relations.understanding.relations),
        "packet_results": packet_results,
        "publication_query_delivery_context_use": 0,
    }
    evaluation = {
        "schema_version": "accepted-items-import-live-target-evaluation-1",
        "scorer_version": scorer.MATERIAL_DEVELOPMENT_SCORER_VERSION,
        "gold_scope": {
            "items": len(sample["items"]),
            "relations": len(sample["relations"]),
            "whole_document_negative_gold": False,
        },
        "metrics": {
            key: score[key]
            for key in (
                "item_recall",
                "critical_item_recall",
                "semantic_target_accuracy",
                "attribution_target_accuracy",
                "critical_all_fields_accuracy",
                "source_relation_recall",
            )
        },
        "counts": score["counts"],
        "gold_relation_matches": gold_relation_matches,
        "selected_endpoint_precision_diagnostic": score["source_relation_precision"],
        "whole_document_precision_measurable": False,
        "precision_reason": (
            "the frozen copper gold contains selected targets, not exhaustive negatives; "
            "two unmatched selected-endpoint edges are semantically plausible answers and "
            "must not be counted as whole-document false positives"
        ),
    }
    _write("relation-artifact.json", relation_artifact_raw)
    _write("relation-payload.json", relation_payload_raw)
    _write("execution-summary.json", execution_summary)
    _write("evaluation-summary.json", evaluation)
    print(
        json.dumps(
            {
                "model_calls": len(attempts),
                "usage": usage_totals,
                "candidates": len(candidate_set.candidates),
                "present": len(relations.understanding.relations),
                "relation_recall": score["source_relation_recall"],
                "packet_results": packet_results,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
