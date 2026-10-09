"""Run and score the frozen R2 development samples without corpus ingestion."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Callable
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from plugins.corpus.claims import build_default_llm, configured_model
from plugins.corpus.claims_detail import triage_block_detail
from plugins.corpus.evidence import fingerprint
from plugins.corpus.evidence_pipeline import build_evidence_run
from plugins.corpus.material_semantics import (
    MATERIAL_EXTRACTOR_VERSION,
    MATERIAL_SLOT_BATCHING_VERSION,
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
MATERIAL_DEVELOPMENT_SCORER_VERSION = "material-development-scorer-4"
DIRECT_LIVE_DISABLED_MESSAGE = (
    "direct live execution is disabled; freeze and execute the request through "
    "python -m plugins.corpus.structured.cli so the formal ledger owns authorization, "
    "attempts, responses and terminal state"
)


def evaluate_item_stage_gate(
    budget: dict[str, Any], results: list[dict[str, Any]]
) -> dict[str, Any]:
    """Evaluate only metrics produced by an item-only development round."""
    policy_ref = budget["non_regression_policy"]
    policy_path = ROOT / policy_ref["path"]
    policy_bytes = policy_path.read_bytes()
    actual_sha256 = hashlib.sha256(policy_bytes).hexdigest()
    if actual_sha256 != policy_ref["sha256"]:
        raise ValueError("non-regression policy identity drifted")
    policy = json.loads(policy_bytes)
    in_scope = tuple(budget["stage1_gate"]["in_scope"]["item"])
    completeness = budget["stage1_gate"]["completeness"]
    violations: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    for result in results:
        sample_id = result["sample_id"]
        protected = policy["protected_samples"][sample_id]
        metric_results: dict[str, dict[str, Any]] = {}
        for metric in in_scope:
            if metric not in result:
                violations.append(
                    {"sample_id": sample_id, "metric": metric, "reason": "not_measured"}
                )
                continue
            floor = protected["metric_floors"][metric]
            value = result[metric]
            passed = value >= floor
            metric_results[metric] = {"value": value, "floor": floor, "passed": passed}
            if not passed:
                violations.append(
                    {
                        "sample_id": sample_id,
                        "metric": metric,
                        "value": value,
                        "floor": floor,
                    }
                )
        packet_status = result["summary"]["packet_status"]
        failed_or_partial = packet_status.get("failed", 0) + packet_status.get("partial", 0)
        max_failed_or_partial = completeness.get(
            "max_failed_or_partial_packets",
            protected["max_failed_or_partial_packets"],
        )
        if not isinstance(max_failed_or_partial, int):
            max_failed_or_partial = protected["max_failed_or_partial_packets"]
        require_complete = completeness.get("require_complete", protected["require_complete"])
        if not isinstance(require_complete, bool):
            require_complete = protected["require_complete"]
        complete = bool(result["summary"]["complete"])
        completeness_passed = failed_or_partial <= max_failed_or_partial and (
            complete or not require_complete
        )
        if not completeness_passed:
            violations.append(
                {
                    "sample_id": sample_id,
                    "reason": "completeness",
                    "failed_or_partial_packets": failed_or_partial,
                    "max_failed_or_partial_packets": max_failed_or_partial,
                    "complete": complete,
                    "require_complete": require_complete,
                }
            )
        samples.append(
            {
                "sample_id": sample_id,
                "metrics": metric_results,
                "failed_or_partial_packets": failed_or_partial,
                "max_failed_or_partial_packets": max_failed_or_partial,
                "complete": complete,
                "require_complete": require_complete,
                "passed": all(violation.get("sample_id") != sample_id for violation in violations),
            }
        )
    return {
        "scope": "item_stage_only",
        "relations": "not_measured",
        "samples": samples,
        "violations": violations,
        "passed": not violations,
    }


def normalized(value: object) -> str:
    return "".join(str(value or "").lower().split())


def values_equivalent(gold_value: object, predicted_value: object) -> bool:
    """Compare a predicted scalar with either frozen gold value representation."""
    predicted = normalized(predicted_value)
    if not isinstance(gold_value, dict):
        return normalized(gold_value) == predicted
    candidates = {
        normalized(gold_value.get(key))
        for key in ("raw", "normalized")
        if gold_value.get(key) is not None
    }
    return predicted in candidates


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
        key=lambda candidate: (-candidate[0], candidate[1], candidate[2]),
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
                "predicted_indices": [predicted_index],
                "quote_similarity": round(score, 4),
            }
        )
    for match in matches:
        gold = gold_items[match["gold_index"]]
        if not _gold_requires_atomic_group(gold):
            continue
        primary_index = match["predicted_index"]
        primary = predicted_items[primary_index]
        eligible = [
            index
            for index, predicted in enumerate(predicted_items)
            if (index == primary_index or index not in used_predicted)
            and quote_score(gold, predicted) >= 0.35
            and _same_atomic_group(primary, predicted)
        ]
        for size in range(1, min(4, len(eligible)) + 1):
            accepted: tuple[int, ...] | None = None
            for group in combinations(eligible, size):
                if primary_index not in group:
                    continue
                predictions = [predicted_items[index] for index in group]
                if _atomic_group_satisfies_gold_shape(gold, predictions):
                    accepted = group
                    break
            if accepted is None:
                continue
            match["predicted_indices"] = list(accepted)
            used_predicted.update(accepted)
            break
    return sorted(matches, key=lambda value: value["gold_index"])


def _gold_requires_atomic_group(gold_item: dict[str, Any]) -> bool:
    value = gold_item.get("value")
    raw_value = value.get("raw") if isinstance(value, dict) else value
    return gold_item.get("polarity") == "mixed" or (isinstance(raw_value, str) and ";" in raw_value)


def _same_atomic_group(primary: dict[str, Any], candidate: dict[str, Any]) -> bool:
    return all(
        primary.get(field) == candidate.get(field)
        for field in (
            "semantic_type",
            "statement_role",
            "speech_role",
            "perspective",
            "speaker_ref",
            "behavior_status",
            "temporal_frame",
        )
    )


def relation_endpoint_indices(
    gold_item: dict[str, Any],
    scored_indices: list[int],
    predicted_items: list[dict[str, Any]],
) -> list[int]:
    """Map one gold proposition to all nearby atomic endpoints without changing item scoring."""
    if not scored_indices:
        return []
    primary = predicted_items[scored_indices[0]]
    primary_evidence = primary["evidence"][0]
    selected = set(scored_indices)
    alternatives: list[tuple[int, float, int]] = []
    for index, candidate in enumerate(predicted_items):
        if index in selected:
            continue
        if any(
            primary.get(field) != candidate.get(field)
            for field in ("speaker_ref", "speech_role", "statement_role")
        ):
            continue
        candidate_evidence = candidate["evidence"][0]
        if any(
            primary_evidence.get(field)
            and candidate_evidence.get(field)
            and primary_evidence[field] != candidate_evidence[field]
            for field in ("packet_id", "locator")
        ):
            continue
        similarity = quote_score(gold_item, candidate)
        if similarity < 0.35:
            continue
        alternatives.append((candidate_evidence.get("start", index), -similarity, index))
    alternatives.sort()
    return [*scored_indices, *(entry[2] for entry in alternatives[: 4 - len(scored_indices)])]


def _group_polarity_matches(gold_polarity: object, predictions: list[dict[str, Any]]) -> bool:
    polarities = {predicted.get("polarity") for predicted in predictions}
    if gold_polarity == "mixed":
        return "mixed" in polarities or {"affirmed", "negated"} <= polarities
    return polarities == {gold_polarity}


def grouped_values_equivalent(gold_value: object, predicted_values: list[object]) -> bool:
    present = [value for value in predicted_values if value is not None]
    if any(values_equivalent(gold_value, value) for value in present):
        return True
    if not present:
        return values_equivalent(gold_value, None)
    return values_equivalent(gold_value, "; ".join(str(value) for value in present))


def _atomic_group_satisfies_gold_shape(
    gold_item: dict[str, Any], predictions: list[dict[str, Any]]
) -> bool:
    if not _group_polarity_matches(gold_item.get("polarity"), predictions):
        return False
    value = gold_item.get("value")
    raw_value = value.get("raw") if isinstance(value, dict) else value
    if isinstance(raw_value, str) and ";" in raw_value:
        return grouped_values_equivalent(
            value, [predicted.get("value") for predicted in predictions]
        )
    return True


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


def _write_restricted_exclusive(path: Path, content: str) -> None:
    """Persist one append-only audit record before returning to the caller."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o600)


class AttemptRecorder:
    """Durably record every experimental model attempt, including interruptions."""

    def __init__(
        self,
        llm: Callable[[str], str],
        *,
        audit_dir: Path,
        budget_version: str,
        round_id: str,
        sample_id: str,
    ) -> None:
        self._llm = llm
        self._audit_dir = audit_dir
        self._identity = {
            "budget_version": budget_version,
            "round_id": round_id,
            "sample_id": sample_id,
        }
        self.attempts: list[dict[str, Any]] = []

    def __call__(self, prompt: str) -> str:
        ordinal = len(self.attempts) + 1
        prompt_sha256 = hashlib.sha256(prompt.encode()).hexdigest()
        attempt_id = "attempt:" + fingerprint(
            {**self._identity, "ordinal": ordinal, "prompt_sha256": prompt_sha256}
        )
        stem = f"attempt-{ordinal:04d}-{attempt_id.removeprefix('attempt:')[:12]}"
        started_path = self._audit_dir / f"{stem}.started.json"
        started = {
            "record_version": "material-development-attempt-v1",
            "attempt_id": attempt_id,
            **self._identity,
            "ordinal": ordinal,
            "prompt_sha256": prompt_sha256,
            "status": "running",
        }
        _write_restricted_exclusive(started_path, json.dumps(started, ensure_ascii=False, indent=2))
        record: dict[str, Any] = {**started, "started_path": str(started_path)}
        self.attempts.append(record)
        try:
            response = str(self._llm(prompt))
        except BaseException as exc:
            diagnostics = getattr(exc, "diagnostics", None)
            explicit_status = (
                diagnostics.get("execution_status") if isinstance(diagnostics, dict) else None
            )
            status = (
                explicit_status
                if explicit_status in {"failed", "outcome_unknown"}
                else "outcome_unknown"
            )
            terminal_path = self._audit_dir / f"{stem}.terminal.json"
            terminal = {
                **started,
                "status": status,
                "error_type": type(exc).__name__,
                "error_code": diagnostics.get("error_code")
                if isinstance(diagnostics, dict)
                else None,
            }
            _write_restricted_exclusive(
                terminal_path, json.dumps(terminal, ensure_ascii=False, indent=2)
            )
            record.update({"status": status, "terminal_path": str(terminal_path)})
            raise
        response_sha256 = hashlib.sha256(response.encode()).hexdigest()
        response_path = self._audit_dir / f"{stem}-{response_sha256[:12]}.response.txt"
        _write_restricted_exclusive(response_path, response)
        terminal_path = self._audit_dir / f"{stem}.terminal.json"
        terminal = {
            **started,
            "status": "succeeded",
            "response_sha256": response_sha256,
            "response_path": str(response_path),
        }
        _write_restricted_exclusive(
            terminal_path, json.dumps(terminal, ensure_ascii=False, indent=2)
        )
        record.update(
            {
                "status": "succeeded",
                "response_sha256": response_sha256,
                "response_path": str(response_path),
                "terminal_path": str(terminal_path),
            }
        )
        return response


def bind_attempt_records(
    material_run: MaterialRun,
    attempts: list[dict[str, Any]],
    stage_names: list[str],
) -> list[dict[str, Any]]:
    """Bind durable attempts to packet/stage order without rewriting audit files."""
    bound: list[dict[str, Any]] = []
    attempt_index = 0
    for packet_run in material_run.packet_runs:
        for stage_index in range(packet_run.model_calls or 0):
            if attempt_index >= len(attempts):
                bound.append(
                    {
                        "capture_status": "missing_attempt_record",
                        "packet_id": packet_run.packet_id,
                        "packet_status": packet_run.status,
                        "stage": stage_names[min(stage_index, len(stage_names) - 1)],
                    }
                )
                continue
            record = dict(attempts[attempt_index])
            attempt_index += 1
            record.update(
                {
                    "capture_status": "recorded",
                    "packet_id": packet_run.packet_id,
                    "packet_status": packet_run.status,
                    "stage": stage_names[min(stage_index, len(stage_names) - 1)],
                }
            )
            bound.append(record)
    for record in attempts[attempt_index:]:
        bound.append({**record, "capture_status": "unbound_attempt_record"})
    return bound


def stage1_stop_reason(budget: dict[str, Any], result: dict[str, Any]) -> str | None:
    """Return the frozen per-sample stop condition before starting another sample."""
    if budget.get("relation_mode") != "deferred":
        return None
    conditions = set(budget.get("stop_conditions", ()))
    gate = evaluate_item_stage_gate(budget, [result])
    for violation in gate["violations"]:
        if (
            violation.get("reason") == "completeness"
            and violation.get("failed_or_partial_packets", 0) > 0
            and "any_failed_or_partial_packet" in conditions
        ):
            return "any_failed_or_partial_packet"
        if "metric" in violation and "any_in_scope_metric_floor_decrease" in conditions:
            return "any_in_scope_metric_floor_decrease"
    return None


def score_sample(sample: dict[str, Any], material_run: Any) -> dict[str, Any]:
    predicted_payload = material_run.understanding.model_dump(mode="json")
    gold_items = sample["items"]
    predicted_items = predicted_payload["items"]
    matches = match_items(gold_items, predicted_items)
    match_by_gold = {match["gold_index"]: match for match in matches}
    gold_speakers = {speaker["speaker_id"]: speaker for speaker in sample["speakers"]}
    predicted_speakers = {
        speaker["speaker_id"]: speaker for speaker in predicted_payload["speakers"]
    }
    detail: list[dict[str, Any]] = []
    semantic_correct = 0
    attribution_correct = 0
    critical_matched = 0
    critical_fields_correct = 0
    endpoint_map: dict[str, tuple[str, ...]] = {}
    for gold_index, gold_item in enumerate(gold_items):
        match = match_by_gold.get(gold_index)
        if match is None:
            detail.append({"gold_item": gold_item["item_id"], "matched": False})
            continue
        predicted_group = [predicted_items[index] for index in match["predicted_indices"]]
        predicted_item = predicted_group[0]
        endpoint_indices = relation_endpoint_indices(
            gold_item, match["predicted_indices"], predicted_items
        )
        endpoint_map[gold_item["item_id"]] = tuple(
            predicted_items[index]["item_id"] for index in endpoint_indices
        )
        semantic_ok = all(
            gold_item["semantic_type"] == predicted["semantic_type"]
            for predicted in predicted_group
        )
        gold_speaker = gold_speakers[gold_item["speaker_ref"]]
        gold_display = normalized(gold_speaker.get("display_name"))
        gold_categories = {
            speaker_category(gold_speaker.get("role")),
            speaker_category(gold_speaker.get("display_name")),
        } - {"", "unknown"}
        attribution_checks: list[bool] = []
        identity_checks: list[bool] = []
        for predicted in predicted_group:
            predicted_speaker = predicted_speakers[predicted["speaker_ref"]]
            predicted_display = normalized(predicted_speaker.get("display_name"))
            display_match = bool(gold_display and predicted_display) and (
                gold_display in predicted_display or predicted_display in gold_display
            )
            predicted_categories = {
                speaker_category(predicted_speaker.get("role")),
                speaker_category(predicted_speaker.get("display_name")),
            } - {"", "unknown"}
            attribution_checks.append(display_match or bool(gold_categories & predicted_categories))
            identity_checks.append(
                gold_speaker["identity_status"] == predicted_speaker["identity_status"]
            )
        attribution_ok = all(attribution_checks)
        field_checks = {
            "semantic_type": semantic_ok,
            "statement_role": all(
                gold_item["statement_role"] == predicted["statement_role"]
                for predicted in predicted_group
            ),
            "speech_role": all(
                gold_item["speech_role"] == predicted["speech_role"]
                for predicted in predicted_group
            ),
            "perspective": all(
                gold_item["perspective"] == predicted["perspective"]
                for predicted in predicted_group
            ),
            "speaker": attribution_ok,
            "identity_status": all(identity_checks),
            "polarity": _group_polarity_matches(gold_item["polarity"], predicted_group),
            "behavior_status": all(
                gold_item["behavior_status"] == predicted["behavior_status"]
                for predicted in predicted_group
            ),
            "temporal_frame": (
                gold_item["semantic_type"] != "behavior"
                or all(
                    gold_item["temporal_frame"] == predicted["temporal_frame"]
                    for predicted in predicted_group
                )
            ),
            "value": grouped_values_equivalent(
                gold_item["value"], [predicted["value"] for predicted in predicted_group]
            ),
            "unknown_fields": set(gold_item["unknown_fields"])
            == {field for predicted in predicted_group for field in predicted["unknown_fields"]},
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
                "predicted_items": [predicted["item_id"] for predicted in predicted_group],
                "relation_endpoint_items": [
                    predicted_items[index]["item_id"] for index in endpoint_indices
                ],
                "quote_similarity": match["quote_similarity"],
                "field_checks": field_checks,
                "predicted_text": [predicted["text"] for predicted in predicted_group],
            }
        )

    matched_gold_relations: set[int] = set()
    relation_true_positive = 0
    relation_false_positive = 0
    predicted_relations = predicted_payload["relations"]
    expected_relations: dict[tuple[str, str, str], set[int]] = {}
    for relation_index, relation in enumerate(sample["relations"]):
        if relation["from_item"] not in endpoint_map or relation["to_item"] not in endpoint_map:
            continue
        for from_item in endpoint_map[relation["from_item"]]:
            for to_item in endpoint_map[relation["to_item"]]:
                expected_relations.setdefault(
                    (relation["type"], from_item, to_item), set()
                ).add(relation_index)
    mapped_endpoint_ids = {
        endpoint_id for endpoint_ids in endpoint_map.values() for endpoint_id in endpoint_ids
    }
    for relation in predicted_relations:
        key = (relation["type"], relation["from_item"], relation["to_item"])
        if key in expected_relations and relation["provenance"] == "source_explicit":
            relation_true_positive += 1
            matched_gold_relations.update(expected_relations[key])
        elif (
            relation["provenance"] == "source_explicit"
            and relation["from_item"] in mapped_endpoint_ids
            and relation["to_item"] in mapped_endpoint_ids
        ):
            relation_false_positive += 1

    gold_count = len(gold_items)
    critical_count = sum(item["critical"] for item in gold_items)
    relation_count = len(sample["relations"])
    matched_predicted_indices = {index for match in matches for index in match["predicted_indices"]}
    relation_matches = len(matched_gold_relations)
    unscored_source_relations = max(
        0, len(predicted_relations) - relation_true_positive - relation_false_positive
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
            relation_true_positive / (relation_true_positive + relation_false_positive)
            if relation_true_positive + relation_false_positive
            else (1.0 if relation_count == 0 else 0.0)
        ),
        "source_relation_precision_scope": "selected_target_endpoints_only",
        "counts": {
            "gold_items": gold_count,
            "matched_items": len(matches),
            "predicted_items": len(predicted_items),
            "unmatched_predicted_items": len(predicted_items) - len(matched_predicted_indices),
            "critical_items": critical_count,
            "matched_critical_items": critical_matched,
            "semantic_correct": semantic_correct,
            "attribution_correct": attribution_correct,
            "critical_all_fields_correct": critical_fields_correct,
            "gold_relations": relation_count,
            "predicted_relations": len(predicted_relations),
            "matched_relations": relation_matches,
            "true_positive_relations": relation_true_positive,
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
    if not args.plan_only and args.replay_report is None:
        raise ValueError(DIRECT_LIVE_DISABLED_MESSAGE)
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    budget_path = args.budget.resolve()
    budget = json.loads(budget_path.read_text(encoding="utf-8"))
    expected_extractor = budget.get("extractor_version_at_plan_time")
    if expected_extractor and expected_extractor != MATERIAL_EXTRACTOR_VERSION:
        raise ValueError(
            f"extractor version drifted: {MATERIAL_EXTRACTOR_VERSION} != {expected_extractor}"
        )
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
                "slot_batching_version": MATERIAL_SLOT_BATCHING_VERSION,
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
    raw_audits: list[dict[str, Any]] = []
    early_stop: dict[str, Any] | None = None
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
            audit_dir = (
                OUT / "raw-audit" / budget["budget_version"] / args.round_id / sample["sample_id"]
            )
            if audit_dir.exists() and any(audit_dir.iterdir()):
                raise ValueError(f"attempt audit already exists: {sample['sample_id']}")
            recorder = AttemptRecorder(
                llm,
                audit_dir=audit_dir,
                budget_version=budget["budget_version"],
                round_id=args.round_id,
                sample_id=sample["sample_id"],
            )
            relation_stage_enabled = budget.get("relation_mode", "atomic_decisions") != "deferred"
            material_run = extract_material_understanding(
                evidence_run,
                llm=recorder,
                max_calls=budget["calls_per_document_per_round_max"],
                material_type=sample["material_type"],
                staged_jsonl=budget.get("response_format")
                in {"material-jsonl-v1", MATERIAL_SLOT_JSONL_VERSION},
                slot_protocol=budget.get("response_format") == MATERIAL_SLOT_JSONL_VERSION,
                max_items_per_packet=budget.get("max_items_per_packet", 30),
                max_slots_per_batch=budget.get("max_slots_per_batch", 8),
                extract_relations=relation_stage_enabled,
                # An intentionally deferred stage is not an omission: leaving
                # relations_required at its default records every packet as
                # incomplete and hides whatever the item stage actually did.
                relations_required=relation_stage_enabled,
                candidate_slot_ids=tuple(
                    budget.get("candidate_slot_ids_by_sample", {}).get(sample["sample_id"], ())
                )
                or None,
            )
            material_run.verify_identity()
            declared_calls = attempted_calls(material_run)
            calls += declared_calls
            stage_names = budget.get("stages", ["combined"])
            bound_attempts = bind_attempt_records(material_run, recorder.attempts, stage_names)
            raw_audits.extend(bound_attempts)
            if len(recorder.attempts) != declared_calls or any(
                record["capture_status"] != "recorded" for record in bound_attempts
            ):
                raise ValueError(f"attempt audit mismatch: {sample['sample_id']}")
            artifact = OUT / f"{material_run.run_id}.json"
            artifact.write_text(material_run.model_dump_json(indent=2), encoding="utf-8")
            result = score_sample(sample, material_run)
            results.append(result)
            stop_reason = stage1_stop_reason(budget, result)
            if stop_reason is not None:
                early_stop = {
                    "reason": stop_reason,
                    "after_sample_id": sample["sample_id"],
                    "not_started_sample_ids": [
                        remaining["sample_id"] for remaining in samples[len(results) :]
                    ],
                }
                break
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
    all_samples_completed = len(results) == len(samples)
    full_acceptance = (
        all_samples_completed
        and aggregate["item_recall"] >= thresholds["item_recall_min"]
        and aggregate["critical_item_recall"] >= thresholds["critical_item_recall"]
        and aggregate["semantic_target_accuracy"] >= thresholds["semantic_recall_min"]
        and aggregate["attribution_target_accuracy"] >= thresholds["attribution_accuracy"]
        and aggregate["critical_all_fields_accuracy"] == 1.0
        and aggregate["source_relation_recall"] >= thresholds["source_relation_recall_min"]
        and aggregate["source_relation_precision"] >= thresholds["source_relation_precision"]
        and all(result["summary"]["complete"] for result in results)
    )
    stage1_gate = (
        evaluate_item_stage_gate(budget, results)
        if not args.replay_report and budget.get("relation_mode") == "deferred"
        else None
    )
    round_gate_passed = stage1_gate["passed"] if stage1_gate is not None else full_acceptance
    report = {
        "scorer_version": MATERIAL_DEVELOPMENT_SCORER_VERSION,
        "slot_batching_version": MATERIAL_SLOT_BATCHING_VERSION,
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
        "early_stop": early_stop,
        "completed_sample_ids": [result["sample_id"] for result in results],
        "not_completed_sample_ids": [
            sample["sample_id"]
            for sample in samples
            if sample["sample_id"] not in {result["sample_id"] for result in results}
        ],
        "deterministic_stress": deterministic_stress,
        "samples": results,
        "aggregate": aggregate,
        "business_acceptance": full_acceptance,
        "stage1_gate": stage1_gate,
        "round_gate_passed": round_gate_passed,
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
    print(
        json.dumps({"report": str(target), "aggregate": aggregate, "accepted": round_gate_passed})
    )
    return int(not round_gate_passed)


if __name__ == "__main__":
    raise SystemExit(main())
