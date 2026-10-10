"""Zero-call score after diagnostic type-to-present normalization."""

from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[5]
SOURCE = (
    ROOT
    / ".scratch"
    / "claims-r2-role-isolation"
    / "evidence"
    / "19-relation-selection-successor-20261010"
    / "r0-p14-counterfactual"
    / "audit_counterfactual.py"
)
EXPECTED_BATCH_ID = (
    "batch:60e684c035b5006cfbe1b68b6fd18ca88a70c41dfc9defd8d93ee2e61ab7e9d7"
)


def _load_evaluator() -> Any:
    spec = importlib.util.spec_from_file_location("issue19_counterfactual", SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError("counterfactual evaluator import failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evaluator: Any = module
    evaluator.P14 = HERE
    return evaluator


def main() -> None:
    evaluator = _load_evaluator()
    raw = json.loads((HERE / "raw-response-audit.json").read_text(encoding="utf-8"))
    audit = json.loads((HERE / "protocol-audit.json").read_text(encoding="utf-8"))
    if audit["batch_id"] != EXPECTED_BATCH_ID or len(raw) != 4:
        raise RuntimeError("Issue 22 audit identity changed")
    context = evaluator._candidate_context()
    packet_ids = list(context["packet_ids"])
    if [row["packet_id"] for row in raw] != packet_ids:
        raise RuntimeError("attempt-to-packet mapping changed")
    reconstructed = evaluator.reparse_responses(raw, context["packet_candidates"])
    score = evaluator.score_gate(reconstructed, context)
    if not reconstructed["reconstructable"]:
        decision = "diagnostic_not_reconstructable"
    elif score["passed"]:
        decision = "format_recoverable_semantics_passed"
    else:
        decision = "format_recoverable_semantics_failed"
    result = {
        "schema_version": "issue22-doubao-lite-zero-call-counterfactual-1",
        "source": {
            "batch_id": EXPECTED_BATCH_ID,
            "plan_sha256": audit["plan_sha256"],
            "candidate_set_id": context["candidate_set"].candidate_set_id,
            "sample_id": context["final_gate"]["sample_id"],
        },
        "constraints": {
            "model_calls": 0,
            "writes_to_live_store": 0,
            "new_gold": 0,
            "raw_result_changed": False,
            "whole_document_precision_measured": False,
            "normalization_is_diagnostic_only": True,
        },
        "reconstruction": {
            "reconstructable": reconstructed["reconstructable"],
            "candidate_decisions": len(reconstructed["decisions"]),
            "present": sum(
                value["decision"] == "present"
                for value in reconstructed["decisions"].values()
            ),
            "provenance_counts": dict(
                sorted(
                    Counter(
                        value["provenance"]
                        for value in reconstructed["decisions"].values()
                    ).items()
                )
            ),
            "errors": reconstructed["errors"],
        },
        "packet_comparison": evaluator.compare_packets(reconstructed, context),
        "score": score,
        "decision": decision,
    }
    (HERE / "counterfactual-summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "reconstruction": result["reconstruction"],
                "score": score,
                "decision": decision,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
