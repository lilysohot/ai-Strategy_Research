"""Pre-execution zero-call verification for the model-substituted items-only run.

Checks: r0 freeze bytes intact; the four-step gate revision chain; gate
revision 4 authorization (deepseek-v4-flash, all other authorizations still
false, thresholds untouched); r2 plan identity/budgets and snapshot reuse;
runtime per-packet call counts (10 / 14); the new extraction profile; run-1
evidence preserved; r2 store absent. No model call, no production access.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
R0 = HERE.parent / "r0-zero-call"
R1 = HERE.parent / "r1-live"
sys.path.insert(0, str(R0))
sys.path.insert(0, str(R1))

import freeze_items_only_plan as frozen  # noqa: E402
import preflight_runtime_batches as preflight  # noqa: E402

from plugins.corpus.structured.adapter import validate_endpoint  # noqa: E402
from plugins.corpus.structured.config import load_extraction_config  # noqa: E402
from plugins.corpus.structured.ledger import BatchPlan  # noqa: E402

ROOT = frozen.ROOT
FREEZE = frozen.FREEZE
REVIEW = frozen.REVIEW
STORE = HERE / "live-store"
EXPECTED_ATTEMPTS = {"industrial-fulian-md": 10, "optical-module-docx": 14}


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    manifest = read_json(R0 / "freeze-manifest.json")
    gate = read_json(R0 / "preregistered-gate.json")
    contract = read_json(REVIEW / "scoring-contract.json")
    replan = read_json(HERE / "replan-manifest.json")
    checked: list[str] = []

    def check(condition: bool, label: str) -> None:
        if not condition:
            raise RuntimeError(f"r2 pre-execution verification failed: {label}")
        checked.append(label)

    # A. r0 freeze bytes and the four-step revision chain.
    for name, recorded in manifest["files_sha256"].items():
        check(digest(R0 / name) == recorded, f"r0_file_bytes:{name}")
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
        check(digest(path) == manifest["inputs_sha256"][name], f"r0_input_bytes:{name}")
    manifest_history = manifest["revision_history"]
    gate_history = gate["revision_history"]
    check(len(gate_history) == 4 and len(manifest_history) == 4, "four_revisions_recorded")
    # rev1 hash A and rev2 hash B are recorded in both documents; the rev3
    # produced-hash C is recorded in gate rev4.previous and manifest rev3;
    # the rev4 produced-hash D is the current gate bytes.
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
    check(
        manifest_history[2]["preregistered_gate_sha256"]
        == gate_history[3]["previous_gate_sha256"],
        "revision_chain_rev3",
    )
    check(
        manifest_history[3]["preregistered_gate_sha256"]
        == digest(R0 / "preregistered-gate.json"),
        "rev4_gate_hash_recorded",
    )

    # B. gate rev4 authorization state and untouched thresholds.
    check(gate["status"] == "frozen_before_execution", "gate_status_unchanged")
    auth = gate["authorization"]["items_live_extraction"]
    check(auth["authorized"] is True and auth["authorized_by"] == "xyl", "items_authorized_by_xyl")
    check(auth["authorized_on"] == "2026-10-11", "authorization_date")
    check(auth["model"] == "deepseek-v4-flash", "authorized_model_is_deepseek_v4_flash")
    check(
        auth["attempts_max"] == gate["execution_requirements"]["material_items_attempts_max"]
        == EXPECTED_ATTEMPTS,
        "attempts_max_unchanged",
    )
    for key in ("publication", "positive_query_delivery_context_use", "production_database_access"):
        check(gate["authorization"][key]["authorized"] is False, f"unauthorized_still_false:{key}")
    check(gate["countersignature"]["status"] == "signed", "countersigned")
    for key, value in gate["scope_constraints"].items():
        check(value is False, f"scope_constraint_intact:{key}")
    quality = gate["quality_requirements"]
    check(
        quality["target_recall_overall_min"] == 0.85
        and quality["target_recall_per_source_min"] == 0.8
        and quality["candidate_precision_min"] == 0.8
        and quality["unresolved_candidates_max"] == 0
        and quality["accepted_records_total_min"] == 40
        and quality["accepted_records_per_source_min"] == 20,
        "thresholds_unchanged",
    )
    check(quality["metric_basis"] == "non-table-selected-target-scoring-contract-v3", "metric_v3")
    nt_ids = sorted(key for key in contract["review_assertions"] if key.startswith("NT-I"))
    check(quality["high_risk_item_assertions_required"] == nt_ids, "high_risk_16_bound")
    check(
        gate["gold"]["scoring_contract_sha256"] == digest(REVIEW / "scoring-contract.json"),
        "gold_bindings_unchanged",
    )
    check(
        gate["protocol"]["material_items"] == frozen.ITEMS_PROTOCOL
        and gate["protocol"]["extractor_version"] == "material-semantics-32",
        "protocol_unchanged",
    )
    check(replan["gate_sha256"] == digest(R0 / "preregistered-gate.json"), "replan_binds_rev4")

    # C. r2 plans: identity, budgets, snapshot reuse, runtime call counts.
    locators = {
        item["source_id"].removeprefix("sha256:"): list(item["locators"])
        for item in contract["candidate_input_scope"]
    }
    built = {item["slug"]: item for item in frozen.scoped_sources()}
    r0_by_slug = {entry["slug"]: entry for entry in manifest["sources"]}
    runtime_calls: dict[str, int] = {}
    plan_summary: dict[str, dict[str, Any]] = {}
    for entry in replan["sources"]:
        slug = entry["slug"]
        plan = BatchPlan.model_validate_json(
            (HERE / f"plan-{slug}.json").read_text(encoding="utf-8")
        )
        plan.verify_identity()
        check(
            plan.plan_sha256 == entry["plan_sha256"] and plan.batch_id == entry["batch_id"],
            f"r2_plan_identity:{slug}",
        )
        check(
            digest(HERE / f"plan-{slug}.json") == replan["files_sha256"][f"plan-{slug}.json"],
            f"r2_plan_bytes:{slug}",
        )
        check(
            plan.snapshot.snapshot_id == entry["snapshot_id"]
            == r0_by_slug[slug]["snapshot_id"],
            f"snapshot_reused:{slug}",
        )
        check(
            plan.snapshot.snapshot_id == built[slug]["snapshot"].snapshot_id,
            f"snapshot_reproducible:{slug}",
        )
        check(plan.enabled_roles == ("material_items",), f"items_only_role:{slug}")
        check(not plan.relations.enabled and plan.relations.max_attempts == 0, f"relations_off:{slug}")
        check(
            plan.role_max_attempts
            == {"claims": 0, "material_items": EXPECTED_ATTEMPTS[slug], "material_relations": 0},
            f"role_budget:{slug}",
        )
        check(len(plan.tasks) == 1 and plan.tasks[0].role == "material_items", f"single_items_task:{slug}")
        check(plan.tasks[0].max_attempts == EXPECTED_ATTEMPTS[slug], f"task_budget:{slug}")
        options = plan.material_items_options
        check(
            options is not None
            and options.max_slots_per_batch == frozen.SELECTOR_MAX_SLOTS
            and options.max_items_per_packet == frozen.SELECTOR_MAX_ITEMS
            and options.max_estimated_tokens_per_batch == frozen.SELECTOR_MAX_TOKENS,
            f"items_options:{slug}",
        )
        for profile in plan.profiles:
            if profile.role == "material_items":
                check(
                    profile.profile_sha256 == replan["profile_sha256"],
                    f"plan_profile_binds_new_model:{slug}",
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
        check(calls["runtime_calls"] == EXPECTED_ATTEMPTS[slug], f"runtime_calls:{slug}")
        runtime_calls[slug] = calls["runtime_calls"]
        plan_summary[slug] = {
            "batch_id": plan.batch_id,
            "plan_sha256": plan.plan_sha256,
            "snapshot_id": plan.snapshot.snapshot_id,
            "attempts_max": EXPECTED_ATTEMPTS[slug],
            "runtime_calls": calls["runtime_calls"],
            "packets": calls["packet_count"],
            "candidate_slots": calls["slot_count"],
        }
    check(auth["attempts_max"] == runtime_calls, "authorized_attempts_equal_runtime_calls")

    # D. extraction profile for run-2 (zero call).
    config = load_extraction_config(dotenv_path=ROOT / ".env", options=frozen.request_options())
    profile = config.require_profile()
    check(profile.model == replan["model"] == "deepseek-v4-flash", "profile_model")
    check(profile.fingerprint == replan["profile_sha256"], "profile_fingerprint")
    check(profile.base_url == "https://api.deepseek.com", "profile_base_url")
    check(
        profile.options.model_dump(mode="json") == manifest["request_options"]
        == replan["request_options"],
        "request_options_kept_verbatim",
    )
    check(config.configured is True, "provider_configured")
    check(
        validate_endpoint(profile.base_url, config.credential.get_secret_value()),
        "endpoint_validated",
    )

    # E. run-1 evidence preserved; r2 store absent.
    check((R1 / "live-store").exists(), "run1_store_preserved")
    run1_summary = R1 / "live-run-summary.json"
    check(digest(run1_summary) == replan["r1_run"]["summary_sha256"], "run1_summary_hash")
    run1 = read_json(run1_summary)
    check(
        run1["sources"]["industrial-fulian-md"]["attempt_status"] == {"succeeded": 8, "failed": 2}
        and run1["sources"]["optical-module-docx"]["attempt_status"] == {"failed": 14},
        "run1_429_record_intact",
    )
    check(not STORE.exists(), "r2_store_absent_before_run")

    summary = {
        "schema_version": "items-only-live-pre-execution-verification-r2-1",
        "status": "verified_zero_call",
        "checked_on": "2026-10-11",
        "gate_sha256": digest(R0 / "preregistered-gate.json"),
        "gate_revision": 4,
        "model": profile.model,
        "profile_sha256": profile.fingerprint,
        "plans": plan_summary,
        "authorization": {
            "authorized_by": auth["authorized_by"],
            "authorized_on": auth["authorized_on"],
            "model": auth["model"],
            "attempts_total": sum(runtime_calls.values()),
        },
        "run1_invalidation": replan["r1_run"],
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
