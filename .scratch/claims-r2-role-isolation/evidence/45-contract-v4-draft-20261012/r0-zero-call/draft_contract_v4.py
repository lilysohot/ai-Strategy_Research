"""Contract v4 draft: consolidate the caliber clause, read path, Stage-2 clause, threshold
single-sourcing and the relations fix into one reviewable proposal.

Zero call, read-only. Implements `preregistered-contract-v4.json` (write-once).

The v3 contract file is NOT modified: the draft lands in this evidence directory, and the
v3 file hash is re-verified at the end (EC-C6). Nothing here is signed or in force.

Usage:
    uv run python .scratch/claims-r2-role-isolation/evidence/41-contract-v4-draft-20261012/r0-zero-call/draft_contract_v4.py
    ... --no-write
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E41 = HERE.parent
CLAIMS = E41.parent.parent
REPO_ROOT = HERE.parents[4]
E36_R0 = CLAIMS / "evidence" / "36-l9-redo-and-baseline-20261011" / "r0-zero-call"
for path in (str(REPO_ROOT), str(E36_R0)):
    if path not in sys.path:
        sys.path.insert(0, path)

from l9_redo import digest, read_json  # noqa: E402

EV = CLAIMS / "evidence"
V3 = EV / "10-quality-gold-expansion-20261008-r2" / "scoring-contract.json"
GOLD = EV / "10-quality-gold-freeze-20261008-r2" / "frozen-gold.json"
E37 = EV / "37-store-baseline-and-route-decision-20261012" / "r0-zero-call" / "store-baseline.json"
E38 = EV / "38-gate33-workbench-rebuild-20261012" / "r0-zero-call" / "workbench-v2.json"
E39 = EV / "39-roles-l3-audit-20261012" / "r0-zero-call" / "roles-l3-audit.json"
E40 = EV / "40-route-ab-decision-inputs-20261012" / "r0-zero-call" / "ab-cost-benefit.json"
GATE28 = EV / "28-items-only-quality-gate-20261010" / "r0-zero-call" / "preregistered-gate.json"
PREREG = HERE / "preregistered-contract-v4.json"


def deep_diff(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    """Machine-computed structural diff; never hand-written (preregistration: diff_is_computed)."""
    out: list[dict[str, Any]] = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            child = f"{path}.{key}" if path else key
            if key not in before:
                out.append({"path": child, "op": "add", "after": after[key]})
            elif key not in after:
                out.append({"path": child, "op": "remove", "before": before[key]})
            else:
                out.extend(deep_diff(before[key], after[key], child))
    elif before != after:
        out.append({"path": path, "op": "change", "before": before, "after": after})
    return out


def build_caliber_rules() -> dict[str, Any]:
    return {
        "principle": "以金标口径为准，在读取/匹配视图上归一化；**不得覆盖候选或金标的原始字段**。",
        "direction_note": (
            "『维持生产端口径并改金标』与 issue-34 §8（冻结金标字节不变）冲突 ⇒ 事实上只剩本方向；"
            "本方向仍标注为待具名签认，草案不自行生效。"
        ),
        "rules": {
            "perspective": {
                "rule": "source_explicit -> unknown（仅匹配视图）",
                "measurement": "evidence/37：raw 0/48 -> 归一化后 32/48（+32）",
                "auto_normalize": True,
            },
            "speech_role": {
                "rule": "question|answer|unknown -> statement",
                "measurement": "evidence/37：raw 34/48 -> 39/48（+5）",
                "auto_normalize": True,
            },
            "statement_role": {
                "rule": "不自动归一化；生产端的 question/answer/other 须人工判定（金标不使用这些取值）",
                "measurement": "evidence/37：归一化后仍仅 21/48",
                "auto_normalize": False,
                "handling": "human_only",
            },
            "semantic_type": {
                "rule": "不自动归一化；生产端 unknown（24 条）须人工判定，金标 behavior（3 条）生产端不产出",
                "measurement": "evidence/37：27/48（归一化无增益）",
                "auto_normalize": False,
                "handling": "human_only",
            },
            "polarity": {
                "rule": "无需规则（两侧同词表）",
                "measurement": "evidence/37：32/48",
                "auto_normalize": False,
            },
            "attribution": {
                "rule": "不作为匹配必需项（粒度不足：生产端 2 类 vs 金标 5 类）",
                "measurement": "evidence/37 EC-A4：layer B 与金标 raw 一致 0/48",
                "auto_normalize": False,
                "handling": "excluded_from_matching_basis",
            },
            "speaker_ref": {
                "rule": "同上（金标内 attribution 与 speaker_ref 1:1 冗余）",
                "measurement": "evidence/37 EC-A4",
                "auto_normalize": False,
                "handling": "excluded_from_matching_basis",
            },
            "source_stance": {
                "rule": "无载体 ⇒ 必须人工按原文判定；**不得设默认值**（默认值属事后拟合）",
                "measurement": "evidence/37 EC-A1：唯一零载体必需字段",
                "auto_normalize": False,
                "handling": "human_only",
            },
        },
    }


def build_read_path() -> dict[str, Any]:
    return {
        "mechanism": "按角色注册读路径：每个契约必需字段声明 carrier 与 normalization；机制与记录 ID 无关。",
        "id_independence": "任何读路径规则不得按 record_id 硬编码（禁止 NT-Ixx 逐条规则）。",
        "review_assertions_status": (
            "契约内 review_assertions 的逐条 ID 断言**仅作回归防退化**，不得作为匹配规则参与评分。"
        ),
        "roles": {
            "material_items": {
                "implemented_in_this_revision": True,
                "carriers": {
                    "proposition": {"carrier": "item.text", "requires": "normalization"},
                    "semantic_type": {"carrier": "item.semantic_type", "requires": "human_only"},
                    "statement_role": {"carrier": "item.statement_role", "requires": "human_only"},
                    "speech_role": {"carrier": "item.speech_role", "requires": "caliber_normalization"},
                    "perspective": {"carrier": "item.perspective", "requires": "caliber_normalization"},
                    "polarity": {"carrier": "item.polarity", "requires": "none"},
                    "speaker_ref": {"carrier": "item.speaker_ref", "requires": "excluded_from_matching_basis"},
                    "attribution": {"carrier": "layer_b.attribution", "requires": "excluded_from_matching_basis"},
                    "source_stance": {"carrier": "none", "requires": "human_only"},
                    "condition": {"carrier": "item.text (statement_role==condition)", "requires": "human_only"},
                },
                "basis": "evidence/37 EC-A1 + evidence/38 contract_view（工作台 v2 已给出雏形）",
            },
            "claims": {
                "implemented_in_this_revision": False,
                "status": "not_observed_on_data；code_level 显示 attribution/perspective/source_stance/estimate_status 无载体（evidence/39）",
            },
            "material_relations": {
                "implemented_in_this_revision": False,
                "status": "协议范围外（实测 0 条）+ 金标主键问题（见 relation_matching）",
            },
        },
    }


def build_adjudication_clause(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": contract["matching"]["mode"],
        "responsible_party": "xyl（待签认确认）",
        "full_coverage_required": {
            "unresolved_max": 0,
            "candidate_records": 222,
            "basis": "门 28 quality_requirements.unresolved_candidates_max = 0；U 2026-10-12 裁定维持全量（选项 a）",
        },
        "required_per_record_fields": list(contract["candidate_adjudication_fields"]),
        "evidence_required": "每条裁定须附逐字引文或原文定位（locator + 区间），不得仅给结论",
        "forbidden": "不得把目标字符串直接赋给候选后宣称自动语义评分（沿用 v3 matching.projection）",
        "tooling": {
            "workbench": "门 33 工作台 v2（evidence/38，含 contract_view 与 field_provenance）",
            "suggestion_policy": "Stage-1 建议仅作辅助；**独立复核或抽样裁定时必须隐藏建议**，以防污染判定",
        },
        "blocking_resolution": (
            "本条即 issue-34 §7-3 的答案：候选→契约字段的规范化责任人在此具名，凭据为逐字引文/定位；"
            "契约不再需要人工『改写命题』这一步骤。"
        ),
    }


def build_threshold_source(gate28: dict[str, Any]) -> dict[str, Any]:
    q = gate28["quality_requirements"]
    return {
        "authority_source": {
            "where": "门 28 preregistered-gate.json quality_requirements（signed）",
            "sha256": digest(GATE28),
            "values": {
                "target_recall_overall_min": q["target_recall_overall_min"],
                "target_recall_per_source_min": q["target_recall_per_source_min"],
                "candidate_precision_min": q["candidate_precision_min"],
                "accepted_records_total_min": q["accepted_records_total_min"],
                "accepted_records_per_source_min": q["accepted_records_per_source_min"],
                "unresolved_candidates_max": q["unresolved_candidates_max"],
            },
        },
        "observed_second_source": {
            "where": "plugins/corpus/structured_scoring.py:332-340（PILOT_CANDIDATE_POLICY）",
            "values": {
                "material_items": {"precision_min": 0.95, "recall_min": 0.90},
                "risk_condition_recall_min": 0.95,
                "report_support_min": 0.95,
            },
        },
        "open_decision": {
            "id": "OPEN-1",
            "question": "阈值以哪个源为单一口径？",
            "options": [
                {
                    "option": "A",
                    "text": "以门 28 为权威（0.85/0.80/20），评分器改为读契约",
                    "consequence": "判定评分器现值（0.95/0.90）为『未经签认的偏离』；数值方向为放宽，须具名签认并记录理由",
                },
                {
                    "option": "B",
                    "text": "维持评分器现值（0.95/0.90）并改门 28",
                    "consequence": "门槛提高；须重算 §6 全部天花板，且与已签认的门 28 冲突，需重新签认门 28",
                },
            ],
            "requires": "具名签认（阈值变更的既有约定）",
        },
        "axes_warning": (
            "`minimum_accepted_records_per_role`（角色轴，20）与门 28 `accepted_records_per_source_min`"
            "（源轴，20）是两个不同轴，不得互相替代或混用。"
        ),
    }


def build_relation_matching() -> dict[str, Any]:
    return {
        "defect": (
            "契约 role_required_fields.material_relations 含 from_gold_record_id / to_gold_record_id，"
            "即要求候选携带金标主键 ⇒ 严格 identity 匹配下该角色恒为 0（evidence/39 EC-B4）"
        ),
        "open_decision": {
            "id": "OPEN-2",
            "question": "material_relations 如何修正？",
            "options": [
                {
                    "option": "A",
                    "text": "改由裁定映射承载（候选只带 item_id，金标主键由 matched_gold_id 提供）",
                    "consequence": "契约条款改动；该角色可评分，但仍需人工裁定",
                },
                {
                    "option": "B",
                    "text": "从必需字段删去两个金标主键字段",
                    "consequence": "字段清单缩短；匹配基改为 relation + provenance",
                },
                {
                    "option": "C",
                    "text": "本轮不纳入 material_relations 评分",
                    "consequence": "范围显式缩小并披露；不产生该角色报分",
                },
            ],
            "requires": "具名签认",
        },
        "scope_note": "另一独立问题：本工作流协议明文不抽 relations，两源实测 0 条（属范围外，不是字段错配）",
    }


def build_bookkeeping() -> dict[str, Any]:
    return {
        "contract_binding_sync": (
            "契约修订必须同轮更新 frozen-gold 侧记录的契约绑定哈希；"
            "现记录 v2 `2eb24be7…` 与实际 v3 `d9bc51f2…` 不符（match=False）"
        ),
        "validation_report_consistency": (
            "validation-report 的 human_accepted_counts 须与 frozen-gold 的 48/48 accepted 一致（现为空 {}）"
        ),
        "freeze_chain_validator_required": "新增机制要求：任何契约/金标/manifest 修订须有校验器验证绑定一致（现无）",
        "gate28_basis_sync": "门 28 的 metric_basis 须随契约版本同步",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="允许覆盖已签认的产物（默认拒写；签认不得由脚本抹掉）",
    )
    args = parser.parse_args()

    # Fail-closed signature guard: never clobber a signed artifact.
    # Incident 2026-10-12: re-running this script silently erased a signature on
    # contract-v4-review.md; the user only authorised revoking chain-report.md.
    SIGNATURE_MARKERS = ("☑ 认可并签认", "☑ 认可本口径", "复核人：xyl", "复核人：　xyl")
    signed_artifacts: list[str] = []
    for name in ("contract-v4-review.md", "proposed-scoring-contract-v4.json"):
        target = HERE / name
        if not target.exists():
            continue
        existing = target.read_text(encoding="utf-8")
        if any(marker in existing for marker in SIGNATURE_MARKERS):
            signed_artifacts.append(name)
    if signed_artifacts and not args.force and not args.no_write:
        raise SystemExit(
            "拒绝写入：检测到已签认产物 %s。签认不得被脚本覆盖。"
            "如确需重生成，须先取得明确指示并使用 --force。" % signed_artifacts
        )

    prereg = read_json(PREREG)
    before = read_json(V3)
    v3_hash_before = digest(V3)
    gate28 = read_json(GATE28)
    e37 = read_json(E37)
    e39 = read_json(E39)

    after = copy.deepcopy(before)
    after["schema_version"] = "non-table-selected-target-scoring-contract-v4"
    after["status"] = "draft_pending_human_signature"
    after["supersedes"] = {
        "schema_version": before["schema_version"],
        "status_at_supersede": before["status"],
        "sha256": v3_hash_before,
        "note": "v4 为 draft；未签认前不生效，v3 字节不变、哈希留存可追溯。",
    }
    after["revision_history"] = list(before["revision_history"]) + [
        {
            "revision": "v4",
            "status": "draft_pending_human_signature",
            "created_on": "2026-10-12",
            "authors": "agent",
            "signed_by": None,
            "basis": "issue-34 §7-1/§7-3/§7-6/§7-7/§7-11/§7-12 与 U 2026-10-12 全量裁定；依据 evidence/36–40 实测",
            "changes": [
                "新增 caliber_rules（逐字段口径归一化；方向由 §8 硬约束推定）",
                "新增 read_path（角色通用机制，本期仅 material_items 落地；声明与记录 ID 无关）",
                "新增 adjudication_clause（Stage 2 责任人/凭据/全量 222）",
                "新增 threshold_source（双源并列 + OPEN-1）",
                "新增 relation_matching（金标主键缺陷 + OPEN-2）",
                "新增 bookkeeping_requirements（绑定同步/校验器/validation-report）",
                "matching.projection 增补：归一化不得覆盖原始字段",
                "status 由 frozen_signed 退回 draft_pending_human_signature（v4 未签认）",
            ],
        }
    ]
    after["signoff"] = {
        "signed_by": "",
        "signed_on": "",
        "statement": "【待签认】本 v4 草案覆盖 issue-34 §7-1/§7-3/§7-6/§7-7/§7-11/§7-12；签认前不生效。",
        "scope_note": "签认只定读路径、口径与度量口径；不代表 items-only 真实复验通过、不代表发布或语境完整。",
    }
    after["caliber_rules"] = build_caliber_rules()
    after["read_path"] = build_read_path()
    after["adjudication_clause"] = build_adjudication_clause(before)
    after["threshold_source"] = build_threshold_source(gate28)
    after["relation_matching"] = build_relation_matching()
    after["bookkeeping_requirements"] = build_bookkeeping()
    after["matching"] = dict(before["matching"])
    after["matching"]["projection"] = (
        before["matching"]["projection"]
        + " 读路径/口径归一化只作用于匹配视图，不得覆盖候选或金标的原始字段；原始候选字段必须完整留存。"
    )

    diff = deep_diff(before, after)
    applied_paths = {item["path"].split(".")[0] for item in diff}
    declared_roots = {item["path"].split(".")[0] for item in prereg["declared_changes"]}
    open_decisions = {
        "schema_version": "items-contract-v4-open-decisions-1",
        "created_on": "2026-10-12",
        "items": [
            after["threshold_source"]["open_decision"],
            after["relation_matching"]["open_decision"],
        ],
        "forced_by_constraint": [
            {
                "id": "FORCED-1",
                "item": "口径方向（§7-11）",
                "forced_to": "以金标口径为准、读时归一化",
                "why": "另一选项『维持生产端口径并改金标』与 issue-34 §8（金标字节不变）冲突",
                "still_requires": "具名签认（方向已定，条款仍须签）",
            }
        ],
        "notes": [
            "OPEN-1 与 OPEN-2 在草案中以并列选项承载，未预设结论（preregistration: no_silent_picks）。",
        ],
    }
    consistency = {
        "diff_covers_all_declared_roots": declared_roots <= applied_paths,
        "declared_roots": sorted(declared_roots),
        "diff_roots": sorted(applied_paths),
        "status_is_draft": after["status"] == "draft_pending_human_signature",
        "no_signer_filled": after["signoff"]["signed_by"] == ""
        and after["revision_history"][-1]["signed_by"] is None,
    }
    result = {
        "schema_version": "items-contract-v4-draft-1",
        "created_on": "2026-10-12",
        "zero_call": True,
        "draft_is_not_a_delivery": prereg["method"]["draft_is_not_delivery"],
        "inputs": {
            "contract_v3": v3_hash_before,
            "gold": digest(GOLD),
            "gate28": digest(GATE28),
            "evidence37": digest(E37),
            "evidence38": digest(E38),
            "evidence39": digest(E39),
            "evidence40": digest(E40),
        },
        "consistency_check": consistency,
        "open_decisions": open_decisions,
        "measurement_notes": {
            "items_absent_required_fields": e37["ec_a1_field_carriers"]["absent_required_fields"],
            "items_5tuple_alignment": e37["ec_a3_tuple_alignment"]["5tuple"]["records"],
            "relations_unscoreable": e39["verdicts"]["ec_b4_structurally_unscoreable"]["fields"],
        },
    }

    print(
        json.dumps(
            {
                "v3_sha256": v3_hash_before,
                "diff_entries": len(diff),
                "consistency": consistency,
                "open_decisions": [item["id"] for item in open_decisions["items"]],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.no_write:
        return

    (HERE / "proposed-scoring-contract-v4.json").write_text(
        json.dumps(after, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "contract-v4-diff.json").write_text(
        json.dumps(
            {"schema_version": "items-contract-v4-diff-1", "v3_sha256": v3_hash_before, "entries": diff},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (HERE / "contract-v4-diff.md").write_text(render_diff(diff, before, after), encoding="utf-8")
    (HERE / "contract-v4-open-decisions.json").write_text(
        json.dumps(open_decisions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "contract-v4-review.md").write_text(render_review(result, after, open_decisions), encoding="utf-8")

    v3_hash_after = digest(V3)
    if v3_hash_after != v3_hash_before:
        raise SystemExit("EC-C6 violated: v3 contract file changed")

    manifest = {
        "schema_version": "items-contract-v4-draft-manifest-1",
        "created_on": "2026-10-12",
        "inputs": {
            str(PREREG.relative_to(REPO_ROOT)): digest(PREREG),
            str(V3.relative_to(REPO_ROOT)): v3_hash_before,
            str(GOLD.relative_to(REPO_ROOT)): digest(GOLD),
            str(GATE28.relative_to(REPO_ROOT)): digest(GATE28),
            str(E37.relative_to(REPO_ROOT)): digest(E37),
            str(E38.relative_to(REPO_ROOT)): digest(E38),
            str(E39.relative_to(REPO_ROOT)): digest(E39),
            str(E40.relative_to(REPO_ROOT)): digest(E40),
        },
        "outputs": {
            name: digest(HERE / name)
            for name in (
                "preregistered-contract-v4.json",
                "proposed-scoring-contract-v4.json",
                "contract-v4-diff.json",
                "contract-v4-diff.md",
                "contract-v4-open-decisions.json",
                "contract-v4-review.md",
                "draft_contract_v4.py",
            )
        },
        "v3_unchanged_verified": True,
    }
    (HERE / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def render_diff(diff: list[dict[str, Any]], before: dict[str, Any], after: dict[str, Any]) -> str:
    lines = [
        "# 契约 v3 → v4 草案 差异（机器计算）",
        "",
        f"- 差异条目：{len(diff)}",
        f"- v3：`{before['schema_version']}` / `{before['status']}`",
        f"- v4 草案：`{after['schema_version']}` / `{after['status']}`",
        "",
        "| JSON 路径 | 操作 | 旧值 | 新值 |",
        "|---|---|---|---|",
    ]

    def brief(value: Any, limit: int = 160) -> str:
        text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
        text = text.replace("|", "\\|").replace("\n", " ")
        return text if len(text) <= limit else text[:limit] + "…"

    for item in diff:
        lines.append(
            "| `{0}` | {1} | {2} | {3} |".format(
                item["path"],
                item["op"],
                brief(item.get("before", "—")),
                brief(item.get("after", "—")),
            )
        )
    lines += [
        "",
        "> 本差异由脚本递归 diff 计算，非手写；审阅对象与 `proposed-scoring-contract-v4.json` 一致。",
    ]
    return "\n".join(lines) + "\n"


def render_review(
    result: dict[str, Any], after: dict[str, Any], open_decisions: dict[str, Any]
) -> str:
    lines = [
        "# 契约 v4 草案 · 审阅件",
        "",
        "> **本草案不是交付物、不入冻结链**；签认前不生效。v3 契约字节未变。",
        "",
        f"- v3 哈希：`{result['inputs']['contract_v3']}`",
        f"- 状态：`{after['status']}`；`signoff.signed_by` 为空：**{result['consistency_check']['no_signer_filled']}**",
        f"- diff 覆盖全部声明改动：**{result['consistency_check']['diff_covers_all_declared_roots']}**",
        "",
        "## 一、待你裁定（2 项 OPEN + 1 项已由硬约束推定）",
        "",
    ]
    for item in open_decisions["items"]:
        lines.append(f"### {item['id']}：{item['question']}")
        lines.append("")
        lines.append("| 选项 | 内容 | 后果 |")
        lines.append("|---|---|---|")
        for option in item["options"]:
            lines.append(f"| {option['option']} | {option['text']} | {option['consequence']} |")
        lines.append("")
        lines.append(f"- 签认要求：{item['requires']}")
        lines.append("")
    for item in open_decisions["forced_by_constraint"]:
        lines.append(f"### {item['id']}：{item['item']}")
        lines.append("")
        lines.append(f"- 结果：**{item['forced_to']}**")
        lines.append(f"- 理由：{item['why']}")
        lines.append(f"- 仍需：{item['still_requires']}")
        lines.append("")
    lines += [
        "## 二、草案已写入的条款（review 对象）",
        "",
        "| 节 | 作用 |",
        "|---|---|",
        "| `caliber_rules` | 逐字段口径归一化规则 + 依据测量值 + 是否可自动归一 |",
        "| `read_path` | 角色通用读路径机制；本期仅 `material_items` 落地；声明与记录 ID 无关 |",
        "| `adjudication_clause` | Stage 2 责任人与凭据（含全量 222 条、逐字引文要求、建议隐藏要求） |",
        "| `threshold_source` | 双源并列（门 28 vs 评分器）+ OPEN-1 + 轴警告 |",
        "| `relation_matching` | 金标主键缺陷 + OPEN-2 |",
        "| `bookkeeping_requirements` | 绑定同步 / 冻结链校验器 / validation-report 一致性 |",
        "| `matching.projection` | 增补：归一化不得覆盖原始字段 |",
        "",
        "## 三、实测支撑",
        "",
        f"- items 零载体必需字段：`{result['measurement_notes']['items_absent_required_fields']}`",
        f"- 归一化后 5 元组对齐：**{result['measurement_notes']['items_5tuple_alignment']}/48**",
        f"- relations 结构性不可评分字段：`{result['measurement_notes']['relations_unscoreable']}`",
        "",
        "## 四、签认栏（草案）",
        "",
        "- 复核人：　　　　日期：",
        "- 结论：☐ 认可并签认 v4　☐ 退回修改",
        "- OPEN-1 选择：☐ A（门 28 权威）　☐ B（评分器现值并改门）",
        "- OPEN-2 选择：☐ A（裁定映射）　☐ B（删字段）　☐ C（本轮不纳入）",
        "- 备注：",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
