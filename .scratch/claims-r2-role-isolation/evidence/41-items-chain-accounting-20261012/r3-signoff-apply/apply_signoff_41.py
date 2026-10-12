"""Issue 41 · 签认落地（零调用、只读输入、幂等）。

用户于 2026-10-12 在 `issues/41-items-chain-accounting-freeze.md` §10 签认
「认可口径并准予继续」（复核人 xyl）。§6 的逐项勾选未填，故本脚本只落地方向无关的四项，
并把唯一的分叉项（阈值方向）留成显式占位 `PENDING_SIGNOFF`，不代选。

产出（全部写入本目录，不修改任何既有产物）：
1. ``freeze-rebinding-record.json``   —— AC-1 金标冻结链契约绑定 v2→v3 漂移的再绑定记录
2. ``gold-acceptance-record.json``    —— AC-7 从 frozen-gold 自身字段确定性投影出验收计数
3. ``scoring-contract-v4.proposed.json`` —— C1/C2 契约 v4 提案（v3 内容逐字保留 + 新条款）
4. ``gate-32-v2-criteria.proposed.json`` —— AC-8 门 32 判据拆成 G1/G2 的提案
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CLAIMS = HERE.parents[2]
EV = CLAIMS / "evidence"

GOLD = EV / "10-quality-gold-freeze-20261008-r2" / "frozen-gold.json"
FREEZE_MANIFEST = EV / "10-quality-gold-freeze-20261008-r2" / "freeze-manifest.json"
FREEZE_STATE = EV / "10-quality-gold-freeze-20261008-r2" / "freeze-state.json"
CONTRACT_V3 = EV / "10-quality-gold-expansion-20261008-r2" / "scoring-contract.json"
VALIDATION = EV / "10-quality-gold-expansion-20261008-r2" / "validation-report.json"
GATE32 = EV / "32-items-v6-reasoning-refreeze-20261011" / "r0-zero-call" / "preregistered-gate.json"
GATE32_DECISION = EV / "32-items-v6-reasoning-refreeze-20261011" / "live" / "gate-decision.json"

APPLIED_ON = "2026-10-12"
SIGNOFF_BASIS = (
    "user_chat_2026-10-12: 已在 issues/41-items-chain-accounting-freeze.md §10 签认"
    "「认可口径并准予继续」（复核人 xyl）；§6 逐项勾选未填"
)

G1_KEYS = (
    "protocol_status",
    "reasoning_tokens_must_be_zero_or_absent",
    "control_arm_must_reproduce_failure",
)
G2_KEYS = (
    "attempts_match_plan",
    "no_http_429",
    "no_automatic_retries",
    "failed_partial_invalid_duplicate_batches_max",
    "completed_min",
    "execution_status",
    "context_status",
)
# 门内判据键名与判定文件键名不同，本表把两者对应，避免将来按名字对不上。
DECISION_KEY_MAP = {
    "protocol_status": "protocol_status_valid",
    "reasoning_tokens_must_be_zero_or_absent": "reasoning_tokens_zero_or_absent",
    "control_arm_must_reproduce_failure": "control_arm_reproduced_failure",
    "failed_partial_invalid_duplicate_batches_max": (
        "failed_partial_invalid_duplicate_batches_max_0"
    ),
    "execution_status": "execution_status_succeeded",
    "context_status": "context_status_complete",
}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, payload: dict[str, Any]) -> None:
    (HERE / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def build_rebinding(
    manifest: dict[str, Any],
    freeze_state: dict[str, Any],
    contract: dict[str, Any],
    gold: dict[str, Any],
) -> dict[str, Any]:
    recorded = next(
        value for key, value in manifest["inputs"].items() if key.endswith("scoring-contract.json")
    )
    return {
        "schema_version": "items-gold-freeze-contract-rebinding-1",
        "created_on": APPLIED_ON,
        "signoff_basis": SIGNOFF_BASIS,
        "issue": "41-items-chain-accounting-freeze",
        "check": "AC-1",
        "finding": (
            "the gold freeze chain recorded the pre-signoff contract v2 hash while the signed "
            "contract is v3; gate 28 was rebound to v3 by issue 30 but the freeze chain was not"
        ),
        "frozen_records": {
            "freeze_manifest": {
                "path": str(FREEZE_MANIFEST),
                "sha256": digest(FREEZE_MANIFEST),
                "recorded_contract_sha256": recorded,
            },
            "freeze_state": {
                "path": str(FREEZE_STATE),
                "sha256": digest(FREEZE_STATE),
                "embedded_contract_schema_version": freeze_state["contract_snapshot"][
                    "schema_version"
                ],
                "embedded_contract_status": freeze_state["contract_snapshot"]["status"],
            },
            "frozen_gold": {
                "path": str(GOLD),
                "sha256": digest(GOLD),
                "self_recorded_contract_sha256": gold.get("scoring_contract_sha256"),
            },
        },
        "actual_signed_contract": {
            "path": str(CONTRACT_V3),
            "sha256": digest(CONTRACT_V3),
            "schema_version": contract["schema_version"],
            "status": contract["status"],
        },
        "rebinding": {
            "effective_binding": digest(CONTRACT_V3),
            "supersedes_recorded_binding": recorded,
            "scope": (
                "bookkeeping only: the frozen gold bytes, the freeze manifest and the freeze "
                "state are NOT modified; this record is the traceable successor binding"
            ),
            "consequence_to_state_explicitly": (
                "the gold was frozen against the v2 required-field list (proposition required, no "
                "condition read path); v3 added the read path and v4 adds the carrier mapping, so "
                "any statement of the form 'the gold is bound to the scoring contract' must cite "
                "this record, not the freeze manifest alone"
            ),
        },
        "not_modified": [
            str(FREEZE_MANIFEST),
            str(FREEZE_STATE),
            str(GOLD),
            str(CONTRACT_V3),
        ],
    }


def build_acceptance(gold: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    by_role: dict[str, dict[str, int]] = {}
    for record in gold["records"]:
        role = record["role"]
        status = record["review_status"]
        by_role.setdefault(role, {})
        by_role[role][status] = by_role[role].get(status, 0) + 1
    with_adjudication = sum(1 for record in gold["records"] if record.get("adjudication"))
    return {
        "schema_version": "items-gold-acceptance-record-1",
        "created_on": APPLIED_ON,
        "signoff_basis": SIGNOFF_BASIS,
        "issue": "41-items-chain-accounting-freeze",
        "check": "AC-7",
        "finding": (
            "the draft validation report still reads status=valid_review_draft with "
            "human_accepted_counts={} and formal_gold_frozen=false, while the freeze state "
            "declares formal_gold_frozen=true; the freeze chain has no machine-readable "
            "acceptance record"
        ),
        "method": (
            "deterministic projection of frozen-gold's own per-record review_status and "
            "adjudication fields; nothing is asserted that the frozen gold does not already carry"
        ),
        "source": {
            "frozen_gold": str(GOLD),
            "sha256": digest(GOLD),
            "records": len(gold["records"]),
            "formal_gold_frozen": gold["formal_gold_frozen"],
            "reviewer": gold["reviewer"],
            "adjudicator": gold["adjudicator"],
            "frozen_on": gold["frozen_on"],
            "signoff_evidence": gold.get("signoff_evidence"),
        },
        "projected_human_accepted_counts": by_role,
        "projected_human_accepted_total": sum(
            count for role in by_role.values() for count in role.values()
        ),
        "records_with_adjudication": with_adjudication,
        "draft_validation_report": {
            "path": str(VALIDATION),
            "sha256": digest(VALIDATION),
            "status": validation["status"],
            "human_accepted_counts": validation["human_accepted_counts"],
            "formal_gold_frozen": validation["formal_gold_frozen"],
            "note": (
                "that report is the pre-freeze draft; it is not modified here. This record is the "
                "successor acceptance view, derived from the frozen gold itself."
            ),
        },
        "does_not_modify": [str(GOLD), str(VALIDATION)],
    }


def build_contract_v4(contract: dict[str, Any], freeze_state: dict[str, Any]) -> dict[str, Any]:
    v4 = json.loads(json.dumps(contract))
    v3_hash = digest(CONTRACT_V3)
    v4["schema_version"] = "non-table-selected-target-scoring-contract-v4"
    v4["status"] = "proposed_pending_signoff"
    v4["supersedes"] = {
        "schema_version": contract["schema_version"],
        "status_at_supersede": contract["status"],
        "sha256": v3_hash,
        "note": (
            "v3 signed the condition read path but left the general carrier question open; v4 adds "
            "the carrier mapping, the absent-field notation and the single threshold source. v3 "
            "content is preserved verbatim and its hash stays traceable."
        ),
    }
    v4["revision_history"] = [
        *contract["revision_history"],
        {
            "revision": "v4",
            "revised_on": APPLIED_ON,
            "authors": "agent",
            "signed_by": None,
            "basis": SIGNOFF_BASIS,
            "changes": [
                "新增 items_field_carrier_read_path：候选 text 视为 proposition 载体；只搬字段名，禁止改写。",
                "新增 absent_required_fields：候选未携带的契约必需字段显式记 absent，禁止从金标回填。",
                "新增 equivalence_judgement：等价性由人工裁定，评分器消费裁定、不得按身份相等自行匹配。",
                "新增 threshold_single_source：阈值与断言清单单一来源；方向待具名签认（见该字段 PENDING_SIGNOFF）。",
                "matching.items 引用 items_field_carrier_read_path。",
                "未改动任何已签认条款的语义；未改动金标与冻结构件。",
            ],
        },
    ]
    v4["signoff"] = {"signed_by": None, "signed_on": None, "statement": "pending human signoff"}
    v4["items_field_carrier_read_path"] = {
        "applies_to": "role == 'material_items'",
        "authoritative_side": (
            "冻结金标（48/48 逐字可回取、xyl 签认、Issue 29 判定 gold_meaning_sound=true）"
        ),
        "carrier_mapping": {
            "rule": (
                "裁定前允许且仅允许做确定性载体映射：候选 `text` 视为契约 `proposition` 的载体。"
                "映射只改字段名，不生成、不改写、不摘要任何语义文本。"
            ),
            "forbidden": (
                "不得从金标反填候选缺失字段；不得把目标字符串直接赋给候选；不得为凑匹配而重写候选文本。"
            ),
            "recording": (
                "映射后的字段集记入 canonical_observed_fields；未映射的契约必需字段必须显式记为 "
                "absent，不得留空、不得猜测。"
            ),
        },
        "absent_required_fields": {
            "list": ["attribution", "source_stance", "speaker_ref"],
            "rule": (
                "候选未携带上述字段时，canonical_observed_fields 记 absent，等价性判定按契约 "
                "unknowns 条款处理；不得因缺字段直接判不匹配，也不得补造。"
            ),
            "condition_role_addition": (
                "statement_role == 'condition' 且候选无 condition 载体时，裁定人须逐条判定候选 "
                "text 是否表达了该条件，并在 reason 记录判据。"
            ),
            "evidence": (
                "实测：候选侧 proposition 键存在数 0、speaker_ref/attribution/source_stance 载体 0 "
                "（evidence/36-l9-redo；evidence/39）"
            ),
        },
        "equivalence_judgement": {
            "owner": "human adjudicator",
            "rule": (
                "等价性一律由人工判定（沿用 matching.mode）；评分器不得自行按字段相等推导匹配。"
            ),
            "scorer_contract": (
                "评分器只消费裁定完成的映射，并校验其 role/source_id 合法性与 "
                "canonical_observed_fields 是否齐备；身份相等不得作为匹配前提。"
            ),
            "evidence": (
                "实测：现有评分器按 (role, source_id, origin, semantic_fields) 严格相等匹配"
                "（structured_scoring.py:118-142,457）；契约合法操作下自动匹配数 = 0"
            ),
        },
        "condition_role": "沿用 v3 的 condition_role_read_path（含 compound_condition 子规则）。",
        "audit_reference": "Issue 34 chain-report §5.2/§11；Issue 36/37/38/39/40/41 实测。",
    }
    v4["threshold_single_source"] = {
        "rule": (
            "召回/精确率/未裁定上限/断言清单以本契约与签认门为唯一来源；任何实现方不得另存一份。"
        ),
        "conflict_resolution": (
            "实现值与契约不一致时以已签认来源为准，实现方须改为读取或与契约同步，变更须具名签认。"
        ),
        "required_alignment": "PENDING_SIGNOFF",
        "pending_signoff_detail": {
            "fork": (
                "门 28（signed）为 target_recall_overall_min=0.85 / candidate_precision_min=0.80；"
                "评分器实现为 0.95 / 0.90（structured_scoring.py:334-339）"
            ),
            "options": [
                "A：以门 28 为权威（0.85 / 0.80），改评分器实现",
                "B：维持评分器现值（0.95 / 0.90）并改门",
            ],
            "why_not_chosen": (
                "阈值变更须具名签认；用户本次签认为文件级「准予继续」，未勾选该分叉，故不代选。"
            ),
        },
        "already_verified": {
            "gate28_contract_binding": "PASS（issue 41 AC-2）",
            "gate28_high_risk_assertions": "PASS：16 条 == 契约 items 断言子集（issue 41 AC-10）",
        },
    }
    v4["matching"]["items"] = (
        v4["matching"]["items"]
        + " 候选侧：non-condition 角色的可匹配原子命题按 items_field_carrier_read_path 由候选 "
        "text 承载（仅载体映射，不得改写）。"
    )
    return v4


def build_gate32_v2(gate: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    original = gate["exit_criteria"]
    original_keys = set(original)
    covered = set(G1_KEYS) | set(G2_KEYS)
    if covered != original_keys:
        raise ValueError(f"criteria split mismatch: {sorted(original_keys ^ covered)}")
    return {
        "schema_version": "items-v6-reasoning-gate-criteria-v2-proposed",
        "created_on": APPLIED_ON,
        "status": "proposed_pending_signoff",
        "signoff_basis": SIGNOFF_BASIS,
        "issue": "41-items-chain-accounting-freeze",
        "check": "AC-8",
        "supersedes_criteria_of": {
            "path": str(GATE32),
            "sha256": digest(GATE32),
            "note": "原判据与判定文件留存可追溯；本文件只重排分组，不改任何判据内容与阈值。",
        },
        "defect": (
            "门 32 的 verdict=structural_fail 与 root_cause_status=eliminated 并列，且未规定哪个代表"
            "本次执行结论；protocol_status_valid 因 items task 未成功而 not_checked ⇒ 一次与协议无关的"
            "传输事件即可使『协议修复』无法被单独确认"
        ),
        "decision_evidence": {
            "path": str(GATE32_DECISION),
            "sha256": digest(GATE32_DECISION),
            "verdict": decision["verdict"],
            "criteria_unmet": decision["criteria_unmet"],
            "protocol_violation_batches": decision["protocol_violations_unsupported_jsonl_record"],
            "root_cause_status": decision["attribution"]["root_cause_status"],
        },
        "group_g1_measured_object": {
            "question": "协议修复是否成立（被测对象）",
            "criteria_keys": list(G1_KEYS),
            "criteria": {key: original[key] for key in G1_KEYS},
            "conclusion_rule": (
                "G1 独立出结论：control 臂协议违规批次数 > 0 且 treatment 臂 == 0 且校验器未放宽，"
                "即记 protocol_fix_confirmed 并附两臂数字；不因 G2 未满足而被否决。"
            ),
        },
        "group_g2_structural_completeness": {
            "question": "本次执行在结构上是否完整（与协议无关的通过条件）",
            "criteria_keys": list(G2_KEYS),
            "criteria": {key: original[key] for key in G2_KEYS},
            "conclusion_rule": (
                "任一项未满足记 structural_incomplete，并逐项归因 infrastructure / our_rule / model；"
                "放行仍要求 G1+G2 同时满足。"
            ),
        },
        "original_exit_criteria": original,
        "gate_key_to_decision_key": DECISION_KEY_MAP,
        "observed_values_in_this_run": {
            "protocol_status": decision["criteria"]["protocol_status_valid"]["observed"],
            "failed_partial_invalid_duplicate_batches_max": decision["criteria"][
                "failed_partial_invalid_duplicate_batches_max_0"
            ]["observed_packet_statuses"],
            "execution_status": decision["criteria"]["execution_status_succeeded"]["observed"],
            "control_arm": decision["criteria"]["control_arm_reproduced_failure"]["detail"],
            "treatment_protocol_violations": decision[
                "protocol_violations_unsupported_jsonl_record"
            ]["treatment"],
        },
        "unchanged_guarantees": [
            "阈值、授权四项、终态判定文本未改",
            "放行条件未放宽（G1+G2 同时满足）",
            "原门哈希与判定文件未修改",
        ],
    }


def main() -> None:
    manifest = load(FREEZE_MANIFEST)
    freeze_state = load(FREEZE_STATE)
    contract = load(CONTRACT_V3)
    gold = load(GOLD)
    validation = load(VALIDATION)
    gate = load(GATE32)
    decision = load(GATE32_DECISION)

    write("freeze-rebinding-record.json", build_rebinding(manifest, freeze_state, contract, gold))
    write("gold-acceptance-record.json", build_acceptance(gold, validation))
    write("scoring-contract-v4.proposed.json", build_contract_v4(contract, freeze_state))
    write("gate-32-v2-criteria.proposed.json", build_gate32_v2(gate, decision))

    print(
        json.dumps(
            {
                "applied": [
                    "AC-1",
                    "AC-7",
                    "C1/C2 contract v4 (proposed)",
                    "AC-8 gate 32 v2 (proposed)",
                ],
                "pending_user_signoff": [
                    "threshold direction (A: gate 28 authoritative 0.85/0.80 | B: keep scorer 0.95/0.90)",
                ],
                "frozen_artifacts_modified": 0,
                "model_requests": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
