"""Zero-call candidate-v4 delta over the immutable P7 items artifact."""

from __future__ import annotations

import json
from pathlib import Path

from plugins.corpus.material_semantics import (
    MATERIAL_ITEMS_VALIDATION_VERSION,
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
        for version in ("material-relation-candidates-v3", "material-relation-candidates-v4")
    }
    v3 = {candidate.candidate_pair_id: candidate for candidate in sets["material-relation-candidates-v3"].candidates}
    v4 = {candidate.candidate_pair_id: candidate for candidate in sets["material-relation-candidates-v4"].candidates}
    added = [candidate for pair_id, candidate in v4.items() if pair_id not in v3]
    removed = [candidate for pair_id, candidate in v3.items() if pair_id not in v4]
    mitsui_ids = {
        "itm_2519affdac798906",
        "itm_20315c03b3120632",
        "itm_02531d4c6d673b87",
    }
    output = {
        "schema_version": "relation-candidate-v4-counterfactual-1",
        "model_calls": 0,
        "v3_candidates": len(v3),
        "v4_candidates": len(v4),
        "preserved_v3_candidates": len(set(v3) & set(v4)),
        "added_candidates": len(added),
        "removed_candidates": len(removed),
        "added": [candidate.model_dump(mode="json") for candidate in added],
        "removed": [candidate.model_dump(mode="json") for candidate in removed],
        "mitsui_candidates": [
            candidate.model_dump(mode="json")
            for candidate in v4.values()
            if candidate.from_item in mitsui_ids and candidate.to_item in mitsui_ids
        ],
        "interpretation": (
            "v4 processes questions in source order, so a trailing question inside an answer "
            "turn no longer erases the preceding caller question before candidate generation"
        ),
    }
    (HERE / "candidate-v4-counterfactual.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {key: output[key] for key in ("v3_candidates", "v4_candidates", "added_candidates", "removed_candidates", "mitsui_candidates")},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
