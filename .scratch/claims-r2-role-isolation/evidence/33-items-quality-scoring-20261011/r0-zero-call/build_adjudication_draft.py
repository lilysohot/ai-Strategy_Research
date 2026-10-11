"""Stage 2 (draft) of the issue-33 gate: pre-fill the adjudication skeleton.

Zero call, read-only against the frozen inputs. Only the Stage-1 suggestions flagged high
or medium are pre-filled as `accepted` drafts, after a greedy one-to-one assignment that
reserves each gold record for at most one candidate. Everything else stays `pending` with an
explicit hint. The draft is a reviewer aid: judgement stays empty-signature until the
reviewer confirms or edits it, exactly as contract v3 requires.

Also emits a provisional preview (matched gold count, unreviewed backlog, coverage gaps as
recall upper bound) which is explicitly NOT a gate result.

Writes adjudications.draft.json and draft-preview.json.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E33 = HERE.parent
CLAIMS = E33.parent.parent
E10 = CLAIMS / "evidence"
GOLD = E10 / "10-quality-gold-freeze-20261008-r2" / "frozen-gold.json"
CONTRACT = E10 / "10-quality-gold-expansion-20261008-r2" / "scoring-contract.json"
WORKBENCH = HERE / "workbench.json"
SKELETON = HERE / "adjudications.json"
PRE_FILL_CONFIDENCE = {"high", "medium"}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_fields(semantic_fields: dict[str, Any]) -> list[list[str]]:
    pairs = sorted(
        (key, value)
        for key, value in (semantic_fields or {}).items()
        if isinstance(value, str) and value
    )
    return [[key, value] for key, value in pairs]


def main() -> None:
    workbench = read_json(WORKBENCH)
    skeleton = read_json(SKELETON)
    gold = read_json(GOLD)
    contract = read_json(CONTRACT)
    gold_items = [row for row in gold["records"] if row["role"] == "material_items"]
    gold_by_id = {row["record_id"]: row for row in gold_items}
    contract_thresholds = {
        "target_recall_overall_min": 0.85,
        "candidate_precision_min": 0.80,
        "source": "non-table-selected-target-scoring-contract-v3",
    }

    suggestions = {item["candidate_id"]: item for item in workbench["suggestions"]}
    pairs: list[dict[str, Any]] = []
    for candidate_id, entry in suggestions.items():
        for item in entry["top_suggestions"]:
            pairs.append(
                {
                    "candidate_id": candidate_id,
                    "gold_record_id": item["gold_record_id"],
                    "score": item["score"],
                    "confidence": item["confidence"],
                }
            )
    pairs.sort(key=lambda item: (-item["score"], item["candidate_id"]))

    assigned_gold: dict[str, str] = {}
    assigned_candidate: dict[str, dict[str, Any]] = {}
    dropped: list[dict[str, Any]] = []
    for pair in pairs:
        if pair["gold_record_id"] in assigned_gold or pair["candidate_id"] in assigned_candidate:
            dropped.append(pair)
            continue
        assigned_gold[pair["gold_record_id"]] = pair["candidate_id"]
        assigned_candidate[pair["candidate_id"]] = pair

    draft_candidates: list[dict[str, Any]] = []
    accepted = 0
    for entry in skeleton["candidates"]:
        candidate_id = entry["candidate_id"]
        assignment = assigned_candidate.get(candidate_id)
        if assignment is not None and assignment["confidence"] in PRE_FILL_CONFIDENCE:
            gold_row = gold_by_id[assignment["gold_record_id"]]
            entry = {
                **entry,
                "judgement": "accepted",
                "matched_gold_id": assignment["gold_record_id"],
                "canonical_observed_fields": {
                    key: value for key, value in canonical_fields(gold_row["semantic_fields"])
                },
                "reason": (
                    f"stage1 {assignment['confidence']} suggestion (score {assignment['score']}) "
                    "from number overlap and character bigrams; reviewer confirmation required"
                ),
                "draft": True,
            }
            accepted += 1
        else:
            best = suggestions[candidate_id]["top_suggestions"]
            if best and best[0]["score"] > 0:
                hint = f"low_confidence_suggestion:{best[0]['gold_record_id']}:{best[0]['score']}"
            else:
                hint = "no_suggestion"
            entry = {
                **entry,
                "judgement": "pending",
                "matched_gold_id": None,
                "reason": hint,
                "draft": True,
            }
        draft_candidates.append(entry)

    matched_gold_ids = sorted(
        entry["matched_gold_id"] for entry in draft_candidates if entry["matched_gold_id"]
    )
    pending = [entry for entry in draft_candidates if entry["judgement"] == "pending"]
    no_suggestion = [entry for entry in pending if entry["reason"] == "no_suggestion"]
    low_pending = [entry for entry in pending if entry["reason"].startswith("low_confidence")]
    critical_gold = {row["record_id"] for row in gold_items if row.get("critical")}
    risk_condition_gold = {row["record_id"] for row in gold_items if row.get("risk_or_condition")}
    missing_gold = sorted(set(gold_by_id) - set(matched_gold_ids))

    residual = read_json(
        CLAIMS
        / "evidence"
        / "32-items-v6-reasoning-refreeze-20261011"
        / "live"
        / "residual-attribution.json"
    )

    draft = {
        "schema_version": "items-quality-adjudications-draft-1",
        "status": "draft_pending_reviewer_confirmation",
        "gate": "33-items-quality-scoring-gate",
        "contract": contract["schema_version"],
        "authorization_basis": (
            "issue-33 §9 named countersignature (xyl, 2026-10-11, 准予执行) plus the user "
            "instruction '已签认，开始执行'; the §7 table was left blank, so parameters are "
            "taken verbatim from §4/§7 wording: read-only gold consumption, diagnostic "
            "reporting only, no gold change, no publication, no production database"
        ),
        "reviewer": "",
        "signed_on": "",
        "counts": {
            "candidates_total": len(draft_candidates),
            "accepted_draft": accepted,
            "pending_total": len(pending),
            "pending_low_confidence": len(low_pending),
            "pending_no_suggestion": len(no_suggestion),
            "assigned_pairs_dropped_by_one_to_one": len(dropped),
        },
        "candidates": draft_candidates,
        "gold_reference": skeleton["gold_reference"],
        "advisory_note": (
            "accepted entries are drafts generated from Stage-1 suggestions; contract v3 forbids "
            "automated semantic scoring, so no score may be reported until the reviewer signs"
        ),
    }
    (HERE / "adjudications.draft.json").write_text(
        json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    preview = {
        "schema_version": "items-quality-draft-preview-1",
        "status": "provisional_not_a_gate_result",
        "created_on": "2026-10-11",
        "inputs": {
            "workbench": digest(WORKBENCH),
            "frozen_gold": digest(GOLD),
            "scoring_contract": digest(CONTRACT),
        },
        "draft_recall_upper_bound": {
            "matched_gold": len(matched_gold_ids),
            "gold_total": len(gold_by_id),
            "fraction": f"{len(matched_gold_ids)}/{len(gold_by_id)}",
            "decimal": round(len(matched_gold_ids) / len(gold_by_id), 4),
            "note": (
                "upper bound only: it assumes every high/medium draft is confirmed and no "
                "pending candidate matches an unmatched gold record"
            ),
        },
        "critical_coverage": {
            "critical_gold_total": len(critical_gold),
            "critical_matched": len(critical_gold & set(matched_gold_ids)),
            "critical_missing": sorted(critical_gold - set(matched_gold_ids)),
        },
        "risk_condition_coverage": {
            "total": len(risk_condition_gold),
            "matched": len(risk_condition_gold & set(matched_gold_ids)),
            "missing": sorted(risk_condition_gold - set(matched_gold_ids)),
        },
        "precision_status": {
            "value": None,
            "status": "N/A",
            "reason": (
                f"{len(pending)} candidate(s) still unresolved; contract v3 requires N/A instead "
                "of reporting a precision that excludes them"
            ),
            "threshold_reference": contract_thresholds,
        },
        "unmatched_gold": missing_gold,
        "unproduced_slots": residual["totals"],
        "unproduced_collateral_items": residual["conclusion"]["collateral_item_loss"],
        "assertions_status": {
            "count": len(contract["review_assertions"]),
            "status": "pending_human_adjudication",
            "ids": sorted(contract["review_assertions"]),
        },
        "model_requests": 0,
        "production_database_access": 0,
    }
    (HERE / "draft-preview.json").write_text(
        json.dumps(preview, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "counts": draft["counts"],
                "draft_recall_upper_bound": preview["draft_recall_upper_bound"],
                "critical_coverage": preview["critical_coverage"],
                "risk_condition_coverage": preview["risk_condition_coverage"],
                "precision_status": preview["precision_status"]["status"],
                "unmatched_gold": missing_gold,
                "files": ["adjudications.draft.json", "draft-preview.json"],
                "model_requests": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
