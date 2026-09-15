"""Versioned, zero-model R2 item-contract verifier.

This scorer is prospective for the final bounded item optimization.  It may replay
v12 as a diagnostic baseline, but it never changes the frozen v12 scorer result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from verify_material_micro_gold import (
    DEFAULT_MICRO_GOLD,
    SOURCE_GOLD,
    item_intersects_scope,
    normalized,
    scope_text,
    validate_micro_gold,
)

from plugins.corpus.evidence import fingerprint
from plugins.corpus.evidence_pipeline import build_evidence_run
from plugins.corpus.material_semantics import MaterialItem, MaterialRun

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = ROOT / ".scratch/corpus-evidence-pipeline/r2-item-acceptance-policy-v2.json"
OUT = ROOT / ".scratch/corpus-evidence-pipeline/material-semantics-runs"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def speaker_category(value: object) -> str:
    text = normalized(value)
    groups = {
        "host": ("host", "moderator", "主持"),
        "expert": ("expert", "专家"),
        "investor": ("investor", "questioner", "投资"),
        "quoted": ("quoted", "公告", "总工"),
        "author": ("author", "analyst", "作者", "分析师", "研报", "证券"),
        "mixed": ("mixed", "ambiguous"),
    }
    return next(
        (group for group, hints in groups.items() if any(hint in text for hint in hints)),
        text,
    )


def evidence_quote(item: MaterialItem) -> str:
    return item.evidence[0].quote if item.evidence else ""


def base_similarity(gold_quote: object, predicted_quote: object) -> float:
    gold = normalized(gold_quote)
    predicted = normalized(predicted_quote)
    if not gold or not predicted:
        return 0.0
    return SequenceMatcher(None, gold, predicted).ratio()


def match_scope_items(
    gold_items: list[dict[str, Any]], predicted_items: list[MaterialItem], threshold: float
) -> list[tuple[int, int, float, str]]:
    """Match one-to-one; short containment is accepted only when unambiguous."""
    containment_targets: dict[int, list[int]] = {}
    for predicted_index, predicted in enumerate(predicted_items):
        quote = normalized(evidence_quote(predicted))
        containment_targets[predicted_index] = [
            gold_index
            for gold_index, gold in enumerate(gold_items)
            if quote
            and (
                quote in normalized(gold["quote"])
                or normalized(gold["quote"]) in quote
            )
        ]
    candidates: list[tuple[float, int, int, str]] = []
    for gold_index, gold in enumerate(gold_items):
        for predicted_index, predicted in enumerate(predicted_items):
            method = "normalized_similarity"
            score = base_similarity(gold["quote"], evidence_quote(predicted))
            if containment_targets[predicted_index] == [gold_index]:
                score = 1.0
                method = "unique_containment"
            candidates.append((score, gold_index, predicted_index, method))
    used_gold: set[int] = set()
    used_predicted: set[int] = set()
    matches: list[tuple[int, int, float, str]] = []
    for score, gold_index, predicted_index, method in sorted(candidates, reverse=True):
        if score < threshold or gold_index in used_gold or predicted_index in used_predicted:
            continue
        used_gold.add(gold_index)
        used_predicted.add(predicted_index)
        matches.append((gold_index, predicted_index, score, method))
    return sorted(matches)


def uncertainty_axes(values: list[str] | tuple[str, ...]) -> set[str]:
    axes: set[str] = set()
    for raw in values:
        value = normalized(raw)
        if "identity" in value:
            axes.add("identity")
        if any(hint in value for hint in ("time", "date", "horizon", "timestamp")):
            axes.add("time")
        if any(hint in value for hint in ("value", "probability", "ratio")):
            axes.add("value")
        if "verification" in value or value == "behavior_status":
            axes.add("external_verification")
        if "authorship" in value or "response_speaker" in value:
            axes.add("attribution")
        if "segmentation" in value or "generation_method" in value:
            axes.add("segmentation")
    return axes


def evidence_is_unique(item: MaterialItem, packet_by_id: dict[str, Any], source_rev: str) -> bool:
    if len(item.evidence) != 1:
        return False
    evidence = item.evidence[0]
    packet = packet_by_id.get(evidence.packet_id)
    return bool(
        packet
        and evidence.source_rev == source_rev
        and packet.text[evidence.start : evidence.end] == evidence.quote
        and packet.text.count(evidence.quote) == 1
    )


def score_report(
    report_path: Path,
    policy_path: Path,
    policy: dict[str, Any],
    micro_gold: dict[str, Any],
) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    source_gold = json.loads(SOURCE_GOLD.read_text(encoding="utf-8"))
    source_samples = {sample["sample_id"]: sample for sample in source_gold["samples"]}
    report_samples = {sample["sample_id"]: sample for sample in report["samples"]}
    runs: dict[str, MaterialRun] = {}
    evidence_packets: dict[str, dict[str, Any]] = {}
    totals: Counter[str] = Counter()
    scope_results: list[dict[str, Any]] = []
    critical_errors: list[dict[str, str]] = []

    for scope in micro_gold["scopes"]:
        sample_id = scope["sample_id"]
        report_sample = report_samples[sample_id]
        run_id = report_sample["material_run_id"]
        if run_id not in runs:
            run_path = report_path.parent / f"{run_id}.json"
            run = MaterialRun.model_validate_json(run_path.read_text(encoding="utf-8"))
            run.verify_identity()
            runs[run_id] = run
            source = source_samples[sample_id]
            evidence_run = build_evidence_run(
                ROOT / source["source_path"],
                pages=tuple(source.get("scoped_pages", ())) or None,
                packet_chars=3000,
            )
            evidence_packets[sample_id] = {
                packet.packet_id: packet for packet in evidence_run.document.packets
            }
        run = runs[run_id]
        speakers = {speaker.speaker_id: speaker for speaker in run.understanding.speakers}
        body = scope_text(scope)
        predicted = [
            item
            for item in run.understanding.items
            if item_intersects_scope(item.model_dump(mode="json"), body)
        ]
        matches = match_scope_items(
            scope["items"],
            predicted,
            float(policy["item_identity"]["normalized_similarity_min"]),
        )
        matched_gold = {gold_index for gold_index, *_ in matches}
        matched_predicted = {predicted_index for _, predicted_index, *_ in matches}
        scope_detail: list[dict[str, Any]] = []
        totals.update(
            gold_items=len(scope["items"]),
            predicted_items=len(predicted),
            matched_items=len(matches),
        )

        for gold_index, predicted_index, score, method in matches:
            gold = scope["items"][gold_index]
            item = predicted[predicted_index]
            speaker = speakers[item.speaker_ref]
            field_checks = {
                "semantic_type": item.semantic_type == gold["semantic_type"],
                "statement_role": item.statement_role == gold["statement_role"],
                "speech_role": item.speech_role == gold["speech_role"],
                "perspective": item.perspective == gold["perspective"],
                "speaker_role": speaker_category(speaker.role)
                == speaker_category(gold["speaker_role"]),
                "identity_status": speaker.identity_status == gold["identity_status"],
                "polarity": item.polarity == gold["polarity"],
                "value": normalized(item.value) == normalized(gold["value"]),
            }
            behavior_ok = True
            if gold["semantic_type"] == "behavior":
                behavior_ok = (
                    item.behavior_status == gold["behavior_status"]
                    and item.temporal_frame == gold["temporal_frame"]
                )
            condition_risk_ok = gold["statement_role"] not in {"condition", "risk"} or (
                item.statement_role == gold["statement_role"]
            )
            evidence_ok = evidence_is_unique(
                item, evidence_packets[sample_id], run.understanding.source.source_rev
            )
            gold_axes = uncertainty_axes(gold.get("unknown_fields", []))
            predicted_axes = uncertainty_axes(item.unknown_fields)
            axis_hits = len(gold_axes & predicted_axes)
            totals.update(
                compared_items=1,
                semantic_correct=int(field_checks["semantic_type"]),
                speech_structure_correct=int(
                    field_checks["statement_role"] and field_checks["speech_role"]
                ),
                attribution_correct=int(
                    field_checks["perspective"]
                    and field_checks["speaker_role"]
                    and field_checks["identity_status"]
                ),
                polarity_correct=int(field_checks["polarity"]),
                condition_risk_items=int(
                    gold["statement_role"] in {"condition", "risk"}
                ),
                condition_risk_correct=int(
                    gold["statement_role"] in {"condition", "risk"} and condition_risk_ok
                ),
                behavior_items=int(gold["semantic_type"] == "behavior"),
                behavior_correct=int(gold["semantic_type"] == "behavior" and behavior_ok),
                value_correct=int(field_checks["value"]),
                evidence_correct=int(evidence_ok),
                unknown_axes=len(gold_axes),
                unknown_axis_hits=axis_hits,
            )
            errors: list[str] = []
            if not evidence_ok:
                errors.append("evidence_not_unique")
            if not (
                field_checks["perspective"]
                and field_checks["speaker_role"]
                and field_checks["identity_status"]
            ):
                errors.append("attribution")
            if not field_checks["polarity"]:
                errors.append("polarity")
            if not condition_risk_ok:
                errors.append("condition_or_risk")
            if not behavior_ok:
                errors.append("behavior_state_or_temporal")
            critical_errors.extend(
                {"scope_id": scope["scope_id"], "item_id": gold["item_id"], "error": error}
                for error in errors
            )
            scope_detail.append(
                {
                    "gold_item": gold["item_id"],
                    "predicted_item": item.item_id,
                    "identity_score": round(score, 4),
                    "identity_method": method,
                    "field_checks": field_checks,
                    "behavior_state_temporal": behavior_ok,
                    "condition_risk_retained": condition_risk_ok,
                    "evidence_unique": evidence_ok,
                    "unknown_axes_expected": sorted(gold_axes),
                    "unknown_axes_predicted": sorted(predicted_axes),
                }
            )

        for gold_index, gold in enumerate(scope["items"]):
            if gold_index not in matched_gold:
                critical_errors.append(
                    {
                        "scope_id": scope["scope_id"],
                        "item_id": gold["item_id"],
                        "error": "item_missing",
                    }
                )
        scope_results.append(
            {
                "scope_id": scope["scope_id"],
                "gold_items": len(scope["items"]),
                "predicted_items": len(predicted),
                "matched_items": len(matches),
                "unmatched_gold": [
                    gold["item_id"]
                    for index, gold in enumerate(scope["items"])
                    if index not in matched_gold
                ],
                "unmatched_predicted": [
                    item.item_id
                    for index, item in enumerate(predicted)
                    if index not in matched_predicted
                ],
                "detail": scope_detail,
            }
        )

    def ratio(numerator: str, denominator: str) -> float:
        return totals[numerator] / totals[denominator] if totals[denominator] else 1.0

    metrics = {
        "item_recall": ratio("matched_items", "gold_items"),
        "item_precision": ratio("matched_items", "predicted_items"),
        "semantic_accuracy": ratio("semantic_correct", "compared_items"),
        "speech_structure_accuracy": ratio(
            "speech_structure_correct", "compared_items"
        ),
        "attribution_accuracy": ratio("attribution_correct", "compared_items"),
        "polarity_accuracy": ratio("polarity_correct", "compared_items"),
        "condition_risk_retention": ratio(
            "condition_risk_correct", "condition_risk_items"
        ),
        "behavior_state_temporal_accuracy": ratio("behavior_correct", "behavior_items"),
        "value_accuracy": ratio("value_correct", "compared_items"),
        "evidence_unique_alignment": ratio("evidence_correct", "compared_items"),
        "unknown_axis_recall": ratio("unknown_axis_hits", "unknown_axes"),
        "unsupported_statement_precision": ratio("matched_items", "predicted_items"),
        "critical_errors": len(critical_errors),
    }
    thresholds = policy["thresholds"]
    violations = [
        f"{metric}: {metrics[metric]} < {threshold}"
        for metric, threshold in thresholds.items()
        if metrics[metric] < threshold
    ]
    return {
        "schema_version": "material-item-contract-score-v2",
        "scorer_version": policy["scorer_version"],
        "policy_sha256": sha256_file(policy_path),
        "diagnostic_replay_report": str(report_path),
        "diagnostic_replay_report_sha256": sha256_file(report_path),
        "split": "development",
        "model_calls": 0,
        "metrics": metrics,
        "thresholds": thresholds,
        "counts": dict(totals),
        "passed": not violations,
        "violations": violations,
        "critical_error_detail": critical_errors,
        "scopes": scope_results,
        "note": "This v2 result does not replace or amend the frozen v12 scorer result.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    policy_path = args.policy.resolve()
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    if policy.get("schema_version") != "r2-item-acceptance-policy-v2":
        raise ValueError("unsupported item acceptance policy")
    if policy.get("split") != "development":
        raise ValueError("item acceptance policy must be development-only")
    for name, binding in policy["bindings"].items():
        path = ROOT / binding["path"]
        if sha256_file(path) != binding["sha256"]:
            raise ValueError(f"binding mismatch: {name}")
    report_path = (
        args.report.resolve()
        if args.report
        else ROOT / policy["bindings"]["diagnostic_baseline_report"]["path"]
    )
    micro_gold, _ = validate_micro_gold(DEFAULT_MICRO_GOLD)
    result = score_report(report_path, policy_path, policy, micro_gold)
    target = OUT / f"item-contract-score-v2-{fingerprint(result)}.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"result": result, "score_report": str(target)}, ensure_ascii=False, indent=2))
    return int(not result["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
