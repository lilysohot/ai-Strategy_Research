"""Build the signed P11 delta and selector-v2 prompt counterfactual without model calls."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from plugins.corpus.evidence_pipeline import build_evidence_run_from_snapshot
from plugins.corpus.material_semantics import (
    MATERIAL_ITEMS_VALIDATION_VERSION,
    MATERIAL_RELATION_SELECTOR_JSONL_VERSION,
    RELATION_CANDIDATE_RULE_VERSION,
    MaterialRun,
    build_relation_candidate_set,
    build_relation_selector_prompt,
)
from plugins.corpus.structured.snapshot import EvidenceSnapshot

HERE = Path(__file__).resolve().parent
ISSUE_ROOT = HERE.parent
P10 = ISSUE_ROOT / "p10-accepted-items-import-live"
P11 = ISSUE_ROOT / "p11-relation-precision-sample"
STORE = P10 / "live-store"
SNAPSHOT = (
    ISSUE_ROOT.parent
    / "17-structured-extraction-convergence-closure-20261009"
    / "p1-plan-freeze/copper-items-relations/snapshot.json"
)
ITEM_PAYLOAD = "sha256:592065e674a8a0c1b2ff6764014781b029f8e22f616f0460dc921426b8a2c896"
RELATION_PAYLOAD = "sha256:5336b091f19462ee999f148bedbfeba7e0df2a9b2bc17368d37ae2080c9cb137"


def _read_object(object_sha256: str) -> dict[str, Any]:
    digest = object_sha256.removeprefix("sha256:")
    path = STORE / "objects/sha256" / digest[:2] / f"{digest}.json"
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise RuntimeError(f"object hash mismatch: {object_sha256}")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError(f"object is not a mapping: {object_sha256}")
    return value


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _write(name: str, value: object) -> None:
    (HERE / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    sample = json.loads((P11 / "sample-plan.json").read_text(encoding="utf-8"))
    adjudication = json.loads(
        (P11 / "candidate-adjudications.agent-draft.json").read_text(encoding="utf-8")
    )
    if adjudication["status"] != "human_signed":
        raise RuntimeError("P11 adjudication is not signed")
    if adjudication["sample_id"] != sample["sample_id"]:
        raise RuntimeError("P11 sample/adjudication identity mismatch")

    p10_plan = json.loads((P10 / "plan.json").read_text(encoding="utf-8"))
    item_artifact_raw = p10_plan["imported_material_items"]["artifact"]
    item_payload_raw = _read_object(ITEM_PAYLOAD)
    items = MaterialRun.model_validate(item_payload_raw)
    relations = MaterialRun.model_validate(_read_object(RELATION_PAYLOAD))
    snapshot = EvidenceSnapshot.model_validate_json(SNAPSHOT.read_text(encoding="utf-8"))
    items.verify_identity()
    relations.verify_identity()
    snapshot.verify_identity()
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
    if candidate_set.candidate_set_id != sample["source"]["candidate_set_id"]:
        raise RuntimeError("candidate set drifted from signed P11 sample")

    candidates = {
        candidate.candidate_pair_id: candidate for candidate in candidate_set.candidates
    }
    item_by_id = {item.item_id: item for item in items.understanding.items}
    present_keys = {
        (relation.type, relation.from_item, relation.to_item): relation
        for relation in relations.understanding.relations
    }
    baseline: dict[str, str] = {}
    for candidate in candidate_set.candidates:
        key = (candidate.allowed_type, candidate.from_item, candidate.to_item)
        baseline[candidate.candidate_pair_id] = "present" if key in present_keys else "absent"

    decisions = {
        row["candidate_pair_id"]: row
        for row in (
            adjudication["precision_decisions"]
            + adjudication["recall_sentinel_decisions"]
        )
    }
    overrides: list[dict[str, Any]] = []
    counterfactual = dict(baseline)
    for pair_id, decision in decisions.items():
        action = decision["agent_decision"]
        expected = (
            "absent"
            if action == "reject_false_positive"
            else "present"
            if action == "overturn_false_negative"
            else baseline[pair_id]
        )
        if expected == baseline[pair_id]:
            continue
        candidate = candidates[pair_id]
        counterfactual[pair_id] = expected
        overrides.append(
            {
                "candidate_pair_id": pair_id,
                "packet_id": candidate.packet_id,
                "allowed_type": candidate.allowed_type,
                "p10_decision": baseline[pair_id],
                "signed_expected_decision": expected,
                "from_item": candidate.from_item,
                "from_text": item_by_id[candidate.from_item].text,
                "to_item": candidate.to_item,
                "to_text": item_by_id[candidate.to_item].text,
                "reason": decision["reason"],
            }
        )

    expected_override_counts = Counter(
        (row["p10_decision"], row["signed_expected_decision"]) for row in overrides
    )
    if expected_override_counts != Counter({("present", "absent"): 5, ("absent", "present"): 4}):
        raise RuntimeError(f"unexpected signed delta: {expected_override_counts}")

    target_evaluation = json.loads(
        (P10 / "evaluation-summary.json").read_text(encoding="utf-8")
    )
    target_relation_ids = {
        relation_id
        for match in target_evaluation["gold_relation_matches"]
        for relation_id in match["accepted_relation_ids"]
    }
    removed_relation_ids = set()
    for row in overrides:
        if row["p10_decision"] != "present":
            continue
        candidate = candidates[row["candidate_pair_id"]]
        relation = present_keys[
            (candidate.allowed_type, candidate.from_item, candidate.to_item)
        ]
        removed_relation_ids.add(relation.relation_id)

    evidence_run = build_evidence_run_from_snapshot(snapshot, role="material_items")
    packet_by_id = {packet.packet_id: packet for packet in evidence_run.document.packets}
    prompt_records = []
    for packet_id in dict.fromkeys(
        candidate.packet_id for candidate in candidate_set.candidates
    ):
        packet_candidates = [
            candidate.model_dump(mode="json", exclude={"packet_id"})
            for candidate in candidate_set.candidates
            if candidate.packet_id == packet_id
        ]
        packet_items = [
            item_by_id[item_id]
            for item_id in candidate_set.endpoint_item_ids
            if item_by_id[item_id].evidence[0].packet_id == packet_id
        ]
        prompt = build_relation_selector_prompt(
            packet_by_id[packet_id],
            packet_items,
            packet_candidates,
            protocol=MATERIAL_RELATION_SELECTOR_JSONL_VERSION,
        )
        prompt_records.append(
            {
                "packet_id": packet_id,
                "candidate_pairs": len(packet_candidates),
                "prompt_chars": len(prompt),
                "prompt_sha256": _sha256_text(prompt),
            }
        )

    calibration = {
        "schema_version": "relation-selector-v2-signed-calibration-1",
        "created_on": "2026-10-10",
        "source_sample_id": sample["sample_id"],
        "signoff": adjudication["signoff"],
        "candidate_set_id": candidate_set.candidate_set_id,
        "candidate_rule_version": candidate_set.rule_version,
        "selector_protocol": MATERIAL_RELATION_SELECTOR_JSONL_VERSION,
        "cases": sorted(overrides, key=lambda row: row["candidate_pair_id"]),
    }
    summary = {
        "schema_version": "relation-selector-v2-zero-call-counterfactual-1",
        "created_on": "2026-10-10",
        "status": "zero_call_contract_remediation_complete_live_validation_not_started",
        "source": {
            "sample_id": sample["sample_id"],
            "candidate_set_id": candidate_set.candidate_set_id,
            "candidate_rule_version": candidate_set.rule_version,
            "item_payload_sha256": ITEM_PAYLOAD,
            "relation_payload_sha256": RELATION_PAYLOAD,
        },
        "protocol": {
            "legacy_read_compatible": "material-relations-selector-jsonl-v1",
            "new_write_version": MATERIAL_RELATION_SELECTOR_JSONL_VERSION,
            "candidate_rule_changed": False,
            "schema_shape_changed": False,
            "semantic_contract_changed": True,
        },
        "baseline": {
            "candidates": len(baseline),
            "present": sum(value == "present" for value in baseline.values()),
            "absent": sum(value == "absent" for value in baseline.values()),
        },
        "signed_delta_counterfactual": {
            "overrides": len(overrides),
            "present_to_absent": expected_override_counts[("present", "absent")],
            "absent_to_present": expected_override_counts[("absent", "present")],
            "resulting_present": sum(
                value == "present" for value in counterfactual.values()
            ),
            "resulting_absent": sum(
                value == "absent" for value in counterfactual.values()
            ),
            "target_relation_ids_removed": sorted(
                target_relation_ids & removed_relation_ids
            ),
            "target_recall_preserved_by_signed_delta": not bool(
                target_relation_ids & removed_relation_ids
            ),
            "interpretation": (
                "This applies only the nine signed P11 corrections. It is an oracle "
                "counterfactual, not a claim that selector v2 has already produced them."
            ),
        },
        "prompt_records": prompt_records,
        "model_calls": 0,
        "publication_query_delivery_context_use": 0,
        "next_gate": (
            "freeze a separate selector-v2 relation-only plan; execution requires an "
            "explicit new live-call authorization"
        ),
    }
    _write("signed-calibration-cases.json", calibration)
    _write("counterfactual-summary.json", summary)
    _write("accepted-items-artifact.json", item_artifact_raw)
    _write("accepted-items-payload.json", item_payload_raw)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
