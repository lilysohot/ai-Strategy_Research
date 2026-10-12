"""Record U's calibration ruling (NT-I45/46/47 → 不匹配) and recompute its impact.

The worksheet was already rewritten per the ruling; this script writes the audit-trail record
and recomputes recall / high-risk coverage / the no-re-run recall ceiling.

Zero model calls, read-only on evidence inputs.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E62 = HERE.parent
CLAIMS = E62.parent.parent
REPO_ROOT = HERE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

WORK = CLAIMS / "adjudication"
SHEET = WORK / "worksheet.json"
GOLD_REF = WORK / "gold-reference.json"
GATE_V2 = (
    CLAIMS / "evidence/28-items-only-quality-gate-20261010/r0-zero-call/preregistered-gate-v2.json"
)
L9 = CLAIMS / "evidence/36-l9-redo-and-baseline-20261011/r0-zero-call/l9-redo.json"

TARGETS = ("NT-I45", "NT-I46", "NT-I47")
RULE = (
    "金标为「被转述且被质疑的预测」(perspective=quoted_other, source_stance=challenged)；"
    "候选为「材料自身陈述的预测」(source_explicit, reported)。归属与来源态度不同 ⇒ 语义不等价"
    "（契约 matching.items：须保持归属与来源态度）⇒ 不匹配。"
)


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    sheet = json.loads(SHEET.read_text(encoding="utf-8"))
    gold = {row["record_id"] for row in json.loads(GOLD_REF.read_text(encoding="utf-8"))["records"]}
    high_risk = tuple(
        json.loads(GATE_V2.read_text(encoding="utf-8"))["quality_requirements"][
            "high_risk_item_assertions_required"
        ]
    )
    l9 = json.loads(L9.read_text(encoding="utf-8"))

    matched = {
        str(row["matched_gold_id"])
        for row in sheet["records"]
        if str(row.get("judgement")) == "matched" and row.get("matched_gold_id")
    }
    unmatched = sorted(gold - matched)
    structurally = [key for key in unmatched if l9["per_record"].get(key, {}).get("corpus_absent")]
    has_candidates = [key for key in unmatched if key not in structurally]
    ceiling = len(matched) + len(has_candidates)

    changed = []
    for row in sheet["records"]:
        if str(row.get("judgement")) != "correct_extra":
            continue
        reason = str(row.get("reason") or "")
        if "校准裁定" not in reason:
            continue
        prior = next((t for t in TARGETS if t in reason), None)
        changed.append(
            {
                "candidate_id": row["candidate_id"],
                "judgement_before": "matched",
                "judgement_after": "correct_extra",
                "matched_gold_id_before": prior,
            }
        )

    record: dict[str, Any] = {
        "schema_version": "items-calibration-ruling-1",
        "created_on": "2026-10-12",
        "zero_call": True,
        "ruling": {
            "rule": RULE,
            "decided_by": "U 2026-10-12",
            "applied_to": list(TARGETS),
            "new_judgement": "correct_extra",
            "contract_ref": (
                "matching.items：须保持语义类型、话语角色、归属、否定、条件、行为意向 ⇒ "
                "归属/来源态度不同即非同一命题"
            ),
            "why_not_incorrect": (
                "候选数值与金标一致，仅归属/立场不同 ⇒ 属「正确但非本目标」= correct_extra。"
                "若 U 认为候选连归属也陈述有误，应改 incorrect（precision ≈0.995 → ≈0.982）。"
            ),
        },
        "changed_records": changed,
        "impact": {
            "matched": len(matched),
            "gold_total": len(gold),
            "recall": round(len(matched) / len(gold), 4),
            "threshold": 0.85,
            "records_needed": 41,
            "high_risk_matched": sorted(set(matched) & set(high_risk)),
            "high_risk_unmatched": sorted(set(high_risk) - matched),
            "unmatched_total": len(unmatched),
            "structurally_absent": structurally,
            "has_candidates_but_unmatched": has_candidates,
            "recall_ceiling_without_rerun": round(ceiling / len(gold), 4),
            "still_short": max(0, 41 - ceiling),
            "conclusion": (
                f"召回上限（不补跑）= {ceiling}/48 = {ceiling / len(gold):.3f} < 0.85 ⇒ "
                f"补跑仍属必要条件，至少需再恢复 {max(0, 41 - ceiling)} 条。"
            ),
        },
        "worksheet_sha256_after": sha256(SHEET),
        "in_place_edits": 1,
        "note": "本件记录 U 的校准裁定；worksheet.json 已按裁定改写（matched→correct_extra，理由写入 reason）。",
    }
    (HERE / "calibration-ruling-i45-47.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(record["impact"], ensure_ascii=False, indent=1))
    print("changed:", [(item["candidate_id"], item["matched_gold_id_before"]) for item in changed])
    return 0


if __name__ == "__main__":
    sys.exit(main())
