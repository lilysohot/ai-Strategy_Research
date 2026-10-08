"""Run the signed non-table gold scope with packet-complete frozen budgets."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from plugins.corpus.evidence_pipeline import evidence_document_from_snapshot
from plugins.corpus.material_semantics import (
    build_candidate_slot_batches,
    build_candidate_slots,
    build_material_structure,
)
from plugins.corpus.structured.config import (
    ExtractionConfig,
    RequestOptions,
    canonical_hash,
    load_extraction_config,
)
from plugins.corpus.structured.ledger import BatchPlan, Role, check_batch, execute_batch, plan_batch
from plugins.corpus.structured.snapshot import (
    SnapshotBuildSource,
    SnapshotDocumentSource,
    SnapshotHead,
    SnapshotUnitSource,
    build_snapshot,
)

EVIDENCE = Path(__file__).resolve().parent
REPO = EVIDENCE.parents[2]
FREEZE = EVIDENCE / "10-quality-gold-freeze-20261008-r2"
REVIEW = EVIDENCE / "10-quality-gold-expansion-20261008-r2"
SOURCE_EXPORT = EVIDENCE / "10-quality-gold-expansion-20261008-r1/source-prose-units.json"
RUN_NAME = "11-live-20261008-non-table-gold-r2"
RUN = EVIDENCE / RUN_NAME
SEMANTICS = REPO / "plugins/corpus/material_semantics.py"
ROLES: tuple[Role, ...] = ("claims", "material_items", "material_relations")


class FrozenReader:
    def __init__(self, payload: SnapshotBuildSource) -> None:
        self.payload = payload

    def read_head(self, source_id: str) -> SnapshotHead:
        if source_id != self.payload.head.source_id:
            raise ValueError("source changed")
        return self.payload.head

    def read_build(self, head: SnapshotHead) -> SnapshotBuildSource:
        if head != self.payload.head:
            raise ValueError("head changed")
        return self.payload


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def config() -> ExtractionConfig:
    result = load_extraction_config(
        dotenv_path=REPO / ".env", options=RequestOptions(max_output_tokens=16_384)
    )
    result.require_profile()
    return result


def source_slug(path: str) -> str:
    if path.endswith(".md"):
        return "industrial-fulian-md"
    if path.endswith(".docx"):
        return "optical-module-docx"
    raise ValueError("unexpected signed source")


def document(path: str) -> SnapshotDocumentSource:
    if path.endswith(".md"):
        return SnapshotDocumentSource(
            title="工业富联投委会决策报告", subject="工业富联", published="2026-08-29"
        )
    return SnapshotDocumentSource(
        title="光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局",
        subject="光模块行业",
        published="2026-09-08",
    )


def snapshots() -> list[tuple[str, Any]]:
    freeze_state = read_json(FREEZE / "freeze-state.json")
    if not freeze_state["formal_gold_frozen"] or not freeze_state["candidate_execution_authorized"]:
        raise ValueError("signed freeze does not authorize candidate execution")
    contract = read_json(REVIEW / "scoring-contract.json")
    export = read_json(SOURCE_EXPORT)
    sources = {f"sha256:{s['source_sha256']}": s for s in export["sources"]}
    result = []
    for scoped in contract["candidate_input_scope"]:
        source = sources[scoped["source_id"]]
        by_locator = {unit["locator"]: unit for unit in source["units"]}
        selected = [by_locator[locator] for locator in scoped["locators"]]
        if len(selected) != len(set(scoped["locators"])):
            raise ValueError("scope contains duplicate/missing locator")
        path = source["path"]
        source_hash = source["source_sha256"]
        versions = {
            "parse": source["extractor_rev"],
            "clean": "signed-non-table-exact-text-1",
            "chunk": "signed-non-table-scope-1",
            "adapter": "signed-gold-evaluation-adapter-1",
        }
        identity = {
            "source": source_hash,
            "versions": versions,
            "locators": scoped["locators"],
            "freeze": sha256(FREEZE / "freeze-manifest.json"),
        }
        build_id = canonical_hash(identity)[7:]
        head = SnapshotHead(source_id=source_hash, build_id=build_id, publication_generation=1)
        units = tuple(
            SnapshotUnitSource(
                source_unit_id=f"signed-unit-{unit['ordinal']}",
                chunk_id="signed-non-table-target-scope",
                kind="prose",
                text=unit["text"],
                locator=unit["locator"],
                element=unit["locator"] if unit["locator"].startswith("body[") else None,
                ordinal=unit["ordinal"],
                metadata={
                    "reader_kind": unit["kind"],
                    "source_text_sha256": unit["text_sha256"],
                    "gold_not_exposed_to_model": True,
                },
            )
            for unit in selected
        )
        payload = SnapshotBuildSource(
            head=head,
            parser_versions=versions,
            document=document(path),
            units=units,
        )
        snapshot = build_snapshot(FrozenReader(payload), source_hash)
        result.append((source_slug(path), snapshot))
    return result


def prepare() -> None:
    if RUN.exists():
        raise SystemExit("refusing to overwrite existing bounded run")
    extraction = config()
    frozen = snapshots()
    runner_hash = sha256(Path(__file__))
    freeze_hash = sha256(FREEZE / "freeze-manifest.json")
    semantics_hash = sha256(SEMANTICS)
    prepared = []
    for slug, snapshot in frozen:
        material_document = evidence_document_from_snapshot(snapshot, role="material_items")
        candidate_slots = build_candidate_slots(
            material_document, build_material_structure(material_document)
        )
        item_batches = build_candidate_slot_batches(
            candidate_slots, max_slots_per_batch=8, max_items_per_batch=30
        )
        role_budgets: dict[Role, int] = {
            "claims": len(material_document.packets),
            "material_items": len(item_batches),
            "material_relations": len(material_document.packets),
        }
        max_attempts = sum(role_budgets.values())
        plan = plan_batch(
            snapshot,
            config=extraction,
            max_attempts=max_attempts,
            role_max_attempts=role_budgets,
            relations_enabled=True,
            max_relation_tasks=1,
            max_relation_attempts=role_budgets["material_relations"],
            deadline_epoch=time.time() + 7200,
        )
        counts = {role: sum(task.role == role for task in plan.tasks) for role in ROLES}
        if plan.role_max_attempts != role_budgets or plan.max_attempts != max_attempts:
            raise ValueError(f"budget plan changed: {slug}")
        if counts != {"claims": 1, "material_items": 1, "material_relations": 0}:
            raise ValueError(f"unexpected initial task plan: {slug}: {counts}")
        prepared.append((slug, snapshot, plan, counts, role_budgets, len(candidate_slots)))
    RUN.mkdir()
    manifest_entries = []
    total_attempt_ceiling = 0
    for slug, snapshot, plan, counts, role_budgets, candidate_slots in prepared:
        target = RUN / slug
        target.mkdir()
        save(target / "snapshot.json", snapshot.model_dump(mode="json"))
        save(target / "plan.json", plan.model_dump(mode="json"))
        freeze = {
            "stage": "signed_non_table_gold_candidate_evaluation",
            "source_slug": slug,
            "batch_id": plan.batch_id,
            "snapshot_id": snapshot.snapshot_id,
            "source_id": snapshot.source_id,
            "unit_locators": [unit.locator for unit in snapshot.units],
            "task_counts": counts,
            "candidate_slot_count": candidate_slots,
            "role_attempt_ceiling": role_budgets,
            "attempt_ceiling": sum(role_budgets.values()),
            "automatic_retries": 0,
            "concurrency": 1,
            "runner_sha256": runner_hash,
            "gold_freeze_manifest_sha256": freeze_hash,
            "material_semantics_sha256": semantics_hash,
            "gold_not_exposed_to_model": True,
            "production_database_access": 0,
            "holdout_accessed": False,
        }
        save(target / "freeze.json", freeze)
        manifest_entries.append({"slug": slug, **freeze})
        total_attempt_ceiling += freeze["attempt_ceiling"]
    save(
        RUN / "manifest.json",
        {
            "stage": "signed_non_table_gold_candidate_evaluation",
            "run_name": RUN_NAME,
            "status": "prepared_zero_calls",
            "model": extraction.require_profile().model,
            "profile_sha256": extraction.require_profile().fingerprint,
            "sources": manifest_entries,
            "total_attempt_ceiling": total_attempt_ceiling,
            "automatic_retries": 0,
            "concurrency": 1,
            "gold_not_exposed_to_model": True,
        },
    )
    print(json.dumps(manifest_entries, ensure_ascii=False, indent=2))


def verify(target: Path) -> tuple[BatchPlan, dict[str, Any]]:
    frozen = read_json(target / "freeze.json")
    if sha256(Path(__file__)) != frozen["runner_sha256"]:
        raise ValueError("runner changed")
    if sha256(FREEZE / "freeze-manifest.json") != frozen["gold_freeze_manifest_sha256"]:
        raise ValueError("gold freeze changed")
    if sha256(SEMANTICS) != frozen["material_semantics_sha256"]:
        raise ValueError("material semantics changed")
    plan = BatchPlan.model_validate_json((target / "plan.json").read_text(encoding="utf-8"))
    if plan.batch_id != frozen["batch_id"] or plan.snapshot.snapshot_id != frozen["snapshot_id"]:
        raise ValueError("plan changed")
    if [unit.locator for unit in plan.snapshot.units] != frozen["unit_locators"]:
        raise ValueError("scope changed")
    return plan, frozen


def execute(slug: str) -> int:
    if not re.fullmatch(r"[a-z0-9-]+", slug):
        raise ValueError("invalid slug")
    target = RUN / slug
    plan, frozen = verify(target)
    save(target / "started.json", {"batch_id": plan.batch_id, "started_epoch": time.time()})
    result = execute_batch(
        plan,
        store_root=target / "store",
        allow_model=True,
        config=config(),
    )
    save(target / "check.json", result.model_dump(mode="json"))
    save(
        target / "summary.json",
        {
            "source_slug": slug,
            "batch_id": plan.batch_id,
            "attempt_ceiling": frozen["attempt_ceiling"],
            "role_attempt_ceiling": frozen["role_attempt_ceiling"],
            "ledger": result.ledger.model_dump(mode="json"),
            "cost_summary": [item.model_dump(mode="json") for item in result.cost_summary],
            "findings": list(result.findings),
            "plan_consistent": result.plan_consistent,
        },
    )
    print(result.model_dump_json(indent=2), flush=True)
    return 0 if result.plan_consistent else 5


def check(slug: str) -> None:
    target = RUN / slug
    plan, _frozen = verify(target)
    print(check_batch(plan.batch_id, store_root=target / "store").model_dump_json(indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "execute", "check"))
    parser.add_argument("slug", nargs="?")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
        return 0
    if not args.slug:
        parser.error("slug required")
    if args.action == "execute":
        return execute(args.slug)
    check(args.slug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
