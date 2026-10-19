"""Generate the human review checklist for failed S5 matrix questions."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs/data_clean_dos/v14-s5-full-matrix-report.json"
GOLD = ROOT / ".scratch/corpus-access-validation/e2_holdout_targets.json"
OUT_MD = ROOT / "docs/data_clean_dos/v14-s5-failed-question-review.md"
OUT_CSV = ROOT / "docs/data_clean_dos/v14-s5-failed-sessions.csv"


def load_gold() -> dict[str, dict[str, Any]]:
    documents = json.loads(GOLD.read_text(encoding="utf-8"))
    targets: dict[str, dict[str, Any]] = {}
    for document in documents:
        for target in document["targets"]:
            targets[target["target_id"]] = {
                **target,
                "file": document["file"],
                "domain": document["domain"],
            }
    return targets


def result_path(row: dict[str, Any]) -> Path:
    return (
        ROOT
        / ".s5runs_v14_full"
        / row["arm"]
        / row["target_id"]
        / f"run-{int(row['repeat']):02d}"
        / "result.json"
    )


def rel_link(path: Path) -> str:
    return "../../" + path.relative_to(ROOT).as_posix()


def verdict_cell(row: dict[str, Any]) -> str:
    verdict = (row.get("judge") or {}).get("verdict", "missing")
    label = "✅ pass" if verdict == "pass" else "❌ fail"
    return f"[{label}]({rel_link(result_path(row))})"


def severity(fail_count: int) -> str:
    if fail_count == 4:
        return "持续失败 4/4"
    if fail_count == 3:
        return "高频失败 3/4"
    return "偶发失败 1/4"


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    gold = load_gold()
    by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in report["per_run"]:
        by_target[row["target_id"]].append(row)

    failed_ids = {
        row["target_id"]
        for row in report["per_run"]
        if (row.get("judge") or {}).get("verdict") == "fail"
    }
    ordered_ids = sorted(
        failed_ids,
        key=lambda target_id: (
            -sum(
                (row.get("judge") or {}).get("verdict") == "fail"
                for row in by_target[target_id]
            ),
            target_id,
        ),
    )

    lines = [
        "# V14 S5 全量矩阵失败题目人工复核清单",
        "",
        f"- 矩阵：{report['scope']['runs']}/{report['scope']['expected_runs']} 次会话",
        "- 失败会话：42",
        f"- 涉及题目：{len(ordered_ids)}",
        "- 冻结 holdout：保持不变；本清单只读取结果和参考证据。",
        "- 判定列可点击打开对应会话的 `result.json`，查看完整回答与 Judge 输出。",
        "",
        "## 总览",
        "",
        "| # | 稳定性 | target_id | 领域/证据角色 | Control | Candidate R1 | Candidate R2 | Candidate R3 |",
        "|---:|---|---|---|---|---|---|---|",
    ]

    grouped: list[tuple[str, dict[str, Any], list[dict[str, Any]]]] = []
    for index, target_id in enumerate(ordered_ids, start=1):
        rows = by_target[target_id]
        target = gold[target_id]
        control = next(row for row in rows if row["arm"] == "control")
        candidate = {
            int(row["repeat"]): row for row in rows if row["arm"] == "candidate"
        }
        fail_count = sum(
            (row.get("judge") or {}).get("verdict") == "fail" for row in rows
        )
        lines.append(
            f"| {index} | {severity(fail_count)} | `{target_id}` | "
            f"{target['domain']} / {target['evidence_role']} | "
            f"{verdict_cell(control)} | {verdict_cell(candidate[1])} | "
            f"{verdict_cell(candidate[2])} | {verdict_cell(candidate[3])} |"
        )
        grouped.append((target_id, target, rows))

    lines.extend(["", "## 逐题复核", ""])
    for index, (target_id, target, rows) in enumerate(grouped, start=1):
        fail_rows = [
            row for row in rows if (row.get("judge") or {}).get("verdict") == "fail"
        ]
        fail_count = len(fail_rows)
        locators = ", ".join(f"`{value}`" for value in target.get("locator") or [])
        lines.extend(
            [
                f"### {index}. {target_id} — {severity(fail_count)}",
                "",
                f"**问题：** {target['question']}",
                "",
                f"**来源：** `{target['file']}`；定位：{locators}",
                "",
                f"**冻结参考证据：** {target['verbatim_quote']}",
                "",
                f"**可接受证据规则：** {target.get('acceptable_evidence') or '未单列'}",
                "",
                "| 会话 | 判定 | 取得目标引文 | 工具错误 | 耗时（秒） |",
                "|---|---|---:|---:|---:|",
            ]
        )
        for row in sorted(rows, key=lambda value: (value["arm"] != "control", value["repeat"])):
            session = "Control" if row["arm"] == "control" else f"Candidate R{row['repeat']}"
            deterministic = row.get("deterministic") or {}
            trace = row.get("trace") or {}
            lines.append(
                f"| {session} | {verdict_cell(row)} | "
                f"{'是' if deterministic.get('quote_fetched') else '否'} | "
                f"{trace.get('tool_errors', 0)} | {row.get('wall_s', '')} |"
            )
        lines.extend(["", "**失败会话的 Judge 原因：**", ""])
        for row in sorted(fail_rows, key=lambda value: (value["arm"] != "control", value["repeat"])):
            session = "Control" if row["arm"] == "control" else f"Candidate R{row['repeat']}"
            reason = (row.get("judge") or {}).get("reason") or "未记录"
            lines.append(f"- **{session}：** {reason}")
        lines.extend(
            [
                "",
                "人工复核：",
                "",
                "- [ ] Judge 判定正确",
                "- [ ] 冻结参考证据正确且足以回答问题",
                "- [ ] 失败归因：漏检索 / 漏取回 / 误取回 / 答案遗漏 / 无依据扩写 / Judge 边界 / 题目或证据缺陷",
                "- [ ] 备注：",
                "",
            ]
        )

    OUT_MD.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "target_id",
                "question",
                "domain",
                "evidence_role",
                "arm",
                "repeat",
                "judge_verdict",
                "judge_reason",
                "quote_fetched",
                "quote_delivered",
                "tool_errors",
                "wall_s",
                "result_json",
            ],
        )
        writer.writeheader()
        for target_id in ordered_ids:
            target = gold[target_id]
            for row in sorted(
                by_target[target_id],
                key=lambda value: (value["arm"] != "control", value["repeat"]),
            ):
                if (row.get("judge") or {}).get("verdict") != "fail":
                    continue
                deterministic = row.get("deterministic") or {}
                trace = row.get("trace") or {}
                judge = row.get("judge") or {}
                writer.writerow(
                    {
                        "target_id": target_id,
                        "question": target["question"],
                        "domain": target["domain"],
                        "evidence_role": target["evidence_role"],
                        "arm": row["arm"],
                        "repeat": row["repeat"],
                        "judge_verdict": judge.get("verdict"),
                        "judge_reason": judge.get("reason"),
                        "quote_fetched": deterministic.get("quote_fetched"),
                        "quote_delivered": deterministic.get("quote_delivered"),
                        "tool_errors": trace.get("tool_errors", 0),
                        "wall_s": row.get("wall_s"),
                        "result_json": str(result_path(row).relative_to(ROOT)),
                    }
                )

    print(OUT_MD)
    print(OUT_CSV)


if __name__ == "__main__":
    main()
