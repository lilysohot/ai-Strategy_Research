"""Execute the frozen conditional copper items/relations P1 plan exactly once."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from plugins.corpus.structured.config import RequestOptions, load_extraction_config
from plugins.corpus.structured.ledger import BatchCheck, BatchPlan, execute_batch

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
PLAN_FREEZE = HERE / "p1-plan-freeze"
TARGET = PLAN_FREEZE / "copper-items-relations"
MANIFEST = PLAN_FREEZE / "manifest.json"
PLAN = TARGET / "plan.json"
STORE = TARGET / "live-store"
OUTPUT = TARGET / "execution-summary.json"
SIGNED_GATE = HERE / "p1r5-claims-adjudication-v2/claims-gate-result.signed.json"
SIGNED_MANIFEST = (
    HERE
    / "p1r5-claims-adjudication-v2/candidate-adjudication-freeze-manifest.json"
)
GOLD = REPO / "data/corpus/.audit/r1_material_gold_v1_20260913.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def verify_authority() -> tuple[BatchPlan, dict[str, Any], dict[str, Any]]:
    signed = read_json(SIGNED_GATE)
    signed_manifest = read_json(SIGNED_MANIFEST)
    if (
        signed.get("status") != "passed"
        or signed.get("human_gate_satisfied") is not True
        or signed.get("quality_gate_passed") is not True
        or signed.get("authorize_copper_execution") is not True
        or signed.get("authorize_publication") is not False
    ):
        raise SystemExit("signed Claims gate does not authorize copper execution")
    if (
        signed_manifest.get("status") != "frozen"
        or signed_manifest.get("copper_execution_authorized") is not True
    ):
        raise SystemExit("signed Claims freeze manifest is not authoritative")
    for group in ("inputs", "outputs"):
        for name, expected in signed_manifest[group].items():
            if sha256(REPO / name) != expected:
                raise SystemExit(f"signed Claims freeze hash drifted: {name}")

    manifest = read_json(MANIFEST)
    entries = {entry["name"]: entry for entry in manifest["entries"]}
    entry = entries["copper-items-relations"]
    if (
        manifest.get("status") != "frozen_not_executed"
        or entry.get("automatic_retries") != 0
        or entry.get("concurrency") != 1
        or entry.get("role_attempt_ceiling")
        != {"claims": 0, "material_items": 12, "material_relations": 4}
        or entry.get("attempt_ceiling") != 16
    ):
        raise SystemExit("frozen copper policy changed")
    paths = {
        "snapshot_file_sha256": TARGET / "snapshot.json",
        "plan_file_sha256": PLAN,
        "freeze_file_sha256": TARGET / "freeze.json",
    }
    for field, path in paths.items():
        if sha256(path) != entry[field]:
            raise SystemExit(f"frozen copper file hash drifted: {path.name}")
    source = REPO / str(entry["source_path"])
    if sha256(source) != entry["source_sha256"]:
        raise SystemExit("copper source changed")
    if sha256(GOLD) != manifest["gold_file_sha256"]:
        raise SystemExit("frozen development gold changed")

    plan = BatchPlan.model_validate_json(PLAN.read_text(encoding="utf-8"))
    plan.verify_identity()
    if (
        plan.batch_id != entry["batch_id"]
        or plan.plan_sha256 != entry["plan_sha256"]
        or plan.role_max_attempts != entry["role_attempt_ceiling"]
        or plan.max_attempts != entry["attempt_ceiling"]
    ):
        raise SystemExit("copper plan identity changed")
    return plan, manifest, entry


def summarize(
    checked: BatchCheck, manifest: dict[str, Any], entry: dict[str, Any]
) -> dict[str, Any]:
    task_roles = {task.task_id: task.role for task in checked.ledger.tasks}
    attempts_by_role = Counter(
        task_roles[attempt.task_id] for attempt in checked.ledger.attempts
    )
    attempt_status_by_role = {
        role: dict(
            Counter(
                attempt.execution_status
                for attempt in checked.ledger.attempts
                if task_roles[attempt.task_id] == role
            )
        )
        for role in ("material_items", "material_relations")
    }
    task_summary = {}
    for role in ("material_items", "material_relations"):
        tasks = [task for task in checked.ledger.tasks if task.role == role]
        task_summary[role] = {
            "count": len(tasks),
            "execution_status": dict(Counter(task.execution_status for task in tasks)),
            "protocol_status": dict(Counter(task.protocol_status for task in tasks)),
            "quality_status": dict(Counter(task.quality_status for task in tasks)),
            "publication_status": dict(Counter(task.publication_status for task in tasks)),
            "artifact_sha256": [task.artifact_sha256 for task in tasks],
            "error_codes": sorted({code for task in tasks for code in task.error_codes}),
        }
    item_tasks = [task for task in checked.ledger.tasks if task.role == "material_items"]
    relation_tasks = [
        task for task in checked.ledger.tasks if task.role == "material_relations"
    ]
    items_valid = bool(item_tasks) and all(
        task.execution_status == "succeeded"
        and task.protocol_status == "valid"
        and task.quality_status == "accepted"
        for task in item_tasks
    )
    relations_valid = bool(relation_tasks) and all(
        task.execution_status == "succeeded"
        and task.protocol_status == "valid"
        and task.quality_status == "accepted"
        for task in relation_tasks
    )
    return {
        "schema_version": "structured-extraction-p1-copper-execution-1",
        "executed_on": "2026-10-09",
        "status": (
            "protocol_complete_pending_semantic_adjudication"
            if items_valid and relations_valid and checked.plan_consistent
            else "failed_or_partial_stop_replace_extractor"
        ),
        "claims_signed_gate_sha256": sha256(SIGNED_GATE),
        "claims_freeze_manifest_sha256": sha256(SIGNED_MANIFEST),
        "plan_manifest_sha256": sha256(MANIFEST),
        "plan_file_sha256": sha256(PLAN),
        "gold_file_sha256": sha256(GOLD),
        "batch_id": checked.ledger.batch_id,
        "plan_sha256": checked.ledger.plan_sha256,
        "attempt_ceiling": entry["attempt_ceiling"],
        "role_attempt_ceiling": entry["role_attempt_ceiling"],
        "actual_attempts": checked.ledger.budget.actual_attempts,
        "reserved_attempts": checked.ledger.budget.reserved_attempts,
        "attempts_by_role": dict(attempts_by_role),
        "attempt_status_by_role": attempt_status_by_role,
        "task_summary": task_summary,
        "items_protocol_gate_passed": items_valid,
        "relations_protocol_gate_passed": relations_valid,
        "plan_consistent": checked.plan_consistent,
        "findings": list(checked.findings),
        "derivations": checked.derivations,
        "cost_summary": [row.model_dump(mode="json") for row in checked.cost_summary],
        "automatic_retries": 0,
        "concurrency": 1,
        "production_database_access": 0,
        "publication_writes": 0,
        "publication_authorized": False,
        "next_action": (
            "score against frozen gold and prepare item/relation adjudications"
            if items_valid and relations_valid and checked.plan_consistent
            else "stop prompt and lexicon patching; preserve architecture and replace extractor implementation"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-model", action="store_true")
    args = parser.parse_args()
    if not args.allow_model:
        raise SystemExit("refusing copper model execution without --allow-model")
    if OUTPUT.exists() or STORE.exists():
        raise SystemExit("refusing to overwrite or resume the immutable copper execution")
    plan, manifest, entry = verify_authority()
    config = load_extraction_config(
        dotenv_path=REPO / ".env",
        options=RequestOptions(max_output_tokens=16_384),
    )
    if config.require_profile().fingerprint != manifest["profile"]["profile_sha256"]:
        raise SystemExit("configured extraction profile does not match the frozen plan")

    def checkpoint(name: str) -> None:
        print(json.dumps({"checkpoint": name}, ensure_ascii=False), flush=True)

    checked = execute_batch(
        plan,
        store_root=STORE,
        allow_model=True,
        config=config,
        checkpoint=checkpoint,
    )
    summary = summarize(checked, manifest, entry)
    save(OUTPUT, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
