"""Freeze a zero-call P1R4 replay over all nineteen immutable P1R3 responses."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from plugins.corpus.claims_binding import CLAIMS_SLOT_PROTOCOL_VERSION
from plugins.corpus.claims_detail import LINT_VERSION, PERIOD_RULE_VERSION, UNIT_RULE_VERSION
from plugins.corpus.evidence_pipeline import CLAIMS_ATOMIC_PROTOCOL, PIPELINE_VERSION
from plugins.corpus.structured.ledger import BatchPlan, ReplayResponse
from plugins.corpus.structured.roles import ROUTING_RULE_VERSION

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "p1r3-claims-plan-freeze"
OUT = HERE / "p1r4-claims-replay-freeze"
RUNS = (
    ("replay-claims-industrial-fulian", "replay-store"),
    ("replay-claims-optical-module", "replay-store"),
    ("live-claims-optical-routing-delta", "live-store"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main() -> None:
    if OUT.exists():
        raise SystemExit("refusing to overwrite the P1R4 replay freeze")
    OUT.mkdir(parents=True)
    entries = []
    for name, store_leaf in RUNS:
        source = SOURCE / name
        plan = BatchPlan.model_validate_json((source / "plan.json").read_text(encoding="utf-8"))
        plan.verify_identity()
        task = next(task for task in plan.tasks if task.role == "claims")
        target = OUT / name
        save(target / "snapshot.json", plan.snapshot.model_dump(mode="json"))
        save(target / "plan.json", plan.model_dump(mode="json"))
        store = source / store_leaf
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
                    "source": "p1r3_immutable_response_object",
                    "source_response_object_sha256": attempt["response_object_sha256"],
                    "execution_status": "succeeded",
                    "provider": "replay",
                    "model": "p1r3-response-replay",
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
                "new_model_calls": 0,
                "snapshot_file_sha256": sha256(target / "snapshot.json"),
                "plan_file_sha256": sha256(target / "plan.json"),
            }
        )
    manifest = {
        "schema_version": "structured-extraction-p1r4-claims-replay-freeze-1",
        "status": "frozen_not_executed",
        "frozen_on": "2026-10-09",
        "purpose": "zero-call deterministic rebinding of the nineteen P1R3 responses",
        "execution_order": [entry["name"] for entry in entries] + ["claims_gate_evaluation"],
        "new_model_calls": 0,
        "automatic_retries": 0,
        "production_database_access": 0,
        "publication_writes": 0,
        "versions": {
            "claims_protocol": CLAIMS_ATOMIC_PROTOCOL,
            "slot_protocol": CLAIMS_SLOT_PROTOCOL_VERSION,
            "routing": ROUTING_RULE_VERSION,
            "pipeline": PIPELINE_VERSION,
            "lint": LINT_VERSION,
            "period_rules": PERIOD_RULE_VERSION,
            "unit_rules": UNIT_RULE_VERSION,
        },
        "entries": entries,
        "p1r3_execution_sha256": sha256(SOURCE / "execution-summary.json"),
        "prepare_script_sha256": sha256(Path(__file__)),
    }
    save(OUT / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
