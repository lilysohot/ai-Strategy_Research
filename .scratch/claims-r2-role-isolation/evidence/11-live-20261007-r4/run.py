"""Execute prompt-v3 material extraction in immutable one-call segments."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from plugins.corpus.evidence_pipeline import evidence_document_from_snapshot
from plugins.corpus.material_semantics import build_candidate_slots, build_material_structure
from plugins.corpus.structured.config import (
    ExtractionConfig,
    RequestOptions,
    load_extraction_config,
)
from plugins.corpus.structured.ledger import BatchPlan, check_batch, execute_batch, plan_batch
from plugins.corpus.structured.snapshot import EvidenceSnapshot

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]
SNAPSHOTS = ROOT.parent / "11-live-20261007-r2"
SEMANTICS = REPO / "plugins/corpus/material_semantics.py"


def save(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def extraction_config() -> ExtractionConfig:
    result = load_extraction_config(
        dotenv_path=REPO / ".env", options=RequestOptions(max_output_tokens=8192)
    )
    result.require_profile()
    return result


def prepare() -> None:
    source = json.loads((SNAPSHOTS / "manifest.json").read_text(encoding="utf-8"))
    assert not (ROOT / "manifest.json").exists()
    runner_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    semantics_hash = hashlib.sha256(SEMANTICS.read_bytes()).hexdigest()
    config = extraction_config()
    entries = []
    for entry in source["segments"]:
        name = entry["name"]
        target = ROOT / name
        assert not target.exists()
        snapshot = EvidenceSnapshot.model_validate_json(
            (SNAPSHOTS / name / "snapshot.json").read_text(encoding="utf-8")
        )
        snapshot.verify_identity()
        document = evidence_document_from_snapshot(snapshot, role="material_items")
        slots = build_candidate_slots(document, build_material_structure(document))
        assert len(slots) == entry["candidate_slot_count"] <= 8
        plan = plan_batch(
            snapshot,
            config=config,
            max_attempts=2,
            role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 1},
            relations_enabled=True,
            max_relation_tasks=1,
            max_relation_attempts=1,
            deadline_epoch=time.time() + 7200,
        )
        target.mkdir()
        save(target / "snapshot.json", snapshot.model_dump(mode="json"))
        save(target / "plan.json", plan.model_dump(mode="json"))
        save(
            target / "freeze.json",
            {
                "segment": name,
                "batch_id": plan.batch_id,
                "snapshot_id": snapshot.snapshot_id,
                "candidate_slot_count": len(slots),
                "runner_sha256": runner_hash,
                "material_semantics_sha256": semantics_hash,
                "items_calls": 1,
                "relation_calls": 1,
                "automatic_retries": 0,
            },
        )
        entries.append({"name": name, "batch_id": plan.batch_id, "slots": len(slots)})
    save(
        ROOT / "manifest.json",
        {
            "stage": "material_items_complete_field_contract_v3",
            "source_scope": source["scope"],
            "semantic_targets": source["semantic_targets"],
            "model": config.require_profile().model,
            "profile_sha256": config.require_profile().fingerprint,
            "runner_sha256": runner_hash,
            "material_semantics_sha256": semantics_hash,
            "automatic_retries": 0,
            "concurrency": 1,
            "segments": entries,
        },
    )
    print(json.dumps(entries, ensure_ascii=False, indent=2))


def verify(target: Path) -> tuple[BatchPlan, dict]:
    freeze = json.loads((target / "freeze.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == freeze["runner_sha256"]
    assert hashlib.sha256(SEMANTICS.read_bytes()).hexdigest() == freeze["material_semantics_sha256"]
    plan = BatchPlan.model_validate_json((target / "plan.json").read_text(encoding="utf-8"))
    assert plan.batch_id == freeze["batch_id"]
    return plan, freeze


def execute(segment: str) -> int:
    target = ROOT / segment
    plan, freeze = verify(target)
    save(target / "started.json", {"batch_id": plan.batch_id, "started_epoch": time.time()})
    result = execute_batch(
        plan, store_root=target / "store", allow_model=True, config=extraction_config()
    )
    save(target / "check.json", result.model_dump(mode="json"))
    item = next(task for task in result.ledger.tasks if task.role == "material_items")
    relations = [task for task in result.ledger.tasks if task.role == "material_relations"]
    summary = {
        "segment": segment,
        "batch_id": plan.batch_id,
        "candidate_slot_count": freeze["candidate_slot_count"],
        "material_items": item.model_dump(mode="json"),
        "material_relations": [task.model_dump(mode="json") for task in relations],
        "attempts": [attempt.model_dump(mode="json") for attempt in result.ledger.attempts],
        "plan_consistent": result.plan_consistent,
        "findings": list(result.findings),
        "cost_summary": [entry.model_dump(mode="json") for entry in result.cost_summary],
    }
    save(target / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    items_ok = (
        item.execution_status == "succeeded"
        and item.protocol_status == "valid"
        and item.quality_status == "accepted"
        and item.publication_status == "candidate"
    )
    relations_ok = all(
        task.execution_status == "succeeded"
        and task.protocol_status == "valid"
        and task.quality_status == "accepted"
        for task in relations
    )
    return 0 if items_ok and relations_ok and result.plan_consistent else 5


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "execute", "check"))
    parser.add_argument("segment", nargs="?")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
        return 0
    if not args.segment:
        parser.error("segment is required")
    if args.action == "execute":
        return execute(args.segment)
    target = ROOT / args.segment
    plan, _freeze = verify(target)
    print(check_batch(plan.batch_id, store_root=target / "store").model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
