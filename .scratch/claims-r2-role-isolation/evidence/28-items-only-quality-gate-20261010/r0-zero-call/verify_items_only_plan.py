"""Re-verify the frozen items-only plan and gate without any model call.

Checks byte-level file hashes, plan identity, role scope, frozen-scope locators,
and deterministic reproducibility of the snapshot ids and batch budgets. Performs
no network I/O and no model request.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from plugins.corpus.evidence_pipeline import evidence_document_from_snapshot
from plugins.corpus.material_semantics import (
    build_candidate_slot_batches,
    build_candidate_slots,
    build_material_structure,
)
from plugins.corpus.structured.ledger import BatchPlan

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import freeze_items_only_plan as frozen  # noqa: E402

ALL_ROLES = ("claims", "material_items", "material_relations")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(path: Path) -> str:
    return "sha256:" + file_sha256(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def contract_locators() -> dict[str, list[str]]:
    contract = read_json(frozen.REVIEW / "scoring-contract.json")
    return {
        item["source_id"].removeprefix("sha256:"): list(item["locators"])
        for item in contract["candidate_input_scope"]
    }


def rebuild_batches(snapshot: Any) -> int:
    material_document = evidence_document_from_snapshot(snapshot, role="material_items")
    candidate_slots = build_candidate_slots(
        material_document, build_material_structure(material_document)
    )
    batches = build_candidate_slot_batches(
        candidate_slots,
        max_slots_per_batch=frozen.SELECTOR_MAX_SLOTS,
        max_items_per_batch=frozen.SELECTOR_MAX_ITEMS,
        max_estimated_tokens_per_batch=frozen.SELECTOR_MAX_TOKENS,
    )
    return len(batches)


def main() -> None:
    manifest = read_json(HERE / "freeze-manifest.json")
    gate = read_json(HERE / "preregistered-gate.json")

    if manifest["status"] != "frozen_not_executed":
        raise RuntimeError("manifest status drifted")
    if manifest["model_requests_during_freeze"] != 0:
        raise RuntimeError("freeze recorded model requests")
    for name, recorded in manifest["files_sha256"].items():
        if digest(HERE / name) != recorded:
            raise RuntimeError(f"frozen bytes drifted: {name}")

    # Deterministic zero-call reconstruction of the signed snapshots.
    rebuilt = frozen.scoped_sources()
    by_slug = {item["slug"]: item for item in rebuilt}
    locators = contract_locators()

    plans: dict[str, BatchPlan] = {}
    entries: dict[str, dict[str, Any]] = {}
    for entry in manifest["sources"]:
        slug = entry["slug"]
        plan = BatchPlan.model_validate_json((HERE / f"plan-{slug}.json").read_text("utf-8"))
        plan.verify_identity()
        if plan.plan_sha256 != entry["plan_sha256"] or plan.batch_id != entry["batch_id"]:
            raise RuntimeError(f"plan identity mismatch: {slug}")
        if plan.snapshot.snapshot_id != by_slug[slug]["snapshot"].snapshot_id:
            raise RuntimeError(f"snapshot not reproducible: {slug}")
        if plan.enabled_roles != ("material_items",):
            raise RuntimeError(f"role scope drifted: {slug}")
        if plan.relations.enabled:
            raise RuntimeError(f"relations enabled: {slug}")
        if plan.role_max_attempts != {
            "claims": 0,
            "material_items": entry["material_items_attempts_max"],
            "material_relations": 0,
        }:
            raise RuntimeError(f"role budget drifted: {slug}")
        counts = {role: sum(task.role == role for task in plan.tasks) for role in ALL_ROLES}
        if counts != {"claims": 0, "material_items": 1, "material_relations": 0}:
            raise RuntimeError(f"task plan drifted: {slug}: {counts}")
        if plan.material_items_options is None:
            raise RuntimeError(f"missing items options: {slug}")
        if (
            plan.material_items_options.max_slots_per_batch != frozen.SELECTOR_MAX_SLOTS
            or plan.material_items_options.max_items_per_packet != frozen.SELECTOR_MAX_ITEMS
            or plan.material_items_options.max_estimated_tokens_per_batch
            != frozen.SELECTOR_MAX_TOKENS
        ):
            raise RuntimeError(f"items options drifted: {slug}")
        if any(unit.metadata.get("gold_not_exposed_to_model") is not True for unit in plan.snapshot.units):
            raise RuntimeError(f"gold leakage metadata missing: {slug}")
        if [unit.locator for unit in plan.snapshot.units] != locators[plan.snapshot.source_id]:
            raise RuntimeError(f"scope locators drifted: {slug}")
        n = rebuild_batches(by_slug[slug]["snapshot"])
        if n != entry["material_items_attempts_max"]:
            raise RuntimeError(f"attempt budget not reproducible: {slug}: {n}")
        if n != plan.role_max_attempts["material_items"]:
            raise RuntimeError(f"attempt budget inconsistent with plan: {slug}")
        plans[slug] = plan
        entries[slug] = entry

    gold = gate["gold"]
    if gold["gold_counts"] != {"claims": 20, "material_items": 48, "material_relations": 24}:
        raise RuntimeError("gold counts drifted")
    if gold["material_items_target_total"] != 48:
        raise RuntimeError("items target total drifted")
    if gold["freeze_manifest_sha256"] != digest(frozen.FREEZE / "freeze-manifest.json"):
        raise RuntimeError("gold freeze manifest drifted")

    scope = gate["scope_constraints"]
    if any(value for key, value in scope.items() if key.endswith("_allowed") or key.startswith("holdout") or key.endswith("_authorized")):
        raise RuntimeError("scope constraint unexpectedly granted")
    if any(item["authorized"] for item in gate["authorization"].values() if isinstance(item, dict)):
        raise RuntimeError("authorization unexpectedly granted")
    if gate["countersignature"]["status"] != "pending_human_signoff":
        raise RuntimeError("gate unexpectedly countersigned")
    if gate["status"] != "frozen_before_execution":
        raise RuntimeError("gate status drifted")

    summary = {
        "schema_version": "items-only-quality-gate-verification-1",
        "status": "verified_zero_call",
        "issue": "28-items-only-quality-gate-preregistration",
        "protocol": gate["protocol"]["material_items"],
        "model": manifest["model"],
        "sources": [
            {
                "slug": slug,
                "batch_id": plan.batch_id,
                "snapshot_id": plan.snapshot.snapshot_id,
                "source_id": plan.snapshot.source_id,
                "unit_count": len(plan.snapshot.units),
                "material_items_attempts_max": plan.role_max_attempts["material_items"],
                "reproducible": True,
            }
            for slug, plan in plans.items()
        ],
        "gate_status": gate["status"],
        "quality_requirements_status": gate["quality_requirements_status"],
        "countersignature_status": gate["countersignature"]["status"],
        "authorization_all_false": True,
        "publication_authorized": False,
        "query_delivery_context_use_authorized": False,
        "model_requests_during_verification": 0,
        "production_database_access": 0,
    }
    (HERE / "verification-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
