"""Where the round-3 candidate set stands against the signed gate — read-only, zero model calls.

The question this answers is narrow and decides the next action: **can the two remaining gate
blockers be cleared by re-judging rows that are already in the pool?**

Method (no gold is ever copied into a candidate; nothing is judged here):

1. read the U-authored candidate set, drop rows that already carry a gold;
2. for each gold the set does not cover, rank the remaining candidates by surface similarity of
   their proposition text to the gold's own text (quote + proposition);
3. report the best few per gold. If the best similarity is low across the board, no in-set
   re-judgement can manufacture a true mapping -- the coverage gap is on the *extraction* side.

Counting predicates are declared in the output (``predicates``) because the gate mixes two
different readings of "accepted" and only one of them is implemented by the scorer.

Writes only its own output; refuses to overwrite (``--force`` to re-run deliberately).
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.evidence_guard import write_once  # noqa: E402

CANDIDATE_SET = HERE / "items-reextract-adjudication-r3/candidate-adjudications.worksheet.json"
SCOREABLE_COPY = (
    HERE / "items-reextract-adjudication-r3-blank/candidate-adjudications.worksheet.json"
)
GOLD = ROOT / "evidence/33-items-quality-scoring-20261011/r0-zero-call/adjudications.json"
GATE_V3 = ROOT / "evidence/75-r2-signed-20261013/r0-zero-call/gate-v3.json"

SOURCE_LABEL = {
    "sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb": "industrial-fulian-md",
    "sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f": "optical-module-docx",
}
TOP_N = 3


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gold_text(record: dict) -> str:
    return f"{record.get('quote') or ''} {record.get('proposition') or ''}".strip()


def candidate_text(row: dict) -> str:
    fields = row.get("canonical_observed_fields") or {}
    return str(fields.get("proposition") or (row.get("original_candidate") or {}).get("text") or "")


def build() -> dict:
    worksheet = json.loads(SCOREABLE_COPY.read_text(encoding="utf-8"))
    authored = json.loads(CANDIDATE_SET.read_text(encoding="utf-8"))
    rows = worksheet["adjudications"]
    gold = json.loads(GOLD.read_text(encoding="utf-8"))["gold_reference"]
    sentinels = json.loads(GATE_V3.read_text(encoding="utf-8"))["quality_requirements"][
        "high_risk_item_assertions_required"
    ]

    matched = {r["matched_gold_id"] for r in rows if r.get("matched_gold_id")}
    unmatched_rows = [r for r in rows if not r.get("matched_gold_id")]
    uncovered = [g["record_id"] for g in gold if g["record_id"] not in matched]

    per_source: dict[str, dict[str, int]] = {}
    for source_id, label in SOURCE_LABEL.items():
        cands = [r for r in rows if r["source_id"] == source_id]
        golds = [g for g in gold if g["source_id"] == source_id]
        hits = sum(1 for g in golds if g["record_id"] in matched)
        per_source[label] = {
            "candidates": len(cands),
            "gold": len(golds),
            "matched": hits,
            "correct_extra": sum(1 for r in cands if r["judgement"] == "correct_extra"),
            "duplicate": sum(1 for r in cands if r["judgement"] == "duplicate"),
        }

    gaps = []
    for record_id in uncovered:
        record = next(g for g in gold if g["record_id"] == record_id)
        target = gold_text(record)
        ranked = sorted(
            (
                (
                    round(
                        difflib.SequenceMatcher(None, target, candidate_text(row)).ratio(),
                        3,
                    ),
                    row,
                )
                for row in unmatched_rows
            ),
            key=lambda pair: -pair[0],
        )[:TOP_N]
        gaps.append(
            {
                "gold_record_id": record_id,
                "source": SOURCE_LABEL.get(record["source_id"], record["source_id"]),
                "sentinel": record_id in sentinels,
                "critical": bool(record.get("critical")),
                "risk_or_condition": bool(record.get("risk_or_condition")),
                "gold_text": target[:120],
                "closest_unmatched_candidates": [
                    {
                        "candidate_id": row["candidate_id"],
                        "run": row["run"],
                        "similarity": score,
                        "proposition": candidate_text(row)[:80],
                    }
                    for score, row in ranked
                ],
                "best_similarity": ranked[0][0] if ranked else 0.0,
            }
        )

    judgements = Counter(r["judgement"] for r in rows)
    total = len(rows)
    accepted_matched = judgements["matched"]
    return {
        "schema_version": "items-p4-remaining-gap-analysis-1",
        "id": "109-p4-remaining-gaps",
        "created_on": "2026-10-15",
        "model_calls": 0,
        "production_pg_writes": 0,
        "status": "read_only_analysis_pending_u_decision",
        "predicates": {
            "accepted_records_per_source (scorer implementation)": (
                "per-source matched count; plugins/corpus/structured_scoring.py:1218 compares "
                "source_matched to accepted_records_per_source_min"
            ),
            "accepted (72-号 verdict-level reading, NOT what the scorer uses)": (
                "matched + correct_extra per source"
            ),
            "uncovered gold": "frozen gold record with no row whose matched_gold_id equals it",
            "in-set repair": "any row already in this pool being re-judged to matched",
        },
        "inputs": {
            "candidate_set_u_authored": {
                "path": str(CANDIDATE_SET.relative_to(ROOT)),
                "sha256": sha256(CANDIDATE_SET),
            },
            "scoreable_copy": {
                "path": str(SCOREABLE_COPY.relative_to(ROOT)),
                "sha256": sha256(SCOREABLE_COPY),
            },
            "frozen_gold_items": {
                "path": str(GOLD.relative_to(ROOT)),
                "sha256": sha256(GOLD),
                "records": len(gold),
            },
            "signed_gate_v3": {"path": str(GATE_V3.relative_to(ROOT)), "sha256": sha256(GATE_V3)},
        },
        "candidate_set": {
            "rows": total,
            "judgements": dict(judgements),
            "reviewer": sorted({r["reviewer"] for r in rows}),
            "adjudicator": sorted({r["adjudicator"] for r in rows}),
            "review_status": sorted({r["review_status"] for r in rows}),
            "rows_matching_authored_set_bytewise": (
                sha256(CANDIDATE_SET) == sha256(SCOREABLE_COPY)
            ),
            "authored_row_count": len(authored["adjudications"]),
            "gold_nulled_rows": sum(
                1
                for a, b in zip(authored["adjudications"], rows, strict=False)
                if a.get("matched_gold_id") != b.get("matched_gold_id")
            ),
        },
        "per_source": per_source,
        "rate_readings": {
            "precision": f"{accepted_matched + judgements['correct_extra']}/{total}",
            "recall": f"{len(matched)}/{len(gold)}",
            "unresolved": 0,
            "sentinels_matched": [s for s in sentinels if s in matched],
            "sentinels_unmatched": [s for s in sentinels if s not in matched],
            "accepted_records_total_min_reading": {
                "scorer-matched": accepted_matched,
                "matched+correct_extra": accepted_matched + judgements["correct_extra"],
            },
        },
        "gate_blockers_under_scorer_predicate": [
            {
                "criterion": "accepted_records_per_source_min",
                "measured": f"{per_source['industrial-fulian-md']['matched']} (md)",
                "threshold": 20,
                "verdict": "FAIL",
                "note": "md 金标 22；分源召回 18/22 本身 ≥0.80，卡的是条数下限",
            },
            {
                "criterion": "high_risk_item_assertions_required",
                "measured": f"{len([s for s in sentinels if s in matched])}/{len(sentinels)}",
                "threshold": f"{len(sentinels)}/{len(sentinels)}",
                "verdict": "FAIL",
                "unmatched": [s for s in sentinels if s not in matched],
            },
        ],
        "gaps": gaps,
        "in_set_repair_possible": False,
        "in_set_repair_evidence": (
            "7 uncovered golds, best unmatched-candidate similarity "
            f"{min(g['best_similarity'] for g in gaps)}–{max(g['best_similarity'] for g in gaps)}; "
            "no row carries the assertion, so no re-judgement can map it truthfully"
        ),
        "c1_pending_coverage": {
            "rows": len(worksheet.get("c1_pending_coverage") or []),
            "with_disposition": sum(
                1
                for row in worksheet.get("c1_pending_coverage") or []
                if row.get("disposition") or row.get("covered_by_candidate_id")
            ),
            "suggestions": {
                "path": str(
                    (HERE / "items-reextract-adjudication-r3/c1-suggestions.json").relative_to(ROOT)
                ),
                "sha256": sha256(HERE / "items-reextract-adjudication-r3/c1-suggestions.json"),
                "suggestion_only": True,
            },
        },
        "untouched": [
            "候选集与可出分副本字节未改（本脚本只读）",
            "冻结金标、已签门 v3、契约、prereg v2、freeze、MANIFEST 均未动",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "p4-remaining-gap-analysis.json")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    payload = build()
    write_once(
        args.out,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        reason="109 号剩余缺口分析",
        allow_overwrite=args.force,
    )
    print(f"wrote {args.out}")
    print(json.dumps(payload["rate_readings"], ensure_ascii=False, indent=2))
    print(json.dumps(payload["gate_blockers_under_scorer_predicate"], ensure_ascii=False, indent=2))
    print("in_set_repair_possible:", payload["in_set_repair_possible"])
    for gap in payload["gaps"]:
        print(
            f"  {gap['gold_record_id']:8} best={gap['best_similarity']:.3f} sentinel={gap['sentinel']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
