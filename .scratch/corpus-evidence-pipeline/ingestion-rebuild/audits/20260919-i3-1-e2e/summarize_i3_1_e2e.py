"""汇总 I3-1 E2E 两阶段结果 → i3-1-e2e-final.{json,md}（含领域×格式矩阵、阻断缺口清单、findings）。"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
FIRST = HERE / "i3-1-e2e-record.json"
SOURCES = HERE / "i3-1-e2e-sources.json"
MANIFEST = HERE / "dev-scope-manifest.json"
FINAL = HERE / "i3-1-e2e-final.json"
FINAL_MD = HERE / "i3-1-e2e-final.md"
GUARD = BASE / "guards/i3-e2e.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    first = json.loads(FIRST.read_text(encoding="utf-8"))
    per_source = json.loads(SOURCES.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    domain_of = {Path(entry["path"]).name: entry["domain_hint"] for entry in manifest["sources"]}

    rows = []
    for row in per_source["sources"]:
        blocking = [
            gap for gap in row["check"]["gaps"] if gap.get("disposition") not in ("acknowledged",)
        ]
        rows.append(
            {
                "domain": domain_of.get(row["original_name"], "?"),
                "format": row["format"],
                "original_name": row["original_name"],
                "build_id": row["build_id"],
                "unit_count": row["unit_count"],
                "chunk_count": row["chunk_count"],
                "check_exit": row["check"]["exit_code"],
                "publishable": bool(row["check"]["publishable"]),
                "publish_exit": row["publish"]["exit_code"],
                "generation": row["publish"].get("generation"),
                "blocking_gaps": [
                    {"code": g["code"], "status": g["status"], "disposition": g["disposition"],
                     "key": g["key"], "remedy": g.get("remedy")}
                    for g in blocking
                ],
                "acknowledged_gaps": sum(
                    1 for g in row["check"]["gaps"] if g.get("disposition") == "acknowledged"
                ),
            }
        )
    rows.sort(key=lambda r: (r["domain"], r["format"], r["original_name"]))

    blocking_inventory = Counter(
        (g["code"], g["status"], g["disposition"]) for r in rows for g in r["blocking_gaps"]
    )
    matrix = {}
    for row in rows:
        cell = matrix.setdefault(f"{row['domain']}:{row['format']}", {"total": 0, "publishable": 0})
        cell["total"] += 1
        cell["publishable"] += int(row["publishable"])

    searches = per_source["search"]
    verify_rows = [v for item in searches for v in item["verified"]]
    final = {
        "artifact": "i3-1-e2e-final",
        "phase": "i3-1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "target": per_source["target"],
        "guard": {"path": str(GUARD.relative_to(ROOT)), "sha256": digest(GUARD)},
        "scope_status": "proposed_pending_ratification",
        "executed_for_real": {
            "pipeline": "登记(ReviewedDecision)→准入→解析→清洗→切块→build→check→publish→status",
            "read_path": "search→fetch_verbatim→(coverage / 同快照组合读取 / 审计)",
            "pg": "隔离沙箱 i2_sandbox_corpus（corpus-db 容器；实例无 apodex=非生产）",
            "model_calls": 0,
            "synthetic_scores_reused": False,
        },
        "summary": {
            "sources": len(rows),
            "published": sum(1 for r in rows if r["publish_exit"] == 0),
            "blocked": sum(1 for r in rows if r["publish_exit"] != 0),
            "total_units": sum(r["unit_count"] or 0 for r in rows),
            "total_chunks": sum(r["chunk_count"] or 0 for r in rows),
            "search_hits": {item["query"]: item["hits"] for item in searches},
            "verify_checks_passed": all(
                v["active"] and v["chunk_text_is_unit_join"] and v["units_in_document_text"]
                for v in verify_rows
            ),
            "verify_rows": len(verify_rows),
            "audit_conflicts": per_source["audit"].get("conflicts"),
            "coverage_processing": (per_source.get("coverage") or {}).get("processing"),
            "coverage_query_status": (per_source.get("coverage") or {}).get("query_status"),
        },
        "matrix": matrix,
        "sources": rows,
        "blocking_gap_inventory": [
            {"code": code, "status": status, "disposition": disposition, "count": count}
            for (code, status, disposition), count in blocking_inventory.most_common()
        ],
        "read_path_verification": {
            "basis": (
                "PDF 正文由 PyMuPDF 解析而来：**字节级逐字不适用**；核验口径为"
                "『chunk 文本 == 所引单元原文的换行拼接』且『每个单元原文 ⊆ 该文档解析文本』，"
                "并核对句柄 active 与页号范围"
            ),
            "hits": [
                {
                    "query": item["query"], "hits": item["hits"],
                    "verified": [
                        {"locator": v["locator"], "units": v["units"], "active": v["active"],
                         "join_ok": v["chunk_text_is_unit_join"],
                         "units_in_doc": v["units_in_document_text"]}
                        for v in item["verified"]
                    ],
                }
                for item in searches
            ],
        },
        "findings": [
            *per_source["findings"],
            {
                "id": "F4",
                "what": (
                    "真实开发样本的缺口分布：4/6 份券商研报被门阻断，代码为 "
                    "`image_region_unreadable`（status=needs_ocr）与 `table_lines_without_extraction`"
                    "（status=review_required）"
                ),
                "effect": (
                    "隔离库内 6 份来源 build 全成功（4305 单元 / 767 切块），但只有 2 份可发布；"
                    "阻断项全部由 §7.3 机读分级给出，处置路径 = 补 OCR（图像区域）/ 换料或转 review_required"
                    "（表格线未抽取）"
                ),
                "suggest": "U 定缺口处置策略（补 OCR / 换料 / 接受为 review_required 并在范围上排除）；本轮不擅自降级门",
            },
            {
                "id": "F5",
                "what": "台账（docs/plan 两份）在本轮未更新",
                "effect": "两份台账属 r31 绑定件，改动需新修订；I3-1 尚未冻结，故本轮只在审计目录留真实记录",
                "suggest": "I3-1 首个冻结修订（范围获批后）一并回填台账",
            },
        ],
        "not_concluded": [
            "I3-1 未宣告完成：开发范围未追认（M1），且 4/6 来源缺口处置策略未定",
            "未做 I3-3（检索/切块参数校准）、I3-4（coverage 开发测试）、I3-5（非回归）；结果不得直接放行 I4",
        ],
        "artifacts": {
            "stage1": FIRST.name,
            "stage2": SOURCES.name,
            "manifest": MANIFEST.name,
            "final": FINAL.name,
        },
    }
    FINAL.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# I3-1 三类开发 E2E —— 真实执行结果（隔离沙箱）",
        "",
        f"- 生成：{final['generated_at']}；目标 `{final['target']['dsn']}`；守卫 `{final['guard']['path']}`"
        f"（sha256 {final['guard']['sha256'][:12]}）",
        f"- **范围状态：{final['scope_status']}** —— 全部来源在 dev-manifest 中仍为 `review_required`（M1 未决），"
        "本轮按 Agent 提案 3 类×2 份执行，登记决定作者写明『待 U 追认』",
        f"- 真实执行：0 次模型调用；**未复用任何合成分数**；写入仅限隔离库 `{final['target']['database']}`",
        "",
        "## 一、总览",
        "",
        f"- 来源 {final['summary']['sources']} 份（company/industry/macro 各 2，PDF）；"
        f"**可发布 {final['summary']['published']} / 阻断 {final['summary']['blocked']}**",
        f"- 规模：{final['summary']['total_units']} 单元 / {final['summary']['total_chunks']} 切块",
        f"- 检索命中：{json.dumps(final['summary']['search_hits'], ensure_ascii=False)}"
        f"（命中取证核验 {final['summary']['verify_rows']} 条，全部通过="
        f"{final['summary']['verify_checks_passed']}）",
        f"- coverage：processing={final['summary']['coverage_processing']}，"
        f"query_status={final['summary']['coverage_query_status']}；审计冲突："
        f"{final['summary']['audit_conflicts']}",
        "",
        "## 二、逐来源门（真实）",
        "",
        "| 领域 | 格式 | 来源 | 单元/切块 | check | publish | 阻断缺口 |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        codes = "；".join(f"{g['code']}({g['status']})@{g['key'].rsplit(':', 1)[-1]}" for g in row["blocking_gaps"])
        lines.append(
            f"| {row['domain']} | {row['format']} | {row['original_name'][:36]} | "
            f"{row['unit_count']}/{row['chunk_count']} | {row['check_exit']} | "
            f"{row['publish_exit']}{'（gen ' + str(row['generation']) + '）' if row['generation'] else ''} | "
            f"{codes or '无'} |"
        )
    lines += [
        "",
        "## 三、领域×格式矩阵",
        "",
        "| 单元格 | 份数 | 可发布 |",
        "|---|---|---|",
    ]
    for cell, info in sorted(matrix.items()):
        lines.append(f"| {cell} | {info['total']} | {info['publishable']} |")
    lines += [
        "",
        "> docx：开发范围无样本 → **缺格式门未过**（需 U 定性：补样本 or 声明缺格式）。",
        "",
        "## 四、阻断缺口清单（§7.3 机读分级）",
        "",
        "| 代码 | status | disposition | 条数 |",
        "|---|---|---|---|",
    ]
    for item in final["blocking_gap_inventory"]:
        lines.append(
            f"| {item['code']} | {item['status']} | {item['disposition']} | {item['count']} |"
        )
    lines += [
        "",
        "处置路径（§7.3）：`image_region_unreadable` → 补 OCR；`table_lines_without_extraction` → "
        "换料 / 转 `review_required`。**本轮未擅自降级门**。",
        "",
        "## 五、读侧核验（search → fetch → verify）",
        "",
        f"- 口径：{final['read_path_verification']['basis']}",
        "",
        "| 查询 | 命中 | 取证核验 |",
        "|---|---|---|",
    ]
    for item in final["read_path_verification"]["hits"]:
        ok = all(v["active"] and v["join_ok"] and v["units_in_doc"] for v in item["verified"])
        lines.append(f"| {item['query']} | {item['hits']} | {'全部通过' if item['verified'] and ok else '—' if not item['hits'] else '有问题'} |")
    lines += ["", "## 六、Findings", ""]
    for finding in final["findings"]:
        lines.append(f"- **{finding['id']}** {finding['what']}")
        lines.append(f"  - 影响：{finding['effect']}")
        lines.append(f"  - 建议：{finding['suggest']}")
    lines += ["", "## 七、未作结论（边界）", ""]
    lines += [f"- {item}" for item in final["not_concluded"]]
    lines += ["", f"- 产物：{json.dumps(final['artifacts'], ensure_ascii=False)}", ""]
    FINAL_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "final": FINAL.name,
        "published": final["summary"]["published"],
        "blocked": final["summary"]["blocked"],
        "matrix": matrix,
        "blocking_inventory": final["blocking_gap_inventory"],
        "verify_ok": final["summary"]["verify_checks_passed"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
