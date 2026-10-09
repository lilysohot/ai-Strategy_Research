"""Freeze the zero-call P1 Claims and copper material execution plans."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from plugins.corpus.evidence_pipeline import build_evidence_run, evidence_document_from_snapshot
from plugins.corpus.material_semantics import (
    MATERIAL_EXTRACTOR_VERSION,
    MATERIAL_ITEMS_VALIDATION_VERSION,
    MATERIAL_SLOT_BATCHING_VERSION,
    MATERIAL_SLOT_JSONL_VERSION,
    RELATION_CANDIDATE_RULE_VERSION,
    build_candidate_slot_batches,
    build_candidate_slots,
    build_material_structure,
)
from plugins.corpus.structured.config import RequestOptions, canonical_hash, load_extraction_config
from plugins.corpus.structured.ledger import BatchPlan, Role, plan_batch
from plugins.corpus.structured.snapshot import (
    EvidenceSnapshot,
    SnapshotBuildSource,
    SnapshotDocumentSource,
    SnapshotHead,
    SnapshotUnitSource,
    build_snapshot,
)

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
OUT = HERE / "p1-plan-freeze"
SIGNED_RUN = HERE.parent / "11-live-20261008-non-table-gold-r2"
GOLD = REPO / "data/corpus/.audit/r1_material_gold_v1_20260913.json"
COPPER = REPO / "data/corpus/5月：锂电铜箔和电子铜箔.md"
CLAIMS_SOURCES = (
    ("claims-industrial-fulian", "industrial-fulian-md"),
    ("claims-optical-module", "optical-module-docx"),
)


class FrozenReader:
    def __init__(self, payload: SnapshotBuildSource) -> None:
        self.payload = payload

    def read_head(self, source_id: str) -> SnapshotHead:
        if source_id != self.payload.head.source_id:
            raise ValueError("source changed")
        return self.payload.head

    def read_build(self, head: SnapshotHead) -> SnapshotBuildSource:
        if head != self.payload.head:
            raise ValueError("head changed")
        return self.payload


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


def copper_snapshot() -> EvidenceSnapshot:
    source_sha256 = sha256(COPPER)
    run = build_evidence_run(COPPER, packet_chars=3_000)
    versions = {
        "parse": run.document.parser_version,
        "clean": "material-development-clean-1",
        "chunk": "evidence-packet-3000-v1",
        "adapter": "p1-copper-freeze-1",
    }
    packets = [
        {"packet_id": packet.packet_id, "text": packet.text}
        for packet in run.document.packets
    ]
    build_id = canonical_hash(
        {
            "source": source_sha256,
            "parse_rev": run.document.parse_rev,
            "versions": versions,
            "packets": packets,
        }
    )[7:]
    payload = SnapshotBuildSource(
        head=SnapshotHead(
            source_id=source_sha256,
            build_id=build_id,
            publication_generation=1,
        ),
        parser_versions=versions,
        document=SnapshotDocumentSource(title=run.document.title),
        units=tuple(
            SnapshotUnitSource(
                source_unit_id=f"packet-{index}-{packet.packet_id[:12]}",
                chunk_id="chunk:copper-p1",
                kind="prose",
                text=packet.text,
                locator=f"packet[{index}]",
                ordinal=index,
                metadata={
                    "original_packet_id": packet.packet_id,
                    "original_locator": packet.locator,
                    "parse_rev": run.document.parse_rev,
                    "packet_chars": 3_000,
                    "gold_not_exposed_to_model": True,
                },
            )
            for index, packet in enumerate(run.document.packets, 1)
        ),
    )
    snapshot = build_snapshot(FrozenReader(payload), source_sha256)
    snapshot.verify_identity()
    return snapshot


def copper_plan(snapshot: EvidenceSnapshot, config: Any) -> tuple[BatchPlan, dict[str, int]]:
    document = evidence_document_from_snapshot(snapshot, role="material_items")
    slots = build_candidate_slots(document, build_material_structure(document))
    batches = build_candidate_slot_batches(
        slots,
        max_slots_per_batch=48,
        max_items_per_batch=64,
    )
    counts = {
        "snapshot_units": len(snapshot.units),
        "candidate_slots": len(slots),
        "item_batches": len(batches),
        "candidate_packets": len({slot.packet_id for slot in slots}),
    }
    if counts != {
        "snapshot_units": 4,
        "candidate_slots": 487,
        "item_batches": 12,
        "candidate_packets": 4,
    }:
        raise ValueError(f"copper deterministic scope drifted: {counts}")
    budgets: dict[Role, int] = {
        "claims": 0,
        "material_items": counts["item_batches"],
        "material_relations": counts["candidate_packets"],
    }
    plan = plan_batch(
        snapshot,
        config=config,
        max_attempts=budgets["material_items"] + budgets["material_relations"],
        role_max_attempts=budgets,
        relations_enabled=True,
        max_relation_tasks=1,
        max_relation_attempts=budgets["material_relations"],
        enabled_roles=("material_items", "material_relations"),
        max_items_per_packet=64,
        max_slots_per_batch=48,
        material_type="conference_minutes",
    )
    return plan, counts


def main() -> None:
    if OUT.exists():
        raise SystemExit("refusing to overwrite the P1 plan freeze")
    config = load_extraction_config(
        dotenv_path=REPO / ".env",
        options=RequestOptions(max_output_tokens=16_384),
    )
    profile = config.require_profile()
    prepared: list[tuple[str, EvidenceSnapshot, BatchPlan, dict[str, object]]] = []
    for name, source_slug in CLAIMS_SOURCES:
        source_path = SIGNED_RUN / source_slug / "snapshot.json"
        snapshot = EvidenceSnapshot.model_validate_json(source_path.read_text(encoding="utf-8"))
        snapshot.verify_identity()
        plan = claims_plan(snapshot, config)
        plan.verify_identity()
        prepared.append(
            (
                name,
                snapshot,
                plan,
                {
                    "stage": "claims_only_gate",
                    "source_snapshot_path": str(source_path.relative_to(REPO)),
                    "source_snapshot_sha256": sha256(source_path),
                    "unit_count": len(snapshot.units),
                    "attempt_ceiling": len(snapshot.units),
                },
            )
        )
    copper = copper_snapshot()
    material_plan, copper_counts = copper_plan(copper, config)
    material_plan.verify_identity()
    prepared.append(
        (
            "copper-items-relations",
            copper,
            material_plan,
            {
                "stage": "copper_items_then_relations",
                "source_path": str(COPPER.relative_to(REPO)),
                "source_sha256": sha256(COPPER),
                **copper_counts,
                "item_attempt_ceiling": 12,
                "relation_attempt_ceiling": 4,
                "attempt_ceiling": 16,
            },
        )
    )
    OUT.mkdir(parents=True)
    entries = []
    for name, snapshot, plan, details in prepared:
        target = OUT / name
        save(target / "snapshot.json", snapshot.model_dump(mode="json"))
        save(target / "plan.json", plan.model_dump(mode="json"))
        freeze = {
            **details,
            "snapshot_id": snapshot.snapshot_id,
            "batch_id": plan.batch_id,
            "plan_sha256": plan.plan_sha256,
            "enabled_roles": list(plan.enabled_roles),
            "role_attempt_ceiling": plan.role_max_attempts,
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
        "schema_version": "structured-extraction-p1-plan-freeze-1",
        "status": "frozen_not_executed",
        "frozen_on": "2026-10-09",
        "execution_order": [
            "claims-industrial-fulian",
            "claims-optical-module",
            "claims_gate_evaluation",
            "copper-items-relations_if_and_only_if_claims_gate_passes",
        ],
        "stop_policy": "Claims failure blocks the copper plan; item failure blocks derived relations.",
        "total_claims_attempt_ceiling": 24,
        "conditional_copper_attempt_ceiling": 16,
        "maximum_total_attempt_ceiling": 40,
        "model_calls_during_planning": 0,
        "versions": {
            "material_extractor": MATERIAL_EXTRACTOR_VERSION,
            "slot_batching": MATERIAL_SLOT_BATCHING_VERSION,
            "item_protocol": MATERIAL_SLOT_JSONL_VERSION,
            "item_validation": MATERIAL_ITEMS_VALIDATION_VERSION,
            "relation_candidates": RELATION_CANDIDATE_RULE_VERSION,
        },
        "profile": {
            "model": profile.model,
            "adapter_version": profile.adapter_version,
            "profile_sha256": profile.fingerprint,
            "request_options": profile.options.model_dump(mode="json"),
        },
        "entries": entries,
        "pre_execution_requirements": [
            "restore the dedicated structured extraction credential without changing the public profile",
            "verify every snapshot, plan and freeze file hash",
            "use the formal structured ledger with concurrency 1 and automatic retries 0",
            "do not start copper until the signed Claims gate report passes",
        ],
        "prepare_script_sha256": sha256(Path(__file__)),
        "gold_file_sha256": sha256(GOLD),
    }
    save(OUT / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
