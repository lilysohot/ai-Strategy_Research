"""Replay P1R1 industrial responses, then execute only the frozen P1R2 optical arm."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

from plugins.corpus.structured.config import RequestOptions, load_extraction_config
from plugins.corpus.structured.ledger import (
    BatchCheck,
    BatchPlan,
    ReplayResponse,
    execute_batch,
    replay_batch,
)

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
FREEZE = HERE / "p1r2-claims-plan-freeze"
P1R1_STORE = HERE / "p1r-claims-plan-freeze/claims-industrial-fulian/live-store"
ORDER = ("claims-industrial-fulian", "claims-optical-module")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_plan(name: str, entry: dict[str, object]) -> BatchPlan:
    path = FREEZE / name / "plan.json"
    if sha256(path) != entry["plan_file_sha256"]:
        raise SystemExit(f"plan file hash drifted: {name}")
    plan = BatchPlan.model_validate_json(path.read_text(encoding="utf-8"))
    plan.verify_identity()
    return plan


def prepare_industrial_replay(plan: BatchPlan) -> Path:
    target = FREEZE / ORDER[0] / "replay-responses"
    if target.exists():
        return target
    target.mkdir(parents=True)
    task = next(task for task in plan.tasks if task.role == "claims")
    connection = sqlite3.connect(P1R1_STORE / "index/structured.sqlite3")
    connection.row_factory = sqlite3.Row
    try:
        attempts = connection.execute(
            "SELECT * FROM attempts ORDER BY attempt_number"
        ).fetchall()
    finally:
        connection.close()
    for attempt in attempts:
        digest = str(attempt["response_object_sha256"]).removeprefix("sha256:")
        response_path = (
            P1R1_STORE / "objects/sha256" / digest[:2] / f"{digest}.json"
        )
        response = json.loads(response_path.read_text(encoding="utf-8"))
        value = ReplayResponse(
            task_id=task.task_id,
            sequence=int(attempt["attempt_number"]),
            role="claims",
            protocol=task.protocol,
            content=response["content"],
            diagnostics={
                "source": "p1r1_immutable_response_object",
                "source_response_object_sha256": attempt["response_object_sha256"],
                "execution_status": "succeeded",
                "provider": "replay",
                "model": "p1r1-response-replay",
            },
        )
        (target / f"{value.sequence:02d}.json").write_text(
            value.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
    return target


def summarize(name: str, plan: BatchPlan, checked: BatchCheck, mode: str) -> dict[str, object]:
    tasks = [task for task in checked.ledger.tasks if task.role == "claims"]
    task_ids = {task.task_id for task in tasks}
    attempts = [attempt for attempt in checked.ledger.attempts if attempt.task_id in task_ids]
    live_calls = sum(attempt.provider != "replay" for attempt in attempts)
    return {
        "name": name,
        "execution_mode": mode,
        "batch_id": plan.batch_id,
        "plan_sha256": plan.plan_sha256,
        "attempt_ceiling": plan.role_max_attempts["claims"],
        "ledger_attempts": len(attempts),
        "new_model_calls": live_calls,
        "attempt_status": dict(Counter(a.execution_status for a in attempts)),
        "task_status": dict(Counter(task.execution_status for task in tasks)),
        "protocol_status": dict(Counter(task.protocol_status for task in tasks)),
        "quality_status": dict(Counter(task.quality_status for task in tasks)),
        "publication_status": dict(Counter(task.publication_status for task in tasks)),
        "findings": list(checked.findings),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-model", action="store_true")
    args = parser.parse_args()
    if not args.allow_model:
        raise SystemExit("refusing optical model execution without --allow-model")
    output = FREEZE / "execution-summary.json"
    if output.exists():
        raise SystemExit("refusing to overwrite the P1R2 execution summary")
    manifest_path = FREEZE / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_name = {entry["name"]: entry for entry in manifest["entries"]}
    config = load_extraction_config(
        dotenv_path=REPO / ".env",
        options=RequestOptions(max_output_tokens=16_384),
    )
    if config.require_profile().fingerprint != manifest["profile"]["profile_sha256"]:
        raise SystemExit("configured profile does not match the frozen plan")

    results = []
    industrial = load_plan(ORDER[0], by_name[ORDER[0]])
    replay = prepare_industrial_replay(industrial)
    checked = replay_batch(
        industrial,
        responses=replay,
        store_root=FREEZE / ORDER[0] / "replay-store",
    )
    results.append(summarize(ORDER[0], industrial, checked, "replay_p1r1_responses"))
    print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    if any(
        task.execution_status != "succeeded" or task.protocol_status != "valid"
        for task in checked.ledger.tasks
        if task.role == "claims"
    ):
        raise SystemExit("industrial replay failed; optical remains blocked")

    optical = load_plan(ORDER[1], by_name[ORDER[1]])
    checked = execute_batch(
        optical,
        store_root=FREEZE / ORDER[1] / "live-store",
        allow_model=True,
        config=config,
    )
    results.append(summarize(ORDER[1], optical, checked, "live_model"))
    print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    summary = {
        "schema_version": "structured-extraction-p1r2-claims-execution-1",
        "executed_on": "2026-10-09",
        "plan_manifest_sha256": sha256(manifest_path),
        "new_model_calls": sum(int(result["new_model_calls"]) for result in results),
        "replayed_attempts": int(results[0]["ledger_attempts"]),
        "automatic_retries": 0,
        "production_database_access": 0,
        "publication_writes": 0,
        "copper_executed": False,
        "results": results,
        "next_action": "evaluate the frozen Claims gate before any copper or publication work",
    }
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
