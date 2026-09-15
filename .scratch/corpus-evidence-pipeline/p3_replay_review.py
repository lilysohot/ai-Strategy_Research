"""P3 development-only replay inventory and planner review queue.

Source and model text are untrusted data. This script never calls a model,
PostgreSQL, the old extractor, or any holdout source path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from plugins.corpus import _r2_runtime as runtime
from plugins.corpus._r2_plan import Packet, Scope, Source, digest, prepare, resolve, source_binding
from plugins.corpus.evidence_pipeline import build_evidence_run

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DEV_IDS = (
    "dev-company-report",
    "dev-industry-qa-report",
    "dev-personal-trade-review",
    "dev-expert-call-copper-foil",
)
MICRO_IDS = (
    "micro-company-recommendation",
    "micro-industry-q7-q8",
    "micro-trade-ttd",
    "micro-copper-summary",
    "micro-copper-audio",
    "micro-copper-yield",
)
GOLD = ROOT / "data/corpus/.audit/r1_material_gold_v1_20260913.json"
MICRO_GOLD = ROOT / "data/corpus/.audit/r2_material_micro_gold_v1_20260913.json"
REPORTS = {
    "v12": HERE
    / "material-semantics-runs/report-09b119120285666aac93fcb41ce1f8c0ebe3c4bb563f50a964bdc30b0b301b40.json",
    "v13": HERE
    / "material-semantics-runs/report-46caccfc1c7d23ef3858a8a501560c07b250888b0b3f189fdff75d8ba6bc6b4b.json",
}
BUDGETS = {
    "v12": HERE / "r2-v12-atomic-items-budget-v6.json",
    "v13": HERE / "r2-v13-final-items-budget-v7.json",
}
OLD_SCORES = {
    "v12": HERE
    / "material-semantics-runs/item-contract-score-v2-76525bcdee094fbb621db58a802afad78faeabc0f4573b4c61e8f45520c41e51.json",
    "v13": HERE
    / "material-semantics-runs/item-contract-score-v2-203a306ebfc2dc881fbbffc78a76b08d771a5b5c596c4cde87c3adadd40a04f0.json",
}
PINS = {
    "scope": (
        HERE / "r2-p3-change-scope.json",
        "1f4a25b1919460a2b941e1da4cd30d20d5775d79e08753c27d3a8979b27996d0",
    ),
    "p2b": (
        HERE / "r2-p2b-manifest.json",
        "85d587047b680b5c76ca985f63945ec243d69e7d16e8ddf35a5596144b72ab3f",
    ),
    "pg_review": (
        HERE / "r2-p2b-pg-readonly-manifest.json",
        "ec6738e40037067e1153b042054383484557c66b32332fce06f20e08da6ec1b8",
    ),
    "gold": (GOLD, "e8b541a6557189898bd8b86beab66af4b294cec19bc89c7d81e069f70ff0ac1b"),
    "micro_gold": (
        MICRO_GOLD,
        "214b1f49f82e36c7c2b59496ada20228730439d0bc4b6f17fc51ff87122077c5",
    ),
}
NEW_WIRE_REQUIRED = {
    "protocol_version",
    "plan_id",
    "obligation_id",
    "terminal",
    "item",
    "reason",
    "evidence_span_ids",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized(value: object) -> str:
    return "".join(str(value or "").lower().split()).replace("。", "").replace("，", ",")


def verify_pins() -> None:
    for path, expected in PINS.values():
        if sha(path) != expected:
            raise ValueError(f"frozen_pin_changed:{path.name}")


def load_inputs() -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    samples = {row["sample_id"]: row for row in gold["samples"] if row["sample_id"] in DEV_IDS}
    if tuple(samples) != DEV_IDS or any(row["split"] != "development" for row in samples.values()):
        raise ValueError("development_sample_boundary")
    micro = json.loads(MICRO_GOLD.read_text(encoding="utf-8"))
    if (
        micro.get("split") != "development"
        or tuple(row["scope_id"] for row in micro["scopes"]) != MICRO_IDS
    ):
        raise ValueError("development_micro_boundary")
    if any(row["sample_id"] not in samples for row in micro["scopes"]):
        raise ValueError("micro_sample_boundary")
    return samples, micro["scopes"]


def scope_text(scope: dict[str, Any]) -> str:
    path = (ROOT / scope["source_path"]).resolve()
    if not path.is_relative_to((ROOT / "data/corpus").resolve()):
        raise ValueError("source_path_boundary")
    if sha(path) != scope["source_sha256"]:
        raise ValueError("source_hash")
    locator = scope["locator"]
    if path.suffix.lower() == ".pdf":
        lines = (
            PdfReader(str(path)).pages[int(locator["page"]) - 1].extract_text() or ""
        ).splitlines()
    else:
        lines = path.read_text(encoding="utf-8").splitlines()
    start, end = int(locator["line_start"]), int(locator["line_end"])
    if not 1 <= start <= end <= len(lines):
        raise ValueError("locator_boundary")
    return "\n".join(lines[start - 1 : end])


def legacy_inventory(label: str, report_path: Path, budget_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    budget = json.loads(budget_path.read_text(encoding="utf-8"))
    if (
        report["split"] != "development"
        or tuple(report["samples"][i]["sample_id"] for i in range(4)) != DEV_IDS
    ):
        raise ValueError("legacy_development_boundary")
    if tuple(budget["sample_ids"]) != DEV_IDS or budget["holdout_calls_allowed"] != 0:
        raise ValueError("legacy_budget_boundary")
    terminals: dict[str, set[str]] = defaultdict(set)
    record_types: Counter[str] = Counter()
    invalid_json = 0
    new_wire_accepted = 0
    raw_rows = []
    base = (HERE / "material-semantics-runs/raw-audit").resolve()
    for audit in report["raw_audits"]:
        path = Path(audit["path"]).resolve()
        if not path.is_relative_to(base) or audit["sample_id"] not in DEV_IDS:
            raise ValueError("legacy_raw_boundary")
        raw = path.read_text(encoding="utf-8")
        if hashlib.sha256(raw.encode()).hexdigest() != audit["response_sha256"]:
            raise ValueError("legacy_raw_hash")
        rows, response_types = 0, Counter()
        for line in raw.splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                invalid_json += 1
                continue
            rows += 1
            kind = str(row.get("record_type", "missing")) if isinstance(row, dict) else "non_object"
            record_types[kind] += 1
            response_types[kind] += 1
            if isinstance(row, dict) and kind in {"item", "coverage"}:
                terminals[audit["sample_id"]].add(str(row.get("candidate_slot_id", "")))
                if set(row) >= NEW_WIRE_REQUIRED:
                    try:
                        runtime.ItemWire.model_validate(row)
                    except ValueError:
                        pass
                    else:
                        new_wire_accepted += 1
        raw_rows.append(
            {
                "sample_id": audit["sample_id"],
                "packet_id": audit["packet_id"],
                "response_sha256": audit["response_sha256"],
                "bytes": len(raw.encode()),
                "json_rows": rows,
                "record_types": dict(response_types),
            }
        )
    expected = {key: set(value) for key, value in budget["candidate_slot_ids_by_sample"].items()}
    coverage = {
        sample: {
            "expected": len(expected[sample]),
            "observed_unique_terminal_ids": len(terminals[sample]),
            "missing": len(expected[sample] - terminals[sample]),
            "unknown": len(terminals[sample] - expected[sample]),
        }
        for sample in DEV_IDS
    }
    score = json.loads(OLD_SCORES[label].read_text(encoding="utf-8"))
    metrics = score["metrics"]
    return {
        "version": label,
        "report_path": str(report_path.relative_to(ROOT)),
        "report_sha256": sha(report_path),
        "budget_path": str(budget_path.relative_to(ROOT)),
        "budget_sha256": sha(budget_path),
        "raw_response_count": len(raw_rows),
        "raw": raw_rows,
        "record_types": dict(record_types),
        "invalid_json_lines": invalid_json,
        "terminal_coverage": coverage,
        "legacy_score": {
            "path": str(OLD_SCORES[label].relative_to(ROOT)),
            "sha256": sha(OLD_SCORES[label]),
            "passed": score["passed"],
            "item_recall": metrics["item_recall"],
            "item_precision": metrics["item_precision"],
            "semantic_accuracy": metrics["semantic_accuracy"],
            "critical_errors": metrics["critical_errors"],
            "historical_only": True,
        },
        "new_wire_records_accepted": new_wire_accepted,
        "new_runtime_replay": "not_replayable",
        "not_replayable_reasons": [
            "legacy rows bind candidate_slot_id, not new plan_id/obligation_id",
            "legacy rows do not carry the new terminal/item envelope or evidence_span_ids",
            "legacy response_received/audit proof cannot be reconstructed from an OfflineGrant journal",
            "missing fields must not be copied from gold or synthesized by an adapter",
        ],
    }


def projected_plan(scope: dict[str, Any]) -> tuple[Source, Any]:
    text = scope_text(scope)
    locator = json.dumps(scope["locator"], sort_keys=True, separators=(",", ":"))
    packet = Packet(digest([scope["scope_id"], locator, scope["source_sha256"]]), locator, text)
    source = Source(
        digest([scope["source_sha256"], locator]),
        scope["source_sha256"],
        "p3-frozen-locator-projection-1",
        (packet,),
    )
    plan = prepare(source, source_binding(source), (Scope(packet.packet_id, 0, len(text)),))
    return source, plan


def micro_analysis(
    scopes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    summaries, queue = [], []
    for scope in scopes:
        source, plan = projected_plan(scope)
        obligations = []
        for obligation in plan.obligations:
            obligations.append((obligation, resolve(source, obligation.focus)))
        statuses = Counter()
        for item in scope["items"]:
            quote = normalized(item["quote"])
            matches = [
                (obligation, text)
                for obligation, text in obligations
                if quote in normalized(text) or normalized(text) in quote
            ]
            candidates = [entry for entry in matches if entry[0].state == "candidate"]
            if not matches:
                status = "missing_from_planner_focus"
            elif len(candidates) == 1 and len(matches) == 1:
                status = "human_atomicity_and_mapping_review_required"
            elif candidates:
                status = "ambiguous_candidate_mapping"
            else:
                status = "structurally_unresolved"
            statuses[status] += 1
            queue.append(
                {
                    "scope_id": scope["scope_id"],
                    "sample_id": scope["sample_id"],
                    "target_id": item["item_id"],
                    "target_quote": item["quote"],
                    "target_fields": {
                        key: item.get(key)
                        for key in (
                            "semantic_type",
                            "speaker_role",
                            "identity_status",
                            "perspective",
                            "speech_role",
                            "statement_role",
                            "polarity",
                            "behavior_status",
                            "temporal_frame",
                            "value",
                            "unknown_fields",
                        )
                    },
                    "mapping_status": status,
                    "review_status": "proposed_not_approved",
                    "matching_obligations": [
                        {
                            "obligation_id": obligation.obligation_id,
                            "state": obligation.state,
                            "reason": obligation.reason,
                            "focus_text": text,
                            "focus_sha256": obligation.focus.text_sha256,
                            "atomicity": obligation.atomicity,
                        }
                        for obligation, text in matches
                    ],
                }
            )
        summaries.append(
            {
                "scope_id": scope["scope_id"],
                "sample_id": scope["sample_id"],
                "selected_chars": plan.selected_chars,
                "gold_items": len(scope["items"]),
                "gold_relations": len(scope["relations"]),
                "gold_negative_relations": len(scope["negative_relations"]),
                "obligations": len(plan.obligations),
                "candidate_obligations": plan.candidate_count,
                "unresolved_obligations": plan.unresolved_count,
                "estimated_item_batches": math.ceil(plan.candidate_count / 8),
                "mapping_statuses": dict(statuses),
                "semantic_coverage": plan.semantic_coverage,
                "relation_status": plan.relation_status,
                "calls_authorized": plan.calls_authorized,
            }
        )
    return summaries, queue


def full_capacity(samples: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for sample_id in DEV_IDS:
        sample = samples[sample_id]
        path = (ROOT / sample["source_path"]).resolve()
        if (
            not path.is_relative_to((ROOT / "data/corpus").resolve())
            or sha(path) != sample["source_sha256"]
        ):
            raise ValueError("full_source_boundary")
        evidence = build_evidence_run(
            path,
            pages=tuple(sample.get("scoped_pages", ())) or None,
            packet_chars=3000,
        )
        scopes = tuple(
            Scope(packet.packet_id, 0, len(packet.text))
            for packet in evidence.document.packets
            if packet.text
        )
        base = {
            "sample_id": sample_id,
            "source_sha256": sample["source_sha256"],
            "packets": len(evidence.document.packets),
            "selected_roots": len(scopes),
            "selected_chars": sum(scope.end - scope.start for scope in scopes),
        }
        try:
            prepared = runtime.prepare(
                evidence,
                scopes,
                expected_evidence_sha=digest(evidence.model_dump(mode="json")),
            )
        except ValueError as exc:
            rows.append({**base, "status": "capacity_or_structure_rejected", "reason": str(exc)})
            continue
        rows.append(
            {
                **base,
                "status": "planned_not_semantically_verified",
                "obligations": len(prepared.plan.obligations),
                "candidate_obligations": prepared.plan.candidate_count,
                "unresolved_obligations": prepared.plan.unresolved_count,
                "item_batches": len(runtime.requests(prepared)),
                "max_request_bytes": max(
                    (len(raw.encode()) for _, raw in runtime.requests(prepared)), default=0
                ),
                "calls_authorized": prepared.plan.calls_authorized,
            }
        )
    return rows


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    verify_pins()
    samples, scopes = load_inputs()
    legacy = {
        label: legacy_inventory(label, REPORTS[label], BUDGETS[label]) for label in ("v12", "v13")
    }
    micro, queue = micro_analysis(scopes)
    capacity = full_capacity(samples)
    status_counts = Counter(row["mapping_status"] for row in queue)
    inventory = {
        "version": "r2-p3-replay-review-1",
        "split": "development",
        "development_sample_ids": list(DEV_IDS),
        "micro_scope_ids": list(MICRO_IDS),
        "source_paths_opened": [samples[sample_id]["source_path"] for sample_id in DEV_IDS],
        "holdout_source_paths_opened": 0,
        "model_calls": 0,
        "judge_calls": 0,
        "postgres_access": 0,
        "legacy": legacy,
        "micro_planner": micro,
        "full_capacity": capacity,
        "review_queue_counts": dict(status_counts),
        "gates": {
            "G0_identity_scope": "passed",
            "G1_terminal_capacity": "not_evaluated_for_new_model_output",
            "G2_content_fidelity": "not_evaluated_review_required",
            "G3_field_semantics": "not_evaluated_review_required",
            "G4_relations": "not_evaluated",
            "G5_old_flow_isolation": "passed_by_p2b_frozen_evidence",
            "G6_class_non_regression": "not_evaluated_no_new_protocol_outputs",
        },
        "p3_status": "blocked_by_non_replayable_legacy_wire_and_unapproved_atomic_mapping",
        "p4_budget_authorized": False,
    }
    queue_artifact = {
        "version": "r2-p3-human-review-queue-1",
        "split": "development",
        "contract_sha256": "feebd1fd816ff824345185f7e3d690ea25621080d9d348f7d53bb82650763776",
        "reviewer": None,
        "approved_records": 0,
        "instructions": "Human reviewer decides atomic denominator and exact obligation mapping. Agent proposals are not approvals.",
        "records": queue,
    }
    return inventory, queue_artifact


def write_once(path: Path, value: object) -> None:
    raw = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(raw)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--review-queue", type=Path, required=True)
    args = parser.parse_args()
    inventory, queue = build()
    write_once(args.inventory, inventory)
    write_once(args.review_queue, queue)
    print(
        json.dumps(
            {
                "inventory": str(args.inventory),
                "review_queue": str(args.review_queue),
                "p3_status": inventory["p3_status"],
                "review_queue_counts": inventory["review_queue_counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
