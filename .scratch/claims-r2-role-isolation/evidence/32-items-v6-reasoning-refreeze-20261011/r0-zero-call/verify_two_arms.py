"""Zero-call verification of the frozen two-arm gate (issue 32).

Re-reads the frozen plans, gate and manifest from disk and re-derives every claim the
gate makes: byte hashes, plan identity, protocol per arm, attempt budgets, snapshot
identity against the issue-28 baseline, the one-variable arm difference, authorization
state and the zero-call assertions. Writes verification-summary.json.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E32 = HERE.parent
CLAIMS = E32.parent.parent
E28_R0 = CLAIMS / "evidence" / "28-items-only-quality-gate-20261010" / "r0-zero-call"

from plugins.corpus.material_semantics import (  # noqa: E402
    MATERIAL_SELECTOR_JSONL_V5,
    MATERIAL_SELECTOR_JSONL_V6,
)
from plugins.corpus.structured.ledger import BatchPlan  # noqa: E402

ORDER = ("industrial-fulian-md", "optical-module-docx")
ARMS = ("control", "treatment")
EXPECTED_ATTEMPTS = {"industrial-fulian-md": 10, "optical-module-docx": 14}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    gate = read_json(HERE / "preregistered-gate.json")
    manifest = read_json(HERE / "freeze-manifest.json")
    baseline = {
        entry["slug"]: entry
        for entry in read_json(E28_R0 / "freeze-manifest.json")["sources"]
    }
    checks: list[tuple[str, bool, Any]] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append((name, bool(ok), detail))

    check(
        "gate_bytes_match_manifest_inputs",
        gate["frozen_inputs"] == manifest["inputs"],
        "gate.frozen_inputs",
    )
    check(
        "manifest_file_hashes_match_disk",
        manifest["files_sha256"]
        == {
            f"plan-{arm}-{slug}.json": digest(HERE / f"plan-{arm}-{slug}.json")
            for arm in ARMS
            for slug in ORDER
        },
        sorted(manifest["files_sha256"]),
    )

    protocols = {"control": MATERIAL_SELECTOR_JSONL_V5, "treatment": MATERIAL_SELECTOR_JSONL_V6}
    for arm in ARMS:
        arm_manifest = manifest["arms"][arm]
        check(
            f"{arm}_protocol",
            arm_manifest["protocol"] == protocols[arm] == gate["arms"][arm]["protocol"],
            arm_manifest["protocol"],
        )
        check(
            f"{arm}_profile_matches_gate",
            arm_manifest["profile_sha256"] == gate["arms"][arm]["profile_sha256"],
            arm_manifest["profile_sha256"],
        )
        for slug in ORDER:
            plan = BatchPlan.model_validate_json(
                (HERE / f"plan-{arm}-{slug}.json").read_text(encoding="utf-8")
            )
            plan.verify_identity()
            entry = next(item for item in arm_manifest["sources"] if item["slug"] == slug)
            task = next(task for task in plan.tasks if task.role == "material_items")
            profile = next(item for item in plan.profiles if item.role == "material_items")
            check(f"{arm}_{slug}_plan_identity", plan.plan_sha256 == entry["plan_sha256"])
            check(f"{arm}_{slug}_batch_id", plan.batch_id == entry["batch_id"])
            check(f"{arm}_{slug}_protocol", task.protocol == protocols[arm])
            check(
                f"{arm}_{slug}_attempts",
                plan.role_max_attempts["material_items"] == EXPECTED_ATTEMPTS[slug],
                plan.role_max_attempts["material_items"],
            )
            check(
                f"{arm}_{slug}_snapshot_unchanged",
                plan.snapshot.snapshot_id == baseline[slug]["snapshot_id"],
                plan.snapshot.snapshot_id,
            )
            check(
                f"{arm}_{slug}_slot_count_unchanged",
                entry["candidate_slot_count"] == baseline[slug]["candidate_slot_count"],
                entry["candidate_slot_count"],
            )
            check(f"{arm}_{slug}_relations_disabled", plan.relations.enabled is False)
            check(
                f"{arm}_{slug}_claims_and_relations_zero",
                plan.role_max_attempts["claims"] == 0
                and plan.role_max_attempts["material_relations"] == 0,
                plan.role_max_attempts,
            )
            check(
                f"{arm}_{slug}_profile_frozen_in_plan",
                profile.profile_sha256 == arm_manifest["profile_sha256"],
                profile.profile_sha256,
            )
            check(
                f"{arm}_{slug}_task_counts",
                sum(task.role == "material_items" for task in plan.tasks) == 1
                and sum(task.role == "claims" for task in plan.tasks) == 0
                and sum(task.role == "material_relations" for task in plan.tasks) == 0,
            )

    control_options = manifest["arms"]["control"]["request_options"]
    treatment_options = manifest["arms"]["treatment"]["request_options"]
    differing = {
        key
        for key in set(control_options) | set(treatment_options)
        if control_options.get(key) != treatment_options.get(key)
    }
    check(
        "arms_differ_only_in_reasoning_switch",
        differing == {"thinking"} and control_options.get("thinking") is None,
        sorted(differing),
    )
    check(
        "control_has_no_reasoning_switch",
        control_options.get("reasoning_effort") is None and control_options.get("thinking") is None,
    )
    check(
        "treatment_disables_thinking",
        treatment_options.get("thinking") == "disabled"
        and treatment_options.get("reasoning_effort") is None,
        treatment_options,
    )
    check(
        "profile_hashes_differ_between_arms",
        manifest["arms"]["control"]["profile_sha256"]
        != manifest["arms"]["treatment"]["profile_sha256"],
    )

    auth = gate["authorization"]
    check(
        "only_items_extraction_authorized",
        auth["items_live_extraction"]["authorized"] is True
        and auth["items_live_extraction"]["authorized_by"] == "xyl"
        and all(
            auth[key]["authorized"] is False
            for key in (
                "publication",
                "positive_query_delivery_context_use",
                "production_database_access",
            )
        ),
        {key: auth[key]["authorized"] for key in auth},
    )
    check(
        "authorized_attempts_match_plans",
        auth["items_live_extraction"]["attempts_max"] == EXPECTED_ATTEMPTS,
        auth["items_live_extraction"]["attempts_max"],
    )
    check(
        "countersigned",
        gate["countersignature"]["status"] == "signed"
        and gate["countersignature"]["reviewer"] == "xyl",
        gate["countersignature"],
    )
    check(
        "scope_locks_hold",
        gate["scope"]["new_gold_allowed"] is False
        and gate["scope"]["threshold_relaxation_after_execution_allowed"] is False
        and gate["scope"]["publication_authorized"] is False
        and gate["scope"]["quality_scoring_in_this_gate"] is False
        and gate["scope"]["response_format_enabled"] is False,
    )
    check(
        "zero_call_freeze",
        manifest["model_requests_during_freeze"] == 0
        and manifest["production_database_access"] == 0
        and manifest["holdout_accessed"] is False,
    )
    check(
        "store_not_created_yet",
        not (E32 / "live" / "control-store").exists()
        and not (E32 / "live" / "treatment-store").exists(),
    )

    failed = [name for name, ok, _ in checks if not ok]
    summary = {
        "schema_version": "items-v6-reasoning-verification-1",
        "created_on": "2026-10-11",
        "status": "verified_zero_call" if not failed else "failed",
        "checks_total": len(checks),
        "checks_failed": failed,
        "checks": [
            {"name": name, "ok": ok, "detail": detail} for name, ok, detail in checks
        ],
        "gate_sha256": digest(HERE / "preregistered-gate.json"),
        "freeze_manifest_sha256": digest(HERE / "freeze-manifest.json"),
        "model_requests_during_verification": 0,
        "production_database_access": 0,
    }
    (HERE / "verification-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": summary["status"],
                "checks_total": summary["checks_total"],
                "checks_failed": failed,
                "gate_sha256": summary["gate_sha256"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
