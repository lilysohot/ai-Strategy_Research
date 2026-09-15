"""Run and score the frozen R2 development samples without corpus ingestion."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Callable
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from plugins.corpus.claims import build_default_llm, configured_model
from plugins.corpus.claims_v2 import triage_block_detail
from plugins.corpus.evidence import fingerprint
from plugins.corpus.evidence_pipeline import build_evidence_run
from plugins.corpus.material_semantics import (
    MATERIAL_SLOT_JSONL_VERSION,
    MaterialRun,
    build_candidate_slot_batches,
    build_candidate_slots,
    build_material_structure,
    extract_material_understanding,
)

ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "data/corpus/.audit/r1_material_gold_v1_20260913.json"
DEFAULT_BUDGET = ROOT / ".scratch/corpus-evidence-pipeline/r2-redesign-development-budget-v1.json"
OUT = ROOT / ".scratch/corpus-evidence-pipeline/material-semantics-runs"
MATERIAL_DEVELOPMENT_SCORER_VERSION = "material-development-scorer-2"


def normalized(value: object) -> str:
    return "".join(str(value or "").lower().split())


def quote_score(gold_item: dict[str, Any], predicted_item: dict[str, Any]) -> float:
    gold_quote = normalized(gold_item["evidence"][0]["quote"])
    predicted_quote = normalized(predicted_item["evidence"][0]["quote"])
    if not gold_quote or not predicted_quote:
        return 0.0
    ratio = SequenceMatcher(None, gold_quote, predicted_quote).ratio()
    if gold_quote in predicted_quote or predicted_quote in gold_quote:
        ratio = max(ratio, len(min((gold_quote, predicted_quote), key=len)) / len(gold_quote))
    return ratio


def match_items(
    gold_items: list[dict[str, Any]], predicted_items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    candidates = sorted(
        (
            (quote_score(gold, predicted), gold_index, predicted_index)
            for gold_index, gold in enumerate(gold_items)
            for predicted_index, predicted in enumerate(predicted_items)
        ),
        reverse=True,
    )
    used_gold: set[int] = set()
    used_predicted: set[int] = set()
    matches: list[dict[str, Any]] = []
    for score, gold_index, predicted_index in candidates:
        if score < 0.35 or gold_index in used_gold or predicted_index in used_predicted:
            continue
        used_gold.add(gold_index)
        used_predicted.add(predicted_index)
        matches.append(
            {
                "gold_index": gold_index,
                "predicted_index": predicted_index,
                "quote_similarity": round(score, 4),
            }
        )
    return sorted(matches, key=lambda value: value["gold_index"])


def speaker_category(role: object) -> str:
    value = normalized(role)
    for category, hints in {
        "host": ("host", "moderator", "主持"),
        "expert": ("expert", "专家"),
        "investor": ("investor", "questioner", "投资"),
        "quoted": ("quoted", "公告", "总工"),
        "author": ("author", "analyst", "作者", "分析师", "研报", "证券"),
        "mixed": ("mixed", "ambiguous"),
    }.items():
        if any(hint in value for hint in hints):
            return category
    return value


def attempted_calls(material_run: MaterialRun) -> int:
    declared = sum(packet.model_calls for packet in material_run.packet_runs)
    if declared:
        return declared
    return sum(
        packet.status in {"completed", "partial", "failed"} for packet in material_run.packet_runs
    )


def capture_responses(llm: Callable[[str], str], sink: list[str | None]) -> Callable[[str], str]:
    def audited(prompt: str) -> str:
        try:
            response = llm(prompt)
        except Exception:
            sink.append(None)
            raise
        sink.append(str(response))
        return response

    return audited


def score_sample(sample: dict[str, Any], material_run: Any) -> dict[str, Any]:
    predicted = material_run.understanding.model_dump(mode="json")
    gold_items = sample["items"]
    predicted_items = predicted["items"]
    matches = match_items(gold_items, predicted_items)
    match_by_gold = {match["gold_index"]: match for match in matches}
    gold_speakers = {speaker["speaker_id"]: speaker for speaker in sample["speakers"]}
    predicted_speakers = {speaker["speaker_id"]: speaker for speaker in predicted["speakers"]}
    detail: list[dict[str, Any]] = []
    semantic_correct = 0
    attribution_correct = 0
    critical_matched = 0
    critical_fields_correct = 0
    endpoint_map: dict[str, str] = {}
    for gold_index, gold_item in enumerate(gold_items):
        match = match_by_gold.get(gold_index)
        if match is None:
            detail.append({"gold_item": gold_item["item_id"], "matched": False})
            continue
        predicted_item = predicted_items[match["predicted_index"]]
        endpoint_map[gold_item["item_id"]] = predicted_item["item_id"]
        semantic_ok = gold_item["semantic_type"] == predicted_item["semantic_type"]
        gold_speaker = gold_speakers[gold_item["speaker_ref"]]
        predicted_speaker = predicted_speakers[predicted_item["speaker_ref"]]
        gold_display = normalized(gold_speaker.get("display_name"))
        predicted_display = normalized(predicted_speaker.get("display_name"))
        display_match = bool(gold_display and predicted_display) and (
            gold_display in predicted_display or predicted_display in gold_display
        )
        gold_categories = {
            speaker_category(gold_speaker.get("role")),
            speaker_category(gold_speaker.get("display_name")),
        } - {"", "unknown"}
        predicted_categories = {
            speaker_category(predicted_speaker.get("role")),
            speaker_category(predicted_speaker.get("display_name")),
        } - {"", "unknown"}
        attribution_ok = display_match or bool(gold_categories & predicted_categories)
        field_checks = {
            "semantic_type": semantic_ok,
            "statement_role": gold_item["statement_role"] == predicted_item["statement_role"],
            "speech_role": gold_item["speech_role"] == predicted_item["speech_role"],
            "perspective": gold_item["perspective"] == predicted_item["perspective"],
            "speaker": attribution_ok,
            "identity_status": gold_speaker["identity_status"]
            == predicted_speaker["identity_status"],
            "polarity": gold_item["polarity"] == predicted_item["polarity"],
            "behavior_status": gold_item["behavior_status"] == predicted_item["behavior_status"],
            "temporal_frame": (
                gold_item["semantic_type"] != "behavior"
                or gold_item["temporal_frame"] == predicted_item["temporal_frame"]
            ),
            "value": normalized(gold_item["value"]) == normalized(predicted_item["value"]),
            "unknown_fields": set(gold_item["unknown_fields"])
            == set(predicted_item["unknown_fields"]),
        }
        semantic_correct += int(semantic_ok)
        attribution_correct += int(attribution_ok)
        if gold_item["critical"]:
            critical_matched += 1
            critical_fields_correct += int(all(field_checks.values()))
        detail.append(
            {
                "gold_item": gold_item["item_id"],
                "matched": True,
                "predicted_item": predicted_item["item_id"],
                "quote_similarity": match["quote_similarity"],
                "field_checks": field_checks,
                "predicted_text": predicted_item["text"],
            }
        )

    relation_matches = 0
    relation_false_positive = 0
    predicted_relations = predicted["relations"]
    expected_relations = {
        (
            relation["type"],
            endpoint_map.get(relation["from_item"]),
            endpoint_map.get(relation["to_item"]),
        )
        for relation in sample["relations"]
        if relation["from_item"] in endpoint_map and relation["to_item"] in endpoint_map
    }
    for relation in predicted_relations:
        key = (relation["type"], relation["from_item"], relation["to_item"])
        if key in expected_relations and relation["provenance"] == "source_explicit":
            relation_matches += 1
        elif (
            relation["provenance"] == "source_explicit"
            and relation["from_item"] in endpoint_map.values()
            and relation["to_item"] in endpoint_map.values()
        ):
            relation_false_positive += 1

    gold_count = len(gold_items)
    critical_count = sum(item["critical"] for item in gold_items)
    relation_count = len(sample["relations"])
    unscored_source_relations = max(
        0, len(predicted_relations) - relation_matches - relation_false_positive
    )
    return {
        "sample_id": sample["sample_id"],
        "source_rev": material_run.understanding.source.source_rev,
        "material_run_id": material_run.run_id,
        "summary": material_run.summary(),
        "item_recall": len(matches) / gold_count if gold_count else 1.0,
        "critical_item_recall": critical_matched / critical_count if critical_count else 1.0,
        "semantic_target_accuracy": semantic_correct / gold_count if gold_count else 1.0,
        "attribution_target_accuracy": attribution_correct / gold_count if gold_count else 1.0,
        "critical_all_fields_accuracy": (
            critical_fields_correct / critical_count if critical_count else 1.0
        ),
        "source_relation_recall": relation_matches / relation_count if relation_count else 1.0,
        "source_relation_precision": (
            relation_matches / (relation_matches + relation_false_positive)
            if relation_matches + relation_false_positive
            else (1.0 if relation_count == 0 else 0.0)
        ),
        "source_relation_precision_scope": "selected_target_endpoints_only",
        "counts": {
            "gold_items": gold_count,
            "matched_items": len(matches),
            "predicted_items": len(predicted_items),
            "unmatched_predicted_items": len(predicted_items) - len(matches),
            "critical_items": critical_count,
            "matched_critical_items": critical_matched,
            "semantic_correct": semantic_correct,
            "attribution_correct": attribution_correct,
            "critical_all_fields_correct": critical_fields_correct,
            "gold_relations": relation_count,
            "predicted_relations": len(predicted_relations),
            "matched_relations": relation_matches,
            "false_positive_relations": relation_false_positive,
            "unscored_source_relations": unscored_source_relations,
        },
        "detail": detail,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-report", type=Path)
    parser.add_argument("--round", dest="round_id")
    parser.add_argument("--budget", type=Path, default=DEFAULT_BUDGET)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    budget_path = args.budget.resolve()
    budget = json.loads(budget_path.read_text(encoding="utf-8"))
    gold_file_sha256 = hashlib.sha256(GOLD.read_bytes()).hexdigest()
    if gold_file_sha256 != budget["gold_sha256"]:
        raise ValueError("redesign budget is not bound to the current frozen gold")
    if budget["split"] != "development" or budget["holdout_calls_allowed"] != 0:
        raise ValueError("redesign budget must forbid holdout access")
    sample_by_id = {sample["sample_id"]: sample for sample in gold["samples"]}
    samples = [sample_by_id[sample_id] for sample_id in budget["sample_ids"]]
    if any(sample["split"] != "development" for sample in samples):
        raise ValueError("redesign budget contains a non-development sample")
    for sample in samples:
        source = ROOT / sample["source_path"]
        from hashlib import sha256

        if sha256(source.read_bytes()).hexdigest() != sample["source_sha256"]:
            raise ValueError(f"source identity mismatch: {sample['sample_id']}")
    deterministic_stress: list[dict[str, Any]] = []
    for sample in budget.get("deterministic_stress_samples", []):
        if sample.get("model_calls_allowed") != 0:
            raise ValueError("stress samples must forbid model calls")
        source = ROOT / sample["source_path"]
        if hashlib.sha256(source.read_bytes()).hexdigest() != sample["source_sha256"]:
            raise ValueError(f"stress source identity mismatch: {sample['sample_id']}")
        stress_run = build_evidence_run(source, packet_chars=budget["packet_chars"])
        stress_structure = build_material_structure(stress_run.document)
        stress_slots = build_candidate_slots(stress_run.document, stress_structure)
        stress_batches = build_candidate_slot_batches(
            stress_slots,
            max_slots_per_batch=budget.get("max_slots_per_batch", 8),
            max_items_per_batch=budget.get("max_items_per_packet", 30),
        )
        deterministic_stress.append(
            {
                "sample_id": sample["sample_id"],
                "source_rev": stress_run.document.source_rev,
                "packets": len(stress_run.document.packets),
                "segments": len(stress_structure.segments),
                "candidate_slots": len(stress_slots),
                "atomic_batches": len(stress_batches),
                "dialogue_structure": stress_structure.dialogue_structure,
                "attribution_capability": stress_structure.attribution_capability,
                "processing_mode": stress_structure.processing_mode,
                "signal_types": sorted(
                    {signal for slot in stress_slots for signal in slot.signal_types}
                ),
                "model_calls": 0,
            }
        )
    OUT.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    calls = 0
    usage: dict[str, int] = {}
    raw_audits: list[dict[str, str]] = []
    if args.replay_report:
        previous = json.loads(args.replay_report.read_text(encoding="utf-8"))
        previous_by_id = {sample["sample_id"]: sample for sample in previous["samples"]}
        model = previous["model"]
        for sample in samples:
            previous_sample = previous_by_id[sample["sample_id"]]
            material_run = MaterialRun.model_validate_json(
                (
                    args.replay_report.parent / f"{previous_sample['material_run_id']}.json"
                ).read_text(encoding="utf-8")
            )
            material_run.verify_identity()
            results.append(score_sample(sample, material_run))
    else:
        if args.round_id not in budget["round_ids"]:
            parser.error("model execution requires one frozen --round id")
        previous_budget_reports = []
        for candidate in OUT.glob("report-*.json"):
            try:
                saved = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if saved.get("budget_version") == budget["budget_version"] and not saved.get(
                "replay_of"
            ):
                previous_budget_reports.append(saved)
        if any(saved.get("round_id") == args.round_id for saved in previous_budget_reports):
            raise ValueError(f"redesign round already consumed: {args.round_id}")
        if len(previous_budget_reports) >= budget["development_rounds_max"]:
            raise ValueError("redesign development round budget exhausted")

        planned_runs = {}
        planned_calls = 0
        for sample in samples:
            evidence_run = build_evidence_run(
                ROOT / sample["source_path"],
                pages=tuple(sample["scoped_pages"]) if "scoped_pages" in sample else None,
                packet_chars=budget["packet_chars"],
            )
            if budget.get("response_format") == MATERIAL_SLOT_JSONL_VERSION:
                structure = build_material_structure(evidence_run.document)
                candidate_slots = build_candidate_slots(evidence_run.document, structure)
                selected_slot_ids = frozenset(
                    budget.get("candidate_slot_ids_by_sample", {}).get(sample["sample_id"], ())
                )
                if selected_slot_ids:
                    available_slot_ids = {slot.candidate_slot_id for slot in candidate_slots}
                    if selected_slot_ids - available_slot_ids:
                        raise ValueError(
                            f"frozen candidate slot scope drifted: {sample['sample_id']}"
                        )
                    candidate_slots = tuple(
                        slot
                        for slot in candidate_slots
                        if slot.candidate_slot_id in selected_slot_ids
                    )
                candidate_packets = len({slot.packet_id for slot in candidate_slots})
                item_batches = build_candidate_slot_batches(
                    candidate_slots,
                    max_slots_per_batch=budget.get("max_slots_per_batch", 8),
                    max_items_per_batch=budget.get("max_items_per_packet", 30),
                )
                relation_calls = (
                    candidate_packets
                    if budget.get("relation_mode", "atomic_decisions") != "deferred"
                    else 0
                )
                # Every finite item batch is mandatory. When relation validation is enabled,
                # reserve one decision call per candidate packet.
                candidate_calls = len(item_batches) + relation_calls
            else:
                candidate_packets = sum(
                    packet.status == "available"
                    and packet.kind != "table"
                    and triage_block_detail(packet.text).candidate
                    for packet in evidence_run.document.packets
                )
                candidate_calls = candidate_packets * len(budget.get("stages", ["combined"]))
            if candidate_calls > budget["calls_per_document_per_round_max"]:
                raise ValueError(f"per-document call budget exceeded: {sample['sample_id']}")
            planned_calls += candidate_calls
            planned_runs[sample["sample_id"]] = evidence_run
        consumed_calls = 0
        for saved in previous_budget_reports:
            for saved_sample in saved.get("samples", []):
                saved_run = MaterialRun.model_validate_json(
                    (OUT / f"{saved_sample['material_run_id']}.json").read_text(encoding="utf-8")
                )
                consumed_calls += attempted_calls(saved_run)
        if planned_calls > budget["calls_per_round_max"]:
            raise ValueError("planned calls exceed the frozen per-round budget")
        if planned_calls != budget.get("planned_calls_upper_bound", planned_calls):
            raise ValueError("deterministic plan differs from the frozen call upper bound")
        if consumed_calls + planned_calls > budget["calls_total_max"]:
            raise ValueError("planned calls exceed the frozen total budget")
        if args.plan_only:
            print(
                json.dumps(
                    {
                        "budget_version": budget["budget_version"],
                        "round_id": args.round_id,
                        "planned_calls_upper_bound": planned_calls,
                        "previously_consumed_calls": consumed_calls,
                        "deterministic_stress": deterministic_stress,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        load_dotenv(ROOT / ".env")
        os.environ["CORPUS_LLM_TIMEOUT"] = str(budget["seconds_per_call"])
        os.environ["CORPUS_LLM_MAX_TOKENS"] = str(budget["max_output_tokens"])
        llm = build_default_llm(usage)
        model = configured_model()
        if model != budget["model"]:
            raise ValueError(f"configured model {model!r} does not match frozen budget")
        for sample in samples:
            evidence_run = planned_runs[sample["sample_id"]]
            if evidence_run.document.source_rev != sample["source_rev"]:
                raise ValueError(f"runtime source_rev mismatch: {sample['sample_id']}")
            captured: list[str | None] = []
            material_run = extract_material_understanding(
                evidence_run,
                llm=capture_responses(llm, captured),
                max_calls=budget["calls_per_document_per_round_max"],
                material_type=sample["material_type"],
                staged_jsonl=budget.get("response_format")
                in {"material-jsonl-v1", MATERIAL_SLOT_JSONL_VERSION},
                slot_protocol=budget.get("response_format") == MATERIAL_SLOT_JSONL_VERSION,
                max_items_per_packet=budget.get("max_items_per_packet", 30),
                max_slots_per_batch=budget.get("max_slots_per_batch", 8),
                extract_relations=budget.get("relation_mode", "atomic_decisions") != "deferred",
                candidate_slot_ids=tuple(
                    budget.get("candidate_slot_ids_by_sample", {}).get(sample["sample_id"], ())
                )
                or None,
            )
            material_run.verify_identity()
            calls += attempted_calls(material_run)
            capture_index = 0
            stage_names = budget.get("stages", ["combined"])
            for packet_run in material_run.packet_runs:
                for stage_index in range(packet_run.model_calls or 0):
                    raw_response = (
                        captured[capture_index] if capture_index < len(captured) else None
                    )
                    capture_index += 1
                    if packet_run.status not in {"failed", "partial"} or raw_response is None:
                        continue
                    audit_dir = (
                        OUT
                        / "raw-audit"
                        / budget["budget_version"]
                        / args.round_id
                        / sample["sample_id"]
                    )
                    audit_dir.mkdir(parents=True, exist_ok=True)
                    stage = stage_names[min(stage_index, len(stage_names) - 1)]
                    response_sha256 = hashlib.sha256(raw_response.encode()).hexdigest()
                    audit_path = (
                        audit_dir / f"{packet_run.packet_id}-{stage}-{response_sha256[:12]}.txt"
                    )
                    audit_path.write_text(raw_response, encoding="utf-8")
                    audit_path.chmod(0o600)
                    raw_audits.append(
                        {
                            "sample_id": sample["sample_id"],
                            "packet_id": packet_run.packet_id,
                            "stage": stage,
                            "response_sha256": response_sha256,
                            "path": str(audit_path),
                        }
                    )
            artifact = OUT / f"{material_run.run_id}.json"
            artifact.write_text(material_run.model_dump_json(indent=2), encoding="utf-8")
            results.append(score_sample(sample, material_run))
    for result in results:
        print(json.dumps({k: v for k, v in result.items() if k != "detail"}, ensure_ascii=False))
    thresholds = gold["thresholds"]
    totals = {key: sum(result["counts"][key] for result in results) for key in results[0]["counts"]}
    relation_predictions = totals["matched_relations"] + totals["false_positive_relations"]
    aggregate = {
        "item_recall": totals["matched_items"] / totals["gold_items"],
        "critical_item_recall": totals["matched_critical_items"] / totals["critical_items"],
        "semantic_target_accuracy": totals["semantic_correct"] / totals["gold_items"],
        "attribution_target_accuracy": totals["attribution_correct"] / totals["gold_items"],
        "critical_all_fields_accuracy": (
            totals["critical_all_fields_correct"] / totals["critical_items"]
        ),
        "source_relation_recall": totals["matched_relations"] / totals["gold_relations"],
        "source_relation_precision": (
            totals["matched_relations"] / relation_predictions if relation_predictions else 1.0
        ),
        "source_relation_precision_scope": "selected_target_endpoints_only",
        "unmatched_predicted_items": totals["unmatched_predicted_items"],
        "unscored_source_relations": totals["unscored_source_relations"],
    }
    acceptance = (
        aggregate["item_recall"] >= thresholds["item_recall_min"]
        and aggregate["critical_item_recall"] >= thresholds["critical_item_recall"]
        and aggregate["semantic_target_accuracy"] >= thresholds["semantic_recall_min"]
        and aggregate["attribution_target_accuracy"] >= thresholds["attribution_accuracy"]
        and aggregate["critical_all_fields_accuracy"] == 1.0
        and aggregate["source_relation_recall"] >= thresholds["source_relation_recall_min"]
        and aggregate["source_relation_precision"] >= thresholds["source_relation_precision"]
        and all(result["summary"]["complete"] for result in results)
    )
    report = {
        "scorer_version": MATERIAL_DEVELOPMENT_SCORER_VERSION,
        "contract_version": gold["contract_version"],
        "gold_sha256": fingerprint(json.loads(GOLD.read_text(encoding="utf-8"))),
        "gold_file_sha256": gold_file_sha256,
        "budget_version": budget["budget_version"] if not args.replay_report else None,
        "budget_sha256": hashlib.sha256(budget_path.read_bytes()).hexdigest()
        if not args.replay_report
        else None,
        "round_id": args.round_id if not args.replay_report else None,
        "split": "development",
        "model": model,
        "model_calls": calls,
        "usage": usage,
        "raw_audits": raw_audits,
        "deterministic_stress": deterministic_stress,
        "samples": results,
        "aggregate": aggregate,
        "business_acceptance": acceptance,
        "replay_of": str(args.replay_report) if args.replay_report else None,
        "limitations": [
            "Development targets are a selected joint gold, not exhaustive whole-document claims.",
            "Extra items and relations are counted but cannot be scored as false positives without exhaustive negative gold.",
            "Source relation precision covers only predictions whose endpoints map to selected gold items.",
            "No corpus ingestion or database write is performed.",
        ],
    }
    target = OUT / f"report-{fingerprint(report)}.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(target), "aggregate": aggregate, "accepted": acceptance}))
    return int(not acceptance)


if __name__ == "__main__":
    raise SystemExit(main())
