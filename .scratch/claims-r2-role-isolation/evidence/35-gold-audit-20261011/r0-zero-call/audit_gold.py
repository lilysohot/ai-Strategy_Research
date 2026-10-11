"""Zero-call audit of the signed non-table gold set (issue 35).

Read-only. Checks the frozen gold's own bookkeeping (hashes, statuses, counts), verifies
every material_items record against the signed source text, compares it with the contract
field set, locates it against the candidate pool (including the lost packet), and lists the
files a human reviewer needs, each with its sha256.

Writes gold-audit.json and gold-audit.md.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E35 = HERE.parent
CLAIMS = E35.parent.parent
E10 = CLAIMS / "evidence"
FREEZE = E10 / "10-quality-gold-freeze-20261008-r2"
REVIEW = E10 / "10-quality-gold-expansion-20261008-r2"
E32 = CLAIMS / "evidence" / "32-items-v6-reasoning-refreeze-20261011"
WORKBENCH = (
    CLAIMS / "evidence" / "33-items-quality-scoring-20261011" / "r0-zero-call" / "workbench.json"
)
RESIDUAL = E32 / "live" / "residual-attribution.json"
SOURCES = ("industrial-fulian-md", "optical-module-docx")
LOST_UNIT_LOCATORS = {"char:5246-5537"}

from plugins.corpus.structured.ledger import BatchPlan  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def bare(value: str) -> str:
    return value.removeprefix("sha256:")


def main() -> None:
    frozen = read_json(FREEZE / "frozen-gold.json")
    manifest = read_json(FREEZE / "freeze-manifest.json")
    state = read_json(FREEZE / "freeze-state.json")
    validation = read_json(REVIEW / "validation-report.json")
    contract = read_json(REVIEW / "scoring-contract.json")
    workbench = read_json(WORKBENCH)
    residual = read_json(RESIDUAL)
    gold_items = [row for row in frozen["records"] if row["role"] == "material_items"]

    # ------------------------------------------------------------ bookkeeping
    bound_contract = frozen.get("scoring_contract_sha256")
    actual_contract = bare(digest(REVIEW / "scoring-contract.json"))
    input_hash_rows = []
    for name, recorded in (manifest.get("inputs") or {}).items():
        path = CLAIMS.parent.parent / name
        input_hash_rows.append(
            {
                "recorded_path": name,
                "exists": path.exists(),
                "recorded": f"sha256:{recorded}",
                "actual": digest(path) if path.exists() else None,
                "match": path.exists() and bare(digest(path)) == recorded,
            }
        )

    bookkeeping = {
        "frozen_gold": {
            "schema_version": frozen.get("schema_version"),
            "status": frozen.get("status"),
            "formal_gold_frozen": frozen.get("formal_gold_frozen"),
            "frozen_on": frozen.get("frozen_on"),
            "reviewer": frozen.get("reviewer"),
            "adjudicator": frozen.get("adjudicator"),
            "evaluation_scope": frozen.get("evaluation_scope"),
            "table_content_included": frozen.get("table_content_included"),
            "holdout_accessed": frozen.get("holdout_accessed"),
            "candidate_outputs_observed_before_freeze": frozen.get(
                "candidate_outputs_observed_before_freeze"
            ),
            "counts": frozen.get("counts"),
        },
        "freeze_state": {
            "status": state.get("status"),
            "quality_gate_passed": state.get("quality_gate_passed"),
            "candidate_execution_authorized": state.get("candidate_execution_authorized"),
            "authorization_provenance": state.get("authorization_provenance"),
        },
        "freeze_manifest": {
            "status": manifest.get("status"),
            "quality_gate_passed": manifest.get("quality_gate_passed"),
            "input_hash_checks": input_hash_rows,
        },
        "validation_report": {
            "status": validation.get("status"),
            "errors": validation.get("errors"),
            "human_accepted_counts": validation.get("human_accepted_counts"),
            "risk_record_counts_by_role": validation.get("risk_record_counts_by_role"),
            "mechanical_checks_prove_semantic_correctness": validation.get(
                "mechanical_checks_prove_semantic_correctness"
            ),
            "unresolved_semantic_ambiguities": validation.get(
                "unresolved_semantic_ambiguities"
            ),
        },
        "contract_binding": {
            "recorded_in_frozen_gold": f"sha256:{bound_contract}" if bound_contract else None,
            "actual_scoring_contract": f"sha256:{actual_contract}",
            "contract_schema_now": contract.get("schema_version"),
            "match": bound_contract == actual_contract,
            "note": (
                "frozen-gold still binds the v2 contract digest while the signed contract file is "
                "now v3; the re-binding was recorded in gate 28 but not written back into the gold"
            ),
        },
    }

    # ------------------------------------------------------------ sources text
    unit_text: dict[str, str] = {}
    unit_id_by_locator: dict[str, str] = {}
    unit_meta: dict[str, dict[str, Any]] = {}
    scoped_locators: dict[str, set[str]] = {}
    for slug in SOURCES:
        plan = BatchPlan.model_validate_json(
            (E32 / "r0-zero-call" / f"plan-treatment-{slug}.json").read_text(encoding="utf-8")
        )
        for unit in plan.snapshot.units:
            unit_text[unit.locator] = unit.text
            unit_id_by_locator[unit.locator] = unit.unit_id
            unit_meta[unit.locator] = dict(unit.metadata or {})
        scoped_locators[slug] = {unit.locator for unit in plan.snapshot.units}

    contract_fields = set(contract["role_required_fields"]["material_items"])
    candidates = workbench["candidates"]
    quotes_by_source: dict[str, list[str]] = {}
    for candidate in candidates:
        quotes_by_source.setdefault(candidate["source_id"], []).append(
            candidate.get("evidence_quote") or ""
        )

    rows: list[dict[str, Any]] = []
    for row in gold_items:
        fields = row.get("semantic_fields") or {}
        evidence = row.get("evidence") or []
        locators = [item.get("locator") for item in evidence if item.get("locator")]
        checks: dict[str, Any] = {
            "record_id": row["record_id"],
            "source_id": row["source_id"],
            "review_status": row.get("review_status"),
            "adjudication": row.get("adjudication"),
            "critical": row.get("critical"),
            "risk_or_condition": row.get("risk_or_condition"),
            "statement_role": fields.get("statement_role"),
            "locators": locators,
            "in_scoped_snapshot": all(locator in unit_text for locator in locators) if locators else False,
            "touches_lost_unit": bool(set(locators) & LOST_UNIT_LOCATORS),
            "contract_fields_missing": sorted(contract_fields - set(fields)),
            "condition_role_has_condition": (
                fields.get("statement_role") != "condition" or bool(fields.get("condition"))
            ),
        }
        quote_checks = []
        for item in evidence:
            locator = item.get("locator")
            start, end = item.get("start"), item.get("end")
            text = unit_text.get(locator)
            if text is None or start is None or end is None:
                quote_checks.append({"locator": locator, "verbatim": None, "reason": "no_unit_text"})
                continue
            span = text[int(start) : int(end)]
            recorded = item.get("quote") or row.get("quote") or ""
            quote_checks.append(
                {
                    "locator": locator,
                    "verbatim": span == recorded,
                    "recorded_quote": recorded[:60],
                    "resolved_span": span[:60],
                    "length_recorded": len(recorded),
                    "length_resolved": len(span),
                }
            )
        checks["quote_checks"] = quote_checks
        checks["quote_verbatim_ok"] = bool(quote_checks) and all(
            item["verbatim"] is True for item in quote_checks
        )
        hard_hits = [
            text
            for text in quotes_by_source.get(row["source_id"], [])
            if (row.get("quote") or "") and (row["quote"] in text or text in row["quote"])
        ]
        checks["candidate_exact_quote_hits"] = len(hard_hits)
        rows.append(checks)

    summary = {
        "records": len(rows),
        "review_status": dict(Counter(row["review_status"] for row in rows)),
        "adjudication_present": sum(1 for row in rows if row.get("adjudication")),
        "critical": sum(1 for row in rows if row["critical"]),
        "risk_or_condition": sum(1 for row in rows if row["risk_or_condition"]),
        "condition_role": sum(1 for row in rows if row["statement_role"] == "condition"),
        "in_scoped_snapshot": sum(1 for row in rows if row["in_scoped_snapshot"]),
        "touching_lost_unit": sum(1 for row in rows if row["touches_lost_unit"]),
        "quote_verbatim_ok": sum(1 for row in rows if row["quote_verbatim_ok"]),
        "quote_not_verbatim": [
            row["record_id"] for row in rows if not row["quote_verbatim_ok"]
        ],
        "records_missing_contract_fields": sum(
            1 for row in rows if row["contract_fields_missing"]
        ),
        "records_missing_contract_field_names": sorted(
            {name for row in rows for name in row["contract_fields_missing"]}
        ),
        "condition_role_without_condition": [
            row["record_id"]
            for row in rows
            if not row["condition_role_has_condition"]
        ],
        "records_with_exact_candidate_quote": sum(
            1 for row in rows if row["candidate_exact_quote_hits"]
        ),
    }

    groups = []
    for group in frozen["condition_groups"]:
        locator = (group.get("evidence") or {}).get("locator")
        groups.append(
            {
                "group_id": group["group_id"],
                "target": group["target_record_id"],
                "conditions": list(group["condition_record_ids"]),
                "locator": locator,
                "touches_lost_unit": locator in LOST_UNIT_LOCATORS,
                "members_critical": [
                    row["record_id"]
                    for row in rows
                    if row["record_id"] in {group["target_record_id"], *group["condition_record_ids"]}
                    and row["critical"]
                ],
            }
        )

    files = [
        {
            "path": str((FREEZE / "frozen-gold.json").relative_to(CLAIMS.parent.parent)),
            "sha256": digest(FREEZE / "frozen-gold.json"),
            "role": "48 条非表格金标（material_items 切片在本审计中核验）",
        },
        {
            "path": str((FREEZE / "freeze-state.json").relative_to(CLAIMS.parent.parent)),
            "sha256": digest(FREEZE / "freeze-state.json"),
            "role": "冻结状态与授权来源",
        },
        {
            "path": str((FREEZE / "freeze-manifest.json").relative_to(CLAIMS.parent.parent)),
            "sha256": digest(FREEZE / "freeze-manifest.json"),
            "role": "冻结清单与输入哈希（含 quality_gate_passed 标记）",
        },
        {
            "path": str((FREEZE / "freeze_signed_gold.py").relative_to(CLAIMS.parent.parent)),
            "sha256": digest(FREEZE / "freeze_signed_gold.py"),
            "role": "冻结脚本（生成 frozen-gold 的代码）",
        },
        {
            "path": str((REVIEW / "gold-review-candidates.json").relative_to(CLAIMS.parent.parent)),
            "sha256": digest(REVIEW / "gold-review-candidates.json"),
            "role": "人工评审草稿（含逐条 review_status/adjudication 的原始录入）",
        },
        {
            "path": str((REVIEW / "gold-review.md").relative_to(CLAIMS.parent.parent)),
            "sha256": digest(REVIEW / "gold-review.md"),
            "role": "由 JSON 生成的评审可读稿（1616 行，可逐条对照）",
        },
        {
            "path": str((REVIEW / "validation-report.json").relative_to(CLAIMS.parent.parent)),
            "sha256": digest(REVIEW / "validation-report.json"),
            "role": "机械校验报告（human_accepted_counts 现状见审计结论）",
        },
        {
            "path": str((REVIEW / "draft-manifest.json").relative_to(CLAIMS.parent.parent)),
            "sha256": digest(REVIEW / "draft-manifest.json"),
            "role": "草稿清单与输入哈希",
        },
        {
            "path": str((REVIEW / "scoring-contract.json").relative_to(CLAIMS.parent.parent)),
            "sha256": digest(REVIEW / "scoring-contract.json"),
            "role": "评分契约 v3（当前签认版本）",
        },
        {
            "path": str((REVIEW / "review_pack.py").relative_to(CLAIMS.parent.parent)),
            "sha256": digest(REVIEW / "review_pack.py"),
            "role": "评审包生成脚本",
        },
        {
            "path": str((E10 / "10-quality-gold-expansion-20261008-r1" / "source-prose-units.json").relative_to(CLAIMS.parent.parent)),
            "sha256": digest(E10 / "10-quality-gold-expansion-20261008-r1" / "source-prose-units.json"),
            "role": "候选输入范围的源单元导出（locator/文本哈希）",
        },
        {
            "path": "data/corpus/工业富联_投委会决策报告_20260829.md",
            "sha256": digest(CLAIMS.parent.parent / "data/corpus/工业富联_投委会决策报告_20260829.md")
            if (CLAIMS.parent.parent / "data/corpus/工业富联_投委会决策报告_20260829.md").exists()
            else None,
            "role": "md 源文件（人工回取原文用）",
        },
    ]

    audit = {
        "schema_version": "non-table-gold-audit-1",
        "created_on": "2026-10-11",
        "scope": "material_items 切片（48 条）；claims/relations 不在本次核查范围",
        "bookkeeping": bookkeeping,
        "summary": summary,
        "condition_groups": groups,
        "records": rows,
        "lost_packet": {
            "unit_locator": sorted(LOST_UNIT_LOCATORS),
            "gold_records_touching_it": [
                row["record_id"] for row in rows if row["touches_lost_unit"]
            ],
            "unproduced_slots": residual["totals"],
            "collateral_items": residual["conclusion"]["collateral_item_loss"],
        },
        "files_for_review": files,
        "model_requests": 0,
        "production_database_access": 0,
    }
    (HERE / "gold-audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    md = [
        "# 金标集回溯核查（issue 35 · material_items 48 条）",
        "",
        "## 一、记账核验",
        f"- frozen-gold：status={bookkeeping['frozen_gold']['status']}、frozen_on="
        f"{bookkeeping['frozen_gold']['frozen_on']}、reviewer/adjudicator="
        f"{bookkeeping['frozen_gold']['reviewer']}/{bookkeeping['frozen_gold']['adjudicator']}",
        f"- freeze-state：quality_gate_passed={bookkeeping['freeze_state']['quality_gate_passed']}、"
        f"candidate_execution_authorized={bookkeeping['freeze_state']['candidate_execution_authorized']}",
        f"- freeze-manifest：quality_gate_passed={bookkeeping['freeze_manifest']['quality_gate_passed']}，"
        f"输入哈希逐项核验 {sum(1 for r in input_hash_rows if r['match'])}/{len(input_hash_rows)} 匹配",
        f"- validation-report：status={bookkeeping['validation_report']['status']}、"
        f"errors={bookkeeping['validation_report']['errors']}、"
        f"human_accepted_counts={bookkeeping['validation_report']['human_accepted_counts']}",
        f"- 契约绑定：记录 `{bookkeeping['contract_binding']['recorded_in_frozen_gold']}` vs 实际 "
        f"`{bookkeeping['contract_binding']['actual_scoring_contract']}`（match="
        f"{bookkeeping['contract_binding']['match']}）",
        "",
        "## 二、48 条逐项结论摘要",
        f"- review_status 分布：{summary['review_status']}；adjudication 非空：{summary['adjudication_present']}/48",
        f"- critical {summary['critical']}、risk_or_condition {summary['risk_or_condition']}、"
        f"condition 角色 {summary['condition_role']}",
        f"- 原文可逐字回取（locator+start/end 与 quote 完全一致）：{summary['quote_verbatim_ok']}/48",
        f"  不可逐字回取的记录：{summary['quote_not_verbatim']}",
        f"- 落在候选 scope 内：{summary['in_scoped_snapshot']}/48；触碰丢失 unit：{summary['touching_lost_unit']}",
        f"- 缺契约必需字段的记录：{summary['records_missing_contract_fields']}/48，"
        f"缺失字段={summary['records_missing_contract_field_names']}",
        f"- condition 角色但无 condition 字段：{summary['condition_role_without_condition']}",
        f"- 候选侧逐字命中（quote 与某候选 evidence_quote 互相包含）："
        f"{summary['records_with_exact_candidate_quote']}/48",
        "",
        "## 三、条件组与丢失包",
    ]
    for group in groups:
        md.append(
            f"- {group['group_id']}：{group['conditions']} → {group['target']}；"
            f"locator={group['locator']}；触碰丢失 unit={group['touches_lost_unit']}；"
            f"其中 critical={group['members_critical']}"
        )
    md.extend(
        [
            "",
            "## 四、供人工核查的文件清单（含 sha256）",
        ]
    )
    for item in files:
        md.append(f"- `{item['path']}` — {item['role']}")
        md.append(f"  - sha256：{item['sha256']}")
    md.extend(
        [
            "",
            "## 五、本审计的产物",
            "- `gold-audit.json`（逐条明细，含每条 quote 的 resolved span 对照）",
            "- `gold-audit.md`（本文件）",
        ]
    )
    (HERE / "gold-audit.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "bookkeeping": {
                    "frozen_status": bookkeeping["frozen_gold"]["status"],
                    "freeze_quality_gate_passed": bookkeeping["freeze_state"]["quality_gate_passed"],
                    "human_accepted_counts": bookkeeping["validation_report"]["human_accepted_counts"],
                    "contract_binding_match": bookkeeping["contract_binding"]["match"],
                    "input_hash_matches": f"{sum(1 for r in input_hash_rows if r['match'])}/{len(input_hash_rows)}",
                },
                "summary": summary,
                "condition_groups": groups,
                "files_listed": len(files),
                "model_requests": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
