"""One explicitly authorized real extraction through the production ledger interface."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from plugins.corpus.structured.config import canonical_hash, load_extraction_config
from plugins.corpus.structured.ledger import BatchPlan, check_batch, execute_batch, plan_batch
from plugins.corpus.structured.snapshot import (
    SnapshotBuildSource,
    SnapshotDependencySource,
    SnapshotDocumentSource,
    SnapshotHead,
    SnapshotUnitSource,
    build_snapshot,
)

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]
RUN = ROOT / "preflight-claims-r1"


def save(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


class FrozenReader:
    def __init__(self, payload: SnapshotBuildSource) -> None:
        self.payload = payload

    def read_head(self, source_id: str) -> SnapshotHead:
        assert source_id == self.payload.head.source_id
        return self.payload.head

    def read_build(self, head: SnapshotHead) -> SnapshotBuildSource:
        assert head == self.payload.head
        return self.payload


def prepare() -> None:
    config = load_extraction_config(dotenv_path=REPO / ".env")
    config.require_profile()
    inspection = json.loads((ROOT / "source-inspection.json").read_text(encoding="utf-8"))
    source = Path(inspection["source_path"])
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    assert source_hash == inspection["source_sha256"]
    capture = json.loads((ROOT / "reader-capture.json").read_text(encoding="utf-8"))
    versions = {
        "parse": capture["reader"]["extractor_rev"],
        "clean": capture["clean"]["clean_rev"],
        "chunk": capture["chunks"]["chunk_rev"],
        "adapter": "approved-local-reader-preflight-v1",
    }
    scope = [unit for unit in capture["reader"]["units"] if unit["ordinal"] in (4, 5, 12)]
    assert len(scope) == 3 and all(unit["location"]["page"] == 1 for unit in scope)
    build_id = canonical_hash({"source": source_hash, "versions": versions, "scope": scope})[7:]
    head = SnapshotHead(source_id=source_hash, build_id=build_id, publication_generation=1)
    units = tuple(
        SnapshotUnitSource(
            source_unit_id=f"pdf-unit-{unit['ordinal']}",
            chunk_id="preflight-page1-results",
            kind="prose" if unit["ordinal"] == 12 else "heading",
            text=unit["raw_text"],
            locator=f"page:1/unit:{unit['ordinal']}",
            page=1,
            ordinal=unit["ordinal"],
            metadata={"reader_kind": unit["kind"], "bbox": unit["location"]["bbox"]},
            dependencies=(
                SnapshotDependencySource("period", "pdf-unit-4"),
                SnapshotDependencySource("attribution", "pdf-unit-5"),
            )
            if unit["ordinal"] == 12
            else (),
        )
        for unit in scope
    )
    payload = SnapshotBuildSource(
        head=head,
        parser_versions=versions,
        document=SnapshotDocumentSource(
            title="华创证券：贵州茅台（600519）2026年中报点评",
            subject="600519.SH",
            published="2026-08-16",
        ),
        units=units,
    )
    snapshot = build_snapshot(FrozenReader(payload), source_hash)
    plan = plan_batch(
        snapshot,
        config=config,
        max_attempts=1,
        role_max_attempts={"claims": 1, "material_items": 0, "material_relations": 0},
        relations_enabled=False,
        max_relation_tasks=0,
        max_relation_attempts=0,
        deadline_epoch=time.time() + 1800,
    )
    assert len([task for task in plan.tasks if task.role == "claims"]) == 1
    RUN.mkdir(exist_ok=False)
    save(RUN / "snapshot.json", snapshot.model_dump(mode="json"))
    save(RUN / "plan.json", plan.model_dump(mode="json"))
    save(
        RUN / "freeze.json",
        {
            "stage": "real_claims_protocol_preflight_only",
            "user_authorization": "2026-10-04 unlimited calls without loops; scope confirmed 2026-10-05",
            "scope_review_sha256": hashlib.sha256(
                (ROOT / "research-scope-review.md").read_bytes()
            ).hexdigest(),
            "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "source_sha256": source_hash,
            "batch_id": plan.batch_id,
            "snapshot_id": snapshot.snapshot_id,
            "source_scope": "PDF page 1, reader units 4/5/12; not a full-document quality claim",
            "attempt_ceiling": 1,
            "automatic_retries": 0,
            "expected_checks": ["E02", "E03", "E04"],
            "production_database_access": 0,
        },
    )
    print(
        json.dumps(
            {"batch_id": plan.batch_id, "requests_sent": 0, "plan": str(RUN / "plan.json")},
            ensure_ascii=False,
        )
    )


def execute() -> int:
    plan = BatchPlan.model_validate_json((RUN / "plan.json").read_text(encoding="utf-8"))
    frozen = json.loads((RUN / "freeze.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == frozen["runner_sha256"]
    assert (
        hashlib.sha256((ROOT / "research-scope-review.md").read_bytes()).hexdigest()
        == frozen["scope_review_sha256"]
    )
    config = load_extraction_config(dotenv_path=REPO / ".env")
    config.require_profile()
    # Exclusive creation prevents this executable from ever dispatching a second run.
    save(RUN / "started.json", {"started_epoch": time.time(), "batch_id": plan.batch_id})
    result = execute_batch(plan, config=config, allow_model=True, store_root=RUN / "store")
    save(RUN / "check.json", result.model_dump(mode="json"))
    print(result.model_dump_json(indent=2), flush=True)
    claims = [task for task in result.ledger.tasks if task.role == "claims"]
    return (
        0
        if claims
        and all(
            task.execution_status == "succeeded" and task.protocol_status == "valid"
            for task in claims
        )
        else 4
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "execute", "check"))
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
        return 0
    if args.action == "execute":
        return execute()
    plan = BatchPlan.model_validate_json((RUN / "plan.json").read_text(encoding="utf-8"))
    print(check_batch(plan.batch_id, store_root=RUN / "store").model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
