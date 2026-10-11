"""Post-run zero-call reconciliation for the run-2 items-only verification.

Re-reads both batches from the store (read-only), rebuilds the candidate slot
scope, and evaluates the gate execution requirements: statuses, attempt
accounting, batch/partial/missing/duplicate/invalid caps, and role isolation.
Emits the item inventory (candidates file) and the structural gate result.
Quality thresholds (recall/precision/assertions) are NOT evaluated here; they
are scored separately against the signed v3 contract. No model call, no
production access.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
R0 = HERE.parent / "r0-zero-call"
sys.path.insert(0, str(R0))

import freeze_items_only_plan as frozen  # noqa: E402

from plugins.corpus.evidence_pipeline import build_evidence_run_from_snapshot  # noqa: E402
from plugins.corpus.material_semantics import (  # noqa: E402
    build_candidate_slots,
    build_material_structure,
)
from plugins.corpus.structured.ledger import BatchPlan, check_batch  # noqa: E402

STORE = HERE / "live-store"
SUMMARY = HERE / "live-run-summary.json"
EXPECTED_ATTEMPTS = {"industrial-fulian-md": 10, "optical-module-docx": 14}
ALLOWED_FINISH = {None, "stop", "completed", "end_turn"}
CLEAN_SLOT_STATUSES = {"extracted", "no_supported_item"}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_object(store: Path, object_sha: str) -> Any:
    hexdigest = object_sha.removeprefix("sha256:")
    path = store / "objects" / "sha256" / hexdigest[:2] / f"{hexdigest}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def payload_object_sha(store: Path, batch_id: str, task_id: str) -> str:
    connection = sqlite3.connect(
        f"file:{store / 'index' / 'structured.sqlite3'}?mode=ro", uri=True
    )
    try:
        row = connection.execute(
            "SELECT payload_object_sha256 FROM tasks WHERE batch_id=? AND task_id=?",
            (batch_id, task_id),
        ).fetchone()
        if row is None or not row[0]:
            raise RuntimeError(f"payload object missing: {batch_id}/{task_id}")
        return str(row[0])
    finally:
        connection.close()


def candidate_slot_ids(snapshot: Any) -> list[str]:
    run = build_evidence_run_from_snapshot(snapshot, role="material_items")
    document = run.document
    slots = build_candidate_slots(document, build_material_structure(document))
    return [slot.candidate_slot_id for slot in slots]


def main() -> None:
    summary = read_json(SUMMARY)
    replan = read_json(HERE / "replan-manifest.json")
    if summary["error"] is not None:
        raise RuntimeError(f"run-2 recorded an error: {summary['error']}")
    if not STORE.exists():
        raise RuntimeError("run-2 store is missing")

    built = {item["slug"]: item for item in frozen.scoped_sources()}
    sources: dict[str, Any] = {}
    candidates: dict[str, Any] = {
        "schema_version": "items-only-run2-candidates-1",
        "sources": {},
    }
    gate_unmet: list[str] = []

    for entry in replan["sources"]:
        slug = entry["slug"]
        expected = EXPECTED_ATTEMPTS[slug]
        plan = BatchPlan.model_validate_json(
            (HERE / f"plan-{slug}.json").read_text(encoding="utf-8")
        )
        plan.verify_identity()
        batch = check_batch(plan.batch_id, store_root=str(STORE.resolve()))
        ledger = batch.ledger

        tasks = [
            {
                "task_id": task.task_id,
                "role": task.role,
                "method": task.method,
                "execution_status": task.execution_status,
                "protocol_status": task.protocol_status,
                "quality_status": task.quality_status,
                "publication_status": task.publication_status,
                "context_status": task.context_status,
                "artifact_sha256": task.artifact_sha256,
                "error_codes": list(task.error_codes),
            }
            for task in ledger.tasks
        ]
        items_task = next(
            (task for task in ledger.tasks if task.role == "material_items"), None
        )
        attempts = ledger.attempts
        role_by_task = {task.task_id: task.role for task in ledger.tasks}
        attempt_roles = Counter(role_by_task.get(item.task_id, "unknown") for item in attempts)

        slot_statuses: dict[str, Any] = {}
        items_inventory: dict[str, Any] = {}
        packet_statuses: dict[str, Any] = {}
        omitted: list[str] = []
        missing_slots: list[str] = []
        duplicate_slots: list[str] = []
        invalid_slots: list[str] = []
        batch_attempt_flags: list[Any] = []
        finish_flags: list[Any] = []
        if items_task is not None:
            payload = read_object(
                STORE, payload_object_sha(STORE, ledger.batch_id, items_task.task_id)
            )
            understanding = payload.get("understanding", {})
            coverage = understanding.get("coverage", {})
            slot_ledger = coverage.get("slot_ledger", [])
            omitted = list(coverage.get("omitted_areas", []))
            built_ids = candidate_slot_ids(built[slug]["snapshot"])
            ledger_ids = [row.get("candidate_slot_id") for row in slot_ledger]
            counts = Counter(ledger_ids)
            missing_slots = sorted(set(built_ids) - set(ledger_ids))
            duplicate_slots = sorted(key for key, value in counts.items() if value > 1)
            invalid_slots = sorted(
                str(row.get("candidate_slot_id"))
                for row in slot_ledger
                if row.get("status") not in CLEAN_SLOT_STATUSES
            )
            slot_statuses = dict(Counter(row.get("status") for row in slot_ledger))
            items = understanding.get("items", [])
            items_inventory = {
                "total": len(items),
                "by_statement_role": dict(
                    Counter(item.get("statement_role") for item in items)
                ),
                "by_semantic_type": dict(
                    Counter(item.get("semantic_type") for item in items)
                ),
                "by_perspective": dict(Counter(item.get("perspective") for item in items)),
                "empty_text": sum(
                    1 for item in items if not (item.get("text") or "").strip()
                ),
                "missing_evidence": sum(1 for item in items if not item.get("evidence")),
            }
            runs = payload.get("packet_runs", [])
            packet_statuses = dict(Counter(run.get("status") for run in runs))
            for run in runs:
                details = (
                    run.get("diagnostics", {}).get("stages", {}).get("item_batches", [])
                )
                for detail in details:
                    batch_attempt_flags.append(detail.get("attempts"))
                    finish_flags.append(detail.get("finish_reason"))
            candidates["sources"][slug] = {
                "candidate_slots": [
                    {
                        "candidate_slot_id": row.get("candidate_slot_id"),
                        "status": row.get("status"),
                    }
                    for row in slot_ledger
                ],
                "items": [
                    {
                        "item_id": item.get("item_id"),
                        "statement_role": item.get("statement_role"),
                        "semantic_type": item.get("semantic_type"),
                        "perspective": item.get("perspective"),
                        "text": item.get("text"),
                        "evidence": item.get("evidence"),
                    }
                    for item in items
                ],
            }

        record = {
            "batch_id": ledger.batch_id,
            "plan_sha256": ledger.plan_sha256,
            "snapshot_id": ledger.snapshot_id,
            "plan_consistent": batch.plan_consistent,
            "findings": list(batch.findings),
            "derivations": dict(batch.derivations),
            "budget": ledger.budget.model_dump(),
            "tasks": tasks,
            "attempts": len(attempts),
            "attempt_status": dict(Counter(item.execution_status for item in attempts)),
            "attempt_roles": dict(attempt_roles),
            "request_models": sorted({item.request_model for item in attempts}),
            "response_models": sorted(
                {item.response_model for item in attempts if item.response_model}
            ),
            "batch_attempt_flags": batch_attempt_flags,
            "finish_flags": finish_flags,
            "slot_statuses": slot_statuses,
            "missing_slots": missing_slots,
            "duplicate_slots": duplicate_slots,
            "invalid_slots": invalid_slots,
            "omitted_areas": omitted,
            "packet_statuses": packet_statuses,
            "items": items_inventory,
        }
        sources[slug] = record

        # Gate execution requirements (structural part).
        unmet: list[str] = []
        if len(attempts) != expected:
            unmet.append(f"{slug}:attempts={len(attempts)}!=expected={expected}")
        if record["attempt_status"].get("failed"):
            unmet.append(f"{slug}:failed_attempts={record['attempt_status']['failed']}")
        if set(attempt_roles) - {"material_items"}:
            unmet.append(f"{slug}:foreign_role_attempts={dict(attempt_roles)}")
        if items_task is None:
            unmet.append(f"{slug}:missing_items_task")
        else:
            if items_task.execution_status != "succeeded":
                unmet.append(f"{slug}:execution={items_task.execution_status}")
            if items_task.protocol_status != "valid":
                unmet.append(f"{slug}:protocol={items_task.protocol_status}")
            if items_task.context_status != "complete":
                unmet.append(f"{slug}:context={items_task.context_status}")
        if set(record["derivations"].values()) - {"disabled"}:
            unmet.append(f"{slug}:relation_derivation={record['derivations']}")
        if record["findings"]:
            unmet.append(f"{slug}:findings={record['findings']}")
        if any(flag not in (1, None) for flag in batch_attempt_flags):
            unmet.append(f"{slug}:adapter_attempts={batch_attempt_flags}")
        if any(flag not in ALLOWED_FINISH for flag in finish_flags):
            unmet.append(f"{slug}:finish_flags={finish_flags}")
        if any(status != "completed" for status in packet_statuses):
            unmet.append(f"{slug}:packet_statuses={packet_statuses}")
        if missing_slots:
            unmet.append(f"{slug}:missing_slots={len(missing_slots)}")
        if duplicate_slots:
            unmet.append(f"{slug}:duplicate_slots={len(duplicate_slots)}")
        if invalid_slots:
            unmet.append(f"{slug}:failed_or_partial_slots={len(invalid_slots)}")
        if omitted:
            unmet.append(f"{slug}:omitted_areas={len(omitted)}")
        gate_unmet.extend(unmet)
        record["gate_unmet"] = unmet

    report = {
        "schema_version": "items-only-post-run-check-r2-1",
        "checked_on": "2026-10-11",
        "model": summary["model"],
        "gate_revision": summary["gate_revision"],
        "gate_sha256": summary["gate_sha256"],
        "replan_manifest_sha256": summary["replan_manifest_sha256"],
        "run_summary_sha256": "sha256:"
        + hashlib.sha256(SUMMARY.read_bytes()).hexdigest(),
        "store_root": summary["store_root"],
        "sources": sources,
        "gate_execution": {
            "status": "pass" if not gate_unmet else "fail",
            "unmet": gate_unmet,
            "evaluated": [
                "attempts==attempts_max==completed_batches_min",
                "failed_batches_max=0",
                "partial_batches_max=0",
                "missing_duplicate_invalid_max=0",
                "execution_status=succeeded",
                "protocol_status=valid",
                "context_status=complete",
                "claims_attempts=0",
                "material_relations_attempts=0",
                "automatic_retries=0 (adapter attempts==1)",
            ],
        },
        "quality_scoring": {
            "status": "pending_scoring_step",
            "note": (
                "target recall / precision / accepted records / 16 high-risk assertions are "
                "scored against the signed non-table-selected-target-scoring-contract-v3 in a "
                "separate zero-call step; this check only covers execution requirements."
            ),
        },
        "model_requests_during_check": 0,
        "production_database_access": 0,
    }
    (HERE / "post-run-check.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "run2-candidates.json").write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "gate_execution": report["gate_execution"],
                "sources": {
                    slug: {
                        "attempts": record["attempts"],
                        "attempt_status": record["attempt_status"],
                        "tasks": [
                            (
                                task["role"],
                                task["execution_status"],
                                task["protocol_status"],
                                task["context_status"],
                            )
                            for task in record["tasks"]
                        ],
                        "packet_statuses": record["packet_statuses"],
                        "slot_statuses": record["slot_statuses"],
                        "items": record["items"],
                    }
                    for slug, record in sources.items()
                },
                "model_requests": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
