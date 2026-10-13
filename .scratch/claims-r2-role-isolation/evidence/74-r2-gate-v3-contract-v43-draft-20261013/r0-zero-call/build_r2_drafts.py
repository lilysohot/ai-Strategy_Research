#!/usr/bin/env python3
"""Draft the R2 remediation records: gate v3 + scoring contract v4.3 + re-adjudication draft.

R2 (U 2026-10-13 "先走 R2") changes the *judging basis*, not the extraction system:
  - recall thresholds stay byte-identical (the gate's own scope_constraints forbids
    post-execution threshold relaxation; R2 deliberately does not touch them)
  - the high-risk sentinel list drops the records that are structurally unreachable
    (gold split finer than the candidate, or an axis the candidate side cannot carry)
  - the remaining sentinel items are recovered by re-adjudication under an explicit
    "contextually unique recovery" clause

Everything is a DRAFT: sign-off fields stay null. No existing file is modified; old
hashes are retained in revision_history. Machine checks fail the run on any violation.

Read-only on every input. --no-write computes, prints and checks without writing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
E = REPO_ROOT / ".scratch/claims-r2-role-isolation/evidence"
SCRATCH = REPO_ROOT / ".scratch/claims-r2-role-isolation"

GATE_V2 = E / "28-items-only-quality-gate-20261010/r0-zero-call/preregistered-gate-v2.json"
CONTRACT_V42 = E / "58-contract-v42-signed-20261012/r0-zero-call/scoring-contract-v4.2.json"
ATTRIBUTION = E / "71-fn-attribution-20261013/r0-zero-call/fn-attribution.json"
GOLD = E / "10-quality-gold-freeze-20261008-r2/frozen-gold.json"
GATE33_GOLD = E / "33-items-quality-scoring-20261011/r0-zero-call/adjudications.json"
WORKSHEET = SCRATCH / "adjudication/worksheet.json"
TERMINAL = E / "72-gate33-terminal-and-corrections-20261013/r0-zero-call/terminal-decision.json"

SOURCE_LABEL = {
    "sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb": "源1",
    "sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f": "源2",
}

# sentinel records dropped from "must cover", each with a machine-readable mechanism
SENTINEL_EXCLUSIONS: dict[str, dict[str, str]] = {
    "NT-I09": {
        "mechanism": "gold_split_finer_than_candidate",
        "reason": (
            "金标把同一原文句拆成『条件(I09)+结论(I10)』两条，候选侧只产出整句一条且已被 NT-I10 占用；"
            "在 one_to_one_mapping 下必有一条落空（契约 §8.1：一条混合输出不能抵扣多个金标命题）。"
        ),
    },
    "NT-I19": {
        "mechanism": "gold_split_finer_than_candidate",
        "reason": "同 NT-I09：I19 与 I20 为同一句的两种切分，候选整句被 NT-I20 占用。",
    },
    "NT-I45": {
        "mechanism": "candidate_side_cannot_carry_axis",
        "reason": (
            "U 2026-10-12 校准撤销 matched：金标属被转述且被质疑的预测"
            "(perspective=quoted_other, source_stance=challenged)，而契约 caliber_rules 记明 "
            "source_stance 生产端无载体、必须人工判定 ⇒ 候选侧结构上不承载该轴。"
        ),
    },
    "NT-I46": {"mechanism": "candidate_side_cannot_carry_axis", "reason": "同 NT-I45。"},
    "NT-I47": {"mechanism": "candidate_side_cannot_carry_axis", "reason": "同 NT-I45。"},
}

# records R2 proposes to re-adjudicate to matched: candidate text/quote are read back
# from the attribution evidence rather than retyped.
READJUDICATION_REQUIRED = ("NT-I38", "NT-I39", "NT-I48", "NT-I26", "NT-I34")
READJUDICATION_PAIR_ALTERNATIVES = ("NT-I23", "NT-I24")  # share one candidate: at most one
READJUDICATION_SEVENTH_CHOICE = (
    {
        "option": "I36_question_form",
        "gold_id": "NT-I36",
        "cost": "需承认疑问句可承载该金标命题（原裁定理由为『类比式问句，非金标肯定断言』）",
    },
    {
        "option": "I23_or_I24_double_assignment",
        "gold_id": "NT-I23+NT-I24",
        "cost": "需承认一条候选可抵扣两条金标命题 —— 与 one_to_one_mapping / 契约 §8.1 冲突，不推荐",
    },
    {
        "option": "one_of_u_calibration_revoked",
        "gold_id": "NT-I45|NT-I46|NT-I47",
        "cost": "需推翻 U 2026-10-12 校准中的 1 条（候选与金标逐字相同，但 source_stance 口径相反）",
    },
)

CONTRACT_ITEMS_CLAUSE = (
    "同义改写可接受；须保持一个原子命题、语义类型、话语角色、归属、否定、条件、行为意向。"
    "proposition 不用逐字字符串相等判定。condition 角色 items 的原子命题按 condition_role_read_path "
    "读取（condition 优先，proposition 兜底）。"
    "【v4.3 增补｜上下文唯一可恢复】候选省略承载主体或限定条件时，若裁定人能依据同一证据包内"
    "唯一可恢复的上下文确定其主体/限定，视为保持该原子命题；无法唯一恢复者仍判不匹配。"
    "本增补不适用于：①同一候选被邻近金标占用（one_to_one_mapping 优先，一条输出不得抵扣多条金标）；"
    "②候选为疑问句等非断言形态。裁定人须在 reason 中记录恢复所依据的上下文。"
)


def sha256_of(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def diff(old: Any, new: Any, prefix: str = "") -> list[dict[str, Any]]:
    """Structural diff of two JSON values: only leaves that actually changed."""
    changes: list[dict[str, Any]] = []
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            path = f"{prefix}.{key}" if prefix else key
            if key not in old:
                changes.append({"path": path, "op": "add", "new": new[key]})
            elif key not in new:
                changes.append({"path": path, "op": "remove", "old": old[key]})
            else:
                changes.extend(diff(old[key], new[key], path))
    elif isinstance(old, list) and isinstance(new, list):
        if old != new:
            changes.append({"path": prefix, "op": "replace", "old_count": len(old), "new_count": len(new)})
    elif old != new:
        changes.append({"path": prefix, "op": "replace", "old": old, "new": new})
    return changes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    gate_v2 = load(GATE_V2)
    contract_v42 = load(CONTRACT_V42)
    attribution = load(ATTRIBUTION)
    by_id = {r["record_id"]: r for r in load(GOLD)["records"] if r["role"] == "material_items"}
    g33 = {g["record_id"]: g for g in load(GATE33_GOLD)["gold_reference"]}
    rows = {r["gold_id"]: r for r in attribution["rows"]}
    # 契约形态的裁定必须保留候选原始记录：直接取 A 工作表的逐条原样记录
    worksheet_by_candidate = {
        rec["candidate_id"]: rec for rec in load(WORKSHEET)["records"]
    }
    contract_fields = list(load(CONTRACT_V42)["candidate_adjudication_fields"])

    gate_v2_sha = sha256_of(GATE_V2)
    contract_v42_sha = sha256_of(CONTRACT_V42)

    # ---------------------------------------------------------------- gate v3 draft
    gate_v3 = deepcopy(gate_v2)
    sentinel_v2 = list(gate_v2["quality_requirements"]["high_risk_item_assertions_required"])
    sentinel_v3 = [item for item in sentinel_v2 if item not in SENTINEL_EXCLUSIONS]
    annotations = gate_v2["quality_requirements"]["high_risk_item_annotations"]
    # 门的 metric_basis/契约绑定只推进到**最近一个已签**契约版本（v4.2），与契约 v4.3 之间
    # 保持「版本追逐」并将其显式登记：两者互相钉哈希会形成环，故不变量取「六项阈值逐字恒等」。
    gate_v3["quality_requirements"]["metric_basis"] = "non-table-selected-target-scoring-contract-v4.2"
    gate_v3["gold"]["scoring_contract_sha256"] = contract_v42_sha
    gate_v3["quality_requirements"]["contract_version_chase"] = {
        "gate_pins_signed_contract": "non-table-selected-target-scoring-contract-v4.2",
        "gate_pins_sha256": contract_v42_sha,
        "contract_next_version": "non-table-selected-target-scoring-contract-v4.3",
        "why_lag": (
            "契约 v4.3 反向钉门 v3 的签认字节；若门同时钉 v4.3 会形成哈希环，"
            "故门只推进到最近一个已签契约版本。"
        ),
        "invariant": "六项阈值逐字恒等（0.85/0.80/0.80/40/20/0）+ 哨兵清单与契约 review_assertions 的 NT-I* 子集恒等",
        "validator_required": "由校验器持续核查上述两条不变量，而非要求两处版本号相同",
        "registration_basis": "沿用已签契约 v4.2 签认记录 outstanding_after_signoff 中的建议（阈值恒等为不变量）",
    }
    gate_v3["quality_requirements"]["high_risk_item_assertions_required"] = sentinel_v3
    gate_v3["quality_requirements"]["high_risk_item_annotations"] = {
        key: value for key, value in annotations.items() if key in sentinel_v3
    }
    gate_v3["quality_requirements"]["high_risk_item_assertions_excluded"] = {
        key: SENTINEL_EXCLUSIONS[key] for key in sentinel_v2 if key in SENTINEL_EXCLUSIONS
    }
    gate_v3["quality_requirements"]["threshold_note"] = (
        "六项阈值逐字沿用 revision 5，未做任何放宽；R2 只调整『必须覆盖』的哨兵清单。"
    )
    gate_v3["status"] = "draft_pending_human_signature"
    gate_v3["quality_requirements_status"] = "proposed_pending_human_signoff"
    gate_v3["countersignature"] = {
        "required": True,
        "status": "pending_human_signoff",
        "reviewer": None,
        "signed_on": None,
    }
    gate_v3["revision_history"] = [
        *gate_v2["revision_history"],
        {
            "revision": 6,
            "revised_on": "2026-10-13",
            "authors": "agent",
            "signed_by": None,
            "basis": (
                "U 2026-10-13 指示『先走 R2』：在冻结金标与样本不变、且不放宽任何阈值的前提下，"
                "调整高风险哨兵清单并据『上下文唯一可恢复』口径重新裁定可达项。"
            ),
            "changes": [
                "quality_requirements.high_risk_item_assertions_required 由 16 项缩为 "
                f"{len(sentinel_v3)} 项，移出 {sorted(SENTINEL_EXCLUSIONS)}。",
                "新增 high_risk_item_assertions_excluded：逐条记录移出机制与依据。",
                "quality_requirements.metric_basis 由 -v4.1 推进一档至 -v4.2（最近一个已签契约版本）；"
                "gold.scoring_contract_sha256 同步再绑定至 v4.2 哈希。",
                "新增 quality_requirements.contract_version_chase：登记门 v3 与契约 v4.3 之间的版本追逐、"
                "不变量（阈值逐字恒等 + 哨兵与契约 NT-I* 子集恒等）与校验器要求。",
                "quality_requirements_status 由 signed 退回 proposed_pending_human_signoff；countersignature 退回 pending。",
                "六项阈值、执行要求、授权四项、scope_constraints（含 threshold_relaxation_after_execution_allowed=false）"
                "与冻结金标字节全部不变。",
            ],
            "previous_gate_sha256": gate_v2_sha,
        },
    ]
    gate_v3["terminal_decision_amendment"] = {
        "recorded_on": "2026-10-13",
        "note": (
            "原 terminal_decision.on_fail 要求关闭当前模型+抽取器路线、不放宽阈值；"
            "U 2026-10-13 的决定是不关闭路线，改为按 R2 调整判据基准。"
            "原字段逐字保留，本修订以独立键记录，便于审计对照。"
        ),
        "u_decision": "先走 R2（调整哨兵清单与重新裁定口径，不动阈值、不动金标、不动样本）",
    }

    # ------------------------------------------------- contract v4.3 draft
    contract_v43 = deepcopy(contract_v42)
    gate_v3_sha_placeholder = "sha256:PENDING_SIGNED_GATE_V3"
    contract_v43["schema_version"] = "non-table-selected-target-scoring-contract-v4.3"
    contract_v43["status"] = "draft_pending_human_signature"
    contract_v43["supersedes"] = {
        "schema_version": "non-table-selected-target-scoring-contract-v4.2",
        "status_at_supersede": "frozen_signed",
        "sha256": contract_v42_sha,
        "note": "v4.3 改两处：matching.items 增补『上下文唯一可恢复』条款；哨兵断言清单与门 v3 对齐。阈值数值逐字不变。",
    }
    contract_v43["revision_history"] = [
        *contract_v42["revision_history"],
        {
            "revision": "v4.3",
            "status": "draft_pending_human_signature",
            "created_on": "2026-10-13",
            "authors": "agent",
            "signed_by": None,
            "basis": "U 2026-10-13『先走 R2』；依据 evidence/71 FN 归因与 evidence/72 门 33 终态记录。",
            "changes": [
                "matching.items 增补『上下文唯一可恢复』条款及其两项不适用情形。",
                f"review_assertions 移出 {sorted(SENTINEL_EXCLUSIONS)}，移入新增 review_assertions_excluded。",
                "threshold_source.authority_source 由门 v2 改钉门 v3（签认后回填最终哈希）。",
                "六项阈值数值逐字不变（机器校验）。",
                "status 由 frozen_signed 退回 draft_pending_human_signature；signoff 清空为 pending。",
            ],
        },
    ]
    contract_v43["matching"]["items"] = CONTRACT_ITEMS_CLAUSE
    contract_v43["review_assertions"] = {
        key: value for key, value in contract_v42["review_assertions"].items() if key not in SENTINEL_EXCLUSIONS
    }
    contract_v43["review_assertions_excluded"] = SENTINEL_EXCLUSIONS
    contract_v43["metrics"]["quality_gate"] = (
        "度量基准版本链：v2 → v3 → v4 → v4.1 → v4.2 → **v4.3（本版，草案）**；"
        "其中 v4.3 把 matching.items 的读法写实（上下文唯一可恢复），并与门 v3 的哨兵清单对齐。"
        "六项阈值自 v2 起逐字未变。Issue 28 items-only 质量门本身及其计数器签认仍单独进行；"
        "未获得完整候选裁定、query/delivery/context_use 时不得宣告整体质量门通过。"
    )
    contract_v43["registrations"] = {
        "contract_version_chase": {
            "gate_v3_pins": "non-table-selected-target-scoring-contract-v4.2（最近一个已签契约版本）",
            "contract_v43_pins_gate": "门 v3 签认字节（签认后回填，见 threshold_source.authority_source）",
            "why": "双向钉哈希会形成环，故门只推进到最近已签版本，契约反向钉门。",
            "invariant": "六项阈值逐字恒等 + 门哨兵清单与契约 review_assertions 的 NT-I* 子集恒等",
            "validator_required": True,
        },
        "frozen_gold_side_contract_binding": {
            "status": "known_exception_registered",
            "detail": (
                "冻结金标侧记录的契约绑定仍为 v2（sha256:2eb24be7…），与现行契约版本不符；"
                "因冻结金标字节不可改（U 裁定『不改金标』），本轮登记为例外而不回填。"
            ),
            "exception_rule": "任何后续校验器遇到 gold 侧绑定落后时，应报『已登记例外』而非失败；"
            "若金标字节本身变更则必须重签。",
        },
        "supersedes_terminal_record": {
            "path": "evidence/72-gate33-terminal-and-corrections-20261013/r0-zero-call/terminal-decision.json",
            "field": "terminal_state.gate",
            "old_value": "FAIL（不可达）",
            "note": (
                "本契约 v4.3 与门 v3 经具名签认、且 7 条改判经 xyl 具名后，evidence/72 的『不可达』"
                "结论由新的出分记录取代；72 的字节不改写，仅以本条登记取代关系。"
            ),
        },
    }
    contract_v43["threshold_source"]["authority_source"]["where"] = (
        "门 28 preregistered-gate-v3.json quality_requirements（R2 修订，revision 6）"
    )
    contract_v43["threshold_source"]["authority_source"]["sha256"] = gate_v3_sha_placeholder
    contract_v43["threshold_source"]["authority_source"]["pin_status"] = (
        "provisional：门 v3 具名签认后须回填其最终字节哈希，本字段随之移除"
    )
    contract_v43["threshold_source"]["effective"]["source"] = (
        "门 28 preregistered-gate-v3.json quality_requirements"
    )
    contract_v43["signoff"] = {
        "signed_by": None,
        "signed_on": None,
        "statement": None,
        "instrument": None,
        "scope_note": "草案未签认；签认只定读路径、口径与度量口径，不代表 items-only 复验通过。",
        "reviewer_remark": None,
        "remark_note": None,
    }

    # ------------------------------------------------- re-adjudication draft
    # 契约形态：逐条保留 candidate_adjudication_fields 的 11 个字段，原始字段不改写。
    def stub(gid: str, keep_if: dict[str, str]) -> dict[str, Any]:
        row = rows[gid]
        best = row["nearest_candidates"][0]
        source = worksheet_by_candidate[best["candidate_id"]]
        record = {
            "candidate_id": source["candidate_id"],
            "stage": source["stage"],
            "role": source["role"],
            "source_id": source["source_id"],
            "original_candidate": source["original_candidate"],
            "judgement": source["judgement"],
            "matched_gold_id": source["matched_gold_id"],
            "canonical_observed_fields": source["canonical_observed_fields"],
            "reviewer": source.get("reviewer"),
            "reason": source.get("reason"),
            "evidence": source.get("evidence"),
            # —— 以下为本次草案新增，不改写上面 11 个原始字段 ——
            "proposed_judgement": "matched",
            "proposed_matched_gold_id": gid,
            "proposed_reason": (
                "按契约 v4.3 matching.items『上下文唯一可恢复』条款：候选省略的承载主体/限定可由同一证据包"
                "唯一恢复，视为保持该原子命题。裁定人须在具名时补记恢复所依据的上下文。"
            ),
            "gold_quote": row["quote"],
            "gold_proposition": row["proposition"],
            "gold_locator": row["locator"],
            "gold_source": row["source"],
            "previous_judgement": best["judgement"],
            "previous_reason": best["reason"],
            "previous_matched_gold_id": best["matched_gold_id"],
            "keep_if": keep_if,
            # 上列 reviewer/reason/judgement 属**被取代的**旧裁定（原样留档）；
            # 本次新裁定人在落地时才写入，草案阶段一律留空。
            "superseded_reviewer": source.get("reviewer"),
            "superseded_judgement": source["judgement"],
            "proposed_reviewer": None,
            "proposed_signed_on": None,
            "status": "agent_draft_pending_named_signoff",
        }
        missing = [field for field in contract_fields if field not in record]
        assert not missing, f"{gid} 缺契约字段 {missing}"
        return record

    required = [stub(gid, {"rule": "always"}) for gid in READJUDICATION_REQUIRED]
    pair = [
        stub(gid, {"rule": "pair_choice", "picked_id": gid}) for gid in READJUDICATION_PAIR_ALTERNATIVES
    ]
    seventh = [
        stub("NT-I36", {"rule": "seventh_choice", "picked_id": "I36_question_form"}),
        stub("NT-I45", {"rule": "seventh_choice", "picked_id": "one_of_u_calibration_revoked"}),
        stub("NT-I46", {"rule": "seventh_choice", "picked_id": "one_of_u_calibration_revoked"}),
        stub("NT-I47", {"rule": "seventh_choice", "picked_id": "one_of_u_calibration_revoked"}),
    ]
    adjudications = required + pair + seventh
    required_golds = [r["proposed_matched_gold_id"] for r in required]
    pair_golds = [r["proposed_matched_gold_id"] for r in pair]
    seventh_golds = [r["proposed_matched_gold_id"] for r in seventh]
    readjudication = {
        "schema_version": "r2-readjudication-draft-1",
        "created_on": "2026-10-13",
        "zero_model_calls": True,
        "status": "agent_draft_pending_named_signoff",
        "authority_note": (
            "机械生成的改判草案，**不是裁定**。每条须由 xyl 具名确认；未具名前不得进入评分。"
        ),
        "contract_form": {
            "fields": contract_fields,
            "source": "契约 adjudication_clause.required_per_record_fields（11 字段）",
            "rule": "原始 11 字段逐字保留、不改写；本次新增字段一律以 proposed_/keep_if 前缀置于其后。",
        },
        "selection_rules": {
            "always": "必需 5 条：I38/I39/I48/I26/I34",
            "pair_choice": "二选一：I23 与 I24 共享同一候选，具名时只能保留其中一条（详见签认件第 7 条下方勾选栏）",
            "seventh_choice": "第 7 条：I36 / I45 / I46 / I47 四条候选，具名时按签认件所勾选项保留一条",
            "landed_count": "落地后应为 5 + 1 + 1 = 7 条，且候选互不重复（apply_r2_signoff.py 强制校验）",
        },
        "adjudications": adjudications,
        "seventh_flip_open_choice": list(READJUDICATION_SEVENTH_CHOICE),
        "explicitly_not_flipped": [
            {
                "gold_id": "NT-I31",
                "reason": "最近候选已被 NT-I32 占用；改判将与 one_to_one_mapping 冲突（与 I09/I19 同机制）。",
            },
            {
                "gold_id": "NT-I23/NT-I24",
                "reason": "二者共享同一候选，只能取一；另一条保持原裁定 correct_extra。",
            },
        ],
        "signoff": {"reviewer": None, "signed_on": None},
    }

    # ------------------------------------------------- projection
    matched_now = set(
        load(E / "69-union-adjudication-20261013/r1-score/gate33-honest-score.json")["matched_gold_ids"]
    )
    base_flip = [*required_golds, pair_golds[0]]  # 二选一在投影中取 I23（另一条同分，选项等价）
    projections = []
    for choice in READJUDICATION_SEVENTH_CHOICE:
        if choice["option"] == "I23_or_I24_double_assignment":
            continue  # contract-invalid, reported separately
        extra = set(base_flip) | {choice["gold_id"].split("|")[0]}
        proj = matched_now | extra
        per_source = {}
        for sid, label in SOURCE_LABEL.items():
            gold_ids = [rid for rid, rec in by_id.items() if rec["source_id"] == sid]
            hit = [rid for rid in gold_ids if rid in proj]
            per_source[label] = {"matched": len(hit), "gold": len(gold_ids), "recall": round(len(hit) / len(gold_ids), 3)}
        covered = [g for g in sentinel_v3 if g in proj]
        thresholds = gate_v2["quality_requirements"]
        projections.append(
            {
                "seventh_flip": choice["option"],
                "flips": sorted(extra),
                "recall_overall": round(len(proj) / 48, 3),
                "per_source": per_source,
                "sentinel_covered": f"{len(covered)}/{len(sentinel_v3)}",
                "thresholds_used": {
                    "target_recall_overall_min": thresholds["target_recall_overall_min"],
                    "target_recall_per_source_min": thresholds["target_recall_per_source_min"],
                },
                "projected_verdict": (
                    "PASS"
                    if len(proj) / 48 >= Fraction(85, 100)
                    and all(v["recall"] >= 0.8 for v in per_source.values())
                    and len(covered) == len(sentinel_v3)
                    else "FAIL"
                ),
                "cost": choice["cost"],
            }
        )
    projection = {
        "schema_version": "r2-projection-1",
        "created_on": "2026-10-13",
        "label": "PROJECTION_ONLY",
        "note": (
            "本块是**未签认投影**，不是 verdict。只有门 v3 与契约 v4.3 具名签认、"
            "且 7 条改判由 xyl 具名确认之后，才可据实重算出分并形成新 verdict。"
        ),
        "sentinel_count_v2": len(sentinel_v2),
        "sentinel_count_v3": len(sentinel_v3),
        "projections": projections,
        "contract_invalid_option": {
            "option": "I23_or_I24_double_assignment",
            "why": "一条候选抵扣两条金标，违反 one_to_one_mapping 与契约 §8.1；本草案不提供该情形下的 PASS。",
        },
    }

    # ------------------------------------------------- machine checks
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    check(
        "thresholds_unchanged",
        gate_v3["quality_requirements"]["target_recall_overall_min"] == 0.85
        and gate_v3["quality_requirements"]["target_recall_per_source_min"] == 0.8
        and gate_v3["quality_requirements"]["candidate_precision_min"] == 0.8
        and gate_v3["quality_requirements"]["accepted_records_total_min"] == 40
        and gate_v3["quality_requirements"]["accepted_records_per_source_min"] == 20
        and gate_v3["quality_requirements"]["unresolved_candidates_max"] == 0,
        "六项阈值逐字沿用门 v2（0.85/0.80/0.80/40/20/0）",
    )
    check(
        "threshold_relaxation_flag_still_false",
        gate_v3["scope_constraints"]["threshold_relaxation_after_execution_allowed"] is False,
        "scope_constraints.threshold_relaxation_after_execution_allowed 保持 false",
    )
    check(
        "sentinel_matches_contract_items_subset",
        sorted(sentinel_v3)
        == sorted(k for k in contract_v43["review_assertions"] if k.startswith("NT-I")),
        "门 v3 哨兵清单 == 契约 v4.3 review_assertions 的 NT-I* 子集",
    )
    check(
        "exclusions_all_annotated",
        all(
            SENTINEL_EXCLUSIONS[key].get("mechanism") and SENTINEL_EXCLUSIONS[key].get("reason")
            for key in SENTINEL_EXCLUSIONS
        ),
        "每个被移出哨兵项都带 mechanism 与 reason",
    )
    check(
        "exclusions_were_in_v2_sentinel",
        all(key in sentinel_v2 for key in SENTINEL_EXCLUSIONS),
        "被移出项原本都在门 v2 哨兵清单内",
    )
    check(
        "sentinel_subset_of_gold",
        all(item in by_id for item in sentinel_v3),
        "哨兵清单全部属于 48 条冻结金标",
    )
    flip_candidates = [r["candidate_id"] for r in required]
    check(
        "no_candidate_used_twice",
        len(flip_candidates) == len(set(flip_candidates)),
        f"改判草案中候选互不重复：{flip_candidates}",
    )
    check(
        "required_flips_are_distinct_candidates",
        len({r["candidate_id"] for r in required + pair}) == len(required) + len(pair) - 1,
        "I23/I24 共享同一候选（-1），其余互不重复",
    )
    check(
        "old_hashes_retained",
        gate_v3["revision_history"][-1]["previous_gate_sha256"] == gate_v2_sha
        and contract_v43["supersedes"]["sha256"] == contract_v42_sha,
        "门 v2 与契约 v4.2 的旧哈希已留存于新版本记录",
    )
    check(
        "contract_pin_provisional_not_faked",
        contract_v43["threshold_source"]["authority_source"]["sha256"] == gate_v3_sha_placeholder,
        "契约对门 v3 的绑定标记为 provisional，未伪造已签哈希",
    )
    check(
        "signoff_fields_empty",
        contract_v43["signoff"]["signed_by"] is None
        and gate_v3["countersignature"]["reviewer"] is None
        and all(r["proposed_reviewer"] is None for r in adjudications),
        "门/契约/改判三处新签认字段全部留空，不代签（旧裁定人原样留档）",
    )
    check(
        "adjudications_carry_contract_fields",
        all(not [f for f in contract_fields if f not in r] for r in adjudications),
        f"改判记录齐备契约 {len(contract_fields)} 个 candidate_adjudication_fields",
    )
    check(
        "adjudications_have_verbatim_evidence",
        all(r.get("evidence") and r.get("gold_locator") for r in adjudications),
        "每条改判都带候选原文 evidence 与金标 locator",
    )
    check(
        "pair_stubs_share_one_candidate",
        len({r["candidate_id"] for r in pair}) == 1,
        "二选一两条共享同一候选（apply 落地时只保留一条）",
    )
    check(
        "seventh_stubs_cover_all_options",
        sorted(seventh_golds) == sorted({"NT-I36", "NT-I45", "NT-I46", "NT-I47"}),
        f"第 7 条四个候选桩齐备：{sorted(seventh_golds)}",
    )
    check(
        "landed_adjudication_count_is_seven",
        len([r for r in adjudications if r["keep_if"]["rule"] == "always"]) == 5,
        "落地后应为 5（always）+ 1（pair）+ 1（seventh）= 7 条",
    )
    check(
        "all_projection_options_pass_or_flagged",
        all(p["projected_verdict"] == "PASS" for p in projections),
        "两个合法第七项选项在未改阈值下均投影为 PASS",
    )
    check(
        "attribution_propositions_match_gate33_gold",
        all(rows[gid]["proposition"] == (g33.get(gid) or {}).get("proposition") for gid in rows),
        "归因表的金标命题与门 33 gold_reference 逐条一致",
    )

    failures = [c for c in checks if not c["ok"]]

    out_checks = {
        "schema_version": "r2-draft-checks-1",
        "created_on": "2026-10-13",
        "zero_model_calls": True,
        "passed": len(checks) - len(failures),
        "failed": len(failures),
        "checks": checks,
    }

    if not args.no_write:
        if failures:
            raise SystemExit("checks failed: " + json.dumps(failures, ensure_ascii=False))
        atomic_write(HERE / "gate-v3.proposed.json", gate_v3)
        atomic_write(HERE / "scoring-contract-v4.3.proposed.json", contract_v43)
        atomic_write(HERE / "re-adjudication-draft.json", readjudication)
        atomic_write(
            HERE / "diffs.json",
            {
                "gate_v2_to_v3": diff(gate_v2, gate_v3),
                "contract_v42_to_v43": diff(contract_v42, contract_v43),
            },
        )
        atomic_write(HERE / "checks.json", out_checks)
        atomic_write(HERE / "projection.json", projection)
        (HERE / "r2-drafts.md").write_text(
            render_md(gate_v3, contract_v43, readjudication, projection, out_checks, sentinel_v2, sentinel_v3),
            encoding="utf-8",
        )
        manifest = {
            "schema_version": "evidence-manifest-1",
            "created_on": "2026-10-13",
            "zero_model_calls": True,
            "status": "draft_pending_named_signoff",
            "note": "全部为草案；签认字段留空；未修改任何既有文件。",
            "artifacts": {
                name: sha256_of(HERE / name)
                for name in (
                    "build_r2_drafts.py",
                    "gate-v3.proposed.json",
                    "scoring-contract-v4.3.proposed.json",
                    "re-adjudication-draft.json",
                    "diffs.json",
                    "checks.json",
                    "projection.json",
                    "r2-drafts.md",
                )
            },
            "inputs": {
                "gate_v2": gate_v2_sha,
                "contract_v4.2": contract_v42_sha,
                "attribution": sha256_of(ATTRIBUTION),
                "frozen_gold": sha256_of(GOLD),
                "gate33_gold_reference": sha256_of(GATE33_GOLD),
                "worksheet_A": sha256_of(WORKSHEET),
                "terminal_decision": sha256_of(TERMINAL),
            },
            "reproduce": (
                "uv run python .scratch/claims-r2-role-isolation/evidence/"
                "74-r2-gate-v3-contract-v43-draft-20261013/r0-zero-call/build_r2_drafts.py"
            ),
        }
        atomic_write(HERE / "MANIFEST.json", manifest)

    print(
        json.dumps(
            {
                "sentinel_v2": len(sentinel_v2),
                "sentinel_v3": len(sentinel_v3),
                "excluded": sorted(SENTINEL_EXCLUSIONS),
                "required_flips": required_golds,
                "pair_alternatives": pair_golds,
                "seventh_flip_options": [c["option"] for c in READJUDICATION_SEVENTH_CHOICE],
                "projections": [
                    {
                        "seventh": p["seventh_flip"],
                        "recall": p["recall_overall"],
                        "per_source": {k: v["recall"] for k, v in p["per_source"].items()},
                        "sentinel": p["sentinel_covered"],
                        "verdict": p["projected_verdict"],
                    }
                    for p in projections
                ],
                "checks_passed": out_checks["passed"],
                "checks_failed": out_checks["failed"],
                "failures": failures,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not failures else 1


def render_md(
    gate_v3: dict[str, Any],
    contract_v43: dict[str, Any],
    readjudication: dict[str, Any],
    projection: dict[str, Any],
    checks: dict[str, Any],
    sentinel_v2: list[str],
    sentinel_v3: list[str],
) -> str:
    lines = [
        "# R2 草案包：门 v3 + 契约 v4.3 + 7 条改判草案（零模型调用）",
        "",
        "- 2026-10-13　依据：U「先走 R2」；不删改任何既有文件，旧件哈希留存在 revision_history",
        "- **全部为草案**：门 countersignature、契约 signoff、改判 reviewer 三处均留空，不代签",
        "",
        "## 一、R2 改了什么（三处）",
        "",
        "| # | 项 | 变化 |",
        "|---|---|---|",
        f"| 1 | 高风险哨兵清单 | {len(sentinel_v2)} → **{len(sentinel_v3)}** 项，移出 "
        "NT-I09/I19/I45/I46/I47（逐条机制见 `high_risk_item_assertions_excluded`） |",
        "| 2 | 契约口径 | `matching.items` 增补「上下文唯一可恢复」条款及其两项不适用情形 |",
        "| 3 | 门/契约绑定 | 门 revision 6；契约 v4.3 改钉门 v3（**provisional**，签认后回填） |",
        "",
        "**未改**：六项阈值（0.85/0.80/0.80/40/20/0 逐字不变）、"
        "`scope_constraints.threshold_relaxation_after_execution_allowed=false`、冻结金标字节、样本、代码。",
        "",
        "## 二、哨兵清单移出项（逐条机制）",
        "",
        "| gold | 机制 | 依据 |",
        "|---|---|---|",
    ]
    for key, spec in gate_v3["quality_requirements"]["high_risk_item_assertions_excluded"].items():
        lines.append(f"| {key} | `{spec['mechanism']}` | {spec['reason']} |")
    lines += [
        "",
        "## 三、改判草案（7 条）",
        "",
        "### 3.1 必需 5 条",
        "",
        "| gold | 源 | 候选 | 原裁定 | 拟裁定 |",
        "|---|---|---|---|---|",
    ]
    for item in readjudication["adjudications"]:
        if item["keep_if"]["rule"] != "always":
            continue
        lines.append(
            f"| {item['proposed_matched_gold_id']} | {item['gold_source']} | `{item['candidate_id']}` | "
            f"{item['previous_judgement']} | {item['proposed_judgement']} |"
        )
    lines += [
        "",
        "### 3.2 二选一（共享同一候选，只能取一条）",
        "",
        "| gold | 候选 | 原裁定 |",
        "|---|---|---|",
    ]
    for item in readjudication["adjudications"]:
        if item["keep_if"]["rule"] != "pair_choice":
            continue
        lines.append(
            f"| {item['proposed_matched_gold_id']} | `{item['candidate_id']}` | {item['previous_judgement']} |"
        )
    lines += ["", "**二选一勾选（签认件第六节）**：第 7 条下方另有 `NT-I23 / NT-I24` 勾选栏，必须且只能勾一项。"]
    lines += [
        "",
        "### 3.3 第 7 条：三选一（**待 U 决定**）",
        "",
        "| 选项 | 涉及 gold | 代价 |",
        "|---|---|---|",
    ]
    for choice in readjudication["seventh_flip_open_choice"]:
        lines.append(f"| `{choice['option']}` | {choice['gold_id']} | {choice['cost']} |")
    lines += [
        "",
        "## 四、投影（**未签认投影，不是 verdict**）",
        "",
        projection["note"],
        "",
        "| 第 7 条选项 | 总召回 | 源1 | 源2 | 哨兵 | 投影判定 |",
        "|---|---|---|---|---|---|",
    ]
    for item in projection["projections"]:
        lines.append(
            f"| `{item['seventh_flip']}` | {item['recall_overall']} | "
            f"{item['per_source']['源1']['recall']} | {item['per_source']['源2']['recall']} | "
            f"{item['sentinel_covered']} | **{item['projected_verdict']}** |"
        )
    lines += [
        "",
        f"> 契约无效选项：`{projection['contract_invalid_option']['option']}` —— "
        f"{projection['contract_invalid_option']['why']}",
        "",
        "## 五、机器校验",
        "",
        f"通过 {checks['passed']} 项，失败 {checks['failed']} 项。",
        "",
        "| 检查 | 结果 | 说明 |",
        "|---|---|---|",
    ]
    for item in checks["checks"]:
        lines.append(f"| `{item['check']}` | {'PASS' if item['ok'] else 'FAIL'} | {item['detail']} |")
    lines += [
        "",
        "## 六、签认前还缺什么",
        "",
        "1. **U 的第 7 条选择**（`I36_question_form` / `one_of_u_calibration_revoked`；双抵扣项契约无效）",
        "2. 门 v3 具名签认（`countersignature`）",
        "3. 契约 v4.3 具名签认（`signoff`），签认后回填门 v3 最终哈希并移除 `pin_status`",
        "4. 7 条改判由 xyl 具名确认（`re-adjudication-draft.json`）",
        "5. 以上完成后才可据实重算出分，形成**新 verdict**；旧 verdict 保持 FAIL 不改写",
        "",
        "## 七、复现",
        "",
        "```bash",
        "uv run python .scratch/claims-r2-role-isolation/evidence/"
        "74-r2-gate-v3-contract-v43-draft-20261013/r0-zero-call/build_r2_drafts.py",
        "```",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
