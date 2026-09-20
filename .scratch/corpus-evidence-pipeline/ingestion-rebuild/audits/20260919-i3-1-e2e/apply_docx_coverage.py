"""把 U 补的 DOCX/MD 的真实结果并入 i3-1-e2e-final（矩阵与结论随之更新）。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
FINAL = HERE / "i3-1-e2e-final.json"
FINAL_MD = HERE / "i3-1-e2e-final.md"
PROBE = HERE / "i3-1-e2e-format-probe.json"


def main() -> int:
    final = json.loads(FINAL.read_text(encoding="utf-8"))
    probe = json.loads(PROBE.read_text(encoding="utf-8"))
    docx_row = next(r for r in probe["pass_a"]["new_sources"] if r["path"].endswith(".docx"))
    md_row = next(r for r in probe["pass_a"]["new_sources"] if r["path"].endswith(".md"))
    docx_outcome = probe["pass_a"]["docx_check"]
    docx_publish = probe["pass_a"].get("docx_publish") or {}

    final["updated_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    final["format_probe"] = {
        "source": PROBE.name,
        "docx": {
            "path": docx_row["path"],
            "sha256": probe["inputs"]["docx"]["sha256"],
            "decision": docx_row["decision"],
            "build_id": docx_row["build_id"],
            "unit_count": 44,
            "chunk_count": 7,
            "check_exit": docx_outcome["exit_code"],
            "publishable": docx_outcome["publishable"],
            "gaps": docx_outcome["gaps"],
            "publish": docx_publish,
            "note": (
                "无人为材料类型凭证时：机器未检出与『分析师研报』冲突的类型（无检出视作审阅人认定）→ "
                "`in_scope`；DOCX 管道 **零缺口、可发布并已发布**"
            ),
        },
        "md": {
            "path": md_row["path"],
            "decision": md_row["decision"],
            "reason": "机器检出 `internal_committee_report` → order-2 `POLICY_CONFLICT` → `review_required`",
            "note": "MD（投委会报告）**格式门未过**：需 U 决定（是否认定研报=存疑 / 换料 / 接受缺格式门未过）",
        },
    }
    final["matrix"]["industry:docx"] = {"total": 1, "publishable": 1}
    final["matrix"]["company:md"] = {"total": 1, "publishable": 0}
    summary = final["summary"]
    summary["sources"] = summary["sources"] + 2
    summary["published"] = summary["published"] + 1
    summary["blocked"] = summary["blocked"] + 1
    summary["total_units"] = summary["total_units"] + 44
    summary["total_chunks"] = summary["total_chunks"] + 7
    summary["format_coverage"] = {
        "pdf": "6 份（2 可发布）",
        "docx": "1 份（U 补料；1 可发布并已发布）",
        "md": "1 份（投委会报告；review_required，格式门未过）",
    }
    final["findings"].append(
        {
            "id": "F6",
            "what": (
                "U 补的 DOCX 经真实引擎判定为 `in_scope`（材料类型无机器冲突检出 → 按审阅人认定处理），"
                "DOCX 管道零缺口、可发布并已发布；同批 MD 投委会报告被判 `review_required`"
            ),
            "effect": (
                "格式矩阵：PDF ✓、DOCX ✓（已覆盖）、MD ✗（未过门）。"
                "docx 的 schema（44 单元/7 切块）与 PDF 差异巨大（258—1518 单元），检索侧样本量偏小，"
                "I3-3 校准时须按格式分层看指标"
            ),
            "suggest": (
                "① U 追认该 DOCX 纳入开发范围（并可确认其材料类型口径）；"
                "② MD 需 U 定性：换料 / 认定 / 接受缺格式门未过（按架构 §12.1 不得静默缩范围）"
            ),
        }
    )
    final["not_concluded"] = [
        item for item in final["not_concluded"] if "docx" not in item.lower()
    ] + [
        "I3-1 未宣告完成：开发范围未追认（M1）；MD 格式门未过待 U 定性；4/6 PDF 缺口处置策略未定",
    ]
    FINAL.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    text = FINAL_MD.read_text(encoding="utf-8")
    text = text.replace(
        "> docx：开发范围无样本 → **缺格式门未过**（需 U 定性：补样本 or 声明缺格式）。",
        "> 格式覆盖（更新）：**PDF ✓（6 份）**、**DOCX ✓（U 补 1 份，已发布）**、"
        "**MD ✗（投委会报告 → `review_required`，格式门未过，需 U 定性）**。",
    )
    text = text.replace(
        "- 来源 6 份（company/industry/macro 各 2，PDF）",
        "- 来源 8 份（company/industry/macro 各 2 份 PDF + U 补 DOCX 1 份 + MD 投委会报告 1 份）",
    )
    text = text.replace(
        "**可发布 2 / 阻断 4**",
        "**可发布 3（2 PDF + 1 DOCX）/ 阻断 5（4 PDF 缺口 + 1 MD 未过门）**",
    )
    lines = text.rstrip().split("\n")
    lines += [
        "",
        "## 八、U 补 DOCX 的真实结果（格式覆盖探针）",
        "",
        f"- DOCX `{Path(docx_row['path']).name}`（sha256 {probe['inputs']['docx']['sha256'][:12]}）："
        f"decision=**{docx_row['decision']}**，44 单元 / 7 切块，"
        f"**check exit {docx_outcome['exit_code']}、缺口 0、可发布**，"
        f"publish {json.dumps(docx_publish, ensure_ascii=False)}",
        "- MD `仕佳光子_投委会决策报告_20260831.md`：decision=**review_required**"
        "（机器检出 `internal_committee_report` → `POLICY_CONFLICT`）→ **格式门未过**",
        "- 沙箱审计计数：" + json.dumps((probe.get("sandbox_audit") or {}).get("counts"), ensure_ascii=False)
        + "；冲突 " + json.dumps((probe.get("sandbox_audit") or {}).get("conflicts"), ensure_ascii=False),
    ]
    FINAL_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"matrix": final["matrix"], "summary_published": summary["published"],
                      "format_coverage": summary["format_coverage"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
