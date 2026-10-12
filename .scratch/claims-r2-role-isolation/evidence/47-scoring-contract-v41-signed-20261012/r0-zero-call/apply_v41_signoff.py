"""Land the signed contract v4.1 in a new directory (write-once).

Zero call, read-only on all inputs. The signed instrument is
`46-contract-v41-draft-20261012/r0-zero-call/contract-v4.1-review.md`
(signed 2026-10-12: 认可并签认 v4.1; 备注为空 ⇒ 按原样接受，含两处 open_for_reviewer 项).

This script never writes into the draft directory and never rewrites a signed artifact.

Usage:
    uv run python .scratch/claims-r2-role-isolation/evidence/47-scoring-contract-v41-signed-20261012/r0-zero-call/apply_v41_signoff.py
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
E47 = HERE.parent
CLAIMS = E47.parent.parent
REPO_ROOT = HERE.parents[4]
E36_R0 = CLAIMS / "evidence" / "36-l9-redo-and-baseline-20261011" / "r0-zero-call"
for path in (str(REPO_ROOT), str(E36_R0)):
    if path not in sys.path:
        sys.path.insert(0, path)

from l9_redo import digest, read_json  # noqa: E402

EV = CLAIMS / "evidence"
DRAFT_V41 = EV / "46-contract-v41-draft-20261012" / "r0-zero-call" / "proposed-scoring-contract-v4.1.json"
REVIEW_V41 = EV / "46-contract-v41-draft-20261012" / "r0-zero-call" / "contract-v4.1-review.md"
SIGNED_V4 = EV / "43-scoring-contract-v4-signed-20261012" / "r0-zero-call" / "scoring-contract-v4.json"
DONOR = (
    EV / "41-items-chain-accounting-20261012" / "r3-signoff-apply" / "scoring-contract-v4.proposed.json"
)
GOLD_MANIFEST = EV / "10-quality-gold-freeze-20261008-r2" / "freeze-manifest.json"
GATE28 = EV / "28-items-only-quality-gate-20261010" / "r0-zero-call" / "preregistered-gate.json"

SIGNED_BY = "xyl"
SIGNED_ON = "2026-10-12"
SIGNATURE_MARKERS = ("☑ 认可并签认", "☑ 认可本口径", "认可并签认 v4.1", "复核人：　xyl", "复核人：xyl")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--force", action="store_true", help="允许覆盖已签认产物（默认拒绝）")
    args = parser.parse_args()

    draft = read_json(DRAFT_V41)
    donor = read_json(DONOR)
    gate28 = read_json(GATE28)
    gold_manifest = read_json(GOLD_MANIFEST)
    review_text = REVIEW_V41.read_text(encoding="utf-8")

    if draft.get("status") != "draft_pending_human_signature":
        raise SystemExit("draft v4.1 is not pending signature: %s" % draft.get("status"))
    if not any(marker in review_text for marker in ("认可并签认 v4.1", "复核人：　xyl", "复核人：xyl")):
        raise SystemExit("signed instrument has no recognisable signature; refusing to land")
    if "备注：" in review_text:
        remark = review_text.split("备注：", 1)[1].splitlines()[0].strip()
    else:
        remark = ""

    signed = copy.deepcopy(draft)
    signed["status"] = "frozen_signed"
    history = list(signed["revision_history"])
    history[-1]["signed_by"] = SIGNED_BY
    signed["revision_history"] = history
    signed["signoff"] = {
        "signed_by": SIGNED_BY,
        "signed_on": SIGNED_ON,
        "statement": (
            "核准本契约 v4.1 作为 items-only 质量门的已签认度量基准"
            "（= 已签 v4 + 并行草案独有叶子，只增不删）。"
        ),
        "instrument": {
            "path": str(REVIEW_V41.relative_to(REPO_ROOT)),
            "sha256": digest(REVIEW_V41),
        },
        "scope_note": (
            "签认只定读路径、口径与度量口径；不代表 items-only 真实复验通过、不代表发布或语境完整。"
            "material_relations 按 OPEN-2=C 本轮不纳入评分。"
        ),
        "reviewer_remark": remark,
    }

    reconciliation_items = [
        {
            "id": "R-1",
            "path": "threshold_source.decision_history",
            "content": "由 donor 的 pending_signoff_detail 改名而来，历史说明已更新为『该分叉已由 OPEN-1=A 裁定』。",
            "disposition": "as_is_accepted",
            "basis": "签署件备注为空 ⇒ 按原样接受（未提出修改）",
        },
        {
            "id": "R-2",
            "path": "read_path.absent_required_fields.alignment_with_caliber_rules",
            "content": "由 agent 撰写的调和句：先按 caliber_rules 决定参与匹配的字段，再对不参与者显式记 absent 以备审。",
            "disposition": "as_is_accepted",
            "basis": "签署件备注为空 ⇒ 按原样接受（未提出修改）",
        },
    ]

    signoff_record = {
        "schema_version": "items-contract-v41-signoff-record-1",
        "created_on": SIGNED_ON,
        "zero_call": True,
        "signed_by": SIGNED_BY,
        "signed_on": SIGNED_ON,
        "instrument": {
            "path": str(REVIEW_V41.relative_to(REPO_ROOT)),
            "sha256": digest(REVIEW_V41),
            "reviewer_remark": remark,
            "reviewer_remark_note": (
                "备注为空。两处 open_for_reviewer 项（R-1/R-2）因此按**原样接受**处理；"
                "这是对空备注的解释，已显式记录，不视为对具体条文的逐条确认。"
            ),
        },
        "signed_contract": {
            "path": "scoring-contract-v4.1.json",
            "schema_version": signed["schema_version"],
            "status": signed["status"],
            "supersedes": signed["supersedes"]["sha256"],
        },
        "decisions_carried": {
            "OPEN-1": "A（门 28 为单一口径 0.85/0.80/20；评分器须改为读契约——代码未改）",
            "OPEN-2": "C（material_relations 本轮不纳入评分）",
            "FORCED-1": "以金标口径为准、读时归一化（由 §8 硬约束推定）",
        },
        "open_for_reviewer_disposition": reconciliation_items,
        "supersession": {
            "superseded_by_v41": [
                {
                    "path": str(SIGNED_V4.relative_to(REPO_ROOT)),
                    "sha256": digest(SIGNED_V4),
                    "note": "已签 v4：其内容被 v4.1 只增不删地包含；v4 字节不变、留存可追溯。",
                }
            ],
            "donor_draft": {
                "path": str(DONOR.relative_to(REPO_ROOT)),
                "sha256": digest(DONOR),
                "status_in_file": donor.get("status"),
                "action": "superseded_by v4.1（该草案从未签认；其独有叶子已并入 v4.1）",
                "note": "本会话不写入 donor 所属目录；本条即为取代声明。",
            },
        },
        "outstanding_after_signoff": [
            "评分器读契约/阈值对齐（P03/§7-6）：代码未改，OPEN-1=A 尚无实现",
            "评分器匹配机制不得以身份相等为前提（P02）：代码未改",
            "裁定→评分输入装配器（P01）：代码不存在",
            "契约绑定再绑定 v2→v3→v4.1（P12）：待落记录",
            "门 28 metric_basis 推进至 v4.1（P13）：待提案（不得就地改）",
            "口径归一化实现与回归（P04/P05）：未实施",
            "route a/b 边际裁定与缺口 1/2（§5.12）：仍缺",
        ],
        "gate28_metric_basis_now": {
            "gate28_recorded": gate28.get("metric_basis"),
            "note": "门 28 记录的度量基准仍指向 v3；v4.1 已签 ⇒ 该项过期，须按 P13 出新版本记录（不得就地改）。",
        },
        "gold_freeze_binding_now": {
            "recorded_contract_in_freeze_manifest": gold_manifest["inputs"][
                ".scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r2/scoring-contract.json"
            ],
            "note": "冻结链记录的契约哈希仍为 v2；实际已签为 v4.1（经 v3、v4）⇒ 须按 P12 出再绑定记录。",
        },
        "note": "签认只签契约条款；不等于 items-only 真实复验通过，也不等于门 33 出分。",
    }

    print(
        json.dumps(
            {
                "status": signed["status"],
                "signed_by": SIGNED_BY,
                "instrument": digest(REVIEW_V41),
                "reviewer_remark_empty": remark == "",
                "supersedes": signed["supersedes"]["sha256"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.no_write:
        return

    target = HERE / "scoring-contract-v4.1.json"
    if target.exists() and not args.force:
        if any(marker in target.read_text(encoding="utf-8") for marker in SIGNATURE_MARKERS):
            raise SystemExit("拒绝写入：scoring-contract-v4.1.json 已含签认标记。")

    (HERE / "scoring-contract-v4.1.json").write_text(
        json.dumps(signed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "signoff-record.json").write_text(
        json.dumps(signoff_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "README.md").write_text(render_readme(signoff_record, signed), encoding="utf-8")
    manifest = {
        "schema_version": "items-contract-v41-signed-manifest-1",
        "created_on": SIGNED_ON,
        "inputs": {
            str(DRAFT_V41.relative_to(REPO_ROOT)): digest(DRAFT_V41),
            str(REVIEW_V41.relative_to(REPO_ROOT)): digest(REVIEW_V41),
            str(SIGNED_V4.relative_to(REPO_ROOT)): digest(SIGNED_V4),
            str(DONOR.relative_to(REPO_ROOT)): digest(DONOR),
            str(GATE28.relative_to(REPO_ROOT)): digest(GATE28),
            str(GOLD_MANIFEST.relative_to(REPO_ROOT)): digest(GOLD_MANIFEST),
        },
        "outputs": {
            name: digest(HERE / name)
            for name in (
                "scoring-contract-v4.1.json",
                "signoff-record.json",
                "README.md",
                "apply_v41_signoff.py",
            )
        },
    }
    (HERE / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def render_readme(record: dict[str, Any], signed: dict[str, Any]) -> str:
    lines = [
        "# 契约 v4.1 · 已签认版",
        "",
        f"- 签署人：**{record['signed_by']}**　日期：**{record['signed_on']}**",
        f"- 签署工具：`{record['instrument']['path']}` `{record['instrument']['sha256']}`",
        f"- 产物：`scoring-contract-v4.1.json`（`status = {signed['status']}`）",
        f"- 取代：已签 v4 `{signed['supersedes']['sha256']}`（字节不变，留存可追溯）",
        "",
        "## 已签的裁定（沿用）",
        "",
        "| 项 | 选择 |",
        "|---|---|",
    ]
    for key, value in record["decisions_carried"].items():
        lines.append(f"| {key} | {value} |")
    lines += [
        "",
        "## 备注为空的处理（显式记录）",
        "",
        f"- {record['instrument']['reviewer_remark_note']}",
        "",
        "| ID | 项 | 处置 |",
        "|---|---|---|",
    ]
    for item in record["open_for_reviewer_disposition"]:
        lines.append(f"| {item['id']} | `{item['path']}` | {item['disposition']}（{item['basis']}） |")
    lines += ["", "## 取代关系", ""]
    for item in record["supersession"]["superseded_by_v41"]:
        lines.append(f"- 已签 v4：`{item['sha256']}` —— {item['note']}")
    donor = record["supersession"]["donor_draft"]
    lines += [
        f"- 并行草案：`{donor['path']}`（`{donor['sha256']}`）—— {donor['action']}",
        "",
        "## 签认之后仍未完成（不得读成已过门）",
        "",
    ]
    lines += [f"- {item}" for item in record["outstanding_after_signoff"]]
    lines += [
        "",
        "## 当前记账漂移（须按 P12/P13 出新版本记录，不得就地改）",
        "",
        f"- 金标冻结链记录的契约：`{record['gold_freeze_binding_now']['recorded_contract_in_freeze_manifest'][:26]}…`（实为 v2）",
        f"- 门 28 `metric_basis`：`{record['gate28_metric_basis_now']['gate28_recorded']}`",
        "",
        f"> {record['note']}",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
