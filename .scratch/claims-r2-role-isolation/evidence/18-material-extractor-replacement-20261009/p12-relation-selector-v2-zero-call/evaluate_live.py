"""Export P12 ledger artifacts and score selector v2 against signed P11 cases."""

from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path
from typing import Any

from plugins.corpus.material_semantics import (
    MATERIAL_ITEMS_VALIDATION_VERSION,
    RELATION_CANDIDATE_RULE_VERSION,
    MaterialRun,
    build_relation_candidate_set,
)
from plugins.corpus.structured.snapshot import EvidenceSnapshot

HERE = Path(__file__).resolve().parent
ISSUE_ROOT = HERE.parent
P10 = ISSUE_ROOT / "p10-accepted-items-import-live"
P11 = ISSUE_ROOT / "p11-relation-precision-sample"
P10_EVALUATOR = P10 / "evaluate_live.py"
SNAPSHOT = (
    ISSUE_ROOT.parent
    / "17-structured-extraction-convergence-closure-20261009"
    / "p1-plan-freeze/copper-items-relations/snapshot.json"
)


def _write(name: str, value: object) -> None:
    (HERE / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_p10_evaluator() -> Any:
    spec = importlib.util.spec_from_file_location("p10_live_evaluator", P10_EVALUATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("P10 evaluator import failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evaluator: Any = module
    evaluator.HERE = HERE
    evaluator.STORE = HERE / "live-store"
    evaluator.SNAPSHOT = SNAPSHOT
    return evaluator


def main() -> None:
    evaluator = _load_p10_evaluator()
    evaluator.main()

    item_payload = json.loads((HERE / "accepted-items-payload.json").read_text())
    p10_relations_raw = json.loads((P10 / "relation-payload.json").read_text())
    p12_relations_raw = json.loads((HERE / "relation-payload.json").read_text())
    items = MaterialRun.model_validate(item_payload)
    p10_relations = MaterialRun.model_validate(p10_relations_raw)
    p12_relations = MaterialRun.model_validate(p12_relations_raw)
    snapshot = EvidenceSnapshot.model_validate_json(SNAPSHOT.read_text(encoding="utf-8"))
    endpoint_ids = tuple(
        item_ref
        for entry in items.understanding.coverage.slot_ledger
        if entry.status == "extracted"
        for item_ref in entry.item_refs
    )
    candidate_set = build_relation_candidate_set(
        snapshot,
        items,
        endpoint_item_ids=endpoint_ids,
        items_validation_version=MATERIAL_ITEMS_VALIDATION_VERSION,
        rule_version=RELATION_CANDIDATE_RULE_VERSION,
    )
    candidate_by_key = {
        (candidate.allowed_type, candidate.from_item, candidate.to_item): candidate
        for candidate in candidate_set.candidates
    }
    candidate_by_id = {
        candidate.candidate_pair_id: candidate for candidate in candidate_set.candidates
    }
    item_by_id = {item.item_id: item for item in items.understanding.items}

    def decisions(run: MaterialRun) -> dict[str, str]:
        present = {
            candidate_by_key[(relation.type, relation.from_item, relation.to_item)].candidate_pair_id
            for relation in run.understanding.relations
        }
        return {
            candidate.candidate_pair_id: (
                "present" if candidate.candidate_pair_id in present else "absent"
            )
            for candidate in candidate_set.candidates
        }

    old = decisions(p10_relations)
    new = decisions(p12_relations)
    transition_counts = Counter((old[pair_id], new[pair_id]) for pair_id in old)
    transitions_by_type = Counter(
        (
            candidate_by_id[pair_id].allowed_type,
            old[pair_id],
            new[pair_id],
        )
        for pair_id in old
    )

    adjudication = json.loads(
        (P11 / "candidate-adjudications.agent-draft.json").read_text(encoding="utf-8")
    )
    if adjudication["status"] != "human_signed":
        raise RuntimeError("P11 adjudication is not signed")
    signed_truth: dict[str, str] = {}
    cohort: dict[str, str] = {}
    for row in adjudication["precision_decisions"]:
        signed_truth[row["candidate_pair_id"]] = (
            "present" if row["agent_decision"] == "accept_present" else "absent"
        )
        cohort[row["candidate_pair_id"]] = "p10_present_precision_sample"
    for row in adjudication["recall_sentinel_decisions"]:
        signed_truth[row["candidate_pair_id"]] = (
            "present"
            if row["agent_decision"] == "overturn_false_negative"
            else "absent"
        )
        cohort[row["candidate_pair_id"]] = "p10_absent_recall_sentinel"

    confusion = Counter((signed_truth[pair_id], new[pair_id]) for pair_id in signed_truth)
    baseline_confusion = Counter(
        (signed_truth[pair_id], old[pair_id]) for pair_id in signed_truth
    )
    rows = [
        {
            "candidate_pair_id": pair_id,
            "allowed_type": candidate_by_id[pair_id].allowed_type,
            "packet_id": candidate_by_id[pair_id].packet_id,
            "from_text": item_by_id[candidate_by_id[pair_id].from_item].text,
            "to_text": item_by_id[candidate_by_id[pair_id].to_item].text,
            "cohort": cohort[pair_id],
            "p10_decision": old[pair_id],
            "p12_decision": new[pair_id],
            "signed_truth": truth,
            "correct": new[pair_id] == truth,
        }
        for pair_id, truth in sorted(signed_truth.items())
    ]
    calibration = json.loads((HERE / "signed-calibration-cases.json").read_text())
    error_case_ids = {row["candidate_pair_id"] for row in calibration["cases"]}
    error_cases_correct = sum(new[pair_id] == signed_truth[pair_id] for pair_id in error_case_ids)
    precision_ids = {
        row["candidate_pair_id"] for row in adjudication["precision_decisions"]
    }
    sentinel_ids = {
        row["candidate_pair_id"]
        for row in adjudication["recall_sentinel_decisions"]
    }

    target_evaluation = json.loads((HERE / "evaluation-summary.json").read_text())
    p10_target_evaluation = json.loads((P10 / "evaluation-summary.json").read_text())
    p10_relation_by_id = {
        relation.relation_id: relation for relation in p10_relations.understanding.relations
    }
    target_pair_decisions = []
    for match in p10_target_evaluation["gold_relation_matches"]:
        for relation_id in match["accepted_relation_ids"]:
            relation = p10_relation_by_id[relation_id]
            candidate = candidate_by_key[
                (relation.type, relation.from_item, relation.to_item)
            ]
            target_pair_decisions.append(
                {
                    "gold_relation": match["gold_relation"],
                    "candidate_pair_id": candidate.candidate_pair_id,
                    "allowed_type": candidate.allowed_type,
                    "from_text": item_by_id[candidate.from_item].text,
                    "to_text": item_by_id[candidate.to_item].text,
                    "p10_decision": old[candidate.candidate_pair_id],
                    "p12_decision": new[candidate.candidate_pair_id],
                }
            )
    execution = json.loads((HERE / "execution-summary.json").read_text())
    usage = execution["usage"]
    regression = {
        "schema_version": "relation-selector-v2-signed-regression-1",
        "created_on": "2026-10-10",
        "status": "failed_signed_regression_and_target_recall_gate",
        "source_sample_id": adjudication["sample_id"],
        "candidate_set_id": candidate_set.candidate_set_id,
        "candidate_rule_version": candidate_set.rule_version,
        "counts": {
            "candidate_universe": len(candidate_set.candidates),
            "p10_present": sum(value == "present" for value in old.values()),
            "p12_present": sum(value == "present" for value in new.values()),
            "present_to_absent": transition_counts[("present", "absent")],
            "absent_to_present": transition_counts[("absent", "present")],
            "unchanged_present": transition_counts[("present", "present")],
            "unchanged_absent": transition_counts[("absent", "absent")],
        },
        "signed_44_case_regression": {
            "cases": len(signed_truth),
            "correct": sum(row["correct"] for row in rows),
            "accuracy": sum(row["correct"] for row in rows) / len(rows),
            "true_positive": confusion[("present", "present")],
            "false_negative": confusion[("present", "absent")],
            "true_negative": confusion[("absent", "absent")],
            "false_positive": confusion[("absent", "present")],
        },
        "p10_signed_44_case_baseline": {
            "cases": len(signed_truth),
            "correct": baseline_confusion[("present", "present")]
            + baseline_confusion[("absent", "absent")],
            "accuracy": (
                baseline_confusion[("present", "present")]
                + baseline_confusion[("absent", "absent")]
            )
            / len(signed_truth),
            "true_positive": baseline_confusion[("present", "present")],
            "false_negative": baseline_confusion[("present", "absent")],
            "true_negative": baseline_confusion[("absent", "absent")],
            "false_positive": baseline_confusion[("absent", "present")],
        },
        "signed_accuracy_delta_vs_p10": (
            confusion[("present", "present")]
            + confusion[("absent", "absent")]
            - baseline_confusion[("present", "present")]
            - baseline_confusion[("absent", "absent")]
        )
        / len(signed_truth),
        "transitions_by_relation_type": [
            {
                "allowed_type": relation_type,
                "p10_decision": before,
                "p12_decision": after,
                "count": count,
            }
            for (relation_type, before, after), count in sorted(
                transitions_by_type.items()
            )
        ],
        "signed_known_error_regression": {
            "cases": len(error_case_ids),
            "corrected": error_cases_correct,
            "correction_rate": error_cases_correct / len(error_case_ids),
        },
        "p10_present_precision_cohort": {
            "cases": len(precision_ids),
            "signed_true_relations_retained": sum(
                signed_truth[pair_id] == "present" and new[pair_id] == "present"
                for pair_id in precision_ids
            ),
            "signed_true_relations_removed": sum(
                signed_truth[pair_id] == "present" and new[pair_id] == "absent"
                for pair_id in precision_ids
            ),
            "signed_false_relations_removed": sum(
                signed_truth[pair_id] == "absent" and new[pair_id] == "absent"
                for pair_id in precision_ids
            ),
            "signed_false_relations_retained": sum(
                signed_truth[pair_id] == "absent" and new[pair_id] == "present"
                for pair_id in precision_ids
            ),
        },
        "p10_absent_sentinel_cohort": {
            "cases": len(sentinel_ids),
            "signed_missed_relations_recovered": sum(
                signed_truth[pair_id] == "present" and new[pair_id] == "present"
                for pair_id in sentinel_ids
            ),
            "signed_missed_relations_still_absent": sum(
                signed_truth[pair_id] == "present" and new[pair_id] == "absent"
                for pair_id in sentinel_ids
            ),
            "signed_true_absences_retained": sum(
                signed_truth[pair_id] == "absent" and new[pair_id] == "absent"
                for pair_id in sentinel_ids
            ),
            "signed_true_absences_flipped_present": sum(
                signed_truth[pair_id] == "absent" and new[pair_id] == "present"
                for pair_id in sentinel_ids
            ),
        },
        "target_evaluation": {
            "gold_relations": target_evaluation["gold_scope"]["relations"],
            "source_relation_recall": target_evaluation["metrics"][
                "source_relation_recall"
            ],
            "matches": target_evaluation["gold_relation_matches"],
            "p10_target_pair_decisions_under_p12": target_pair_decisions,
        },
        "whole_document_precision_measurable": False,
        "precision_reason": (
            "P11 precision rows were sampled from P10 present decisions and absent rows "
            "were non-probability sentinels. P12 changed the prediction population, so the "
            "signed 44-case regression is valid but cannot estimate whole-document P12 precision."
        ),
        "usage": usage,
        "cost": None,
        "cost_status": "unavailable_not_zero",
        "model_calls": execution["model_calls"],
        "publication_query_delivery_context_use": 0,
        "cases": rows,
        "misclassified_signed_cases": [row for row in rows if not row["correct"]],
    }
    _write("signed-sample-regression.json", regression)
    print(json.dumps(regression, ensure_ascii=False))


if __name__ == "__main__":
    main()
