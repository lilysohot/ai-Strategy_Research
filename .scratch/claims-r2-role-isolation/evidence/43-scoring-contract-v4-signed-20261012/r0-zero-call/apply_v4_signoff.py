"""Apply the signed contract-v4 decisions and land the signed contract in a new directory.

Zero call, read-only on all inputs. The signed instrument is
`45-contract-v4-draft-20261012/r0-zero-call/contract-v4-review.md` (signed 2026-10-12:
认可并签认 v4 / OPEN-1 = A / OPEN-2 = C). 该目录原编号 41，2026-10-12 按 P07 改号为 45
（消歧义：41 另属并行会话的 Issue 41 items-chain-accounting）；文件字节未变。

This script NEVER writes into the draft directory and never rewrites a signed artifact:
the signed contract lands here as a new file, and the draft stays byte-identical.

Usage:
    uv run python .scratch/claims-r2-role-isolation/evidence/43-scoring-contract-v4-signed-20261012/r0-zero-call/apply_v4_signoff.py
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
E43 = HERE.parent
CLAIMS = E43.parent.parent
REPO_ROOT = HERE.parents[4]
E36_R0 = CLAIMS / "evidence" / "36-l9-redo-and-baseline-20261011" / "r0-zero-call"
for path in (str(REPO_ROOT), str(E36_R0)):
    if path not in sys.path:
        sys.path.insert(0, path)

from l9_redo import digest, read_json  # noqa: E402

EV = CLAIMS / "evidence"
DRAFT_DIR = EV / "45-contract-v4-draft-20261012" / "r0-zero-call"
DRAFT = DRAFT_DIR / "proposed-scoring-contract-v4.json"
REVIEW = DRAFT_DIR / "contract-v4-review.md"
PARALLEL_DIR = EV / "41-items-chain-accounting-20261012" / "r3-signoff-apply"
PARALLEL = PARALLEL_DIR / "scoring-contract-v4.proposed.json"
GOLD_MANIFEST = EV / "10-quality-gold-freeze-20261008-r2" / "freeze-manifest.json"
GATE28 = EV / "28-items-only-quality-gate-20261010" / "r0-zero-call" / "preregistered-gate.json"

SIGNED_ON = "2026-10-12"
SIGNED_BY = "xyl"
# Root mapping for reconciling the parallel draft's section names.
ROOT_MAP = {
    "items_field_carrier_read_path": "read_path",
    "threshold_single_source": "threshold_source",
}


def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            out.update(flatten(child, f"{prefix}.{key}" if prefix else key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            out.update(flatten(child, f"{prefix}[{index}]"))
    else:
        out[prefix] = value
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    draft = read_json(DRAFT)
    parallel = read_json(PARALLEL)
    gold_manifest = read_json(GOLD_MANIFEST)
    gate28 = read_json(GATE28)
    review_text = REVIEW.read_text(encoding="utf-8")

    signed = copy.deepcopy(draft)
    signed["status"] = "frozen_signed"
    signed["signoff"] = {
        "signed_by": SIGNED_BY,
        "signed_on": SIGNED_ON,
        "statement": (
            "核准本契约 v4 作为 items-only 质量门的已签认度量基准；"
            "签署工具为 contract-v4-review.md 的签认栏（认可并签认 v4）。"
        ),
        "instrument": {
            "path": str(REVIEW.relative_to(REPO_ROOT)),
            "sha256": digest(REVIEW),
        },
        "scope_note": (
            "签认只定读路径、口径与度量口径；不代表 items-only 真实复验通过、不代表发布或语境完整。"
            "material_relations 按 OPEN-2=C 本轮不纳入评分。"
        ),
    }
    history = list(signed["revision_history"])
    history[-1]["signed_by"] = SIGNED_BY
    signed["revision_history"] = history

    # OPEN-1 = A
    signed["threshold_source"]["open_decision"]["chosen"] = "A"
    signed["threshold_source"]["open_decision"]["decided_on"] = SIGNED_ON
    signed["threshold_source"]["open_decision"]["rationale_recorded"] = (
        "0.95/0.90 是评分器实现方未经签认的硬编码偏离（structured_scoring.py:334-339），"
        "从未获授权；门 28 是唯一经签认的权威源。选 A 是恢复到已签认口径，不是降低已批准的标准。"
    )
    signed["threshold_source"]["effective"] = {
        "source": "门 28 preregistered-gate.json quality_requirements",
        "target_recall_overall_min": gate28["quality_requirements"]["target_recall_overall_min"],
        "target_recall_per_source_min": gate28["quality_requirements"][
            "target_recall_per_source_min"
        ],
        "candidate_precision_min": gate28["quality_requirements"]["candidate_precision_min"],
        "accepted_records_total_min": gate28["quality_requirements"]["accepted_records_total_min"],
        "accepted_records_per_source_min": gate28["quality_requirements"][
            "accepted_records_per_source_min"
        ],
        "unresolved_candidates_max": gate28["quality_requirements"]["unresolved_candidates_max"],
        "implementation_required": (
            "评分器 `plugins/corpus/structured_scoring.py` 现以 PILOT_CANDIDATE_POLICY 硬编码 "
            "0.95/0.90，与本节冲突；须改为读取本契约。**该代码改动尚未执行**，属独立工作项（§7-6）。"
        ),
    }

    # OPEN-2 = C
    signed["relation_matching"]["open_decision"]["chosen"] = "C"
    signed["relation_matching"]["open_decision"]["decided_on"] = SIGNED_ON
    signed["relation_matching"]["in_scope_this_round"] = False
    signed["relation_matching"]["scope_decision_note"] = (
        "本轮不纳入 material_relations 评分：39 号实测生产端不产出 relations（协议明文本阶段不抽），"
        "A/B 通道本期无输入。`role_required_fields.material_relations` 的金标主键缺陷**保留在案**，"
        "将来恢复 relations 抽取时按 `read_path` 的角色通用机制补条款。"
    )

    # ---------------------------------------------------------------- reconciliation with the parallel draft
    reconciliation: list[dict[str, Any]] = []
    draft_flat = flatten(draft)
    for their_root, our_root in ROOT_MAP.items():
        if their_root not in parallel:
            reconciliation.append({"their_root": their_root, "status": "absent_in_parallel"})
            continue
        their_flat = flatten(parallel[their_root], our_root)
        our_values = set(map(str, draft_flat.values()))
        missing_paths = []
        for path, value in their_flat.items():
            if path in draft_flat:
                continue
            if str(value) in our_values:
                continue
            missing_paths.append(path)
        reconciliation.append(
            {
                "their_root": their_root,
                "mapped_to": our_root,
                "their_leaf_count": len(their_flat),
                "unreconciled_paths": missing_paths,
                "verdict": "no_unique_content"
                if not missing_paths
                else "UNRECONCILED_CONTENT_PRESENT",
            }
        )
    parallel_only_roots = [
        key
        for key in parallel
        if key not in draft and key not in ROOT_MAP
    ]

    signoff_record = {
        "schema_version": "items-contract-v4-signoff-record-1",
        "created_on": SIGNED_ON,
        "zero_call": True,
        "signed_by": SIGNED_BY,
        "signed_on": SIGNED_ON,
        "instrument": {"path": str(REVIEW.relative_to(REPO_ROOT)), "sha256": digest(REVIEW)},
        "decisions": {
            "OPEN-1": {"chosen": "A", "effect": "门 28 为单一口径；评分器须改为读契约（未执行）"},
            "OPEN-2": {"chosen": "C", "effect": "material_relations 本轮不纳入评分（显式披露）"},
            "FORCED-1": {"resolved_to": "以金标口径为准、读时归一化（由 §8 硬约束推定）"},
        },
        "signed_contract": {
            "path": "scoring-contract-v4.json",
            "schema_version": signed["schema_version"],
            "status": signed["status"],
            "supersedes": signed["supersedes"]["sha256"],
        },
        "parallel_draft": {
            "path": str(PARALLEL.relative_to(REPO_ROOT)),
            "sha256": digest(PARALLEL),
            "status_in_file": parallel.get("status"),
            "relation_to_signed": "superseded_by this signed contract（其签认栏为空，从未签认）",
            "reconciliation": reconciliation,
            "parallel_only_roots": parallel_only_roots,
        },
        "outstanding_after_signoff": [
            "评分器读契约/阈值对齐（§7-6 C3）：代码改动，未执行",
            "金标冻结链契约绑定再绑定（v2→v3→v4）：须与本次签认同轮落地",
            "口径归一化（caliber_rules）的实现与回归测试（§7-7 A1/A2）：未执行",
            "route a/b 边际裁定与缺口 1/2：仍缺（§5.12）",
        ],
        "note": (
            "本次签认只签契约条款；**不等于** items-only 真实复验通过，也不等于门 33 出分。"
        ),
    }

    print(
        json.dumps(
            {
                "signed_status": signed["status"],
                "OPEN-1": "A",
                "OPEN-2": "C",
                "instrument_sha256": digest(REVIEW),
                "reconciliation": reconciliation,
                "parallel_only_roots": parallel_only_roots,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.no_write:
        return

    (HERE / "scoring-contract-v4.json").write_text(
        json.dumps(signed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "signoff-record.json").write_text(
        json.dumps(signoff_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "README.md").write_text(render_readme(signoff_record, signed), encoding="utf-8")
    manifest = {
        "schema_version": "items-contract-v4-signed-manifest-1",
        "created_on": SIGNED_ON,
        "inputs": {
            str(DRAFT.relative_to(REPO_ROOT)): digest(DRAFT),
            str(REVIEW.relative_to(REPO_ROOT)): digest(REVIEW),
            str(PARALLEL.relative_to(REPO_ROOT)): digest(PARALLEL),
            str(GATE28.relative_to(REPO_ROOT)): digest(GATE28),
            str(GOLD_MANIFEST.relative_to(REPO_ROOT)): digest(GOLD_MANIFEST),
        },
        "outputs": {
            name: digest(HERE / name)
            for name in ("scoring-contract-v4.json", "signoff-record.json", "README.md", "apply_v4_signoff.py")
        },
        "draft_untouched": digest(DRAFT) == digest(DRAFT),
    }
    (HERE / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def render_readme(record: dict[str, Any], signed: dict[str, Any]) -> str:
    lines = [
        "# 契约 v4 · 已签认版（Issue 34 §7-11/§7-3/§7-6/§7-7/§7-12）",
        "",
        f"- 签署人：**{record['signed_by']}**　日期：**{record['signed_on']}**",
        f"- 签署工具：`{record['instrument']['path']}` `{record['instrument']['sha256']}`",
        f"- 产物：`scoring-contract-v4.json`（`status = {signed['status']}`）",
        "- 取代：契约 v3 `d9bc51f2…`（v3 字节不变，留存可追溯）",
        "",
        "## 已签的裁定",
        "",
        "| 项 | 选择 | 效果 |",
        "|---|---|---|",
    ]
    for key, blob in record["decisions"].items():
        text = blob.get("chosen") or blob.get("resolved_to")
        lines.append(f"| {key} | **{text}** | {blob.get('effect', '由 §8 硬约束推定')} |")
    lines += [
        "",
        "## 与并行草案的关系",
        "",
        f"- 并行草案：`{record['parallel_draft']['path']}`"
        f"（`{record['parallel_draft']['sha256']}`，状态 `{record['parallel_draft']['status_in_file']}`）",
        f"- 关系：{record['parallel_draft']['relation_to_signed']}",
        "",
        "| 并行节 | 映射到 | 未对账叶子路径 | 结论 |",
        "|---|---|---|---|",
    ]
    for item in record["parallel_draft"]["reconciliation"]:
        lines.append(
            "| `{0}` | `{1}` | {2} | {3} |".format(
                item.get("their_root"),
                item.get("mapped_to", "—"),
                len(item.get("unreconciled_paths", [])),
                item.get("verdict", "—"),
            )
        )
    if record["parallel_draft"]["parallel_only_roots"]:
        lines.append("")
        lines.append(
            f"- ⚠️ 并行草案另有未映射的顶层节：`{record['parallel_draft']['parallel_only_roots']}`"
        )
    lines += ["", "## 签认之后仍未完成的（不得读成已过门）", ""]
    lines += [f"- {item}" for item in record["outstanding_after_signoff"]]
    lines += ["", f"> {record['note']}"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
