"""Issue 36 · items 链路记账与口径一致性核对（零调用、只读、幂等）。

对 items 链路的"多份真相"做一次机读核对：契约绑定、阈值单源、匹配模式、被禁止的
反填操作、验收链、门判据同轴性。每项检查输出 PASS / FAIL / INFO 与原文证据。

约定：
- 零模型调用、零生产库访问、不修改任何既有产物（含冻结目录）；
- ``--no-write`` 只打印不落盘；重复运行结果逐字节一致（不含墙钟时间戳）；
- 只输出"事实 + 差异"，不做阈值或判据变更（那两项须具名签认）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CLAIMS = HERE.parents[2]
REPO = CLAIMS.parents[1]
EV = CLAIMS / "evidence"

GOLD = EV / "10-quality-gold-freeze-20261008-r2" / "frozen-gold.json"
FREEZE_MANIFEST = EV / "10-quality-gold-freeze-20261008-r2" / "freeze-manifest.json"
FREEZE_STATE = EV / "10-quality-gold-freeze-20261008-r2" / "freeze-state.json"
CONTRACT = EV / "10-quality-gold-expansion-20261008-r2" / "scoring-contract.json"
VALIDATION = EV / "10-quality-gold-expansion-20261008-r2" / "validation-report.json"
GATE28 = EV / "28-items-only-quality-gate-20261010" / "r0-zero-call" / "preregistered-gate.json"
GATE32 = EV / "32-items-v6-reasoning-refreeze-20261011" / "r0-zero-call" / "preregistered-gate.json"
GATE32_MANIFEST = (
    EV / "32-items-v6-reasoning-refreeze-20261011" / "r0-zero-call" / "freeze-manifest.json"
)
GATE32_DECISION = EV / "32-items-v6-reasoning-refreeze-20261011" / "live" / "gate-decision.json"
E33 = EV / "33-items-quality-scoring-20261011" / "r0-zero-call"
SKELETON = E33 / "adjudications.json"
DRAFT = E33 / "adjudications.draft.json"
PREVIEW = E33 / "draft-preview.json"
DRAFT_SCRIPT = E33 / "build_adjudication_draft.py"
SCORER = REPO / "plugins" / "corpus" / "structured_scoring.py"

SCHEMA_VERSION = "items-chain-accounting-checks-1"
CHECK_DATE = "2026-10-12"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(
    check_id: str,
    title: str,
    status: str,
    detail: dict[str, Any],
    *,
    needs_signoff: bool = False,
) -> dict[str, Any]:
    if status not in {"PASS", "FAIL", "INFO"}:
        raise ValueError(f"{check_id}: bad status {status}")
    return {
        "check_id": check_id,
        "title": title,
        "status": status,
        "needs_signoff": needs_signoff,
        "detail": detail,
    }


def parse_scorer_thresholds() -> dict[str, Any]:
    """Read the scorer's hard-coded thresholds without importing the package."""
    text = SCORER.read_text(encoding="utf-8")
    items = re.search(
        r"RoleThreshold\(\s*Role\.MATERIAL_ITEMS,\s*Fraction\((\d+),\s*(\d+)\),\s*"
        r"Fraction\((\d+),\s*(\d+)\)\s*\)",
        text,
    )
    risk = re.search(r"risk_condition_recall_min\s*=\s*Fraction\((\d+),\s*(\d+)\)", text)
    if items is None or risk is None:
        raise ValueError("could not parse scorer thresholds")
    group = items.groups()
    return {
        "material_items_recall": f"{group[0]}/{group[1]}",
        "material_items_recall_decimal": round(int(group[0]) / int(group[1]), 4),
        "material_items_precision": f"{group[2]}/{group[3]}",
        "material_items_precision_decimal": round(int(group[2]) / int(group[3]), 4),
        "risk_condition_recall": f"{risk.group(1)}/{risk.group(2)}",
        "risk_condition_recall_decimal": round(int(risk.group(1)) / int(risk.group(2)), 4),
    }


def scorer_match_mode() -> dict[str, str]:
    text = SCORER.read_text(encoding="utf-8")
    identity = re.search(
        r"return \(self\.role, self\.source_id, self\.origin, self\.semantic_fields\)", text
    )
    equality = re.search(r"item\.identity == candidate\.identity", text)
    return {
        "identity_expression": identity.group(0) if identity else "NOT_FOUND",
        "match_predicate": equality.group(0) if equality else "NOT_FOUND",
    }


def run_checks() -> dict[str, Any]:
    gold = load(GOLD)
    manifest = load(FREEZE_MANIFEST)
    freeze_state = load(FREEZE_STATE)
    contract = load(CONTRACT)
    validation = load(VALIDATION)
    gate28 = load(GATE28)
    gate32 = load(GATE32)
    decision = load(GATE32_DECISION)
    skeleton = load(SKELETON)
    draft = load(DRAFT)
    preview = load(PREVIEW)

    contract_digest = digest(CONTRACT)
    checks: list[dict[str, Any]] = []

    # AC-1 · 金标冻结链记录的契约哈希 vs 实际签认契约
    frozen_binding = next(
        value for key, value in manifest["inputs"].items() if key.endswith("scoring-contract.json")
    )
    checks.append(
        check(
            "AC-1",
            "金标冻结链的契约绑定是否等于实际签认契约",
            "PASS" if frozen_binding == contract_digest else "FAIL",
            {
                "manifest_records": frozen_binding,
                "actual_contract": contract_digest,
                "manifest_embedded_status": freeze_state["contract_snapshot"]["status"],
                "manifest_embedded_schema": freeze_state["contract_snapshot"]["schema_version"],
                "signed_contract_schema": contract["schema_version"],
                "signed_contract_status": contract["status"],
            },
        )
    )

    # AC-2 · 门 28 记录的契约绑定 vs 实际签认契约
    gate28_binding = gate28["gold"]["scoring_contract_sha256"].removeprefix("sha256:")
    checks.append(
        check(
            "AC-2",
            "门 28 的契约绑定是否等于实际签认契约",
            "PASS" if gate28_binding == contract_digest else "FAIL",
            {
                "gate_records": gate28_binding,
                "actual_contract": contract_digest,
                "quality_requirements_status": gate28["quality_requirements_status"],
                "metric_basis": gate28["quality_requirements"]["metric_basis"],
            },
        )
    )

    # AC-3 · 阈值单源：评分器硬编码 vs 门 28 权威值
    scorer = parse_scorer_thresholds()
    authoritative = {
        "target_recall_overall_min": gate28["quality_requirements"]["target_recall_overall_min"],
        "target_recall_per_source_min": gate28["quality_requirements"][
            "target_recall_per_source_min"
        ],
        "candidate_precision_min": gate28["quality_requirements"]["candidate_precision_min"],
        "risk_condition_recall_min": scorer["risk_condition_recall_decimal"],
    }
    threshold_match = (
        scorer["material_items_recall_decimal"] == authoritative["target_recall_overall_min"]
        and scorer["material_items_precision_decimal"] == authoritative["candidate_precision_min"]
    )
    checks.append(
        check(
            "AC-3",
            "评分器阈值是否与门 28 权威阈值同源",
            "PASS" if threshold_match else "FAIL",
            {
                "scorer_hard_coded": scorer,
                "gate28_authoritative": {
                    "target_recall_overall_min": authoritative["target_recall_overall_min"],
                    "target_recall_per_source_min": authoritative["target_recall_per_source_min"],
                    "candidate_precision_min": authoritative["candidate_precision_min"],
                },
                "scorer_reads_contract_or_gate": False,
            },
            needs_signoff=True,
        )
    )

    # AC-4 · 匹配模式：评分器严格相等 vs 契约语义等价
    mode = scorer_match_mode()
    checks.append(
        check(
            "AC-4",
            "评分器匹配模式是否符合契约 matching.mode",
            "FAIL",
            {
                "scorer": mode,
                "contract_matching_mode": contract["matching"]["mode"],
                "contract_items_rule": freeze_state["contract_snapshot"]["matching"]["items"],
                "contract_projection_rule": contract["matching"]["projection"],
            },
        )
    )

    # AC-5 · 禁止操作：Stage-2 草案是否从金标反填候选字段
    draft_text = DRAFT_SCRIPT.read_text(encoding="utf-8")
    backfill = re.search(
        r'"canonical_observed_fields":\s*\{(.{0,200}?)\n\s*\}',
        draft_text,
        re.DOTALL,
    )
    backfill_source = 'gold_row["semantic_fields"]' in draft_text
    normalization_rule = freeze_state["contract_snapshot"]["matching"]["normalization"]
    checks.append(
        check(
            "AC-5",
            "Stage-2 草案是否执行了契约禁止的『从金标反填候选缺字段』",
            "FAIL" if backfill_source else "PASS",
            {
                "draft_script_fills_canonical_observed_fields_from_gold": backfill_source,
                "draft_script_excerpt": backfill.group(0) if backfill else "NOT_FOUND",
                "contract_normalization_rule": normalization_rule,
                "contract_forbids": "不从金标反填候选缺字段",
                "skeleton_entries_empty": sum(
                    1 for row in skeleton["candidates"] if not row.get("canonical_observed_fields")
                ),
                "skeleton_entries_total": len(skeleton["candidates"]),
                "draft_auto_accepted": sum(
                    1 for row in draft["candidates"] if row.get("judgement") == "accepted"
                ),
            },
        )
    )

    # AC-6 · 受污染数字：preview 的召回/关键覆盖率依赖 AC-5 的结果
    checks.append(
        check(
            "AC-6",
            "草案预览的召回类数字是否可用于门槛判断",
            "FAIL",
            {
                "draft_recall_upper_bound": preview["draft_recall_upper_bound"],
                "critical_coverage": preview["critical_coverage"],
                "risk_condition_coverage": preview["risk_condition_coverage"],
                "contaminated_by": "AC-5",
                "reason": (
                    "these counts are computed from draft entries whose canonical_observed_fields "
                    "were copied from the gold record, so they measure the copy, not the extraction"
                ),
                "still_usable": {
                    "unresolved_candidates": preview["precision_status"]["reason"],
                    "physically_lost_slots": preview["unproduced_slots"],
                },
            },
        )
    )

    # AC-7 · 验收链：冻结声明 vs 验收记录
    checks.append(
        check(
            "AC-7",
            "冻结后的验收记录是否齐备",
            "FAIL"
            if not validation.get("human_accepted_counts")
            and freeze_state.get("formal_gold_frozen")
            else "PASS",
            {
                "validation_status": validation["status"],
                "validation_human_accepted_counts": validation["human_accepted_counts"],
                "validation_formal_gold_frozen": validation["formal_gold_frozen"],
                "freeze_state_formal_gold_frozen": freeze_state["formal_gold_frozen"],
                "freeze_state_status": freeze_state["status"],
                "freeze_state_reviewer": freeze_state["reviewer"],
                "unresolved_semantic_ambiguities": validation["unresolved_semantic_ambiguities"],
            },
        )
    )

    # AC-8 · 门 32 判据与被测对象同轴性
    criteria = decision["criteria"]
    checks.append(
        check(
            "AC-8",
            "门 32 判据能否独立确认『协议修复』这一被测对象",
            "FAIL",
            {
                "verdict": decision["verdict"],
                "root_cause_status": decision["attribution"]["root_cause_status"],
                "protocol_status_valid": criteria["protocol_status_valid"],
                "criteria_unmet": decision["criteria_unmet"],
                "protocol_violation_batches": decision[
                    "protocol_violations_unsupported_jsonl_record"
                ],
            },
            needs_signoff=True,
        )
    )

    # AC-9 · 金标字节未变（与冻结清单记录一致）
    gold_digest = digest(GOLD)
    recorded_gold = next(
        value for key, value in manifest["outputs"].items() if key.endswith("frozen-gold.json")
    )
    checks.append(
        check(
            "AC-9",
            "冻结金标字节未变",
            "PASS" if gold_digest == recorded_gold else "FAIL",
            {
                "manifest_records": recorded_gold,
                "actual": gold_digest,
                "records": len(gold["records"]),
                "material_items": sum(
                    1 for row in gold["records"] if row["role"] == "material_items"
                ),
            },
        )
    )

    # AC-10 · 门 28 高风险断言清单 vs 契约 items 角色断言子集
    gate28_assertions = gate28["quality_requirements"]["high_risk_item_assertions_required"]
    items_assertions = sorted(
        key for key in contract["review_assertions"] if key.startswith("NT-I")
    )
    checks.append(
        check(
            "AC-10",
            "门 28 高风险断言清单是否等于契约 items 角色断言子集",
            "PASS" if sorted(gate28_assertions) == items_assertions else "FAIL",
            {
                "gate28_count": len(gate28_assertions),
                "contract_items_subset_count": len(items_assertions),
                "gate28_only": sorted(set(gate28_assertions) - set(items_assertions)),
                "contract_only": sorted(set(items_assertions) - set(gate28_assertions)),
                "contract_total_assertions": len(contract["review_assertions"]),
                "contract_non_items": sorted(
                    key for key in contract["review_assertions"] if not key.startswith("NT-I")
                ),
            },
        )
    )

    # AC-11 · 门 32 判定记录引用的冻结清单哈希是否可复核
    freeze_manifest_digest = digest(GATE32_MANIFEST)
    decision_manifest = decision["freeze_manifest_sha256"].removeprefix("sha256:")
    checks.append(
        check(
            "AC-11",
            "门 32 判定记录引用的冻结清单哈希是否可复核",
            "PASS" if decision_manifest == freeze_manifest_digest else "FAIL",
            {
                "decision_freeze_manifest_sha256": decision["freeze_manifest_sha256"],
                "actual_freeze_manifest": f"sha256:{freeze_manifest_digest}",
                "decision_gate_sha256_declared_only": decision["gate_sha256"],
                "preregistered_gate_has_own_hash_field": "gate_sha256" in gate32,
            },
        )
    )

    counts = {
        "PASS": sum(1 for item in checks if item["status"] == "PASS"),
        "FAIL": sum(1 for item in checks if item["status"] == "FAIL"),
        "INFO": sum(1 for item in checks if item["status"] == "INFO"),
        "needs_signoff": sum(1 for item in checks if item["needs_signoff"]),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "created_on": CHECK_DATE,
        "scope": "items chain bookkeeping and accounting consistency (zero-call, read-only)",
        "inputs": {
            "frozen_gold": f"sha256:{digest(GOLD)}",
            "scoring_contract": f"sha256:{contract_digest}",
            "freeze_manifest": f"sha256:{digest(FREEZE_MANIFEST)}",
            "freeze_state": f"sha256:{digest(FREEZE_STATE)}",
            "validation_report": f"sha256:{digest(VALIDATION)}",
            "gate28": f"sha256:{digest(GATE28)}",
            "gate32": f"sha256:{digest(GATE32)}",
            "gate32_freeze_manifest": f"sha256:{digest(GATE32_MANIFEST)}",
            "gate32_decision": f"sha256:{digest(GATE32_DECISION)}",
            "skeleton": f"sha256:{digest(SKELETON)}",
            "draft": f"sha256:{digest(DRAFT)}",
            "preview": f"sha256:{digest(PREVIEW)}",
            "draft_script": f"sha256:{digest(DRAFT_SCRIPT)}",
            "scorer": f"sha256:{digest(SCORER)}",
        },
        "counts": counts,
        "checks": checks,
        "model_requests": 0,
        "production_database_access": 0,
        "writes_evidence": False,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# items 链路记账与口径一致性核对（Issue 36）",
        "",
        f"- 日期：{report['created_on']}",
        "- 零模型调用、零生产库访问、未修改任何既有产物",
        f"- 汇总：PASS {report['counts']['PASS']} / FAIL {report['counts']['FAIL']} / "
        f"INFO {report['counts']['INFO']}；其中需具名签认 {report['counts']['needs_signoff']} 项",
        "",
        "## 输入哈希",
        "",
        "| 产物 | sha256 |",
        "| --- | --- |",
    ]
    for key, value in report["inputs"].items():
        lines.append(f"| `{key}` | `{value}` |")
    lines.extend(["", "## 检查明细", ""])
    for item in report["checks"]:
        mark = {"PASS": "PASS", "FAIL": "FAIL", "INFO": "INFO"}[item["status"]]
        signoff = "（需签认）" if item["needs_signoff"] else ""
        lines.append(f"### {item['check_id']} · {item['title']} — {mark}{signoff}")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(item["detail"], ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true", help="print only, write nothing")
    args = parser.parse_args()

    report = run_checks()
    if not args.no_write:
        (HERE / "accounting-checks.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (HERE / "accounting-checks.md").write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "counts": report["counts"],
                "statuses": {item["check_id"]: item["status"] for item in report["checks"]},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
