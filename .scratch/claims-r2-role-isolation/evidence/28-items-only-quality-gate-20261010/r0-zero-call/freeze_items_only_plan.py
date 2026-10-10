"""Freeze the items-only quality-gate pre-registration without any model call.

Rebuilds the two signed non-table snapshots from the Issue 10 frozen gold scope,
plans the material-items role under the current selector extractor protocol, and
writes the frozen plans, the pre-registered quality gate, and the freeze
manifest. It performs no network I/O and no model request.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from plugins.corpus.evidence_pipeline import evidence_document_from_snapshot
from plugins.corpus.material_semantics import (
    MATERIAL_EXTRACTOR_VERSION,
    MATERIAL_ITEMS_VALIDATION_VERSION,
    MATERIAL_SELECTOR_JSONL_VERSION,
    MATERIAL_SLOT_BATCHING_VERSION,
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
from plugins.corpus.structured.ledger import BatchPlan, plan_batch
from plugins.corpus.structured.snapshot import (
    SnapshotBuildSource,
    SnapshotDocumentSource,
    SnapshotHead,
    SnapshotUnitSource,
    build_snapshot,
)

ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
CLAIMS = ROOT / ".scratch" / "claims-r2-role-isolation"
EVIDENCE = CLAIMS / "evidence"
FREEZE = EVIDENCE / "10-quality-gold-freeze-20261008-r2"
REVIEW = EVIDENCE / "10-quality-gold-expansion-20261008-r2"
SOURCE_EXPORT = EVIDENCE / "10-quality-gold-expansion-20261008-r1" / "source-prose-units.json"
SEMANTICS = ROOT / "plugins" / "corpus" / "material_semantics.py"
LEDGER = ROOT / "plugins" / "corpus" / "structured" / "ledger.py"

ITEMS_PROTOCOL = MATERIAL_SELECTOR_JSONL_VERSION
SELECTOR_MAX_SLOTS = 24
SELECTOR_MAX_ITEMS = 64
SELECTOR_MAX_TOKENS = 8192

# Proposed thresholds. These are NOT self-authorized: they must be countersigned
# by the human adjudicator before any live extraction may run.
PROPOSED_TARGET_RECALL_OVERALL_MIN = 0.85
PROPOSED_TARGET_RECALL_PER_SOURCE_MIN = 0.80
PROPOSED_CANDIDATE_PRECISION_MIN = 0.80
PROPOSED_ACCEPTED_RECORDS_TOTAL_MIN = 40


class FrozenReader:
    """Read a signed snapshot payload from frozen bytes only."""

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


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(path: Path) -> str:
    return "sha256:" + file_sha256(path)


def atomic_write(path: Path, content: str) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".pending", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary)


def request_options() -> RequestOptions:
    # Mirrors the calibrated provider ceiling used on the closed relation line.
    return RequestOptions(
        timeout_seconds=300.0,
        max_output_tokens=262144,
        token_parameter="max_tokens",
        reasoning_effort="minimal",
    )


def config() -> ExtractionConfig:
    result = load_extraction_config(dotenv_path=ROOT / ".env", options=request_options())
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


def scoped_sources() -> list[dict[str, Any]]:
    """Return the signed candidate input scope with reused snapshot construction."""

    freeze_state = read_json(FREEZE / "freeze-state.json")
    if not freeze_state["formal_gold_frozen"] or not freeze_state["candidate_execution_authorized"]:
        raise ValueError("signed freeze does not authorize candidate execution")
    contract = read_json(REVIEW / "scoring-contract.json")
    export = read_json(SOURCE_EXPORT)
    sources = {f"sha256:{item['source_sha256']}": item for item in export["sources"]}
    result: list[dict[str, Any]] = []
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
            "freeze": file_sha256(FREEZE / "freeze-manifest.json"),
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
        result.append(
            {
                "slug": source_slug(path),
                "source_id": scoped["source_id"],
                "locators": list(scoped["locators"]),
                "snapshot": snapshot,
            }
        )
    return result


def item_assertion_ids(contract: dict[str, Any]) -> list[str]:
    ids = sorted(key for key in contract["review_assertions"] if re.fullmatch(r"NT-I\d+", key))
    return ids


def build_gate(
    contract: dict[str, Any],
    freeze_state: dict[str, Any],
    sources: list[dict[str, Any]],
    batch_counts: dict[str, int],
) -> dict[str, Any]:
    item_ids = item_assertion_ids(contract)
    return {
        "schema_version": "items-only-quality-gate-preregistration-1",
        "created_on": "2026-10-10",
        "status": "frozen_before_execution",
        "issue": "28-items-only-quality-gate-preregistration",
        "role_scope": ["material_items"],
        "protocol": {
            "material_items": ITEMS_PROTOCOL,
            "extractor_version": MATERIAL_EXTRACTOR_VERSION,
            "items_validation_version": MATERIAL_ITEMS_VALIDATION_VERSION,
            "slot_batching_version": MATERIAL_SLOT_BATCHING_VERSION,
            "relations_default_off": True,
        },
        "gold": {
            "source": ".scratch/claims-r2-role-isolation/evidence/10-quality-gold-freeze-20261008-r2",
            "freeze_manifest_sha256": digest(FREEZE / "freeze-manifest.json"),
            "freeze_state_sha256": digest(FREEZE / "freeze-state.json"),
            "frozen_gold_sha256": digest(FREEZE / "frozen-gold.json"),
            "scoring_contract_sha256": digest(REVIEW / "scoring-contract.json"),
            "evaluation_scope": freeze_state["evaluation_scope"],
            "reviewer": freeze_state["reviewer"],
            "adjudicator": freeze_state["adjudicator"],
            "gold_counts": freeze_state["counts"],
            "material_items_target_total": freeze_state["counts"]["material_items"],
            "per_source": [
                {
                    "slug": item["slug"],
                    "source_id": item["source_id"],
                    "locators": item["locators"],
                }
                for item in sources
            ],
        },
        "execution_requirements": {
            "claims_attempts": 0,
            "material_relations_attempts": 0,
            "automatic_retries": 0,
            "concurrency": 1,
            "gold_not_exposed_to_model": True,
            "production_database_access": 0,
            "protocol_status_required": "valid",
            "execution_status_required": "succeeded",
            "context_status_required": "complete",
            "failed_batches_max": 0,
            "partial_batches_max": 0,
            "missing_duplicate_invalid_max": 0,
            "material_items_attempts_max": dict(batch_counts),
            "completed_batches_min": dict(batch_counts),
        },
        "quality_requirements_status": "proposed_pending_human_signoff",
        "quality_requirements": {
            "metric_basis": contract["schema_version"],
            "evaluation_scope": contract["evaluation_scope"],
            "material_items_target_total": freeze_state["counts"]["material_items"],
            "target_recall_overall_min": PROPOSED_TARGET_RECALL_OVERALL_MIN,
            "target_recall_per_source_min": PROPOSED_TARGET_RECALL_PER_SOURCE_MIN,
            "candidate_precision_min": PROPOSED_CANDIDATE_PRECISION_MIN,
            "unresolved_candidates_max": 0,
            "accepted_records_total_min": PROPOSED_ACCEPTED_RECORDS_TOTAL_MIN,
            "accepted_records_per_source_min": contract["minimum_accepted_records_per_role"],
            "role_required_fields": contract["role_required_fields"]["material_items"],
            "semantic_types": contract["semantic_types"],
            "statement_roles": contract["statement_roles"],
            "perspectives": contract["perspectives"],
            "high_risk_item_assertions_required": item_ids,
            "high_risk_item_annotations": {
                key: contract["review_assertions"][key] for key in item_ids
            },
        },
        "consumption_closure": {
            "chain": [
                "publish",
                "positive_query",
                "delivery",
                "context_use",
                "report_reference",
            ],
            "zero_call_stages": ["publish", "positive_query"],
            "model_call_stages": ["delivery", "context_use", "report_reference"],
            "stage_pass_conditions": {
                "publish": (
                    "accepted items artifact is published with stable item ids and "
                    "verbatim evidence spans; verifiable without any model call"
                ),
                "positive_query": (
                    "a positive query with a known-true predicate returns at least one "
                    "published item whose evidence pointer is correct; zero model calls"
                ),
                "delivery": (
                    "published items are delivered into the consuming report context with "
                    "provenance preserved; requires an authorized live path"
                ),
                "context_use": (
                    "delivered items are actually referenced by the report reasoning; "
                    "requires an authorized live path"
                ),
                "report_reference": (
                    "the final report cites the item with traceable evidence back to the "
                    "signed snapshot; requires an authorized live path"
                ),
            },
            "claim_boundary": "proves the tested scope is connected only, not full coverage",
        },
        "scope_constraints": {
            "new_gold_allowed": False,
            "threshold_relaxation_after_execution_allowed": False,
            "prompt_revision_after_execution_allowed": False,
            "protocol_or_extractor_change_after_execution_allowed": False,
            "holdout_accessed": False,
            "publication_authorized": False,
            "query_delivery_context_use_authorized": False,
            "production_database_access_authorized": False,
        },
        "authorization": {
            "note": (
                "Every entry must be filled by an explicit human decision; this gate "
                "authorizes nothing on its own."
            ),
            "items_live_extraction": {
                "authorized": False,
                "authorized_by": None,
                "authorized_on": None,
                "attempts_max": None,
                "model": None,
            },
            "publication": {
                "authorized": False,
                "authorized_by": None,
                "authorized_on": None,
            },
            "positive_query_delivery_context_use": {
                "authorized": False,
                "authorized_by": None,
                "authorized_on": None,
            },
            "production_database_access": {
                "authorized": False,
                "authorized_by": None,
                "authorized_on": None,
            },
        },
        "countersignature": {
            "required": True,
            "status": "pending_human_signoff",
            "reviewer": None,
            "signed_on": None,
        },
        "terminal_decision": {
            "on_pass": (
                "items-only quality gate satisfied; proceed to authorized positive "
                "consumption closure"
            ),
            "on_fail": (
                "close current model plus extractor route; no prompt or threshold "
                "relaxation; no new gold"
            ),
        },
    }


def main() -> None:
    extraction = config()
    profile = extraction.require_profile()
    freeze_state = read_json(FREEZE / "freeze-state.json")
    contract = read_json(REVIEW / "scoring-contract.json")
    sources = scoped_sources()

    plans: dict[str, BatchPlan] = {}
    batch_counts: dict[str, int] = {}
    slot_counts: dict[str, int] = {}
    for item in sources:
        snapshot = item["snapshot"]
        snapshot.verify_identity()
        material_document = evidence_document_from_snapshot(snapshot, role="material_items")
        candidate_slots = build_candidate_slots(
            material_document, build_material_structure(material_document)
        )
        batches = build_candidate_slot_batches(
            candidate_slots,
            max_slots_per_batch=SELECTOR_MAX_SLOTS,
            max_items_per_batch=SELECTOR_MAX_ITEMS,
            max_estimated_tokens_per_batch=SELECTOR_MAX_TOKENS,
        )
        if not batches:
            raise ValueError(f"no material-items batches for {item['slug']}")
        n = len(batches)
        plan = plan_batch(
            snapshot,
            config=extraction,
            max_attempts=n,
            role_max_attempts={"claims": 0, "material_items": n, "material_relations": 0},
            relations_enabled=False,
            enabled_roles=("material_items",),
            max_items_per_packet=SELECTOR_MAX_ITEMS,
            max_slots_per_batch=SELECTOR_MAX_SLOTS,
            max_estimated_tokens_per_batch=SELECTOR_MAX_TOKENS,
            material_items_protocol=ITEMS_PROTOCOL,
        )
        plan.verify_identity()
        counts = {
            role: sum(task.role == role for task in plan.tasks)
            for role in ("claims", "material_items", "material_relations")
        }
        if counts != {"claims": 0, "material_items": 1, "material_relations": 0}:
            raise ValueError(f"unexpected initial task plan: {item['slug']}: {counts}")
        if plan.role_max_attempts["material_items"] != n:
            raise ValueError(f"items budget mismatch: {item['slug']}")
        if plan.relations.enabled:
            raise ValueError(f"relations unexpectedly enabled: {item['slug']}")
        plans[item["slug"]] = plan
        batch_counts[item["slug"]] = n
        slot_counts[item["slug"]] = len(candidate_slots)

    gate = build_gate(contract, freeze_state, sources, batch_counts)

    for slug, plan in plans.items():
        atomic_write(HERE / f"plan-{slug}.json", plan.model_dump_json(indent=2))
    atomic_write(HERE / "preregistered-gate.json", json.dumps(gate, ensure_ascii=False, indent=2))

    manifest = {
        "schema_version": "items-only-quality-gate-freeze-manifest-1",
        "created_on": "2026-10-10",
        "status": "frozen_not_executed",
        "issue": "28-items-only-quality-gate-preregistration",
        "role_scope": ["material_items"],
        "protocol": ITEMS_PROTOCOL,
        "model": profile.model,
        "profile_sha256": profile.fingerprint,
        "request_options": profile.options.model_dump(mode="json"),
        "sources": [
            {
                "slug": slug,
                "batch_id": plan.batch_id,
                "plan_sha256": plan.plan_sha256,
                "snapshot_id": plan.snapshot.snapshot_id,
                "source_id": plan.snapshot.source_id,
                "candidate_slot_count": slot_counts[slug],
                "material_items_attempts_max": batch_counts[slug],
            }
            for slug, plan in plans.items()
        ],
        "inputs_sha256": {
            "frozen-gold.json": digest(FREEZE / "frozen-gold.json"),
            "freeze-state.json": digest(FREEZE / "freeze-state.json"),
            "freeze-manifest.json": digest(FREEZE / "freeze-manifest.json"),
            "scoring-contract.json": digest(REVIEW / "scoring-contract.json"),
            "source-prose-units.json": digest(SOURCE_EXPORT),
            "material_semantics.py": digest(SEMANTICS),
            "ledger.py": digest(LEDGER),
        },
        "files_sha256": {
            **{
                f"plan-{slug}.json": digest(HERE / f"plan-{slug}.json") for slug in plans
            },
            "preregistered-gate.json": digest(HERE / "preregistered-gate.json"),
        },
        "model_requests_during_freeze": 0,
        "production_database_access": 0,
        "holdout_accessed": False,
        "publication_authorized": False,
    }
    atomic_write(
        HERE / "freeze-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
    )
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "model": profile.model,
                "protocol": ITEMS_PROTOCOL,
                "sources": [
                    {
                        "slug": entry["slug"],
                        "batch_id": entry["batch_id"],
                        "material_items_attempts_max": entry["material_items_attempts_max"],
                        "snapshot_id": entry["snapshot_id"],
                    }
                    for entry in manifest["sources"]
                ],
                "gate_status": gate["status"],
                "model_requests": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
