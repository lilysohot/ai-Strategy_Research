"""Execute the frozen P1R3 replay arms, then the two-unit live routing delta."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import cast

from plugins.corpus.structured.config import RequestOptions, load_extraction_config
from plugins.corpus.structured.ledger import BatchCheck, BatchPlan, execute_batch, replay_batch

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
FREEZE = HERE / "p1r3-claims-plan-freeze"
ORDER = (
    "replay-claims-industrial-fulian",
    "replay-claims-optical-module",
    "live-claims-optical-routing-delta",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_plan(name: str, entry: dict[str, object]) -> BatchPlan:
    path = FREEZE / name / "plan.json"
    if sha256(path) != entry["plan_file_sha256"]:
        raise SystemExit(f"plan file hash drifted: {name}")
    plan = BatchPlan.model_validate_json(path.read_text(encoding="utf-8"))
    plan.verify_identity()
    return plan


def summarize(name: str, checked: BatchCheck, mode: str) -> dict[str, object]:
    tasks = [task for task in checked.ledger.tasks if task.role == "claims"]
    task_ids = {task.task_id for task in tasks}
    attempts = [attempt for attempt in checked.ledger.attempts if attempt.task_id in task_ids]
    return {
        "name": name,
        "execution_mode": mode,
        "ledger_attempts": len(attempts),
        "new_model_calls": sum(attempt.provider != "replay" for attempt in attempts),
        "attempt_status": dict(Counter(attempt.execution_status for attempt in attempts)),
        "task_status": dict(Counter(task.execution_status for task in tasks)),
        "protocol_status": dict(Counter(task.protocol_status for task in tasks)),
        "quality_status": dict(Counter(task.quality_status for task in tasks)),
        "publication_status": dict(Counter(task.publication_status for task in tasks)),
        "findings": list(checked.findings),
    }


def valid(checked: BatchCheck) -> bool:
    return not checked.findings and all(
        task.execution_status == "succeeded" and task.protocol_status == "valid"
        for task in checked.ledger.tasks
        if task.role == "claims"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-model", action="store_true")
    args = parser.parse_args()
    if not args.allow_model:
        raise SystemExit("refusing live delta execution without --allow-model")
    output = FREEZE / "execution-summary.json"
    if output.exists():
        raise SystemExit("refusing to overwrite the P1R3 execution summary")
    manifest_path = FREEZE / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_name = {entry["name"]: entry for entry in manifest["entries"]}
    results: list[dict[str, object]] = []

    for name in ORDER[:2]:
        plan = load_plan(name, by_name[name])
        checked = replay_batch(
            plan,
            responses=(FREEZE / name / "responses").resolve(),
            store_root=FREEZE / name / "replay-store",
        )
        result = summarize(name, checked, "offline_replay")
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if not valid(checked):
            raise SystemExit(f"{name} failed; live delta remains blocked")

    config = load_extraction_config(
        dotenv_path=REPO / ".env", options=RequestOptions(max_output_tokens=16_384)
    )
    if config.require_profile().fingerprint != manifest["profile"]["profile_sha256"]:
        raise SystemExit("configured profile does not match the frozen plan")
    name = ORDER[2]
    plan = load_plan(name, by_name[name])
    checked = execute_batch(
        plan,
        store_root=FREEZE / name / "live-store",
        allow_model=True,
        config=config,
    )
    result = summarize(name, checked, "live_model")
    results.append(result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    summary = {
        "schema_version": "structured-extraction-p1r3-claims-execution-1",
        "executed_on": "2026-10-09",
        "plan_manifest_sha256": sha256(manifest_path),
        "new_model_calls": sum(cast(int, item["new_model_calls"]) for item in results),
        "replayed_attempts": sum(
            cast(int, item["ledger_attempts"])
            for item in results
            if item["execution_mode"] == "offline_replay"
        ),
        "automatic_retries": 0,
        "production_database_access": 0,
        "publication_writes": 0,
        "copper_executed": False,
        "results": results,
        "next_action": "evaluate the P1R3 Claims gate before copper or publication",
    }
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
