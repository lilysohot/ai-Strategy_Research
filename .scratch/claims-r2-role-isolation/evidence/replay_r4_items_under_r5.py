"""Reparse the immutable r4 material-item responses with the r5 validator, offline."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from plugins.corpus.material_semantics import (
    MATERIAL_EXTRACTOR_VERSION,
    MATERIAL_ITEMS_VALIDATION_VERSION,
    RELATION_CANDIDATE_RULE_VERSION,
    MaterialRun,
    build_relation_candidate_set,
)
from plugins.corpus.structured.ledger import (
    BatchPlan,
    ReplayResponse,
    _read_object,
    plan_batch,
    replay_batch,
)

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "15-live-20261008-non-table-gold-r4" / "industrial-fulian-md"
OUTPUT = HERE / "16-r5-zero-model-replay-20261008-r4" / "industrial-fulian-md"
SEMANTICS = HERE.parents[2] / "plugins" / "corpus" / "material_semantics.py"
LEDGER = HERE.parents[2] / "plugins" / "corpus" / "structured" / "ledger.py"
ADAPTER = HERE.parents[2] / "plugins" / "corpus" / "structured" / "adapter.py"
CONFIG = HERE.parents[2] / "plugins" / "corpus" / "structured" / "config.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def response_object_path(root: Path, object_id: str) -> Path:
    digest = object_id.removeprefix("sha256:")
    if len(digest) != 64:
        raise ValueError("invalid response object hash")
    return root / "objects" / "sha256" / digest[:2] / f"{digest}.json"


def open_immutable_database(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)


def load_r4_item_responses() -> list[dict[str, Any]]:
    store = SOURCE / "store"
    connection = open_immutable_database(store / "index" / "structured.sqlite3")
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT a.attempt_number, a.execution_status, a.response_object_sha256 "
            "FROM attempts a JOIN tasks t ON a.task_id=t.task_id "
            "WHERE t.role='material_items' ORDER BY a.attempt_number"
        ).fetchall()
    finally:
        connection.close()
    if not rows or any(
        row["execution_status"] != "succeeded" or not row["response_object_sha256"]
        for row in rows
    ):
        raise ValueError("r4 material-item response set is incomplete")
    responses = []
    for row in rows:
        path = response_object_path(store, row["response_object_sha256"])
        payload = json.loads(path.read_text(encoding="utf-8"))
        responses.append(
            {
                "sequence": row["attempt_number"],
                "object_sha256": row["response_object_sha256"],
                "object_file_sha256": sha256(path),
                "content": payload["content"],
                "diagnostics": payload.get("diagnostics", {}),
            }
        )
    return responses


def load_replayed_items(store: Path, task_id: str) -> MaterialRun:
    connection = open_immutable_database(store / "index" / "structured.sqlite3")
    row = connection.execute(
        "SELECT payload_object_sha256 FROM tasks WHERE task_id=?", (task_id,)
    ).fetchone()
    connection.close()
    if row is None or not row[0]:
        raise ValueError("replayed material-item payload is missing")
    return MaterialRun.model_validate(_read_object(store, row[0]))


def main() -> int:
    if OUTPUT.parent.exists():
        raise SystemExit("refusing to overwrite existing r5 replay evidence")
    old_plan_path = SOURCE / "plan.json"
    old_plan = BatchPlan.model_validate_json(old_plan_path.read_text(encoding="utf-8"))
    responses = load_r4_item_responses()
    plan = plan_batch(
        old_plan.snapshot,
        max_attempts=len(responses),
        role_max_attempts={
            "claims": 0,
            "material_items": len(responses),
            "material_relations": 0,
        },
        relations_enabled=False,
    )
    items_task = next(task for task in plan.tasks if task.role == "material_items")

    replay_directory = OUTPUT / "responses"
    replay_directory.mkdir(parents=True)
    bindings = []
    for response in responses:
        replay = ReplayResponse(
            task_id=items_task.task_id,
            sequence=response["sequence"],
            role="material_items",
            protocol=items_task.protocol,
            content=response["content"],
            diagnostics=response["diagnostics"],
        )
        response_path = replay_directory / f"items-{response['sequence']:02d}.json"
        save_json(response_path, replay.model_dump(mode="json"))
        bindings.append(
            {
                "sequence": response["sequence"],
                "r4_response_object_sha256": response["object_sha256"],
                "r4_response_file_sha256": response["object_file_sha256"],
                "replay_response_sha256": sha256(response_path),
            }
        )

    save_json(OUTPUT / "plan.json", plan.model_dump(mode="json"))
    result = replay_batch(
        plan,
        responses=replay_directory.resolve(),
        store_root=OUTPUT / "store",
    )
    save_json(OUTPUT / "check.json", result.model_dump(mode="json"))
    items_run = load_replayed_items(OUTPUT / "store", items_task.task_id)
    qualified_item_ids = {
        item_ref
        for entry in items_run.understanding.coverage.slot_ledger
        if entry.status == "extracted"
        for item_ref in entry.item_refs
    }
    endpoints = tuple(
        item.item_id
        for item in items_run.understanding.items
        if item.item_id in qualified_item_ids
    )
    candidate_set = build_relation_candidate_set(
        old_plan.snapshot,
        items_run,
        endpoint_item_ids=endpoints,
        items_validation_version=MATERIAL_ITEMS_VALIDATION_VERSION,
        rule_version=RELATION_CANDIDATE_RULE_VERSION,
    )
    save_json(OUTPUT / "relation-candidates.json", candidate_set.model_dump(mode="json"))

    items_ledger = next(task for task in result.ledger.tasks if task.role == "material_items")
    slot_statuses = Counter(
        entry.status for entry in items_run.understanding.coverage.slot_ledger
    )
    packet_statuses = Counter(packet.status for packet in items_run.packet_runs)
    summary = {
        "mode": "offline_replay_only",
        "model_calls": 0,
        "source_run": "15-live-20261008-non-table-gold-r4/industrial-fulian-md",
        "source_response_count": len(responses),
        "snapshot_id": old_plan.snapshot.snapshot_id,
        "items_task": items_ledger.model_dump(mode="json"),
        "items_run_id": items_run.run_id,
        "item_count": len(items_run.understanding.items),
        "slot_count": len(items_run.understanding.coverage.slot_ledger),
        "slot_statuses": dict(sorted(slot_statuses.items())),
        "packet_statuses": dict(sorted(packet_statuses.items())),
        "qualified_relation_endpoint_count": len(endpoints),
        "relation_candidate_count": len(candidate_set.candidates),
        "relation_model_calls": 0,
        "plan_consistent": result.plan_consistent,
        "findings": list(result.findings),
    }
    save_json(OUTPUT / "summary.json", summary)
    save_json(
        OUTPUT.parent / "manifest.json",
        {
            "status": "complete_zero_model_replay",
            "source_plan_sha256": sha256(old_plan_path),
            "source_snapshot_id": old_plan.snapshot.snapshot_id,
            "source_response_bindings": bindings,
            "versions": {
                "material_extractor": MATERIAL_EXTRACTOR_VERSION,
                "items_validation": MATERIAL_ITEMS_VALIDATION_VERSION,
                "relation_candidate_rule": RELATION_CANDIDATE_RULE_VERSION,
            },
            "implementation_sha256": {
                "material_semantics.py": sha256(SEMANTICS),
                "structured/ledger.py": sha256(LEDGER),
                "structured/adapter.py": sha256(ADAPTER),
                "structured/config.py": sha256(CONFIG),
                "replay_r4_items_under_r5.py": sha256(Path(__file__)),
            },
            "model_calls": 0,
            "summary_sha256": sha256(OUTPUT / "summary.json"),
            "relation_candidates_sha256": sha256(OUTPUT / "relation-candidates.json"),
        },
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
