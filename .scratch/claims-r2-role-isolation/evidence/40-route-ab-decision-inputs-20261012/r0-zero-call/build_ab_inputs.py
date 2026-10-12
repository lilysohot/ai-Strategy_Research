"""Route a/b decision inputs: cost-benefit table, freeze-impact inventory, experiment protocol.

Zero call, read-only. Implements `preregistered-ab-inputs.json` (write-once) and emits
ab-cost-benefit.{json,md}, freeze-impact.{json,md}, route-b-experiment-protocol.{json,md}
and MANIFEST.json.

Every measured number is read from an existing artifact (with its hash recorded); every
authored judgement carries a `basis` and a `status`. Nothing here modifies any artifact.

Usage:
    uv run python .scratch/claims-r2-role-isolation/evidence/40-route-ab-decision-inputs-20261012/r0-zero-call/build_ab_inputs.py
    ... --no-write
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E40 = HERE.parent
CLAIMS = E40.parent.parent
REPO_ROOT = HERE.parents[4]
E36_R0 = CLAIMS / "evidence" / "36-l9-redo-and-baseline-20261011" / "r0-zero-call"
for path in (str(REPO_ROOT), str(E36_R0)):
    if path not in sys.path:
        sys.path.insert(0, path)

from l9_redo import digest, read_json  # noqa: E402

EV = CLAIMS / "evidence"
GOLD = EV / "10-quality-gold-freeze-20261008-r2" / "frozen-gold.json"
GOLD_MANIFEST = EV / "10-quality-gold-freeze-20261008-r2" / "freeze-manifest.json"
CONTRACT = EV / "10-quality-gold-expansion-20261008-r2" / "scoring-contract.json"
E32_R0 = EV / "32-items-v6-reasoning-refreeze-20261011" / "r0-zero-call"
E32_LIVE = EV / "32-items-v6-reasoning-refreeze-20261011" / "live"
E33_R0 = EV / "33-items-quality-scoring-20261011" / "r0-zero-call"
E35 = EV / "35-gold-audit-20261011" / "r0-zero-call" / "gold-audit.json"
E36_RESULT = E36_R0 / "l9-redo.json"
E37_RESULT = EV / "37-store-baseline-and-route-decision-20261012" / "r0-zero-call" / "store-baseline.json"
E38_RESULT = EV / "38-gate33-workbench-rebuild-20261012" / "r0-zero-call" / "workbench-v2.json"
E39_RESULT = EV / "39-roles-l3-audit-20261012" / "r0-zero-call" / "roles-l3-audit.json"
GATE28 = EV / "28-items-only-quality-gate-20261010" / "r0-zero-call" / "preregistered-gate.json"
PREREG = HERE / "preregistered-ab-inputs.json"

COST_DIMENSIONS = (
    "model_calls",
    "human_adjudication_records",
    "freeze_revisions",
    "gate_runs",
    "zero_call_code_changes",
)

WORK_ITEMS: list[dict[str, Any]] = [
    {
        "id": "C1",
        "name": "口径归一化条款（契约 v4 修订）",
        "bucket": "common",
        "cost": {"model_calls": 0, "human_adjudication_records": 0, "freeze_revisions": 1, "gate_runs": 0, "zero_call_code_changes": 0},
        "basis": "issue-34 §5.9 口径差实测（perspective 0→32 等）；§7-11",
        "status": "measured_basis",
    },
    {
        "id": "C2",
        "name": "Stage 2 阻塞条款：候选→契约字段由谁负责、凭据是什么",
        "bucket": "common",
        "cost": {"model_calls": 0, "human_adjudication_records": 0, "freeze_revisions": 0, "gate_runs": 0, "zero_call_code_changes": 0},
        "basis": "并入 C1 同一份 v4（issue-34 §7 注：1 与 3 应合并为一轮）",
        "status": "authored",
    },
    {
        "id": "C3",
        "name": "评分器读契约 + 阈值单源（对齐门 28）",
        "bucket": "common",
        "cost": {"model_calls": 0, "human_adjudication_records": 0, "freeze_revisions": 1, "gate_runs": 0, "zero_call_code_changes": 1},
        "basis": "全仓零代码读 scoring-contract.json；阈值硬编码 structured_scoring.py:332-340；阈值变更须具名签认",
        "status": "measured_basis",
    },
    {
        "id": "C4",
        "name": "重建门 33 工作台（补 speaker_ref 与 layer B 字段）",
        "bucket": "common",
        "cost": {"model_calls": 0, "human_adjudication_records": 0, "freeze_revisions": 0, "gate_runs": 0, "zero_call_code_changes": 1},
        "basis": "evidence/38 已完成（§5.10），成本已付",
        "status": "done",
    },
    {
        "id": "C5",
        "name": "人工裁定全部候选（unresolved_candidates_max = 0 的硬要求）",
        "bucket": "common",
        "cost": {"model_calls": 0, "human_adjudication_records": 222, "freeze_revisions": 0, "gate_runs": 0, "zero_call_code_changes": 0},
        "basis": "门 33 草案：accepted 19 + pending 203 = 222；契约 matching.mode 要求人工裁定；门 28 unresolved_candidates_max=0",
        "status": "measured_basis",
    },
    {
        "id": "C6",
        "name": "门 33 Stage 3 严格评分",
        "bucket": "common",
        "cost": {"model_calls": 0, "human_adjudication_records": 0, "freeze_revisions": 0, "gate_runs": 1, "zero_call_code_changes": 0},
        "basis": "issue-33 §3 三步流程",
        "status": "authored",
    },
    {
        "id": "A1",
        "name": "实现正式读路径（layer A + layer B + text → 契约字段）",
        "bucket": "route_a_marginal",
        "cost": {"model_calls": 0, "human_adjudication_records": 0, "freeze_revisions": 1, "gate_runs": 0, "zero_call_code_changes": 1},
        "basis": "工作台 v2 已给出 contract_view 雏形（evidence/38）；条款并入 v4",
        "status": "measured_basis",
    },
    {
        "id": "A2",
        "name": "口径映射的回归测试（防映射随数据/模型漂移）",
        "bucket": "route_a_marginal",
        "cost": {"model_calls": 0, "human_adjudication_records": 0, "freeze_revisions": 0, "gate_runs": 0, "zero_call_code_changes": 1},
        "basis": "映射是事后口径，非源头口径（issue-34 §5.7 读路径须与记录 ID 无关）",
        "status": "authored",
    },
    {
        "id": "B1",
        "name": "把口径写进协议文本（material_semantics.py 提示词）",
        "bucket": "route_b_marginal",
        "cost": {"model_calls": 0, "human_adjudication_records": 0, "freeze_revisions": 0, "gate_runs": 0, "zero_call_code_changes": 1},
        "basis": "gate-32 freeze-manifest 绑定 material_semantics_module = 1305dba1…",
        "status": "measured_basis",
    },
    {
        "id": "B2",
        "name": "重抽：单臂 24 包（md 10 + docx 14）；含对照臂则 48",
        "bucket": "route_b_marginal",
        "cost": {"model_calls": 24, "human_adjudication_records": 0, "freeze_revisions": 0, "gate_runs": 0, "zero_call_code_changes": 0},
        "basis": "gate-32 expected_attempts = {md:10, docx:14}（实测字段）；若需 control 臂归因则 ×2",
        "status": "measured_basis",
        "variant_control_arm": 48,
    },
    {
        "id": "B3",
        "name": "推进 extractor_version 并登记 _HISTORICAL_RUN_PAYLOAD_SHAPES",
        "bucket": "route_b_marginal",
        "cost": {"model_calls": 0, "human_adjudication_records": 0, "freeze_revisions": 0, "gate_runs": 0, "zero_call_code_changes": 1},
        "basis": "环境硬约定：推进 version 不登记旧 current 会导致旧产物读不回（现 current 产物为 material-semantics-32）",
        "status": "measured_basis",
    },
    {
        "id": "B4",
        "name": "新冻结 + 新门（gate-32 冻结作废）",
        "bucket": "route_b_marginal",
        "cost": {"model_calls": 0, "human_adjudication_records": 0, "freeze_revisions": 1, "gate_runs": 1, "zero_call_code_changes": 0},
        "basis": "见 freeze-impact.json",
        "status": "measured_basis",
    },
    {
        "id": "I1",
        "name": "补跑被传输事件丢掉的 1 个包（md 第 8 包，7 条 critical）",
        "bucket": "independent",
        "cost": {"model_calls": 1, "human_adjudication_records": 0, "freeze_revisions": 0, "gate_runs": 1, "zero_call_code_changes": 0},
        "basis": "issue-34 §5.1/§6；gate-32 automatic_retries = 0（损失根因）⇒ 须先定重试/幂等策略",
        "status": "measured_basis",
    },
    {
        "id": "I2",
        "name": "裁定 B-1 两条（NT-I06 / NT-I41）的性质",
        "bucket": "independent",
        "cost": {"model_calls": 0, "human_adjudication_records": 1, "freeze_revisions": 0, "gate_runs": 0, "zero_call_code_changes": 0},
        "basis": "issue-34 §5.8 backlog B-1",
        "status": "measured_basis",
    },
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    prereg = read_json(PREREG)
    e35 = read_json(E35)
    e36 = read_json(E36_RESULT)
    e37 = read_json(E37_RESULT)
    e39 = read_json(E39_RESULT)
    contract = read_json(CONTRACT)
    gate32 = read_json(E32_R0 / "preregistered-gate.json")
    freeze32 = read_json(E32_R0 / "freeze-manifest.json")
    gate28 = read_json(GATE28)
    gold_manifest = read_json(GOLD_MANIFEST)

    # ---------------------------------------------------------------- measured inputs
    measured = {
        "gold_denominator": e35["summary"]["records"],
        "field_identical_after_normalization": e37["ec_a3_tuple_alignment"]["5tuple"]["records"],
        "verbatim_evidence_reachable": e35["summary"]["records_with_exact_candidate_quote"],
        "records_without_candidate": e36["totals"]["corpus_absent"],
        "lost_packet_records": e35["summary"]["touching_lost_unit"],
        "absent_required_fields_items": e37["ec_a1_field_carriers"]["absent_required_fields"],
        "relations_structurally_unscoreable": e39["verdicts"]["ec_b4_structurally_unscoreable"]["fields"],
        "gate32_expected_attempts": gate32["expected_attempts"],
        "gate32_automatic_retries": gate32["automatic_retries"],
        "gate32_extractor_version": freeze32["extractor_version"],
        "gate28_unresolved_candidates_max": gate28["quality_requirements"]["unresolved_candidates_max"],
        "contract_matching_mode": contract["matching"]["mode"],
    }
    measured["human_adjudication_band"] = measured["verbatim_evidence_reachable"] - measured[
        "field_identical_after_normalization"
    ]

    # ---------------------------------------------------------------- benefit scenarios
    low = measured["field_identical_after_normalization"]
    high = measured["verbatim_evidence_reachable"]
    benefit = [
        {
            "id": "S0",
            "label": "现状（不修任何项）",
            "matchable_gold": 0,
            "status": "measured",
            "basis": "evidence/36 A 臂 tp=0（严格 identity，原生候选形态）",
        },
        {
            "id": "S1",
            "label": "共同项完成后（口径条款 + 评分器读契约 + 工作台 v2 + 人工裁定）",
            "matchable_gold": {"lower": low, "upper": high},
            "status": "bounded_by_measurement",
            "basis": f"下界 {low} = 归一化后 5 元组逐字对齐（实测）；上界 {high} = 逐字证据可达（evidence/35 实测）；"
            f"中间 {measured['human_adjudication_band']} 条须人工裁定，**机上不可测**",
        },
        {
            "id": "S2",
            "label": "S1 + 补跑丢失包（7 条 critical）",
            "matchable_gold": {"lower": low, "upper": 48},
            "status": "unverified",
            "basis": "补跑只解除物理缺失（7 条）；其余上限变化取决于人工裁定与 route b 效果，均未证",
        },
        {
            "id": "S3",
            "label": "S2 + route b 重抽",
            "matchable_gold": {"lower": low, "upper": 48},
            "status": "unverified",
            "basis": "route b 的增量收益**无任何证据**（缺口 2）；须先做 route-b-experiment-protocol 的受控实验",
        },
    ]

    # ---------------------------------------------------------------- per-dimension totals
    totals: dict[str, Any] = {}
    for dim in COST_DIMENSIONS:
        common = sum(item["cost"][dim] for item in WORK_ITEMS if item["bucket"] == "common")
        marg_a = sum(item["cost"][dim] for item in WORK_ITEMS if item["bucket"] == "route_a_marginal")
        marg_b = sum(item["cost"][dim] for item in WORK_ITEMS if item["bucket"] == "route_b_marginal")
        independent = sum(item["cost"][dim] for item in WORK_ITEMS if item["bucket"] == "independent")
        totals[dim] = {
            "common": common,
            "route_a_marginal": marg_a,
            "route_b_marginal": marg_b,
            "independent": independent,
            "common_ge_sum_of_marginals": common >= (marg_a + marg_b),
        }
    holds_on = [
        dim
        for dim, blob in totals.items()
        if blob["common_ge_sum_of_marginals"] and blob["common"] > 0
    ]
    does_not_hold_on = [dim for dim in totals if dim not in holds_on]
    pseudo_dichotomy = {
        "hypothesis": "共同项成本占主导 ⇒ 先做共同项优于先分叉（可能为伪二分）",
        "per_dimension": totals,
        "holds_on": holds_on,
        "does_not_hold_on": does_not_hold_on,
        "verdict": (
            f"在 {holds_on} 上成立：共同项 ≥ 两边际项之和。"
            "其中人工裁定维度由契约 matching.mode 决定——route a 与 route b 都必须付这一项，"
            "且 route b 在新的候选集上无法复用 route a 的裁定结果，故该维度上『先分叉』不省成本。"
            f"在 {does_not_hold_on} 上不成立（边际项更大）：这两项正是路线分叉真正的差异所在，"
            "须由缺口 1（人工可裁定比例）与缺口 2（route b 收益）补齐后才能定。"
        ),
        "status": "authored_from_measured",
    }
    route_a_vs_b_marginal = {
        "model_calls": {"route_a": totals["model_calls"]["route_a_marginal"], "route_b": totals["model_calls"]["route_b_marginal"]},
        "freeze_revisions": {
            "route_a": totals["freeze_revisions"]["route_a_marginal"],
            "route_b": totals["freeze_revisions"]["route_b_marginal"],
        },
        "gate_runs": {"route_a": totals["gate_runs"]["route_a_marginal"], "route_b": totals["gate_runs"]["route_b_marginal"]},
        "human_adjudication_records": {
            "route_a": "222（在现候选集上）",
            "route_b": "222（在**新**候选集上，不可复用现裁定）",
        },
        "note": "route b 的收益（是否能减少 32 条人工裁定区间）未证；route a 的收益下界/上界见 benefit S1。",
    }

    cost_benefit = {
        "schema_version": "items-ab-cost-benefit-1",
        "created_on": "2026-10-12",
        "zero_call": True,
        "preregistration": {"path": PREREG.name, "sha256": digest(PREREG)},
        "units": prereg["units"],
        "measured_inputs": measured,
        "work_items": WORK_ITEMS,
        "totals_by_dimension": totals,
        "route_a_vs_b_marginal": route_a_vs_b_marginal,
        "benefit_scenarios": benefit,
        "pseudo_dichotomy": pseudo_dichotomy,
        "remaining_gaps": {
            "gap_1": "32 条区间的人工可裁定比例 —— 需 xyl 分层抽样裁定（本批不代替）",
            "gap_2": "route b 的抽取差可修复性 —— 需执行 route-b-experiment-protocol（需授权）",
            "gap_3": "本批已关闭（同量纲表已产出）",
            "gap_4": "本批已关闭（freeze-impact.json）",
        },
    }

    # ---------------------------------------------------------------- freeze impact (EC-AB4)
    bound = [
        {
            "artifact": "gate-32 freeze-manifest 输入 material_semantics_module",
            "path": "32-…/r0-zero-call/freeze-manifest.json",
            "sha256": freeze32["inputs"]["material_semantics_module"],
            "bound_by": "gate-32 freeze-manifest inputs",
            "impact": "直接失配（该文件是绑定输入）",
            "action": "新冻结（新版本记录，旧哈希留存），须新门",
        },
        {
            "artifact": "gate-32 freeze-manifest 输入 structured_config_module",
            "path": "32-…/r0-zero-call/freeze-manifest.json",
            "sha256": freeze32["inputs"]["structured_config_module"],
            "bound_by": "gate-32 freeze-manifest inputs",
            "impact": "若同时改配置则失配；仅改提示词则不受影响",
            "action": "按实际改动面决定",
        },
        {
            "artifact": "gate-32 freeze-manifest 输入 structured_adapter_module",
            "path": "32-…/r0-zero-call/freeze-manifest.json",
            "sha256": freeze32["inputs"]["structured_adapter_module"],
            "bound_by": "gate-32 freeze-manifest inputs",
            "impact": "若改装配投影则失配（工作台投影缺陷即在此层）",
            "action": "按实际改动面决定",
        },
        {
            "artifact": "gate-32 四个 plan 文件",
            "path": "32-…/r0-zero-call/plan-*.json",
            "sha256": freeze32["files_sha256"],
            "bound_by": "gate-32 freeze-manifest files_sha256",
            "impact": "协议/快照变更会改 plan 内容 ⇒ 4 个哈希全部失配",
            "action": "重新 plan（零调用）并新冻结",
        },
        {
            "artifact": "金标冻结链 freeze-manifest 输入 scoring-contract.json",
            "path": "10-quality-gold-freeze-20261008-r2/freeze-manifest.json",
            "sha256": gold_manifest["inputs"][".scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r2/scoring-contract.json"],
            "bound_by": "金标冻结链（Issue 10）",
            "impact": "**已漂移**：记录 v2，实际签认 v3（7/8 匹配）；契约 v4 会再漂一次",
            "action": "与 C1/C3 同轮修绑定（新版本记录，不改金标字节）",
        },
        {
            "artifact": "门 28 preregistered-gate（signed，权威阈值与字段清单来源）",
            "path": "28-…/r0-zero-call/preregistered-gate.json",
            "sha256": digest(GATE28),
            "bound_by": "门 28 自身",
            "impact": "v4 若改 metric_basis / role_required_fields ⇒ 门 28 度量基准失配",
            "action": "新版本门记录（不就地改）",
        },
        {
            "artifact": "门 33 workbench v1",
            "path": "33-…/r0-zero-call/workbench.json",
            "sha256": digest(E33_R0 / "workbench.json"),
            "bound_by": "门 33 自身",
            "impact": "route b 改协议 ⇒ 候选集变化 ⇒ v1 与 v2 均作废",
            "action": "route b 须重建工作台（零调用，复用 evidence/38 脚本）",
        },
        {
            "artifact": "门 33 adjudications 骨架",
            "path": "33-…/r0-zero-call/adjudications.json",
            "sha256": digest(E33_R0 / "adjudications.json"),
            "bound_by": "门 33 自身",
            "impact": "候选集变化即作废（现为空骨架，未填）",
            "action": "随工作台重建",
        },
        {
            "artifact": "treatment store 对象（现 extractor material-semantics-32）",
            "path": "32-…/live/treatment-store/**/objects/**",
            "sha256": {
                "industrial-fulian-md": e37["store_runs"]["industrial-fulian-md"]["object_sha256"],
                "optical-module-docx": e37["store_runs"]["optical-module-docx"]["object_sha256"],
            },
            "bound_by": "运行产物本身",
            "impact": "推进 extractor_version 后旧产物须保持可读，否则 222 条候选读不回",
            "action": "登记 _HISTORICAL_RUN_PAYLOAD_SHAPES（对应 B3）",
        },
    ]
    unaffected = [
        {
            "artifact": "frozen-gold.json / freeze-state.json",
            "sha256": digest(GOLD),
            "reason": "金标字节不动（§8 范围外硬约束）；只修其 manifest 里的契约绑定记录",
        },
        {
            "artifact": "plugins/corpus/structured_scoring.py",
            "sha256": digest(REPO_ROOT / "plugins/corpus/structured_scoring.py"),
            "reason": "不在 gate-32 freeze-manifest 的绑定输入清单内（已核对；仍建议在 v4 轮显式确认一次）",
        },
    ]
    freeze_impact = {
        "schema_version": "items-freeze-impact-1",
        "created_on": "2026-10-12",
        "zero_call": True,
        "trigger": "任一改动 material_semantics.py 提示词文本 / 协议版本 / 装配投影",
        "bound_artifacts": bound,
        "unaffected": unaffected,
        "gate32_gate_self_hash_from_report": "6fb47e79…fba8（issue-34 §2 记载；本批未重算，需在执行前复核）",
        "summary": {
            "direct_hash_mismatch": ["material_semantics_module", "四个 plan（协议变更时）"],
            "requires_new_gate": True,
            "requires_new_freeze": True,
            "gold_bytes_untouched": True,
            "historical_readability_risk": "旧 222 条候选须保持可读（B3）",
        },
    }

    # ---------------------------------------------------------------- experiment protocol (EC-AB5)
    protocol = {
        "schema_version": "items-route-b-experiment-protocol-1",
        "created_on": "2026-10-12",
        "status": "draft_for_authorization_not_executed",
        "question": "抽取差（quoted_other 7 vs 2、condition 10 vs 6、behavior 3 vs 0）是口径歧义（改提示词可解）还是模型能力（不可解）？",
        "why": "这是 route b 唯一的收益来源；不测就没有收益证据（缺口 2）。",
        "design": {
            "arms": {
                "control": "现行冻结协议文本（material-semantics-32 / material-atomic-selector-jsonl-v6），逐字不变",
                "treatment": "同代码 + 口径明确化增量（**只改提示词文本**，不改解析、装配、校验、阈值）",
            },
            "same_code_requirement": "两臂必须同代码同提交，diff 仅限提示词常量；禁止用历史冻结报告当对照（会把代码漂移混进归因）",
            "sample": "两源各 1 个包（md 第 3 包 + docx 第 3 包，包号预注册固定）用于试跑；确认判据尺度后再决定是否全量",
            "budget": {
                "smoke_model_calls": 4,
                "full_model_calls": 48,
                "basis": "gate-32 expected_attempts md 10 + docx 14 = 24/臂，双臂 48",
            },
        },
        "metrics": {
            "M1": "perspective == quoted_other 计数（金标 7，现 2）",
            "M2": "statement_role == condition 计数（金标 10，现 6）",
            "M3": "semantic_type == behavior 计数（金标 3，现 0）",
            "M4": "speech_role 分布（金标全 statement；现有 question/answer）",
            "M5": "协议违规数（须为 0；gate-32 v6 实测为 0）",
            "M6": "逐字证据可达率（现 39/48，见 evidence/35）",
            "M7": "items_error / 解析失败数（fail-closed 不得放大）",
        },
        "exit_criteria": {
            "EC-X1": "若 M1/M2/M3 任一在 treatment 上达到金标计数的 ≥50% 且 M5 仍为 0 ⇒ 『抽取差属口径歧义』成立，route b 收益存在。",
            "EC-X2": "若 M1/M2/M3 全部无改善（变化 ≤1）且 M6 无提升 ⇒ 『抽取差属模型能力』，route b 不得以『改善抽取差』为由；route a 优先。",
            "EC-X3": "单臂不得归因；两臂必须同代码。",
            "EC-X4": "判据外新发现进 backlog，不回流本次。",
            "EC-X5": "M7 若上升（fail-closed 放大）⇒ 立即终止并回滚，不得以收益为由放宽校验。",
        },
        "authorization_required": {
            "granted_by": "",
            "granted_on": "",
            "model": "待填（gate-32 用 deepseek-flash / openai_compat）",
            "attempts_max": "待填（gate-32 为 automatic_retries=0 ⇒ 本次须显式设定重试与幂等策略）",
            "pacing": "待填（gate-32 为 checkpoint_after_reserve 20s）",
            "budget_cap_model_calls": "待填",
        },
        "scope_out": [
            "不放宽 fail-closed 校验与解析",
            "不改金标、契约、阈值；不报分；不发布",
            "不访问生产库；不触碰 holdout",
            "不在本实验内改口径条款以外的任何提示词内容",
        ],
        "note": "本协议为草案，执行前须由 U 填授权并具名签认；执行本身属『开放式真实运行』，须先有本预注册。",
    }

    print(
        json.dumps(
            {
                "measured_inputs": measured,
                "totals_by_dimension": {
                    dim: {k: v for k, v in blob.items() if k != "common_ge_sum_of_marginals"}
                    for dim, blob in totals.items()
                },
                "benefit_S1": benefit[1]["matchable_gold"],
                "pseudo_dichotomy_holds_on": pseudo_dichotomy["holds_on"],
                "freeze_impact_bound": len(bound),
                "protocol_status": protocol["status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.no_write:
        return

    (HERE / "ab-cost-benefit.json").write_text(
        json.dumps(cost_benefit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "ab-cost-benefit.md").write_text(render_cost_benefit(cost_benefit), encoding="utf-8")
    (HERE / "freeze-impact.json").write_text(
        json.dumps(freeze_impact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "freeze-impact.md").write_text(render_freeze_impact(freeze_impact), encoding="utf-8")
    (HERE / "route-b-experiment-protocol.json").write_text(
        json.dumps(protocol, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "route-b-experiment-protocol.md").write_text(
        render_protocol(protocol), encoding="utf-8"
    )
    manifest = {
        "schema_version": "items-ab-decision-inputs-manifest-1",
        "created_on": "2026-10-12",
        "inputs": {
            str(PREREG.relative_to(REPO_ROOT)): digest(PREREG),
            str(GOLD.relative_to(REPO_ROOT)): digest(GOLD),
            str(GOLD_MANIFEST.relative_to(REPO_ROOT)): digest(GOLD_MANIFEST),
            str(CONTRACT.relative_to(REPO_ROOT)): digest(CONTRACT),
            str(E35.relative_to(REPO_ROOT)): digest(E35),
            str(E36_RESULT.relative_to(REPO_ROOT)): digest(E36_RESULT),
            str(E37_RESULT.relative_to(REPO_ROOT)): digest(E37_RESULT),
            str(E38_RESULT.relative_to(REPO_ROOT)): digest(E38_RESULT),
            str(E39_RESULT.relative_to(REPO_ROOT)): digest(E39_RESULT),
            str((E32_R0 / "preregistered-gate.json").relative_to(REPO_ROOT)): digest(
                E32_R0 / "preregistered-gate.json"
            ),
            str((E32_R0 / "freeze-manifest.json").relative_to(REPO_ROOT)): digest(
                E32_R0 / "freeze-manifest.json"
            ),
            str(GATE28.relative_to(REPO_ROOT)): digest(GATE28),
            str((E33_R0 / "workbench.json").relative_to(REPO_ROOT)): digest(
                E33_R0 / "workbench.json"
            ),
            str((E33_R0 / "adjudications.json").relative_to(REPO_ROOT)): digest(
                E33_R0 / "adjudications.json"
            ),
            "plugins/corpus/structured_scoring.py": digest(
                REPO_ROOT / "plugins/corpus/structured_scoring.py"
            ),
        },
        "outputs": {
            name: digest(HERE / name)
            for name in (
                "preregistered-ab-inputs.json",
                "ab-cost-benefit.json",
                "ab-cost-benefit.md",
                "freeze-impact.json",
                "freeze-impact.md",
                "route-b-experiment-protocol.json",
                "route-b-experiment-protocol.md",
                "build_ab_inputs.py",
            )
        },
    }
    (HERE / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def render_cost_benefit(cb: dict[str, Any]) -> str:
    m = cb["measured_inputs"]
    lines = [
        "# 路线 a/b 同量纲成本-收益表",
        "",
        f"- 预注册：`{cb['preregistration']['path']}` `{cb['preregistration']['sha256']}`",
        "- 单位：成本 = 模型调用 / 人工裁定条数 / 冻结修订 / 门次 / 零调用代码改动；收益 = 可匹配金标条数",
        "",
        "## 实测输入（全部取自既有产物）",
        "",
        "| 量 | 值 |",
        "|---|---|",
        f"| 金标分母 | {m['gold_denominator']} |",
        f"| 归一化后字段逐字对齐 | {m['field_identical_after_normalization']} |",
        f"| 逐字证据可达（evidence/35） | {m['verbatim_evidence_reachable']} |",
        f"| 人工裁定区间（上−下） | **{m['human_adjudication_band']}** |",
        f"| 覆盖槽位内无候选 | {m['records_without_candidate']}（其中丢包 {m['lost_packet_records']}） |",
        f"| items 零载体必需字段 | {m['absent_required_fields_items']} |",
        f"| relations 结构性不可评分字段 | {m['relations_structurally_unscoreable']} |",
        f"| gate-32 expected_attempts | {m['gate32_expected_attempts']} |",
        f"| gate-32 automatic_retries | {m['gate32_automatic_retries']} |",
        f"| 门 28 unresolved_candidates_max | {m['gate28_unresolved_candidates_max']} |",
        f"| 契约 matching.mode | `{m['contract_matching_mode']}` |",
        "",
        "## 工作项 × 成本（归属：共同 / route a 边际 / route b 边际 / 独立）",
        "",
        "| ID | 事 | 归属 | 模型调用 | 人工裁定 | 冻结修订 | 门次 | 代码改动 | 依据 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    bucket_label = {
        "common": "共同",
        "route_a_marginal": "a 边际",
        "route_b_marginal": "b 边际",
        "independent": "独立",
    }
    for item in cb["work_items"]:
        c = item["cost"]
        lines.append(
            "| {0} | {1} | {2} | {3} | {4} | {5} | {6} | {7} | {8} |".format(
                item["id"],
                item["name"],
                bucket_label[item["bucket"]],
                c["model_calls"],
                c["human_adjudication_records"],
                c["freeze_revisions"],
                c["gate_runs"],
                c["zero_call_code_changes"],
                item["basis"][:60],
            )
        )
    lines += [
        "",
        "## 分维度合计与共同项占比",
        "",
        "| 维度 | 共同项 | a 边际 | b 边际 | 独立 | 共同项 ≥ 两边际之和 |",
        "|---|---|---|---|---|---|",
    ]
    for dim, blob in cb["totals_by_dimension"].items():
        lines.append(
            "| `{0}` | {1} | {2} | {3} | {4} | {5} |".format(
                dim,
                blob["common"],
                blob["route_a_marginal"],
                blob["route_b_marginal"],
                blob["independent"],
                blob["common_ge_sum_of_marginals"],
            )
        )
    lines += [
        "",
        "## route a vs route b（仅边际项）",
        "",
        "| 维度 | route a | route b |",
        "|---|---|---|",
    ]
    for dim, blob in cb["route_a_vs_b_marginal"].items():
        if dim == "note":
            continue
        lines.append(f"| `{dim}` | {blob['route_a']} | {blob['route_b']} |")
    lines += [
        "",
        f"> {cb['route_a_vs_b_marginal']['note']}",
        "",
        "## 收益情形（三态：measured / bounded / unverified）",
        "",
        "| 情形 | 内容 | 可匹配金标 | 状态 |",
        "|---|---|---|---|",
    ]
    for blob in cb["benefit_scenarios"]:
        value = blob["matchable_gold"]
        shown = (
            f"{value}（实测）"
            if isinstance(value, int)
            else f"[{value['lower']}, {value['upper']}]"
        )
        lines.append(f"| {blob['id']} | {blob['label']} | {shown} | {blob['status']} |")
    lines += [
        "",
        "## 伪二分假设（EC-AB3）",
        "",
        f"- 假设：{cb['pseudo_dichotomy']['hypothesis']}",
        f"- 成立的维度：{cb['pseudo_dichotomy']['holds_on']}",
        f"- 不成立的维度：{cb['pseudo_dichotomy']['does_not_hold_on']}",
        f"- 判定：{cb['pseudo_dichotomy']['verdict']}",
        f"- 状态：{cb['pseudo_dichotomy']['status']}",
        "",
        "## 剩余缺口",
        "",
    ]
    lines += [f"- {k}：{v}" for k, v in cb["remaining_gaps"].items()]
    return "\n".join(lines) + "\n"


def render_freeze_impact(fi: dict[str, Any]) -> str:
    lines = [
        "# route b 冻结影响清单",
        "",
        f"- 触发条件：{fi['trigger']}",
        "",
        "## 受影响（逐条）",
        "",
        "| 物件 | 绑定来源 | 影响方式 | 处置 |",
        "|---|---|---|---|",
    ]
    for item in fi["bound_artifacts"]:
        lines.append(
            "| {0} | {1} | {2} | {3} |".format(
                item["artifact"], item["bound_by"], item["impact"], item["action"]
            )
        )
    lines += [
        "",
        "## 声明不受影响",
        "",
        "| 物件 | 理由 |",
        "|---|---|",
    ]
    for item in fi["unaffected"]:
        lines.append(f"| {item['artifact']} | {item['reason']} |")
    lines += [
        "",
        "## 摘要",
        "",
    ]
    for k, v in fi["summary"].items():
        lines.append(f"- `{k}`：{v}")
    lines += ["", f"> {fi['gate32_gate_self_hash_from_report']}"]
    return "\n".join(lines) + "\n"


def render_protocol(p: dict[str, Any]) -> str:
    lines = [
        "# route b 收益的受控双臂实验（预注册草案，未执行）",
        "",
        f"- 状态：`{p['status']}`",
        f"- 问题：{p['question']}",
        f"- 为什么必须测：{p['why']}",
        "",
        "## 设计",
        "",
        f"- control：{p['design']['arms']['control']}",
        f"- treatment：{p['design']['arms']['treatment']}",
        f"- 同代码要求：{p['design']['same_code_requirement']}",
        f"- 样本：{p['design']['sample']}",
        f"- 预算：试跑 {p['design']['budget']['smoke_model_calls']} 次；全量 {p['design']['budget']['full_model_calls']} 次（{p['design']['budget']['basis']}）",
        "",
        "## 被测指标",
        "",
    ]
    lines += [f"- **{k}**：{v}" for k, v in p["metrics"].items()]
    lines += ["", "## 预注册判据", ""]
    lines += [f"- **{k}**：{v}" for k, v in p["exit_criteria"].items()]
    lines += ["", "## 需要授权（执行前填）", "", "| 项 | 值 |", "|---|---|"]
    lines += [f"| `{k}` | {v or '待填'} |" for k, v in p["authorization_required"].items()]
    lines += ["", "## 范围外", ""]
    lines += [f"- {item}" for item in p["scope_out"]]
    lines += ["", f"> {p['note']}"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
