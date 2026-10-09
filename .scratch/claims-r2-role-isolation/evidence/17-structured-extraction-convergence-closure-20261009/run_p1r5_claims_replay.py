"""Freeze and execute the final zero-call Claims rebinding replay."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

from plugins.corpus.claims_detail import LINT_VERSION, PERIOD_RULE_VERSION, UNIT_RULE_VERSION
from plugins.corpus.evidence_pipeline import PIPELINE_VERSION
from plugins.corpus.structured.ledger import BatchPlan, ReplayResponse, replay_batch
from plugins.corpus.structured.roles import ROUTING_RULE_VERSION

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "p1r4-claims-replay-freeze"
OUT = HERE / "p1r5-claims-replay-freeze"
RUNS = (
    "replay-claims-industrial-fulian",
    "replay-claims-optical-module",
    "live-claims-optical-routing-delta",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def freeze() -> dict[str, object]:
    if OUT.exists():
        raise SystemExit("refusing to overwrite the P1R5 replay freeze")
    OUT.mkdir(parents=True)
    entries = []
    for name in RUNS:
        source = SOURCE / name
        plan = BatchPlan.model_validate_json((source / "plan.json").read_text(encoding="utf-8"))
        plan.verify_identity()
        task = next(task for task in plan.tasks if task.role == "claims")
        target = OUT / name
        save(target / "snapshot.json", plan.snapshot.model_dump(mode="json"))
        save(target / "plan.json", plan.model_dump(mode="json"))
        store = source / "replay-store"
        connection = sqlite3.connect(store / "index/structured.sqlite3")
        connection.row_factory = sqlite3.Row
        try:
            attempts = connection.execute(
                "SELECT * FROM attempts ORDER BY attempt_number"
            ).fetchall()
        finally:
            connection.close()
        for attempt in attempts:
            digest = str(attempt["response_object_sha256"]).removeprefix("sha256:")
            response = json.loads(
                (store / "objects/sha256" / digest[:2] / f"{digest}.json").read_text(
                    encoding="utf-8"
                )
            )
            replay = ReplayResponse(
                task_id=task.task_id,
                sequence=int(attempt["attempt_number"]),
                role="claims",
                protocol=task.protocol,
                content=response["content"],
                diagnostics={
                    "source": "p1r4_immutable_response_object",
                    "source_response_object_sha256": attempt["response_object_sha256"],
                    "execution_status": "succeeded",
                    "provider": "replay",
                    "model": "p1r4-response-replay",
                },
            )
            save(
                target / "responses" / f"{replay.sequence:02d}.json",
                replay.model_dump(mode="json"),
            )
        entries.append(
            {
                "name": name,
                "batch_id": plan.batch_id,
                "plan_sha256": plan.plan_sha256,
                "attempts": len(attempts),
                "plan_file_sha256": sha256(target / "plan.json"),
            }
        )
    manifest: dict[str, object] = {
        "schema_version": "structured-extraction-p1r5-claims-replay-freeze-1",
        "status": "frozen_not_executed",
        "frozen_on": "2026-10-09",
        "new_model_calls": 0,
        "automatic_retries": 0,
        "production_database_access": 0,
        "publication_writes": 0,
        "versions": {
            "routing": ROUTING_RULE_VERSION,
            "pipeline": PIPELINE_VERSION,
            "lint": LINT_VERSION,
            "period_rules": PERIOD_RULE_VERSION,
            "unit_rules": UNIT_RULE_VERSION,
        },
        "entries": entries,
        "p1r4_execution_sha256": sha256(SOURCE / "execution-summary.json"),
        "runner_sha256": sha256(Path(__file__)),
    }
    save(OUT / "manifest.json", manifest)
    return manifest


def execute(manifest: dict[str, object]) -> None:
    results = []
    for entry in manifest["entries"]:  # type: ignore[union-attr]
        name = str(entry["name"])
        plan_path = OUT / name / "plan.json"
        if sha256(plan_path) != entry["plan_file_sha256"]:
            raise SystemExit(f"plan file hash drifted: {name}")
        plan = BatchPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        checked = replay_batch(
            plan,
            responses=(OUT / name / "responses").resolve(),
            store_root=OUT / name / "replay-store",
        )
        tasks = [task for task in checked.ledger.tasks if task.role == "claims"]
        attempts = checked.ledger.attempts
        result = {
            "name": name,
            "attempts": len(attempts),
            "attempt_status": dict(Counter(a.execution_status for a in attempts)),
            "task_status": dict(Counter(t.execution_status for t in tasks)),
            "protocol_status": dict(Counter(t.protocol_status for t in tasks)),
            "quality_status": dict(Counter(t.quality_status for t in tasks)),
            "findings": list(checked.findings),
        }
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if checked.findings or any(
            task.execution_status != "succeeded" or task.protocol_status != "valid"
            for task in tasks
        ):
            raise SystemExit(f"P1R5 replay failed: {name}")
    summary = {
        "schema_version": "structured-extraction-p1r5-claims-replay-execution-1",
        "executed_on": "2026-10-09",
        "manifest_sha256": sha256(OUT / "manifest.json"),
        "new_model_calls": 0,
        "replayed_attempts": sum(int(result["attempts"]) for result in results),
        "automatic_retries": 0,
        "production_database_access": 0,
        "publication_writes": 0,
        "copper_executed": False,
        "results": results,
        "next_action": "Claims gate evaluation",
    }
    save(OUT / "execution-summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    execute(freeze())
