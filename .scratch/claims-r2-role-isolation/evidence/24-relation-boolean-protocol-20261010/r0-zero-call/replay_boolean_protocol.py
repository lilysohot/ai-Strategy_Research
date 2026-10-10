"""Replay frozen Issue 22 decisions through question-group JSONL v2 with zero calls."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

from plugins.corpus.evidence_pipeline import build_evidence_run_from_snapshot
from plugins.corpus.material_semantics import (
    MATERIAL_RELATION_QUESTION_GROUP_JSONL_V2,
    _relations_from_question_group_results,
    _strict_role_llm,
    build_relation_question_group_prompt,
    group_relation_answer_candidates,
)

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[5]
CLAIMS = ROOT / ".scratch" / "claims-r2-role-isolation"
ISSUE22 = CLAIMS / "evidence" / "22-doubao-lite-provider-ceiling-20261010" / "p0-256k-minimal-live"
ISSUE23 = CLAIMS / "evidence" / "23-relation-adjudication-correction-20261010" / "r0-zero-call"
EVALUATOR = (
    CLAIMS
    / "evidence"
    / "19-relation-selection-successor-20261010"
    / "r0-p14-counterfactual"
    / "audit_counterfactual.py"
)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON root is not an object: {path}")
    return value


def _load_evaluator() -> Any:
    spec = importlib.util.spec_from_file_location("issue24_evaluator", EVALUATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("counterfactual evaluator import failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evaluator: Any = module
    evaluator.P14 = ISSUE22
    return evaluator


def main() -> None:
    evaluator = _load_evaluator()
    context = evaluator._candidate_context()
    raw_audit = json.loads((ISSUE22 / "raw-response-audit.json").read_text(encoding="utf-8"))
    reconstructed = evaluator.reparse_responses(raw_audit, context["packet_candidates"])
    if not reconstructed["reconstructable"]:
        raise RuntimeError("Issue 22 decisions are not reconstructable")
    decisions = {
        pair_id: value["decision"] for pair_id, value in reconstructed["decisions"].items()
    }
    if len(decisions) != 333:
        raise RuntimeError("frozen candidate decision count drifted")

    evidence_run = build_evidence_run_from_snapshot(context["snapshot"], role="material_items")
    packets = {packet.packet_id: packet for packet in evidence_run.document.packets}
    items = {item.item_id: item for item in context["items"].understanding.items}
    packet_replays: list[dict[str, Any]] = []
    transformed_responses: list[dict[str, Any]] = []
    totals = {
        "candidate_pairs": 0,
        "terminals": 0,
        "relations": 0,
        "missing_decisions": 0,
        "duplicate_decisions": 0,
        "invalid_decisions": 0,
    }

    for packet_id in context["packet_ids"]:
        packet = packets[packet_id]
        candidates = context["packet_candidates"][packet_id]
        groups = group_relation_answer_candidates(candidates)
        rows: list[dict[str, Any]] = []
        for group in groups:
            selected = [
                option.answer_index
                for option in group.options
                if decisions[option.candidate_pair_id] == "present"
            ]
            rows.append(
                {
                    "record_type": "answer_group_result",
                    "question_index": group.question_index,
                    "selected_answer_indices": selected,
                }
            )
        for relation_index, candidate in enumerate(candidates):
            if candidate["allowed_type"] == "answers":
                continue
            rows.append(
                {
                    "record_type": "relation_result",
                    "relation_index": relation_index,
                    "is_present": decisions[candidate["candidate_pair_id"]] == "present",
                }
            )
        content = "\n".join(_canonical(row) for row in rows)
        strict = _strict_role_llm(
            lambda _prompt, response=content: response,
            frozenset({"answer_group_result", "relation_result"}),
            boolean_relation_results=True,
        )
        if strict is None or strict("zero-call replay") != content:
            raise RuntimeError("strict v2 transport validation failed")

        packet_items = [item for item in items.values() if item.evidence[0].packet_id == packet_id]
        prompt = build_relation_question_group_prompt(
            packet,
            packet_items,
            candidates,
            protocol=MATERIAL_RELATION_QUESTION_GROUP_JSONL_V2,
        )
        relations, incomplete, counts = _relations_from_question_group_results(
            content,
            packet,
            context["snapshot"].snapshot_id,
            candidates,
            items,
            protocol=MATERIAL_RELATION_QUESTION_GROUP_JSONL_V2,
        )
        expected_present = {
            (
                candidate["allowed_type"],
                candidate["from_item"],
                candidate["to_item"],
            )
            for candidate in candidates
            if decisions[candidate["candidate_pair_id"]] == "present"
        }
        actual_present = {
            (relation.type, relation.from_item, relation.to_item) for relation in relations
        }
        if incomplete or actual_present != expected_present:
            raise RuntimeError(f"v2 replay failed for packet: {packet_id}")
        totals["candidate_pairs"] += counts["candidate_pairs"]
        totals["terminals"] += counts["decisions"]
        totals["relations"] += len(relations)
        for key in ("missing_decisions", "duplicate_decisions", "invalid_decisions"):
            totals[key] += counts[key]
        packet_replays.append(
            {
                "packet_id": packet_id,
                "protocol": MATERIAL_RELATION_QUESTION_GROUP_JSONL_V2,
                "prompt_sha256": _sha256_text(prompt),
                "response_sha256": _sha256_text(content),
                "candidate_pairs": counts["candidate_pairs"],
                "expected_terminals": counts["expected_terminals"],
                "terminals": counts["decisions"],
                "relations": len(relations),
                "missing_decisions": counts["missing_decisions"],
                "duplicate_decisions": counts["duplicate_decisions"],
                "invalid_decisions": counts["invalid_decisions"],
                "complete": not incomplete,
            }
        )
        transformed_responses.append(
            {
                "packet_id": packet_id,
                "protocol": MATERIAL_RELATION_QUESTION_GROUP_JSONL_V2,
                "zero_model_calls": True,
                "content": content,
            }
        )

    gold = _read_object(ISSUE23 / "gold-v2.agent-draft.json")
    if gold["status"] != "human_signed" or gold["signoff"]["name"] != "xyl":
        raise RuntimeError("gold-v2 is not signed by xyl")
    gold_truth = {row["candidate_pair_id"]: row["truth"] for row in gold["decisions"]}
    correct = sum(decisions[pair_id] == truth for pair_id, truth in gold_truth.items())
    errors = sorted(pair_id for pair_id, truth in gold_truth.items() if decisions[pair_id] != truth)
    if totals != {
        "candidate_pairs": 333,
        "terminals": 100,
        "relations": 212,
        "missing_decisions": 0,
        "duplicate_decisions": 0,
        "invalid_decisions": 0,
    }:
        raise RuntimeError(f"unexpected v2 replay totals: {totals}")

    summary = {
        "schema_version": "relation-question-group-boolean-zero-call-replay-1",
        "created_on": "2026-10-10",
        "status": "zero_call_protocol_replay_passed",
        "protocol": MATERIAL_RELATION_QUESTION_GROUP_JSONL_V2,
        "source_batch_id": "batch:60e684c035b5006cfbe1b68b6fd18ca88a70c41dfc9defd8d93ee2e61ab7e9d7",
        "constraints": {
            "model_calls": 0,
            "production_database_access": 0,
            "historical_issue22_changed": False,
            "model_protocol_compliance_claimed": False,
            "publication_query_delivery_context_use": 0,
        },
        "gold_v2": {
            "status": gold["status"],
            "signer": gold["signoff"]["name"],
            "eligible_cases": len(gold_truth),
        },
        "protocol_replay": {
            "packets_complete": sum(row["complete"] for row in packet_replays),
            "packets_total": len(packet_replays),
            **totals,
        },
        "signed_gold_sensitivity": {
            "correct": correct,
            "eligible_cases": len(gold_truth),
            "accuracy": correct / len(gold_truth),
            "remaining_errors": errors,
        },
        "packets": packet_replays,
        "decision": (
            "the boolean protocol and controller expansion close offline; one bounded live "
            "trial is still required to establish model compliance"
        ),
    }
    (HERE / "transformed-responses.json").write_text(
        json.dumps(transformed_responses, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (HERE / "replay-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    readme = """# Issue 24 · Relation boolean protocol zero-call replay

Status: passed
Model calls: 0

- `material-relations-question-group-jsonl-v2` keeps answer-group local indices.
- Non-answer terminals are exactly `record_type`, `relation_index`, `is_present`.
- Controller restores relation type, pair identity, evidence window and relation ID.
- Frozen Issue 22 decisions replay as 4/4 complete packets, 333/333 candidate decisions,
  100 terminals, 212 present relations, and zero missing/duplicate/invalid decisions.
- Signed gold-v2 sensitivity remains 37/38; the only error is the compatible thickness
  ordering incorrectly selected as a challenge.

This replay proves Interface and parser closure only. It transforms already stored decisions
and therefore does not prove that Doubao Lite will obey the new output shape. A separately
frozen, bounded live trial is required for that claim.
"""
    (HERE / "README.md").write_text(readme, encoding="utf-8")
    print(_canonical(summary))


if __name__ == "__main__":
    main()
