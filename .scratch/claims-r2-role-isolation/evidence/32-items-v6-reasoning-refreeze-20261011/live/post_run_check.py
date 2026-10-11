"""Post-run zero-call reconciliation for the issue-32 two-arm gate.

Re-reads both arms from their stores (read-only), rebuilds the candidate slot scope and
evaluates the frozen exit criteria per arm: statuses, attempt accounting, batch/slot
caps, role isolation, the reasoning-token evidence and the control-arm requirement.
Quality thresholds are NOT scored here. No model call, no production access.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E32 = HERE.parent
CLAIMS = E32.parent.parent
R0 = E32 / "r0-zero-call"
E28_R0 = CLAIMS / "evidence" / "28-items-only-quality-gate-20261010" / "r0-zero-call"
ORDER = ("industrial-fulian-md", "optical-module-docx")
ARMS = ("control", "treatment")
EXPECTED_ATTEMPTS = {"industrial-fulian-md": 10, "optical-module-docx": 14}
ALLOWED_FINISH = {None, "stop", "completed", "end_turn"}
CLEAN_SLOT_STATUSES = {"extracted", "no_supported_item"}

from plugins.corpus.evidence_pipeline import evidence_document_from_snapshot  # noqa: E402
from plugins.corpus.material_semantics import (  # noqa: E402
    build_candidate_slots,
    build_material_structure,
)
from plugins.corpus.structured.ledger import BatchPlan, check_batch  # noqa: E402
from plugins.corpus.structured.snapshot import EvidenceSnapshot  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


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


def candidate_slot_ids(snapshot: EvidenceSnapshot) -> list[str]:
    document = evidence_document_from_snapshot(snapshot, role="material_items")
    slots = build_candidate_slots(document, build_material_structure(document))
    return [slot.candidate_slot_id for slot in slots]


def main() -> None:
    freeze = read_json(R0 / "freeze-manifest.json")
    gate = read_json(R0 / "preregistered-gate.json")
    baseline = {
        entry["slug"]: entry
        for entry in read_json(E28_R0 / "freeze-manifest.json")["sources"]
    }
    snapshots = {slug: None for slug in ORDER}
    for arm in ARMS:
        for slug in ORDER:
            plan = BatchPlan.model_validate_json(
                (R0 / f"plan-{arm}-{slug}.json").read_text(encoding="utf-8")
            )
            snapshots[slug] = plan.snapshot

    arms_report: dict[str, Any] = {}
    candidates: dict[str, Any] = {
        "schema_version": "items-v6-reasoning-candidates-1",
        "sources": {},
    }
    gate_unmet: dict[str, list[str]] = {arm: [] for arm in ARMS}
    reasoning_totals: dict[str, int] = {}

    for arm in ARMS:
        summary = read_json(HERE / f"{arm}-run-summary.json")
        arm_entries: dict[str, Any] = {}
        reasoning_totals[arm] = sum(
            (source.get("usage") or {}).get("reasoning_tokens") or 0
            for source in summary["sources"].values()
        )
        for slug in ORDER:
            expected = EXPECTED_ATTEMPTS[slug]
            store = HERE / f"{arm}-store" / slug
            plan = BatchPlan.model_validate_json(
                (R0 / f"plan-{arm}-{slug}.json").read_text(encoding="utf-8")
            )
            plan.verify_identity()
            batch = check_batch(plan.batch_id, store_root=str(store.resolve()))
            ledger = batch.ledger
            attempts = ledger.attempts
            role_by_task = {task.task_id: task.role for task in ledger.tasks}
            attempt_roles = Counter(role_by_task.get(item.task_id, "unknown") for item in attempts)
            items_task = next(
                (task for task in ledger.tasks if task.role == "material_items"), None
            )
            usage = {
                key: sum((item.usage or {}).get(key) or 0 for item in attempts)
                for key in (
                    "prompt_tokens",
                    "completion_tokens",
                    "reasoning_tokens",
                    "total_tokens",
                )
            }
            reasoning_present = any(
                item.usage is not None and "reasoning_tokens" in item.usage for item in attempts
            )
            slot_statuses: dict[str, Any] = {}
            packet_statuses: dict[str, Any] = {}
            batch_diagnostics: list[dict[str, Any]] = []
            omitted: list[str] = []
            missing_slots: list[str] = []
            duplicate_slots: list[str] = []
            invalid_slots: list[str] = []
            items_inventory: dict[str, Any] = {"total": 0}
            if items_task is not None and items_task.execution_status != "cancelled":
                payload = read_object(
                    store, payload_object_sha(store, ledger.batch_id, items_task.task_id)
                )
                understanding = payload.get("understanding", {})
                coverage = understanding.get("coverage", {})
                slot_ledger = coverage.get("slot_ledger", [])
                omitted = list(coverage.get("omitted_areas", []))
                built_ids = candidate_slot_ids(plan.snapshot)
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
                }
                packet_statuses = dict(
                    Counter(run.get("status") for run in payload.get("packet_runs", []))
                )
                for run in payload.get("packet_runs", []):
                    stages = (run.get("diagnostics") or {}).get("stages") or {}
                    for detail in stages.get("item_batches", []) or []:
                        batch_diagnostics.append(
                            {
                                "batch_index": detail.get("batch_index"),
                                "candidate_slots": detail.get("candidate_slots"),
                                "attempts": detail.get("attempts"),
                                "finish_reason": detail.get("finish_reason"),
                                "error_type": detail.get("error_type"),
                                "validation_error": detail.get("validation_error"),
                                "discarded_records": detail.get("discarded_records"),
                            }
                        )
                candidates["sources"][f"{arm}/{slug}"] = {
                    "candidate_slots": [
                        {
                            "candidate_slot_id": row.get("candidate_slot_id"),
                            "status": row.get("status"),
                            "reason_codes": row.get("reason_codes"),
                        }
                        for row in slot_ledger
                    ],
                    "items": [
                        {
                            "item_id": item.get("item_id"),
                            "text": item.get("text"),
                            "statement_role": item.get("statement_role"),
                            "semantic_type": item.get("semantic_type"),
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
                "attempts": len(attempts),
                "expected_attempts": expected,
                "attempt_status": dict(Counter(item.execution_status for item in attempts)),
                "attempt_roles": dict(attempt_roles),
                "usage": usage,
                "reasoning_tokens_field_present": reasoning_present,
                "tasks": [
                    {
                        "role": task.role,
                        "method": task.method,
                        "execution_status": task.execution_status,
                        "protocol_status": task.protocol_status,
                        "quality_status": task.quality_status,
                        "context_status": task.context_status,
                        "error_codes": list(task.error_codes),
                    }
                    for task in ledger.tasks
                ],
                "slot_statuses": slot_statuses,
                "missing_slots": missing_slots,
                "duplicate_slots": duplicate_slots,
                "invalid_slots": invalid_slots,
                "omitted_areas": omitted,
                "packet_statuses": packet_statuses,
                "batch_diagnostics": batch_diagnostics,
                "items": items_inventory,
            }
            arm_entries[slug] = record

            unmet: list[str] = []
            if len(attempts) != expected:
                unmet.append(f"{slug}:attempts={len(attempts)}!=expected={expected}")
            if attempt_roles and set(attempt_roles) - {"material_items"}:
                unmet.append(f"{slug}:foreign_role_attempts={dict(attempt_roles)}")
            unknown = record["attempt_status"].get("outcome_unknown")
            if unknown:
                unmet.append(f"{slug}:transport_outcome_unknown={unknown}")
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
            if any(
                detail.get("attempts") not in (1, None) for detail in batch_diagnostics
            ):
                unmet.append(f"{slug}:adapter_attempts!=1")
            if any(
                detail.get("finish_reason") not in ALLOWED_FINISH
                for detail in batch_diagnostics
            ):
                unmet.append(f"{slug}:finish_reasons")
            if packet_statuses and any(
                status != "completed" for status in packet_statuses
            ):
                unmet.append(f"{slug}:packet_statuses={packet_statuses}")
            if missing_slots:
                unmet.append(f"{slug}:missing_slots={len(missing_slots)}")
            if duplicate_slots:
                unmet.append(f"{slug}:duplicate_slots={len(duplicate_slots)}")
            if invalid_slots:
                unmet.append(f"{slug}:failed_or_partial_slots={len(invalid_slots)}")
            if omitted:
                unmet.append(f"{slug}:omitted_areas={len(omitted)}")
            if reasoning_present and usage["reasoning_tokens"] != 0:
                unmet.append(f"{slug}:reasoning_tokens={usage['reasoning_tokens']}")
            if missing_slots or duplicate_slots:
                unmet.append(f"{slug}:slot_coverage_incomplete")
            else:
                covered = sum(
                    value
                    for status, value in slot_statuses.items()
                    if status in CLEAN_SLOT_STATUSES
                )
                if covered < baseline[slug]["candidate_slot_count"]:
                    unmet.append(
                        f"{slug}:clean_slots={covered}"
                        f"<{baseline[slug]['candidate_slot_count']}"
                    )
            gate_unmet[arm].extend(unmet)
            record["gate_unmet"] = unmet
        arms_report[arm] = {
            "protocol": freeze["arms"][arm]["protocol"],
            "profile_sha256": freeze["arms"][arm]["profile_sha256"],
            "request_options": freeze["arms"][arm]["request_options"],
            "reasoning_tokens_total": reasoning_totals[arm],
            "sources": arm_entries,
            "gate_unmet": gate_unmet[arm],
        }

    control_failed = bool(gate_unmet["control"])
    treatment_passed = not gate_unmet["treatment"]
    report = {
        "schema_version": "items-v6-reasoning-post-run-check-1",
        "checked_on": "2026-10-11",
        "model": freeze["arms"]["control"]["model"],
        "gate_sha256": digest(R0 / "preregistered-gate.json"),
        "freeze_manifest_sha256": digest(R0 / "freeze-manifest.json"),
        "run_summaries": {
            arm: digest(HERE / f"{arm}-run-summary.json") for arm in ARMS
        },
        "arms": arms_report,
        "reasoning_tokens": reasoning_totals,
        "control_arm_reproduced_failure": control_failed,
        "treatment_arm_passed": treatment_passed,
        "gate_execution": {
            "status": "pass" if treatment_passed else "fail",
            "treatment_unmet": gate_unmet["treatment"],
            "control_unmet": gate_unmet["control"],
        },
        "quality_scoring": {
            "status": "not_in_this_gate",
            "note": "target recall / precision / 16 assertions are a separate downstream gate",
        },
        "model_requests_during_check": 0,
        "production_database_access": 0,
    }
    (HERE / "post-run-check.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "candidates.json").write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "reasoning_tokens": reasoning_totals,
                "control_arm_reproduced_failure": control_failed,
                "treatment_arm_passed": treatment_passed,
                "treatment_unmet": gate_unmet["treatment"],
                "control_unmet": gate_unmet["control"],
                "arms": {
                    arm: {
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
                            "slot_statuses": record["slot_statuses"],
                            "packet_statuses": record["packet_statuses"],
                            "items": record["items"],
                            "usage": record["usage"],
                            "batch_errors": [
                                {
                                    "batch_index": detail["batch_index"],
                                    "error_type": detail["error_type"],
                                    "validation_error": detail["validation_error"],
                                }
                                for detail in record["batch_diagnostics"]
                                if detail.get("error_type")
                            ],
                        }
                        for slug, record in arms_report[arm]["sources"].items()
                    }
                    for arm in ARMS
                },
                "model_requests": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
