"""Execute the frozen P1R Claims-only plans through the formal ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from plugins.corpus.structured.config import RequestOptions, load_extraction_config
from plugins.corpus.structured.ledger import BatchPlan, execute_batch

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
FREEZE = HERE / "p1r-claims-plan-freeze"
ORDER = ("claims-industrial-fulian", "claims-optical-module")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-model", action="store_true")
    args = parser.parse_args()
    if not args.allow_model:
        raise SystemExit("refusing model execution without --allow-model")
    output = FREEZE / "execution-summary.json"
    if output.exists():
        raise SystemExit("refusing to overwrite the P1R execution summary")

    manifest_path = FREEZE / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_name = {entry["name"]: entry for entry in manifest["entries"]}
    config = load_extraction_config(
        dotenv_path=REPO / ".env",
        options=RequestOptions(max_output_tokens=16_384),
    )
    if config.require_profile().fingerprint != manifest["profile"]["profile_sha256"]:
        raise SystemExit("configured profile does not match the frozen plan")

    results: list[dict[str, object]] = []
    for name in ORDER:
        target = FREEZE / name
        plan_path = target / "plan.json"
        entry = by_name[name]
        if sha256(plan_path) != entry["plan_file_sha256"]:
            raise SystemExit(f"plan file hash drifted: {name}")
        plan = BatchPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        plan.verify_identity()
        checked = execute_batch(
            plan,
            store_root=target / "live-store",
            allow_model=True,
            config=config,
        )
        tasks = [task for task in checked.ledger.tasks if task.role == "claims"]
        task_ids = {task.task_id for task in tasks}
        attempts = [
            attempt for attempt in checked.ledger.attempts if attempt.task_id in task_ids
        ]
        results.append(
            {
                "name": name,
                "batch_id": plan.batch_id,
                "plan_sha256": plan.plan_sha256,
                "attempt_ceiling": plan.role_max_attempts["claims"],
                "actual_attempts": len(attempts),
                "attempt_status": dict(Counter(a.execution_status for a in attempts)),
                "task_status": dict(Counter(task.execution_status for task in tasks)),
                "protocol_status": dict(Counter(task.protocol_status for task in tasks)),
                "quality_status": dict(Counter(task.quality_status for task in tasks)),
                "publication_status": dict(Counter(task.publication_status for task in tasks)),
                "findings": list(checked.findings),
                "store": str((target / "live-store").relative_to(REPO)),
            }
        )
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
        if any(
            task.execution_status != "succeeded" or task.protocol_status != "valid"
            for task in tasks
        ):
            break

    summary = {
        "schema_version": "structured-extraction-p1r-claims-execution-1",
        "executed_on": "2026-10-09",
        "plan_manifest_sha256": sha256(manifest_path),
        "model_calls": sum(int(result["actual_attempts"]) for result in results),
        "automatic_retries": 0,
        "production_database_access": 0,
        "publication_writes": 0,
        "copper_executed": False,
        "stopped_early": len(results) != len(ORDER),
        "blocked_plans": list(ORDER[len(results) :]),
        "results": results,
        "next_action": (
            "diagnose the atomic slot protocol failure without further model calls"
            if len(results) != len(ORDER)
            else "evaluate the frozen Claims gate before any copper or publication work"
        ),
    }
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
