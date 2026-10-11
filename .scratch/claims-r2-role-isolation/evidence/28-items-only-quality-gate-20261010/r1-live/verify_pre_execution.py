"""Pre-execution zero-call verification for the authorized items-only live run.

Verifies, without any model call or production access: freeze-manifest byte
integrity (plans, gate, gold, contract, code inputs), the gate revision chain,
the signed v3 contract binding, the filled human authorization with the other
three authorizations still false, plan reproducibility, the runtime-style
per-packet call budget (10 / 14), and the extraction profile fingerprint.
Writes ``pre-execution-verification.json`` beside this script.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
FREEZE_DIR = HERE.parent / "r0-zero-call"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(FREEZE_DIR))

import freeze_items_only_plan as frozen  # noqa: E402
import preflight_runtime_batches as preflight  # noqa: E402

from plugins.corpus.structured.config import load_extraction_config  # noqa: E402
from plugins.corpus.structured.ledger import BatchPlan  # noqa: E402

ROOT = frozen.ROOT
FREEZE = frozen.FREEZE
REVIEW = frozen.REVIEW
STORE = HERE / "live-store"


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    manifest = read_json(FREEZE_DIR / "freeze-manifest.json")
    gate = read_json(FREEZE_DIR / "preregistered-gate.json")
    contract = read_json(REVIEW / "scoring-contract.json")
    checked: list[str] = []

    def check(condition: bool, label: str) -> None:
        if not condition:
            raise RuntimeError(f"pre-execution verification failed: {label}")
        checked.append(label)

    # A. freeze manifest byte integrity.
    check(manifest["status"] == "frozen_not_executed", "manifest_status_frozen_not_executed")
    check(manifest["model_requests_during_freeze"] == 0, "freeze_requests_zero")
    check(manifest["production_database_access"] == 0, "freeze_production_access_zero")
    check(manifest["holdout_accessed"] is False, "freeze_holdout_untouched")
    check(manifest["publication_authorized"] is False, "freeze_publication_unauthorized")
    for name, recorded in manifest["files_sha256"].items():
        check(digest(FREEZE_DIR / name) == recorded, f"manifest_file_bytes:{name}")
    input_paths = {
        "frozen-gold.json": FREEZE / "frozen-gold.json",
        "freeze-state.json": FREEZE / "freeze-state.json",
        "freeze-manifest.json": FREEZE / "freeze-manifest.json",
        "scoring-contract.json": REVIEW / "scoring-contract.json",
        "source-prose-units.json": frozen.SOURCE_EXPORT,
        "material_semantics.py": frozen.SEMANTICS,
        "ledger.py": frozen.LEDGER,
    }
    for name, path in input_paths.items():
        check(digest(path) == manifest["inputs_sha256"][name], f"manifest_input_bytes:{name}")

    # B. gate revision chain (rev1 -> rev2 -> rev3) and current hash.
    gate_hash = digest(FREEZE_DIR / "preregistered-gate.json")
    manifest_history = manifest["revision_history"]
    gate_history = gate["revision_history"]
    check(len(gate_history) == 3 and len(manifest_history) == 3, "three_revisions_recorded")
    check(
        manifest_history[0]["preregistered_gate_sha256"] == gate_history[0]["gate_sha256"],
        "revision_chain_rev1",
    )
    check(
        manifest_history[1]["preregistered_gate_sha256"] == gate_history[1]["gate_sha256"],
        "revision_chain_rev2",
    )
    check(
        gate_history[2]["previous_gate_sha256"] == gate_history[1]["gate_sha256"],
        "revision_chain_rev3_previous",
    )
    check(manifest_history[2]["preregistered_gate_sha256"] == gate_hash, "gate_hash_recorded")

    # C. gate bindings and signed contract.
    check(gate["status"] == "frozen_before_execution", "gate_status_frozen_before_execution")
    check(
        gate["gold"]["scoring_contract_sha256"] == digest(REVIEW / "scoring-contract.json"),
        "gate_binds_v3_contract",
    )
    check(
        gate["gold"]["freeze_manifest_sha256"] == digest(FREEZE / "freeze-manifest.json"),
        "gate_binds_gold_freeze_manifest",
    )
    check(
        gate["gold"]["frozen_gold_sha256"] == digest(FREEZE / "frozen-gold.json"),
        "gate_binds_frozen_gold",
    )
    check(
        gate["gold"]["freeze_state_sha256"] == digest(FREEZE / "freeze-state.json"),
        "gate_binds_freeze_state",
    )
    check(
        contract["schema_version"] == "non-table-selected-target-scoring-contract-v3",
        "contract_is_v3",
    )
    check(contract["status"] == "frozen_signed", "contract_frozen_signed")
    check(contract["signoff"]["signed_by"] == "xyl", "contract_signed_by_xyl")
    check(
        contract["supersedes"]["sha256"] == manifest_history[0]["scoring_contract_sha256"],
        "contract_v2_supersede_traceable",
    )
    check("condition_role_read_path" in contract, "contract_has_condition_read_path")
    nt_ids = sorted(key for key in contract["review_assertions"] if key.startswith("NT-I"))
    check(len(nt_ids) == 16, "contract_has_16_high_risk_assertions")
    check(
        gate["quality_requirements"]["high_risk_item_assertions_required"] == nt_ids,
        "high_risk_assertions_bound_to_contract",
    )
    check(gate["quality_requirements_status"] == "signed", "quality_requirements_signed")
    check(
        gate["quality_requirements"]["metric_basis"] == contract["schema_version"],
        "metric_basis_v3",
    )

    # D. authorization state: only items_live_extraction granted.
    authorization = gate["authorization"]
    items_auth = authorization["items_live_extraction"]
    check(items_auth["authorized"] is True, "items_authorized")
    check(items_auth["authorized_by"] == "xyl", "items_authorized_by_xyl")
    check(items_auth["authorized_on"] == "2026-10-11", "items_authorized_on_today")
    check(
        items_auth["model"] == manifest["model"] == "doubao-seed-2.1-lite",
        "authorized_model_is_doubao_lite",
    )
    check(
        items_auth["attempts_max"] == gate["execution_requirements"]["material_items_attempts_max"],
        "attempts_max_bound_to_execution_requirements",
    )
    for key in (
        "publication",
        "positive_query_delivery_context_use",
        "production_database_access",
    ):
        check(authorization[key]["authorized"] is False, f"unauthorized_still_false:{key}")
    check(gate["countersignature"]["status"] == "signed", "countersigned")
    check(gate["countersignature"]["reviewer"] == "xyl", "countersigned_by_xyl")
    for key, value in gate["scope_constraints"].items():
        check(value is False, f"scope_constraint_intact:{key}")

    # E. plan identity, reproducibility, and runtime-style call budget.
    locators = {
        item["source_id"].removeprefix("sha256:"): list(item["locators"])
        for item in contract["candidate_input_scope"]
    }
    built = {item["slug"]: item for item in frozen.scoped_sources()}
    runtime_calls: dict[str, int] = {}
    plan_summary: dict[str, dict[str, Any]] = {}
    for entry in manifest["sources"]:
        slug = entry["slug"]
        plan = BatchPlan.model_validate_json(
            (FREEZE_DIR / f"plan-{slug}.json").read_text(encoding="utf-8")
        )
        plan.verify_identity()
        check(
            plan.plan_sha256 == entry["plan_sha256"] and plan.batch_id == entry["batch_id"],
            f"plan_identity:{slug}",
        )
        check(plan.snapshot.snapshot_id == entry["snapshot_id"], f"plan_snapshot_id:{slug}")
        check(
            plan.snapshot.snapshot_id == built[slug]["snapshot"].snapshot_id,
            f"snapshot_reproducible:{slug}",
        )
        check(plan.enabled_roles == ("material_items",), f"items_only_role:{slug}")
        check(not plan.relations.enabled, f"relations_disabled:{slug}")
        check(plan.relations.max_attempts == 0, f"relations_budget_zero:{slug}")
        check(
            plan.role_max_attempts
            == {
                "claims": 0,
                "material_items": entry["material_items_attempts_max"],
                "material_relations": 0,
            },
            f"role_budget:{slug}",
        )
        check(len(plan.tasks) == 1, f"single_task:{slug}")
        task = plan.tasks[0]
        check(
            task.role == "material_items"
            and task.method == "model"
            and task.max_attempts == entry["material_items_attempts_max"],
            f"items_task:{slug}",
        )
        options = plan.material_items_options
        check(
            options is not None
            and options.max_slots_per_batch == frozen.SELECTOR_MAX_SLOTS
            and options.max_items_per_packet == frozen.SELECTOR_MAX_ITEMS
            and options.max_estimated_tokens_per_batch == frozen.SELECTOR_MAX_TOKENS,
            f"items_options:{slug}",
        )
        check(
            [unit.locator for unit in plan.snapshot.units] == locators[plan.snapshot.source_id],
            f"scope_locators:{slug}",
        )
        check(
            all(
                unit.metadata.get("gold_not_exposed_to_model") is True
                for unit in plan.snapshot.units
            ),
            f"gold_sealed:{slug}",
        )
        calls = preflight.per_packet_calls(built[slug]["snapshot"])
        check(
            calls["runtime_calls"] == entry["material_items_attempts_max"],
            f"runtime_calls_match_budget:{slug}",
        )
        runtime_calls[slug] = calls["runtime_calls"]
        plan_summary[slug] = {
            "batch_id": plan.batch_id,
            "plan_sha256": plan.plan_sha256,
            "snapshot_id": plan.snapshot.snapshot_id,
            "attempts_max": entry["material_items_attempts_max"],
            "runtime_calls": calls["runtime_calls"],
            "packets": calls["packet_count"],
            "candidate_slots": calls["slot_count"],
        }
    preflight_file = read_json(HERE / "preflight-runtime-batches.json")
    check(preflight_file["all_match"] is True, "preflight_file_all_match")
    check(
        {slug: item["runtime_calls"] for slug, item in preflight_file["sources"].items()}
        == runtime_calls,
        "preflight_file_consistent_with_rebuild",
    )
    check(items_auth["attempts_max"] == runtime_calls, "authorized_attempts_equal_runtime_calls")

    # F. extraction profile (zero call) still matches the frozen fingerprint.
    config = load_extraction_config(dotenv_path=ROOT / ".env", options=frozen.request_options())
    profile = config.require_profile()
    check(profile.fingerprint == manifest["profile_sha256"], "profile_fingerprint_matches_freeze")
    check(profile.model == manifest["model"], "profile_model_matches_freeze")
    check(
        profile.options.model_dump(mode="json") == manifest["request_options"],
        "profile_options_match_freeze",
    )
    check(config.configured is True, "extraction_provider_configured")

    # G. the live store must not exist before the authorized run.
    check(not STORE.exists(), "live_store_absent_before_run")

    summary = {
        "schema_version": "items-only-live-pre-execution-verification-1",
        "status": "verified_zero_call",
        "checked_on": "2026-10-11",
        "gate_sha256": gate_hash,
        "gate_revision": 3,
        "freeze_manifest_sha256": digest(FREEZE_DIR / "freeze-manifest.json"),
        "scoring_contract_sha256": digest(REVIEW / "scoring-contract.json"),
        "plans": plan_summary,
        "authorization": {
            "authorized_by": items_auth["authorized_by"],
            "authorized_on": items_auth["authorized_on"],
            "model": items_auth["model"],
            "attempts_total": sum(runtime_calls.values()),
        },
        "checks_passed": len(checked),
        "model_requests_during_verification": 0,
        "production_database_access": 0,
    }
    (HERE / "pre-execution-verification.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
