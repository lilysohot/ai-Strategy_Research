"""Freeze the two-arm items selector gate (v5 control vs v6 treatment) without any call.

Rebuilds the same signed snapshots issue 28 froze, re-plans the material_items role once
per arm, and writes the frozen plans, the pre-registered gate and the arm manifest. The
only intended difference between arms is the items prompt protocol plus the reasoning
switch declared in the gate; every other option, budget and snapshot stays verbatim.

No network I/O, no model request, no production database access.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E32 = HERE.parent
CLAIMS = E32.parent.parent
E28 = CLAIMS / "evidence" / "28-items-only-quality-gate-20261010"
E28_R0 = E28 / "r0-zero-call"
sys.path.insert(0, str(E28_R0))

import freeze_items_only_plan as frozen  # noqa: E402

from plugins.corpus.evidence_pipeline import evidence_document_from_snapshot  # noqa: E402
from plugins.corpus.material_semantics import (  # noqa: E402
    MATERIAL_EXTRACTOR_VERSION,
    MATERIAL_ITEMS_VALIDATION_VERSION,
    MATERIAL_SELECTOR_JSONL_V5,
    MATERIAL_SELECTOR_JSONL_V6,
    MATERIAL_SLOT_BATCHING_VERSION,
    build_candidate_slot_batches,
    build_candidate_slots,
    build_material_structure,
)
from plugins.corpus.structured.config import (  # noqa: E402
    ExtractionConfig,
    RequestOptions,
    load_extraction_config,
)
from plugins.corpus.structured.ledger import plan_batch  # noqa: E402

ROOT = frozen.ROOT
ORDER = ("industrial-fulian-md", "optical-module-docx")
ARMS = ("control", "treatment")
PACING_SECONDS = 20.0
MODEL_REQUESTS_DURING_FREEZE = 0


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def options_for(arm: str) -> RequestOptions:
    """Identical transport limits; only the reasoning switch differs between arms."""
    base: dict[str, Any] = {
        "timeout_seconds": 300.0,
        "max_output_tokens": 262144,
        "token_parameter": "max_tokens",
    }
    if arm == "control":
        # Gate §4: reproduce the closed-gate condition (provider default thinking).
        return RequestOptions(**base)
    if arm == "treatment":
        return RequestOptions(**base, thinking="disabled")
    raise ValueError(f"unknown arm: {arm}")


def protocol_for(arm: str) -> str:
    return MATERIAL_SELECTOR_JSONL_V5 if arm == "control" else MATERIAL_SELECTOR_JSONL_V6


def config_for(arm: str) -> ExtractionConfig:
    result = load_extraction_config(dotenv_path=ROOT / ".env", options=options_for(arm))
    result.require_profile()
    return result


def build_gate(
    *,
    freeze_manifest: dict[str, Any],
    arms: dict[str, Any],
) -> dict[str, Any]:
    model = arms["control"]["model"]
    if model != arms["treatment"]["model"]:
        raise ValueError("arms were frozen against different models")
    return {
        "schema_version": "items-v6-reasoning-gate-1",
        "issue": "32-items-v6-and-reasoning-refreeze-gate",
        "created_on": "2026-10-11",
        "frozen_before_execution": True,
        "supersedes_closed_route": {
            "gate": "28-items-only-quality-gate-preregistration",
            "terminal_state": "route_closed_on_fail",
            "cause": "prompt field-whitelist contradiction (L2) + reasoning enabled",
        },
        "arms": {
            arm: {
                "protocol": arms[arm]["protocol"],
                "request_options": arms[arm]["request_options"],
                "profile_sha256": arms[arm]["profile_sha256"],
            }
            for arm in ARMS
        },
        "model": model,
        "provider": arms["control"]["provider"],
        "base_url": arms["control"]["base_url"],
        "pacing": {"mode": "checkpoint_after_reserve", "seconds": PACING_SECONDS},
        "concurrency": 1,
        "automatic_retries": 0,
        "expected_attempts": {
            slug: {
                "industrial-fulian-md": 10,
                "optical-module-docx": 14,
            }[slug]
            for slug in ORDER
        },
        "exit_criteria": {
            "attempts_match_plan": True,
            "no_http_429": True,
            "no_automatic_retries": True,
            "protocol_status": "valid",
            "failed_partial_invalid_duplicate_batches_max": 0,
            "completed_min": {"industrial-fulian-md": 10, "optical-module-docx": 14},
            "execution_status": "succeeded",
            "context_status": "complete",
            "reasoning_tokens_must_be_zero_or_absent": True,
            "control_arm_must_reproduce_failure": True,
        },
        "scope": {
            "claims_attempts": 0,
            "material_relations_attempts": 0,
            "new_gold_allowed": False,
            "threshold_relaxation_after_execution_allowed": False,
            "prompt_revision_after_execution_allowed": False,
            "publication_authorized": False,
            "holdout_accessed": False,
            "quality_scoring_in_this_gate": False,
            "response_format_enabled": False,
        },
        "authorization": {
            "items_live_extraction": {
                "authorized": True,
                "authorized_by": "xyl",
                "authorized_on": "2026-10-11",
                "model": model,
                "attempts_max": {"industrial-fulian-md": 10, "optical-module-docx": 14},
                "pacing_seconds": PACING_SECONDS,
                "basis": (
                    "issue-32 §10 named countersignature (xyl, 准予执行) plus the explicit "
                    "user instruction '已经签认，可执行' on 2026-10-11; the §7 table was left "
                    "blank, so every parameter is taken verbatim from §4/§5 and the .env "
                    "profile instead of being chosen by the implementer."
                ),
            },
            "publication": {"authorized": False},
            "positive_query_delivery_context_use": {"authorized": False},
            "production_database_access": {"authorized": False},
        },
        "countersignature": {
            "status": "signed",
            "reviewer": "xyl",
            "signed_on": "2026-10-11",
            "note": "issue-32 §10; §7 authorization table left blank (recorded, not filled in)",
        },
        "frozen_inputs": freeze_manifest["inputs"],
        "model_requests_during_freeze": MODEL_REQUESTS_DURING_FREEZE,
    }


def main() -> None:
    reference = read_json(E28_R0 / "freeze-manifest.json")
    baseline = {entry["slug"]: entry for entry in reference["sources"]}

    arms: dict[str, Any] = {}
    plans: dict[tuple[str, str], Any] = {}
    for arm in ARMS:
        config = config_for(arm)
        profile = config.require_profile()
        protocol = protocol_for(arm)
        entries: list[dict[str, Any]] = []
        for item in frozen.scoped_sources():
            slug = item["slug"]
            snapshot = item["snapshot"]
            snapshot.verify_identity()
            expected = baseline[slug]
            if snapshot.snapshot_id != expected["snapshot_id"]:
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
            attempts = len(batches)
            if attempts != expected["material_items_attempts_max"]:
                raise RuntimeError(f"attempt budget drifted: {slug}: {attempts}")
            if len(candidate_slots) != expected["candidate_slot_count"]:
                raise RuntimeError(f"candidate slot count drifted: {slug}")
            plan = plan_batch(
                snapshot,
                config=config,
                max_attempts=attempts,
                role_max_attempts={"claims": 0, "material_items": attempts, "material_relations": 0},
                relations_enabled=False,
                enabled_roles=("material_items",),
                max_items_per_packet=frozen.SELECTOR_MAX_ITEMS,
                max_slots_per_batch=frozen.SELECTOR_MAX_SLOTS,
                max_estimated_tokens_per_batch=frozen.SELECTOR_MAX_TOKENS,
                material_items_protocol=protocol,
            )
            plan.verify_identity()
            counts = {
                role: sum(task.role == role for task in plan.tasks)
                for role in ("claims", "material_items", "material_relations")
            }
            if counts != {"claims": 0, "material_items": 1, "material_relations": 0}:
                raise RuntimeError(f"unexpected task plan: {slug}: {counts}")
            item_task = next(task for task in plan.tasks if task.role == "material_items")
            if item_task.protocol != protocol:
                raise RuntimeError(f"task protocol drifted: {slug}")
            if plan.relations.enabled:
                raise RuntimeError(f"relations must stay disabled: {slug}")
            plans[(arm, slug)] = plan
            entries.append(
                {
                    "slug": slug,
                    "batch_id": plan.batch_id,
                    "plan_sha256": plan.plan_sha256,
                    "snapshot_id": plan.snapshot.snapshot_id,
                    "source_id": plan.snapshot.source_id,
                    "protocol": item_task.protocol,
                    "candidate_slot_count": len(candidate_slots),
                    "packet_count": len(document.packets),
                    "expected_attempts": attempts,
                    "baseline_attempts": expected["material_items_attempts_max"],
                }
            )
        arms[arm] = {
            "protocol": protocol,
            "model": profile.model,
            "provider": profile.provider,
            "base_url": profile.base_url,
            "profile_sha256": profile.fingerprint,
            "request_options": profile.options.model_dump(mode="json"),
            "sources": entries,
        }

    for (arm, slug), plan in plans.items():
        frozen.atomic_write(HERE / f"plan-{arm}-{slug}.json", plan.model_dump_json(indent=2))

    inputs = {
        "issue28_freeze_manifest": digest(E28_R0 / "freeze-manifest.json"),
        "issue28_preregistered_gate": digest(E28_R0 / "preregistered-gate.json"),
        "material_semantics_module": digest(ROOT / "plugins" / "corpus" / "material_semantics.py"),
        "structured_config_module": digest(
            ROOT / "plugins" / "corpus" / "structured" / "config.py"
        ),
        "structured_adapter_module": digest(
            ROOT / "plugins" / "corpus" / "structured" / "adapter.py"
        ),
        "source_prose_units": digest(
            E28.parent
            / "10-quality-gold-expansion-20261008-r1"
            / "source-prose-units.json"
        ),
        "scoring_contract": digest(
            E28.parent / "10-quality-gold-expansion-20261008-r2" / "scoring-contract.json"
        ),
    }
    freeze_manifest = {
        "schema_version": "items-v6-reasoning-freeze-manifest-1",
        "created_on": "2026-10-11",
        "issue": "32-items-v6-and-reasoning-refreeze-gate",
        "extractor_version": MATERIAL_EXTRACTOR_VERSION,
        "items_validation_version": MATERIAL_ITEMS_VALIDATION_VERSION,
        "slot_batching_version": MATERIAL_SLOT_BATCHING_VERSION,
        "protocols": {"control": MATERIAL_SELECTOR_JSONL_V5, "treatment": MATERIAL_SELECTOR_JSONL_V6},
        "selector_options_kept_verbatim": {
            "max_slots_per_batch": frozen.SELECTOR_MAX_SLOTS,
            "max_items_per_packet": frozen.SELECTOR_MAX_ITEMS,
            "max_estimated_tokens_per_batch": frozen.SELECTOR_MAX_TOKENS,
        },
        "arms": arms,
        "pacing": {"mode": "checkpoint_after_reserve", "seconds": PACING_SECONDS},
        "inputs": inputs,
        "files_sha256": {
            f"plan-{arm}-{slug}.json": digest(HERE / f"plan-{arm}-{slug}.json")
            for (arm, slug) in plans
        },
        "model_requests_during_freeze": MODEL_REQUESTS_DURING_FREEZE,
        "production_database_access": 0,
        "holdout_accessed": False,
    }
    frozen.atomic_write(
        HERE / "freeze-manifest.json", json.dumps(freeze_manifest, ensure_ascii=False, indent=2)
    )
    gate = build_gate(freeze_manifest=freeze_manifest, arms=arms)
    frozen.atomic_write(
        HERE / "preregistered-gate.json", json.dumps(gate, ensure_ascii=False, indent=2)
    )
    print(
        json.dumps(
            {
                "arms": {
                    arm: {
                        "protocol": arms[arm]["protocol"],
                        "profile_sha256": arms[arm]["profile_sha256"],
                        "request_options": arms[arm]["request_options"],
                        "expected_attempts": {
                            entry["slug"]: entry["expected_attempts"]
                            for entry in arms[arm]["sources"]
                        },
                    }
                    for arm in ARMS
                },
                "gate_sha256": digest(HERE / "preregistered-gate.json"),
                "freeze_manifest_sha256": digest(HERE / "freeze-manifest.json"),
                "model_requests": MODEL_REQUESTS_DURING_FREEZE,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
