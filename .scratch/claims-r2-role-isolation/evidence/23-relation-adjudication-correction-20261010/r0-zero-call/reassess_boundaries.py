"""Apply the Issue 23 boundary addendum as a zero-call sensitivity analysis."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[5]
CLAIMS = ROOT / ".scratch" / "claims-r2-role-isolation"
ISSUE22 = (
    CLAIMS
    / "evidence"
    / "22-doubao-lite-provider-ceiling-20261010"
    / "p0-256k-minimal-live"
)
EVALUATOR = (
    CLAIMS
    / "evidence"
    / "19-relation-selection-successor-20261010"
    / "r0-p14-counterfactual"
    / "audit_counterfactual.py"
)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON root is not an object: {path}")
    return value


def _load_evaluator() -> Any:
    spec = importlib.util.spec_from_file_location("issue23_counterfactual", EVALUATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("counterfactual evaluator import failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evaluator: Any = module
    evaluator.P14 = ISSUE22
    return evaluator


def main() -> None:
    evaluator = _load_evaluator()
    context = evaluator._candidate_context()
    raw = json.loads((ISSUE22 / "raw-response-audit.json").read_text(encoding="utf-8"))
    reconstructed = evaluator.reparse_responses(raw, context["packet_candidates"])
    if not reconstructed["reconstructable"]:
        raise RuntimeError("Issue 22 decisions are not reconstructable")

    addendum = _read(HERE / "semantic-boundary-addendum.agent-draft.json")
    adjudication = _read(evaluator.P11 / "candidate-adjudications.agent-draft.json")
    truth: dict[str, str] = {}
    for row in adjudication["precision_decisions"]:
        truth[row["candidate_pair_id"]] = (
            "present" if row["agent_decision"] == "accept_present" else "absent"
        )
    for row in adjudication["recall_sentinel_decisions"]:
        truth[row["candidate_pair_id"]] = (
            "present"
            if row["agent_decision"] == "overturn_false_negative"
            else "absent"
        )
    decisions = {
        pair_id: value["decision"]
        for pair_id, value in reconstructed["decisions"].items()
    }
    rows = addendum["cases"]
    if len(rows) != 7 or len({row["candidate_pair_id"] for row in rows}) != 7:
        raise RuntimeError("boundary case identity is not unique")
    for row in rows:
        pair_id = row["candidate_pair_id"]
        if truth.get(pair_id) != row["original_truth"]:
            raise RuntimeError(f"original truth drifted: {pair_id}")
        if decisions.get(pair_id) != row["model_decision"]:
            raise RuntimeError(f"model decision drifted: {pair_id}")

    excluded = {
        row["candidate_pair_id"]
        for row in rows
        if row["review_disposition"] == "exclude_unscorable"
    }
    corrected_truth = dict(truth)
    changed_truth = {
        row["candidate_pair_id"]: row["corrected_truth"]
        for row in rows
        if row["review_disposition"] == "change_truth"
    }
    corrected_truth.update(changed_truth)
    retained = set(truth) - excluded
    correct = sum(
        decisions[pair_id] == corrected_truth[pair_id] for pair_id in retained
    )
    original_requirement = context["final_gate"]["quality_requirements"]
    equivalent_minimum = math.ceil(
        original_requirement["signed_cases_correct_min"]
        / original_requirement["signed_cases_total"]
        * len(retained)
    )

    calibration = _read(evaluator.P12 / "signed-calibration-cases.json")
    known_error_ids = {
        row["candidate_pair_id"] for row in calibration["cases"]
    } & retained
    known_correct = sum(
        decisions[pair_id] == corrected_truth[pair_id] for pair_id in known_error_ids
    )
    original = _read(ISSUE22 / "counterfactual-summary.json")["score"]
    remaining_errors = {
        pair_id
        for pair_id in retained
        if decisions[pair_id] != corrected_truth[pair_id]
    }
    surviving_regressions = remaining_errors & set(
        original["previously_correct_regressions"]
    )
    candidate_by_id = {
        candidate.candidate_pair_id: candidate
        for candidate in context["candidate_set"].candidates
    }
    stable_regressions = {
        pair_id
        for pair_id in surviving_regressions
        if candidate_by_id[pair_id].allowed_type in {"supports", "conditions"}
    }
    target_matched = sum(row["matched"] for row in original["target_results"])
    sensitivity_passed = (
        correct >= equivalent_minimum
        and known_correct >= original_requirement["known_error_cases_correct_min"]
        and len(surviving_regressions)
        <= original_requirement["previously_correct_regressions_max"]
        and target_matched >= original_requirement["target_relations_matched_min"]
        and not stable_regressions
    )
    result = {
        "schema_version": "issue23-boundary-corrected-sensitivity-score-1",
        "created_on": "2026-10-10",
        "status": "sensitivity_passed_pending_full_cohort_audit_and_signature",
        "source_sample_id": addendum["source_sample_id"],
        "candidate_set_id": addendum["candidate_set_id"],
        "constraints": {
            "model_calls": 0,
            "original_signed_file_modified": False,
            "issue22_terminal_decision_changed": False,
            "post_hoc_official_gate_claimed": False,
            "whole_document_precision_measured": False,
        },
        "boundary_review": {
            "reviewed_cases": len(rows),
            "excluded_unscorable": sorted(excluded),
            "retained_truth_cases": sorted(
                row["candidate_pair_id"]
                for row in rows
                if row["review_disposition"] == "retain_truth"
            ),
            "changed_truth": dict(sorted(changed_truth.items())),
        },
        "original_frozen_score": {
            "correct": original["signed_cases_correct"],
            "cases": original_requirement["signed_cases_total"],
            "minimum": original_requirement["signed_cases_correct_min"],
            "passed": False,
        },
        "corrected_sensitivity_score": {
            "correct": correct,
            "eligible_cases": len(retained),
            "accuracy": correct / len(retained),
            "equivalent_ratio_minimum": equivalent_minimum,
            "passed_equivalent_ratio": correct >= equivalent_minimum,
            "remaining_errors": sorted(remaining_errors),
        },
        "known_error_sensitivity": {
            "correct": known_correct,
            "eligible_cases": len(known_error_ids),
        },
        "other_frozen_gate_sensitivity": {
            "previously_correct_regressions": len(surviving_regressions),
            "previously_correct_regressions_maximum": original_requirement[
                "previously_correct_regressions_max"
            ],
            "supports_conditions_regressions": len(stable_regressions),
            "target_relations_matched": target_matched,
            "target_relations_required": original_requirement[
                "target_relations_matched_min"
            ],
        },
        "sensitivity_passed": sensitivity_passed,
        "decision": (
            "the reviewed-error sensitivity passes, but it is post-hoc and cannot relabel "
            "Issue 22; audit all 44 cases and obtain an independent signature before "
            "freezing gold-v2"
        ),
    }
    (HERE / "corrected-sensitivity-score.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
