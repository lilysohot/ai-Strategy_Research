"""Audit the immutable Issue 20 GLM live store without model requests."""

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
    "batch:5c0a6386599b91e18bcfc62ea5a5d45a23e367eff62d99e2649f6fa7485efeb9"
)
EXPECTED_PLAN_SHA256 = (
    "sha256:5c0a6386599b91e18bcfc62ea5a5d45a23e367eff62d99e2649f6fa7485efeb9"
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
        raise RuntimeError("Issue 20 batch identity changed")
    if batch["plan_sha256"] != EXPECTED_PLAN_SHA256:
        raise RuntimeError("Issue 20 plan identity changed")
    if batch["actual_attempts"] != 4 or len(attempts) != 4:
        raise RuntimeError("Issue 20 did not consume exactly four calls")
    if any(attempt["execution_status"] != "succeeded" for attempt in attempts):
        raise RuntimeError("Issue 20 has a non-success transport attempt")

    relation_task = tasks["material_relations"]
    relation_payload = _read_object(relation_task["payload_object_sha256"])
    packet_runs = relation_payload.get("packet_runs")
    if not isinstance(packet_runs, list) or len(packet_runs) != len(attempts):
        raise RuntimeError("packet/attempt cardinality mismatch")

    responses: list[dict[str, Any]] = []
    for attempt, packet in zip(attempts, packet_runs, strict=True):
        response = _read_object(attempt["response_object_sha256"])
        content = response.get("content")
        diagnostics = response.get("diagnostics")
        if not isinstance(content, str) or not isinstance(diagnostics, dict):
            raise RuntimeError("invalid stored model response")
        if diagnostics.get("model") != "glm-5.3-flash":
            raise RuntimeError("unexpected response model")
        responses.append(
            {
                "attempt_number": attempt["attempt_number"],
                "attempt_id": attempt["attempt_id"],
                "packet_id": packet["packet_id"],
                "execution_status": attempt["execution_status"],
                "response_sha256": attempt["response_sha256"],
                "response_object_sha256": attempt["response_object_sha256"],
                "content_chars": len(content),
                "parsed_records": len([line for line in content.splitlines() if line.strip()]),
                "finish_reason": diagnostics.get("finish_reason"),
                "response_model": diagnostics.get("response_model"),
                "prompt_tokens": diagnostics.get("prompt_tokens"),
                "completion_tokens": diagnostics.get("completion_tokens"),
                "reasoning_tokens": diagnostics.get("reasoning_tokens"),
                "total_tokens": diagnostics.get("total_tokens"),
                "packet_status": packet["status"],
                "packet_reasons": packet["reasons"],
            }
        )

    if any(row["content_chars"] != 0 for row in responses):
        raise RuntimeError("expected all four frozen responses to be empty")
    if any(row["finish_reason"] != "length" for row in responses):
        raise RuntimeError("expected all four responses to stop on length")
    if any(row["completion_tokens"] != 4096 for row in responses):
        raise RuntimeError("expected all four responses to exhaust output budget")

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
    response_hashes = Counter(attempt["response_sha256"] for attempt in attempts)
    protocol_audit = {
        "schema_version": "issue20-glm-question-group-protocol-audit-1",
        "audited_on": "2026-10-10",
        "batch_id": batch["batch_id"],
        "plan_sha256": batch["plan_sha256"],
        "candidate_set_id": EXPECTED_CANDIDATE_SET_ID,
        "model_requests_during_audit": 0,
        "responses": responses,
        "distinct_visible_response_hashes": len(response_hashes),
        "empty_responses": sum(row["content_chars"] == 0 for row in responses),
        "length_terminated_responses": sum(
            row["finish_reason"] == "length" for row in responses
        ),
        "diagnosis": (
            "all four successful HTTP/model attempts exhausted the frozen 4096-token "
            "completion budget in reasoning and returned zero visible protocol content"
        ),
        "normalization_or_replay_applied": False,
    }
    execution_summary = {
        "schema_version": "issue20-glm-bounded-live-execution-1",
        "executed_on": "2026-10-10",
        "status": "failed_output_completeness_model_route_closed",
        "batch_id": batch["batch_id"],
        "plan_sha256": batch["plan_sha256"],
        "model": "glm-5.3-flash",
        "response_model": "glm-5-3-flash-260828",
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
        "candidate_set_id": EXPECTED_CANDIDATE_SET_ID,
        "retained_relations": len(
            relation_payload.get("understanding", {}).get("relations", [])
        ),
        "visible_protocol_records": sum(row["parsed_records"] for row in responses),
        "publication_query_delivery_context_use": 0,
    }
    final_decision = {
        "schema_version": "issue20-glm-final-gate-decision-1",
        "decided_on": "2026-10-10",
        "status": "failed_glm_5_3_flash_plus_frozen_extractor_rejected",
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
            "signed_44": "not_scored_because_output_completeness_failed",
            "known_error_9": "not_scored_because_output_completeness_failed",
            "previously_correct_35": "not_scored_because_output_completeness_failed",
            "target_relations_4": "not_scored_because_output_completeness_failed",
        },
        "root_cause": {
            "class": "model_output_budget_exhausted_before_visible_protocol_content",
            "http_or_transport_failure": False,
            "controller_index_failure": False,
            "successful_attempts": 4,
            "empty_visible_responses": 4,
            "finish_reason_length": 4,
            "completion_token_limit_each": 4096,
            "reasoning_tokens_total": usage["reasoning_tokens"],
            "semantic_quality_determined": False,
        },
        "terminal_policy": {
            "additional_model_calls_allowed": False,
            "request_option_or_prompt_change_in_current_task_allowed": False,
            "publication_authorized": False,
            "query_delivery_context_use_authorized": False,
            "next_state": (
                "close glm-5.3-flash plus frozen extractor; any compatibility "
                "experiment requires a separately frozen task"
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
                "empty_responses": protocol_audit["empty_responses"],
                "final_status": final_decision["status"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
