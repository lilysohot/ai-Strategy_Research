"""Read-only audit and signed-gold scoring for the final boolean-v2 live run."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, cast

from plugins.corpus.material_semantics import group_relation_answer_candidates

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[5]
CLAIMS = ROOT / ".scratch" / "claims-r2-role-isolation"
STORE = HERE / "live-store-v2"
ISSUE23 = CLAIMS / "evidence" / "23-relation-adjudication-correction-20261010" / "r0-zero-call"
P12 = (
    CLAIMS
    / "evidence"
    / "18-material-extractor-replacement-20261009"
    / "p12-relation-selector-v2-zero-call"
)
EVALUATOR = (
    CLAIMS
    / "evidence"
    / "19-relation-selection-successor-20261010"
    / "r0-p14-counterfactual"
    / "audit_counterfactual.py"
)
EXPECTED_BATCH_ID = "batch:3269051ddc97ebc979132d5110bdf923c22f28b9f87dd579717b27acb120f920"
ANSWER_FIELDS = frozenset({"record_type", "question_index", "selected_answer_indices"})
RELATION_FIELDS = frozenset({"record_type", "relation_index", "is_present"})


def _read_mapping(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON root is not an object: {path}")
    return value


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


def _write(name: str, value: object) -> None:
    (HERE / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_evaluator() -> Any:
    spec = importlib.util.spec_from_file_location("issue25_context", EVALUATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("candidate context import failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evaluator: Any = module
    evaluator.P14 = HERE
    return evaluator


def _parse_packet(
    content: str, candidates: list[dict[str, str]]
) -> tuple[dict[str, str], dict[str, int], list[dict[str, Any]]]:
    groups = group_relation_answer_candidates(candidates)
    non_answer_indices = {
        index
        for index, candidate in enumerate(candidates)
        if candidate["allowed_type"] != "answers"
    }
    answers: dict[int, list[dict[str, Any]]] = {}
    relations: dict[int, list[dict[str, Any]]] = {}
    violations: list[dict[str, Any]] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            violations.append(
                {"line_number": line_number, "reason": "invalid_json", "detail": exc.msg}
            )
            continue
        if not isinstance(row, dict):
            violations.append({"line_number": line_number, "reason": "not_object"})
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
                violations.append(
                    {
                        "line_number": line_number,
                        "reason": "invalid_answer_group",
                        "keys": sorted(str(key) for key in row),
                    }
                )
                continue
            answers.setdefault(cast(int, question_index), []).append(row)
        elif row.get("record_type") == "relation_result":
            relation_index = row.get("relation_index")
            valid = (
                set(row) == RELATION_FIELDS
                and type(relation_index) is int
                and relation_index in non_answer_indices
                and type(row.get("is_present")) is bool
            )
            if not valid:
                violations.append(
                    {
                        "line_number": line_number,
                        "reason": "invalid_boolean_relation",
                        "keys": sorted(str(key) for key in row),
                    }
                )
                continue
            relations.setdefault(cast(int, relation_index), []).append(row)
        else:
            violations.append({"line_number": line_number, "reason": "unsupported_record_type"})

    decisions: dict[str, str] = {}
    missing = 0
    duplicates = 0
    for group in groups:
        rows = answers.get(group.question_index, [])
        if not rows:
            missing += 1
            continue
        if len(rows) != 1:
            duplicates += len(rows) - 1
            continue
        selected = set(rows[0]["selected_answer_indices"])
        for option in group.options:
            decisions[option.candidate_pair_id] = (
                "present" if option.answer_index in selected else "absent"
            )
    for relation_index in sorted(non_answer_indices):
        rows = relations.get(relation_index, [])
        if not rows:
            missing += 1
            continue
        if len(rows) != 1:
            duplicates += len(rows) - 1
            continue
        pair_id = candidates[relation_index]["candidate_pair_id"]
        decisions[pair_id] = "present" if rows[0]["is_present"] else "absent"
    counts = {
        "candidate_pairs": len(candidates),
        "expected_terminals": len(groups) + len(non_answer_indices),
        "terminals": sum(len(rows) for rows in answers.values())
        + sum(len(rows) for rows in relations.values()),
        "candidate_decisions": len(decisions),
        "missing_decisions": missing,
        "duplicate_decisions": duplicates,
        "invalid_decisions": len(violations),
    }
    return decisions, counts, violations


def main() -> None:
    connection = sqlite3.connect(f"file:{STORE / 'index/structured.sqlite3'}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    connection.row_factory = sqlite3.Row
    batch = dict(connection.execute("SELECT * FROM batches").fetchone())
    tasks = {
        row["role"]: dict(row)
        for row in connection.execute("SELECT * FROM tasks ORDER BY derived, task_id").fetchall()
    }
    attempts = [
        dict(row)
        for row in connection.execute("SELECT * FROM attempts ORDER BY attempt_number").fetchall()
    ]
    connection.close()
    if batch["batch_id"] != EXPECTED_BATCH_ID or batch["actual_attempts"] != 4:
        raise RuntimeError("frozen batch identity or attempt count drifted")

    relation_task = tasks["material_relations"]
    payload = _read_object(relation_task["payload_object_sha256"])
    packet_runs = payload.get("packet_runs")
    if not isinstance(packet_runs, list) or len(packet_runs) != 4:
        raise RuntimeError("relation packet cardinality drifted")
    context = _load_evaluator()._candidate_context()
    gate = _read_mapping(HERE / "final-gate.json")
    if context["candidate_set"].candidate_set_id != gate["candidate_set_id"]:
        raise RuntimeError("candidate set identity drifted")

    all_decisions: dict[str, str] = {}
    response_audit: list[dict[str, Any]] = []
    totals = Counter()
    raw_responses: list[dict[str, Any]] = []
    for attempt, packet_run in zip(attempts, packet_runs, strict=True):
        response = _read_object(attempt["response_object_sha256"])
        content = response.get("content")
        diagnostics = response.get("diagnostics")
        if not isinstance(content, str) or not isinstance(diagnostics, dict):
            raise RuntimeError("response object is malformed")
        packet_id = packet_run["packet_id"]
        decisions, counts, violations = _parse_packet(
            content, context["packet_candidates"][packet_id]
        )
        overlap = set(all_decisions) & set(decisions)
        if overlap:
            raise RuntimeError(f"candidate decisions repeated across packets: {sorted(overlap)}")
        all_decisions.update(decisions)
        totals.update(counts)
        response_audit.append(
            {
                "attempt_number": attempt["attempt_number"],
                "attempt_id": attempt["attempt_id"],
                "execution_status": attempt["execution_status"],
                "packet_id": packet_id,
                "packet_status": packet_run["status"],
                "packet_reasons": packet_run["reasons"],
                "response_sha256": attempt["response_sha256"],
                "response_object_sha256": attempt["response_object_sha256"],
                "response_model": diagnostics.get("response_model"),
                "finish_reason": diagnostics.get("finish_reason"),
                "duration_ms": diagnostics.get("duration_ms"),
                "content_chars": len(content),
                "nonempty_lines": sum(bool(line.strip()) for line in content.splitlines()),
                "prompt_tokens": diagnostics.get("prompt_tokens"),
                "completion_tokens": diagnostics.get("completion_tokens"),
                "reasoning_tokens": diagnostics.get("reasoning_tokens"),
                "counts": counts,
                "violations": violations,
            }
        )
        raw_responses.append(
            {
                "attempt_number": attempt["attempt_number"],
                "packet_id": packet_id,
                "content": content,
            }
        )

    usage_rows = [json.loads(attempt["usage"]) for attempt in attempts]
    usage = {
        key: sum((row.get(key) or 0) for row in usage_rows)
        for key in ("prompt_tokens", "completion_tokens", "reasoning_tokens", "total_tokens")
    }
    packet_status = Counter(packet["status"] for packet in packet_runs)
    protocol_passed = (
        len(all_decisions) == 333
        and totals["missing_decisions"] == 0
        and totals["duplicate_decisions"] == 0
        and totals["invalid_decisions"] == 0
        and packet_status["completed"] == 4
        and packet_status["partial"] == 0
        and packet_status["failed"] == 0
    )

    gold = _read_mapping(ISSUE23 / "gold-v2.agent-draft.json")
    expected_gold_hash = gate["gold_v2_sha256"].removeprefix("sha256:")
    if hashlib.sha256((ISSUE23 / "gold-v2.agent-draft.json").read_bytes()).hexdigest() != (
        expected_gold_hash
    ):
        raise RuntimeError("signed gold-v2 bytes drifted")
    if gold["status"] != "human_signed" or gold["signoff"]["name"] != "xyl":
        raise RuntimeError("gold-v2 signoff drifted")
    truth = {row["candidate_pair_id"]: row["truth"] for row in gold["decisions"]}
    calibration = _read_mapping(P12 / "signed-calibration-cases.json")
    known_ids = {row["candidate_pair_id"] for row in calibration["cases"]}
    eligible_known = known_ids & set(truth)
    prior_correct_ids = set(truth) - eligible_known
    candidate_by_id = {
        candidate.candidate_pair_id: candidate for candidate in context["candidate_set"].candidates
    }
    item_by_id = {item.item_id: item for item in context["items"].understanding.items}
    errors = {
        pair_id for pair_id, expected in truth.items() if all_decisions.get(pair_id) != expected
    }
    correct = len(truth) - len(errors)
    known_correct = sum(all_decisions.get(pair_id) == truth[pair_id] for pair_id in eligible_known)
    regressions = errors & prior_correct_ids
    stable_regressions = {
        pair_id
        for pair_id in regressions
        if candidate_by_id[pair_id].allowed_type in {"supports", "conditions"}
    }
    target_results = [
        {
            "gold_relation": row["gold_relation"],
            "candidate_pair_ids": row["candidate_pair_ids"],
            "matched": any(
                all_decisions.get(pair_id) == "present" for pair_id in row["candidate_pair_ids"]
            ),
        }
        for row in gate["target_groups"]
    ]
    target_matched = sum(row["matched"] for row in target_results)
    misclassified_cases = [
        {
            "candidate_pair_id": pair_id,
            "relation_type": candidate_by_id[pair_id].allowed_type,
            "from_text": item_by_id[candidate_by_id[pair_id].from_item].text,
            "to_text": item_by_id[candidate_by_id[pair_id].to_item].text,
            "gold_v2_truth": truth[pair_id],
            "model_decision": all_decisions.get(pair_id),
            "known_error_case": pair_id in eligible_known,
        }
        for pair_id in sorted(errors)
    ]
    requirements = gate["quality_requirements"]
    quality_passed = (
        protocol_passed
        and correct >= requirements["signed_cases_correct_min"]
        and known_correct >= requirements["known_error_cases_correct_min"]
        and len(regressions) <= requirements["previously_correct_regressions_max"]
        and target_matched >= requirements["target_relations_matched_min"]
        and len(stable_regressions) <= requirements["supports_conditions_regressions_max"]
    )

    protocol = {
        "schema_version": "issue25-boolean-live-protocol-audit-1",
        "created_on": "2026-10-10",
        "batch_id": batch["batch_id"],
        "plan_sha256": batch["plan_sha256"],
        "protocol": "material-relations-question-group-jsonl-v2",
        "model_requests_during_audit": 0,
        "attempt_status": dict(Counter(row["execution_status"] for row in attempts)),
        "packet_status": {
            status: packet_status.get(status, 0)
            for status in ("completed", "partial", "failed", "deferred")
        },
        "totals": dict(totals),
        "usage": usage,
        "visible_content_chars": sum(row["content_chars"] for row in response_audit),
        "visible_nonempty_lines": sum(row["nonempty_lines"] for row in response_audit),
        "retained_relations": len(payload.get("understanding", {}).get("relations", [])),
        "responses": response_audit,
        "protocol_passed": protocol_passed,
        "publication_query_delivery_context_use": 0,
    }
    score = {
        "schema_version": "issue25-signed-gold-v2-score-1",
        "created_on": "2026-10-10",
        "candidate_set_id": gate["candidate_set_id"],
        "gold_v2_sha256": gate["gold_v2_sha256"],
        "signed_cases": {
            "correct": correct,
            "total": len(truth),
            "minimum": requirements["signed_cases_correct_min"],
            "errors": sorted(errors),
        },
        "known_error_cases": {
            "correct": known_correct,
            "total": len(eligible_known),
            "minimum": requirements["known_error_cases_correct_min"],
        },
        "previously_correct_cases": {
            "regressions": len(regressions),
            "total": len(prior_correct_ids),
            "maximum": requirements["previously_correct_regressions_max"],
            "regression_ids": sorted(regressions),
        },
        "supports_conditions_regressions": {
            "count": len(stable_regressions),
            "maximum": requirements["supports_conditions_regressions_max"],
            "candidate_pair_ids": sorted(stable_regressions),
        },
        "target_relations": {
            "matched": target_matched,
            "total": len(target_results),
            "minimum": requirements["target_relations_matched_min"],
            "results": target_results,
        },
        "quality_passed": quality_passed,
        "whole_document_precision_measured": False,
        "misclassified_cases": misclassified_cases,
    }
    execution = {
        "schema_version": "issue25-final-live-execution-summary-1",
        "created_on": "2026-10-10",
        "batch_id": batch["batch_id"],
        "model": "doubao-seed-2.1-lite",
        "response_models": sorted(
            {row["response_model"] for row in response_audit if row["response_model"]}
        ),
        "model_calls": len(attempts),
        "automatic_retries": 0,
        "claims_calls": 0,
        "items_calls": 0,
        "relation_calls": len(attempts),
        "attempt_status": protocol["attempt_status"],
        "usage": usage,
        "protocol_passed": protocol_passed,
        "quality_passed": quality_passed,
        "publication_query_delivery_context_use": 0,
    }
    decision = {
        "schema_version": "issue25-final-live-decision-1",
        "created_on": "2026-10-10",
        "status": "passed_close_relation_extractor_repair"
        if quality_passed
        else "failed_close_route",
        "protocol_passed": protocol_passed,
        "quality_passed": quality_passed,
        "additional_extraction_calls_allowed": False,
        "publication_authorized": False,
        "decision": gate["terminal_decision"]["on_pass" if quality_passed else "on_fail"],
    }
    _write("raw-response-audit.json", raw_responses)
    _write("protocol-audit.json", protocol)
    _write("signed-gold-v2-score.json", score)
    _write("execution-summary.json", execution)
    _write("final-decision.json", decision)
    print(
        json.dumps(
            {
                "protocol_passed": protocol_passed,
                "packet_status": protocol["packet_status"],
                "totals": protocol["totals"],
                "signed_cases": score["signed_cases"],
                "known_error_cases": score["known_error_cases"],
                "previously_correct_cases": score["previously_correct_cases"],
                "supports_conditions_regressions": score["supports_conditions_regressions"],
                "target_relations": score["target_relations"],
                "quality_passed": quality_passed,
                "usage": usage,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
