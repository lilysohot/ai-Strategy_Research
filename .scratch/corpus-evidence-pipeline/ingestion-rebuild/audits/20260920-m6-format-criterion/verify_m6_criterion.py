"""M6 判据「格式门」口径一致性只读校验（i0c-r35）。

背景：`tasks.md` 的 M6 判据行原无「格式」字样，而架构 §12.1 与 I3-7 行都含格式规则 → 完成口径不一致。
本脚本只读核验三处口径是否已对齐，并确认台账导航/节锚点齐备；**不写任何文件**（默认即只读，
`--no-write` 仅为符合「校验类脚本必须支持 --no-write」的调用约定）。

用法::

    uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/\
20260920-m6-format-criterion/verify_m6_criterion.py [--no-write]

退出码：0 = 全部一致；1 = 有缺口（逐条打印）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
TASKS = ROOT / "docs/plan/corpus-ingestion-rebuild-tasks.md"
PLAN = ROOT / "docs/plan/claims-market-closed-loop-plan.md"
ARCH = ROOT / "docs/plan/corpus-ingestion-rebuild-architecture.md"

#: M6 判据行必须显式声明的格式门要素（与 §12.1 / I3-7 口径对齐）
M6_REQUIRED = ("§12.1", "格式", "PDF/DOCX/MD", "dev_lane")
#: 里程碑表 M6 行的前缀（注意 M6 后是两个空格，区别于导航表「| M6 判据补齐格式门 |」）
M6_ROW_PREFIX = "| M6  |"


def row_of(text: str, prefix: str) -> str:
    """取表格中以 ``prefix`` 开头的那一行（如 ``| M6  ``）。"""

    for line in text.splitlines():
        if line.startswith(prefix):
            return line
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="M6 判据格式门口径一致性校验（只读）")
    parser.add_argument("--no-write", action="store_true", help="显式声明只读（默认即只读）")
    parser.parse_args()

    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"item": name, "status": "pass" if ok else "fail", "detail": detail})

    tasks_text = TASKS.read_text(encoding="utf-8")
    plan_text = PLAN.read_text(encoding="utf-8")
    arch_text = ARCH.read_text(encoding="utf-8")

    m6_row = row_of(tasks_text, M6_ROW_PREFIX)
    missing = [token for token in M6_REQUIRED if token not in m6_row]
    check(
        "M6 判据行写入 §12.1 格式门",
        bool(m6_row) and not missing,
        f"缺失要素={missing}；行首={m6_row[:40]!r}",
    )

    i3_7_row = row_of(tasks_text, "| I3-7 ")
    check("I3-7 行仍含格式要求（口径同源）", "格式" in i3_7_row, f"行首={i3_7_row[:40]!r}")

    check(
        "架构 §12.1 格式可得性对账条款在位",
        "格式可得性对账" in arch_text and "format_availability" in arch_text,
        "需同时含『格式可得性对账』与 `format_availability`",
    )
    check(
        "架构 §12.1 禁止静默缩范围条款在位",
        "不能静默缩范围" in arch_text,
        "缺格式样本须显式处置（补料工单 / U 改声称）",
    )
    check(
        "台账含 m6-format-criterion 节",
        'id="m6-format-criterion"' in plan_text,
        "反查链接目标必须存在",
    )
    check(
        "导航表含指向该节的条目",
        "#m6-format-criterion" in tasks_text,
        "tasks.md 导航表需可追",
    )
    check(
        "M6 判据未引入与代码不一致的行为变更描述",
        "格式门" in m6_row or "§12.1" in m6_row,
        "只应改判据文字，不得声称新增/关闭任何门",
    )

    failed = [item for item in checks if item["status"] == "fail"]
    report = {
        "artifact": "m6-format-criterion-consistency",
        "verdict": "PASS" if not failed else "FAIL",
        "checks": checks,
        "failed_items": [item["item"] for item in failed],
        "note": "只读校验；格式门的实际执行仍在架构 §12.1 / dev-manifest.format_availability / preflight_scope_check.py。",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
