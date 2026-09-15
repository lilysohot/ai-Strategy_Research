"""Verify exhaustive R2 micro-gold and score an existing material run offline.

This utility never calls a model, reads a holdout split, or writes to the corpus
database.  It validates exact source identity and quote alignment before scoring.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from plugins.corpus.evidence import fingerprint
from plugins.corpus.evidence_pipeline import build_evidence_run
from plugins.corpus.material_semantics import (
    MaterialRun,
    build_candidate_slot_batches,
    build_candidate_slots,
    build_material_structure,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MICRO_GOLD = ROOT / "data/corpus/.audit/r2_material_micro_gold_v1_20260913.json"
SOURCE_GOLD = ROOT / "data/corpus/.audit/r1_material_gold_v1_20260913.json"
OUT = ROOT / ".scratch/corpus-evidence-pipeline/material-semantics-runs"
DEFAULT_NON_REGRESSION_POLICY = (
    ROOT / ".scratch/corpus-evidence-pipeline/r2-non-regression-policy-v1.json"
)
MATERIAL_MICRO_SCORER_VERSION = "material-micro-scorer-1"

SEMANTIC_TYPES = {"fact", "forecast", "opinion", "behavior", "unknown"}
STATEMENT_ROLES = {"claim", "evidence", "condition", "risk", "question", "answer", "other"}
SPEECH_ROLES = {"statement", "question", "answer", "unknown"}
PERSPECTIVES = {"source_explicit", "quoted_other", "unknown"}
POLARITIES = {"affirmed", "negated", "mixed", "unknown"}
BEHAVIOR_STATUSES = {"intent", "claimed_executed", "claimed_not_executed", "unknown"}
TEMPORAL_FRAMES = {"contemporaneous", "retrospective", "unknown"}
RELATION_TYPES = {
    "supports",
    "challenges",
    "conditions",
    "invalidates",
    "answers",
    "motivates",
    "attributes",
    "elaborates",
}


def normalized(value: object) -> str:
    """Normalize whitespace and common PDF punctuation without paraphrasing."""
    text = "".join(str(value or "").lower().split())
    return text.replace("。", "").replace("，", ",").replace("；", ";")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scope_text(scope: dict[str, Any]) -> str:
    path = ROOT / scope["source_path"]
    locator = scope["locator"]
    if path.suffix.lower() == ".pdf":
        page = PdfReader(str(path)).pages[int(locator["page"]) - 1]
        lines = (page.extract_text() or "").splitlines()
    else:
        lines = path.read_text(encoding="utf-8").splitlines()
    start = int(locator["line_start"])
    end = int(locator["line_end"])
    if start < 1 or end < start or end > len(lines):
        raise ValueError(f"invalid locator in {scope['scope_id']}: {locator}")
    return "\n".join(lines[start - 1 : end])


def assert_unique_quote(scope_id: str, text: str, quote: object, label: str) -> None:
    needle = normalized(quote)
    if not needle:
        raise ValueError(f"empty {label} quote in {scope_id}")
    occurrences = normalized(text).count(needle)
    if occurrences != 1:
        raise ValueError(
            f"{label} quote must align exactly once in {scope_id}; got {occurrences}: {quote!r}"
        )


def validate_micro_gold(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    gold = json.loads(path.read_text(encoding="utf-8"))
    if gold.get("schema_version") != "material-micro-gold-v1":
        raise ValueError("unsupported micro-gold schema")
    if gold.get("split") != "development":
        raise ValueError("micro-gold must be development-only")
    if sha256_file(SOURCE_GOLD) != gold.get("source_gold_sha256"):
        raise ValueError("micro-gold is not bound to the current frozen source gold")

    source_gold = json.loads(SOURCE_GOLD.read_text(encoding="utf-8"))
    samples = {sample["sample_id"]: sample for sample in source_gold["samples"]}
    item_ids: set[str] = set()
    relation_ids: set[str] = set()
    relation_triples: set[tuple[str, str, str]] = set()
    negative_triples: set[tuple[str, str, str]] = set()
    per_type: Counter[str] = Counter()
    scope_stats: list[dict[str, Any]] = []

    for scope in gold.get("scopes", []):
        scope_id = scope["scope_id"]
        sample = samples.get(scope["sample_id"])
        if sample is None or sample.get("split") != "development":
            raise ValueError(f"scope is not bound to a development sample: {scope_id}")
        if scope["source_path"] != sample["source_path"]:
            raise ValueError(f"source path differs from frozen source gold: {scope_id}")
        source = ROOT / scope["source_path"]
        if sha256_file(source) != scope["source_sha256"]:
            raise ValueError(f"source hash mismatch: {scope_id}")
        if scope["source_sha256"] != sample["source_sha256"]:
            raise ValueError(f"source hash differs from frozen source gold: {scope_id}")

        text = scope_text(scope)
        local_ids = {item["item_id"] for item in scope["items"]}
        if len(local_ids) != len(scope["items"]):
            raise ValueError(f"duplicate item id inside {scope_id}")
        if item_ids & local_ids:
            raise ValueError(f"item id reused across scopes: {sorted(item_ids & local_ids)}")
        item_ids.update(local_ids)

        for item in scope["items"]:
            assert_unique_quote(scope_id, text, item["quote"], "item")
            if item["semantic_type"] not in SEMANTIC_TYPES:
                raise ValueError(f"invalid semantic_type in {item['item_id']}")
            if item["statement_role"] not in STATEMENT_ROLES:
                raise ValueError(f"invalid statement_role in {item['item_id']}")
            if item["speech_role"] not in SPEECH_ROLES:
                raise ValueError(f"invalid speech_role in {item['item_id']}")
            if item["perspective"] not in PERSPECTIVES:
                raise ValueError(f"invalid perspective in {item['item_id']}")
            if item["polarity"] not in POLARITIES:
                raise ValueError(f"invalid polarity in {item['item_id']}")
            if item["temporal_frame"] not in TEMPORAL_FRAMES:
                raise ValueError(f"invalid temporal_frame in {item['item_id']}")
            status = item["behavior_status"]
            if item["semantic_type"] == "behavior" and status not in BEHAVIOR_STATUSES:
                raise ValueError(f"behavior item lacks valid behavior_status: {item['item_id']}")
            if item["semantic_type"] != "behavior" and status is not None:
                raise ValueError(f"non-behavior item has behavior_status: {item['item_id']}")
            per_type[item["semantic_type"]] += 1

        for excluded in scope.get("excluded", []):
            assert_unique_quote(scope_id, text, excluded["quote"], "excluded")

        for relation in scope.get("relations", []):
            relation_id = relation["relation_id"]
            if relation_id in relation_ids:
                raise ValueError(f"duplicate relation id: {relation_id}")
            relation_ids.add(relation_id)
            triple = (relation["type"], relation["from_item"], relation["to_item"])
            validate_relation(scope_id, triple, local_ids)
            if triple in relation_triples:
                raise ValueError(f"duplicate positive relation: {triple}")
            relation_triples.add(triple)

        for relation in scope.get("negative_relations", []):
            triple = (relation["type"], relation["from_item"], relation["to_item"])
            validate_relation(scope_id, triple, local_ids)
            if triple in relation_triples:
                raise ValueError(f"relation is both positive and negative: {triple}")
            if triple in negative_triples:
                raise ValueError(f"duplicate negative relation: {triple}")
            negative_triples.add(triple)

        scope_stats.append(
            {
                "scope_id": scope_id,
                "items": len(scope["items"]),
                "positive_relations": len(scope.get("relations", [])),
                "negative_relations": len(scope.get("negative_relations", [])),
                "excluded": len(scope.get("excluded", [])),
            }
        )

    summary = {
        "micro_gold": str(path),
        "micro_gold_sha256": sha256_file(path),
        "split": "development",
        "scopes": len(scope_stats),
        "items": len(item_ids),
        "positive_relations": len(relation_triples),
        "negative_relations": len(negative_triples),
        "excluded_fragments": sum(value["excluded"] for value in scope_stats),
        "semantic_types": dict(sorted(per_type.items())),
        "quote_alignment": "all_unique_within_scope",
        "scope_detail": scope_stats,
    }
    expected_counts = gold.get("expected_counts")
    observed_counts = {key: summary[key] for key in expected_counts or {}}
    if not expected_counts or observed_counts != expected_counts:
        raise ValueError(
            f"micro-gold count invariant failed: expected={expected_counts}, "
            f"observed={observed_counts}"
        )
    summary["atomic_obligations"] = validate_atomic_obligations(gold, samples)
    return gold, summary


def validate_atomic_obligations(
    micro_gold: dict[str, Any], source_samples: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Prove every development gold item has its own system-generated slot."""
    slots_by_sample: dict[str, tuple[Any, ...]] = {}
    sample_stats: dict[str, dict[str, int]] = {}
    matched_items = 0
    for scope in micro_gold["scopes"]:
        sample_id = scope["sample_id"]
        if sample_id not in slots_by_sample:
            sample = source_samples[sample_id]
            evidence_run = build_evidence_run(
                ROOT / sample["source_path"],
                pages=tuple(sample["scoped_pages"]) if "scoped_pages" in sample else None,
                packet_chars=3000,
            )
            if evidence_run.document.source_rev != sample["source_rev"]:
                raise ValueError(f"atomic slot source revision mismatch: {sample_id}")
            slots = build_candidate_slots(
                evidence_run.document, build_material_structure(evidence_run.document)
            )
            batches = build_candidate_slot_batches(
                slots, max_slots_per_batch=16, max_items_per_batch=16
            )
            candidate_packets = len({slot.packet_id for slot in slots})
            slots_by_sample[sample_id] = slots
            sample_stats[sample_id] = {
                "candidate_slots": len(slots),
                "item_batches": len(batches),
                "candidate_packets": candidate_packets,
                "calls_upper_bound": len(batches) + candidate_packets,
            }

        scope_body = normalized(scope_text(scope))
        slots = [
            slot
            for slot in slots_by_sample[sample_id]
            if normalized(slot.text) and normalized(slot.text) in scope_body
        ]
        candidates = sorted(
            (
                (quote_similarity(item["quote"], slot.text), item_index, slot_index)
                for item_index, item in enumerate(scope["items"])
                for slot_index, slot in enumerate(slots)
            ),
            reverse=True,
        )
        used_items: set[int] = set()
        used_slots: set[int] = set()
        for score, item_index, slot_index in candidates:
            if score < 0.5 or item_index in used_items or slot_index in used_slots:
                continue
            used_items.add(item_index)
            used_slots.add(slot_index)
        if len(used_items) != len(scope["items"]):
            missing = [
                item["item_id"]
                for index, item in enumerate(scope["items"])
                if index not in used_items
            ]
            raise ValueError(
                f"gold items lack distinct atomic obligations in {scope['scope_id']}: {missing}"
            )
        matched_items += len(used_items)

    return {
        "matched_items": matched_items,
        "distinct_slot_per_item": True,
        "samples": sample_stats,
        "model_calls": 0,
    }


def validate_relation(scope_id: str, triple: tuple[str, str, str], local_ids: set[str]) -> None:
    relation_type, from_item, to_item = triple
    if relation_type not in RELATION_TYPES:
        raise ValueError(f"invalid relation type in {scope_id}: {relation_type}")
    if from_item not in local_ids or to_item not in local_ids:
        raise ValueError(f"relation endpoint outside {scope_id}: {triple}")
    if from_item == to_item:
        raise ValueError(f"self relation in {scope_id}: {triple}")


def quote_similarity(gold_quote: object, predicted_quote: object) -> float:
    gold = normalized(gold_quote)
    predicted = normalized(predicted_quote)
    if not gold or not predicted:
        return 0.0
    ratio = SequenceMatcher(None, gold, predicted).ratio()
    if gold in predicted or predicted in gold:
        ratio = max(ratio, min(len(gold), len(predicted)) / len(gold))
    return ratio


def evidence_quote(item: dict[str, Any]) -> str:
    evidence = item.get("evidence") or []
    return str(evidence[0].get("quote", "")) if evidence else ""


def item_intersects_scope(item: dict[str, Any], text: str) -> bool:
    quote = normalized(evidence_quote(item))
    haystack = normalized(text)
    return bool(quote and (quote in haystack or haystack in quote))


def match_items(
    gold_items: list[dict[str, Any]], predicted_items: list[dict[str, Any]]
) -> list[tuple[int, int, float]]:
    candidates = sorted(
        (
            (quote_similarity(gold["quote"], evidence_quote(predicted)), gold_index, pred_index)
            for gold_index, gold in enumerate(gold_items)
            for pred_index, predicted in enumerate(predicted_items)
        ),
        reverse=True,
    )
    used_gold: set[int] = set()
    used_predicted: set[int] = set()
    matches: list[tuple[int, int, float]] = []
    for score, gold_index, pred_index in candidates:
        if score < 0.5 or gold_index in used_gold or pred_index in used_predicted:
            continue
        used_gold.add(gold_index)
        used_predicted.add(pred_index)
        matches.append((gold_index, pred_index, score))
    return sorted(matches)


def map_relation_endpoints(
    gold_items: list[dict[str, Any]], predicted_items: list[dict[str, Any]]
) -> dict[str, str]:
    """Map each gold endpoint independently so merged predictions stay auditable."""
    endpoint_map: dict[str, str] = {}
    for gold in gold_items:
        candidates = [
            (quote_similarity(gold["quote"], evidence_quote(predicted)), predicted["item_id"])
            for predicted in predicted_items
        ]
        if not candidates:
            continue
        score, predicted_id = max(candidates)
        if score >= 0.5:
            endpoint_map[gold["item_id"]] = predicted_id
    return endpoint_map


def score_scope(scope: dict[str, Any], material_run: MaterialRun) -> dict[str, Any]:
    predicted = material_run.understanding.model_dump(mode="json")
    text = scope_text(scope)
    predicted_items = [item for item in predicted["items"] if item_intersects_scope(item, text)]
    matches = match_items(scope["items"], predicted_items)
    matched_gold_to_pred = {
        scope["items"][gold_index]["item_id"]: predicted_items[pred_index]["item_id"]
        for gold_index, pred_index, _score in matches
    }
    relation_endpoint_map = map_relation_endpoints(scope["items"], predicted_items)
    matched_pred_ids = set(matched_gold_to_pred.values())
    scoped_pred_ids = {item["item_id"] for item in predicted_items}
    predicted_relations = [
        relation
        for relation in predicted["relations"]
        if relation["from_item"] in scoped_pred_ids and relation["to_item"] in scoped_pred_ids
    ]
    predicted_triples = {
        (relation["type"], relation["from_item"], relation["to_item"])
        for relation in predicted_relations
        if relation["provenance"] == "source_explicit"
    }
    expected_triples = {
        (
            relation["type"],
            relation_endpoint_map.get(relation["from_item"]),
            relation_endpoint_map.get(relation["to_item"]),
        )
        for relation in scope.get("relations", [])
        if relation["from_item"] in relation_endpoint_map
        and relation["to_item"] in relation_endpoint_map
    }
    assessable_negatives = [
        relation
        for relation in scope.get("negative_relations", [])
        if relation["from_item"] in relation_endpoint_map
        and relation["to_item"] in relation_endpoint_map
    ]
    relation_tp = predicted_triples & expected_triples
    negative_hits = {
        (
            relation["type"],
            relation_endpoint_map[relation["from_item"]],
            relation_endpoint_map[relation["to_item"]],
        )
        for relation in assessable_negatives
    } & predicted_triples
    relation_fp = predicted_triples - expected_triples
    gold_count = len(scope["items"])
    predicted_count = len(predicted_items)
    positive_count = len(scope.get("relations", []))
    matched_count = len(matches)
    relation_predictions = len(predicted_triples)
    return {
        "scope_id": scope["scope_id"],
        "sample_id": scope["sample_id"],
        "material_run_id": material_run.run_id,
        "item_recall": matched_count / gold_count if gold_count else 1.0,
        "item_precision": matched_count / predicted_count if predicted_count else 1.0,
        "relation_recall": len(relation_tp) / positive_count if positive_count else 1.0,
        "relation_precision": (
            len(relation_tp) / relation_predictions if relation_predictions else 1.0
        ),
        "counts": {
            "gold_items": gold_count,
            "predicted_items": predicted_count,
            "matched_items": matched_count,
            "positive_relations": positive_count,
            "predicted_relations": relation_predictions,
            "matched_relations": len(relation_tp),
            "false_positive_relations": len(relation_fp),
            "negative_relations": len(scope.get("negative_relations", [])),
            "assessable_negative_relations": len(assessable_negatives),
            "negative_relation_hits": len(negative_hits),
        },
        "missed_items": [
            item["item_id"]
            for index, item in enumerate(scope["items"])
            if index not in {match[0] for match in matches}
        ],
        "extra_predicted_items": [
            item["item_id"] for item in predicted_items if item["item_id"] not in matched_pred_ids
        ],
        "negative_relation_hits": [list(value) for value in sorted(negative_hits)],
    }


def score_report(gold: dict[str, Any], micro_gold_path: Path, report_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("split") != "development":
        raise ValueError("only a development report may be replayed")
    samples = {sample["sample_id"]: sample for sample in report["samples"]}
    runs: dict[str, MaterialRun] = {}
    results: list[dict[str, Any]] = []
    for scope in gold["scopes"]:
        sample = samples.get(scope["sample_id"])
        if sample is None:
            raise ValueError(f"report lacks sample: {scope['sample_id']}")
        run_id = sample["material_run_id"]
        if run_id not in runs:
            run_path = report_path.parent / f"{run_id}.json"
            material_run = MaterialRun.model_validate_json(run_path.read_text(encoding="utf-8"))
            material_run.verify_identity()
            runs[run_id] = material_run
        results.append(score_scope(scope, runs[run_id]))

    total = Counter[str]()
    for result in results:
        total.update(result["counts"])
    aggregate = {
        "item_recall": total["matched_items"] / total["gold_items"],
        "item_precision": total["matched_items"] / total["predicted_items"]
        if total["predicted_items"]
        else 1.0,
        "relation_recall": total["matched_relations"] / total["positive_relations"],
        "relation_precision": total["matched_relations"] / total["predicted_relations"]
        if total["predicted_relations"]
        else 1.0,
        "negative_relation_avoidance": (
            1 - total["negative_relation_hits"] / total["assessable_negative_relations"]
            if total["assessable_negative_relations"]
            else None
        ),
    }
    return {
        "schema_version": "material-micro-score-v1",
        "scorer_version": MATERIAL_MICRO_SCORER_VERSION,
        "micro_gold_sha256": sha256_file(micro_gold_path),
        "replay_report": str(report_path),
        "replay_report_sha256": sha256_file(report_path),
        "split": "development",
        "model_calls": 0,
        "source_model_calls_reused": report.get("model_calls", 0),
        "precision_scope": "six_exhaustively_annotated_micro_scopes_only",
        "samples": results,
        "aggregate": aggregate,
        "counts": dict(total),
        "limitations": [
            "This is exhaustive only inside the six frozen micro-scopes.",
            "Offline replay reuses existing predictions and makes no model calls.",
            "No holdout source or corpus database is accessed.",
        ],
    }


def check_non_regression(
    material_report: dict[str, Any], micro_score: dict[str, Any], policy_path: Path
) -> dict[str, Any]:
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    if policy.get("schema_version") != "r2-non-regression-policy-v1":
        raise ValueError("unsupported non-regression policy")
    expected_scorers = policy.get("scorer_versions", {})
    if material_report.get("scorer_version") != expected_scorers.get("material"):
        raise ValueError("candidate material report uses a different scorer version")
    if micro_score.get("scorer_version") != expected_scorers.get("micro"):
        raise ValueError("candidate micro score uses a different scorer version")
    if policy.get("split") != "development" or material_report.get("split") != "development":
        raise ValueError("non-regression checking is development-only")
    for binding_name in (
        "source_gold",
        "micro_gold",
        "baseline_material_report",
        "baseline_micro_score",
    ):
        binding = policy[binding_name]
        bound_path = ROOT / binding["path"]
        if sha256_file(bound_path) != binding["sha256"]:
            raise ValueError(f"non-regression binding mismatch: {binding_name}")

    violations: list[str] = []
    candidate_samples = {sample["sample_id"]: sample for sample in material_report["samples"]}
    protected_samples = policy["protected_samples"]
    if set(candidate_samples) != set(protected_samples):
        violations.append(
            "candidate sample ids differ from the four protected development categories"
        )
    for sample_id, rule in protected_samples.items():
        candidate = candidate_samples.get(sample_id)
        if candidate is None:
            continue
        for metric, floor in rule["metric_floors"].items():
            actual = float(candidate[metric])
            if actual + 1e-12 < float(floor):
                violations.append(f"{sample_id}.{metric}: {actual} < {floor}")
        summary = candidate["summary"]
        if rule["require_complete"] and not summary["complete"]:
            violations.append(f"{sample_id}.complete regressed to false")
        packet_status = summary.get("packet_status", {})
        failed_or_partial = int(packet_status.get("failed", 0)) + int(
            packet_status.get("partial", 0)
        )
        if failed_or_partial > int(rule["max_failed_or_partial_packets"]):
            violations.append(
                f"{sample_id}.failed_or_partial_packets: {failed_or_partial} > "
                f"{rule['max_failed_or_partial_packets']}"
            )

    candidate_scopes = {scope["scope_id"]: scope for scope in micro_score["samples"]}
    protected_scopes = policy["protected_micro_scopes"]
    if set(candidate_scopes) != set(protected_scopes):
        violations.append("candidate micro-scope ids differ from the six protected scopes")
    for scope_id, rule in protected_scopes.items():
        candidate = candidate_scopes.get(scope_id)
        if candidate is None:
            continue
        for metric, floor in rule["metric_floors"].items():
            actual = float(candidate[metric])
            if actual + 1e-12 < float(floor):
                violations.append(f"{scope_id}.{metric}: {actual} < {floor}")
        counts = candidate["counts"]
        for count_name, rule_name in (
            ("negative_relation_hits", "max_negative_relation_hits"),
            ("false_positive_relations", "max_false_positive_relations"),
        ):
            if int(counts[count_name]) > int(rule[rule_name]):
                violations.append(
                    f"{scope_id}.{count_name}: {counts[count_name]} > {rule[rule_name]}"
                )

    return {
        "policy": str(policy_path),
        "policy_sha256": sha256_file(policy_path),
        "protected_samples": len(protected_samples),
        "protected_micro_scopes": len(protected_scopes),
        "passed": not violations,
        "violations": violations,
        "note": "Floors prevent regression; they do not replace the stricter R2 acceptance thresholds.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--micro-gold", type=Path, default=DEFAULT_MICRO_GOLD)
    parser.add_argument("--material-report", type=Path)
    parser.add_argument("--non-regression-policy", type=Path, default=DEFAULT_NON_REGRESSION_POLICY)
    args = parser.parse_args()

    gold_path = args.micro_gold.resolve()
    gold, verification = validate_micro_gold(gold_path)
    output: dict[str, Any] = {"verification": verification}
    if args.material_report:
        report_path = args.material_report.resolve()
        score = score_report(gold, gold_path, report_path)
        target = OUT / f"micro-score-{fingerprint(score)}.json"
        target.write_text(json.dumps(score, ensure_ascii=False, indent=2), encoding="utf-8")
        output["score"] = score
        output["score_report"] = str(target)
        material_report = json.loads(report_path.read_text(encoding="utf-8"))
        output["non_regression"] = check_non_regression(
            material_report, score, args.non_regression_policy.resolve()
        )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return int(not output.get("non_regression", {"passed": True})["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
