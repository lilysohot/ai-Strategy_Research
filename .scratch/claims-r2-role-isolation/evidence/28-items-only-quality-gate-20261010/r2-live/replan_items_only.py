"""Re-freeze the items-only plans for the user-directed model substitution.

Zero-call: rebuilds the same signed snapshots and re-plans the material_items
role under the new extraction profile (deepseek-v4-flash), keeping every frozen
option, protocol, and budget verbatim. Writes r2 plan files and
replan-manifest.json; no model request, no production access.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
R0 = HERE.parent / "r0-zero-call"
R1 = HERE.parent / "r1-live"
sys.path.insert(0, str(R0))

import freeze_items_only_plan as frozen  # noqa: E402

from plugins.corpus.evidence_pipeline import evidence_document_from_snapshot  # noqa: E402
from plugins.corpus.material_semantics import (  # noqa: E402
    build_candidate_slot_batches,
    build_candidate_slots,
    build_material_structure,
)
from plugins.corpus.structured.ledger import plan_batch  # noqa: E402

ALL_ROLES = ("claims", "material_items", "material_relations")


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write(path: Path, content: str) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".pending", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary)


def main() -> None:
    manifest = read_json(R0 / "freeze-manifest.json")
    gate = read_json(R0 / "preregistered-gate.json")
    auth = gate["authorization"]["items_live_extraction"]
    if not auth["authorized"] or auth["authorized_by"] != "xyl":
        raise RuntimeError("items live extraction is not authorized")
    if auth["model"] != "deepseek-v4-flash":
        raise RuntimeError("gate does not authorize the substituted model")

    extraction = frozen.config()
    profile = extraction.require_profile()
    if profile.model != "deepseek-v4-flash":
        raise RuntimeError("extraction profile does not match the substituted model")

    plans = {}
    entries = []
    total = 0
    for item in frozen.scoped_sources():
        slug = item["slug"]
        snapshot = item["snapshot"]
        snapshot.verify_identity()
        r0_entry = next(e for e in manifest["sources"] if e["slug"] == slug)
        if snapshot.snapshot_id != r0_entry["snapshot_id"]:
            raise RuntimeError(f"snapshot drifted: {slug}")
        document = evidence_document_from_snapshot(snapshot, role="material_items")
        candidate_slots = build_candidate_slots(
            document, build_material_structure(document)
        )
        batches = build_candidate_slot_batches(
            candidate_slots,
            max_slots_per_batch=frozen.SELECTOR_MAX_SLOTS,
            max_items_per_batch=frozen.SELECTOR_MAX_ITEMS,
            max_estimated_tokens_per_batch=frozen.SELECTOR_MAX_TOKENS,
        )
        n = len(batches)
        if n != r0_entry["material_items_attempts_max"]:
            raise RuntimeError(f"attempt budget drifted: {slug}: {n}")
        if len(candidate_slots) != r0_entry["candidate_slot_count"]:
            raise RuntimeError(f"candidate slot count drifted: {slug}")
        plan = plan_batch(
            snapshot,
            config=extraction,
            max_attempts=n,
            role_max_attempts={"claims": 0, "material_items": n, "material_relations": 0},
            relations_enabled=False,
            enabled_roles=("material_items",),
            max_items_per_packet=frozen.SELECTOR_MAX_ITEMS,
            max_slots_per_batch=frozen.SELECTOR_MAX_SLOTS,
            max_estimated_tokens_per_batch=frozen.SELECTOR_MAX_TOKENS,
            material_items_protocol=frozen.ITEMS_PROTOCOL,
        )
        plan.verify_identity()
        counts = {
            role: sum(task.role == role for task in plan.tasks) for role in ALL_ROLES
        }
        if counts != {"claims": 0, "material_items": 1, "material_relations": 0}:
            raise RuntimeError(f"unexpected task plan: {slug}: {counts}")
        if plan.relations.enabled or plan.role_max_attempts["material_items"] != n:
            raise RuntimeError(f"relations/budget drifted: {slug}")
        plans[slug] = plan
        total += n
        entries.append(
            {
                "slug": slug,
                "batch_id": plan.batch_id,
                "plan_sha256": plan.plan_sha256,
                "snapshot_id": plan.snapshot.snapshot_id,
                "source_id": plan.snapshot.source_id,
                "candidate_slot_count": len(candidate_slots),
                "packet_count": len(document.packets),
                "material_items_attempts_max": n,
            }
        )

    for slug, plan in plans.items():
        atomic_write(HERE / f"plan-{slug}.json", plan.model_dump_json(indent=2))

    replan = {
        "schema_version": "items-only-replan-manifest-1",
        "created_on": "2026-10-11",
        "issue": "28-items-only-quality-gate-preregistration",
        "purpose": "user-directed model substitution after the run-1 infrastructure invalidation (HTTP 429 burst protection)",
        "supersedes_execution_model": "doubao-seed-2.1-lite",
        "model": profile.model,
        "provider": profile.provider,
        "base_url": profile.base_url,
        "profile_sha256": profile.fingerprint,
        "request_options": profile.options.model_dump(mode="json"),
        "protocol": frozen.ITEMS_PROTOCOL,
        "items_options_kept_verbatim": {
            "max_slots_per_batch": frozen.SELECTOR_MAX_SLOTS,
            "max_items_per_packet": frozen.SELECTOR_MAX_ITEMS,
            "max_estimated_tokens_per_batch": frozen.SELECTOR_MAX_TOKENS,
        },
        "gate_sha256": digest(R0 / "preregistered-gate.json"),
        "gate_revision": 4,
        "r0_freeze_manifest_sha256": digest(R0 / "freeze-manifest.json"),
        "r1_run": {
            "summary_sha256": digest(R1 / "live-run-summary.json"),
            "store_preserved": (R1 / "live-store").exists(),
            "status": "invalidated_http_429_burst_protection",
            "attempts": 24,
            "rejected_429": 16,
        },
        "sources": entries,
        "attempts_total": total,
        "files_sha256": {
            f"plan-{slug}.json": digest(HERE / f"plan-{slug}.json") for slug in plans
        },
        "pacing": {"mode": "checkpoint_after_reserve", "seconds": 20},
        "model_requests_during_replan": 0,
        "production_database_access": 0,
        "holdout_accessed": False,
        "publication_authorized": False,
    }
    atomic_write(
        HERE / "replan-manifest.json", json.dumps(replan, ensure_ascii=False, indent=2)
    )
    print(
        json.dumps(
            {
                "model": profile.model,
                "profile_sha256": profile.fingerprint,
                "sources": entries,
                "attempts_total": total,
                "gate_revision": 4,
                "model_requests": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
