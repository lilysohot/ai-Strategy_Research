"""Zero-call candidate-v5 pruning delta over the immutable P7 items artifact."""

from __future__ import annotations

import json
from pathlib import Path

from plugins.corpus.material_semantics import (
    MATERIAL_ITEMS_VALIDATION_VERSION,
    RELATION_CANDIDATE_RULE_V4,
    RELATION_CANDIDATE_RULE_VERSION,
    MaterialRun,
    build_relation_candidate_set,
)
from plugins.corpus.structured.snapshot import EvidenceSnapshot

HERE = Path(__file__).resolve().parent
ITEMS_PATH = (
    HERE.parent
    / "p7-copper-selector-v5-zero-call"
    / "replay-store/objects/sha256/59"
    / "592065e674a8a0c1b2ff6764014781b029f8e22f616f0460dc921426b8a2c896.json"
)
SNAPSHOT_PATH = (
    HERE.parents[1]
    / "17-structured-extraction-convergence-closure-20261009"
    / "p1-plan-freeze/copper-items-relations/snapshot.json"
)


def main() -> None:
    snapshot = EvidenceSnapshot.model_validate_json(SNAPSHOT_PATH.read_text())
    items = MaterialRun.model_validate_json(ITEMS_PATH.read_text())
    endpoint_ids = tuple(
        item_ref
        for entry in items.understanding.coverage.slot_ledger
        if entry.status == "extracted"
        for item_ref in entry.item_refs
    )
    sets = {
        version: build_relation_candidate_set(
            snapshot,
            items,
            endpoint_item_ids=endpoint_ids,
            items_validation_version=MATERIAL_ITEMS_VALIDATION_VERSION,
            rule_version=version,
        )
        for version in (RELATION_CANDIDATE_RULE_V4, RELATION_CANDIDATE_RULE_VERSION)
    }
    v4 = {candidate.candidate_pair_id: candidate for candidate in sets[RELATION_CANDIDATE_RULE_V4].candidates}
    v5 = {
        candidate.candidate_pair_id: candidate
        for candidate in sets[RELATION_CANDIDATE_RULE_VERSION].candidates
    }
    added = [candidate for pair_id, candidate in v5.items() if pair_id not in v4]
    removed = [candidate for pair_id, candidate in v4.items() if pair_id not in v5]
    by_id = {item.item_id: item for item in items.understanding.items}
    mitsui_ids = {
        "itm_2519affdac798906",
        "itm_20315c03b3120632",
        "itm_02531d4c6d673b87",
    }
    output = {
        "schema_version": "relation-candidate-v5-counterfactual-1",
        "model_calls": 0,
        "v4_candidates": len(v4),
        "v5_candidates": len(v5),
        "preserved_v4_candidates": len(set(v4) & set(v5)),
        "added_candidates": len(added),
        "removed_candidates": len(removed),
        "added": [candidate.model_dump(mode="json") for candidate in added],
        "removed": [
            {
                **candidate.model_dump(mode="json"),
                "target_text": by_id[candidate.to_item].text,
            }
            for candidate in removed
        ],
        "mitsui_candidates": [
            candidate.model_dump(mode="json")
            for candidate in v5.values()
            if candidate.from_item in mitsui_ids and candidate.to_item in mitsui_ids
        ],
        "interpretation": (
            "v5 removes only answer edges aimed at a facilitator turn-management invitation; "
            "the other v4 source-ordered question candidates, including both Mitsui answer "
            "atoms, remain frozen"
        ),
    }
    (HERE / "candidate-v5-counterfactual.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                key: output[key]
                for key in (
                    "v4_candidates",
                    "v5_candidates",
                    "added_candidates",
                    "removed_candidates",
                    "mitsui_candidates",
                )
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
