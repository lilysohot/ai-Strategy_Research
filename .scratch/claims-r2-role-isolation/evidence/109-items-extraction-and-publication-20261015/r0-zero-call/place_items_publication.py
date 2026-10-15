"""Publish the accepted 109 号 items pool into a store, beside the already-published claims (P6).

Both roles travel in **one** publication generation. That is not stylistic: the read path
(``read_semantic``) resolves a head publication's artifacts only, and ``_coverage`` is computed from
the artifacts of the publication at hand — so an items-only generation would silently drop claims
readability that 106/108 verified. Generation 2 therefore re-imports the same signed claims payload
(106 号 bridge, byte-identical) together with the new items payload and keeps
``coverage {claims: complete, material_items: complete}``.

Preconditions, all fail-closed:
* the store already holds the 106 号 generation-1 head whose publication id matches the signed value;
* the head is the expected parent (no silent branch);
* zero model calls (``allow_model=False``) and both imported tasks land ``valid`` / ``accepted``.

Usage:
    python place_items_publication.py --store-root /abs/path [--record OUT.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.structured.config import load_extraction_config  # noqa: E402
from plugins.corpus.structured.ledger import (  # noqa: E402
    AcceptedClaims,
    AcceptedMaterialItems,
    BatchPlan,
    execute_batch,
    plan_batch,
)
from plugins.corpus.structured.query import query_semantic  # noqa: E402
from plugins.corpus.structured.roles import RoleArtifact  # noqa: E402
from plugins.corpus.structured.snapshot import EvidenceSnapshot  # noqa: E402
from plugins.corpus.structured.store import (  # noqa: E402
    ArtifactReference,
    publish_semantic,
    read_semantic,
)

FREEZE = HERE / "items-reextract-plan-freeze-r3"
BASE_106 = ROOT / "evidence/106-claims-publication-lifecycle-20261015/r0-zero-call"
RUNS = (
    ("industrial-fulian-md", "claims-industrial-fulian"),
    ("optical-module-docx", "claims-optical-module"),
)
# 106 号 signed generation-1 publication ids (landing-record.json「S2…publications」)
SIGNED_GEN1 = {
    "industrial-fulian-md": "sha256:5fc7116b",
    "optical-module-docx": "sha256:8dde446f",
}
PREFIX_LEN = len("sha256:") + 8
PURPOSES = ("cite", "compare", "calculate")


def accepted_claims(run: str) -> AcceptedClaims:
    from plugins.corpus.evidence_pipeline import EvidenceRun

    directory = BASE_106 / f"bridge-{run}"
    return AcceptedClaims(
        artifact=RoleArtifact.model_validate_json(
            (directory / "claims-artifact.json").read_text(encoding="utf-8")
        ),
        payload=EvidenceRun.model_validate_json(
            (directory / "claims-payload.json").read_text(encoding="utf-8")
        ),
    )


def accepted_items(run: str) -> AcceptedMaterialItems:
    from plugins.corpus.material_semantics import MaterialRun

    directory = HERE / f"items-bridge-{run}"
    return AcceptedMaterialItems(
        artifact=RoleArtifact.model_validate_json(
            (directory / "items-artifact.json").read_text(encoding="utf-8")
        ),
        payload=MaterialRun.model_validate_json(
            (directory / "items-payload.json").read_text(encoding="utf-8")
        ),
    )


def snapshot_of(run: str) -> EvidenceSnapshot:
    return EvidenceSnapshot.model_validate_json(
        (FREEZE / run / "snapshot.json").read_text(encoding="utf-8")
    )


def head_of(snapshot: EvidenceSnapshot, store_root: Path) -> dict[str, Any]:
    view = read_semantic(snapshot.source_id, snapshot.build_id, store_root=store_root)
    return {
        "publication_id": view.manifest.publication_id,
        "generation": view.manifest.generation,
        "coverage": view.manifest.coverage.model_dump(mode="json"),
        "quality_status": view.manifest.quality_status,
        "publication_status": view.manifest.publication_status,
    }


def count_records(source_id: str, build_id: str, purpose: str, store_root: Path) -> dict[str, Any]:
    role_counts: dict[str, int] = {}
    licensed: dict[str, int] = {}
    total = 0
    cursor: str | None = None
    pages = 0
    while True:
        page = query_semantic(
            source_id,
            build_id,
            purpose=purpose,  # type: ignore[arg-type]
            query_text="",
            limit=100,
            cursor=cursor,
            store_root=store_root,
        )
        for record in page.records:
            role_counts[record.role] = role_counts.get(record.role, 0) + 1
            if purpose in tuple(record.usable_for):
                licensed[record.role] = licensed.get(record.role, 0) + 1
        total += len(page.records)
        pages += 1
        cursor = page.next_cursor
        if not cursor or pages >= 500:
            break
    return {
        "records": total,
        "by_role": dict(sorted(role_counts.items())),
        "licensed_by_role": dict(sorted(licensed.items())),
        "pages": pages,
        "exhausted": not cursor,
    }


def publish(run: str, claims_run: str, store_root: Path) -> dict[str, Any]:
    config = load_extraction_config()
    snapshot = snapshot_of(run)
    before = head_of(snapshot, store_root)
    signed = SIGNED_GEN1[run]
    if str(before["publication_id"])[:PREFIX_LEN] != signed[:PREFIX_LEN]:
        raise SystemExit(
            f"refusing: {run} head {before['publication_id']} is not the signed 106 号 generation 1"
        )
    if before["coverage"]["claims"] != "complete":
        raise SystemExit(f"refusing: {run} head does not carry complete claims coverage")

    plan: BatchPlan = plan_batch(
        snapshot,
        config=config,
        imported_claims=accepted_claims(claims_run),
        imported_material_items=accepted_items(run),
        enabled_roles=("claims", "material_items"),
        max_attempts=0,
    )
    check = execute_batch(plan, store_root=store_root, allow_model=False)
    if not check.plan_consistent or check.findings:
        raise SystemExit(f"refusing: {run} execution inconsistent: findings={list(check.findings)}")
    tasks = {task.role: task for task in check.ledger.tasks}
    for role in ("claims", "material_items"):
        task = tasks.get(role)
        if task is None:
            raise SystemExit(f"refusing: {run} plan has no {role} task")
        if task.method != "imported":
            raise SystemExit(f"refusing: {run} {role} task method={task.method}")
        if task.protocol_status != "valid" or task.quality_status != "accepted":
            raise SystemExit(
                f"refusing: {run} {role} task protocol={task.protocol_status} "
                f"quality={task.quality_status}; the signed-bridge semantics broke"
            )

    manifest = publish_semantic(
        source_id=snapshot.source_id,
        build_id=snapshot.build_id,
        snapshot_id=snapshot.snapshot_id,
        artifacts=tuple(
            ArtifactReference(
                batch_id=plan.batch_id,
                task_id=tasks[role].task_id,
                artifact_sha256=tasks[role].artifact_sha256,
            )
            for role in ("claims", "material_items")
        ),
        expected_parent_publication_id=before["publication_id"],
        store_root=store_root,
    )
    after = head_of(snapshot, store_root)
    if after["coverage"] != {
        "claims": "complete",
        "material_items": "complete",
        "material_relations": "missing",
    }:
        raise SystemExit(f"refusing: {run} coverage after publish is {after['coverage']}")
    if after["generation"] != before["generation"] + 1:
        raise SystemExit(f"refusing: {run} generation did not advance")
    if manifest.parent_publication_id != before["publication_id"]:
        raise SystemExit(f"refusing: {run} parent chain broke")

    purposes = {
        purpose: count_records(snapshot.source_id, snapshot.build_id, purpose, store_root)
        for purpose in PURPOSES
    }
    return {
        "run": run,
        "source_id": snapshot.source_id,
        "build_id": snapshot.build_id,
        "batch_id": plan.batch_id,
        "parent_publication_id": before["publication_id"],
        "generation_before": before["generation"],
        "publication_id": after["publication_id"],
        "generation": after["generation"],
        "coverage": after["coverage"],
        "quality_status": after["quality_status"],
        "publication_status": after["publication_status"],
        "claims_artifact": tasks["claims"].artifact_sha256,
        "items_artifact": tasks["material_items"].artifact_sha256,
        "artifacts": len(manifest.artifacts),
        "mappings": len(manifest.mappings),
        "queries": purposes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-root", required=True)
    parser.add_argument("--record", default=None)
    args = parser.parse_args()

    store_root = Path(args.store_root).resolve()
    if not (store_root / "index/structured.sqlite3").exists():
        raise SystemExit(f"refusing: {store_root} is not a structured store")
    results = [publish(run, claims_run, store_root) for run, claims_run in RUNS]
    record = {
        "schema_version": "items-publication-run-1",
        "id": "109-items-extraction-and-publication-20261015",
        "created_on": "2026-10-15",
        "model_calls": 0,
        "production_pg_writes": 0,
        "store_root": str(store_root),
        "design": (
            "gen-2 单代承载 claims + material_items 两个 artifact：读路径只解析 head 的 artifacts，"
            "coverage 也按本代 artifacts 计；items-only 代会使 claims 可读性静默丢失"
        ),
        "runs": results,
    }
    print(json.dumps(record, ensure_ascii=False, indent=2))
    if args.record:
        from tools.evidence_guard import assert_writable, write_once

        target = Path(args.record).resolve()
        payload = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
        assert_writable(target, reason="109 号 P6 发布记录")
        write_once(target, payload)
        print(f"wrote {target} sha256={hashlib.sha256(payload.encode()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
