"""Fail-closed P1 Claims gate using mandatory-field recall upper bounds."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from plugins.corpus.structured.ledger import BatchPlan, check_batch

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
FREEZE = HERE / "p1-plan-freeze"
GOLD = HERE.parent / "10-quality-gold-freeze-20261008-r2" / "frozen-gold.json"
SIGNED = (
    HERE.parent
    / "11-live-20261008-non-table-gold-r2"
    / "candidate-adjudications.signed.json"
)
RESULT = HERE / "p1-claims-gate-result.json"
RUNS = ("claims-industrial-fulian", "claims-optical-module")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def payload(root: Path) -> tuple[str, dict[str, Any]]:
    connection = sqlite3.connect(root / "index/structured.sqlite3")
    try:
        row = connection.execute(
            "SELECT payload_object_sha256 FROM tasks WHERE role='claims'"
        ).fetchone()
    finally:
        connection.close()
    if row is None or not row[0]:
        raise ValueError("claims payload is missing")
    digest = str(row[0]).removeprefix("sha256:")
    path = root / "objects" / "sha256" / digest[:2] / f"{digest}.json"
    return "sha256:" + digest, json.loads(path.read_text(encoding="utf-8"))


def candidates_for_quote(facts: list[dict[str, Any]], quote: str) -> list[dict[str, Any]]:
    needle = compact(quote)
    matches = []
    for fact in facts:
        claim = fact["claim"]
        alignment = fact.get("evidence_alignment") or {}
        observed = compact(alignment.get("source_quote") or claim.get("evidence_quote"))
        if observed and (needle in observed or observed in needle):
            matches.append(fact)
    return matches


def observed(fact: dict[str, Any]) -> dict[str, Any]:
    claim = fact["claim"]
    alignment = fact.get("evidence_alignment") or {}
    return {
        "candidate_id": fact["fact_id"],
        "quote": alignment.get("source_quote") or claim.get("evidence_quote"),
        "subject": claim.get("subject"),
        "metric": claim.get("metric"),
        "metric_id": fact.get("metric_id"),
        "period_raw": claim.get("period_raw"),
        "period_end": claim.get("period_end"),
        "value_num": claim.get("value_num"),
        "value_text": claim.get("value_text"),
        "unit": claim.get("unit"),
        "kind": claim.get("kind"),
        "quality_status": claim.get("quality_status"),
        "reason_codes": fact.get("reasons", []),
    }


def main() -> None:
    if RESULT.exists():
        raise SystemExit("refusing to overwrite the Claims gate result")
    executions = []
    facts: list[dict[str, Any]] = []
    model_calls = 0
    for name in RUNS:
        target = FREEZE / name
        plan = BatchPlan.model_validate_json((target / "plan.json").read_text(encoding="utf-8"))
        plan.verify_identity()
        check = check_batch(plan.batch_id, store_root=target / "live-store")
        if not check.plan_consistent or check.findings:
            raise ValueError(f"ledger check failed: {name}: {check.findings}")
        statuses = Counter(attempt.execution_status for attempt in check.ledger.attempts)
        if set(statuses) != {"succeeded"}:
            raise ValueError(f"non-success attempt: {name}: {statuses}")
        object_sha256, value = payload(target / "live-store")
        facts.extend(value["facts"])
        actual = check.ledger.budget.actual_attempts
        model_calls += actual
        executions.append(
            {
                "name": name,
                "batch_id": plan.batch_id,
                "plan_sha256": plan.plan_sha256,
                "attempt_ceiling": plan.max_attempts,
                "actual_attempts": actual,
                "attempt_status": dict(statuses),
                "plan_consistent": check.plan_consistent,
                "findings": list(check.findings),
                "task_status": check.ledger.tasks[0].execution_status,
                "protocol_status": check.ledger.tasks[0].protocol_status,
                "quality_status": check.ledger.tasks[0].quality_status,
                "context_status": check.ledger.tasks[0].context_status,
                "payload_object_sha256": object_sha256,
                "candidate_count": len(value["facts"]),
                "packet_status": dict(Counter(item["status"] for item in value["packet_runs"])),
            }
        )
    gold_payload = json.loads(GOLD.read_text(encoding="utf-8"))
    gold = {
        record["record_id"]: record
        for record in gold_payload["records"]
        if record["role"] == "claims"
    }
    blockers: list[dict[str, Any]] = []
    required_absences = {
        "NT-C11": "metric_missing_and_period_unresolved",
        "NT-C12": "metric_missing_and_period_unresolved",
        "NT-C13": "metric_missing_and_period_unresolved",
        "NT-C15": "metric_value_and_unit_missing",
        "NT-C17": "period_missing",
        "NT-C20": "unit_and_period_invalid",
    }
    for record_id, reason in required_absences.items():
        matches = candidates_for_quote(facts, gold[record_id]["quote"])
        if len(matches) != 1:
            raise ValueError(f"unexpected candidate count for {record_id}: {len(matches)}")
        candidate = observed(matches[0])
        if record_id in {"NT-C11", "NT-C12", "NT-C13"} and candidate["metric"] is not None:
            raise ValueError(f"expected missing metric: {record_id}")
        if record_id == "NT-C15" and any(
            candidate[field] is not None for field in ("metric", "value_num", "value_text", "unit")
        ):
            raise ValueError("expected missing categorical coordinate: NT-C15")
        if record_id == "NT-C17" and any(
            candidate[field] is not None for field in ("period_raw", "period_end")
        ):
            raise ValueError("expected missing period: NT-C17")
        if record_id == "NT-C20" and candidate["unit"] == gold[record_id]["semantic_fields"]["unit"]:
            raise ValueError("expected invalid unit: NT-C20")
        blockers.append(
            {
                "record_id": record_id,
                "reason": reason,
                "required_fields": gold[record_id]["semantic_fields"],
                "observed_candidate": candidate,
            }
        )
    missing = candidates_for_quote(facts, gold["NT-C14"]["quote"])
    if missing:
        raise ValueError("NT-C14 unexpectedly has a candidate")
    blockers.append(
        {
            "record_id": "NT-C14",
            "reason": "target_not_recalled",
            "required_fields": gold["NT-C14"]["semantic_fields"],
            "observed_candidate": None,
        }
    )
    total = len(gold)
    upper_numerator = total - len(blockers)
    upper_recall = upper_numerator / total
    floor = 0.75
    if upper_recall >= floor:
        raise ValueError("Claims recall upper bound no longer proves an early stop")
    result = {
        "schema_version": "structured-extraction-p1-claims-gate-result-1",
        "status": "failed_recall_upper_bound",
        "evaluated_on": "2026-10-09",
        "model_calls": model_calls,
        "automatic_retries": 0,
        "production_database_access": 0,
        "publication_writes": 0,
        "executions": executions,
        "candidate_count": len(facts),
        "gate": {
            "baseline_recall_floor": floor,
            "gold_target_count": total,
            "mandatory_field_or_missing_blockers": len(blockers),
            "maximum_possible_matched_targets": upper_numerator,
            "target_recall_upper_bound": upper_recall,
            "candidate_precision": None,
            "candidate_precision_reason": (
                "not adjudicated because the recall upper bound already fails the frozen floor"
            ),
            "passed": False,
        },
        "blockers": sorted(blockers, key=lambda item: item["record_id"]),
        "decision": {
            "authorize_copper_execution": False,
            "authorize_publication": False,
            "next_action": (
                "preserve the structured snapshot/ledger/role interfaces and replace the current "
                "Claims extractor binding implementation; do not start another prompt/lexicon round"
            ),
        },
        "evidence": {
            "plan_freeze_manifest_sha256": sha256(FREEZE / "manifest.json"),
            "frozen_gold_sha256": sha256(GOLD),
            "signed_baseline_sha256": sha256(SIGNED),
            "evaluator_sha256": sha256(Path(__file__)),
        },
    }
    with RESULT.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
