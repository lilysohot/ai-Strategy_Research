"""Read-only audit of the frozen live trial; no model or publication writes."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from plugins.corpus.structured.config import canonical_hash
from plugins.corpus.structured.ledger import BatchPlan, StructuredExecutionError, check_batch
from plugins.corpus.structured.store import ArtifactReference, _load_candidate

ROOT = Path(__file__).resolve().parent
RUN = ROOT / "preflight-claims-r1"
STORE = RUN / "store"


def read_object(digest: str) -> dict:
    key = digest.removeprefix("sha256:")
    path = STORE / "objects" / "sha256" / key[:2] / f"{key}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    assert canonical_hash(value) == digest
    return value


def main() -> None:
    plan = BatchPlan.model_validate_json((RUN / "plan.json").read_text(encoding="utf-8"))
    frozen = json.loads((RUN / "freeze.json").read_text(encoding="utf-8"))
    for filename, key in (
        ("live_preflight.py", "runner_sha256"),
        ("research-scope-review.md", "scope_review_sha256"),
    ):
        assert hashlib.sha256((ROOT / filename).read_bytes()).hexdigest() == frozen[key]
    check = check_batch(plan.batch_id, store_root=STORE)
    assert check.plan_consistent
    assert check.ledger.budget.actual_attempts == 1
    task = next(task for task in check.ledger.tasks if task.role == "claims")
    artifact = read_object(task.artifact_sha256)
    payload = read_object(artifact["payload_sha256"])
    units = {unit.metadata["source_unit_id"]: unit for unit in plan.snapshot.units}
    span_count = 0
    for fact in payload["facts"]:
        for key in ("source_spans", "dependency_spans", "role_context_spans"):
            for span in fact["evidence_alignment"][key]:
                unit = units[span["unit_id"]]
                assert unit.text[span["start"] : span["end"]] == span["quote"]
                assert unit.text_sha256 == span["text_sha256"]
                span_count += 1
    db = STORE / "index" / "structured.sqlite3"
    with sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT response_object_sha256, response_sha256 FROM attempts WHERE batch_id=?",
            (plan.batch_id,),
        ).fetchone()
        response = read_object(row["response_object_sha256"])
        assert canonical_hash(response["content"]) == row["response_sha256"]
        try:
            _load_candidate(
                connection,
                STORE,
                ArtifactReference(
                    batch_id=plan.batch_id,
                    task_id=task.task_id,
                    artifact_sha256=task.artifact_sha256,
                ),
            )
        except StructuredExecutionError as exc:
            gate = str(exc)
            assert "artifact_not_publishable" in gate
        else:
            raise AssertionError("Review-required artifact unexpectedly publishable")
    summary = {
        "audit": "read_only_no_model_calls",
        "batch_id": plan.batch_id,
        "plan_consistent": check.plan_consistent,
        "freeze_bindings_valid": True,
        "source_span_bindings_checked": span_count,
        "response_object_sha256": row["response_object_sha256"],
        "raw_response_binding_valid": True,
        "publication_gate": gate,
        "facts": [
            {
                "text": fact["claim"]["claim_text"],
                "quality": fact["claim"]["quality_status"],
                "usable_for": fact["usable_for"],
                "reasons": fact["reasons"],
            }
            for fact in payload["facts"]
        ],
        "findings": check.findings,
        "cost_summary": check.model_dump(mode="json")["cost_summary"],
    }
    with (RUN / "audit.json").open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
