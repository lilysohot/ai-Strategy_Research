"""Freeze the zero-call replacement-Claims proof plans after the P1 gate failure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from plugins.corpus.claims_binding import (
    CLAIMS_SLOT_PROTOCOL_VERSION,
    build_claim_candidate_slots,
)
from plugins.corpus.claims_detail import (
    EXTRACTOR_VERSION_V2,
    LINT_VERSION,
    PERIOD_RULE_VERSION,
    UNIT_RULE_VERSION,
)
from plugins.corpus.evidence_pipeline import (
    CLAIMS_ATOMIC_PROTOCOL,
    PIPELINE_VERSION,
    evidence_document_from_snapshot,
)
from plugins.corpus.structured.config import RequestOptions, load_extraction_config
from plugins.corpus.structured.ledger import BatchPlan, Role, plan_batch
from plugins.corpus.structured.snapshot import EvidenceSnapshot

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
SOURCE_FREEZE = HERE / "p1-plan-freeze"
OUT = HERE / "p1r-claims-plan-freeze"
SOURCES = ("claims-industrial-fulian", "claims-optical-module")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def claims_plan(snapshot: EvidenceSnapshot, config: Any) -> BatchPlan:
    calls = len(snapshot.units)
    budgets: dict[Role, int] = {
        "claims": calls,
        "material_items": 0,
        "material_relations": 0,
    }
    return plan_batch(
        snapshot,
        config=config,
        max_attempts=calls,
        role_max_attempts=budgets,
        relations_enabled=False,
        max_relation_tasks=0,
        max_relation_attempts=0,
        enabled_roles=("claims",),
    )


def main() -> None:
    if OUT.exists():
        raise SystemExit("refusing to overwrite the P1R plan freeze")
    config = load_extraction_config(
        dotenv_path=REPO / ".env",
        options=RequestOptions(max_output_tokens=16_384),
    )
    profile = config.require_profile()
    entries: list[dict[str, object]] = []
    prepared: list[tuple[str, EvidenceSnapshot, BatchPlan, int, int]] = []
    for name in SOURCES:
        source_path = SOURCE_FREEZE / name / "snapshot.json"
        snapshot = EvidenceSnapshot.model_validate_json(source_path.read_text(encoding="utf-8"))
        snapshot.verify_identity()
        plan = claims_plan(snapshot, config)
        plan.verify_identity()
        protocols = {task.protocol for task in plan.tasks if task.role == "claims"}
        if protocols != {CLAIMS_ATOMIC_PROTOCOL}:
            raise ValueError(f"replacement Claims protocol drifted: {protocols}")
        document = evidence_document_from_snapshot(snapshot, role="claims")
        claim_task = next(task for task in plan.tasks if task.role == "claims")
        scoped_ids = set(claim_task.scoped_unit_ids)
        scoped_document = document.model_copy(
            update={
                "packets": tuple(
                    packet
                    for packet in document.packets
                    if any(span.locator in scoped_ids for span in packet.spans)
                )
            }
        )
        slots = build_claim_candidate_slots(scoped_document)
        prepared.append(
            (name, snapshot, plan, len(slots), len({slot.packet_id for slot in slots}))
        )

    OUT.mkdir(parents=True)
    for name, snapshot, plan, slot_count, candidate_packets in prepared:
        target = OUT / name
        save(target / "snapshot.json", snapshot.model_dump(mode="json"))
        save(target / "plan.json", plan.model_dump(mode="json"))
        freeze = {
            "stage": "replacement_claims_only_gate",
            "snapshot_id": snapshot.snapshot_id,
            "batch_id": plan.batch_id,
            "plan_sha256": plan.plan_sha256,
            "protocol": CLAIMS_ATOMIC_PROTOCOL,
            "slot_protocol": CLAIMS_SLOT_PROTOCOL_VERSION,
            "unit_count": len(snapshot.units),
            "candidate_slot_count": slot_count,
            "candidate_packet_count": candidate_packets,
            "attempt_ceiling": len(snapshot.units),
            "automatic_retries": 0,
            "concurrency": 1,
            "model_calls_during_planning": 0,
            "profile_sha256": profile.fingerprint,
            "model": profile.model,
            "adapter_version": profile.adapter_version,
            "max_output_tokens": profile.options.max_output_tokens,
            "gold_not_exposed_to_model": True,
            "production_database_access": 0,
            "publication_writes": 0,
        }
        save(target / "freeze.json", freeze)
        entries.append(
            {
                "name": name,
                **freeze,
                "snapshot_file_sha256": sha256(target / "snapshot.json"),
                "plan_file_sha256": sha256(target / "plan.json"),
                "freeze_file_sha256": sha256(target / "freeze.json"),
            }
        )

    manifest = {
        "schema_version": "structured-extraction-p1r-claims-plan-freeze-1",
        "status": "frozen_not_executed",
        "frozen_on": "2026-10-09",
        "cause": "P1 Claims recall upper bound 65% was below the frozen 75% floor",
        "execution_order": [
            "claims-industrial-fulian",
            "claims-optical-module",
            "claims_gate_evaluation",
        ],
        "stop_policy": "Any missing/conflicting claim-slot terminal or frozen quality-floor failure blocks publication and copper.",
        "total_attempt_ceiling": sum(int(entry["attempt_ceiling"]) for entry in entries),
        "model_calls_during_planning": 0,
        "versions": {
            "claims_protocol": CLAIMS_ATOMIC_PROTOCOL,
            "slot_protocol": CLAIMS_SLOT_PROTOCOL_VERSION,
            "extractor": EXTRACTOR_VERSION_V2,
            "pipeline": PIPELINE_VERSION,
            "lint": LINT_VERSION,
            "period_rules": PERIOD_RULE_VERSION,
            "unit_rules": UNIT_RULE_VERSION,
        },
        "profile": {
            "model": profile.model,
            "adapter_version": profile.adapter_version,
            "profile_sha256": profile.fingerprint,
            "request_options": profile.options.model_dump(mode="json"),
        },
        "entries": entries,
        "pre_execution_requirements": [
            "verify snapshot, plan and freeze hashes",
            "use the formal structured ledger with concurrency 1 and automatic retries 0",
            "require one terminal outcome for every frozen candidate_slot_id",
            "do not start copper or publication unless the signed replacement Claims gate passes",
        ],
        "prepare_script_sha256": sha256(Path(__file__)),
    }
    save(OUT / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
