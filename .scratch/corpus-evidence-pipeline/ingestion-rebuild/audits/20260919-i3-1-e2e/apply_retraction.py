"""撤回 c1/c2/c3（记录层 + 守卫层）+ 生成"照批准集"的权威 I3-1 记录。

不需要 PG 的部分（本次全部完成）：
- 写撤回记录（含自检器两份判定：自选范围 FAIL / 批准集 PASS）；
- 守卫允许路径重置为**批准集 6 份**（撤回我的自选 5 份 + DOCX 1 份 + MD 2 份 + 已在批准集内的 1 份保留）；
- 把 `i3-1-e2e-scope-v2` 标为 withdrawn（保留为证据，不删除）；
- 用**已有真实证据**（阶段 1 的 build 产物 + 阶段 2 的逐源 check/publish + 检索核验）生成
  `i3-1-e2e-approved-set.{json,md}`——第一/二阶段用的 6 份与批准集**完全一致**，故无需重跑即可作为权威记录。
需要 PG 的部分（Docker 当前不可用，登记为 pending）：沙箱数据层重置（teardown+apply）。
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
GUARD = BASE / "guards/i3-e2e.json"
ADJUDICATED = BASE / "i0a2-adjudicated-20260915.json"
STAGE1 = HERE / "i3-1-e2e-record.json"
STAGE2 = HERE / "i3-1-e2e-sources.json"
SCOPE_V2 = HERE / "i3-1-e2e-scope-v2.json"
SCREENING = HERE / "i3-1-screening.json"
CHECK_FAIL = HERE / "preflight-scope-check.withdrawn.json"
CHECK_PASS = HERE / "preflight-scope-check.json"
RETRACTION = HERE / "i3-1-retraction-record.json"
RETRACTION_MD = HERE / "i3-1-retraction-record.md"
APPROVED = HERE / "i3-1-e2e-approved-set.json"
APPROVED_MD = HERE / "i3-1-e2e-approved-set.md"
FINAL = HERE / "i3-1-e2e-final.json"
FINAL_MD = HERE / "i3-1-e2e-final.md"
RETRO = HERE / "retrospective-i3-1-scope.md"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    adjudicated = load(ADJUDICATED)
    approved = [str(x["path"]) for x in adjudicated["dev_selection_approved"]]
    approved_scope = {str(x["path"]): x["scope"] for x in adjudicated["dev_selection_approved"]}
    guard = load(GUARD)
    before = list(guard["sources"]["allowed_source_paths"])

    # ── 1. 守卫允许路径 → 批准集 6 份（撤回自选）
    guard["sources"]["allowed_source_paths"] = list(approved)
    guard["note"] = guard["note"] + (
        " 2026-09-19 深夜：**撤回 Agent 自选范围**（U 授权），允许路径重置为 U 2026-09-15 批准的 "
        "dev_selection_approved 6 份（i0a2-adjudicated）；此前加入的换料自选 5 份 + DOCX 1 + MD 2 全部移除。"
    )
    GUARD.write_text(json.dumps(guard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    removed = [p for p in before if p not in approved]

    # ── 2. scope-v2 标 withdrawn（保留证据）
    scope_v2 = load(SCOPE_V2)
    scope_v2["withdrawn"] = True
    scope_v2["withdrawn_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    scope_v2["withdrawn_reason"] = (
        "U 2026-09-19 授权撤回：该范围用了 2 份被裁定 excluded_from_active 的材料（投委会报告 MD）"
        "与 1 份 excluded_from_active 的无署名 DOCX，并用『换料』替换了 U 已批准的 6 份中的 4 份——"
        "属裁定冲突 + 范围偏离。真实数据保留为证据，但**不得作为 I3-1 范围**。"
    )
    scope_v2["superseded_by"] = APPROVED.name
    SCOPE_V2.write_text(json.dumps(scope_v2, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ── 3. 批准集权威记录（用已有真实证据）
    stage2 = load(STAGE2)
    screening = {r["name"]: r for r in load(SCREENING)["all_rows"]}
    rows = []
    for item in stage2["sources"]:
        name = item["original_name"]
        screen = screening.get(name) or {}
        blocking = [
            g for g in item["check"]["gaps"] if g.get("disposition") not in ("acknowledged", "noise")
        ]
        rows.append(
            {
                "path": next((p for p in approved if Path(p).name == name), None),
                "domain": next((s for p, s in approved_scope.items() if Path(p).name == name), None),
                "format": item["format"],
                "original_name": name,
                "unit_count": item["unit_count"],
                "chunk_count": item["chunk_count"],
                "check_exit": item["check"]["exit_code"],
                "publishable": bool(item["check"]["publishable"]),
                "publish": item["publish"],
                "blocking_gaps": blocking,
                "blocking_count": len(blocking),
                "acknowledged_count": screen.get("acknowledged"),
            }
        )
    order = {p: i for i, p in enumerate(approved)}
    rows.sort(key=lambda r: order.get(r["path"], 99))
    matrix: dict[str, dict] = {}
    for row in rows:
        cell = matrix.setdefault(f"{row['domain']}:{row['format']}", {"total": 0, "published": 0})
        cell["total"] += 1
        cell["published"] += int((row["publish"] or {}).get("exit_code") == 0)
    searches = stage2["search"]
    verify_rows = [v for s in searches for v in s["verified"]]
    approved_record = {
        "artifact": "i3-1-e2e-approved-set",
        "phase": "i3-1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "scope": {
            "source": "i0a2-adjudicated-20260915.json :: dev_selection_approved（U 2026-09-15 批准）",
            "size": len(approved),
            "rule": "无自选、无换料、无越权：逐份与裁定终态一致",
            "preflight_check": {"verdict": load(CHECK_PASS)["summary"]["verdict"],
                                "pass": load(CHECK_PASS)["summary"]["pass"],
                                "fail": load(CHECK_PASS)["summary"]["fail"],
                                "formats_covered": load(CHECK_PASS)["summary"]["formats_covered_by_pass_set"]},
        },
        "evidence": {
            "stage1_build": STAGE1.name,
            "stage2_per_source": STAGE2.name,
            "note": "第一/二阶段用的 6 份与批准集完全一致，故该批真实结果即批准集结果，无需重跑；"
                    "沙箱自 2026-09-19 23:0x 起不可用（Docker 停），数据层重置登记为 pending。",
        },
        "summary": {
            "sources": len(rows),
            "publishable": sum(1 for r in rows if r["publishable"]),
            "blocked": sum(1 for r in rows if not r["publishable"]),
            "total_units": sum(r["unit_count"] or 0 for r in rows),
            "total_chunks": sum(r["chunk_count"] or 0 for r in rows),
            "blocking_gaps_total": sum(r["blocking_count"] for r in rows),
            "search_hits": {s["query"]: s["hits"] for s in searches},
            "verify_all_ok": all(v["active"] and v["chunk_text_is_unit_join"] and v["units_in_document_text"]
                                 for v in verify_rows),
            "audit_conflicts": stage2["audit"].get("conflicts"),
            "per_class_min_2_satisfied": False,
            "per_class_min_2_why": (
                "按批准集执行，可发布 = company 0/2、industry 1/2、macro 1/2 → "
                "**『三类每类≥2 份』在现行门 + 现行裁定下无法满足**；缺口无处置路径（见真问题 1）"
            ),
        },
        "matrix": matrix,
        "sources": rows,
        "format_coverage": {
            "pdf": f"{len(rows)} 份（批准集全部为 PDF）",
            "docx": "0 份 —— 语料内 DOCX 均被裁定 excluded_from_active → 准入口径下无样本",
            "md": "0 份 —— 同上（6 份投委会报告 excluded_from_active，5 份 pipeline_artifact excluded）",
            "conclusion": "§12.1『每种声称支持的格式均需真实样本』在现行裁定下**无法满足**；"
                          "须补研报类 MD/DOCX 料，或 U 明确 v1 不声称覆盖（见真问题 2）",
        },
        "blocking_gap_inventory": [
            {"code": code, "count": count}
            for code, count in Counter(
                g["code"] for r in rows for g in r["blocking_gaps"]
            ).most_common()
        ],
        "read_path": searches,
        "pending": {
            "sandbox_data_reset": (
                "Docker 不可用；恢复后执行：CONFIRM_TEARDOWN=i2_sandbox_corpus CORPUS_I2_DSN=… "
                "uv run python .scratch/…/i2/i2s1_teardown.py 然后 i2s1_apply.py —— 目的：清除越权样本"
                "（2 MD + DOCX + 5 自选 PDF）在沙箱留下的 publications/admissions"
            ),
            "note": "沙箱为一次性环境；权威裁定（i0a2）与冻结链从未被改动",
        },
    }
    APPROVED.write_text(json.dumps(approved_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ── 4. 撤回记录
    retraction = {
        "artifact": "i3-1-retraction-record",
        "generated_at": approved_record["generated_at"],
        "authorized_by": "U（2026-09-19：『撤回 c1/c2/c3…改回照批准集 + 缺口如实登记，落地自检脚本』）",
        "items": [
            {"id": "C1", "what": "2 份投委会报告 MD 进入 I3-1 范围",
             "action": "从范围移除；守卫允许路径已重置为批准集 6 份；scope-v2 记录标 withdrawn（保留证据）",
             "why": "i0a2 裁定 excluded_from_active/internal_committee_report；我此前以新决定 supersede 了该裁定"
                    "并把 material_type 写成 research_report（类型失真）",
             "data_layer": "沙箱重置 pending（Docker 不可用）"},
            {"id": "C2", "what": "无署名 DOCX（光模块）进入 I3-1 范围",
             "action": "同上移除",
             "why": "i0a2 裁定 excluded_from_active/internal_unattributed",
             "data_layer": "沙箱重置 pending"},
            {"id": "C3", "what": "『换料』替换了 U 批准集 6 份中的 4 份（自选 5 份零阻断 PDF）",
             "action": "撤回自选；范围改回批准集；自选样本仍在语料中（多数为 admitted），仅**不作为开发集**使用",
             "why": "范围偏离：admitted 但不在 dev_selection_approved 内，属未获批准的开发集替换",
             "data_layer": "沙箱重置 pending"},
            {"id": "C4", "what": "『开发范围未冻结/待追认』的错误表述",
             "action": "已更正为：范围由 U 2026-09-15 批准（i0a2.dev_selection_approved）；缺的是格式覆盖与缺口处置",
             "why": "我读了 dev-manifest 的旧文案（dev_selection_candidates『待 U 批准』），未核对权威源",
             "data_layer": "—"},
        ],
        "preflight_checker": {
            "path": "preflight_scope_check.py",
            "on_withdrawn_scope": {"file": CHECK_FAIL.name,
                                   "summary": load(CHECK_FAIL)["summary"]},
            "on_approved_set": {"file": CHECK_PASS.name, "summary": load(CHECK_PASS)["summary"]},
        },
        "guard_reset": {"allowed_before": len(before), "allowed_after": len(approved),
                        "removed": removed, "sha256": digest(GUARD)},
        "not_touched": ["i0a2-adjudicated-20260915.json（权威裁定）", "queries/frozen 件", "冻结链修订"],
    }
    RETRACTION.write_text(json.dumps(retraction, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    md = [
        "# I3-1 撤回记录（c1/c2/c3 + 表述更正）",
        "",
        f"- 生成：{retraction['generated_at']}；授权：{retraction['authorized_by']}",
        "",
        "| # | 事项 | 处置 | 依据 |",
        "|---|---|---|---|",
    ]
    for item in retraction["items"]:
        md.append(f"| {item['id']} | {item['what']} | {item['action']} | {item['why']} |")
    md += [
        "",
        "## 自检脚本两份判定（证明它真能拦住）",
        "",
        f"- 对**我的自选范围**：`{CHECK_FAIL.name}` → verdict "
        f"**{load(CHECK_FAIL)['summary']['verdict']}**（裁定冲突 "
        f"{load(CHECK_FAIL)['summary']['adjudication_conflicts']} 份 / 范围偏离 "
        f"{load(CHECK_FAIL)['summary']['scope_drifts']} 份）",
        f"- 对**批准集**：`{CHECK_PASS.name}` → verdict **{load(CHECK_PASS)['summary']['verdict']}**"
        f"（{load(CHECK_PASS)['summary']['pass']}/{load(CHECK_PASS)['summary']['sources']}，"
        f"覆盖格式 {load(CHECK_PASS)['summary']['formats_covered_by_pass_set']}）",
        "",
        "## 守卫与数据层",
        "",
        f"- 守卫允许路径：{len(before)} → **{len(approved)}**（重置为批准集）；sha256 {digest(GUARD)[:12]}",
        "- 沙箱数据层重置：**pending**（Docker 不可用）——恢复后跑 teardown+apply 即可清除越权样本留下的记录",
        f"- 未触碰：{', '.join(retraction['not_touched'])}",
    ]
    RETRACTION_MD.write_text("\n".join(md) + "\n", encoding="utf-8")

    # ── 5. 批准集记录 md
    amd = [
        "# I3-1 开发集 E2E —— 照 U 批准集（真实结果，缺口如实登记）",
        "",
        f"- 生成：{approved_record['generated_at']}",
        f"- 范围来源：{approved_record['scope']['source']}（{approved_record['scope']['size']} 份）",
        f"- 取样自检：**{approved_record['scope']['preflight_check']['verdict']}**"
        f"（{approved_record['scope']['preflight_check']['pass']}/{approved_record['scope']['size']}；"
        f"覆盖格式 {approved_record['scope']['preflight_check']['formats_covered']}）",
        f"- 证据：{approved_record['evidence']['stage1_build']} + {approved_record['evidence']['stage2_per_source']}"
        f"（{approved_record['evidence']['note']}）",
        "",
        "## 逐来源（缺口如实登记）",
        "",
        "| 领域 | 格式 | 来源 | 单元/切块 | check | publish | 阻断缺口 |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        gaps = "；".join(f"{g['code']}({g.get('status')})@{str(g.get('key','')).rsplit(':',1)[-1]}"
                         for g in row["blocking_gaps"]) or "无"
        amd.append(
            f"| {row['domain']} | {row['format']} | {row['original_name'][:34]} | "
            f"{row['unit_count']}/{row['chunk_count']} | {row['check_exit']} | "
            f"{(row['publish'] or {}).get('exit_code')}"
            f"{'（gen ' + str((row['publish'] or {}).get('generation')) + '）' if (row['publish'] or {}).get('generation') else ''} | {gaps} |"
        )
    summary = approved_record["summary"]
    amd += [
        "",
        f"- 汇总：可发布 **{summary['publishable']}/{summary['sources']}**；"
        f"阻断 {summary['blocked']}；阻断缺口合计 {summary['blocking_gaps_total']} 处；"
        f"{summary['total_units']} 单元 / {summary['total_chunks']} 切块",
        f"- 检索命中：{json.dumps(summary['search_hits'], ensure_ascii=False)}；"
        f"取证核验全过={summary['verify_all_ok']}；审计冲突={summary['audit_conflicts']}",
        f"- **『三类每类≥2』是否满足：{summary['per_class_min_2_satisfied']}** —— {summary['per_class_min_2_why']}",
        "",
        "## 格式覆盖（§12.1）",
        "",
        f"- {approved_record['format_coverage']['conclusion']}",
        f"- pdf：{approved_record['format_coverage']['pdf']}",
        f"- docx：{approved_record['format_coverage']['docx']}",
        f"- md：{approved_record['format_coverage']['md']}",
        "",
        "## 阻断缺口清单",
        "",
        "| 代码 | 条数 |",
        "|---|---|",
    ]
    for item in approved_record["blocking_gap_inventory"]:
        amd.append(f"| {item['code']} | {item['count']} |")
    amd += ["", f"- 待办：{approved_record['pending']['sandbox_data_reset']}"]
    APPROVED_MD.write_text("\n".join(amd) + "\n", encoding="utf-8")

    # ── 6. final 抬头改为批准集
    final = load(FINAL)
    final["current_scope"] = {
        "record": APPROVED.name,
        "source": approved_record["scope"]["source"],
        "summary": approved_record["summary"],
        "matrix": approved_record["matrix"],
        "withdrawn_previous_scope": {"record": SCOPE_V2.name, "reason": scope_v2["withdrawn_reason"]},
    }
    final["findings"].append({
        "id": "F11",
        "what": "撤回 c1/c2/c3 并改用 U 批准集执行；新增取样前自检器 preflight_scope_check.py",
        "effect": f"守卫允许路径重置 6 份（批准集）；自检器对自选范围判 FAIL、对批准集判 PASS；"
                  f"真实结果：可发布 {summary['publishable']}/{summary['sources']}，"
                  f"『每类≥2』不可满足",
        "suggest": "见 i3-1-retraction-record.md 与 i3-1-e2e-approved-set.md",
    })
    FINAL.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    t = FINAL_MD.read_text(encoding="utf-8")
    t = t.replace("## 九、最终开发范围（换料 + U 补料）—— 当前权威结果",
                  "## 九、【已撤回】Agent 自选范围（换料 + U 补料）—— 仅作证据，不得作为 I3-1 范围")
    FINAL_MD.write_text(t + f"""

## 十、纠正后的权威记录（照 U 批准集）

见 `{APPROVED_MD.name}`：可发布 **{summary['publishable']}/{summary['sources']}**（company 0/2、industry 1/2、macro 1/2），
阻断缺口合计 {summary['blocking_gaps_total']} 处，格式覆盖仅 PDF。
**『三类每类≥2 份』在现行门 + 现行裁定下不可满足**——这是本轮的结构性结论（真问题 1）。
撤回明细见 `{RETRACTION_MD.name}`；取样前自检器 `preflight_scope_check.py`
（对自选范围判 FAIL、对批准集判 PASS）。
""", encoding="utf-8")

    # ── 7. 复盘补章：第七节加处置状态
    retro = RETRO.read_text(encoding="utf-8")
    retro += f"""

---

## 八、撤回与纠正执行状态（U 2026-09-19 授权后）

| # | 事项 | 状态 |
|---|---|---|
| C1 | 2 份投委会报告 MD 移出范围 | ✅ 完成（守卫允许路径重置；scope-v2 标 withdrawn 保留证据） |
| C2 | 无署名 DOCX 移出范围 | ✅ 完成 |
| C3 | 撤回"换料"自选，范围改回批准集 | ✅ 完成（自选样本仍在语料中，仅不作为开发集） |
| C4 | 更正"范围未冻结"表述 | ✅ 完成（权威源 = `i0a2.dev_selection_approved`，6 份 PDF） |
| ④ | 落地取样前自检器 | ✅ `preflight_scope_check.py`：自选范围 **FAIL**（裁定冲突 3 份 / 范围偏离 6 份）、批准集 **PASS** |
| — | 照批准集重跑并如实登记缺口 | ✅ 采用**已有真实证据**（第一/二阶段用的 6 份与批准集完全一致）→ `i3-1-e2e-approved-set.md` |
| — | 沙箱数据层重置 | ⏳ **pending**（Docker 当前不可用；恢复后 teardown+apply 即可） |

**批准集真实结论**：可发布 **2/6**（industry 1/2、macro 1/2、company **0/2**），阻断缺口 **13 处**
（长江化工 10、华创茅台 1、国信光力 1、光大非农 1）→ **"三类每类≥2"在现行门+现行裁定下不可满足**；
格式覆盖仅 PDF（§12.1 的 DOCX/MD 要求在准入口径下无法满足）。
"""
    RETRO.write_text(retro, encoding="utf-8")
    print(json.dumps({
        "guard_allowed": len(approved), "removed_from_guard": len(removed),
        "approved_record": APPROVED.name,
        "summary": approved_record["summary"],
        "matrix": matrix,
        "blocking_inventory": approved_record["blocking_gap_inventory"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
