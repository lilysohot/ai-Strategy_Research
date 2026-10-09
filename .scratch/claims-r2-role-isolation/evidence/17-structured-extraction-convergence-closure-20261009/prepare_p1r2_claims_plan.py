"""Freeze P1R2 after unique-quote slot rebinding was proven on P1R1 responses."""

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
OUT = HERE / "p1r2-claims-plan-freeze"
SOURCES = ("claims-industrial-fulian", "claims-optical-module")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def make_plan(snapshot: EvidenceSnapshot, config: Any) -> BatchPlan:
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
        raise SystemExit("refusing to overwrite the P1R2 plan freeze")
    config = load_extraction_config(
        dotenv_path=REPO / ".env",
        options=RequestOptions(max_output_tokens=16_384),
    )
    profile = config.require_profile()
    prepared = []
    for name in SOURCES:
        source_path = SOURCE_FREEZE / name / "snapshot.json"
        snapshot = EvidenceSnapshot.model_validate_json(source_path.read_text(encoding="utf-8"))
        snapshot.verify_identity()
        plan = make_plan(snapshot, config)
        plan.verify_identity()
        task = next(task for task in plan.tasks if task.role == "claims")
        if task.protocol != CLAIMS_ATOMIC_PROTOCOL:
            raise ValueError(f"replacement Claims protocol drifted: {task.protocol}")
        scope = set(task.scoped_unit_ids)
        document = evidence_document_from_snapshot(snapshot, role="claims")
        document = document.model_copy(
            update={
                "packets": tuple(
                    packet
                    for packet in document.packets
                    if any(span.locator in scope for span in packet.spans)
                )
            }
        )
        slots = build_claim_candidate_slots(document)
        prepared.append((name, snapshot, plan, slots))

    OUT.mkdir(parents=True)
    entries = []
    for name, snapshot, plan, slots in prepared:
        target = OUT / name
        save(target / "snapshot.json", snapshot.model_dump(mode="json"))
        save(target / "plan.json", plan.model_dump(mode="json"))
        mode = "replay_p1r1_responses" if name == SOURCES[0] else "live_model"
        freeze = {
            "stage": "replacement_claims_unique_quote_rebind_gate",
            "execution_mode": mode,
            "snapshot_id": snapshot.snapshot_id,
            "batch_id": plan.batch_id,
            "plan_sha256": plan.plan_sha256,
            "protocol": CLAIMS_ATOMIC_PROTOCOL,
            "slot_protocol": CLAIMS_SLOT_PROTOCOL_VERSION,
            "candidate_slot_count": len(slots),
            "candidate_packet_count": len({slot.packet_id for slot in slots}),
            "attempt_ceiling": plan.role_max_attempts["claims"],
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
        "schema_version": "structured-extraction-p1r2-claims-plan-freeze-1",
        "status": "frozen_not_executed",
        "frozen_on": "2026-10-09",
        "cause": (
            "P1R1 produced semantically usable records in two packets without copying slot IDs; "
            "v2 permits deterministic rebinding only for a unique exact quote owner"
        ),
        "execution_order": [*SOURCES, "claims_gate_evaluation"],
        "stop_policy": "Industrial replay failure blocks optical; any Claims gate failure blocks copper.",
        "maximum_new_model_calls": entries[1]["attempt_ceiling"],
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
        "p1r1_execution_sha256": sha256(HERE / "p1r-claims-plan-freeze/execution-summary.json"),
        "prepare_script_sha256": sha256(Path(__file__)),
    }
    save(OUT / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
