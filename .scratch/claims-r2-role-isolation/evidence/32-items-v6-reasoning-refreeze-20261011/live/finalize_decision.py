"""Zero-call terminal decision for the issue-32 gate (idempotent, re-runnable).

Reads post-run-check.json plus the two run summaries, evaluates every frozen exit
criterion per arm, and writes gate-decision.json. It never writes to the stores and makes
no model request. Quality thresholds are explicitly out of scope.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E32 = HERE.parent
R0 = E32 / "r0-zero-call"
ARMS = ("control", "treatment")
ORDER = ("industrial-fulian-md", "optical-module-docx")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    report = read_json(HERE / "post-run-check.json")
    summaries = {arm: read_json(HERE / f"{arm}-run-summary.json") for arm in ARMS}
    treatment = report["arms"]["treatment"]
    control = report["arms"]["control"]

    def batches_with_error(arm: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for slug, record in report["arms"][arm]["sources"].items():
            result[slug] = sum(
                1 for detail in record["batch_diagnostics"] if detail.get("error_type")
            )
        return result

    protocol_violations = {
        arm: {
            slug: sum(
                1
                for detail in record["batch_diagnostics"]
                if detail.get("validation_error") == "role response contains an unsupported JSONL record"
            )
            for slug, record in report["arms"][arm]["sources"].items()
        }
        for arm in ARMS
    }
    token = {
        arm: {
            key: sum(
                record["usage"][key]
                for record in report["arms"][arm]["sources"].values()
            )
            for key in ("prompt_tokens", "completion_tokens", "reasoning_tokens", "total_tokens")
        }
        for arm in ARMS
    }
    items = {
        arm: {
            slug: record["items"]["total"]
            for slug, record in report["arms"][arm]["sources"].items()
        }
        for arm in ARMS
    }
    failed_slot_reasons = {
        arm: {
            slug: sorted(
                {
                    tuple(slot.get("reason_codes") or ())
                    for slot in read_json(HERE / "candidates.json")["sources"][
                        f"{arm}/{slug}"
                    ]["candidate_slots"]
                    if slot["status"] not in {"extracted", "no_supported_item"}
                }
            )
            for slug in ORDER
        }
        for arm in ARMS
    }

    attempts_ok = all(
        report["arms"]["treatment"]["sources"][slug]["attempts"]
        == report["arms"]["treatment"]["sources"][slug]["expected_attempts"]
        for slug in ORDER
    )
    no_429 = all(
        set(report["arms"][arm]["sources"][slug]["attempt_status"]) - {"succeeded", "outcome_unknown"}
        == set()
        for arm in ARMS
        for slug in ORDER
    )
    no_retries = all(
        detail.get("attempts") in (1, None)
        for arm in ARMS
        for record in report["arms"][arm]["sources"].values()
        for detail in record["batch_diagnostics"]
    )
    context_ok = all(
        task["context_status"] == "complete"
        for arm in ARMS
        for record in report["arms"][arm]["sources"].values()
        for task in record["tasks"]
    )

    criteria = {
        "attempts_match_plan": {
            "met": attempts_ok,
            "detail": {
                slug: f"{report['arms']['treatment']['sources'][slug]['attempts']}"
                f"/{report['arms']['treatment']['sources'][slug]['expected_attempts']}"
                for slug in ORDER
            },
        },
        "no_http_429": {"met": no_429, "detail": "attempt statuses limited to succeeded/outcome_unknown"},
        "no_automatic_retries": {"met": no_retries, "detail": "adapter attempts == 1 on every batch"},
        "protocol_status_valid": {
            "met": False,
            "observed": {
                slug: report["arms"]["treatment"]["sources"][slug]["tasks"][0]["protocol_status"]
                for slug in ORDER
            },
            "reason": "the items task did not succeed, so protocol adjudication was not reached",
        },
        "failed_partial_invalid_duplicate_batches_max_0": {
            "met": False,
            "observed_packet_statuses": {
                slug: report["arms"]["treatment"]["sources"][slug]["packet_statuses"]
                for slug in ORDER
            },
        },
        "completed_min": {
            "met": False,
            "detail": {
                slug: report["arms"]["treatment"]["sources"][slug]["packet_statuses"].get(
                    "completed", 0
                )
                for slug in ORDER
            },
        },
        "execution_status_succeeded": {
            "met": False,
            "observed": {
                slug: report["arms"]["treatment"]["sources"][slug]["tasks"][0]["execution_status"]
                for slug in ORDER
            },
        },
        "context_status_complete": {"met": context_ok},
        "reasoning_tokens_zero_or_absent": {
            "met": token["treatment"]["reasoning_tokens"] == 0,
            "detail": {
                "treatment": token["treatment"]["reasoning_tokens"],
                "control": token["control"]["reasoning_tokens"],
            },
        },
        "control_arm_reproduced_failure": {
            "met": report["control_arm_reproduced_failure"],
            "detail": {
                "control_protocol_violation_batches": protocol_violations["control"],
                "control_failed_slots": {
                    slug: report["arms"]["control"]["sources"][slug]["slot_statuses"].get(
                        "failed", 0
                    )
                    for slug in ORDER
                },
            },
        },
    }

    unmet = [name for name, value in criteria.items() if not value["met"]]
    verdict = "pass" if not unmet else "structural_fail"

    decision = {
        "schema_version": "items-v6-reasoning-gate-decision-1",
        "decided_on": "2026-10-11",
        "gate_sha256": digest(R0 / "preregistered-gate.json"),
        "freeze_manifest_sha256": digest(R0 / "freeze-manifest.json"),
        "post_run_check_sha256": digest(HERE / "post-run-check.json"),
        "run_summaries": {arm: digest(HERE / f"{arm}-run-summary.json") for arm in ARMS},
        "verdict": verdict,
        "criteria": criteria,
        "criteria_unmet": unmet,
        "token_effect_treatment_vs_control": {
            "prompt_tokens": {"control": token["control"]["prompt_tokens"], "treatment": token["treatment"]["prompt_tokens"]},
            "completion_tokens": {
                "control": token["control"]["completion_tokens"],
                "treatment": token["treatment"]["completion_tokens"],
                "delta_percent": round(
                    100
                    * (token["treatment"]["completion_tokens"] - token["control"]["completion_tokens"])
                    / token["control"]["completion_tokens"],
                    1,
                ),
            },
            "reasoning_tokens": {
                "control": token["control"]["reasoning_tokens"],
                "treatment": token["treatment"]["reasoning_tokens"],
            },
            "total_tokens": {
                "control": token["control"]["total_tokens"],
                "treatment": token["treatment"]["total_tokens"],
                "delta_percent": round(
                    100
                    * (token["treatment"]["total_tokens"] - token["control"]["total_tokens"])
                    / token["control"]["total_tokens"],
                    1,
                ),
            },
        },
        "items_produced": items,
        "protocol_violations_unsupported_jsonl_record": protocol_violations,
        "failed_slot_reasons": {
            arm: {slug: [list(codes) for codes in reasons] for slug, reasons in per_arm.items()}
            for arm, per_arm in failed_slot_reasons.items()
        },
        "attribution": {
            "protocol_violation_batches": {
                "control": protocol_violations["control"],
                "treatment": protocol_violations["treatment"],
            },
            "treatment_residual_causes": [
                "industrial-fulian-md: one TransportOutcomeUnknown attempt "
                "(LlmCallError, no automatic retry) — independent infrastructure event, "
                "same shape as issue-31 run-2",
                "optical-module-docx: two slots rejected by controller semantic validation "
                "(controller_semantic_validation_failed with missing_signal/commentary_only) "
                "— fail-closed semantic adjudication, not a JSONL format violation",
            ],
            "root_cause_status": (
                "eliminated: zero 'unsupported JSONL record' batches under the v6 prompt, "
                "against 11 batches under the v5 control arm"
            ),
        },
        "quality_scoring": {
            "status": "not_in_this_gate",
            "note": "target recall / precision / 16 assertions belong to a separate downstream gate",
        },
        "reporting_scope": {
            "structural_only": True,
            "passed_is_not_quality_pass": True,
        },
        "model_requests_during_decision": 0,
        "production_database_access": 0,
    }
    (HERE / "gate-decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "verdict": verdict,
                "criteria_unmet": unmet,
                "token_effect": decision["token_effect_treatment_vs_control"],
                "protocol_violations": protocol_violations,
                "items_produced": items,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
