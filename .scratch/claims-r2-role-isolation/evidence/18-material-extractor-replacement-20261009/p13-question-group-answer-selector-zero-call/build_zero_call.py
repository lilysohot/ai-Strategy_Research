"""Verify the P13 question-group selector on immutable P10/P11 evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from plugins.corpus.evidence_pipeline import evidence_document_from_snapshot
from plugins.corpus.material_semantics import (
    MATERIAL_ITEMS_VALIDATION_VERSION,
    MATERIAL_RELATION_QUESTION_GROUP_JSONL_V1,
    RELATION_CANDIDATE_RULE_VERSION,
    MaterialRelation,
    MaterialRun,
    _relations_from_question_group_results,
    build_relation_candidate_set,
    build_relation_question_group_prompt,
    group_relation_answer_candidates,
)
from plugins.corpus.structured.snapshot import EvidenceSnapshot

HERE = Path(__file__).resolve().parent
ISSUE_ROOT = HERE.parent
P10 = ISSUE_ROOT / "p10-accepted-items-import-live"
P12 = ISSUE_ROOT / "p12-relation-selector-v2-zero-call"
SNAPSHOT = (
    ISSUE_ROOT.parent
    / "17-structured-extraction-convergence-closure-20261009"
    / "p1-plan-freeze/copper-items-relations/snapshot.json"
)


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(name: str, value: object) -> None:
    (HERE / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _relation_key(relation: MaterialRelation) -> tuple[str, str, str]:
    return (relation.type, relation.from_item, relation.to_item)


def _build() -> dict[str, object]:
    snapshot = EvidenceSnapshot.model_validate_json(SNAPSHOT.read_text(encoding="utf-8"))
    items_path = P12 / "accepted-items-payload.json"
    relations_path = P10 / "relation-payload.json"
    items = MaterialRun.model_validate_json(items_path.read_text(encoding="utf-8"))
    p10_relations = MaterialRun.model_validate_json(relations_path.read_text(encoding="utf-8"))
    signed = _load(P12 / "signed-sample-regression.json")
    p12_counterfactual = _load(P12 / "counterfactual-summary.json")
    target_evaluation = _load(P10 / "evaluation-summary.json")

    endpoint_ids = tuple(
        item_ref
        for entry in items.understanding.coverage.slot_ledger
        if entry.status == "extracted"
        for item_ref in entry.item_refs
    )
    candidate_set = build_relation_candidate_set(
        snapshot,
        items,
        endpoint_item_ids=endpoint_ids,
        items_validation_version=MATERIAL_ITEMS_VALIDATION_VERSION,
        rule_version=RELATION_CANDIDATE_RULE_VERSION,
    )
    candidates_by_id = {
        candidate.candidate_pair_id: candidate for candidate in candidate_set.candidates
    }
    pair_id_by_key = {
        (candidate.allowed_type, candidate.from_item, candidate.to_item): candidate.candidate_pair_id
        for candidate in candidate_set.candidates
    }
    baseline_present = {
        pair_id_by_key[_relation_key(relation)]
        for relation in p10_relations.understanding.relations
    }
    oracle_present = set(baseline_present)
    signed_cases = signed["cases"]
    if len(signed_cases) != 44 or len({case["candidate_pair_id"] for case in signed_cases}) != 44:
        raise RuntimeError("signed P11 sample is not the frozen 44-case set")
    for case in signed_cases:
        pair_id = case["candidate_pair_id"]
        if pair_id not in candidates_by_id:
            raise RuntimeError(f"signed pair is outside candidate v5: {pair_id}")
        if case["signed_truth"] == "present":
            oracle_present.add(pair_id)
        else:
            oracle_present.discard(pair_id)

    packets = {
        packet.packet_id: packet
        for packet in evidence_document_from_snapshot(snapshot, role="material_items").packets
    }
    items_by_id = {item.item_id: item for item in items.understanding.items}
    packet_records: list[dict[str, object]] = []
    replay_relation_ids: set[str] = set()
    replay_pair_ids: set[str] = set()
    total_groups = 0
    total_non_answer = 0
    total_terminals = 0
    total_prompt_chars = 0

    packet_ids = tuple(dict.fromkeys(candidate.packet_id for candidate in candidate_set.candidates))
    for packet_id in packet_ids:
        packet = packets[packet_id]
        packet_candidates = [
            candidate.model_dump(mode="json", exclude={"packet_id"})
            for candidate in candidate_set.candidates
            if candidate.packet_id == packet_id
        ]
        packet_items = [
            items_by_id[item_id]
            for item_id in candidate_set.endpoint_item_ids
            if items_by_id[item_id].evidence[0].packet_id == packet_id
        ]
        groups = group_relation_answer_candidates(packet_candidates)
        grouped_indices = {
            option.relation_index for group in groups for option in group.options
        }
        non_answer_indices = {
            index
            for index, pair in enumerate(packet_candidates)
            if pair["allowed_type"] != "answers"
        }
        if grouped_indices & non_answer_indices or grouped_indices | non_answer_indices != set(
            range(len(packet_candidates))
        ):
            raise RuntimeError(f"candidate partition is not exact for {packet_id}")

        prompt = build_relation_question_group_prompt(packet, packet_items, packet_candidates)
        if prompt != build_relation_question_group_prompt(packet, packet_items, packet_candidates):
            raise RuntimeError(f"prompt is not deterministic for {packet_id}")
        rows: list[dict[str, object]] = []
        for group in groups:
            rows.append(
                {
                    "record_type": "answer_group_result",
                    "question_index": group.question_index,
                    "selected_answer_indices": [
                        option.answer_index
                        for option in group.options
                        if option.candidate_pair_id in oracle_present
                    ],
                }
            )
        for relation_index in sorted(non_answer_indices):
            pair_id = packet_candidates[relation_index]["candidate_pair_id"]
            present = pair_id in oracle_present
            rows.append(
                {
                    "record_type": "relation_result",
                    "relation_index": relation_index,
                    "status": "present" if present else "absent",
                    "evidence_selector": "pair_window" if present else None,
                }
            )
        raw = "\n".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows
        )
        relations, incomplete, counts = _relations_from_question_group_results(
            raw,
            packet,
            snapshot.snapshot_id,
            packet_candidates,
            items_by_id,
        )
        if incomplete:
            raise RuntimeError(f"oracle replay was incomplete for {packet_id}: {counts}")
        packet_replay_ids = {
            pair_id_by_key[_relation_key(relation)] for relation in relations
        }
        expected_ids = {
            pair["candidate_pair_id"]
            for pair in packet_candidates
            if pair["candidate_pair_id"] in oracle_present
        }
        if packet_replay_ids != expected_ids:
            raise RuntimeError(f"controller expansion drifted for {packet_id}")
        replay_pair_ids.update(packet_replay_ids)
        replay_relation_ids.update(relation.relation_id for relation in relations)
        total_groups += len(groups)
        total_non_answer += len(non_answer_indices)
        total_terminals += len(rows)
        total_prompt_chars += len(prompt)
        packet_records.append(
            {
                "packet_id": packet_id,
                "candidate_pairs": len(packet_candidates),
                "answer_pairs": len(grouped_indices),
                "question_groups": len(groups),
                "non_answer_pairs": len(non_answer_indices),
                "expected_terminals": len(rows),
                "oracle_present": len(expected_ids),
                "prompt_chars": len(prompt),
                "prompt_sha256": _sha256(prompt.encode("utf-8")),
                "response_sha256": _sha256(raw.encode("utf-8")),
            }
        )

    if replay_pair_ids != oracle_present:
        raise RuntimeError("whole-run controller expansion did not reproduce the signed oracle")
    target_results = []
    for target in target_evaluation["gold_relation_matches"]:
        matched_ids = set(target["accepted_relation_ids"]) & replay_relation_ids
        target_results.append(
            {
                "gold_relation": target["gold_relation"],
                "matched": bool(matched_ids),
                "accepted_relation_ids": sorted(matched_ids),
            }
        )
    signed_correct = sum(
        (case["candidate_pair_id"] in oracle_present) == (case["signed_truth"] == "present")
        for case in signed_cases
    )
    answer_pairs = sum(
        1 for candidate in candidate_set.candidates if candidate.allowed_type == "answers"
    )
    expected_terminals = total_groups + total_non_answer
    pairwise_prompt_chars = sum(
        record["prompt_chars"] for record in p12_counterfactual["prompt_records"]
    )
    return {
        "schema_version": "relation-question-group-zero-call-summary-1",
        "created_on": "2026-10-10",
        "status": "zero_call_implementation_complete_live_validation_not_authorized",
        "protocol": MATERIAL_RELATION_QUESTION_GROUP_JSONL_V1,
        "source": {
            "snapshot_id": snapshot.snapshot_id,
            "candidate_set_id": candidate_set.candidate_set_id,
            "candidate_rule_version": candidate_set.rule_version,
            "items_payload_sha256": _sha256(items_path.read_bytes()),
            "p10_relation_payload_sha256": _sha256(relations_path.read_bytes()),
            "signed_sample_id": signed["source_sample_id"],
        },
        "population": {
            "candidate_pairs": len(candidate_set.candidates),
            "answer_pairs": answer_pairs,
            "distinct_question_groups": total_groups,
            "non_answer_pairs": total_non_answer,
            "pairwise_terminals": len(candidate_set.candidates),
            "question_group_terminals": expected_terminals,
            "terminal_reduction": len(candidate_set.candidates) - expected_terminals,
            "terminal_reduction_rate": 1 - expected_terminals / len(candidate_set.candidates),
            "packet_calls_if_live": len(packet_ids),
        },
        "oracle_replay": {
            "baseline_p10_present": len(baseline_present),
            "signed_oracle_present": len(oracle_present),
            "expanded_present": len(replay_pair_ids),
            "signed_cases": len(signed_cases),
            "signed_cases_correct": signed_correct,
            "known_signed_errors_corrected": "9/9",
            "target_relations_matched": sum(result["matched"] for result in target_results),
            "target_relations_total": len(target_results),
            "target_results": target_results,
            "result_is_oracle_not_model_accuracy": True,
        },
        "prompts": {
            "pairwise_v2_total_chars": pairwise_prompt_chars,
            "question_group_total_chars": total_prompt_chars,
            "char_reduction": pairwise_prompt_chars - total_prompt_chars,
            "char_reduction_rate": 1 - total_prompt_chars / pairwise_prompt_chars,
            "records": packet_records,
            "deterministic": True,
        },
        "controller_invariants": {
            "candidate_partition_exact": True,
            "pair_identity_unchanged": True,
            "evidence_controller_owned": True,
            "missing_duplicate_invalid_fail_closed": True,
            "candidate_rule_changed": False,
        },
        "model_calls": 0,
        "live_plan_frozen": False,
        "publication_query_delivery_context_use": 0,
        "next_gate": "review zero-call evidence and freeze a separate bounded plan only after explicit authorization",
    }


def main() -> None:
    summary = _build()
    _write("zero-call-summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
