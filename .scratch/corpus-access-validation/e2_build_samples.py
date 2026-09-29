"""E2 · 生成 samples.jsonl：开发集 30 题金标映射 + 留出集 12 篇骨架。

零模型、只读。开发集条目自 query-gold-scoring-v1.jsonl 映射为 protocol §2 字段
（补 doc_identity / acceptable_evidence / required_dependencies）；
留出集条目为骨架（status=needs_source_page_review），题干与目标由评分侧在
源页核查阶段建立，执行侧不可读。
产物：samples.jsonl（本目录）
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
GOLD = REPO / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/query-gold-scoring-v1.jsonl"
INVENTORY = HERE / "e2-inventory.json"
OUT = HERE / "samples.jsonl"

# 留出集首批 12 篇（2026-09-29 用户确认范围：高盛 3738c927 图片型已剔除、兴业极致轮动归宏观）
HOLDOUT_SELECTED = {
    "c195233b": "company  国信·贵州茅台中报点评（同主体跨机构对照，注意与开发集 6f14cc14 区分）",
    "f0e67b73": "company  国泰海通·新股精要贝特利",
    "c1ddcd8a": "industry  光大·金属周期品高频周报",
    "b7e932c8": "industry  中信建投·行业数据周报",
    "0c25f0e9": "industry  国泰海通·机器人行业周报",
    "f86c6d2c": "industry  国联民生·医药行业周报",
    "a91d95c7": "industry  国金·通信行业研究（HBM）",
    "5e305376": "macro  华泰·宏观海外周报",
    "f7f65d7e": "macro  天风·A股策略周报",
    "d179b615": "macro  中银国际·策略周报",
    "2f8aa709": "macro  国金·A股策略周报",
    "f3b28791": "macro  兴业·极致轮动如何收敛（用户确认归宏观）",
}


def main() -> None:
    inv = json.loads(INVENTORY.read_text(encoding="utf-8"))
    sha_by_short = {e["sha256_8"]: e["sha256"] for e in inv["entries"]}

    samples: list[dict] = []
    with GOLD.open(encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            targets = []
            for role_key, role in (("evidence_targets", "required"), ("supplementary_evidence_targets", "supplementary")):
                for t in g.get(role_key, []):
                    c = t.get("constraints", {}) or {}
                    targets.append({
                        "target_id": t["target_id"],
                        "doc_identity": sha_by_short.get(t["source_id"].split("_", 1)[1], t["source_id"]),
                        "source_ref": t.get("locator"),
                        "verbatim_quote": t.get("quote"),
                        "row": c.get("row"), "col": c.get("col"), "cell": c.get("cell"),
                        "period": c.get("period"), "unit": c.get("unit"),
                        "role": role,
                    })
            samples.append({
                "sample_id": g["query_id"],
                "split": "dev",
                "domain": g["domain"],
                "query_kind": g.get("query_kind"),
                "critical": g.get("critical"),
                "satisfy_rule": g.get("satisfy_rule"),
                "question": g["question"],
                "evidence_requirement": g.get("evidence_requirement"),
                "targets": targets,
                "required_dependencies": [],  # unit/period 内嵌 constraints；独立依赖目标于源页复核时枚举
                "relevant_sources": g.get("relevant_sources"),
                "provenance": "query-gold-scoring-v1.jsonl（真人复核 xyl）",
            })

    by_short = {e["sha256_8"]: e for e in inv["entries"]}
    n_holdout = 0
    for short, desc in HOLDOUT_SELECTED.items():
        e = by_short[short]
        n_holdout += 1
        samples.append({
            "sample_id": f"holdout-{e['report_type']}-{n_holdout:03d}",
            "split": "holdout",
            "domain": e["report_type"],
            "doc_identity": e["sha256"],
            "file": e["file"],
            "author": e["author"],
            "selection_note": desc,
            "status": "needs_source_page_review",
            "question": None,
            "targets": [],
            "required_dependencies": [],
            "provenance": "E2 人工挑选（e2-inventory.json，排除记录见覆盖矩阵）",
        })

    OUT.write_text(
        "\n".join(json.dumps(s, ensure_ascii=False) for s in samples) + "\n",
        encoding="utf-8",
    )
    dev = sum(1 for s in samples if s["split"] == "dev")
    print(f"samples={len(samples)} dev={dev} holdout_skeleton={n_holdout}")


if __name__ == "__main__":
    main()