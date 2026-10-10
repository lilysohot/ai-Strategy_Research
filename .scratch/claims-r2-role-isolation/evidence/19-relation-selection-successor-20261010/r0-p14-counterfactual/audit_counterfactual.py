"""Read-only, zero-call P14 diagnostic counterfactual.

The script prints one canonical JSON object to stdout and never writes to the P14
store.  It does not change the frozen P14 decision.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, cast

from plugins.corpus.material_semantics import (
    MATERIAL_ITEMS_VALIDATION_VERSION,
    RELATION_CANDIDATE_RULE_VERSION,
    MaterialRun,
    build_relation_candidate_set,
    group_relation_answer_candidates,
)
from plugins.corpus.structured.snapshot import EvidenceSnapshot

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
SCRATCH = ROOT / ".scratch" / "claims-r2-role-isolation"
E18 = SCRATCH / "evidence" / "18-material-extractor-replacement-20261009"
P10 = E18 / "p10-accepted-items-import-live"
P11 = E18 / "p11-relation-precision-sample"
P12 = E18 / "p12-relation-selector-v2-zero-call"
P14 = E18 / "p14-question-group-live-plan"
STORE = P14 / "live-store"
SNAPSHOT = (
    SCRATCH
    / "evidence"
    / "17-structured-extraction-convergence-closure-20261009"
    / "p1-plan-freeze"
    / "copper-items-relations"
    / "snapshot.json"
)

EXPECTED_BATCH_ID = (
    "batch:391150525103650ff49af17a251091c0908e00bd299553d7108643c174f27a58"
)
EXPECTED_PLAN_SHA256 = (
    "sha256:391150525103650ff49af17a251091c0908e00bd299553d7108643c174f27a58"
)
RELATION_FIELDS = frozenset(
    {"record_type", "relation_index", "status", "evidence_selector"}
)
ANSWER_FIELDS = frozenset(
    {"record_type", "question_index", "selected_answer_indices"}
)


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON root is not an object: {path}")
    return value


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _read_object(object_sha256: str) -> dict[str, Any]:
    digest = object_sha256.removeprefix("sha256:")
    path = STORE / "objects" / "sha256" / digest[:2] / f"{digest}.json"
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise RuntimeError(f"object hash mismatch: {object_sha256}")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError(f"stored object is not a mapping: {object_sha256}")
    return value


def load_immutable_store() -> dict[str, Any]:
    """Load P14 through a read-only SQLite connection and assert frozen identity."""
    frozen_manifest = _read_json(P14 / "manifest.json")
    for name in ("plan.json", "final-gate.json"):
        expected = frozen_manifest["files_sha256"][name]
        if _sha256_file(P14 / name) != expected:
            raise RuntimeError(f"frozen P14 file drifted: {name}")

    connection = sqlite3.connect(
        f"file:{STORE / 'index/structured.sqlite3'}?mode=ro", uri=True
    )
    connection.execute("PRAGMA query_only = ON")
    connection.row_factory = sqlite3.Row
    batch_row = connection.execute("SELECT * FROM batches").fetchone()
    if batch_row is None:
        raise RuntimeError("P14 batch is missing")
    batch = dict(batch_row)
    tasks = {
        row["role"]: dict(row)
        for row in connection.execute(
            "SELECT * FROM tasks ORDER BY derived, task_id"
        ).fetchall()
    }
    attempts = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM attempts ORDER BY attempt_number"
        ).fetchall()
    ]
    connection.close()

    if batch["batch_id"] != EXPECTED_BATCH_ID:
        raise RuntimeError("P14 batch identity drifted")
    if batch["plan_sha256"] != EXPECTED_PLAN_SHA256:
        raise RuntimeError("P14 plan identity drifted")
    if batch["actual_attempts"] != 4 or len(attempts) != 4:
        raise RuntimeError("P14 four-attempt identity drifted")
    if [attempt["attempt_number"] for attempt in attempts] != [1, 2, 3, 4]:
        raise RuntimeError("P14 attempt ordering drifted")

    relation_task = tasks.get("material_relations")
    if relation_task is None:
        raise RuntimeError("P14 relation task is missing")
    relation_payload = _read_object(relation_task["payload_object_sha256"])
    packet_runs = relation_payload.get("packet_runs")
    if not isinstance(packet_runs, list) or len(packet_runs) != 4:
        raise RuntimeError("P14 packet ledger drifted")

    responses: list[dict[str, Any]] = []
    for attempt, packet_run in zip(attempts, packet_runs, strict=True):
        response = _read_object(attempt["response_object_sha256"])
        if response.get("schema_version") != "corpus-model-response-v1":
            raise RuntimeError("unexpected response object schema")
        content = response.get("content")
        if not isinstance(content, str):
            raise RuntimeError("response content is not text")
        responses.append(
            {
                "attempt_number": attempt["attempt_number"],
                "attempt_id": attempt["attempt_id"],
                "packet_id": packet_run["packet_id"],
                "response_sha256": attempt["response_sha256"],
                "response_object_sha256": attempt["response_object_sha256"],
                "content": content,
            }
        )
    return {
        "batch": batch,
        "relation_task": relation_task,
        "relation_payload": relation_payload,
        "responses": responses,
    }


def _candidate_context() -> dict[str, Any]:
    snapshot = EvidenceSnapshot.model_validate_json(
        SNAPSHOT.read_text(encoding="utf-8")
    )
    items = MaterialRun.model_validate_json(
        (P12 / "accepted-items-payload.json").read_text(encoding="utf-8")
    )
    items.verify_identity()
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
    final_gate = _read_json(P14 / "final-gate.json")
    if candidate_set.candidate_set_id != final_gate["candidate_set_id"]:
        raise RuntimeError("candidate-v5 identity drifted")
    packet_ids = tuple(
        dict.fromkeys(candidate.packet_id for candidate in candidate_set.candidates)
    )
    packet_candidates = {
        packet_id: [
            candidate.model_dump(mode="json", exclude={"packet_id"})
            for candidate in candidate_set.candidates
            if candidate.packet_id == packet_id
        ]
        for packet_id in packet_ids
    }
    return {
        "snapshot": snapshot,
        "items": items,
        "candidate_set": candidate_set,
        "packet_ids": packet_ids,
        "packet_candidates": packet_candidates,
        "final_gate": final_gate,
    }


def reparse_responses(
    responses: list[dict[str, Any]],
    packet_candidates: dict[str, list[dict[str, str]]],
) -> dict[str, Any]:
    """Reparse P14 narrowly; relation type to present is diagnostic only."""
    decisions: dict[str, dict[str, Any]] = {}
    packet_summaries: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for response in responses:
        packet_id = response["packet_id"]
        candidates = packet_candidates.get(packet_id)
        if candidates is None:
            raise RuntimeError(f"response packet is outside candidate set: {packet_id}")
        groups = group_relation_answer_candidates(candidates)
        non_answer_indices = {
            index
            for index, candidate in enumerate(candidates)
            if candidate["allowed_type"] != "answers"
        }
        answer_rows: dict[int, list[dict[str, Any]]] = {}
        relation_rows: dict[int, list[dict[str, Any]]] = {}
        local_errors: list[dict[str, Any]] = []

        for line_number, line in enumerate(response["content"].splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                local_errors.append(
                    {"line_number": line_number, "reason": "invalid_json"}
                )
                continue
            if not isinstance(row, dict):
                local_errors.append(
                    {"line_number": line_number, "reason": "record_not_object"}
                )
                continue
            if row.get("record_type") == "answer_group_result":
                question_index = row.get("question_index")
                selected = row.get("selected_answer_indices")
                valid = (
                    set(row) == ANSWER_FIELDS
                    and type(question_index) is int
                    and 0 <= question_index < len(groups)
                    and isinstance(selected, list)
                    and all(type(index) is int for index in selected)
                    and len(selected) == len(set(selected))
                    and all(0 <= index < len(groups[question_index].options) for index in selected)
                )
                if not valid:
                    local_errors.append(
                        {
                            "line_number": line_number,
                            "reason": "invalid_answer_group_result",
                        }
                    )
                    continue
                question_index = cast(int, question_index)
                answer_rows.setdefault(question_index, []).append(row)
                continue
            if row.get("record_type") == "relation_result":
                relation_index = row.get("relation_index")
                valid_index = (
                    type(relation_index) is int
                    and relation_index in non_answer_indices
                )
                if set(row) != RELATION_FIELDS or not valid_index:
                    local_errors.append(
                        {
                            "line_number": line_number,
                            "reason": "invalid_relation_result_shape_or_index",
                        }
                    )
                    continue
                relation_index = cast(int, relation_index)
                relation_rows.setdefault(relation_index, []).append(row)
                continue
            local_errors.append(
                {"line_number": line_number, "reason": "unsupported_record_type"}
            )

        normalized = 0
        for group in groups:
            rows = answer_rows.get(group.question_index, [])
            if len(rows) != 1:
                local_errors.append(
                    {
                        "question_index": group.question_index,
                        "reason": "missing_or_duplicate_answer_group_terminal",
                        "records": len(rows),
                    }
                )
                continue
            selected = set(rows[0]["selected_answer_indices"])
            for option in group.options:
                pair_id = option.candidate_pair_id
                if pair_id in decisions:
                    raise RuntimeError(f"candidate decision duplicated across packets: {pair_id}")
                decisions[pair_id] = {
                    "decision": (
                        "present" if option.answer_index in selected else "absent"
                    ),
                    "provenance": (
                        "observed_answer_selection"
                        if option.answer_index in selected
                        else "implicit_absent_from_answer_selection"
                    ),
                    "packet_id": packet_id,
                }

        for relation_index in sorted(non_answer_indices):
            rows = relation_rows.get(relation_index, [])
            if len(rows) != 1:
                local_errors.append(
                    {
                        "relation_index": relation_index,
                        "reason": "missing_or_duplicate_non_answer_terminal",
                        "records": len(rows),
                    }
                )
                continue
            row = rows[0]
            pair = candidates[relation_index]
            status = row["status"]
            selector = row["evidence_selector"]
            provenance: str
            if status == "present" and selector == "pair_window":
                decision = "present"
                provenance = "observed_valid"
            elif status == "absent" and selector is None:
                decision = "absent"
                provenance = "observed_valid"
            elif status == pair["allowed_type"] and selector == "pair_window":
                decision = "present"
                provenance = "diagnostic_type_as_present"
                normalized += 1
            else:
                local_errors.append(
                    {
                        "relation_index": relation_index,
                        "reason": "unrecoverable_non_answer_terminal",
                        "returned_status": status,
                        "allowed_type": pair["allowed_type"],
                        "evidence_selector": selector,
                    }
                )
                continue
            pair_id = pair["candidate_pair_id"]
            if pair_id in decisions:
                raise RuntimeError(f"candidate decision duplicated across packets: {pair_id}")
            decisions[pair_id] = {
                "decision": decision,
                "provenance": provenance,
                "packet_id": packet_id,
            }

        errors.extend(
            {
                "attempt_number": response["attempt_number"],
                "packet_id": packet_id,
                **error,
            }
            for error in local_errors
        )
        packet_decisions = [
            value for value in decisions.values() if value["packet_id"] == packet_id
        ]
        packet_summaries.append(
            {
                "attempt_number": response["attempt_number"],
                "packet_id": packet_id,
                "candidate_pairs": len(candidates),
                "question_groups": len(groups),
                "non_answer_pairs": len(non_answer_indices),
                "reconstructed_decisions": len(packet_decisions),
                "present": sum(
                    value["decision"] == "present" for value in packet_decisions
                ),
                "diagnostic_normalizations": normalized,
                "reconstructable": not local_errors
                and len(packet_decisions) == len(candidates),
            }
        )
    return {
        "decisions": decisions,
        "packets": packet_summaries,
        "errors": errors,
        "reconstructable": not errors
        and all(packet["reconstructable"] for packet in packet_summaries),
    }


def _relation_key(relation: Any) -> tuple[str, str, str]:
    return (relation.type, relation.from_item, relation.to_item)


def score_gate(
    reconstructed: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Score the frozen signed regression cohort; never claim whole-document precision."""
    candidate_set = context["candidate_set"]
    final_gate = context["final_gate"]
    candidate_by_id = {
        candidate.candidate_pair_id: candidate for candidate in candidate_set.candidates
    }
    candidate_id_by_key = {
        (candidate.allowed_type, candidate.from_item, candidate.to_item): (
            candidate.candidate_pair_id
        )
        for candidate in candidate_set.candidates
    }
    all_pair_ids = set(candidate_by_id)
    decisions = {
        pair_id: value["decision"]
        for pair_id, value in reconstructed["decisions"].items()
    }

    p10_relations = MaterialRun.model_validate_json(
        (P10 / "relation-payload.json").read_text(encoding="utf-8")
    )
    p10_present = {
        candidate_id_by_key[_relation_key(relation)]
        for relation in p10_relations.understanding.relations
    }
    baseline = {
        pair_id: "present" if pair_id in p10_present else "absent"
        for pair_id in all_pair_ids
    }

    adjudication = _read_json(P11 / "candidate-adjudications.agent-draft.json")
    if adjudication.get("status") != "human_signed":
        raise RuntimeError("P11 sample is not human signed")
    if adjudication.get("sample_id") != final_gate["sample_id"]:
        raise RuntimeError("P11 sample identity drifted")
    signed_truth: dict[str, str] = {}
    for row in adjudication["precision_decisions"]:
        signed_truth[row["candidate_pair_id"]] = (
            "present" if row["agent_decision"] == "accept_present" else "absent"
        )
    for row in adjudication["recall_sentinel_decisions"]:
        signed_truth[row["candidate_pair_id"]] = (
            "present"
            if row["agent_decision"] == "overturn_false_negative"
            else "absent"
        )

    requirements = final_gate["quality_requirements"]
    if len(signed_truth) != requirements["signed_cases_total"]:
        raise RuntimeError("signed cohort cardinality drifted")
    if not set(signed_truth) <= all_pair_ids:
        raise RuntimeError("signed cohort escaped candidate-v5")

    calibration = _read_json(P12 / "signed-calibration-cases.json")
    if calibration["source_sample_id"] != final_gate["sample_id"]:
        raise RuntimeError("known-error sample identity drifted")
    if calibration["candidate_set_id"] != candidate_set.candidate_set_id:
        raise RuntimeError("known-error candidate identity drifted")
    known_error_ids = {row["candidate_pair_id"] for row in calibration["cases"]}
    if len(known_error_ids) != requirements["known_error_cases_total"]:
        raise RuntimeError("known-error cohort cardinality drifted")

    previously_correct = {
        pair_id
        for pair_id, truth in signed_truth.items()
        if baseline[pair_id] == truth
    }
    if len(previously_correct) != requirements["previously_correct_cases_total"]:
        raise RuntimeError("previously-correct cohort cardinality drifted")

    signed_correct = sum(
        decisions.get(pair_id) == truth for pair_id, truth in signed_truth.items()
    )
    known_correct = sum(
        decisions.get(pair_id) == signed_truth[pair_id]
        for pair_id in known_error_ids
    )
    regressions = {
        pair_id
        for pair_id in previously_correct
        if decisions.get(pair_id) != signed_truth[pair_id]
    }
    stable_type_regressions = {
        pair_id
        for pair_id in regressions
        if candidate_by_id[pair_id].allowed_type in {"supports", "conditions"}
    }

    p10_relation_pair = {
        relation.relation_id: candidate_id_by_key[_relation_key(relation)]
        for relation in p10_relations.understanding.relations
    }
    target_evaluation = _read_json(P10 / "evaluation-summary.json")
    target_results = []
    for target in target_evaluation["gold_relation_matches"]:
        pair_ids = sorted(
            {
                p10_relation_pair[relation_id]
                for relation_id in target["accepted_relation_ids"]
            }
        )
        matched = any(decisions.get(pair_id) == "present" for pair_id in pair_ids)
        target_results.append(
            {
                "gold_relation": target["gold_relation"],
                "candidate_pair_ids": pair_ids,
                "matched": matched,
            }
        )
    if len(target_results) != requirements["target_relations_total"]:
        raise RuntimeError("target relation cohort cardinality drifted")
    target_matched = sum(target["matched"] for target in target_results)

    gates = {
        "signed_cases": {
            "actual": signed_correct,
            "minimum": requirements["signed_cases_correct_min"],
            "passed": signed_correct >= requirements["signed_cases_correct_min"],
        },
        "known_errors": {
            "actual": known_correct,
            "minimum": requirements["known_error_cases_correct_min"],
            "passed": known_correct >= requirements["known_error_cases_correct_min"],
        },
        "previously_correct_regressions": {
            "actual": len(regressions),
            "maximum": requirements["previously_correct_regressions_max"],
            "passed": len(regressions)
            <= requirements["previously_correct_regressions_max"],
        },
        "target_relations": {
            "actual": target_matched,
            "minimum": requirements["target_relations_matched_min"],
            "passed": target_matched >= requirements["target_relations_matched_min"],
        },
        "supports_conditions_previously_correct_regressions": {
            "actual": len(stable_type_regressions),
            "maximum": 0,
            "passed": not stable_type_regressions,
        },
    }
    return {
        "whole_document_precision_measured": False,
        "signed_cases_correct": signed_correct,
        "known_errors_correct": known_correct,
        "previously_correct_regressions": sorted(regressions),
        "supports_conditions_regressions": sorted(stable_type_regressions),
        "target_results": target_results,
        "gates": gates,
        "passed": reconstructed["reconstructable"]
        and len(decisions) == len(all_pair_ids)
        and all(gate["passed"] for gate in gates.values()),
    }


def compare_packets(
    reconstructed: dict[str, Any], context: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return descriptive packet diagnostics, never a causal comparison."""
    candidate_by_id = {
        candidate.candidate_pair_id: candidate
        for candidate in context["candidate_set"].candidates
    }
    adjudication = _read_json(P11 / "candidate-adjudications.agent-draft.json")
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
    decisions = reconstructed["decisions"]
    output = []
    for packet in reconstructed["packets"]:
        packet_id = packet["packet_id"]
        signed_ids = sorted(
            pair_id
            for pair_id in truth
            if candidate_by_id[pair_id].packet_id == packet_id
        )
        output.append(
            {
                **packet,
                "signed_cases": len(signed_ids),
                "signed_correct": sum(
                    decisions.get(pair_id, {}).get("decision") == truth[pair_id]
                    for pair_id in signed_ids
                ),
                "causal_inference_allowed": False,
            }
        )
    return output


def main() -> None:
    store = load_immutable_store()
    context = _candidate_context()
    packet_ids = list(context["packet_ids"])
    response_packet_ids = [response["packet_id"] for response in store["responses"]]
    if response_packet_ids != packet_ids:
        raise RuntimeError("attempt-to-packet mapping drifted")
    reconstructed = reparse_responses(
        store["responses"], context["packet_candidates"]
    )
    score = score_gate(reconstructed, context)
    if not reconstructed["reconstructable"]:
        decision = "diagnostic_not_reconstructable"
    elif score["passed"]:
        decision = (
            "format_recoverable_semantics_passed_allow_issue_19_implementation"
        )
    else:
        decision = (
            "format_recoverable_semantics_failed_stop_same_model_successor"
        )
    result = {
        "schema_version": "p14-read-only-counterfactual-1",
        "source": {
            "batch_id": EXPECTED_BATCH_ID,
            "plan_sha256": EXPECTED_PLAN_SHA256,
            "candidate_set_id": context["candidate_set"].candidate_set_id,
            "sample_id": context["final_gate"]["sample_id"],
        },
        "constraints": {
            "model_calls": 0,
            "writes_to_p14_store": 0,
            "new_gold": 0,
            "revive_p14": False,
            "p14_final_decision_changed": False,
            "whole_document_precision_measured": False,
        },
        "reconstruction": {
            "reconstructable": reconstructed["reconstructable"],
            "candidate_decisions": len(reconstructed["decisions"]),
            "present": sum(
                value["decision"] == "present"
                for value in reconstructed["decisions"].values()
            ),
            "provenance_counts": dict(
                sorted(
                    Counter(
                        value["provenance"]
                        for value in reconstructed["decisions"].values()
                    ).items()
                )
            ),
            "errors": reconstructed["errors"],
        },
        "packet_comparison": compare_packets(reconstructed, context),
        "score": score,
        "decision": decision,
    }
    print(_canonical(result))


if __name__ == "__main__":
    main()
