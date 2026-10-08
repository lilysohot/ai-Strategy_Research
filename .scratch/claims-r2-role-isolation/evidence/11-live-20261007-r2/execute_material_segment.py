"""Execute exactly one frozen material segment and summarize its ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from plugins.corpus.structured.config import RequestOptions, load_extraction_config
from plugins.corpus.structured.ledger import BatchPlan, check_batch, execute_batch

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]


def save(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def verify(run: Path) -> tuple[BatchPlan, dict]:
    frozen = json.loads((run / "freeze.json").read_text(encoding="utf-8"))
    for filename, digest in frozen["runner_sha256"].items():
        assert hashlib.sha256((ROOT / filename).read_bytes()).hexdigest() == digest
    plan = BatchPlan.model_validate_json((run / "plan.json").read_text(encoding="utf-8"))
    assert plan.batch_id == frozen["batch_id"]
    assert plan.snapshot.snapshot_id == frozen["snapshot_id"]
    return plan, frozen


def execute(segment: str) -> int:
    run = ROOT / segment
    plan, frozen = verify(run)
    config = load_extraction_config(
        dotenv_path=REPO / ".env",
        options=RequestOptions(max_output_tokens=8192),
    )
    config.require_profile()
    save(run / "started.json", {"started_epoch": time.time(), "batch_id": plan.batch_id})
    result = execute_batch(plan, store_root=run / "store", allow_model=True, config=config)
    save(run / "check.json", result.model_dump(mode="json"))
    item = next(task for task in result.ledger.tasks if task.role == "material_items")
    relation_tasks = [task for task in result.ledger.tasks if task.role == "material_relations"]
    summary = {
        "segment": segment,
        "batch_id": plan.batch_id,
        "candidate_slot_count": frozen["candidate_slot_count"],
        "material_items": item.model_dump(mode="json"),
        "material_relations": [task.model_dump(mode="json") for task in relation_tasks],
        "attempts": [attempt.model_dump(mode="json") for attempt in result.ledger.attempts],
        "plan_consistent": result.plan_consistent,
        "findings": list(result.findings),
        "cost_summary": [entry.model_dump(mode="json") for entry in result.cost_summary],
    }
    save(run / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    items_ok = (
        item.execution_status == "succeeded"
        and item.protocol_status == "valid"
        and item.quality_status == "accepted"
        and item.publication_status == "candidate"
    )
    relations_ok = all(
        task.execution_status == "succeeded"
        and task.protocol_status == "valid"
        and task.quality_status == "accepted"
        for task in relation_tasks
    )
    return 0 if items_ok and relations_ok and result.plan_consistent else 5


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("segment")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    run = ROOT / args.segment
    plan, _frozen = verify(run)
    if args.check:
        print(check_batch(plan.batch_id, store_root=run / "store").model_dump_json(indent=2))
        return 0
    return execute(args.segment)


if __name__ == "__main__":
    raise SystemExit(main())
