"""Freeze and execute the prompt-v2 material-items round one segment at a time."""

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
SOURCE_RUN = ROOT.parent / "11-live-20261007-r2"
SEMANTICS_SOURCE = REPO / "plugins/corpus/material_semantics.py"


def save(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def config() -> ExtractionConfig:
    value = load_extraction_config(
        dotenv_path=REPO / ".env",
        options=RequestOptions(max_output_tokens=8192),
    )
    value.require_profile()
    return value


def prepare() -> None:
    source_manifest = json.loads((SOURCE_RUN / "manifest.json").read_text(encoding="utf-8"))
    assert not (ROOT / "manifest.json").exists()
    assert source_manifest["automatic_retries"] == 0
    runner_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    semantics_sha256 = hashlib.sha256(SEMANTICS_SOURCE.read_bytes()).hexdigest()
    extraction_config = config()
    entries = []
    for source_entry in source_manifest["segments"]:
        name = source_entry["name"]
        run = ROOT / name
        assert not run.exists()
        snapshot = EvidenceSnapshot.model_validate_json(
            (SOURCE_RUN / name / "snapshot.json").read_text(encoding="utf-8")
        )
        snapshot.verify_identity()
        document = evidence_document_from_snapshot(snapshot, role="material_items")
        slots = build_candidate_slots(document, build_material_structure(document))
        assert len(slots) == source_entry["candidate_slot_count"] <= 8
        plan = plan_batch(
            snapshot,
            config=extraction_config,
            max_attempts=2,
            role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 1},
            relations_enabled=True,
            max_relation_tasks=1,
            max_relation_attempts=1,
            deadline_epoch=time.time() + 7200,
        )
        run.mkdir()
        save(run / "snapshot.json", snapshot.model_dump(mode="json"))
        save(run / "plan.json", plan.model_dump(mode="json"))
        freeze = {
            "segment": name,
            "batch_id": plan.batch_id,
            "snapshot_id": snapshot.snapshot_id,
            "candidate_slot_count": len(slots),
            "runner_sha256": runner_sha256,
            "material_semantics_sha256": semantics_sha256,
            "material_items_call_ceiling": 1,
            "material_relations_call_ceiling": 1,
            "automatic_retries": 0,
            "supersedes_failed_r2_batch": (
                source_entry["batch_id"] if name == "01_results" else None
            ),
        }
        save(run / "freeze.json", freeze)
        entries.append(
            {
                "name": name,
                "batch_id": plan.batch_id,
                "snapshot_id": snapshot.snapshot_id,
                "candidate_slot_count": len(slots),
            }
        )
    save(
        ROOT / "manifest.json",
        {
            "stage": "material_items_prompt_contract_v2",
            "source_scope": source_manifest["scope"],
            "semantic_targets": source_manifest["semantic_targets"],
            "model": extraction_config.require_profile().model,
            "profile_sha256": extraction_config.require_profile().fingerprint,
            "runner_sha256": runner_sha256,
            "material_semantics_sha256": semantics_sha256,
            "automatic_retries": 0,
            "concurrency": 1,
            "segments": entries,
        },
    )
    print(json.dumps(entries, ensure_ascii=False, indent=2))


def verify(run: Path) -> tuple[BatchPlan, dict]:
    frozen = json.loads((run / "freeze.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == frozen["runner_sha256"]
    assert (
        hashlib.sha256(SEMANTICS_SOURCE.read_bytes()).hexdigest()
        == frozen["material_semantics_sha256"]
    )
    plan = BatchPlan.model_validate_json((run / "plan.json").read_text(encoding="utf-8"))
    assert plan.batch_id == frozen["batch_id"]
    assert plan.snapshot.snapshot_id == frozen["snapshot_id"]
    return plan, frozen


def execute(segment: str) -> int:
    run = ROOT / segment
    plan, frozen = verify(run)
    save(run / "started.json", {"started_epoch": time.time(), "batch_id": plan.batch_id})
    result = execute_batch(plan, store_root=run / "store", allow_model=True, config=config())
    save(run / "check.json", result.model_dump(mode="json"))
    item = next(task for task in result.ledger.tasks if task.role == "material_items")
    relation_tasks = [task for task in result.ledger.tasks if task.role == "material_relations"]
    summary = {
        "segment": segment,
        "batch_id": plan.batch_id,
        "candidate_slot_count": frozen["candidate_slot_count"],
        "material_items": item.model_dump(mode="json"),
        "material_relations": [task.model_dump(mode="json") for task in relation_tasks],
        "attempts": [attempt.model_dump(mode="json") for attempt in result.ledger.attempts],
        "plan_consistent": result.plan_consistent,
        "findings": list(result.findings),
        "cost_summary": [entry.model_dump(mode="json") for entry in result.cost_summary],
    }
    save(run / "summary.json", summary)
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
        for task in relation_tasks
    )
    return 0 if items_ok and relations_ok and result.plan_consistent else 5


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("prepare")
    execute_parser = subparsers.add_parser("execute")
    execute_parser.add_argument("segment")
    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("segment")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
        return 0
    if args.action == "execute":
        return execute(args.segment)
    run = ROOT / args.segment
    plan, _frozen = verify(run)
    print(check_batch(plan.batch_id, store_root=run / "store").model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
