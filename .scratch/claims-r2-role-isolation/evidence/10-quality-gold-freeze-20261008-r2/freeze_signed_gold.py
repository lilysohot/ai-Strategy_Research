"""Build once or verify the signed non-table development-gold freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
REVIEW = HERE.parent / "10-quality-gold-expansion-20261008-r2"
SOURCE_EXPORT = HERE.parent / "10-quality-gold-expansion-20261008-r1/source-prose-units.json"
OUTPUTS = (HERE / "frozen-gold.json", HERE / "freeze-state.json", HERE / "freeze-manifest.json")
SIGNER = "xyl"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(REPO))


def checked_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    review = read_json(REVIEW / "gold-review-candidates.json")
    validation = read_json(REVIEW / "validation-report.json")
    contract = read_json(REVIEW / "scoring-contract.json")
    markdown = (REVIEW / "gold-review.md").read_text(encoding="utf-8")
    if validation["status"] != "valid_review_draft" or validation["errors"]:
        raise SystemExit("signed review is not a valid review draft")
    if review.get("reviewer") != SIGNER or review.get("adjudicator") != SIGNER:
        raise SystemExit("reviewer/adjudicator signature mismatch")
    if f"审核人：{SIGNER}" not in markdown or f"裁定人：{SIGNER}" not in markdown:
        raise SystemExit("human-readable signatures are missing")
    if review.get("candidate_outputs_observed_before_draft") is not False:
        raise SystemExit("review is not pre-candidate")
    if (
        review.get("table_content_included") is not False
        or review.get("holdout_accessed") is not False
    ):
        raise SystemExit("review boundary violation")
    if any(record["review_status"] != "pending" for record in review["records"]):
        raise SystemExit("draft was mutated after blanket signoff; adjudicate in a successor")
    if contract["status"] != "draft_pending_human_review":
        raise SystemExit("unexpected scoring-contract status")
    if contract["evaluation_scope"] != review["evaluation_scope"]:
        raise SystemExit("scope mismatch")
    return review, contract


def build_payloads() -> tuple[dict[str, Any], dict[str, Any]]:
    review, contract = checked_inputs()
    records = []
    for record in review["records"]:
        frozen = dict(record)
        frozen["review_status"] = "accepted"
        frozen["adjudication"] = {
            "reviewer": SIGNER,
            "decision": "accepted",
            "reason": "用户于 2026-10-08 明确签认 r2 两份审阅文档；按整包原样接受。",
            "changes": [],
        }
        records.append(frozen)
    counts = {
        role: sum(record["role"] == role for record in records)
        for role in ("claims", "material_items", "material_relations")
    }
    frozen_gold = {
        "schema_version": "corpus-structured-non-table-gold-freeze-v2",
        "status": "frozen",
        "formal_gold_frozen": True,
        "frozen_on": "2026-10-08",
        "reviewer": SIGNER,
        "adjudicator": SIGNER,
        "signoff_evidence": [
            relative(REVIEW / "gold-review-candidates.json"),
            relative(REVIEW / "gold-review.md"),
        ],
        "parent_review": relative(REVIEW),
        "evaluation_scope": review["evaluation_scope"],
        "candidate_outputs_observed_before_freeze": False,
        "table_content_included": False,
        "holdout_accessed": False,
        "sources": review["sources"],
        "speakers": review["speakers"],
        "condition_groups": review["condition_groups"],
        "retired_records": review["retired_records"],
        "counts": counts,
        "known_ambiguities": [
            {
                "record_id": "NT-I17",
                "field": "condition_inner_boolean",
                "decision": "preserve_unknown",
            }
        ],
        "scoring_contract_sha256": sha256(REVIEW / "scoring-contract.json"),
        "records": records,
    }
    state = {
        "schema_version": "corpus-structured-non-table-gold-freeze-state-v2",
        "status": "frozen_ready_for_candidate_evaluation",
        "formal_gold_frozen": True,
        "quality_gate_passed": False,
        "candidate_execution_authorized": True,
        "authorization_provenance": [
            "user_chat_2026-10-08_model_calls_unlimited_no_infinite_loop",
            "user_chat_2026-10-08_r2_documents_signed",
        ],
        "reviewer": SIGNER,
        "adjudicator": SIGNER,
        "counts": counts,
        "evaluation_scope": review["evaluation_scope"],
        "candidate_outputs_observed_before_freeze": False,
        "table_content_included": False,
        "holdout_accessed": False,
        "model_calls_during_freeze": 0,
        "production_database_access": 0,
        "next_gate": "run bounded candidates on frozen input scope; adjudicate every output; then score",
        "scoring_contract": relative(REVIEW / "scoring-contract.json"),
        "contract_snapshot": contract,
    }
    return frozen_gold, state


def build() -> None:
    if any(path.exists() for path in OUTPUTS):
        raise SystemExit("refusing to overwrite immutable freeze outputs")
    frozen_gold, state = build_payloads()
    (HERE / "frozen-gold.json").write_text(
        json.dumps(frozen_gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "freeze-state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    input_paths = [
        REVIEW / "gold-review-candidates.json",
        REVIEW / "gold-review.md",
        REVIEW / "scoring-contract.json",
        REVIEW / "validation-report.json",
        REVIEW / "draft-manifest.json",
        SOURCE_EXPORT,
    ]
    for source in frozen_gold["sources"]:
        input_paths.append(REPO / source["path"])
    output_paths = [
        HERE / "README.md",
        HERE / "freeze_signed_gold.py",
        HERE / "frozen-gold.json",
        HERE / "freeze-state.json",
    ]
    manifest = {
        "schema_version": "corpus-structured-non-table-gold-freeze-manifest-v2",
        "status": "frozen",
        "created_on": "2026-10-08",
        "parent_review": relative(REVIEW),
        "formal_gold_frozen": True,
        "quality_gate_passed": False,
        "inputs": {relative(path): sha256(path) for path in input_paths},
        "outputs": {relative(path): sha256(path) for path in output_paths},
    }
    (HERE / "freeze-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def verify() -> None:
    checked_inputs()
    manifest = read_json(HERE / "freeze-manifest.json")
    if manifest["status"] != "frozen" or manifest["quality_gate_passed"] is not False:
        raise SystemExit("invalid freeze manifest state")
    for group in ("inputs", "outputs"):
        for name, expected in manifest[group].items():
            if sha256(REPO / name) != expected:
                raise SystemExit(f"hash mismatch: {name}")
    gold = read_json(HERE / "frozen-gold.json")
    state = read_json(HERE / "freeze-state.json")
    if any(record["review_status"] != "accepted" for record in gold["records"]):
        raise SystemExit("not every frozen record is accepted")
    if gold["counts"] != {"claims": 20, "material_items": 48, "material_relations": 24}:
        raise SystemExit("frozen counts changed")
    if not gold["formal_gold_frozen"] or state["quality_gate_passed"]:
        raise SystemExit("freeze/quality states are inconsistent")
    print(json.dumps({"status": "verified", "counts": gold["counts"]}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    verify() if args.verify else build()


if __name__ == "__main__":
    main()
