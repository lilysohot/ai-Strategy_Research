"""C1 29 条 —— 供 U 具名裁定的逐条清单（零调用，只读）。

为什么会有这件：`p4-c1-disposition.json` 的处置是按一个**我自己定的** 0.55 字面相似度阈值出的，
而冻结预注册 v2 的 C1 条款只有一句话——「有对应新池候选者入裁定、无对应者记 no_candidate」，
**没有任何阈值**。阈值把"筛"当成了"判"，须由 U 按「语义相同」重新裁。本件把两侧原文全列，
并把最像的前 3 条候选一并给出（含其裁定与金标），使裁定可以只看字面完成。

不产出新的处置结论：`ruling` 一律留空，等 U 具名。

Usage:
    python build_c1_review_listing.py [--no-write] [--force]
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.evidence_guard import write_once  # noqa: E402

CREATED_ON = "2026-10-15"
TOP_N = 3

CANDIDATE_SET = HERE / "items-reextract-adjudication-r3/candidate-adjudications.worksheet.json"
PREREG_V2 = HERE / "items-reextraction-preregistration-v2.json"
DISPOSITION_V1 = HERE / "p4-c1-disposition.json"
OUT = HERE / "p4-c1-review-listing.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def build() -> dict:
    worksheet = json.loads(CANDIDATE_SET.read_text(encoding="utf-8"))
    prereg = json.loads(PREREG_V2.read_text(encoding="utf-8"))
    binding = prereg["adjudication_clause"]["c1_pending_coverage"]
    registration = json.loads((REPO_ROOT / binding["source"]).read_text(encoding="utf-8"))
    entries = [
        entry
        for entry in registration["entries"]
        if entry.get("owner_role") == "material_items"
        and entry.get("status") == "pending_coverage"
    ]
    if len(entries) != binding["count"]:
        raise SystemExit(f"C1 count drift: {len(entries)} != {binding['count']}")
    previous = {
        row["c1_candidate_id"]: row
        for row in json.loads(DISPOSITION_V1.read_text(encoding="utf-8"))["dispositions"]
    }

    pool = [
        {
            "candidate_id": row["candidate_id"],
            "text": str((row.get("original_candidate") or {}).get("text") or ""),
            "run": row["run"],
            "judgement": row["judgement"],
            "matched_gold_id": row.get("matched_gold_id"),
        }
        for row in worksheet["adjudications"]
    ]

    rows = []
    for index, entry in enumerate(entries, start=1):
        target = norm(entry["claim_text"])
        ranked = sorted(
            (
                (round(difflib.SequenceMatcher(None, target, norm(item["text"])).ratio(), 3), item)
                for item in pool
            ),
            key=lambda pair: -pair[0],
        )[:TOP_N]
        rows.append(
            {
                "serial": index,
                "c1_candidate_id": entry["candidate_id"],
                "claim_text": entry["claim_text"],
                "source_id": entry.get("source_id"),
                "role_external_reason": entry.get("role_external_reason"),
                "machine_disposition_v1": previous[entry["candidate_id"]]["disposition"],
                "machine_review_flag_v1": previous[entry["candidate_id"]]["review_flag"],
                "closest_pool_candidates": [
                    {
                        "candidate_id": item["candidate_id"],
                        "text": item["text"],
                        "run": item["run"],
                        "judgement": item["judgement"],
                        "matched_gold_id": item["matched_gold_id"],
                        "similarity": score,
                    }
                    for score, item in ranked
                ],
                "ruling": None,
                "ruled_by": None,
                "ruled_on": None,
            }
        )

    return {
        "schema_version": "items-c1-review-listing-1",
        "id": "109-p4-c1-review-listing",
        "created_on": CREATED_ON,
        "model_calls": 0,
        "status": "for_named_human_ruling",
        "why_this_exists": (
            "处置 v1 按 assistant 自定的 0.55 字面相似度阈值出结论；冻结预注册 v2 的 C1 条款"
            "只有『有对应新池候选者入裁定、无对应者记 no_candidate』一句，没有任何阈值。"
            "阈值无签署权威，须按『语义相同』由 U 重裁。"
        ),
        "ruling_rule": {
            "ask": "逐条回答：池内是否有候选在讲同一件事（语义相同即算，不看字面相似度）",
            "allowed": ["covered_by_candidate", "no_candidate"],
            "covered_by_candidate": "填是哪一个候选；若字面最像的那条其实不是同一件事，可指名其它 candidate_id",
            "no_candidate": "全池确实无对应 ⇒ 该内容跨角色仍无人覆盖 ⇒ 进发布件的显式缺口清单",
        },
        "basis": {
            "prereg_v2": {"path": str(PREREG_V2.relative_to(ROOT)), "sha256": sha256(PREREG_V2)},
            "candidate_set": {
                "path": str(CANDIDATE_SET.relative_to(ROOT)),
                "sha256": sha256(CANDIDATE_SET),
            },
            "disposition_v1": {
                "path": str(DISPOSITION_V1.relative_to(ROOT)),
                "sha256": sha256(DISPOSITION_V1),
                "role": "被本件取代的读法（threshold 0.55）；旧件字节保留",
            },
            "registration": {"path": binding["source"], "sha256": sha256(REPO_ROOT / binding["source"])},
        },
        "caveat_for_reviewer": (
            "本件只给两侧原文与最像候选，不给结论方向：candidate 的 judgement/matched_gold_id 是"
            "评分侧事实，可用于判断该候选承载了什么，但不等于该候选与 C1 文本语义相同"
        ),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    payload = build()
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.no_write:
        print(text)
        return 0
    write_once(OUT, text, reason="C1 29 条裁定清单", allow_overwrite=args.force)
    print(f"wrote {OUT.name}")
    pending = [row for row in payload["rows"] if row["machine_disposition_v1"] == "no_candidate"]
    print(f"rows={len(payload['rows'])} 曾被判 no_candidate 的 {len(pending)} 条需重裁")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
