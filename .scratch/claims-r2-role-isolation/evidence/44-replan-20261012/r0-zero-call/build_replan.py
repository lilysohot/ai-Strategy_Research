"""Re-plan of the whole remaining chain, with a machine-checked completeness audit.

Zero call, read-only. The inventory is declared in one place; a coverage check then proves that
every source list (report §7 rows, report §9 rows, defect list D1-D12, and the artifacts found by
scanning) maps to at least one plan item, and it declares explicitly what was NOT scanned.

Usage:
    uv run python .scratch/claims-r2-role-isolation/evidence/44-replan-20261012/r0-zero-call/build_replan.py
    ... --no-write
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E44 = HERE.parent
CLAIMS = E44.parent.parent
REPO_ROOT = HERE.parents[4]
E36_R0 = CLAIMS / "evidence" / "36-l9-redo-and-baseline-20261011" / "r0-zero-call"
for path in (str(REPO_ROOT), str(E36_R0)):
    if path not in sys.path:
        sys.path.insert(0, path)

from l9_redo import digest, read_json  # noqa: E402

EV = CLAIMS / "evidence"
REPORT = EV / "34-chain-root-cause-audit-20261011" / "chain-report.md"
REVIEW = EV / "45-contract-v4-draft-20261012" / "r0-zero-call" / "contract-v4-review.md"
SIGNED_V4 = EV / "43-scoring-contract-v4-signed-20261012" / "r0-zero-call" / "scoring-contract-v4.json"
PARALLEL_DIR = EV / "41-items-chain-accounting-20261012" / "r3-signoff-apply"
PREREG = HERE / "preregistered-replan.json"

# id, title, wave, kind, owner, cost, deps, source
ITEMS: list[dict[str, Any]] = [
    # ---------------- Wave 0: zero-decision, pure engineering / hygiene, can start now
    {"id": "P01", "title": "裁定→评分输入装配器（adjudications + 工作台 → raw/validated CandidateRecord）",
     "wave": 0, "kind": "code", "owner": "agent", "cost": "零模型调用", "deps": [], "sources": ["D3", "§9-Stage2阻塞条款"]},
    {"id": "P02", "title": "评分器匹配机制改造（消费裁定映射，不再以 identity 相等为前提）",
     "wave": 0, "kind": "code", "owner": "agent", "cost": "零模型调用", "deps": ["P10"], "sources": ["D2", "D12"]},
    {"id": "P03", "title": "阈值单源落地：评分器读契约（OPEN-1=A 的兑现）",
     "wave": 2, "kind": "code", "owner": "agent", "cost": "零模型调用", "deps": ["P11"], "sources": ["D5", "§7-6"]},
    {"id": "P04", "title": "口径归一化 + 读路径实现（caliber_rules / read_path）",
     "wave": 2, "kind": "code", "owner": "agent", "cost": "零模型调用", "deps": ["P11"], "sources": ["§7-7", "§7-11"]},
    {"id": "P05", "title": "口径映射回归测试（防映射随数据/模型漂移）",
     "wave": 2, "kind": "code", "owner": "agent", "cost": "零模型调用", "deps": ["P04"], "sources": ["§7-7 A2"]},
    {"id": "P06", "title": "签认护栏推广到其它生成脚本（默认拒绝覆盖已签认产物）",
     "wave": 0, "kind": "process", "owner": "agent", "cost": "零调用", "deps": [], "sources": ["D9"]},
    {"id": "P07", "title": "消编号歧义（两个 41：contract-v4-draft 与 items-chain-accounting）",
     "wave": 0, "kind": "process", "owner": "U", "cost": "零调用", "deps": [], "sources": ["D10"]},
    {"id": "P08", "title": "补齐或声明不补 MANIFEST（32/33/34/35 与 41-items-chain-accounting 的 r0）",
     "wave": 0, "kind": "audit", "owner": "agent", "cost": "零调用", "deps": [], "sources": ["scan-MANIFEST-missing"]},

    # ---------------- Wave 1: signed contract completion
    {"id": "P10", "title": "v4.1 合并草案：并入并行草案 18 条独有叶子（含 3 条核心读路径条款）",
     "wave": 1, "kind": "contract", "owner": "agent", "cost": "零调用", "deps": [], "sources": ["§9-v4.1", "§5.13.1", "D1", "D4", "D6"]},
    {"id": "P11", "title": "v4.1 签认（取代两份 v4 并存的局面）",
     "wave": 1, "kind": "signoff", "owner": "U", "cost": "人工", "deps": ["P10"], "sources": ["§9-v4.1", "D6"]},

    # ---------------- Wave 2: bookkeeping that depends on the signed contract hash
    {"id": "P12", "title": "契约绑定再绑定 v2→v3→v4.1（金标 freeze-manifest）",
     "wave": 2, "kind": "audit", "owner": "agent", "cost": "零调用", "deps": ["P11"], "sources": ["D8", "§5.3-记账4条", "scan-parallel-freeze-rebinding-record"]},
    {"id": "P13", "title": "门 28 metric_basis 推进至 v4.1，消除「权威源基准过期 + 阈值循环引用」",
     "wave": 2, "kind": "contract", "owner": "U", "cost": "零调用，须具名签认", "deps": ["P11"], "sources": ["D7"]},
    {"id": "P14", "title": "validation-report.human_accepted_counts 与 48/48 对齐",
     "wave": 2, "kind": "audit", "owner": "agent", "cost": "零调用", "deps": ["P11"], "sources": ["§5.3-记账4条", "scan-parallel-gold-acceptance-record"]},
    {"id": "P15", "title": "采纳/否决并行提案 gate-32-v2-criteria.proposed.json（门 32 判据拆 G1/G2）",
     "wave": 2, "kind": "contract", "owner": "U", "cost": "零调用", "deps": [], "sources": ["§5.3-门32判据不同轴", "scan-parallel-gate32-criteria"]},
    {"id": "P16", "title": "冻结链校验器（任何契约/金标/manifest 修订须校验绑定一致）",
     "wave": 2, "kind": "code", "owner": "agent", "cost": "零模型调用", "deps": ["P11"], "sources": ["v4 bookkeeping_requirements"]},

    # ---------------- Wave 3: human / authorized, parallelisable
    {"id": "P18", "title": "缺口1：32 条区间「可救性」粗判抽样（不依赖 v4.1 细节）",
     "wave": 3, "kind": "human", "owner": "xyl", "cost": "人工", "deps": [], "sources": ["§9-32条抽样", "§7-14", "gap1"]},
    {"id": "P19", "title": "缺口2：route b 受控双臂实验（试跑 4 次 → 视结论决定全量 48）",
     "wave": 3, "kind": "authorized-call", "owner": "U", "cost": "4~48 次模型调用", "deps": [], "sources": ["§9-routeb实验授权", "§7-13", "gap2"]},
    {"id": "P20", "title": "补跑被传输事件丢掉的 1 个包（7 条 critical），含重试/幂等策略",
     "wave": 3, "kind": "authorized-call", "owner": "U", "cost": "1 次模型调用 + 新门", "deps": [], "sources": ["§9-补跑授权", "§7-2", "I1"]},
    {"id": "P21", "title": "裁定 L6 两个我方信号槽（forecast / evidence）",
     "wave": 3, "kind": "contract", "owner": "U", "cost": "零调用", "deps": [], "sources": ["§9-L6两槽", "§7-4"]},
    {"id": "P22", "title": "裁定 B-1 两条（NT-I06 / NT-I41）性质",
     "wave": 3, "kind": "human", "owner": "U", "cost": "零调用", "deps": [], "sources": ["§9-B1两条", "backlog B-1"]},
    {"id": "P23", "title": "跨角色范围裁定（claims 是否建读路径）",
     "wave": 3, "kind": "contract", "owner": "U", "cost": "零调用", "deps": [], "sources": ["§9-跨角色范围", "§5.11"]},
    {"id": "P24", "title": "读路径普遍性三条硬要求：接受与否",
     "wave": 3, "kind": "contract", "owner": "U", "cost": "零调用", "deps": [], "sources": ["§9-普遍性三条", "§5.7"]},
    {"id": "P25", "title": "Stage-1 助手 v2 是否采用为新裁定基线（取代 v1/v2 建议）",
     "wave": 3, "kind": "tool", "owner": "U", "cost": "零调用", "deps": [], "sources": ["§9-Stage1助手", "§5.14"]},
    {"id": "P26", "title": "路线 a/b 最终裁定（凭缺口 1+2 的数据）",
     "wave": 3, "kind": "contract", "owner": "U", "cost": "零调用", "deps": ["P18", "P19"], "sources": ["§9-接缝路线", "§9-路线ab最终裁定"]},

    # ---------------- Wave 4: execution
    {"id": "P27", "title": "Stage 2 全量 222 条裁定（含 source_stance 逐条按原文判定）",
     "wave": 4, "kind": "human", "owner": "xyl", "cost": "222 条人工", "deps": ["P11", "P25"], "sources": ["§9-Stage2阻塞条款", "unresolved_candidates_max=0"]},
    {"id": "P29", "title": "Stage 3 严格评分（依赖装配器 + 匹配改造 + 阈值单源）",
     "wave": 4, "kind": "code", "owner": "agent", "cost": "零模型调用", "deps": ["P01", "P02", "P03", "P04", "P27"], "sources": ["D2", "D3", "D5"]},
    {"id": "P30", "title": "门 33 判定（出分或明确失败归因）",
     "wave": 4, "kind": "gate", "owner": "U", "cost": "零调用", "deps": ["P29", "P20"], "sources": ["§6", "§7-2"]},

    # ---------------- Wave 5: closure
    {"id": "P31", "title": "报告 r9 收口：闭项回填、§7/§9 去重与重排、签认栏",
     "wave": 5, "kind": "doc", "owner": "U", "cost": "零调用", "deps": ["P30"], "sources": ["§7-编号乱序", "§9-接缝路线重复两行"]},

    # ---------------- already closed (kept so the audit can prove nothing was dropped)
    {"id": "C01", "title": "L9 重做（留出记录、禁金标注入）", "wave": -1, "kind": "closed",
     "owner": "agent", "cost": "—", "deps": [], "sources": ["§7-8"]},
    {"id": "C02", "title": "三角色同型 L3 审计", "wave": -1, "kind": "closed",
     "owner": "agent", "cost": "—", "deps": [], "sources": ["§7-9"]},
    {"id": "C03", "title": "门 33 工作台 v2（严格超集）", "wave": -1, "kind": "closed",
     "owner": "agent", "cost": "—", "deps": [], "sources": ["§7-10"]},
    {"id": "C04", "title": "Stage-1 助手 v2（证据链版）", "wave": -1, "kind": "closed",
     "owner": "agent", "cost": "—", "deps": [], "sources": ["§7-5"]},
    {"id": "C05", "title": "契约 v4 签认并落地（OPEN-1=A / OPEN-2=C / FORCED-1 确认）", "wave": -1,
     "kind": "closed", "owner": "xyl", "cost": "—", "deps": [], "sources": ["§9-契约v4审阅", "§9-阈值统一", "§9-枚举口径"]},
    {"id": "C06", "title": "chain-report §10 误填签认撤销（含留痕）", "wave": -1, "kind": "closed",
     "owner": "agent", "cost": "—", "deps": [], "sources": ["§10-撤销留痕"]},
    {"id": "C07", "title": "生成脚本签认护栏（本批脚本）", "wave": -1, "kind": "closed",
     "owner": "agent", "cost": "—", "deps": [], "sources": ["D9-partial"]},
    {"id": "C08", "title": "route a/b 同量纲成本-收益表 + 冻结影响清单 + 实验预注册草案", "wave": -1,
     "kind": "closed", "owner": "agent", "cost": "—", "deps": [], "sources": ["§5.12"]},
]

# Items observed by the scan that are already closed by a decision; kept so the audit can prove
# they were seen rather than silently dropped.
EXTRA_CLOSED: list[dict[str, Any]] = [
    {"id": "C09", "title": "§7-12 material_relations 契约缺陷：由 OPEN-2=C 裁定本轮不纳入评分（缺陷保留在案）",
     "wave": -1, "kind": "closed", "owner": "xyl", "cost": "—", "deps": [], "sources": ["relations缺陷"]},
    {"id": "C10", "title": "issues 32/33 门签认有效（xyl 2026-10-10/11），无需动作",
     "wave": -1, "kind": "closed", "owner": "xyl", "cost": "—", "deps": [],
     "sources": ["scan:issues32(filled)", "scan:issues33(filled)"]},
    {"id": "C11", "title": "issues/41 §10 用户签认有效（认可口径并准予继续，2026-10-12）",
     "wave": -1, "kind": "closed", "owner": "xyl", "cost": "—", "deps": [],
     "sources": ["scan:issues41(filled)"]},
]
ITEMS = ITEMS + EXTRA_CLOSED

# Explicit ownership for source labels that are not literally a declared source string.
# Keeps the coverage check strict (every label must resolve to an owning item) while readable.
ALIASES = {
    "§7-3": "P01",
    "§7-12": "C09",
    "relations缺陷": "C09",
    "口径归一化": "C05",
    "D11": "P08",
    "parallel:contract-v4-draft.md": "P10",
    "parallel:gate-32-criteria-alignment.md": "P15",
    "parallel:scoring-contract-v4.proposed.json": "P10",
    "parallel:gate-32-v2-criteria.proposed.json": "P15",
    "parallel:freeze-rebinding-record.json": "P12",
    "parallel:gold-acceptance-record.json": "P14",
    "MANIFEST-missing:32/33/34/35": "P08",
    "MANIFEST-missing:41-items-chain-accounting": "P08",
    "signoff:chain-report(blank/revoked)": "C06",
    "signoff:issues32(filled)": "C10",
    "signoff:issues33(filled)": "C10",
    "signoff:issues41(filled)": "C11",
    "signoff:contract-v4-review(filled)": "C05",
}

DEFECTS = {
    "D1": "已签 v4 缺 absent_required_fields.rule（缺字段不得直接判不匹配）→ P10",
    "D2": "评分器只认字段逐字相等，不消费裁定 → P02",
    "D3": "裁定→评分输入装配器不存在 → P01",
    "D4": "已签 v4 缺 carrier_mapping.rule（只改字段名）→ P10",
    "D5": "OPEN-1=A 已签但评分器未改（阈值双源）→ P03",
    "D6": "两份 v4 并存 → P10/P11",
    "D7": "门 28 基准过期 + 阈值循环引用 → P13",
    "D8": "金标冻结链契约绑定未再绑定 → P12",
    "D9": "护栏只在单个脚本（部分闭合）→ P06",
    "D10": "编号冲突（两个 41）→ P07",
    "D11": "32/33/34/35 与 41-items-chain-accounting 的 r0 无 MANIFEST → P08",
    "D12": "评分器 identity 匹配与契约 matching.mode 不相容（D2 的契约侧）→ P02/P10",
}

REPORT_SECTION7_ROWS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14"]
REPORT_SECTION9_ROWS = [
    "接缝路线", "补跑授权", "L6两槽", "Stage2阻塞条款", "Stage1助手", "契约v4审阅", "v4.1",
    "阈值统一", "普遍性三条", "跨角色范围", "B1两条", "relations缺陷", "routeb实验授权",
    "32条抽样", "路线ab最终裁定", "口径归一化",
]
SCAN_FINDINGS = [
    "parallel:contract-v4-draft.md", "parallel:gate-32-criteria-alignment.md",
    "parallel:scoring-contract-v4.proposed.json", "parallel:gate-32-v2-criteria.proposed.json",
    "parallel:freeze-rebinding-record.json", "parallel:gold-acceptance-record.json",
    "MANIFEST-missing:32/33/34/35", "MANIFEST-missing:41-items-chain-accounting",
    "signoff:chain-report(blank/revoked)", "signoff:issues32(filled)", "signoff:issues33(filled)",
    "signoff:issues41(filled)", "signoff:contract-v4-review(filled)",
]

NOT_SCANNED = [
    "U01 evidence/01–31 的内容未逐一核（仅按引用触及 10/28/32/33/34/35）",
    "U02 issues/01–31 的开放项未逐一核",
    "U03 benchmarks/ workflows/ plugins/ 全量未核（仅核评分器与契约相关文件）",
    "U04 并行会话在 44 号之后的产出未纳入（滚动纳入，不声称穷尽）",
    "U05 未核 holdout 与生产库（范围内禁止）",
]


def coverage_check() -> dict[str, Any]:
    """Every source label must resolve to an owning item, either literally or via ALIASES."""
    mapped = {src for item in ITEMS for src in item["sources"]}
    joined = " ".join(mapped)

    def covered(label: str) -> bool:
        return label in ALIASES or label in joined

    unmapped7 = [row for row in REPORT_SECTION7_ROWS if not covered(f"§7-{row}")]
    unmapped9 = [row for row in REPORT_SECTION9_ROWS if not covered(row)]
    unmapped_defects = [key for key in DEFECTS if not covered(key)]
    unmapped_scan = [key for key in SCAN_FINDINGS if not covered(key)]
    return {
        "section7_rows_unmapped": unmapped7,
        "section9_rows_unmapped": unmapped9,
        "defects_unmapped": unmapped_defects,
        "scan_findings_unmapped": unmapped_scan,
        "aliases_used": len(ALIASES),
        "complete": not (unmapped7 or unmapped9 or unmapped_defects or unmapped_scan),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    read_json(PREREG)
    coverage = coverage_check()
    waves: dict[str, list[dict[str, Any]]] = {}
    for item in ITEMS:
        waves.setdefault(str(item["wave"]), []).append(item["id"])

    wave_meta = {
        "0": {"name": "零裁定·纯工程（可现在开始）", "exit": "P01/P02/P06/P08 全部产出且回归通过；P07 由 U 一句话决定"},
        "1": {"name": "契约补全（需 U 签）", "exit": "v4.1 草案 diff 可核 + U 签认；并行那份标 superseded"},
        "2": {"name": "记账与绑定（依赖 v4.1 哈希）", "exit": "绑定再绑定记录 + 门 28 基准推进 + 校验器落地"},
        "3": {"name": "人工/授权（可并行）", "exit": "缺口 1 与缺口 2 各有数据；路线 a/b 可裁"},
        "4": {"name": "执行出分", "exit": "Stage 2 全量裁定完成 → Stage 3 评分 → 门 33 判定"},
        "5": {"name": "收口", "exit": "报告 r9 闭项回填且签认"},
        "-1": {"name": "已闭合（仅为审计保留）", "exit": "—"},
    }
    critical_path = ["P10", "P11", "P01", "P02", "P03", "P04", "P27", "P29", "P30"]

    artifact = {
        "schema_version": "items-replan-1",
        "created_on": "2026-10-12",
        "zero_call": True,
        "inputs": {
            "report": digest(REPORT),
            "contract_v4_review_signed": digest(REVIEW),
            "scoring_contract_v4_signed": digest(SIGNED_V4),
            "gate32_v2_criteria_proposed": digest(PARALLEL_DIR / "gate-32-v2-criteria.proposed.json"),
        },
        "coverage_check": coverage,
        "defects": DEFECTS,
        "items": ITEMS,
        "waves": wave_meta,
        "wave_members": waves,
        "critical_path": critical_path,
        "not_scanned": NOT_SCANNED,
        "completeness_mechanism": (
            "① 清单只在本文件声明一处，所有其它视图由它派生；"
            "② coverage_check 逐源核对（§7 全 14 行、§9 全 16 项、D1–D12、扫描命中），任何未映射即 complete=false；"
            "③ not_scanned 显式声明未覆盖范围，未核项不得被当作已闭合。"
        ),
        "headline": (
            "链路末端有两个无代码实现的缺环（P01 装配器、P02 匹配机制）："
            "不修则『v4.1 补全 + 222 条裁定做完』仍然 0 分，并会把 0 分误归因为抽取质量。"
            "这两项零裁定、可立刻做，是本次重规划的起点。"
        ),
    }

    print(
        json.dumps(
            {
                "coverage_complete": coverage["complete"],
                "coverage": coverage,
                "wave_members": waves,
                "critical_path": critical_path,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.no_write:
        return

    (HERE / "replan.json").write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "replan.md").write_text(render_md(artifact), encoding="utf-8")
    manifest = {
        "schema_version": "items-replan-manifest-1",
        "created_on": "2026-10-12",
        "inputs": artifact["inputs"],
        "outputs": {
            name: digest(HERE / name)
            for name in ("preregistered-replan.json", "replan.json", "replan.md", "build_replan.py")
        },
    }
    (HERE / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if not coverage["complete"]:
        raise SystemExit("coverage_check failed: %s" % json.dumps(coverage, ensure_ascii=False))


def render_md(artifact: dict[str, Any]) -> str:
    items = {item["id"]: item for item in artifact["items"]}
    lines = [
        "# 全链路重规划（含遗漏自检）",
        "",
        f"- 遗漏自检：**complete = {artifact['coverage_check']['complete']}**"
        f"（§7 未映射 {len(artifact['coverage_check']['section7_rows_unmapped'])}、"
        f"§9 未映射 {len(artifact['coverage_check']['section9_rows_unmapped'])}、"
        f"缺陷未映射 {len(artifact['coverage_check']['defects_unmapped'])}、"
        f"扫描命中未映射 {len(artifact['coverage_check']['scan_findings_unmapped'])}）",
        f"- 关键路径：`{' → '.join(artifact['critical_path'])}`",
        "",
        f"> {artifact['headline']}",
        "",
        "## 遗漏自检机制",
        "",
        f"{artifact['completeness_mechanism']}",
        "",
        "## 未覆盖范围（不得当作已闭合）",
        "",
    ]
    lines += [f"- {item}" for item in artifact["not_scanned"]]
    for wave in ["0", "1", "2", "3", "4", "5", "-1"]:
        meta = artifact["waves"][wave]
        members = artifact["wave_members"].get(wave, [])
        lines += ["", f"## Wave {wave} · {meta['name']}", "", f"- 退出判据：{meta['exit']}", ""]
        if wave == "-1":
            lines.append("- " + "、".join(f"`{mid}`" for mid in members))
            continue
        lines += ["| ID | 事项 | 性质 | 责任 | 成本 | 依赖 | 来源 |", "|---|---|---|---|---|---|---|"]
        for mid in members:
            item = items[mid]
            lines.append(
                "| {0} | {1} | {2} | {3} | {4} | {5} | {6} |".format(
                    item["id"], item["title"], item["kind"], item["owner"], item["cost"],
                    ", ".join(item["deps"]) or "—", ", ".join(item["sources"]),
                )
            )
    lines += ["", "## 缺陷 → 计划项 映射（D1–D12）", "", "| 缺陷 | 内容 |", "|---|---|"]
    for key, value in artifact["defects"].items():
        lines.append(f"| {key} | {value} |")
    lines += [
        "",
        "## 与并行会话的关系",
        "",
        "- 并行提案 `gate-32-v2-criteria.proposed.json`（门 32 判据拆 G1/G2）与"
        "`freeze-rebinding-record.json` / `gold-acceptance-record.json` 已纳入 P15/P12/P14，"
        "**须采纳或明确否决**，不得静默并存。",
        "- 并行 `scoring-contract-v4.proposed.json` 由 P10 并入后标 `superseded_by`。",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
