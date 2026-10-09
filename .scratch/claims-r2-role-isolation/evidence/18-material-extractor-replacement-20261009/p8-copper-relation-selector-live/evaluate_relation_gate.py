"""Score the P8 relation payload against the frozen copper target gold."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[5]
P7_PAYLOAD = (
    HERE.parent
    / "p7-copper-selector-v5-zero-call"
    / "replay-store"
    / "objects"
    / "sha256"
    / "59"
    / "592065e674a8a0c1b2ff6764014781b029f8e22f616f0460dc921426b8a2c896.json"
)
GOLD = ROOT / "data/corpus/.audit/r1_material_gold_v1_20260913.json"
SCORER = ROOT / ".scratch/corpus-evidence-pipeline/run_material_development.py"


def main() -> None:
    spec = importlib.util.spec_from_file_location("material_development_scorer", SCORER)
    if spec is None or spec.loader is None:
        raise RuntimeError("scorer import failed")
    scorer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scorer)
    gold = json.loads(GOLD.read_text())
    sample = next(
        value for value in gold["samples"] if value["sample_id"] == "dev-expert-call-copper-foil"
    )
    items_run = json.loads(P7_PAYLOAD.read_text())
    relations_run = json.loads((HERE / "relation-payload.json").read_text())
    combined = dict(items_run["understanding"])
    combined["relations"] = relations_run["understanding"]["relations"]
    understanding = SimpleNamespace(
        model_dump=lambda **_kwargs: combined,
        source=SimpleNamespace(source_rev=combined["source"]["source_rev"]),
    )
    material_run = SimpleNamespace(
        understanding=understanding,
        run_id=relations_run["run_id"],
        summary=lambda: {
            "complete": all(
                packet["status"] == "completed" for packet in relations_run["packet_runs"]
            ),
            "packet_status": {
                status: sum(packet["status"] == status for packet in relations_run["packet_runs"])
                for status in ("completed", "partial", "failed", "deferred")
            },
        },
    )
    result = scorer.score_sample(sample, material_run)
    output = {
        "schema_version": "copper-selector-v5-relation-target-evaluation-1",
        "gold_file": str(GOLD.relative_to(ROOT)),
        "gold_scope": {
            "items": len(sample["items"]),
            "relations": len(sample["relations"]),
            "whole_document_negative_gold": False,
        },
        "candidate_relations": len(combined["relations"]),
        "metrics": {
            key: result[key]
            for key in (
                "item_recall",
                "critical_item_recall",
                "semantic_target_accuracy",
                "attribution_target_accuracy",
                "critical_all_fields_accuracy",
                "source_relation_recall",
            )
        },
        "detail": result.get("detail"),
        "precision_measurable": False,
        "precision_reason": (
            "the frozen copper gold is selected target gold, not exhaustive negative gold"
        ),
    }
    (HERE / "evaluation-summary.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(output["metrics"], ensure_ascii=False))


if __name__ == "__main__":
    main()
