"""Execute the frozen zero-call P1R4 Claims replay."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import cast

from plugins.corpus.structured.ledger import BatchPlan, replay_batch

HERE = Path(__file__).resolve().parent
FREEZE = HERE / "p1r4-claims-replay-freeze"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    output = FREEZE / "execution-summary.json"
    if output.exists():
        raise SystemExit("refusing to overwrite the P1R4 execution summary")
    manifest_path = FREEZE / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results: list[dict[str, object]] = []
    for entry in manifest["entries"]:
        name = str(entry["name"])
        plan_path = FREEZE / name / "plan.json"
        if sha256(plan_path) != entry["plan_file_sha256"]:
            raise SystemExit(f"plan file hash drifted: {name}")
        plan = BatchPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        plan.verify_identity()
        checked = replay_batch(
            plan,
            responses=(FREEZE / name / "responses").resolve(),
            store_root=FREEZE / name / "replay-store",
        )
        tasks = [task for task in checked.ledger.tasks if task.role == "claims"]
        attempts = [
            attempt
            for attempt in checked.ledger.attempts
            if attempt.task_id in {task.task_id for task in tasks}
        ]
        result = {
            "name": name,
            "ledger_attempts": len(attempts),
            "new_model_calls": 0,
            "attempt_status": dict(Counter(attempt.execution_status for attempt in attempts)),
            "task_status": dict(Counter(task.execution_status for task in tasks)),
            "protocol_status": dict(Counter(task.protocol_status for task in tasks)),
            "quality_status": dict(Counter(task.quality_status for task in tasks)),
            "publication_status": dict(Counter(task.publication_status for task in tasks)),
            "findings": list(checked.findings),
        }
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if checked.findings or any(
            task.execution_status != "succeeded" or task.protocol_status != "valid"
            for task in tasks
        ):
            raise SystemExit(f"P1R4 replay failed: {name}")
    summary = {
        "schema_version": "structured-extraction-p1r4-claims-replay-execution-1",
        "executed_on": "2026-10-09",
        "plan_manifest_sha256": sha256(manifest_path),
        "new_model_calls": 0,
        "replayed_attempts": sum(cast(int, item["ledger_attempts"]) for item in results),
        "automatic_retries": 0,
        "production_database_access": 0,
        "publication_writes": 0,
        "copper_executed": False,
        "results": results,
        "next_action": "evaluate the P1R4 Claims gate before copper or publication",
    }
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
