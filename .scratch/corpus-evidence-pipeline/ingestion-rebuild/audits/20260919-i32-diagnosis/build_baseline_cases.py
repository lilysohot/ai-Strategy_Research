"""步骤 3：生成 7 类旧基线的**用例清单**（case manifest）+ 步骤 1 的统一状态表。

只读仓库内既有证据，零模型、零写库；**资料缺口一律标 `blocked_needs_user` 并写清问题，不猜、不拼**。
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]  # ingestion-rebuild
ROOT = HERE.parents[4]

PILOT = ROOT / ".scratch/corpus-evidence-pipeline/pilot_manifest.json"
MACHINE = (
    ROOT
    / ".scratch/corpus-evidence-pipeline/claims-entry-27dfab4cb9a97cf8ad72d269039d822afc3f39631601d76c0bed1b87645c0cb3.json"
)
BASELINE_INDEX = BASE / "baseline-bindings.json"
V3 = BASE / "i0a4-candidates-v3-20260915.json"
GUARD = BASE / "guards/i3.json"
FREEZE_MANIFEST = BASE / "freezes/freeze-manifest.json"
GOLDEN = ROOT / "plugins/corpus/golden.py"
SPEC = ROOT / ".scratch/corpus-evidence-pipeline/spec.md"
SEMANTIC = ROOT / ".scratch/corpus-evidence-pipeline/semantic-repair-report.md"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_financial_57() -> dict:
    manifest = load_json(PILOT)
    cases = []
    for sample in manifest.get("samples", []):
        name = sample.get("name")
        for row in sample.get("gold") or []:
            for column, value in zip(row.get("columns") or [], row.get("values") or []):
                cases.append(
                    {
                        "case_id": f"fin57|{name}|{row.get('row')}|{column}",
                        "category": "financial_controlled_recalc_57",
                        "expected": value,
                        "unit": row.get("unit"),
                        "column": column,
                        "row": row.get("row"),
                        "sample": name,
                        "sample_role": sample.get("role"),
                        "source_anchor": sample.get("pattern"),
                        "source_pages": sample.get("pages"),
                        "tolerance": 0,  # U 2026-09-19：规范化后精确匹配；公式子节点沿用 tolerance
                        "holdout_related": sample.get("role") == "held_out_parser_check"
                        or "holdout" in str(name),
                    }
                )
    return {
        "categories": ["financial_controlled_recalc_57"],
        "expected_asset": {
            "path": rel(PILOT),
            "sha256": digest(PILOT),
            "selector": "samples[*].gold[*].{row,columns,values,unit}",
        },
        "case_count": len(cases),
        "cases": cases,
        "historical_status": "57/57 字段通过（历史 run：maotai 32／guangli 15／guosen 10）",
        "historical_record_ref": {
            "path": rel(MACHINE),
            "sha256": digest(MACHINE),
            "selector": "samples[*].{name,run_id,fields_passed,facts_read}",
        },
        "rerun_contract": {
            "entry": ".scratch/corpus-evidence-pipeline/verify_claims_entry.py",
            "entry_sha256": digest(ROOT / ".scratch/corpus-evidence-pipeline/verify_claims_entry.py"),
            "params": "CorpusService.extract_claims(明确源文件, pages)；消费 pilot_manifest gold",
            "side_effects": "向**原库 5432** 写 corpus_evidence_runs 新行（零模型但非零写）",
            "required_environment": "隔离 PG 目标 + 显式预算授权（I3-5）",
            "runnable_now": False,
            "why_not": "I3 守卫 read_roots 为空、无网络；旧入口写原库，须先迁移到已核验隔离目标",
        },
        "validation_stage": "I3-5（非回归重验，需单独授权）；I3-2 只冻结预期与契约",
        "gaps": [
            {
                "status": "confirmed",
                "item": "字段容差（tolerance）",
                "detail": "U 2026-09-19 确认；普通字段先规范化（去千分位逗号、去尾随/前导零、统一负号）后精确匹配 tolerance=0；公式沿用其 tolerance（1e-6）",
            },
            {
                "status": "confirmed",
                "item": "范围：guosen_maotai_holdout（10 格）与留出的关系",
                "detail": "U 2026-09-19 确认纳入守卫留出链：i3.json forbidden_roots 第 4 份 = data/corpus/2026-08-17_…国信证券-…bbba671e.pdf；"
                          "10 格列『历史非回归范围』，I3-5 才可重验、开发校准不读其原文",
            },
        ],
    }


def build_formula_7() -> dict:
    record = load_json(MACHINE)
    sample = next((s for s in record.get("samples", []) if s.get("formulas")), None)
    cases = []
    for formula in (sample or {}).get("formulas") or []:
        cases.append(
            {
                "case_id": f"formula7|{formula.get('formula')}",
                "category": "formula_7",
                "calculation_id": formula.get("calculation_id"),
                "formula": formula.get("formula"),
                "expected": formula.get("expected"),
                "tolerance": formula.get("tolerance"),
                "computed_by": formula.get("computed_by"),
                "run_id": formula.get("run_id"),
                "passed_historically": formula.get("passed"),
                "parent_category": "financial_controlled_recalc_57",
            }
        )
    return {
        "categories": ["formula_7"],
        "expected_asset": {
            "path": rel(MACHINE),
            "sha256": digest(MACHINE),
            "selector": f"samples[name={sample.get('name') if sample else None}].formulas[*]",
        },
        "case_count": len(cases),
        "cases": cases,
        "historical_status": "7/7 复算通过（父项 financial_controlled_recalc_57 的子节点）",
        "historical_record_ref": {"path": rel(MACHINE), "sha256": digest(MACHINE)},
        "rerun_contract": {
            "entry": "corpus-financial-formulas-1（computed_by）",
            "params": "同一 pilot_manifest 样本（derive=True 的茅台表）",
            "side_effects": "随父项入口写原库（同上）",
            "runnable_now": False,
        },
        "validation_stage": "I3-5（随父项）",
        "gaps": [
            {
                "status": "ok",
                "item": "7 条公式 case_id/预期/容差/formula 名",
                "detail": "已从机器记录逐条取出（calculation_id 唯一）",
            },
            {
                "status": "needs_definition",
                "item": "输入字段（每公式依赖哪些冻结字段）",
                "detail": "机器记录只给 formula 名与预期值，未列输入字段清单",
                "proposed_default": "按 formula 名（revenue_growth 等）在 I3-5 重验时由公式实现声明输入字段并回链 57 字段用例",
            },
        ],
    }


def build_legacy_retrieval() -> dict:
    sys.path.insert(0, str(ROOT))
    questions = []
    import_ok = True
    try:
        from plugins.corpus.golden import GOLDEN_SET  # type: ignore
    except Exception as exc:  # noqa: BLE001
        import_ok = False
        GOLDEN_SET = ()
        questions.append({"import_error": f"{type(exc).__name__}: {exc}"})
    # 适用范围明文：U 2026-09-19 确认冻结 19 题，排除与留出冲突的 O6（来源华泰联储加息，
    # 在 guards/i3.json forbidden_roots 内）。O6 不静默删除，仅排除出本轮冻结分母；不删除 golden.py 原题。
    EXCLUDED_QIDS = {"O6"}
    for question in GOLDEN_SET:
        if getattr(question, "qid", None) in EXCLUDED_QIDS:
            continue
        questions.append(
            {
                "case_id": f"legacy_retrieval|{question.qid}",
                "category": "legacy_retrieval_golden",
                "qid": question.qid,
                "question": question.question,
                "kind": question.kind,
                "require_all": question.require_all,
                "old_anchor": [
                    {"title_contains": m.title_contains, "doc_prefix": m.doc_prefix}
                    for m in question.expects
                ],
                "new_locator_or_mapping_rule": "to_be_resolved（旧锚点→新 source_id/locator 映射）",
                "note": question.note,
            }
        )
    excluded = [
        {
            "qid": q.qid,
            "question": q.question,
            "kind": q.kind,
            "old_anchor": [
                {"title_contains": m.title_contains, "doc_prefix": m.doc_prefix} for m in q.expects
            ],
            "note": q.note,
            "exclude_reason": "来源（华泰联储加息白热化，d571f138.pdf）在 guards/i3.json forbidden_roots 内，属留出范围",
        }
        for q in GOLDEN_SET
        if getattr(q, "qid", None) in EXCLUDED_QIDS
    ]
    return {
        "categories": ["legacy_retrieval_golden"],
        "expected_asset": {"path": rel(GOLDEN), "sha256": digest(GOLDEN), "selector": "GOLDEN_SET"},
        "case_count": len(questions) if import_ok else 0,
        "cases": questions,
        "excluded_cases": excluded,
        "require_all_true_count": sum(
            1 for q in GOLDEN_SET if getattr(q, "require_all", False)
        ),
        "historical_status": "2026-09-08 语料 17 份时 Recall@5 = 100%（逐题通过口径，含 require_all）；"
                            "U 2026-09-19 确认冻结 19 题、排除留出冲突 O6",
        "scope_decision": {
            "decided_by": "U",
            "decided_at": "2026-09-19",
            "decision": "冻结 19 题，排除 O6（留出冲突）",
            "excluded": ["O6"],
            "note": "O6 来源属留出；排除出本轮冻结分母而非删除，golden.py 原题保留",
        },
        "metric_note": "旧 recall 为逐题通过口径，不转移为新索引的标准集合召回（架构 §7.1/§12.3）；"
                      "本轮口径分母=19（排除 O6）",
        "historical_record_ref": {"path": rel(GOLDEN), "sha256": digest(GOLDEN)},
        "rerun_contract": {
            "entry": "plugins/corpus/golden.py::run_golden(corpus, top_k=5)",
            "params": "top_k=5；需真实语料库连接",
            "side_effects": "只读（无写入）",
            "runnable_now": False,
            "why_not": "需 I3-1 的 i3-e2e 阶段（真实来源读取 + 隔离 PG），当前 i3 守卫 read_roots 为空",
        },
        "validation_stage": "I3-5（旧检索能力不退化，19 题口径）",
        "gaps": [
            {
                "status": "confirmed",
                "item": "适用题目范围",
                "detail": "U 2026-09-19 确认冻结 19 题、排除 O6（来源华泰联储加息，属 forbidden_roots 留出）；"
                          "分母=19",
            },
            {
                "status": "to_be_resolved",
                "item": "旧锚点→新 locator 映射",
                "detail": "旧锚点是 (title_contains, doc_prefix)；新体系是 source_id/locator。"
                          "需先定范围，再逐题映射并人工确认",
                "proposed_method": "按 title_contains 匹配 data/corpus 文件名→source_id，映射表留人工确认位",
            },
        ],
    }


def build_customer_table_12() -> dict:
    return {
        "categories": ["customer_table_12"],
        "expected_asset": {
            "path": None,
            "sha256": None,
            "selector": None,
            "note": "12 个单元格（行/列/原值/单位）预期**无机器可读工件**："
                    "历史 run 0a1dbf39… 在仓库内找不到记录文件",
        },
        "case_count": 0,
        "cases": [],
        "historical_status": "贝特利客户表冻结单元格召回 0/12 → 12/12（semantic-repair-report L15）",
        "historical_record_ref": {
            "path": rel(SEMANTIC),
            "sha256": digest(SEMANTIC),
            "note": "仅报告级记录：run_id 0a1dbf39dbfad8428b31eacdd7d5cf8a5fdef250e7df558eb55586690ed4e44f",
        },
        "rerun_contract": {
            "entry": "待构建（v3 亦标『独立复现脚本需从冻结 run 重建，登记为 I3-5 前待办』）",
            "side_effects": "未知",
            "required_environment": "需从冻结 run 重建；开发校准阶段不得读原文",
            "runnable_now": False,
        },
        "validation_stage": "I3-5（非回归）；范围冲突需先裁定",
        "gaps": [
            {
                "status": "confirmed",
                "item": "12 个单元格预期（材料）+ 冻结 run 记录",
                "detail": "U 2026-09-19 确认以报告为准、不再追要 12 格明细与 run 文件；权威依据 = semantic-repair-report（0/12→12/12 + run_id 0a1dbf39…）",
            },
            {
                "status": "confirmed",
                "item": "留出范围冲突",
                "detail": f"U 2026-09-19 确认按『历史非回归范围』处置：来源贝特利（2594e01d.pdf）已在守卫 forbidden_roots 第 1 份，"
                          "I3-5 才可重验、开发校准不读原文",
            },
        ],
    }


def build_prose_numbers_3() -> dict:
    manifest = load_json(PILOT)
    prose = next((s for s in manifest["samples"] if s.get("prose_gold")), {})
    cases = [
        {
            "case_id": f"prose3|{item.get('subject')}|{item.get('metric')}|{item.get('state')}",
            "category": "prose_numbers_3",
            "subject": item.get("subject"),
            "metric": item.get("metric"),
            "period_end": item.get("period_end"),
            "expected": item.get("value_num"),
            "unit": item.get("unit"),
            "state": item.get("state"),
            "source_anchor": prose.get("pattern"),
            "quality_gate": "质量=review（不得由模型计算）",
        }
        for item in prose.get("prose_gold") or []
    ]
    prose_report = Path("/home/administrator/FrontierAgent/data/corpus/.evidence/prose-repair/report-78a012e302a9a7fc38b79406b671a83e3402620abc30a38678ec0b036540630d.json")
    return {
        "categories": ["prose_numbers_3"],
        "expected_asset": {
            "path": rel(PILOT),
            "sha256": digest(PILOT),
            "selector": f"samples[name={prose.get('name')}].prose_gold[*]",
        },
        "authority_ref": {"path": rel(prose_report), "sha256": digest(prose_report)},
        "case_count": len(cases),
        "cases": cases,
        "historical_status": "华泰/中银正文目标数字 2/3 → 3/3（semantic-repair-report）；"
                            "非农目标 0/2 → 4 次真实调用 2/2（prose-repair-report）",
        "historical_record_ref": {
            "path": rel(SEMANTIC),
            "sha256": digest(SEMANTIC),
            "note": "spec.md L87 只给集合级数字（3/3）",
        },
        "rerun_contract": {
            "entry": "含模型调用的历史轮（prose-repair / semantic-repair）",
            "side_effects": "非零写（历史轮）",
            "required_environment": "另立预算授权",
            "runnable_now": False,
        },
        "validation_stage": "I3-5（且需预算授权）",
        "gaps": [
            {
                "status": "confirmed",
                "item": "第 3 个用例身份",
                "detail": "U 2026-09-19 确认：以 prose-repair 最终 report json 为权威身份，仅有 2 条可复现的 prose_checks"
                          "（NFP actual 16.2 / consensus 5.6）；第 3 条中银 0.38% 无可复现记录、标注『不可复现』，"
                          "不进冻结分母",
            },
            {
                "status": "confirmed",
                "item": "历史 2/2 与最终 3/3 的集合关系",
                "detail": "U 2026-09-19 确认：『4 次真实调用 2/2』指 prose report 的 2 条 prose_checks；『3/3』为 spec.md 集合级文字，"
                          "与 prose-report 的 2 条非同一集合。冻结身份取 prose-report json（2 用例）",
            },
        ],
    }


def build_macro_legacy() -> dict:
    record = load_json(MACHINE)
    macro_targets = record.get("macro_targets") or 0
    return {
        "categories": ["macro_legacy_fields_0_of_3"],
        "expected_asset": {
            "path": rel(MACHINE),
            "sha256": digest(MACHINE),
            "selector": "macro_targets / macro_comparison_rows",
            "note": "machine record: macro_targets=2、macro_comparison_rows=0；U 2026-09-19 确认以机器记录为准",
        },
        "case_count": macro_targets,
        "cases": [
            {"case_id": f"macro0of3|{f}", "field": f, "historical_status": "0/3（失败基线保留）"}
            for f in ("actual", "consensus")
        ],
        "historical_status": "0/3 单列、不伪装通过（spec.md L87）",
        "historical_cat_status": "spec.md『3/3』为集合级文字口径；机器可读层仅 macro_targets=2（actual/consensus），"
                                "previous 无独立机器身份、U 2026-09-19 确认移出冻结分母",
        "failure_reasons": "华泰『万』不可验证岗位单位；预期指标未统一；中银 basis『同比』≠冻结 YoY",
        "historical_record_ref": {"path": rel(MACHINE), "sha256": digest(MACHINE), "note": f"macro_reused_run={record.get('macro_reused_run')}"},
        "rerun_contract": {
            "entry": "无通过入口（失败基线保留）；宏观实施 M1—M6 未执行",
            "runnable_now": False,
        },
        "validation_stage": "I3-5（保留为历史失败用例，不并入开发分母）",
        "gaps": [
            {
                "status": "confirmed",
                "item": "失败用例的机器可读身份（3 字段 vs 记录里的 2 targets）",
                "detail": "U 2026-09-19 确认：以机器记录 macro_targets=2 为准（actual/consensus），previous 移出冻结分母；"
                          "spec.md『3/3』为集合级文字口径，不作机器身份",
            },
            {
                "status": "noted",
                "item": "留出关系",
                "detail": "华泰/中银两份来源在守卫 forbidden_roots 内（留出）；本条为历史失败基线，开发校准不读其原文",
            },
        ],
    }


DECISION_DOC_KIND = HERE / "decision-old-doc-kind-review-authority-20260919.json"


def build_doc_kind_review() -> dict:
    index = load_json(BASELINE_INDEX)
    entry = next(
        e for e in index["bindings"] if e["category"] == "old_doc_kind_review_export"
    )
    asset_path = ROOT / entry["asset"]
    current_ok = asset_path.is_file() and digest(asset_path) == entry.get("sha256")
    decision_ok = (
        DECISION_DOC_KIND.is_file()
        and load_json(DECISION_DOC_KIND).get("decided_by") == "U"
        and load_json(DECISION_DOC_KIND)["binding"]["asset"] == entry["asset"]
        and load_json(DECISION_DOC_KIND)["binding"]["sha256"] == entry.get("sha256")
    )
    gaps = []
    if decision_ok:
        gaps.append(
            {
                "status": "confirmed",
                "item": "权威版本确认",
                "detail": "U 已于 2026-09-19 确认该文件为旧人工审核导出的权威版本（冻结身份 + 哈希，不再扩到 88 个工件）；"
                          f"决定记录见 `{rel(DECISION_DOC_KIND)}`",
            }
        )
    else:
        gaps.append(
            {
                "status": "blocked_needs_user",
                "item": "权威版本确认（单一问题，不涉及 88 个工件）",
                "detail": f"索引已有候选：`{entry['asset']}`（sha256 {str(entry.get('sha256'))[:12]}…，"
                          f"现况一致={current_ok}）；"
                          "仓库内**未找到既有决定**指定该候选为权威版本",
                "question": f"是否确认以 `{entry['asset']}`（上述哈希）为该导出的权威版本（即冻结它、不再扩到 88 个工件）？",
            }
        )
    return {
        "categories": ["old_doc_kind_review_export"],
        "expected_asset": {
            "path": entry["asset"],
            "sha256": entry.get("sha256"),
            "sha256_matches_current": current_ok,
            "selector": "CSV 行（文档级 doc_kind 覆写候选）",
        },
        "case_count": None,
        "cases": [],
        "historical_status": (
            "旧人工审核导出权威版本已由 U 确认（2026-09-19）并冻结；"
            "review_decision 全空，属建议继承而非裁决"
            if decision_ok
            else "旧人工审核导出候选（标注：权威版本待 U 确认；.audit 共 88 个 2026-09-12 工件）"
        ),
        "historical_record_ref": {"path": rel(BASELINE_INDEX), "sha256": digest(BASELINE_INDEX)},
        "rerun_contract": {"entry": "不适用（人工审核导出，非可跑基线）", "runnable_now": False},
        "validation_stage": "I3-2 冻结身份；无需重跑",
        "gaps": gaps,
    }


def build_manifest() -> dict:
    categories = [
        build_legacy_retrieval(),
        build_doc_kind_review(),
        build_financial_57(),
        build_formula_7(),
        build_customer_table_12(),
        build_prose_numbers_3(),
        build_macro_legacy(),
    ]
    blocked = [
        {"category": c["categories"][0], **gap}
        for c in categories
        for gap in c["gaps"]
        if str(gap["status"]).startswith("blocked")
    ]
    return {
        "artifact": "i3-2-baseline-case-manifest",
        "generated_at": now(),
        "status": "frozen_r27",
        "scope_note": (
            "I3-2 只冻结『将来用哪些用例、按什么预期比较』；运行状态保持 not_run；I3-5/I3-7 才执行。"
        ),
        "holdout_policy": (
            "留出相关历史基线单列为历史非回归范围；开发校准不得读取其原文；"
            "即便以后获准重验，也不得据此声称新的独立留出评估。"
        ),
        "freeze": {"snapshot": "i0c-r27", "freeze_manifest": rel(FREEZE_MANIFEST)},
        "guard": {"path": rel(GUARD), "sha256": digest(GUARD)},
        "categories": categories,
        "blocked_items": blocked,
        "counts": {
            "categories": len(categories),
            "cases_total": sum(len(c.get("cases") or []) for c in categories),
            "blocked_items": len(blocked),
        },
    }


def write_markdown(manifest: dict) -> None:
    lines = ["# 7 类旧基线用例清单（步骤 3，草稿·未冻结）", ""]
    lines.append(f"- 生成：{manifest['generated_at']}；状态：**{manifest['status']}**")
    lines.append(f"- 用例合计 **{manifest['counts']['cases_total']}**；待你定/待补 **{manifest['counts']['blocked_items']}** 项")
    lines.append(f"- 范围原则：{manifest['scope_note']}")
    lines.append("")
    lines.append("| 类别 | 用例数 | 预期资产 | 历史状态 | 重跑入口 | 验证阶段 | 待办 |")
    lines.append("|---|---|---|---|---|---|---|")
    for category in manifest["categories"]:
        name = category["categories"][0]
        asset = category["expected_asset"]
        rerun = category["rerun_contract"]
        blocked = [g for g in category["gaps"] if str(g["status"]).startswith("blocked")]
        other = [g for g in category["gaps"] if not str(g["status"]).startswith("blocked")]
        todo = "；".join(
            f"**{g['status']}**：{g['item']}" for g in blocked + other
        )
        lines.append(
            f"| {name} | {category['case_count']} | `{str(asset.get('path')).split('/')[-1]}`"
            f"{'（缺）' if not asset.get('path') else ''} | {str(category['historical_status'])[:48]} | "
            f"{'可跑' if rerun.get('runnable_now') else '**not_run**'} | {category['validation_stage']} | {todo} |"
        )
    lines.append("")
    lines.append("## 需要你确认/补充的项（已停止执行的部分）")
    lines.append("")
    for item in manifest["blocked_items"]:
        lines.append(f"### {item['category']} / {item['item']}")
        lines.append("")
        lines.append(f"- 现状：{item.get('detail')}")
        if item.get("question"):
            lines.append(f"- **问题**：{item['question']}")
        if item.get("proposed_default"):
            lines.append(f"- 建议默认：{item['proposed_default']}")
        lines.append("")
    lines.append("## 统一记录字段")
    lines.append("")
    lines.append(
        "`case_id / category / expected_asset(path, sha256, selector) / source_id / old_anchor / "
        "new_locator_or_mapping_rule / historical_status / historical_record_ref / applicability / "
        "rerun_contract(entry, params, side_effects, required_environment) / validation_stage`"
    )
    (HERE / "baseline-case-manifest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_status_table(manifest: dict) -> None:
    lines = ["# I3-2 统一状态表（步骤 1，2026-09-19）", ""]
    lines.append("| # | 冻结项 | 状态 | 证据 | 缺口/下一步 |")
    lines.append("|---|---|---|---|---|")
    rows = [
        ("1", "source gold", "✅ 冻结（r26）", "`source-gold-frozen.jsonl` `37662c77…`；负例库 `0fc9dac3…`", "—"),
        ("2", "query gold（审批原件）", "✅ 冻结（r26）", "`query-gold-frozen.jsonl` `6f6c5a25…`；门 ready=true", "不改动（保留审批证据）"),
        ("2b", "**正式评分输入**", "✅ 已派生（待冻结 r27）", "`i3-2/query-gold-scoring-v1.jsonl` `1b018ceb…` + `i3-2/scoring-input-manifest.json`；"
         "自校验 0 错、6 条变异反例各自失败、与 P1 逐字节一致、评分器接受", "随 r27 绑定 + U 签认"),
        ("3", "阈值（policy）", "✅ 已确认（记于 P2）", "默认 5 项；`p2/policy-and-lists-confirmation.json`", "随 r27 记录；运行时显式构造 policy"),
        ("4", "关键题", "✅ 已确认（记于 P2）", "28/30；清单哈希已记", "同 I3-2-4 的语义风险保留"),
        ("5", "负例", "✅ 已确认（记于 P2）", "6 道全 critical；误报上限 0", "—"),
        ("6", "旧基线映射", "✅ 范围已确认（U 2026-09-19）", "`baseline-case-manifest.json`（19 旧检索题含 O6 排除 + 57 字段 + 7 公式已枚举）",
         "见清单 blocked_items（tout 12 格材料、第 3 条正文用例、宏观身份）"),
        ("7", "评分器冻结", "✅ 无缺口", "`plugins/corpus/scoring.py` `bf9c8b80…`（r19/r21）", "—"),
        ("8", "试验初始版本", "⚠️ 草稿（待唯一化）", "`p4/experiment-initial-version.json`；本轮已把评分输入唯一化",
         "待步骤 4：唯一 manifest + 阶段完成门"),
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("## 两处旧记录的更正（诊断文档第 29—32 行）")
    lines.append("")
    lines.append("- **更正 1**：`inventory.md/json` 里『阈值未确认、试验初始版本无产物』已落后——P2 已确认阈值/清单，"
                 "P4 已建清单草稿；本轮状态表以 P2/P4 为准。")
    lines.append("- **更正 2**：『30 题全部因缺 targets 不能评分』不准确——缺 targets 阻断的是 **24 道有答案题**；"
                 "6 道负例按 `_evidence_required(no_answer)=False` 本就不需要 targets。")
    lines.append("")
    lines.append("## 本轮新增/变更文件")
    lines.append("")
    lines.append("| 文件 | 性质 |")
    lines.append("|---|---|")
    lines.append("| `i3s2_scoring_input.py`（新） | 正式评分输入派生器 + 自校验 + 变异反例 + 唯一读入口 |")
    lines.append("| `i3-2/query-gold-scoring-v1.jsonl`（新） | 正式派生评分输入（不改审批原件） |")
    lines.append("| `i3-2/scoring-input-manifest.json`（新） | 派生 lineage 清单 |")
    lines.append("| `audits/20260919-i32-diagnosis/baseline-case-manifest.{json,md}`（新） | 步骤 3 用例清单 |")
    lines.append("| `audits/20260918-i32-remaining-inventory/inventory.{md,json}` | 更正两处旧表述 |")
    lines.append("")
    (HERE / "unified-status.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def fix_inventory() -> None:
    inventory_dir = BASE / "audits/20260918-i32-remaining-inventory"
    md = (inventory_dir / "inventory.md").read_text(encoding="utf-8")
    md = md.replace(
        "| 3 | **各类阈值** | ❌ 未冻结：`ScoringPolicy` 5 个取值目前只是**代码默认值**",
        "| 3 | **各类阈值** | ✅ 已确认（2026-09-19，U：按默认；记录见 `p2/policy-and-lists-confirmation.json`；"
        "仍待随 r27 冻结）——原表述『未冻结/仅代码默认』已更正。取值：`ScoringPolicy` 5 项默认值",
    )
    md = md.replace(
        "| 8 | **试验初始版本** | ❌ 无产物（全仓检索无\"试验初始版本/initial experiment\"痕迹） |",
        "| 8 | **试验初始版本** | ⚠️ 清单草稿已建（`p4/experiment-initial-version.json`，`draft_pending_signoff`）；"
        "唯一评分输入已派生（`i3-2/query-gold-scoring-v1.jsonl`）——原表述『无产物』已更正 |",
    )
    md = md.replace(
        "**最关键的阻塞**：`query-gold-frozen.jsonl` **30/30 题没有 `evidence_targets`**——评分器按设计"
        "对每题落 `missing_required_input:<qid>:evidence_targets_absent`，即**现在无法对任何一题产出有效指标**。",
        "**最关键的阻塞（已更正口径）**：`query-gold-frozen.jsonl` 缺 `evidence_targets`，"
        "阻断的是 **24 道有答案题**（评分器落 `missing_required_input:<qid>:evidence_targets_absent`）；"
        "6 道负例按 `_evidence_required(no_answer)=False` 本就不需要 targets。"
        "该阻塞已由 `i3-2/query-gold-scoring-v1.jsonl`（派生正式评分输入，79 必需 + 20 补充）解除，待 r27 冻结。",
    )
    (inventory_dir / "inventory.md").write_text(md, encoding="utf-8")

    data = load_json(inventory_dir / "inventory.json")
    for item in data["items"]:
        if item["id"] == "I3-2-3":
            item["status"] = "confirmed_pending_freeze"
            item["gap"] = "取值已按默认确认（p2/policy-and-lists-confirmation.json）；随 r27 冻结记录"
        if item["id"] == "I3-2-8":
            item["status"] = "draft_built_pending_signoff"
            item["gap"] = "清单草稿已建（p4/experiment-initial-version.json）；唯一评分输入已派生，待 r27 冻结"
    data["corrections"] = [
        "阈值『未确认』已更正为已确认（U 2026-09-19，按默认）。",
        "试验初始版本『无产物』已更正为清单草稿已建。",
        "缺 targets 阻断 24 道有答案题（不是 30 题）；6 道负例不需要 targets；"
        "阻塞已由 i3-2/query-gold-scoring-v1.jsonl 解除（待 r27 冻结）。",
    ]
    (inventory_dir / "inventory.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    manifest = build_manifest()
    (HERE / "baseline-case-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_markdown(manifest)
    write_status_table(manifest)
    fix_inventory()
    print(json.dumps(
        {
            "cases_total": manifest["counts"]["cases_total"],
            "per_category": {c["categories"][0]: c["case_count"] for c in manifest["categories"]},
            "blocked_items": [
                {"category": b["category"], "item": b["item"], "status": b["status"]}
                for b in manifest["blocked_items"]
            ],
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
