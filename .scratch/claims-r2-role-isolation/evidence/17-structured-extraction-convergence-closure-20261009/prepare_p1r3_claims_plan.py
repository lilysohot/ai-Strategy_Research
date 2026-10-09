"""Freeze P1R3 as offline rebinding plus the two newly routed optical units."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from plugins.corpus.claims_binding import CLAIMS_SLOT_PROTOCOL_VERSION
from plugins.corpus.claims_detail import (
    EXTRACTOR_VERSION_V2,
    LINT_VERSION,
    PERIOD_RULE_VERSION,
    UNIT_RULE_VERSION,
)
from plugins.corpus.evidence_pipeline import CLAIMS_ATOMIC_PROTOCOL, PIPELINE_VERSION
from plugins.corpus.structured.config import RequestOptions, load_extraction_config
from plugins.corpus.structured.ledger import BatchPlan, ReplayResponse, Role, plan_batch
from plugins.corpus.structured.roles import ROUTING_RULE_VERSION
from plugins.corpus.structured.snapshot import (
    EvidenceSnapshot,
    SnapshotBuildSource,
    SnapshotDocumentSource,
    SnapshotHead,
    SnapshotReader,
    SnapshotUnitSource,
    build_snapshot,
    source_unit_id,
)

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
SOURCE = HERE / "p1r2-claims-plan-freeze"
OUT = HERE / "p1r3-claims-plan-freeze"
RUNS = ("claims-industrial-fulian", "claims-optical-module")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def payload_store(name: str) -> Path:
    leaf = "replay-store" if name == RUNS[0] else "live-store"
    return SOURCE / name / leaf


def freeze_replay(name: str, plan: BatchPlan, target: Path) -> int:
    task = next(task for task in plan.tasks if task.role == "claims")
    store = payload_store(name)
    connection = sqlite3.connect(store / "index/structured.sqlite3")
    connection.row_factory = sqlite3.Row
    try:
        attempts = connection.execute(
            "SELECT * FROM attempts ORDER BY attempt_number"
        ).fetchall()
    finally:
        connection.close()
    for attempt in attempts:
        digest = str(attempt["response_object_sha256"]).removeprefix("sha256:")
        response_path = store / "objects/sha256" / digest[:2] / f"{digest}.json"
        response = json.loads(response_path.read_text(encoding="utf-8"))
        replay = ReplayResponse(
            task_id=task.task_id,
            sequence=int(attempt["attempt_number"]),
            role="claims",
            protocol=task.protocol,
            content=response["content"],
            diagnostics={
                "source": "p1r2_immutable_response_object",
                "source_response_object_sha256": attempt["response_object_sha256"],
                "execution_status": "succeeded",
                "provider": "replay",
                "model": "p1r2-response-replay",
            },
        )
        save(target / f"{replay.sequence:02d}.json", replay.model_dump(mode="json"))
    return len(attempts)


@dataclass
class DeltaReader(SnapshotReader):
    payload: SnapshotBuildSource

    def read_head(self, source_id: str) -> SnapshotHead:
        if source_id != self.payload.head.source_id:
            raise ValueError("delta source mismatch")
        return self.payload.head

    def read_build(self, head: SnapshotHead) -> SnapshotBuildSource:
        if head != self.payload.head:
            raise ValueError("delta head mismatch")
        return self.payload


def delta_snapshot(full: EvidenceSnapshot, old_plan: BatchPlan) -> EvidenceSnapshot:
    old_task = next(task for task in old_plan.tasks if task.role == "claims")
    old_scope = set(old_task.scoped_unit_ids)
    new_config = load_extraction_config(
        dotenv_path=REPO / ".env", options=RequestOptions(max_output_tokens=16_384)
    )
    full_new_plan = make_plan(full, new_config, max_attempts=len(full.units))
    new_task = next(task for task in full_new_plan.tasks if task.role == "claims")
    added = [unit for unit in full.units if unit.unit_id in set(new_task.scoped_unit_ids) - old_scope]
    if [unit.locator for unit in added] != ["body[3]", "body[51]"]:
        raise ValueError(f"unexpected routing delta: {[unit.locator for unit in added]}")
    document = cast(dict[str, object], added[0].metadata["document"])
    units = tuple(
        SnapshotUnitSource(
            source_unit_id=source_unit_id(unit),
            chunk_id=unit.chunk_id,
            kind=unit.kind,
            text=unit.text,
            locator=unit.locator,
            page=cast(int | None, unit.metadata.get("page")),
            element=cast(str | None, unit.metadata.get("element")),
            label_path=tuple(cast(list[str], unit.metadata.get("label_path") or [])),
            parent_id=cast(str | None, unit.metadata.get("parent_id")),
            ordinal=cast(int | None, unit.metadata.get("ordinal")),
            status=str(unit.metadata.get("status") or "kept"),
            reasons=tuple(cast(list[str], unit.metadata.get("reasons") or [])),
            metadata={"gold_not_exposed_to_model": True, "delta_from_snapshot": full.snapshot_id},
        )
        for unit in added
    )
    payload = SnapshotBuildSource(
        head=SnapshotHead(
            source_id=full.source_id,
            build_id=full.build_id,
            publication_generation=full.publication_generation,
        ),
        parser_versions={k: v for k, v in full.parser_versions.items() if k != "snapshot"},
        document=SnapshotDocumentSource(
            title=str(document["title"]),
            subject=cast(str | None, document.get("subject")),
            published=cast(str | None, document.get("published")),
        ),
        units=units,
    )
    return build_snapshot(DeltaReader(payload), full.source_id)


def make_plan(snapshot: EvidenceSnapshot, config: Any, *, max_attempts: int) -> BatchPlan:
    budgets: dict[Role, int] = {
        "claims": max_attempts,
        "material_items": 0,
        "material_relations": 0,
    }
    return plan_batch(
        snapshot,
        config=config,
        max_attempts=max_attempts,
        role_max_attempts=budgets,
        relations_enabled=False,
        max_relation_tasks=0,
        max_relation_attempts=0,
        enabled_roles=("claims",),
    )


def main() -> None:
    if OUT.exists():
        raise SystemExit("refusing to overwrite the P1R3 plan freeze")
    config = load_extraction_config(
        dotenv_path=REPO / ".env", options=RequestOptions(max_output_tokens=16_384)
    )
    profile = config.require_profile()
    OUT.mkdir(parents=True)
    entries: list[dict[str, object]] = []
    old_plans: dict[str, BatchPlan] = {}
    for name in RUNS:
        source = SOURCE / name
        snapshot = EvidenceSnapshot.model_validate_json(
            (source / "snapshot.json").read_text(encoding="utf-8")
        )
        plan = BatchPlan.model_validate_json((source / "plan.json").read_text(encoding="utf-8"))
        snapshot.verify_identity()
        plan.verify_identity()
        old_plans[name] = plan
        target = OUT / f"replay-{name}"
        save(target / "snapshot.json", snapshot.model_dump(mode="json"))
        save(target / "plan.json", plan.model_dump(mode="json"))
        attempts = freeze_replay(name, plan, target / "responses")
        entries.append(
            {
                "name": f"replay-{name}",
                "mode": "offline_replay",
                "batch_id": plan.batch_id,
                "plan_sha256": plan.plan_sha256,
                "attempts": attempts,
                "new_model_calls": 0,
                "snapshot_file_sha256": sha256(target / "snapshot.json"),
                "plan_file_sha256": sha256(target / "plan.json"),
            }
        )

    optical_full = EvidenceSnapshot.model_validate_json(
        (SOURCE / RUNS[1] / "snapshot.json").read_text(encoding="utf-8")
    )
    delta = delta_snapshot(optical_full, old_plans[RUNS[1]])
    delta_plan = make_plan(delta, config, max_attempts=2)
    delta_task = next(task for task in delta_plan.tasks if task.role == "claims")
    if len(delta_task.scoped_unit_ids) != 2 or delta_task.protocol != CLAIMS_ATOMIC_PROTOCOL:
        raise ValueError("delta Claims plan does not contain exactly two atomic prose units")
    target = OUT / "live-claims-optical-routing-delta"
    save(target / "snapshot.json", delta.model_dump(mode="json"))
    save(target / "plan.json", delta_plan.model_dump(mode="json"))
    entries.append(
        {
            "name": "live-claims-optical-routing-delta",
            "mode": "live_model",
            "batch_id": delta_plan.batch_id,
            "plan_sha256": delta_plan.plan_sha256,
            "attempt_ceiling": 2,
            "new_model_calls": 2,
            "locators": [unit.locator for unit in delta.units],
            "snapshot_file_sha256": sha256(target / "snapshot.json"),
            "plan_file_sha256": sha256(target / "plan.json"),
        }
    )
    manifest = {
        "schema_version": "structured-extraction-p1r3-claims-plan-freeze-1",
        "status": "frozen_not_executed",
        "frozen_on": "2026-10-09",
        "purpose": "recompute deterministic Claims bindings and cover the two v1 routing misses",
        "execution_order": [entry["name"] for entry in entries] + ["claims_gate_evaluation"],
        "stop_policy": "Any replay or delta protocol failure blocks the Claims gate and copper.",
        "maximum_new_model_calls": 2,
        "automatic_retries": 0,
        "production_database_access": 0,
        "publication_writes": 0,
        "gold_not_exposed_to_model": True,
        "versions": {
            "claims_protocol": CLAIMS_ATOMIC_PROTOCOL,
            "slot_protocol": CLAIMS_SLOT_PROTOCOL_VERSION,
            "routing": ROUTING_RULE_VERSION,
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
        "p1r2_execution_sha256": sha256(SOURCE / "execution-summary.json"),
        "prepare_script_sha256": sha256(Path(__file__)),
    }
    save(OUT / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
