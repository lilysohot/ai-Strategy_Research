"""Audit the immutable Issue 21 16K store without model requests."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
STORE = HERE / "live-store-16k"
EXPECTED_BATCH_ID = (
    "batch:c1cbc89331a8866beb28d62b33bff5ef1e5a2fb3c0bf6261a3c8f858f5d7f2e2"
)
EXPECTED_PLAN_SHA256 = (
    "sha256:c1cbc89331a8866beb28d62b33bff5ef1e5a2fb3c0bf6261a3c8f858f5d7f2e2"
)
EXPECTED_CANDIDATE_SET_ID = (
    "sha256:0e93746e5edf13547b7d149c90ebfa586ed48910707db5aceefac2379f100613"
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
        raise RuntimeError("Issue 21 batch identity changed")
    if batch["plan_sha256"] != EXPECTED_PLAN_SHA256:
        raise RuntimeError("Issue 21 plan identity changed")
    if batch["actual_attempts"] != 4 or len(attempts) != 4:
        raise RuntimeError("Issue 21 did not consume exactly four attempts")
    if [attempt["execution_status"] for attempt in attempts] != [
        "succeeded",
        "succeeded",
        "succeeded",
        "outcome_unknown",
    ]:
        raise RuntimeError("unexpected attempt terminal states")

    relation_task = tasks["material_relations"]
    relation_payload = _read_object(relation_task["payload_object_sha256"])
    packet_runs = relation_payload.get("packet_runs")
    if not isinstance(packet_runs, list) or len(packet_runs) != 4:
        raise RuntimeError("packet cardinality mismatch")

    responses: list[dict[str, Any]] = []
    for attempt, packet in zip(attempts, packet_runs, strict=True):
        response_object_sha256 = attempt["response_object_sha256"]
        if attempt["execution_status"] == "outcome_unknown":
            if response_object_sha256 is not None or attempt["response_sha256"] is not None:
                raise RuntimeError("unknown attempt unexpectedly has a response object")
            responses.append(
                {
                    "attempt_number": attempt["attempt_number"],
                    "attempt_id": attempt["attempt_id"],
                    "packet_id": packet["packet_id"],
                    "execution_status": "outcome_unknown",
                    "response_sha256": None,
                    "response_object_sha256": None,
                    "content_chars": None,
                    "parsed_records": None,
                    "finish_reason": None,
                    "duration_ms": packet["diagnostics"].get("duration_ms"),
                    "completion_tokens": None,
                    "reasoning_tokens": None,
                    "packet_status": packet["status"],
                    "packet_reasons": packet["reasons"],
                }
            )
            continue
        response = _read_object(str(response_object_sha256))
        content = response.get("content")
        diagnostics = response.get("diagnostics")
        if not isinstance(content, str) or not isinstance(diagnostics, dict):
            raise RuntimeError("invalid stored response")
        responses.append(
            {
                "attempt_number": attempt["attempt_number"],
                "attempt_id": attempt["attempt_id"],
                "packet_id": packet["packet_id"],
                "execution_status": attempt["execution_status"],
                "response_sha256": attempt["response_sha256"],
                "response_object_sha256": response_object_sha256,
                "content_chars": len(content),
                "parsed_records": len([line for line in content.splitlines() if line.strip()]),
                "finish_reason": diagnostics.get("finish_reason"),
                "duration_ms": diagnostics.get("duration_ms"),
                "completion_tokens": diagnostics.get("completion_tokens"),
                "reasoning_tokens": diagnostics.get("reasoning_tokens"),
                "packet_status": packet["status"],
                "packet_reasons": packet["reasons"],
            }
        )

    completed_responses = [
        row for row in responses if row["execution_status"] == "succeeded"
    ]
    if any(row["content_chars"] != 0 for row in completed_responses):
        raise RuntimeError("expected completed 16K responses to be empty")
    if any(row["finish_reason"] != "length" for row in completed_responses):
        raise RuntimeError("expected completed responses to stop on length")
    if any(row["completion_tokens"] != 16384 for row in completed_responses):
        raise RuntimeError("expected completed responses to exhaust 16K")

    known_usage_rows = [
        json.loads(attempt["usage"])
        for attempt in attempts
        if attempt["usage"] is not None
    ]
    usage = {
        key: sum((row.get(key) or 0) for row in known_usage_rows)
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "reasoning_tokens",
            "total_tokens",
        )
    }
    packet_status = Counter(packet["status"] for packet in packet_runs)
    protocol_audit = {
        "schema_version": "issue21-glm-16k-protocol-audit-1",
        "audited_on": "2026-10-10",
        "batch_id": batch["batch_id"],
        "plan_sha256": batch["plan_sha256"],
        "candidate_set_id": EXPECTED_CANDIDATE_SET_ID,
        "model_requests_during_audit": 0,
        "responses": responses,
        "completed_empty_responses": sum(
            row["execution_status"] == "succeeded" and row["content_chars"] == 0
            for row in responses
        ),
        "length_terminated_responses": sum(
            row["finish_reason"] == "length" for row in responses
        ),
        "outcome_unknown_responses": sum(
            row["execution_status"] == "outcome_unknown" for row in responses
        ),
        "diagnosis": (
            "raising max_output_tokens from 4096 to 16384 did not produce visible "
            "protocol content: three responses exhausted 16K in reasoning and the "
            "fourth crossed the 300-second boundary with unknown outcome"
        ),
        "normalization_or_replay_applied": False,
    }
    execution_summary = {
        "schema_version": "issue21-glm-16k-bounded-live-execution-1",
        "executed_on": "2026-10-10",
        "status": "outcome_unknown_and_output_completeness_failed_route_closed",
        "batch_id": batch["batch_id"],
        "plan_sha256": batch["plan_sha256"],
        "model": "glm-5.3-flash",
        "response_model": "glm-5-3-flash-260828",
        "max_output_tokens": 16384,
        "model_attempts": len(attempts),
        "attempt_status": dict(
            Counter(attempt["execution_status"] for attempt in attempts)
        ),
        "claims_attempts": 0,
        "items_attempts": 0,
        "relation_attempts": len(attempts),
        "automatic_retries": 0,
        "known_usage_excludes_unknown_attempt": usage,
        "cost": None,
        "cost_status": "unavailable_not_zero_and_unknown_attempt_may_have_consumed",
        "relation_task": {
            "task_id": relation_task["task_id"],
            "execution_status": relation_task["execution_status"],
            "protocol_status": relation_task["protocol_status"],
            "quality_status": relation_task["quality_status"],
            "publication_status": relation_task["publication_status"],
            "error_codes": json.loads(relation_task["error_codes"]),
            "artifact_sha256": relation_task["artifact_sha256"],
            "payload_sha256": relation_task["payload_sha256"],
        },
        "packet_status": {
            status: packet_status.get(status, 0)
            for status in ("completed", "partial", "failed", "deferred")
        },
        "candidate_set_id": EXPECTED_CANDIDATE_SET_ID,
        "retained_relations": len(
            relation_payload.get("understanding", {}).get("relations", [])
        ),
        "visible_protocol_records": sum(
            row["parsed_records"] or 0 for row in responses
        ),
        "publication_query_delivery_context_use": 0,
    }
    final_decision = {
        "schema_version": "issue21-glm-16k-final-gate-decision-1",
        "decided_on": "2026-10-10",
        "status": "failed_glm_16k_compatibility_route_closed",
        "batch_id": batch["batch_id"],
        "gate": {
            "relation_packets_completed": {
                "required": 4,
                "actual": packet_status.get("completed", 0),
                "passed": False,
            },
            "failed_packets": {
                "maximum": 0,
                "actual": packet_status.get("failed", 0),
                "passed": False,
            },
            "signed_44": "not_scored_because_output_completeness_failed",
            "known_error_9": "not_scored_because_output_completeness_failed",
            "previously_correct_35": "not_scored_because_output_completeness_failed",
            "target_relations_4": "not_scored_because_output_completeness_failed",
        },
        "root_cause": {
            "class": "reasoning_consumed_expanded_output_budget",
            "secondary_class": "final_attempt_outcome_unknown_at_timeout",
            "successful_transport_attempts": 3,
            "outcome_unknown_attempts": 1,
            "completed_empty_responses": 3,
            "finish_reason_length": 3,
            "completion_token_limit_each": 16384,
            "known_reasoning_tokens": usage["reasoning_tokens"],
            "semantic_quality_determined": False,
        },
        "terminal_policy": {
            "automatic_or_manual_retry_allowed": False,
            "additional_model_calls_allowed": False,
            "publication_authorized": False,
            "query_delivery_context_use_authorized": False,
            "next_state": (
                "close 16K route; do not increase token budget again. A future route "
                "must control or disable reasoning, or use a model with visible-output guarantees"
            ),
        },
    }
    _write("protocol-audit.json", protocol_audit)
    _write("execution-summary.json", execution_summary)
    _write("final-decision.json", final_decision)
    print(
        json.dumps(
            {
                "attempt_status": execution_summary["attempt_status"],
                "known_usage": usage,
                "packet_status": execution_summary["packet_status"],
                "visible_protocol_records": 0,
                "final_status": final_decision["status"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
