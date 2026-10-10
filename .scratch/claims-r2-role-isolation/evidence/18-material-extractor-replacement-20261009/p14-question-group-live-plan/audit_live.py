"""Audit the immutable P14 live store without making model requests."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
STORE = HERE / "live-store"
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


def _read_object(object_sha256: str) -> dict[str, Any]:
    digest = object_sha256.removeprefix("sha256:")
    path = STORE / "objects" / "sha256" / digest[:2] / f"{digest}.json"
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise RuntimeError(f"object hash mismatch: {object_sha256}")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError(f"object is not a mapping: {object_sha256}")
    return value


def _write(name: str, value: object) -> None:
    (HERE / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _is_valid_answer(row: dict[str, Any]) -> bool:
    question_index = row.get("question_index")
    selected = row.get("selected_answer_indices")
    return bool(
        set(row) == ANSWER_FIELDS
        and type(question_index) is int
        and question_index >= 0
        and isinstance(selected, list)
        and all(type(index) is int and index >= 0 for index in selected)
        and len(selected) == len(set(selected))
    )


def _relation_error(row: dict[str, Any]) -> str | None:
    if set(row) != RELATION_FIELDS:
        return "unexpected_fields"
    status = row.get("status")
    selector = row.get("evidence_selector")
    if status not in {"present", "absent"}:
        return "invalid_status"
    if status == "present" and selector != "pair_window":
        return "invalid_evidence_selector"
    if status == "absent" and selector is not None:
        return "invalid_evidence_selector"
    return None


def main() -> None:
    database = STORE / "index" / "structured.sqlite3"
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    batch = dict(connection.execute("SELECT * FROM batches").fetchone())
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
        raise RuntimeError("P14 batch identity changed")
    if batch["plan_sha256"] != EXPECTED_PLAN_SHA256:
        raise RuntimeError("P14 plan identity changed")
    if batch["actual_attempts"] != 4 or len(attempts) != 4:
        raise RuntimeError("P14 did not consume exactly the frozen four-call budget")

    relation_task = tasks["material_relations"]
    relation_payload = _read_object(relation_task["payload_object_sha256"])
    packet_runs = relation_payload.get("packet_runs")
    if not isinstance(packet_runs, list) or len(packet_runs) != len(attempts):
        raise RuntimeError("P14 packet/attempt cardinality mismatch")

    invalid_rows: list[dict[str, Any]] = []
    response_records: list[dict[str, Any]] = []
    for attempt, packet in zip(attempts, packet_runs, strict=True):
        response = _read_object(attempt["response_object_sha256"])
        content = response.get("content")
        if not isinstance(content, str):
            raise RuntimeError("model response content is not text")
        parsed_records = 0
        for line_number, line in enumerate(content.splitlines(), start=1):
            if not line.strip():
                continue
            parsed_records += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                invalid_rows.append(
                    {
                        "attempt_number": attempt["attempt_number"],
                        "packet_id": packet["packet_id"],
                        "line_number": line_number,
                        "record_type": None,
                        "error": "invalid_json",
                    }
                )
                continue
            if not isinstance(row, dict):
                invalid_rows.append(
                    {
                        "attempt_number": attempt["attempt_number"],
                        "packet_id": packet["packet_id"],
                        "line_number": line_number,
                        "record_type": None,
                        "error": "record_not_object",
                    }
                )
                continue
            record_type = row.get("record_type")
            error: str | None = None
            if record_type == "answer_group_result":
                if not _is_valid_answer(row):
                    error = "invalid_answer_group_result"
            elif record_type == "relation_result":
                error = _relation_error(row)
            else:
                error = "unsupported_record_type"
            if error is not None:
                invalid_rows.append(
                    {
                        "attempt_number": attempt["attempt_number"],
                        "packet_id": packet["packet_id"],
                        "line_number": line_number,
                        "record_type": record_type,
                        "relation_index": row.get("relation_index"),
                        "returned_status": row.get("status"),
                        "error": error,
                    }
                )
        response_records.append(
            {
                "attempt_number": attempt["attempt_number"],
                "attempt_id": attempt["attempt_id"],
                "packet_id": packet["packet_id"],
                "execution_status": attempt["execution_status"],
                "response_sha256": attempt["response_sha256"],
                "response_object_sha256": attempt["response_object_sha256"],
                "records": parsed_records,
                "invalid_records": sum(
                    row["attempt_number"] == attempt["attempt_number"]
                    for row in invalid_rows
                ),
                "packet_status": packet["status"],
                "packet_reasons": packet["reasons"],
            }
        )

    usage_rows = [json.loads(attempt["usage"]) for attempt in attempts]
    usage = {
        key: sum((row.get(key) or 0) for row in usage_rows)
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "reasoning_tokens",
            "total_tokens",
        )
    }
    packet_status = Counter(packet["status"] for packet in packet_runs)
    invalid_statuses = Counter(
        str(row["returned_status"])
        for row in invalid_rows
        if row["error"] == "invalid_status"
    )
    protocol_audit = {
        "schema_version": "p14-question-group-protocol-audit-1",
        "audited_on": "2026-10-10",
        "batch_id": batch["batch_id"],
        "plan_sha256": batch["plan_sha256"],
        "model_requests_during_audit": 0,
        "responses": response_records,
        "invalid_records": invalid_rows,
        "invalid_record_count": len(invalid_rows),
        "invalid_status_counts": dict(sorted(invalid_statuses.items())),
        "diagnosis": (
            "attempts 2 and 3 returned relation types in the status field; the frozen "
            "contract permits only present or absent, so strict rejection is correct"
        ),
        "normalization_or_replay_applied": False,
    }
    execution_summary = {
        "schema_version": "p14-question-group-live-execution-1",
        "executed_on": "2026-10-10",
        "status": "failed_final_gate_current_route_closed",
        "batch_id": batch["batch_id"],
        "plan_sha256": batch["plan_sha256"],
        "model_calls": len(attempts),
        "attempt_status": dict(
            Counter(attempt["execution_status"] for attempt in attempts)
        ),
        "claims_attempts": 0,
        "items_attempts": 0,
        "relation_attempts": len(attempts),
        "automatic_retries": 0,
        "usage": usage,
        "cost": None,
        "cost_status": "unavailable_not_zero",
        "relation_task": {
            "task_id": relation_task["task_id"],
            "execution_status": relation_task["execution_status"],
            "protocol_status": relation_task["protocol_status"],
            "quality_status": relation_task["quality_status"],
            "publication_status": relation_task["publication_status"],
            "reason_codes": json.loads(relation_task["reason_codes"]),
            "artifact_sha256": relation_task["artifact_sha256"],
            "payload_sha256": relation_task["payload_sha256"],
        },
        "packet_status": {
            status: packet_status.get(status, 0)
            for status in ("completed", "partial", "failed", "deferred")
        },
        "candidate_set_id": relation_payload.get("relation_candidate_set_id"),
        "retained_relations_from_completed_packets": len(
            relation_payload.get("understanding", {}).get("relations", [])
        ),
        "invalid_terminal_records": len(invalid_rows),
        "publication_query_delivery_context_use": 0,
    }
    final_decision = {
        "schema_version": "p14-final-gate-decision-1",
        "decided_on": "2026-10-10",
        "status": "failed_current_model_plus_extractor_route_rejected",
        "batch_id": batch["batch_id"],
        "gate": {
            "relation_packets_completed": {
                "required": 4,
                "actual": packet_status.get("completed", 0),
                "passed": packet_status.get("completed", 0) == 4,
            },
            "partial_packets": {
                "maximum": 0,
                "actual": packet_status.get("partial", 0),
                "passed": packet_status.get("partial", 0) == 0,
            },
            "failed_packets": {
                "maximum": 0,
                "actual": packet_status.get("failed", 0),
                "passed": packet_status.get("failed", 0) == 0,
            },
            "signed_44": "not_scored_because_protocol_completeness_failed",
            "known_error_9": "not_scored_because_protocol_completeness_failed",
            "previously_correct_35": "not_scored_because_protocol_completeness_failed",
            "target_relations_4": "not_scored_because_protocol_completeness_failed",
        },
        "root_cause": {
            "class": "model_response_contract_violation",
            "invalid_terminal_records": len(invalid_rows),
            "returned_relation_types_as_status": dict(sorted(invalid_statuses.items())),
            "controller_index_or_transport_failure": False,
        },
        "terminal_policy": {
            "p15_allowed": False,
            "prompt_revision_or_schema_relaxation_in_current_task_allowed": False,
            "additional_model_calls_allowed": False,
            "publication_authorized": False,
            "query_delivery_context_use_authorized": False,
            "next_state": (
                "close current model plus extractor route; any replacement is a new task"
            ),
        },
    }
    _write("protocol-audit.json", protocol_audit)
    _write("execution-summary.json", execution_summary)
    _write("final-decision.json", final_decision)
    print(
        json.dumps(
            {
                "model_calls": len(attempts),
                "usage": usage,
                "packet_status": execution_summary["packet_status"],
                "invalid_terminal_records": len(invalid_rows),
                "invalid_status_counts": dict(sorted(invalid_statuses.items())),
                "final_status": final_decision["status"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
