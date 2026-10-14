"""Build the claims pre-registration draft (95 号): question, arms, metrics, exit rules.

Zero model calls. This is a *pre-registration*: every threshold below is either derived from a
frozen measurement or explicitly marked as a proposal awaiting the U's value. Nothing here is
decided, and the live run it authorises does not start until the budget line is filled and the
instrument is signed.

Why a pre-registration at all: the trial's outcome decides whether the claims role stays, so the
读数 rules must be fixed *before* the new pool exists -- otherwise a weak result can be re-read
under a friendlier caliber (the failure mode the whole 83-93 chain exists to prevent).

Definitions are imported from ``tools/check_claims_gate`` so the pre-registration cannot drift
from the audited caliber definitions.

Usage:
    python build_preregistration.py [--no-write] [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = HERE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from tools.check_claims_gate import (  # noqa: E402
    COORDINATE_REASON_CODES,
    _claim_of,
    _is_role_external,
    recompute_calibers,
    sha256,
)
from tools.evidence_guard import assert_writable, write_once  # noqa: E402

PREREG_ON = "2026-10-14"

GOLD = ROOT / "evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json"
POOL = (
    ROOT
    / "evidence/17-structured-extraction-convergence-closure-20261009"
    / "p1r5-claims-adjudication-v2/candidate-adjudications.signed.json"
)
COVERAGE = (
    ROOT / "evidence/83-claims-scope-gate-draft-20261014/r0-zero-call/coverage-measurements.json"
)
BINDING_AUDIT = (
    ROOT
    / "evidence/17-structured-extraction-convergence-closure-20261009/claims-binding-audit.json"
)
HISTORICAL_RUN = (
    ROOT
    / "evidence/17-structured-extraction-convergence-closure-20261009/p1-claims-gate-result.json"
)
GATE_V3 = ROOT / "evidence/91-claims-gate-v3-signed-20261014/r0-zero-call/claims-gate-v3.json"
CONTRACT_V44 = (
    ROOT / "evidence/88-claims-contract-v44-signed-20261014/r0-zero-call/scoring-contract-v4.4.json"
)
PLAN_93 = (
    ROOT / "evidence/93-claims-governance-plan-20261014/r0-zero-call/claims-governance-plan.json"
)
REFUSAL_97 = (
    ROOT
    / "evidence/97-claims-governance-refusal-20261014/r0-zero-call/claims-governance-refusal.json"
)

INPUTS = {
    "frozen_gold": GOLD,
    "p1r5_candidate_adjudications_signed": POOL,
    "claims_coverage_v1": COVERAGE,
    "claims_binding_audit": BINDING_AUDIT,
    "historical_claims_gate_result": HISTORICAL_RUN,
    "claims_gate_v3_signed": GATE_V3,
    "signed_scoring_contract_v4.4": CONTRACT_V44,
    "governance_plan_93": PLAN_93,
    "governance_refusal_97": REFUSAL_97,
}

# Binding families that the treatment arm must cover, or the trial under-tests claims. Counts are
# overlapping (one candidate may violate several coordinates) and come from the frozen audit.
REQUIRED_TREATMENT_COVERAGE = (
    "metric_binding",
    "subject_binding",
    "period_binding",
    "value_or_unit_binding",
    "role_or_overgeneration",
)

# Every stage-2 stop-loss proxy must be owned by one pre-registered treatment rule: a stop-loss that
# no arm can move aborts the run no matter what the repair did. v3 adds T4 because
# ``unbound_fields_without_reason_code`` had no owner (the 9 unlabelled rows found in this package).
TREATMENT_OWNERSHIP = {
    "role_external_candidates": "T1_no_opinion",
    "unbound_union": "T2_unbound_disposition",
    "redundant_renderings": "T3_dedupe_tie_break",
    "unbound_fields_without_reason_code": "T4_missing_field_must_be_labelled",
}

# Did the treatment get *done* (trial validity) vs is the result *good* (quality guardrail). Only the
# former can void a run; only the latter can drop claims to tier C.
TREATMENT_DEFINITION_ITEM_IDS = (
    "role_external_candidates",
    "unbound_fields_without_reason_code",
)
QUALITY_GUARDRAIL_ITEMS = (
    "target_recall",
    "unresolved_candidates",
    "sentinels",
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _norm(text: str | None) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff%]", "", text or "").lower()


def measure_proxies(pool: dict[str, Any]) -> dict[str, Any]:
    """Zero-call proxies measurable on any candidate pool, without human adjudication.

    They exist so the expensive adjudication can be aborted early: if the treatment arm does not
    move these, no amount of judging will turn the run into a pass.

    Two definitions matter and both are *corrected* here versus the 83/84-号 records:

    * the coordinate gap is measured **field-first** (empty period/unit/metric/subject) and unioned
      with the recorded reason codes, because the reason codes miss cases -- 9 in-role candidates
      lack a field yet carry no blocking code, so a code-only count under-reports the defect;
    * redundancy is grouped by ``subject + metric + normalized quote``, because the same source
      span can render two numbers (e.g. "+3.2 / +3 倍") that no value-keyed grouping would pair.
    """
    rows = pool["adjudications"]
    in_role = [row for row in rows if not _is_role_external(_claim_of(row))]

    def field_gap(claim: dict[str, Any]) -> bool:
        return any(
            claim.get(field) in (None, "")
            for field in ("subject", "metric", "period_raw", "unit_raw")
        )

    def code_gap(claim: dict[str, Any]) -> bool:
        return bool(set(claim.get("reason_codes") or ()) & set(COORDINATE_REASON_CODES))

    field_gap_rows = [row for row in in_role if field_gap(_claim_of(row))]
    code_gap_rows = [row for row in in_role if code_gap(_claim_of(row))]
    unbound_ids = {id(row) for row in field_gap_rows} | {id(row) for row in code_gap_rows}
    unlabelled = [
        row for row in in_role if field_gap(_claim_of(row)) and not code_gap(_claim_of(row))
    ]

    keys: Counter = Counter()
    for row in in_role:
        claim = _claim_of(row)
        keys[
            (
                _norm(claim.get("subject")),
                _norm(claim.get("metric")),
                _norm(claim.get("evidence_quote"))[:80],
            )
        ] += 1
    redundant = sum(count - 1 for count in keys.values() if count > 1)
    return {
        "candidates_total": len(rows),
        "in_role_candidates": len(in_role),
        "role_external_candidates": len(rows) - len(in_role),
        "unbound_union": len(unbound_ids),
        "unbound_by_field": len(field_gap_rows),
        "unbound_by_reason_code": len(code_gap_rows),
        "unbound_fields_without_reason_code": len(unlabelled),
        "redundant_renderings": redundant,
        "redundant_groups": sorted(
            " | ".join(part for part in key if part) for key, count in keys.items() if count > 1
        ),
    }


def _field_gap(claim: dict[str, Any]) -> bool:
    return any(
        claim.get(field) in (None, "") for field in ("subject", "metric", "period_raw", "unit_raw")
    )


def _score(kept: list[dict[str, Any]], targets_total: int) -> dict[str, Any]:
    judgements = Counter(row.get("judgement") for row in kept)
    numerator = judgements["matched"] + judgements["correct_extra"]
    denominator = numerator + judgements["incorrect"] + judgements["duplicate"]
    hits = {row.get("matched_gold_id") for row in kept if row.get("judgement") == "matched"}
    return {
        "kept": len(kept),
        "judgements": {
            name: judgements[name]
            for name in ("matched", "correct_extra", "incorrect", "duplicate")
        },
        "precision": f"{numerator}/{denominator} = {numerator / denominator:.4f}"
        if denominator
        else "N/A",
        "recall": f"{len(hits)}/{targets_total}",
        "matched_ids": sorted(name for name in hits if name),
    }


def measure_treatment_counterfactuals(pool: dict[str, Any], targets_total: int) -> dict[str, Any]:
    """Zero-call counterfactuals for the *deletion-shaped* halves of the treatment.

    Only deletion can be simulated on a frozen pool: filtering and de-duplication remove records
    without changing any surviving record, so the signed judgements can be inherited as-is. The
    repair-shaped half (binding a missing period/unit) cannot be simulated here, because the
    repaired record does not exist in the pool -- that half needs a live run, and this measurement
    is what tells us how much of the gap it has to close.
    """
    rows = pool["adjudications"]
    in_role = [row for row in rows if not _is_role_external(_claim_of(row))]

    def dedupe(kept: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for row in kept:
            claim = _claim_of(row)
            key = (
                _norm(claim.get("subject")),
                _norm(claim.get("metric")),
                _norm(claim.get("evidence_quote"))[:80],
            )
            groups.setdefault(key, []).append(row)
        dropped = [row for group in groups.values() if len(group) > 1 for row in group[1:]]
        return [row for row in kept if row not in dropped], dropped

    baseline = _score(in_role, targets_total)
    deduped, dropped_rows = dedupe(in_role)
    reject_unbound = [row for row in in_role if not _field_gap(_claim_of(row))]
    reject_deduped, _ = dedupe(reject_unbound)

    dropped_groups = []
    seen: set[tuple[str, str, str]] = set()
    for row in in_role:
        claim = _claim_of(row)
        key = (
            _norm(claim.get("subject")),
            _norm(claim.get("metric")),
            _norm(claim.get("evidence_quote"))[:80],
        )
        if key in seen:
            continue
        members = [
            other
            for other in in_role
            if (
                _norm(_claim_of(other).get("subject")),
                _norm(_claim_of(other).get("metric")),
                _norm(_claim_of(other).get("evidence_quote"))[:80],
            )
            == key
        ]
        if len(members) > 1:
            seen.add(key)
            dropped_groups.append(
                {
                    "group": " | ".join(part for part in key if part),
                    "members": [
                        {
                            "judgement": member.get("judgement"),
                            "matched_gold_id": member.get("matched_gold_id"),
                            "value_text": _claim_of(member).get("value_text"),
                        }
                        for member in members
                    ],
                    "tie_break_is_load_bearing": any(
                        member.get("judgement") == "matched" for member in members
                    ),
                }
            )

    lost_matched = sorted(
        row["matched_gold_id"]
        for row in in_role
        if _field_gap(_claim_of(row))
        and row.get("judgement") == "matched"
        and row.get("matched_gold_id")
    )
    return {
        "simulatable_here": [
            "C1 去 opinion（删条目）",
            "去冗余渲染（删条目）",
            "缺坐标不产出（删条目）",
        ],
        "not_simulatable_here": "坐标绑定/补齐（产生旧池里不存在的新记录）⇒ 必须真跑",
        "variants": {
            "D2_baseline": baseline,
            "D2_plus_dedupe": _score(deduped, targets_total),
            "reject_unbound": _score(reject_unbound, targets_total),
            "reject_unbound_plus_dedupe": _score(reject_deduped, targets_total),
        },
        "dedupe_dropped": len(dropped_rows),
        "dedupe_groups": dropped_groups,
        "reject_unbound_loses_matched_gold": lost_matched,
        "readings": [
            "不破召回的前提下，确定性治疗的安全上限 = D2_plus_dedupe（去 opinion 早已在 D2 口径内，不再加分）",
            "『缺坐标不产出』会丢掉命中的金标 ⇒ 破护栏 ⇒ 该处置不可行，只能选『补齐』",
            "去冗余的并列规则是载重项：同组内可能同时存在 matched 与 duplicate",
        ],
    }


def measure_binding_families() -> dict[str, Any]:
    audit = load_json(BINDING_AUDIT)
    families = audit["incorrect_candidate_failure_families"]
    counted = {key: value for key, value in families.items() if isinstance(value, int)}
    missing = [name for name in REQUIRED_TREATMENT_COVERAGE if name not in counted]
    if missing:
        raise SystemExit(f"binding audit families changed shape; missing {missing}")
    codes = Counter(audit["reason_code_counts"])
    return {
        "families_overlapping_do_not_sum": counted,
        "top_reason_codes": codes.most_common(8),
        "role_external_by_audit": counted["role_or_overgeneration"],
        "subject_counterfactual_limitation": audit["coordinate_observations"][
            "document_subject_inheritance"
        ]["limitation"],
        "required_treatment_coverage": list(REQUIRED_TREATMENT_COVERAGE),
    }


def measure_historical_budget() -> dict[str, Any]:
    if not HISTORICAL_RUN.exists():
        return {
            "available": False,
            "note": "历史同类轮次的调用账不可用；预算须由 U 以其他依据填写",
        }
    record = load_json(HISTORICAL_RUN)
    executions = record.get("executions") or []
    ceilings = [entry.get("attempt_ceiling") for entry in executions]
    attempts = [entry.get("actual_attempts") for entry in executions]
    return {
        "available": True,
        "artifact": str(HISTORICAL_RUN.relative_to(ROOT)),
        "scope": record.get("status"),
        "model_calls_recorded": record.get("model_calls"),
        "candidate_count": record.get("candidate_count"),
        "per_execution": [
            {"name": entry.get("name"), "attempt_ceiling": e, "actual_attempts": a}
            for entry, e, a in zip(executions, ceilings, attempts, strict=True)
        ],
        "note": "单源轮次实测账；本次治疗臂为同源同配置 ⇒ 预算形态以此为上限依据，数值待 U 填",
    }


def build() -> dict[str, Any]:
    gold = load_json(GOLD)
    pool = load_json(POOL)
    coverage = load_json(COVERAGE)
    contract = load_json(CONTRACT_V44)

    calibers = recompute_calibers(pool, coverage, gold)
    d1 = calibers["D1_all_candidates"]
    d2 = calibers["D2_in_role_only"]
    proxies = measure_proxies(pool)
    families = measure_binding_families()
    historical = measure_historical_budget()
    counterfactuals = measure_treatment_counterfactuals(
        pool, len([r for r in gold["records"] if r["role"] == "claims"])
    )

    numerator = d2["precision_contract_formula"]["numerator"]
    d2_counterfactual = counterfactuals["variants"]["D2_baseline"]
    release_min = contract["claims_thresholds"]["release_line_proposed"]["candidate_precision_min"]
    target_min = contract["claims_thresholds"]["target_line"]["candidate_precision_min"]

    def fp_allowance(line: float) -> int:
        return int(numerator * (1 - line) / line)

    return {
        "schema_version": "claims-preregistration-1",
        "id": "95-claims-prereg-20261014",
        "status": "draft_pending_human_signature",
        "role": "claims",
        "created_on": PREREG_ON,
        "zero_model_calls": True,
        "purpose": (
            "在花掉预算与人工裁定之前，把『产出侧修复是否让 claims 值得保留』这一问的题目、臂、"
            "指标与退出规则写死；未签认不得起跑，未写入退出规则的分不得用于去留。"
        ),
        "question": {
            "statement": (
                "把 Claims 产出侧按已签 C1 口径修复（角色边界 / 坐标绑定 / 去冗余渲染）之后，"
                "在同一份冻结金标（20 条目标）上重跑得到的候选池，能否把 in-role 精度从"
                f"{d2['precision_contract_formula']['display']} 抬到放行线之上，或直接过目标线？"
            ),
            "decision_use": "结果决定 Claims 角色的去留：保留（有条件/无条件）或降级退出默认路径",
            "not_asking": [
                "不问是否能过 items 的目标线（claims 目标线在 20 条目标上本就不可达，已登记）",
                "不问模型/成本效率（成本只在质量过关后比较）",
                "不问是否扩金标或改判据（金标冻结、判据预注册）",
            ],
        },
        "reading_axes": {
            "in_verdict": [
                "candidate_precision",
                "target_recall",
                "unresolved_candidates",
                "sentinels",
            ],
            "excluded": {
                "accepted_records_total_min": (
                    "与 target_recall 字面等价（claims 目标 20/10 ⇒ floor(0.85×20)=17 ⟺ matched ≥ 17；"
                    "floor(0.85×10)=8 ⟺ 分源召回 ≥ 0.80）⇒ 零独立判别力，不参与读数"
                ),
                "accepted_records_per_source_min": "同上（分源层面）",
                "per_source_precision": "诊断项：只报告，不参与判定（M2 拒签/未裁）",
            },
            "basis": "M1 退化证明 + 97 号拒签登记（净治理效果为空）",
            "note": "读数轴从 6 项收敛到 4 项；被排除的轴一律只出现在诊断块",
            "precondition_note": (
                "accepted 轴退出判定后，91 号放行线的前提『D-1 ≠ a』自然消解 ⇒ 91 号 release_line "
                "读作无条件 PASS（登记见 prior_record_readings；即 97 号 consequences[3] 的取代读法）"
            ),
        },
        "deterministic_ceiling_on_frozen_pool": {
            "why": (
                "给结果定读法：在『不重抽』的前提下，能拿到的最高分是多少。看到新分时用来判断"
                "『治疗是否真的起了作用』而不是『运气好不好』。"
            ),
            "counterfactuals": counterfactuals["variants"],
            "safe_ceiling": counterfactuals["variants"]["D2_plus_dedupe"]["precision"],
            "over_guardrail_ceiling": counterfactuals["variants"]["reject_unbound_plus_dedupe"][
                "precision"
            ],
            "implication": (
                f"安全上限 {counterfactuals['variants']['D2_plus_dedupe']['precision']}、破护栏上限 "
                f"{counterfactuals['variants']['reject_unbound_plus_dedupe']['precision']}，都远低于目标线 0.80 "
                "⇒ 目标线的达成只能来自『把缺的坐标补回原文』（重抽），不能来自删条目"
            ),
        },
        "pre_registered_treatment_rules": {
            "why": "治疗臂怎么改必须现在写死，否则改法一变，结果就无法归因",
            "coverage_rule": (
                "四条规则与阶段 2 的四个止损项一一对账（每项恰有一个 owner_treatment_rule）；"
                "任何止损项若无对应治疗规则，该闸门在无治疗时恒不可达，本轮不得起跑"
            ),
            "rules": [
                {
                    "id": "T1_no_opinion",
                    "class": "production_filter（改候选集合）",
                    "verified_by": "role_external_candidates",
                    "rule": "按已签 C1 不再产出 opinion / 无 value 的候选（对齐口径，不改口径）",
                    "score_effect_on_frozen_pool": "0（C1 过滤已含在现口径 D2 内）",
                },
                {
                    "id": "T2_unbound_disposition",
                    "class": "binding_repair（补回原文坐标）",
                    "verified_by": "unbound_union",
                    "rule": "缺 period/unit 的候选一律『补齐』，不得『不产出』",
                    "forced_by_measurement": (
                        f"『不产出』实测会丢掉命中的金标 {counterfactuals['reject_unbound_loses_matched_gold']}"
                        " ⇒ 召回从 20/20 掉到 19/20，护栏当场破"
                    ),
                    "note": "这一条不是判断，是实测排除了一个选项",
                },
                {
                    "id": "T3_dedupe_tie_break",
                    "class": "dedupe_rule（合并同坐标渲染）",
                    "verified_by": "redundant_renderings",
                    "rule": (
                        "同 subject+metric+引用区间的多次渲染合并为一条；并列时按确定性优先级"
                        "『坐标更完整 > value 与引用一致 > 文件序』，禁止使用金标或裁定结果做并列依据"
                    ),
                    "load_bearing": [
                        {
                            "group": group["group"],
                            "members": group["members"],
                        }
                        for group in counterfactuals["dedupe_groups"]
                        if group["tie_break_is_load_bearing"]
                    ],
                    "risk": "并列规则选错会删掉 matched 行 ⇒ 召回 19/20，护栏破",
                },
                {
                    "id": "T4_missing_field_must_be_labelled",
                    "class": "observability_repair（不改候选，只让缺陷可观测）",
                    "verified_by": "unbound_fields_without_reason_code",
                    "rule": (
                        "缺 subject/metric/period/unit 任一字段的候选，必须在产出时就带上对应 reason 码；"
                        "『补齐字段』与『标出阻断码』二者必居其一，不得静默省略"
                    ),
                    "why_needed": (
                        "阶段 2 止损项 unbound_fields_without_reason_code（基线 "
                        f"{proxies['unbound_fields_without_reason_code']} 条）此前无任何治疗规则承担，"
                        "该闸门在无治疗时恒不可达 ⇒ 试验会被自己的止损线挡死"
                    ),
                    "basis": (
                        "本件更正②：in-role 全体字段级缺 "
                        f"{proxies['unbound_by_field']} 条 / 带 reason 码 {proxies['unbound_by_reason_code']} 条 / "
                        f"并集 {proxies['unbound_union']} 条 ⇒ 漏标 {proxies['unbound_fields_without_reason_code']} 条；"
                        "reason 码漏标是『拿 reason 当门』的口径低估缺陷的根因"
                    ),
                    "cost": "零额外模型调用（同一轮产出的仪器化）；工程缺件清单 +1（标码路径）",
                    "classification": "治疗定义项（见 metrics.treatment_definition_checks）：失败 ⇒ 试验无效，不计去留",
                    "alternative_considered": (
                        "把该止损项降级为诊断、不加治疗规则——未采纳：降级会让『漏标』这一缺陷在本轮"
                        "无任何治疗承担，且该缺陷正是 reason 码口径不可信的根因；如 U 在签认时否决，"
                        "须同时把该止损项移出 stage2_proxies 并说明理由"
                    ),
                },
            ],
        },
        "corrections_to_prior_records": [
            {
                "target": "83/84 号 FP 三分里的『结构齐备仍不匹配 7 条 = 同坐标多次渲染（目标价×4、动态PE隐含市值×3）』",
                "retracted": True,
                "measured_instead": (
                    "该 7 条实测构成：2 条同引用重复渲染（GPU/ASIC 机柜 +3.2 / +3 倍，同一个源区间两次数值）"
                    "+ 4 条缺 period 但**未被标任何坐标 reason 码**"
                    "+ 1 条坐标齐备但确不匹配（成交额 103.15 亿元 / 2026-08-28）"
                ),
                "consequences": [
                    "『去冗余渲染』的真实规模是 1 条冗余（不是 7 条）⇒ F9-c 不是主要矛盾",
                    "reason 码漏标 9 条（in-role 全体）⇒ 任何『拿 reason 当门』的口径都会低估缺陷（G2/D3 已因此掉召回）",
                    "校验器的 structurally_complete_nonmatch 桶语义应读作『无 reason 码』而非『结构齐备』",
                ],
                "evidence": "evidence/17-…/p1r5-claims-adjudication-v2/candidate-adjudications.signed.json（零调用逐条复核）",
            },
            {
                "target": "『坐标未绑 20 条』这一计数",
                "retracted": False,
                "measured_instead": (
                    "20 条是『有 reason 码』的 in-role incorrect；并入 4 条漏标的缺字段条目后为 24 条；"
                    "若按 in-role 全体（含正确条目）计，字段级缺 25 条 / 有码 45 条 / 并集 54 条"
                ),
                "consequences": ["预注册的提前止损代理改用并集口径"],
            },
        ],
        "prior_record_readings": [
            {
                "registration_id": "REG-91-RELEASE-UNCONDITIONAL",
                "what": "91 号 claims 门 v3 的 release_line 读法（放行线 PASS 是否带前提）",
                "record": "evidence/91-claims-gate-v3-signed-20261014/r0-zero-call/claims-gate-v3.json",
                "record_sha256": sha256(GATE_V3),
                "field": "verdict.release_line.precondition",
                "recorded_text": "D-1 ≠ a（若取 a，放行线另受 accepted 下限 3 项阻断）",
                "reading_in_force": (
                    "无条件 PASS：读数轴收敛为 4 项（见 reading_axes.excluded）后，accepted 条数下限不再是"
                    "判定轴 ⇒ 前提『D-1 ≠ a』失去所指，放行线 PASS 不带前提、也不再等 D-1 裁定"
                ),
                "why_the_precondition_dissolves": (
                    "该前提的成立基础是『D-1 仍是判定轴』；accepted 下限已被证明与 target_recall 字面等价"
                    "（零独立判别力，M1 退化证明）并移出判定 ⇒ 前提自然消解，无须另行裁定 D-1"
                ),
                "supersedes": {
                    "record": (
                        "evidence/97-claims-governance-refusal-20261014/r0-zero-call/"
                        "claims-governance-refusal.json"
                    ),
                    "record_sha256": sha256(REFUSAL_97),
                    "field": "consequences[3]",
                    "superseded_text": (
                        "91 号 verdict.release_line 的读法仍按 governance-corrections.json 的登记人工读作 "
                        "pending_caliber"
                    ),
                    "why_superseded": (
                        "该 consequence 以『D-1 仍决定放行线读法』为隐含前提；本件已把 accepted 轴移出判定 "
                        "⇒ 前提不成立，故该行不再是现行读法。97 号字节一字不改，本项即其取代读法。"
                    ),
                },
                "does_not_change": [
                    "91 号任何字节：原文与 precondition 保留为当时语境的档案，只改读法、不改记录",
                    "目标线终态 FAIL + unreachable_registered（与 D-1 无关、变体无关）",
                    "放行线的功能线性质：PASS 不等于质量达标、不等于发布许可",
                    "D-2（分源精度轴）仍未裁：该轴只报告、不 gating",
                ],
                "signoff_path": (
                    "本项落在本件（95 号）之内，随本件签认生效；不与 93/94 的 R1–R4 规则捆绑 ⇒ 满足 97 号"
                    "重开条件①『独立、有自身签署路径』的形态要求。未签认前不得当作已生效读法。"
                ),
            }
        ],
        "arms": [
            {
                "id": "A_frozen_baseline",
                "kind": "对照（零成本，已签数据）",
                "treatment": "不跑：使用已签的 P1R5 冻结池与裁定",
                "measured": {
                    "caliber": "C1 角色范围（in_role_only）",
                    "target_recall": d2["target_recall"]["display"],
                    "candidate_precision": d2["precision_contract_formula"]["display"],
                    "per_source_precision": {
                        source: value["display"]
                        for source, value in d2["per_source_precision"].items()
                    },
                },
                "note": "基线不需要新预算，也不需要新裁定",
            },
            {
                "id": "B_production_fix",
                "kind": "治疗臂（本次唯一实跑）",
                "treatment": (
                    "产出侧修复一组：①按已签 C1 不再产出 opinion/无值候选（去角色外过产出）；"
                    "②坐标绑定（subject/metric/period/unit/value 的绑定缺陷，见 binding_caveat）；"
                    "③去冗余渲染（同坐标多次渲染合并为一条）"
                ),
                "held_fixed": [
                    "同一来源与同源快照",
                    "同一抽取配置（M_extract 与模型、提示词版本除上述三项）",
                    "同一份冻结金标（20 条目标）",
                    "同一匹配规则（one-to-one、已签裁定口径）",
                ],
                "added_work": "新池需一轮人工裁定（工作量见 budget_request.human_adjudication）",
            },
        ],
        "arms_not_run": {
            "ablation_arms": (
                "本轮不跑消融臂：每个臂都要一轮人工裁定（约等于池容量），成本过高且题目是去留而非归因"
            ),
            "conditional_second_round": (
                "若 B 落在 B 档边界（0.72 ≤ 精度 < 0.80 或分源不均衡），再单独立项做归因臂，"
                "须另行授权；不得把本轮预算挪用为归因"
            ),
            "rejected_arms": [
                "只改判据不改产出（83 号 B/C 相似度移出）——已定性为定向调参",
                "重划分母 / 改金标 / 改判定为 correct——禁止",
            ],
        },
        "metrics": {
            "primary": {
                "name": "candidate_precision",
                "caliber": (
                    "C1 in_role_only；分母含 duplicate（与已签 C2 单一口径一致）；"
                    "分子 = matched + correct_extra（与已签 C2 同源）"
                ),
                "numerator": "matched + correct_extra",
                "denominator": "matched + correct_extra + incorrect + duplicate（= in-role 池全部条目）",
                "numerator_basis": (
                    "契约已签叶 claims_precision_single_source（C2）：单一口径、一个分子一个分母、fp 含 duplicate；"
                    "correct_extra 属分子，不得挪入分母、不得改判 matched（见 forbidden_readings）"
                ),
                "worked_example_on_frozen_pool": (
                    f"({d2_counterfactual['judgements']['matched']} matched + "
                    f"{d2_counterfactual['judgements']['correct_extra']} correct_extra) / "
                    f"{d2_counterfactual['kept']} = {d2['precision_contract_formula']['display']}"
                ),
                "baseline": d2["precision_contract_formula"]["display"],
                "direction": "higher_is_better",
            },
            "guardrails_must_not_regress": {
                "kind": "质量护栏（结果好不好）；任一破 ⇒ C 档",
                "items": list(QUALITY_GUARDRAIL_ITEMS),
                "target_recall": {
                    "baseline": d2["target_recall"]["display"],
                    "rule": "不得低于 20/20",
                },
                "unresolved_candidates": {"baseline": 0, "rule": "必须为 0"},
                "sentinels": {
                    "baseline": "3/3",
                    "rule": "NT-C11/C12/C13 必须全中",
                },
            },
            "treatment_definition_checks": {
                "kind": "治疗定义项（治疗有没有做对）；失败 ⇒ 试验无效，不计去留、也不读成 C 档",
                "why": (
                    "把『治疗有没有做对』与『质量够不够』分开：治疗定义项失败说明这一轮根本不是预注册的"
                    "那一轮（例如过滤漏了一条角色外候选），任何分数都不能用于 claims 去留判定"
                ),
                "items": [
                    {
                        "proxy": proxy_id,
                        "owner_treatment_rule": TREATMENT_OWNERSHIP[proxy_id],
                        "rule": "== 0",
                    }
                    for proxy_id in TREATMENT_DEFINITION_ITEM_IDS
                ],
                "source_of_truth": (
                    "exit_rules.early_stop_before_human_adjudication.stage2_proxies 的同名条目"
                    "（同一份计数，不重复计量）"
                ),
                "not_a_guardrail": (
                    "role_external_candidates 此前被放在 guardrails_must_not_regress 内，而档位条件写"
                    "『护栏全绿』：一旦过滤漏一条就会被读成『C 档：claims 差』。v3 把它移到本块。"
                ),
            },
            "diagnostics_not_in_verdict": {
                "per_source_precision": {
                    source: value["display"] for source, value in d2["per_source_precision"].items()
                },
                "fp_allowance_for_target_line": fp_allowance(target_min),
                "fp_allowance_for_release_line": fp_allowance(release_min),
                "fp_decomposition_after_run": "角色外 / 坐标未绑 / 齐备不匹配 三类计数",
                "precision_granularity_warning": contract["claims_thresholds"]["target_line"][
                    "granularity_warning"
                ],
            },
        },
        "exit_rules": {
            "preregistration_rule": "以下线值在看到本轮结果之前写死；结果出来后不得改写、不得挑口径",
            "trial_validity": {
                "why": (
                    "先判『这一轮是不是预注册的那一轮』，再判『结果好不好』。治疗定义项失败只说明治疗没执行，"
                    "不说明 claims 质量差"
                ),
                "checks": [
                    f"{proxy_id} == 0（治疗定义项，owner = {TREATMENT_OWNERSHIP[proxy_id]}）"
                    for proxy_id in TREATMENT_DEFINITION_ITEM_IDS
                ],
                "if_passed": "试验有效：继续按 tiers 判 A/B/C",
                "if_failed": (
                    "试验无效：不计入去留（尤其不得读成 C 档『claims 差』）；须先按本件治疗定义修好产出侧、"
                    "再另行授权重跑"
                ),
            },
            "tiers": [
                {
                    "id": "A_keep_and_pass_target",
                    "condition": (
                        f"precision ≥ {target_min} 且质量护栏全绿"
                        "（target_recall = 20/20 且 unresolved = 0 且哨兵 3/3）"
                    ),
                    "reading": "claims 保留，且目标线达成（在 20 条目标粒度内）",
                    "consequence": "进入发布/消费闭环的下一阶段（另行立项）",
                },
                {
                    "id": "B_conditional_keep",
                    "condition": (
                        f"{release_min} ≤ precision < {target_min} 且质量护栏全绿"
                        "（target_recall = 20/20 且 unresolved = 0 且哨兵 3/3）"
                    ),
                    "reading": "claims 有条件保留：停在放行线（功能线），不宣称质量达标",
                    "consequence": "登记目标线不可达 + 已知 FP 族，按功能线有限使用",
                },
                {
                    "id": "C_drop_from_default_path",
                    "condition": (
                        f"precision < {release_min} 或质量护栏任一破"
                        "（target_recall < 20/20 或 unresolved > 0 或哨兵 < 3/3）"
                    ),
                    "reading": "产出侧修复不足以支撑 claims 角色",
                    "consequence": "claims 退出默认路径，指标断言改由 material_items 侧覆盖承接",
                },
            ],
            "tier_note": (
                "档位只由『质量护栏 + 主指标』决定；治疗定义项（role_external_candidates、"
                "unbound_fields_without_reason_code）不出现在任何档位条件里，其失败走 trial_validity"
            ),
            "early_stop_before_human_adjudication": {
                "why": (
                    "阶段 2 的代理指标零调用可算；若它们没动，人工裁定不可能把结果救回来，"
                    "因此先停下来省掉整轮人工"
                ),
                "stage2_proxies": {
                    "role_external_candidates": {
                        "baseline": proxies["role_external_candidates"],
                        "rule": "== 0（治疗定义）",
                        "owner_treatment_rule": TREATMENT_OWNERSHIP["role_external_candidates"],
                        "classification": "treatment_definition",
                    },
                    "unbound_union": {
                        "baseline": proxies["unbound_union"],
                        "rule": "≤ baseline × 0.5",
                        "proposed_by": "assistant",
                        "definition": "字段级缺（subject/metric/period/unit）与 reason 码的并集",
                        "owner_treatment_rule": TREATMENT_OWNERSHIP["unbound_union"],
                        "classification": "quality_proxy",
                    },
                    "redundant_renderings": {
                        "baseline": proxies["redundant_renderings"],
                        "rule": "== 0",
                        "note": "基线只有 2 组，不是主要矛盾，故用零容忍而非折半",
                        "owner_treatment_rule": TREATMENT_OWNERSHIP["redundant_renderings"],
                        "classification": "quality_proxy",
                    },
                    "unbound_fields_without_reason_code": {
                        "baseline": proxies["unbound_fields_without_reason_code"],
                        "rule": "== 0",
                        "reading": "校验器不得再出现『缺字段却无阻断码』的漏标",
                        "owner_treatment_rule": TREATMENT_OWNERSHIP[
                            "unbound_fields_without_reason_code"
                        ],
                        "classification": "treatment_definition",
                    },
                },
                "if_failed": "判『产出侧修复未达预期』，不进入阶段 3；不消耗人工裁定预算",
            },
            "forbidden_readings": [
                "用放行线通过宣称质量达标",
                "在看到结果后调整精度口径（D1/D2/D3/D4 之间换）",
                "把 correct_extra 计入分母或把 incorrect 改判为 matched",
                "用目标线不可达登记为本次结果开脱（它是登记，不是判据）",
                "把治疗定义项失败（角色外未清零 / 漏标未清零）读成 C 档『claims 差』",
            ],
        },
        "binding_caveat": {
            "why_it_matters": (
                "若治疗臂只修 period/unit 这类『补字段』，试验会低估 claims：审计显示最大的绑定族是 "
                "metric 与 subject，且 subject 类条目全部还带至少一条非 subject 阻断理由。"
            ),
            "families": families["families_overlapping_do_not_sum"],
            "top_reason_codes": families["top_reason_codes"],
            "subject_limitation": families["subject_counterfactual_limitation"],
            "required_treatment_coverage": families["required_treatment_coverage"],
            "pre_registered_rule": (
                "治疗臂必须覆盖 required_treatment_coverage 的全部五个族；交付物须逐族说明改了哪一处、"
                "否则该次运行不得用于去留判定"
            ),
        },
        "budget_request": {
            "stage_1_live_run": {
                "shape": "两源、同源快照、同配置的一次全量抽取（唯一实跑）",
                "historical_reference": historical,
                "requested_ceiling": None,
                "filled_by": "U",
                "hard_limits": [
                    "不得超 attempt ceiling 自动重试",
                    "不得换模型或换提供方",
                    "不得在运行中改判据或改提示词",
                    "不得跑第二个臂",
                ],
            },
            "stage_2_proxy_check": {"shape": "零模型调用", "requested": 0},
            "stage_3_human_adjudication": {
                "shape": "对新池逐条做 one-to-one 裁定（与 P1R5 同一口径）",
                "estimated_items": (
                    f"约 {proxies['in_role_candidates']} 条量级（基线 in-role {proxies['in_role_candidates']} 条）"
                ),
                "baseline_reference": "P1R5：reviewer=xyl 逐条裁定 110 条",
                "note": "这是本轮真正的成本大头，且不可由模型代劳",
            },
        },
        "gold_and_caliber_freezes": {
            "gold": {
                "path": str(GOLD.relative_to(ROOT)),
                "sha256": sha256(GOLD),
                "claims_targets": len([r for r in gold["records"] if r["role"] == "claims"]),
                "rule": "不得扩、不得改判；扩金标会同时改变分子与分母，属另立项",
            },
            "thresholds_in_force": {
                "target_line": contract["claims_thresholds"]["target_line"],
                "release_line": contract["claims_thresholds"]["release_line_proposed"],
                "note": "M1/M2 若在起跑前签认，按其口径读分（R3：用新口径重算）；未签认则按 93 号 R2 只报告",
            },
            "governance_preconditions": {
                "M1": "不需要：该轴已证与召回字面等价（零独立判别力），已从读数轴移除；97 号拒签已登记",
                "M2": "不需要：分源精度降为诊断项，只报告不判定",
                "M3": "不需要：与去留无关",
                "R1_R2": "不需要：治理机制已拒签（97 号：净治理效果为空），读数不依赖它",
                "only_prerequisites": [
                    "签本件（读数标准 + 提前止损线 + 91 号放行线读法登记）",
                    "预算 ceiling + 人工裁定工时（U 供）",
                    "三个工程缺件：活跑入口、新池裁定工作表、缺字段标码路径（T4）（assistant 可零调用先备）",
                ],
            },
        },
        "evidence_chain": {
            "baseline_calibers": {
                "D1_all_candidates": d1["precision_contract_formula"]["display"],
                "D2_in_role_only": d2["precision_contract_formula"]["display"],
                "per_source_precision": {
                    source: value["display"] for source, value in d2["per_source_precision"].items()
                },
                "target_recall": d2["target_recall"]["display"],
            },
            "proxies": proxies,
            "treatment_counterfactuals": counterfactuals,
            "frozen_input_hashes": {name: sha256(path) for name, path in INPUTS.items()},
        },
        "revisions": [
            {
                "revision": "v1 → v2（2026-10-14，零调用，草案态编辑）",
                "reason": (
                    "M1 拒签（97 号）且该轴经证与召回字面等价 ⇒ 读数轴从 6 项收敛为 4 项；"
                    "同时把零调用可算的治疗反事实写进标准，使『结果怎么读』不再含糊"
                ),
                "changes": [
                    "新增 reading_axes（判定只用 precision / recall / unresolved / sentinels）",
                    "新增 deterministic_ceiling_on_frozen_pool（安全上限与破护栏上限）",
                    "新增 pre_registered_treatment_rules（去 opinion / 缺坐标=补齐 / 去冗余并列规则）",
                    "governance_preconditions：M1/M2/M3/R1-R2 由『待签』改为『不需要』，只留本件签名与预算",
                ],
                "unchanged": [
                    "退出规则 A/B/C 三档的线值（0.80 / 0.60）与护栏条款",
                    "提前止损的代理基线与阈值",
                    "预算请求形态（ceiling 仍为 null，待 U 填）",
                    "金标冻结（20 条目标）与判据数值",
                ],
                "no_signature_existed_before": True,
            },
            {
                "revision": "v2 → v3（2026-10-14，零调用，草案态编辑）",
                "reason": (
                    "四项一致性清欠：①91 号放行线的读法无主（97 号读作 pending_caliber，而本件已把 accepted "
                    "轴移出判定 ⇒ 前提本应消解）②阶段 2 的『缺字段却无阻断码 = 0』无任何治疗规则承担 "
                    "③主指标只写了分母、没写分子 ④治疗定义项（角色外 = 0）混在质量护栏内，会被读成"
                    "『C 档：claims 差』"
                ),
                "changes": [
                    "新增 prior_record_readings：登记 91 号 release_line 读作无条件 PASS，并登记其对 97 号 "
                    "consequences[3] 的取代关系（97 号字节未改，只记取代读法）",
                    "新增治疗规则 T4_missing_field_must_be_labelled；四条规则与阶段 2 四个止损项一一对账"
                    "（owner_treatment_rule），并由 coverage_rule 钉住『无 owner 不得起跑』",
                    "metrics.primary 补 numerator / denominator / numerator_basis / 冻结池算例"
                    "（分子 = matched + correct_extra，与已签 C2 同源）",
                    "role_external_candidates 移出 guardrails_must_not_regress；新增 "
                    "metrics.treatment_definition_checks 与 exit_rules.trial_validity（治疗定义项失败 ⇒ 试验无效）",
                    "A/B/C 档条件改写为『质量护栏全绿 / 质量护栏任一破』，并加 tier_note 明示档位不含治疗定义项",
                ],
                "unchanged": [
                    "退出规则 A/B/C 三档的线值（0.80 / 0.60）",
                    "质量护栏的基线与阈值（召回 20/20、unresolved 0、哨兵 3/3）",
                    "提前止损的代理基线与阈值（4 项全留；其中 2 项重新分类为治疗定义项，规则值未动）",
                    "预算请求形态（ceiling 仍为 null）、金标冻结（20 条目标）与判据数值",
                ],
                "assistant_choices_awaiting_signature": [
                    "G2 取『加 T4』而非『把该止损项降级为诊断』（备选与理由记在 T4.alternative_considered；"
                    "签认时可否决，否决须同时移出该止损项）",
                ],
                "no_signature_existed_before": True,
            },
        ],
        "not_done": [
            "未跑任何模型调用；未产生新候选池",
            "未裁定任何新条目；未改金标、契约、门、任何冻结件字节",
            "预算数值与阶段 2 的两个代理阈值留空/标注为提议，待 U 填或改写",
            "T4 与『治疗定义项 ⇒ 试验无效』的分类为 assistant 采择，签认时 U 可否决",
        ],
    }


SIGNOFF_MD = """# Claims 预注册判据（95 号）· 签认件

状态：草稿，**未签认**。`status = draft_pending_human_signature`。
本件只做一件事：在花预算与人工之前，把"产出侧修复后 claims 是否值得保留"的题目、臂、指标、退出规则写死。
零模型调用；不改任何冻结件字节。

## 一、题目

把 Claims 产出侧按已签 C1 口径修复（角色边界 / 坐标绑定 / 去冗余渲染）后，在**同一份冻结金标**（20 条目标）上重跑，
in-role 精度能否从 51/81 = 0.6296 抬到放行线之上，或直接过目标线？**结果决定 claims 的去留。**

## 二、臂

| 臂 | 内容 | 成本 |
|---|---|---|
| A 冻结基线 | 不跑，用已签 P1R5 池（0.6296 / 召回 20/20） | 0 |
| **B 治疗臂** | 产出侧三项修复后重跑（唯一实跑） | 一次实跑 + 一轮人工裁定 |

不跑消融臂（每个臂都要一轮人工裁定）；边界情形再单独立项归因。

## 三、指标与读数轴（v2：读数轴 6 → 4；v3：补主指标分子定义）

**判定只用这 4 项**：`candidate_precision`（C1 口径、分母含 duplicate）、`target_recall`、`unresolved_candidates`、`sentinels`。

**已移出判定的轴（只出现在诊断块）**：
- `accepted_records_total_min` / `accepted_records_per_source_min`：**已证与召回字面等价** —— claims 目标 20 条 / 每源 10 条 ⇒ floor(0.85×20)=17 ⟺ matched ≥ 17，floor(0.85×10)=8 ⟺ 分源召回 ≥ 0.80 ⇒ **零独立判别力**。该格（M1）已拒签，登记见 97 号。
- `per_source_precision`：诊断项，只报告不判定。

诊断（不进判定）：分源精度、FP 三分、FP allowance（目标线 ≤12 条、放行线 ≤85 条）。

**主指标口径（v3 补分子，此前只写了分母）**：`candidate_precision` = 分子 / 分母

- 分子 = `matched + correct_extra`（与已签 C2 `claims_precision_single_source` 同源；`correct_extra` 属分子，**不得挪入分母、不得改判 matched**）
- 分母 = `matched + correct_extra + incorrect + duplicate`（= in-role 池全部条目；**分母含 duplicate**，与 C2 单一口径一致）
- 冻结池算例：(20 matched + 31 correct_extra) / 81 = **51/81 = 0.6296**

**连带读法（v3）**：accepted 轴退出判定后，**91 号放行线的前提「D-1 ≠ a」自然消解**（登记见第四节）。

## 四、91 号放行线的读法（v3 新增登记项）

- **读作无条件 PASS**：91 号 `verdict.release_line.precondition = "D-1 ≠ a"` 的成立基础是"D-1 仍是判定轴"；accepted 下限已证与 `target_recall` 字面等价（零独立判别力）并移出判定 ⇒ 前提失去所指，放行线 PASS **不带前提，也不再等 D-1 裁定**。
- **取代 97 号 `consequences[3]`**：97 号那句"仍人工读作 pending_caliber"写于该轴移出判定之前；**97 号字节一字不改**，本项即其取代读法。
- **只改读法、不改记录**：91 号字节与原文 precondition、目标线终态（FAIL + 不可达登记）、放行线的功能线性质（PASS ≠ 质量达标）都不变；D-2（分源精度轴）仍未裁、只报告不 gating。
- 本项落在本件内、随本件签认生效，不与 93/94 的 R1–R4 规则捆绑。

## 五、退出规则（结果出来前写死）

**先判试验有效性（v3 拆出）**：治疗定义项 = `role_external_candidates == 0`（T1 的验收）、`unbound_fields_without_reason_code == 0`（T4 的验收）。
**这两项失败 ⇒ 试验无效**：不计入去留，也**不得**读成"C 档：claims 差"——它说明治疗没做对，不说明 claims 差。

| 档 | 条件 | 后果 |
|---|---|---|
| A 保留并过目标线 | 精度 ≥ 0.80 且**质量护栏全绿**（召回 20/20、unresolved 0、哨兵 3/3） | 保留，进入发布/消费下一阶段 |
| B 有条件保留 | 0.60 ≤ 精度 < 0.80 且**质量护栏全绿**（同上） | 停在功能线，登记目标线不可达 |
| C 降级退出 | 精度 < 0.60 或**质量护栏任一破**（同上三项任一） | claims 退出默认路径，指标断言由 items 侧承接 |

档位只由"主指标 + 质量护栏"决定；**治疗定义项不出现在任何档位条件里**。

**提前止损（阶段 2，零调用）**：角色外候选须 = 0（owner T1）；未绑并集（字段级缺 ∪ reason 码）须 ≤ 54 × 0.5（owner T2）；冗余渲染须 = 0（owner T3）；"缺字段却无阻断码"须 = 0（owner T4）。
每个止损项都恰有一条预注册治疗规则承担；**没有 owner 的止损项不得起跑**。
未达则不进入人工裁定（阶段 3），直接判"产出侧修复未达预期"。

## 六、确定性治疗的实测天花板（零调用；给"新分怎么读"定标尺）

在冻结池上重放**"删条目"型**治疗（能继承旧裁定的那部分）：

| 变体 | 保留 | 精度 | 召回 |
|---|---|---|---|
| D2 基线（C1 口径） | 81 | 51/81 = **0.6296** | 20/20 |
| ＋去冗余 | 79 | 51/79 = **0.6456** | 20/20 |
| 缺坐标"不产出" | 56 | 39/56 = 0.6964 | **19/20 ❌** |
| 上两者叠加 | 55 | 39/55 = 0.7091 | **19/20 ❌** |

- **不破召回的安全上限 = 0.6456**；破护栏上限 = 0.7091 ⇒ **目标线 0.80 只能来自"把缺的坐标补回原文"（重抽），不可能来自删条目**。
- 所以新分的读法：明显高于 0.65 ⇒ 重抽确实补回了坐标；停在 0.65 附近 ⇒ 补回没发生。

## 七、治疗臂的四条预注册规则（现在写死，否则结果无法归因）

**对账要求**：四条规则与阶段 2 的四个止损项一一对应；**没有 owner 的止损项不得起跑**。

| 治疗规则 | 内容 | 验收它的止损项 | 类别 |
|---|---|---|---|
| T1 去 opinion | 按已签 C1 不再产出 opinion / 无 value 的候选（对齐口径） | 角色外候选 = 0 | 治疗定义项 |
| T2 缺坐标=补齐 | 一律"补齐"，不得"不产出" | 未绑并集 ≤ 54 × 0.5 | 质量代理 |
| T3 去冗余 | 同 subject+metric+引用区间合并为一条；并列按"坐标更完整 > value 与引用一致 > 文件序" | 冗余渲染 = 0 | 质量代理 |
| **T4 缺字段必标码（v3 新增）** | 缺 subject/metric/period/unit 任一 ⇒ 产出时必须带对应 reason 码；"补齐字段"与"标出阻断码"二者必居其一 | "缺字段却无阻断码" = 0 | 治疗定义项 |

- **T1**：在现口径上**不加分**（C1 过滤已含在 D2 内）。
- **T2**：实测"不产出"会丢掉命中的金标 **NT-C17** ⇒ 召回 19/20、护栏当场破。**这一条不是判断，是实测排除了另一个选项。**
- **T3**：**禁止使用金标或裁定结果做并列依据**。载重提示：`归母净利润` 那组同时含 matched(NT-C03) 与 duplicate，规则选错即掉召回。
- **T4**：此前"缺字段却无阻断码 = 0"这一止损项**没有任何治疗规则承担**（该闸门在无治疗时恒不可达）；T4 是它的对应治疗。零额外模型调用（同一轮产出的仪器化），但工程缺件 +1（标码路径）。备选方案是"把该止损项降级为诊断"——**未采纳**（会让 reason 码漏标这一缺陷在本轮无人承担；它正是"拿 reason 当门"低估缺陷的根因），签认时 U 可否决。

## 八、对既有记录的更正（零调用复核得出）

- **撤回** 83/84 号的"7 条结构齐备仍不匹配 = 同坐标多次渲染（目标价×4、动态PE隐含市值×3）"：
  实测该 7 条 = GPU/ASIC 组 2 条（同引用双数）+ 4 条**缺 period 却未被标码** + 1 条确不匹配（成交额 103.15 亿元）。
- 去冗余的真实规模 = **2 组、删 2 条**（GPU/ASIC 组两条都 incorrect；归母净利润 组 = matched + duplicate）。
- **reason 码漏标 9 条**（in-role 全体）⇒ 代理指标一律用"字段级缺 ∪ reason 码"的并集，不用单一 reason 码口径。

## 九、公平性条款（重要）

审计显示最大的绑定族是 **metric_binding(94) 与 subject_binding(67)**，且 subject 类条目**全部**还带至少一条非 subject 阻断理由。
因此治疗臂**必须**覆盖这五个族，否则试验会低估 claims、进而错误地把它淘汰掉。

## 十、预算请求（数值待 U 填）

- 阶段 1：两源同配置一次全量抽取（历史同类单源轮次实测 17 次调用 / 上限 10 attempts）⇒ 上限待填
- 阶段 2：零调用
- 阶段 3：新池人工裁定 ≈ in-role 池容量量级（P1R5 为 xyl×110）——**真正的成本大头**

## 十一、硬约束（不属于待裁）

- 不改金标（20 条目标）、不改判据、不改判定；不跑第二臂；不换模型
- 未填预算、未签认 ⇒ 不得起跑
- 未写入本件退出规则的分，不得用于去留
- 读数轴已收敛为 4 项，**不得在结果出来后再把被排除的轴加回来**
- **治疗定义项失败 ⇒ 试验无效**，不得读成 C 档；档位条件里不含治疗定义项
- 91 号放行线按第四节读作**无条件 PASS**（只改读法，不改 91/97 号任何字节）

## 签名

reviewer: ____________    adjudicator: ____________    signed_on: ____________
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true", help="只打印摘要，不写文件")
    parser.add_argument("--force", action="store_true", help="允许覆盖本目录内已存在的输出")
    args = parser.parse_args()

    prereg = build()
    outputs = {
        "claims-preregistration.json": (
            json.dumps(prereg, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
        "claims-preregistration-signoff.md": SIGNOFF_MD.encode("utf-8"),
    }
    manifest = {
        "schema_version": "claims-preregistration-manifest-1",
        "status": "draft",
        "created_on": PREREG_ON,
        "model_calls": 0,
        "inputs": {name: sha256(path) for name, path in INPUTS.items()},
        "outputs": {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()},
        "does_not_touch": [
            "evidence/10-quality-gold-freeze-20261008-r2/**",
            "evidence/17-structured-extraction-convergence-closure-20261009/**",
            "evidence/88-claims-contract-v44-signed-20261014/**",
            "evidence/91-claims-gate-v3-signed-20261014/**",
            "evidence/93-claims-governance-plan-20261014/**",
            "evidence/97-claims-governance-refusal-20261014/**",
        ],
        "blocked_on": ["budget_request.stage_1_live_run.requested_ceiling 由 U 填", "签认"],
    }
    outputs["MANIFEST.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )

    if args.no_write:
        print(json.dumps(prereg["evidence_chain"], ensure_ascii=False, indent=2))
        print(json.dumps(prereg["exit_rules"]["tiers"], ensure_ascii=False, indent=2))
        print(f"[no-write] {len(outputs)} outputs computed; nothing written.")
        return 0

    # Guard every target before writing any of them: a signed instrument must never be regenerated,
    # not even with --force, and an all-or-nothing check keeps the package self-consistent.
    targets = {name: HERE / name for name in outputs}
    for name, target in targets.items():
        assert_writable(target, reason="95 号预注册 v3（草案态就地改）")
        if target.exists() and not args.force:
            raise SystemExit(f"refusing to overwrite existing output {name}; use --force")
    for name, data in outputs.items():
        write_once(targets[name], data.decode("utf-8"), allow_overwrite=True)
    print(f"wrote {len(outputs)} files to {HERE}")
    print(json.dumps(manifest["outputs"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
