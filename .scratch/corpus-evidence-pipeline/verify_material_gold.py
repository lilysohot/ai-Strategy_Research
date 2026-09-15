"""Deterministically verify the frozen R1 material contract/gold package."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "data/corpus/.audit/r1_material_gold_v1_20260913.json"
PRIOR_AUDIT = ROOT / "data/corpus/.audit/c1_full87_gold_candidates_20260912_merged_smoke30.csv"
PRIOR_MANIFESTS = (
    ROOT / ".scratch/corpus-evidence-pipeline/pilot_manifest.json",
    ROOT / ".scratch/corpus-evidence-pipeline/prose_holdout_manifest.json",
    ROOT / ".scratch/corpus-evidence-pipeline/expanded_holdout_manifest.json",
)
VALID_MATERIAL_TYPES = {
    "research_report",
    "earnings_call",
    "conference_minutes",
    "market_commentary",
    "personal_trade_log",
    "post_trade_review",
    "other",
    "unknown",
}
VALID_DOMAINS = {"company", "industry", "macro", "multi_asset", "unknown"}
VALID_SEMANTICS = {"fact", "forecast", "opinion", "behavior", "unknown"}
VALID_ROLES = {"claim", "evidence", "condition", "risk", "question", "answer", "other"}
VALID_SPEECH_ROLES = {"statement", "question", "answer", "unknown"}
VALID_PERSPECTIVES = {"source_explicit", "quoted_other", "system_synthesis", "unknown"}
VALID_POLARITY = {"affirmed", "negated", "mixed", "unknown"}
VALID_BEHAVIOR = {"intent", "claimed_executed", "claimed_not_executed", "unknown"}
VALID_TEMPORAL = {"contemporaneous", "retrospective", "unknown"}
VALID_RELATIONS = {
    "supports",
    "challenges",
    "conditions",
    "invalidates",
    "answers",
    "motivates",
    "attributes",
    "elaborates",
}


def fail(message: str) -> None:
    raise ValueError(message)


def normalized(text: str) -> str:
    return re.sub(r"\s+", "", text)


def unique_alignment(quote: str, page_text: str) -> bool:
    needle = normalized(quote)
    return bool(needle) and normalized(page_text).count(needle) == 1


def prior_source_revs() -> set[str]:
    if not PRIOR_AUDIT.exists():
        fail(f"missing prior audit: {PRIOR_AUDIT}")
    with PRIOR_AUDIT.open(encoding="utf-8-sig", newline="") as stream:
        return {row["doc_id"].rsplit("_", 1)[-1] for row in csv.DictReader(stream)}


def prior_manifest_patterns() -> list[str]:
    patterns: list[str] = []
    for manifest in PRIOR_MANIFESTS:
        if not manifest.exists():
            fail(f"missing prior manifest: {manifest}")
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        patterns.extend(sample["pattern"] for sample in payload["samples"])
    return patterns


def require_keys(value: dict[str, Any], keys: set[str], context: str) -> None:
    missing = sorted(keys - value.keys())
    if missing:
        fail(f"{context}: missing keys {missing}")


def evidence_context(
    evidence: dict[str, Any],
    *,
    sample_id: str,
    pages: dict[int, str],
    lines: list[str],
    scoped_lines: set[int],
) -> tuple[str, str]:
    if "page" in evidence:
        page = evidence["page"]
        if page not in pages:
            fail(f"evidence outside scoped pages: {sample_id} p{page}")
        return pages[page], f"p{page}"
    if "line_start" in evidence and "line_end" in evidence:
        start = evidence["line_start"]
        end = evidence["line_end"]
        if start > end or not set(range(start, end + 1)) <= scoped_lines:
            fail(f"evidence outside scoped lines: {sample_id} L{start}-{end}")
        return "\n".join(lines[start - 1 : end]), f"L{start}-{end}"
    fail(f"evidence lacks a supported locator: {sample_id}")


def verify() -> dict[str, Any]:
    payload = json.loads(GOLD.read_text(encoding="utf-8"))
    require_keys(
        payload,
        {"contract_version", "budgets", "thresholds", "stop_conditions", "coverage", "samples"},
        "gold",
    )
    if payload["contract_version"] != "material-understanding-v1":
        fail("wrong contract_version")
    if not payload.get("frozen_before_r2_execution"):
        fail("gold was not frozen before R2")
    if payload["budgets"]["calls_total_max"] != (
        payload["budgets"]["development_calls_total_max"]
        + payload["budgets"]["holdout_calls_total_max"]
    ):
        fail("inconsistent call budget")
    if not payload["stop_conditions"]:
        fail("stop conditions must be frozen")

    splits = Counter(sample["split"] for sample in payload["samples"])
    if splits != {"development": 4, "holdout": 2}:
        fail(f"expected 4 development + 2 holdout, got {dict(splits)}")

    prior_revs = prior_source_revs()
    prior_patterns = prior_manifest_patterns()
    sample_ids: set[str] = set()
    source_revs: set[str] = set()
    item_ids: set[str] = set()
    relation_ids: set[str] = set()
    aligned_quotes = 0
    critical_items = 0
    semantic_counts: Counter[str] = Counter()
    behavior_states: Counter[str] = Counter()
    holdout_prior_collisions: list[str] = []
    holdout_prior_manifest_collisions: list[str] = []

    for sample in payload["samples"]:
        require_keys(
            sample,
            {
                "sample_id",
                "split",
                "source_path",
                "source_rev",
                "source_sha256",
                "material_type",
                "research_domain",
                "speakers",
                "items",
                "relations",
            },
            "sample",
        )
        if sample["sample_id"] in sample_ids:
            fail(f"duplicate sample_id: {sample['sample_id']}")
        sample_ids.add(sample["sample_id"])
        if sample["source_rev"] in source_revs:
            fail(f"duplicate source_rev: {sample['source_rev']}")
        source_revs.add(sample["source_rev"])
        if sample["material_type"] not in VALID_MATERIAL_TYPES:
            fail(f"invalid material_type: {sample['material_type']}")
        if sample["research_domain"] not in VALID_DOMAINS:
            fail(f"invalid research_domain: {sample['research_domain']}")

        source = ROOT / sample["source_path"]
        if not source.is_file():
            fail(f"missing source: {source}")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != sample["source_sha256"] or digest[:16] != sample["source_rev"]:
            fail(f"source_identity_mismatch: {sample['sample_id']}")
        if sample["split"] == "holdout" and digest[:8] in prior_revs:
            holdout_prior_collisions.append(sample["sample_id"])
        if sample["split"] == "holdout" and any(
            fnmatch(source.name, pattern) for pattern in prior_patterns
        ):
            holdout_prior_manifest_collisions.append(sample["sample_id"])

        pages: dict[int, str] = {}
        lines: list[str] = []
        scoped_lines = set(sample.get("scoped_lines", []))
        if source.suffix.lower() == ".pdf":
            if "scoped_pages" not in sample or scoped_lines:
                fail(f"PDF must define only scoped_pages: {sample['sample_id']}")
            reader = PdfReader(source)
            pages = {
                page: reader.pages[page - 1].extract_text() or ""
                for page in sample["scoped_pages"]
            }
        elif source.suffix.lower() == ".md":
            if not scoped_lines or "scoped_pages" in sample:
                fail(f"Markdown must define only scoped_lines: {sample['sample_id']}")
            lines = source.read_text(encoding="utf-8").splitlines()
            if any(line < 1 or line > len(lines) for line in scoped_lines):
                fail(f"invalid scoped_lines: {sample['sample_id']}")
        else:
            fail(f"unsupported source type: {source.suffix}")

        speaker_ids = {speaker["speaker_id"] for speaker in sample["speakers"]}
        local_items: set[str] = set()

        for item in sample["items"]:
            require_keys(
                item,
                {
                    "item_id",
                    "text",
                    "semantic_type",
                    "statement_role",
                    "speech_role",
                    "perspective",
                    "speaker_ref",
                    "polarity",
                    "value",
                    "behavior_status",
                    "temporal_frame",
                    "evidence",
                    "unknown_fields",
                    "critical",
                },
                f"item in {sample['sample_id']}",
            )
            item_id = item["item_id"]
            if item_id in item_ids:
                fail(f"duplicate item_id: {item_id}")
            item_ids.add(item_id)
            local_items.add(item_id)
            if item["semantic_type"] not in VALID_SEMANTICS:
                fail(f"invalid semantic_type: {item_id}")
            if item["statement_role"] not in VALID_ROLES:
                fail(f"invalid statement_role: {item_id}")
            if item["speech_role"] not in VALID_SPEECH_ROLES:
                fail(f"invalid speech_role: {item_id}")
            if item["perspective"] not in VALID_PERSPECTIVES:
                fail(f"invalid perspective: {item_id}")
            if item["speaker_ref"] not in speaker_ids:
                fail(f"unknown speaker_ref: {item_id}")
            if item["polarity"] not in VALID_POLARITY:
                fail(f"invalid polarity: {item_id}")
            if item["temporal_frame"] not in VALID_TEMPORAL:
                fail(f"invalid temporal_frame: {item_id}")
            if item["semantic_type"] == "behavior":
                if item["behavior_status"] not in VALID_BEHAVIOR:
                    fail(f"behavior without valid behavior_status: {item_id}")
                behavior_states[item["behavior_status"]] += 1
            elif item["behavior_status"] is not None:
                fail(f"non-behavior has behavior_status: {item_id}")
            if (
                item["semantic_type"] == "forecast"
                and item["value"] is None
                and "numeric_value" not in item["unknown_fields"]
                and item["statement_role"] == "claim"
            ):
                fail(f"qualitative forecast must preserve numeric unknown: {item_id}")
            if not item["evidence"]:
                fail(f"item without evidence: {item_id}")
            for evidence in item["evidence"]:
                context, locator = evidence_context(
                    evidence,
                    sample_id=sample["sample_id"],
                    pages=pages,
                    lines=lines,
                    scoped_lines=scoped_lines,
                )
                if not unique_alignment(evidence["quote"], context):
                    fail(f"evidence_not_uniquely_aligned: {item_id} {locator}")
                aligned_quotes += 1
            semantic_counts[item["semantic_type"]] += 1
            critical_items += int(item["critical"])

        for relation in sample["relations"]:
            require_keys(
                relation,
                {"relation_id", "type", "from_item", "to_item", "provenance", "evidence", "critical"},
                f"relation in {sample['sample_id']}",
            )
            if relation["relation_id"] in relation_ids:
                fail(f"duplicate relation_id: {relation['relation_id']}")
            relation_ids.add(relation["relation_id"])
            if relation["type"] not in VALID_RELATIONS:
                fail(f"invalid relation type: {relation['relation_id']}")
            if relation["from_item"] not in local_items or relation["to_item"] not in local_items:
                fail(f"relation endpoint outside sample: {relation['relation_id']}")
            if relation["provenance"] not in {"source_explicit", "system_inferred"}:
                fail(f"invalid relation provenance: {relation['relation_id']}")
            for evidence in relation["evidence"]:
                context, locator = evidence_context(
                    evidence,
                    sample_id=sample["sample_id"],
                    pages=pages,
                    lines=lines,
                    scoped_lines=scoped_lines,
                )
                if not unique_alignment(evidence["quote"], context):
                    fail(
                        "relation evidence_not_uniquely_aligned: "
                        f"{relation['relation_id']} {locator}"
                    )
                aligned_quotes += 1

    if holdout_prior_collisions:
        fail(f"holdout leakage into prior audit: {holdout_prior_collisions}")
    if holdout_prior_manifest_collisions:
        fail(f"holdout leakage into prior manifests: {holdout_prior_manifest_collisions}")
    required_semantics = {"fact", "forecast", "opinion", "behavior", "unknown"}
    if not required_semantics <= semantic_counts.keys():
        fail(f"missing semantic gold: {sorted(required_semantics - semantic_counts.keys())}")
    if behavior_states["claimed_executed"] == 0:
        fail("missing claimed_executed behavior gold")
    if set(payload["coverage"]["missing_material_types"]) != {"earnings_call"}:
        fail("earnings-call coverage gap must remain explicit")
    if set(payload["coverage"]["missing_holdout_material_types"]) != {
        "earnings_call",
        "conference_minutes",
    }:
        fail("call/minutes holdout gap must remain explicit")

    return {
        "status": "passed",
        "contract_version": payload["contract_version"],
        "gold_sha256": hashlib.sha256(GOLD.read_bytes()).hexdigest(),
        "samples": dict(splits),
        "items": len(item_ids),
        "critical_items": critical_items,
        "relations": len(relation_ids),
        "aligned_quotes": aligned_quotes,
        "semantic_counts": dict(sorted(semantic_counts.items())),
        "behavior_states": dict(sorted(behavior_states.items())),
        "holdout_prior_audit_collisions": 0,
        "holdout_prior_manifest_collisions": 0,
        "coverage_gaps": payload["coverage"]["missing_material_types"],
        "holdout_coverage_gaps": payload["coverage"]["missing_holdout_material_types"],
        "model_calls": 0,
    }


if __name__ == "__main__":
    try:
        print(json.dumps(verify(), ensure_ascii=False, indent=2, sort_keys=True))
    except (KeyError, IndexError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2))
        sys.exit(1)
