"""Freeze a reusable, zero-call precision sample over the P10 relation decisions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from plugins.corpus.evidence_pipeline import build_evidence_run_from_snapshot
from plugins.corpus.material_semantics import (
    MATERIAL_ITEMS_VALIDATION_VERSION,
    RELATION_CANDIDATE_RULE_VERSION,
    MaterialRun,
    _relation_pair_window,
    build_relation_candidate_set,
)
from plugins.corpus.structured.snapshot import EvidenceSnapshot

HERE = Path(__file__).resolve().parent
ISSUE_ROOT = HERE.parent
P10 = ISSUE_ROOT / "p10-accepted-items-import-live"
STORE = P10 / "live-store"
SNAPSHOT = (
    ISSUE_ROOT.parent
    / "17-structured-extraction-convergence-closure-20261009"
    / "p1-plan-freeze/copper-items-relations/snapshot.json"
)
SAMPLE_VERSION = "relation-precision-sample-v1"
PRESENT_ANSWER_QUOTAS = {
    "e108c939f724308f632c568300f357f52ac23179e62b056cb947a0549ff77eb5": 3,
    "2b35e7331ea30bfe3b93b314be9fec8c5719c53ecbbb9c4b5944178d7c057f24": 5,
    "57f2c897c0d8215402f65bb9aa382069153df56dd5ffd2e844576c3a47685f19": 5,
}
ABSENT_STRATUM_QUOTAS = {
    # These are recall sentinels, never part of the precision denominator.
    ("e108c939f724308f632c568300f357f52ac23179e62b056cb947a0549ff77eb5", "answers"): 2,
    ("e108c939f724308f632c568300f357f52ac23179e62b056cb947a0549ff77eb5", "supports"): 1,
    ("2b35e7331ea30bfe3b93b314be9fec8c5719c53ecbbb9c4b5944178d7c057f24", "challenges"): 2,
    ("b4f469a04092ab4cf3f8f60bf74a3e5401806b0a3d0cb74e66cf7550b637b9c1", "answers"): 3,
    ("b4f469a04092ab4cf3f8f60bf74a3e5401806b0a3d0cb74e66cf7550b637b9c1", "challenges"): 1,
    ("b4f469a04092ab4cf3f8f60bf74a3e5401806b0a3d0cb74e66cf7550b637b9c1", "supports"): 1,
    ("57f2c897c0d8215402f65bb9aa382069153df56dd5ffd2e844576c3a47685f19", "challenges"): 2,
}


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


def _stable_rank(candidate_pair_id: str) -> str:
    return hashlib.sha256(f"{SAMPLE_VERSION}|{candidate_pair_id}".encode()).hexdigest()


def _sha256_json(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def _write(name: str, value: object) -> None:
    (HERE / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    connection = sqlite3.connect(
        f"file:{STORE / 'index/structured.sqlite3'}?mode=ro", uri=True
    )
    connection.row_factory = sqlite3.Row
    tasks = {
        row["role"]: dict(row)
        for row in connection.execute("SELECT * FROM tasks ORDER BY derived, task_id")
    }
    connection.close()

    item_payload_raw = _read_object(tasks["material_items"]["payload_object_sha256"])
    relation_payload_raw = _read_object(
        tasks["material_relations"]["payload_object_sha256"]
    )
    items = MaterialRun.model_validate(item_payload_raw)
    relations = MaterialRun.model_validate(relation_payload_raw)
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
    evidence_run = build_evidence_run_from_snapshot(snapshot, role="material_items")
    packets = {packet.packet_id: packet for packet in evidence_run.document.packets}
    items_by_id = {item.item_id: item for item in items.understanding.items}
    present_keys = {
        (relation.type, relation.from_item, relation.to_item)
        for relation in relations.understanding.relations
    }

    rows: list[dict[str, Any]] = []
    for candidate in candidate_set.candidates:
        pair = candidate.model_dump(mode="json")
        decision = (
            "present"
            if (candidate.allowed_type, candidate.from_item, candidate.to_item)
            in present_keys
            else "absent"
        )
        window = _relation_pair_window(
            packets[candidate.packet_id],
            snapshot.snapshot_id,
            pair,
            items_by_id,
        )
        source = items_by_id[candidate.from_item]
        target = items_by_id[candidate.to_item]
        rows.append(
            {
                **pair,
                "selector_decision": decision,
                "stable_rank": _stable_rank(candidate.candidate_pair_id),
                "from_endpoint": {
                    key: getattr(source, key)
                    for key in (
                        "text",
                        "speech_role",
                        "statement_role",
                        "semantic_type",
                        "perspective",
                        "polarity",
                    )
                },
                "to_endpoint": {
                    key: getattr(target, key)
                    for key in (
                        "text",
                        "speech_role",
                        "statement_role",
                        "semantic_type",
                        "perspective",
                        "polarity",
                    )
                },
                "pair_window": window.model_dump(mode="json"),
            }
        )

    by_stratum: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_stratum[
            (row["selector_decision"], row["packet_id"], row["allowed_type"])
        ].append(row)
    for values in by_stratum.values():
        values.sort(key=lambda row: (row["stable_rank"], row["candidate_pair_id"]))

    selected_present: list[dict[str, Any]] = []
    for (decision, packet_id, relation_type), values in sorted(by_stratum.items()):
        if decision != "present":
            continue
        quota = (
            PRESENT_ANSWER_QUOTAS[packet_id]
            if relation_type == "answers"
            else len(values)
        )
        selected_present.extend(values[:quota])

    selected_absent: list[dict[str, Any]] = []
    for (packet_id, relation_type), quota in ABSENT_STRATUM_QUOTAS.items():
        selected_absent.extend(by_stratum[("absent", packet_id, relation_type)][:quota])

    selected_present.sort(key=lambda row: (row["packet_id"], row["allowed_type"], row["stable_rank"]))
    selected_absent.sort(key=lambda row: (row["packet_id"], row["allowed_type"], row["stable_rank"]))
    universe_counts = Counter(
        (row["selector_decision"], row["packet_id"], row["allowed_type"])
        for row in rows
    )
    sample_counts = Counter(
        (row["selector_decision"], row["packet_id"], row["allowed_type"])
        for row in selected_present + selected_absent
    )
    strata = [
        {
            "selector_decision": decision,
            "packet_id": packet_id,
            "allowed_type": relation_type,
            "universe_count": count,
            "sample_count": sample_counts[(decision, packet_id, relation_type)],
            "inclusion_probability": (
                sample_counts[(decision, packet_id, relation_type)] / count
            ),
            "metric_role": (
                "precision_denominator"
                if decision == "present"
                else "recall_sentinel_only"
            ),
        }
        for (decision, packet_id, relation_type), count in sorted(universe_counts.items())
    ]
    sample = {
        "schema_version": "relation-precision-sample-1",
        "sample_version": SAMPLE_VERSION,
        "created_on": "2026-10-10",
        "source": {
            "p10_batch_id": "batch:da6a70bbc4152430bf01a75201e198a1846146d51e0a99f1c2639b82559e3b78",
            "candidate_set_id": candidate_set.candidate_set_id,
            "candidate_rule_version": candidate_set.rule_version,
            "relation_artifact_id": tasks["material_relations"]["artifact_id"],
            "relation_payload_sha256": tasks["material_relations"]["payload_sha256"],
            "snapshot_id": snapshot.snapshot_id,
        },
        "sampling_method": {
            "rank": "sha256(sample_version + '|' + candidate_pair_id)",
            "present": (
                "census every non-answers stratum; stable-hash sample answers by packet "
                "with frozen quotas 3/5/5"
            ),
            "absent": (
                "stable-hash sentinel sample with frozen packet/type quotas; excluded "
                "from precision denominator"
            ),
            "estimator": (
                "stratified expansion: sum(N_h * accepted_h / n_h) / 217; "
                "do not use the raw unweighted acceptance rate"
            ),
        },
        "counts": {
            "candidate_universe": len(rows),
            "present_universe": sum(row["selector_decision"] == "present" for row in rows),
            "absent_universe": sum(row["selector_decision"] == "absent" for row in rows),
            "precision_sample": len(selected_present),
            "recall_sentinel_sample": len(selected_absent),
        },
        "strata": strata,
        "precision_sample": selected_present,
        "recall_sentinel_sample": selected_absent,
    }
    sample["sample_id"] = _sha256_json(sample)
    _write("sample-plan.json", sample)

    draft = {
        "schema_version": "relation-adjudication-draft-1",
        "sample_id": sample["sample_id"],
        "status": "agent_draft_unsigned",
        "human_signoff_required": True,
        "adjudication_rule": {
            "present": "accept only when the typed relation is explicit in the frozen pair window",
            "absent": "accept when no typed relation is explicit; absent rows are recall sentinels only",
            "endpoint_rule": "judge the atomic endpoint texts, not topical co-occurrence alone",
        },
        "precision_decisions": [
            {
                "candidate_pair_id": row["candidate_pair_id"],
                "agent_decision": None,
                "reason": None,
                "human_decision": None,
            }
            for row in selected_present
        ],
        "recall_sentinel_decisions": [
            {
                "candidate_pair_id": row["candidate_pair_id"],
                "agent_decision": None,
                "reason": None,
                "human_decision": None,
            }
            for row in selected_absent
        ],
    }
    _write("candidate-adjudications.agent-draft.json", draft)
    print(
        json.dumps(
            {
                "sample_id": sample["sample_id"],
                "counts": sample["counts"],
                "strata_sampled": sum(value["sample_count"] > 0 for value in strata),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
