"""Audit the immutable Issue 22 store without making model requests."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
STORE = HERE / "live-store-256k-minimal"
EXPECTED_BATCH_ID = (
    "batch:60e684c035b5006cfbe1b68b6fd18ca88a70c41dfc9defd8d93ee2e61ab7e9d7"
)
_ANSWER_FIELDS = {"record_type", "question_index", "selected_answer_indices"}
_RELATION_FIELDS = {"record_type", "relation_index", "status", "evidence_selector"}


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


def _diagnose_lines(content: str) -> list[dict[str, Any]]:
    invalid: list[dict[str, Any]] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            continue
        reasons: list[str] = []
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            invalid.append(
                {
                    "line_number": line_number,
                    "reasons": ["invalid_json"],
                    "json_error": exc.msg,
                    "line_prefix": line[:240],
                }
            )
            continue
        if not isinstance(record, dict):
            reasons.append("not_object")
            keys: list[str] = []
            record_type = None
        else:
            keys = sorted(str(key) for key in record)
            record_type = record.get("record_type")
            if record_type == "answer_group_result":
                if set(record) != _ANSWER_FIELDS:
                    reasons.append("unexpected_answer_fields")
                selected = record.get("selected_answer_indices")
                if not isinstance(selected, list):
                    reasons.append("selected_answers_not_list")
            elif record_type == "relation_result":
                if set(record) != _RELATION_FIELDS:
                    reasons.append("unexpected_relation_fields")
                status = record.get("status")
                selector = record.get("evidence_selector")
                if status not in {"present", "absent"}:
                    reasons.append("invalid_status")
                elif (status == "present" and selector != "pair_window") or (
                    status == "absent" and selector is not None
                ):
                    reasons.append("invalid_evidence_selector")
            else:
                reasons.append("unsupported_record_type")
        if reasons:
            invalid.append(
                {
                    "line_number": line_number,
                    "record_type": record_type,
                    "keys": keys,
                    "reasons": reasons,
                    "line_prefix": line[:240],
                }
            )
    return invalid


def main() -> None:
    database = STORE / "index" / "structured.sqlite3"
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    batch = dict(connection.execute("SELECT * FROM batches").fetchone())
    tasks = {
        row["role"]: dict(row)
        for row in connection.execute("SELECT * FROM tasks ORDER BY derived, task_id")
    }
    attempts = [
        dict(row)
        for row in connection.execute("SELECT * FROM attempts ORDER BY attempt_number")
    ]
    connection.close()
    if batch["batch_id"] != EXPECTED_BATCH_ID or batch["actual_attempts"] != 4:
        raise RuntimeError("Issue 22 frozen identity or attempt count changed")

    relation_task = tasks["material_relations"]
    relation_payload = _read_object(relation_task["payload_object_sha256"])
    packet_runs = relation_payload.get("packet_runs")
    if not isinstance(packet_runs, list) or len(packet_runs) != 4:
        raise RuntimeError("packet cardinality mismatch")

    response_rows: list[dict[str, Any]] = []
    raw_responses: list[dict[str, Any]] = []
    for attempt, packet in zip(attempts, packet_runs, strict=True):
        response = _read_object(attempt["response_object_sha256"])
        content = response.get("content")
        diagnostics = response.get("diagnostics")
        if not isinstance(content, str) or not isinstance(diagnostics, dict):
            raise RuntimeError("invalid stored response")
        nonempty_lines = [line for line in content.splitlines() if line.strip()]
        response_rows.append(
            {
                "attempt_number": attempt["attempt_number"],
                "attempt_id": attempt["attempt_id"],
                "packet_id": packet["packet_id"],
                "execution_status": attempt["execution_status"],
                "response_sha256": attempt["response_sha256"],
                "response_object_sha256": attempt["response_object_sha256"],
                "response_model": diagnostics.get("response_model"),
                "finish_reason": diagnostics.get("finish_reason"),
                "duration_ms": diagnostics.get("duration_ms"),
                "content_chars": len(content),
                "nonempty_lines": len(nonempty_lines),
                "prompt_tokens": diagnostics.get("prompt_tokens"),
                "completion_tokens": diagnostics.get("completion_tokens"),
                "reasoning_tokens": diagnostics.get("reasoning_tokens"),
                "reasoning_effort": diagnostics.get("reasoning_effort"),
                "packet_status": packet["status"],
                "packet_reasons": packet["reasons"],
                "packet_records": packet["records"],
                "packet_diagnostics": packet["diagnostics"],
                "strict_line_violations": _diagnose_lines(content),
            }
        )
        raw_responses.append(
            {
                "attempt_number": attempt["attempt_number"],
                "packet_id": packet["packet_id"],
                "content": content,
            }
        )

    usage_rows = [json.loads(attempt["usage"]) for attempt in attempts]
    usage = {
        key: sum((row.get(key) or 0) for row in usage_rows)
        for key in ("prompt_tokens", "completion_tokens", "reasoning_tokens", "total_tokens")
    }
    packet_status = Counter(packet["status"] for packet in packet_runs)
    summary = {
        "schema_version": "issue22-doubao-lite-protocol-audit-1",
        "audited_on": "2026-10-10",
        "batch_id": batch["batch_id"],
        "plan_sha256": batch["plan_sha256"],
        "model": "doubao-seed-2.1-lite",
        "max_output_tokens": 262144,
        "reasoning_effort": "minimal",
        "model_requests_during_audit": 0,
        "attempt_status": dict(Counter(row["execution_status"] for row in attempts)),
        "usage": usage,
        "packet_status": {
            status: packet_status.get(status, 0)
            for status in ("completed", "partial", "failed", "deferred")
        },
        "visible_content_chars": sum(row["content_chars"] for row in response_rows),
        "visible_nonempty_lines": sum(row["nonempty_lines"] for row in response_rows),
        "retained_relations": len(relation_payload.get("understanding", {}).get("relations", [])),
        "relation_task": {
            "execution_status": relation_task["execution_status"],
            "protocol_status": relation_task["protocol_status"],
            "quality_status": relation_task["quality_status"],
            "publication_status": relation_task["publication_status"],
            "error_codes": json.loads(relation_task["error_codes"]),
            "reason_codes": json.loads(relation_task["reason_codes"]),
        },
        "responses": response_rows,
        "publication_query_delivery_context_use": 0,
    }
    _write("protocol-audit.json", summary)
    _write("raw-response-audit.json", raw_responses)
    print(
        json.dumps(
            {
                "attempt_status": summary["attempt_status"],
                "usage": usage,
                "packet_status": summary["packet_status"],
                "visible_content_chars": summary["visible_content_chars"],
                "visible_nonempty_lines": summary["visible_nonempty_lines"],
                "retained_relations": summary["retained_relations"],
                "relation_task": summary["relation_task"],
                "packet_reasons": [row["packet_reasons"] for row in response_rows],
                "responses": [
                    {
                        "attempt_number": row["attempt_number"],
                        "packet_status": row["packet_status"],
                        "finish_reason": row["finish_reason"],
                        "content_chars": row["content_chars"],
                        "completion_tokens": row["completion_tokens"],
                        "packet_diagnostics": row["packet_diagnostics"],
                        "strict_line_violations": row["strict_line_violations"],
                    }
                    for row in response_rows
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
