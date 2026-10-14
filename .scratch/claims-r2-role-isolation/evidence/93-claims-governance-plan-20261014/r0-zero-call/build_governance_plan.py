"""Build the claims governance plan (93 号): carrier meta-rules, correction registration, R1-R4.

Read-only with respect to every frozen artifact. This script never edits, rebases or re-signs
83/84/88/90/91/92 号 or any signed contract/gate/adjudication byte; it only *registers*.

Design rule of this revision (the fix for the "same concept returns every round" loop):

  * 判据的「取值」签了、判据的「载体」没签 -- so the three remaining cells (M1/M2/M3) are
    carrier questions, not value questions, and are left as ``pending_human_decision`` with
    ``value: null`` and every option's measured consequence attached;
  * 治理只阻断「断言」，不阻断「动作」 -- R1/R2;
  * 未裁轴的默认行为 = 拒绝正面断言（fail-closed），而不是强取最严值去阻断执行;
  * 例外登记（correction）只能豁免「已登记且规则已生效」的产物；规则未签认时，
    校验器只检出、不阻塞（否则等于拿未签的规则去卡已签的产物）。

Usage:
    python build_governance_plan.py [--no-write] [--force]

--no-write prints the canonical summary without touching the filesystem.
Existing outputs are refused unless --force is given.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
PLAN_ON = "2026-10-14"

GOLD = ROOT / "evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json"
POOL = (
    ROOT
    / "evidence/17-structured-extraction-convergence-closure-20261009"
    / "p1r5-claims-adjudication-v2/candidate-adjudications.signed.json"
)
CONTRACT_V43 = ROOT / "evidence/75-r2-signed-20261013/r0-zero-call/scoring-contract-v4.3.json"
ITEMS_GATE_V3 = ROOT / "evidence/75-r2-signed-20261013/r0-zero-call/gate-v3.json"
CONTRACT_V44 = (
    ROOT / "evidence/88-claims-contract-v44-signed-20261014/r0-zero-call/scoring-contract-v4.4.json"
)
GATE_V3 = ROOT / "evidence/91-claims-gate-v3-signed-20261014/r0-zero-call/claims-gate-v3.json"
SCOPE_REGISTRATION = (
    ROOT
    / "evidence/92-claims-scope-registration-20261014/r0-zero-call/claims-scope-registration.json"
)

INPUTS = {
    "frozen_gold": GOLD,
    "p1r5_candidate_adjudications_signed": POOL,
    "scoring_contract_v4.3": CONTRACT_V43,
    "items_gate_v3_signed_reference": ITEMS_GATE_V3,
    "signed_scoring_contract_v4.4": CONTRACT_V44,
    "claims_gate_v3_signed": GATE_V3,
    "claims_scope_registration": SCOPE_REGISTRATION,
}

# The 11 claims required fields live in the signed contract; the vocabulary gate is here so the
# plan can state, with a file:line anchor, why C4's cite-side axes are currently inexpressible.
USABLE_FOR_VOCABULARY_SITE = "plugins/corpus/structured/store.py:332"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_of(row: dict[str, Any]) -> str:
    doc = row["original_candidate"]["claim"].get("doc_id") or "unknown"
    return doc.split(":", 1)[-1][:12]


def measure_accepted(pool: dict[str, Any]) -> dict[str, Any]:
    """Independent recomputation of the accepted-record counts the gate's blockers quote.

    The gate's ``accepted_records_total:20<40`` / ``...:10<20`` strings are the only place the
    counts appear, so they are recomputed here from the frozen pool instead of being copied.
    """
    matched = [r for r in pool["adjudications"] if r.get("judgement") == "matched"]
    per_source: dict[str, int] = {}
    for row in matched:
        per_source[_source_of(row)] = per_source.get(_source_of(row), 0) + 1
    return {"accepted_records_total": len(matched), "accepted_records_per_source": per_source}


def build_plan() -> dict[str, Any]:
    gate = load(GATE_V3)
    contract = load(CONTRACT_V44)
    pool = load(POOL)
    gold = load(GOLD)
    accepted = measure_accepted(pool)
    targets = [r for r in gold["records"] if r["role"] == "claims"]

    gate_sha = sha256(GATE_V3)
    variant_a = gate["measured_run"]["variants"]["a_items_40_20"]
    release = gate["thresholds"]["release_line"]
    use_grading = contract["claims_use_grading"]
    thresholds_block = contract["claims_thresholds"]
    unfrozen = list(gate.get("unfrozen_axes") or [])

    per_source = accepted["accepted_records_per_source"]
    scaled_total = 0.85 * len(targets)
    scaled_per_source = {name: 0.85 * count for name, count in sorted(per_source.items())}

    plan: dict[str, Any] = {
        "schema_version": "claims-governance-plan-1",
        "status": "draft_pending_human_signature",
        "id": "93-claims-governance-plan-20261014",
        "role": "claims",
        "created_on": PLAN_ON,
        "zero_model_calls": True,
        "purpose": (
            "把「判据的载体」从判据的取值里拆出来单独裁：三格（M1/M2/M3）全部是载体问题，"
            "裁完这三格，同一条线上不会再出现同一概念以新名字复活。"
        ),
        "problem_statement": {
            "statement": (
                "门/契约把判据的「取值」签了，却没有签判据的「载体」；于是每遇到一个新数值或"
                "新词，就必然回到『这个数字/这个词归谁』这同一个问题。"
            ),
            "anchors": [
                {
                    "site": "gate v3 unfrozen_axes",
                    "evidence": f"{unfrozen}",
                    "reading": "判据被「留白」，不是「未定」：三个轴的载体没有归属声明",
                },
                {
                    "site": "gate v3 verdict.release_line.precondition",
                    "evidence": gate["verdict"]["release_line"].get("precondition"),
                    "reading": "已签的 PASS 以未裁轴（D-1）为前提 ⇒ 用未定的判据撑已签的结论",
                },
                {
                    "site": "contract v4.4 claims_thresholds.target_line.basis",
                    "evidence": thresholds_block["target_line"]["basis"],
                    "reading": (
                        "写着「与契约六项逐字恒等」，枚举却只列 3 个比例 + unresolved "
                        "⇒ 字面恒等就得取 items 的 40/20，而 claims 池只有 20 条"
                    ),
                },
                {
                    "site": "contract v4.4 claims_use_grading.axes",
                    "evidence": sorted(use_grading["axes"].keys()),
                    "reading": (
                        f"签的是 cite 侧轴名；下游 {USABLE_FOR_VOCABULARY_SITE} 的 usable_for "
                        "只允许 {cite, compare, calculate} ⇒ 签下的规则无处安放"
                    ),
                },
            ],
        },
        "rules": RULES,
        "registration_template": REGISTRATION_TEMPLATE,
        "cells": [
            {
                "id": "M1",
                "title": "数值阈值的角色归属：比例恒等继承，条数下限如何派生",
                "question": (
                    "claims 的 accepted_records_total_min / accepted_records_per_source_min "
                    "取哪一条派生规则？（这是载体问题：两个数字该挂在角色规模上，还是原样挂在 "
                    "items 的绝对条数上）"
                ),
                "applies_to": ["accepted_records_total_min", "accepted_records_per_source_min"],
                "kind": "carrier_meta_rule",
                "status": "pending_human_decision",
                "value": None,
                "signature_did_not_decide": True,
                "owner": "U",
                "decide_by": None,
                "pending_caliber": True,
                "recompute_on_fill": [
                    "claims-gate-v3.verdict.release_line.verdict",
                    "claims-gate-v3.measured_run.variants.*.rate_gate_passed",
                    "claims-gate-v3.measured_run.variants.*.rate_blockers",
                ],
                "reopen_history": [
                    {"round": "OPEN-A（83 号）", "form": "40/20 直接平移是否可接受"},
                    {"round": "C5（契约 v4.4）", "form": "目标线「与 items 契约六项逐字恒等」"},
                    {"round": "D-1（91 号）", "form": "accepted 下限取 a/b/c 哪套"},
                ],
                "measured_common": {
                    "accepted_records_total": accepted["accepted_records_total"],
                    "accepted_records_per_source": per_source,
                    "gold_targets_total": len(targets),
                    "target_line_candidate_precision_min": thresholds_block["target_line"][
                        "candidate_precision_min"
                    ],
                    "note": (
                        "两个 accepted 计数由冻结池独立复算（matched 去重计数），与门 blocker 文本"
                        f"（{variant_a['rate_blockers'][1]} / {variant_a['rate_blockers'][2][:64]}…）同源"
                    ),
                },
                "options": [
                    {
                        "key": "a_transplant",
                        "rule": "平移 items 门 v3 的绝对条数（40 / 20），不按角色规模缩放",
                        "derived": {
                            "accepted_records_total_min": 40,
                            "accepted_records_per_source_min": 20,
                        },
                        "measured": {
                            "target_line": "FAIL（与下限无关，被精度 0.6296 < 0.80 卡住，三变体一致）",
                            "release_line": "FAIL：额外 3 项 accepted 下限阻断",
                            "blockers": variant_a["rate_blockers"],
                        },
                        "reading": "算术上不可满足（池 20 条 < 40；每源 10 < 20）⇒ 等价于永久 FAIL",
                    },
                    {
                        "key": "b_scaled_floor",
                        "rule": (
                            "比例类阈值角色间恒等继承；条数下限按角色目标规模派生，向下取整："
                            "total = floor(0.85 × 20) = 17；per_source = floor(0.85 × 10) = 8"
                        ),
                        "derived": {
                            "accepted_records_total_min": 17,
                            "accepted_records_per_source_min": 8,
                        },
                        "measured": {
                            "target_line": "FAIL（同上，唯一卡点是精度）",
                            "release_line": "PASS（前提：该轴已裁；实测 20 ≥ 17、10 ≥ 8）",
                            "blockers": gate["measured_run"]["variants"]["b_scaled_17_8"][
                                "rate_blockers"
                            ],
                        },
                        "reading": "与已签 C5「六项逐字恒等」的字面冲突最小，且把比例与条数分开归属",
                    },
                    {
                        "key": "b_scaled_ceil",
                        "rule": (
                            "同 b_scaled_floor，但向上取整：total = ceil(0.85 × 20) = 17；"
                            "per_source = ceil(0.85 × 10) = 9"
                        ),
                        "derived": {
                            "accepted_records_total_min": 17,
                            "accepted_records_per_source_min": 9,
                        },
                        "measured": {
                            "target_line": "FAIL（同上）",
                            "release_line": "PASS（实测 10 ≥ 9）",
                            "blockers": gate["measured_run"]["variants"]["b_scaled_17_8"][
                                "rate_blockers"
                            ],
                        },
                        "reading": "更严；在本池上与向下取整同结论，但取整方向对将来新角色是有载体的",
                    },
                    {
                        "key": "c_diagnostic",
                        "rule": "不设数值下限，仅作诊断计数（accepted 只报告不 gating，须契约修订）",
                        "derived": None,
                        "measured": {
                            "target_line": "FAIL（同上）",
                            "release_line": "PASS（无 accepted 阻断项）",
                            "blockers": gate["measured_run"]["variants"]["c_diagnostic_min"][
                                "rate_blockers"
                            ],
                        },
                        "reading": "最干净，但要改契约语义（该轴从 gating 降为 diagnostic），多一轮修订",
                    },
                ],
                "load_bearing_note": (
                    "取整方向（floor 8 / ceil 9）在本池上不影响判定（10 ≥ 9），因此它现在不是"
                    "载重项；但若不定，换角色时它会成为新的未定轴。必须在同一格内把取整方向定死。"
                ),
                "scaling_basis": {
                    "formula_numerator": 0.85,
                    "formula_numerator_basis": "已签目标线 target_recall_overall_min = 0.85",
                    "scaled_total": scaled_total,
                    "scaled_per_source": scaled_per_source,
                },
            },
            {
                "id": "M2",
                "title": "分源精度轴是否存在",
                "question": ("放行线的分源轴（0.55）在契约六项里没有对应字段，是否新增该轴？"),
                "applies_to": ["per_source_precision_axis"],
                "kind": "carrier_meta_rule",
                "status": "pending_human_decision",
                "value": None,
                "signature_did_not_decide": True,
                "owner": "U",
                "decide_by": None,
                "pending_caliber": True,
                "recompute_on_fill": [
                    "claims-gate-v3.verdict.release_line.verdict",
                    "claims-gate-v3.thresholds.release_line.per_source_axis_status",
                ],
                "reopen_history": [
                    {"round": "C5（契约 v4.4）", "form": "放行线新增分源 0.55"},
                    {"round": "D-2（91 号）", "form": "该轴在契约六项里没有载体"},
                ],
                "measured_common": {
                    "release_line_per_source_precision_min": release["per_source_precision_min"],
                    "measured_per_source_precision": release["measured_per_source_precision"],
                    "reading": "两源实测均 ≥ 0.55 ⇒ 若新增该轴，放行线结论不变（仍 PASS）",
                },
                "options": [
                    {
                        "key": "exists",
                        "rule": "新增契约字段（分源精度下限）+ 评分器读取该字段；该轴进入 gating",
                        "derived": {"per_source_precision_min": 0.55},
                        "measured": {"release_line": "PASS（0.5893 / 0.7200 均 ≥ 0.55）"},
                        "cost": (
                            "契约 schema 加字段；ContractGateRequirements 的字段元组被 P03 绑定校验器"
                            "逐字钉住 ⇒ 须同轮出新绑定记录（取代声明）"
                        ),
                    },
                    {
                        "key": "report_only",
                        "rule": "不新增；分源精度永远只报告，不参与 gating",
                        "derived": None,
                        "measured": {"release_line": "PASS（与现状一致）"},
                        "cost": "0；但该轴的退化不会被自动检出（只能靠人读报告）",
                    },
                ],
            },
            {
                "id": "M3",
                "title": "C4 的 cite 侧轴在当前下游词表下如何落地",
                "question": (
                    "C4 已签的 cite 侧轴（cite_attributed / cite_stance）在 "
                    f"{USABLE_FOR_VOCABULARY_SITE} 的 usable_for 词表下无法表达，如何处置？"
                ),
                "applies_to": [
                    "claims_use_grading.axes.attribution",
                    "claims_use_grading.axes.perspective",
                    "claims_use_grading.axes.source_stance",
                ],
                "kind": "carrier_meta_rule",
                "status": "pending_human_decision",
                "value": None,
                "signature_did_not_decide": True,
                "owner": "U",
                "decide_by": None,
                "pending_caliber": True,
                "recompute_on_fill": [
                    "usable_for 词表（plugins/corpus/structured/store.py）",
                    "compare/calculate 可用记录数（当前 11/56）",
                ],
                "reopen_history": [
                    {"round": "OPEN-D（83 号）", "form": "compare/calculate 是否仍全或无"},
                    {"round": "C4（契约 v4.4）", "form": "按受影响轴撤去用途（轴名已签）"},
                    {
                        "round": "D-3（92 号机制落地后）",
                        "form": "两个理由码挂 condition 轴还是 attribution 轴",
                    },
                ],
                "measured_common": {
                    "records_that_can_compare_or_calculate_today": use_grading["measured_impact"][
                        "records_that_can_compare_or_calculate_today"
                    ],
                    "correct_records_with_at_least_one_reason": use_grading["measured_impact"][
                        "correct_records_with_at_least_one_reason"
                    ],
                    "reason_codes_as_hard_gate_cost": use_grading["measured_impact"][
                        "reason_codes_as_hard_gate_cost"
                    ],
                    "default_implementation": "92 号 claim_use_axes.py 已落地，默认档与旧规则同结果（11 = 11）",
                },
                "options": [
                    {
                        "key": "O1_status_quo",
                        "rule": "保持现状：不改词表、不改轴归属；cite 侧缺口只报告",
                        "derived": {"usable_compare_or_calculate": "11/56"},
                        "measured": {"delta_vs_today": 0},
                        "cost": "0；但已签的 C4 三条 cite 侧轴在本词表下名不副实",
                    },
                    {
                        "key": "O2_remap_two_codes",
                        "rule": (
                            "把 source_qualified_context_requires_review 与 "
                            "qualifier_definition_unverified 从 condition 轴改挂 attribution 轴"
                        ),
                        "derived": {"usable_compare_or_calculate": "26/56"},
                        "measured": {"delta_vs_today": 15},
                        "cost": (
                            "属口径变更须签认；风险：带条件/否定/转述语境的数值断言变成「可计算」，"
                            "与报告 §5.1.2「有缺口的条目不得取得受影响的用途」相冲"
                        ),
                    },
                    {
                        "key": "O3_extend_vocabulary",
                        "rule": (
                            "扩展下游 usable_for 词表，新增 cite_attributed / cite_stance；"
                            "不放行 compare/calculate"
                        ),
                        "derived": {
                            "usable_compare_or_calculate": "11/56",
                            "cite_side_axes": "可表达",
                        },
                        "measured": {"delta_vs_today": 0},
                        "cost": (
                            f"改 {USABLE_FOR_VOCABULARY_SITE} 的允许集合 + query/consumption/derivation "
                            "消费点 + 回归证明（数据结构变更，须 U 裁）"
                        ),
                    },
                ],
            },
        ],
        "verification": {
            "measured_by_this_script": {
                "accepted_records_total": accepted["accepted_records_total"],
                "accepted_records_per_source": per_source,
                "gold_claims_targets": len(targets),
                "gate_v3_unfrozen_axes": unfrozen,
                "gate_v3_release_precondition": gate["verdict"]["release_line"].get("precondition"),
                "gate_v3_target_line_verdict": gate["verdict"]["target_line"]["verdict"],
                "gate_v3_release_verdict": gate["verdict"]["release_line"]["verdict"],
            },
            "read_not_recomputed": {
                "per_source_precision": release["measured_per_source_precision"],
                "usable_compare_or_calculate": use_grading["measured_impact"][
                    "records_that_can_compare_or_calculate_today"
                ],
            },
            "frozen_input_hashes": {name: sha256(path) for name, path in INPUTS.items()},
        },
        "authority": {
            "gate_v3_signed": {"path": _rel(GATE_V3), "sha256": gate_sha},
            "contract_v4.4_signed": {"path": _rel(CONTRACT_V44), "sha256": sha256(CONTRACT_V44)},
            "registration_92": {
                "path": _rel(SCOPE_REGISTRATION),
                "sha256": sha256(SCOPE_REGISTRATION),
            },
        },
        "rules_in_force": {
            "status": "pending_human_signature",
            "note": (
                "R1/R2 未签认前，校验器对「未裁轴承载 PASS」只检出、不阻塞（否则等于用未签的规则"
                "去卡已签的产物）；签认后自动升为阻塞，91 号由更正登记豁免。"
            ),
            "checker": "tools/check_claims_gate.py::pass-not-dependent-on-unfrozen-axis",
        },
        "not_in_scope": [
            "不改金标 / 不改 P1R5 已签裁定 / 不改契约 v4.3、v4.4 / 不改门 v3（91 号）/ 不改 92 号登记",
            "不做约定外的阈值或口径取值裁定（三格 value 留空，由 U 填）",
            "不启动 F6 重跑、不改生产侧接缝（F9）",
        ],
    }
    return plan


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


RULES: dict[str, Any] = {
    "R1_assertion_only": {
        "rule": "治理只阻断「断言」，不阻断「动作」",
        "detail": (
            "执行层可以继续跑、继续产、继续改；带未裁轴的结论必须标 pending_caliber，"
            "不得标 PASS / 达标 / 可交付。"
        ),
        "why": "否则治理会以「判据未定」为由冻结执行，与「治理服务执行层」相冲。",
        "how_to_apply": "任何门/报告/登记件中出现 PASS 时，检查其是否引用 pending_human_decision 的轴。",
        "enforced_by": "tools/check_claims_gate.py::pass-not-dependent-on-unfrozen-axis",
    },
    "R2_fail_closed_default": {
        "rule": "未裁轴的默认行为 = 拒绝正面断言（fail-closed），而不是强取最严值去阻断执行",
        "detail": (
            "未裁期间该轴只报告；既不因为未裁而放行（不 PASS），也不因为未裁而阻断动作"
            "（不 fail 执行）。"
        ),
        "why": (
            "强取最严值（例如未裁即按 a=40/20）会阻断执行，等价于让治理阻碍执行；"
            "而默认放行则会用未定判据产出结论。两者都不是 fail-closed 的正确形态。"
        ),
        "how_to_apply": "登记件必填 pending_caliber=true；校验器只在规则生效后升为阻塞。",
        "enforced_by": "governance-registration-template.fields.pending_caliber",
    },
    "R3_recompute_on_fill": {
        "rule": "回填必须重算",
        "detail": "任何轴裁完后，受影响的结论必须用新口径重算并重新签认；旧分只作历史证据，不得沿用。",
        "why": "防止「旧分挂新尺」，也防止「改尺子过门」。",
        "how_to_apply": "登记件必填 recompute_on_fill（结论路径清单）；缺该字段的登记不接受。",
        "enforced_by": "governance-registration-template.fields.recompute_on_fill",
    },
    "R4_expiry_to_report_only": {
        "rule": "到期即转报告项",
        "detail": "每格登记 owner + decide_by；到期末裁 ⇒ 该轴自动转为永久报告项（保守），不自动放行。",
        "why": "防止「永久滞后」积债，也防止滞后被读成默认通过。",
        "how_to_apply": "登记件必填 owner / decide_by；到期后 status 只能是 expired_to_report_only。",
        "enforced_by": "governance-registration-template.fields.status.allowed",
    },
}

REGISTRATION_TEMPLATE: dict[str, Any] = {
    "schema_version": "claims-governance-registration-template-1",
    "fields": {
        "id": {"required": True, "note": "稳定标识（如 M1 / CORR-91-PRECONDITION）"},
        "axis": {"required": True, "note": "被裁的轴名（须与门 unfrozen_axes / 契约叶子同名）"},
        "status": {
            "required": True,
            "allowed": ["pending_human_decision", "decided", "expired_to_report_only"],
            "note": "到期未裁只能转 expired_to_report_only，不得转 decided",
        },
        "value": {"required": True, "note": "未裁时必须是 null；禁止预填"},
        "owner": {"required": True, "note": "裁决人"},
        "decide_by": {"required": True, "note": "ISO 日期；R4 到期检查依据"},
        "pending_caliber": {
            "required": True,
            "note": "true ⇒ 该轴只能报告，不得承载 PASS / 达标 / 可交付",
        },
        "recompute_on_fill": {
            "required": True,
            "note": "裁完后必须重算并重签的结论路径清单（R3）",
        },
        "measured_options": {
            "required": True,
            "note": "每个选项的实测后果，供裁决时对照；不得只给推荐值",
        },
    },
    "forbidden": [
        "预填 value 或代签",
        "用未裁轴承载 PASS / 达标 / 可交付（R1/R2）",
        "到期后自动放行（到期 ⇒ 转报告项，不是转为通过）",
        "裁完后沿用旧分而不重算（R3）",
    ],
}

SIGNOFF_MD = """# Claims 治理层方案（93 号）· 签认件

状态：草稿，**未签认**。`status = draft_pending_human_signature`。
本件只做三件事：把判据的**载体**拆出来单独裁、登记 91 号那处更正、给出治理服务执行的四条规则。
不改 83/84/88/90/91/92 号或任何冻结件的字节；零模型调用。

## 一、为什么要单独做这一件

判据的「取值」签了，判据的「载体」没签 —— 于是每遇到一个新数值或新词，就回到同一个问题：

| 概念（同一件事） | 第一次 | 第二次 | 第三次 |
|---|---|---|---|
| claims 能否借 items 的数值 | OPEN-A：40/20 平移？ | C5：目标线「逐字恒等」 | **M1** |
| 分源精度轴是否存在 | C5：放行线加 0.55 | D-2：契约六项无该字段 | **M2** |
| 缺字段时撤什么用途 | OPEN-C：四零载体字段 | C4：按轴撤用途 | **M3** |

## 二、三格（请逐格填值并签名；实测后果见 `claims-governance-plan.json` 的 `cells[].options`）

**填法：只在下面三行等号右侧写枚举值（原样照抄，不要改写其它文字；不要留 `____`）。**

```
M1 = ____            # a_transplant | b_scaled_floor | b_scaled_ceil | c_diagnostic
M2 = ____            # exists | report_only
M3 = ____            # O1_status_quo | O2_remap_two_codes | O3_extend_vocabulary
```

| 编号 | 待裁（载体问题） | 选项与实测后果 | 我的建议 |
|---|---|---|---|
| M1 | 两个 accepted 条数下限如何派生 | `a_transplant` 平移 40/20（池只有 20/10 ⇒ 算术不可满足，放行线多 3 项阻断）／ `b_scaled_floor` 17/8 ／ `b_scaled_ceil` 17/9 ／ `c_diagnostic` 仅诊断（须契约语义变更） | b_scaled_floor（并在同格定死取整方向） |
| M2 | 分源精度轴是否存在 | `exists` 进 gating（须契约加字段 + 新 P03 绑定记录）／ `report_only` 只报告 | report_only |
| M3 | C4 的 cite 侧轴如何落地 | `O1_status_quo` 现状 11/56 ／ `O2_remap_two_codes` 改挂 attribution → 26/56（+15，风险：条件/否定语境断言变可算）／ `O3_extend_vocabulary` 扩下游词表（可表达 cite 侧轴，不放行计算） | O1 或 O3；O2 不建议 |

## 三、四条规则（治理服务执行层）

- **R1** 治理只阻断「断言」，不阻断「动作」：执行可继续，带未裁轴的结论须标 `pending_caliber`。
- **R2** 未裁轴 fail-closed = 拒绝正面断言，**不是**强取最严值去阻断执行。
- **R3** 回填必须重算：轴裁完后受影响的结论必须用新口径重算并重签，旧分只作历史证据。
- **R4** 到期即转报告项：登记 `owner` + `decide_by`，到期未裁 ⇒ 转 `expired_to_report_only`，不自动放行。

## 四、91 号更正登记（不改其字节）

`evidence/91-.../claims-gate-v3.json` 的 `verdict.release_line`：

- 现状：`verdict = PASS`，`precondition = "D-1 ≠ a"` ⇒ 已签结论以未裁轴为前提。
- 更正读法（R1/R2）：`D-1` 裁定前，该行读作 **`pending_caliber`**，不得读作 PASS。
- 不变项：`measured` 值（0.6296 / 0.5893 / 0.7200）与目标线 FAIL 终态一律不变。
- 更正记录见 `governance-corrections.json`（含 91 号 sha256 绑定）。

## 五、硬约束（不属于待裁）

- 例外登记只能豁免「已登记且规则已生效」的产物；R1/R2 未签认前，校验器只检出、不阻塞。
- 三格 `value` 一律为 `null`；本件不代填、不预填、不代签。

## 签名

reviewer: ____________    adjudicator: ____________    signed_on: ____________
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true", help="只打印摘要，不写文件")
    parser.add_argument("--force", action="store_true", help="允许覆盖本目录内已存在的输出")
    args = parser.parse_args()

    plan = build_plan()
    gate_sha = plan["authority"]["gate_v3_signed"]["sha256"]

    corrections = {
        "schema_version": "claims-governance-corrections-1",
        "created_on": PLAN_ON,
        "zero_model_calls": True,
        "authority": {
            "plan": "claims-governance-plan.json",
            "rules": ["R1_assertion_only", "R2_fail_closed_default"],
            "rules_status": "pending_human_signature",
            "note": ("本件的豁免只在 R1/R2 签认后生效；未签认时校验器对该缺陷只检出、不阻塞。"),
        },
        "corrections": [
            {
                "id": "CORR-91-PRECONDITION",
                "artifact": {
                    "path": _rel(GATE_V3),
                    "sha256": gate_sha,
                    "bytes_unchanged": True,
                    "mutation_forbidden": "本件不修改 91 号任何字节",
                },
                "field_path": ["verdict", "release_line"],
                "defect": "已签 PASS 以未裁轴（D-1）为前提：precondition = 'D-1 ≠ a'",
                "corrected_view": {
                    "until_M1_decided": "pending_caliber（不得读作 PASS）",
                    "after_M1_decided": "按 R3 用新口径重算并重新签认",
                    "unchanged": "measured 值（0.6296 / 0.5893 / 0.7200）与 target_line FAIL 终态",
                },
                "scope": "仅该行判定读法；不触及目标线终态、不触及任何 measured 值",
                "status": "registered_pending_human_signature",
            }
        ],
        "not_covered": [
            {
                "item": "M2 / D-2 分源精度轴",
                "reason": "91 号已按报告项处理（per_source_axis_note），未承载 PASS ⇒ 无需更正",
            },
            {
                "item": "M3 / D-3 用途轴归属",
                "reason": "不在 91 号门内，属 92 号机制落地；见 plan.cells.M3",
            },
        ],
    }

    landing = {
        "schema_version": "claims-governance-landing-1",
        "created_on": PLAN_ON,
        "zero_model_calls": True,
        "code_changes": [
            {
                "path": "tools/check_claims_gate.py",
                "change": (
                    "新增不变量 pass-not-dependent-on-unfrozen-axis（门里任何 PASS 不得以未裁轴为"
                    "前提）+ 例外登记读取；判定升为阻塞的条件是 R1/R2 签认，豁免的额外条件是更正"
                    "登记自身已签认且绑定本件哈希。既有检查项语义未改。"
                ),
            },
            {
                "path": "tests/test_claims_governance_plan.py",
                "change": "新增 12 项常驻测试：三格留空、登记绑定哈希、未签登记不得豁免、规则生效后才阻塞。",
            },
        ],
        "frozen_artifacts_unchanged": {name: sha256(path) for name, path in INPUTS.items()},
        "verification_commands": [
            "uv run python tools/check_claims_gate.py",
            "uv run pytest tests/test_claims_governance_plan.py tests/test_claims_gate_invariants.py"
            " tests/test_claims_contract_role.py -q",
            "uv run ruff check tools/check_claims_gate.py tests/test_claims_governance_plan.py",
            "uv run pyright tools/check_claims_gate.py",
            "uv run python tools/check_evidence_guard.py",
            "python build_governance_plan.py --no-write  # 幂等：产物内容不变",
        ],
        "results": {
            "observed_on": PLAN_ON,
            "note": ("时点观测，不是不变量；不变量由 verification_commands 里的命令与测试承担。"),
            "checker": "tools/check_claims_gate.py exit 0（30 项，blocking_failures=[]）",
            "pytest_focused": "test_claims_governance_plan + test_claims_gate_invariants + "
            "test_claims_contract_role = 44 passed",
            "pytest_broader": "claims/structured/evidence-pipeline/evidence-guard 十件组 = 179 passed",
            "ruff": "ruff check + ruff format --check 全通过（2 文件已格式化）",
            "pyright": "0 errors",
            "evidence_guard": "tools/check_evidence_guard.py exit 0",
            "import_smoke": (
                "489 文件中 1 项失败：benchmarks.public.harbor_agent（ModuleNotFoundError: harbor，"
                "eval extra 未安装）——环境类，与本轮改动无关"
            ),
            "check_symbols": "OK: 0 missing-symbol import(s) across 489 file(s)",
            "frozen_artifacts": "6 个冻结件 sha256 与本件记录逐字一致（未改字节）",
        },
        "note": (
            "results 由执行报告填写；本件不记录代码文件哈希，避免代码再次改动时产生虚假漂移。"
        ),
    }

    outputs = {
        "claims-governance-plan.json": (
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
        "landing-record.json": (json.dumps(landing, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        ),
        "governance-corrections.json": (
            json.dumps(corrections, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
        "governance-registration-template.json": (
            json.dumps(REGISTRATION_TEMPLATE, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
        "claims-governance-signoff.md": SIGNOFF_MD.encode("utf-8"),
    }
    manifest = {
        "schema_version": "claims-governance-plan-manifest-1",
        "status": "draft",
        "created_on": PLAN_ON,
        "model_calls": 0,
        "inputs": {name: sha256(path) for name, path in INPUTS.items()},
        "outputs": {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()},
        "touched_code": [
            "tools/check_claims_gate.py",
            "tests/test_claims_governance_plan.py",
        ],
        "does_not_touch": [
            "evidence/83-claims-scope-gate-draft-20261014/**",
            "evidence/84-claims-gate-v2-draft-20261014/**",
            "evidence/88-claims-contract-v44-signed-20261014/**",
            "evidence/90-claims-gate-v3-and-run-20261014/**",
            "evidence/91-claims-gate-v3-signed-20261014/**",
            "evidence/92-claims-scope-registration-20261014/**",
            "evidence/75-r2-signed-20261013/**",
            "evidence/10-quality-gold-freeze-20261008-r2/**",
            "evidence/17-structured-extraction-convergence-closure-20261009/**",
        ],
    }
    outputs["MANIFEST.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )

    if args.no_write:
        print(json.dumps(plan["verification"], ensure_ascii=False, indent=2))
        print(json.dumps(corrections, ensure_ascii=False, indent=2))
        print(f"[no-write] {len(outputs)} outputs computed; nothing written.")
        return 0

    existing = [name for name in outputs if (HERE / name).exists()]
    if existing and not args.force:
        raise SystemExit(f"refusing to overwrite existing outputs {existing}; use --force")

    for name, data in outputs.items():
        (HERE / name).write_bytes(data)
    print(f"wrote {len(outputs)} files to {HERE}")
    print(json.dumps(manifest["outputs"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
