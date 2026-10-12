"""Land the signed contract v4.2 (U signed 2026-10-12) in a new directory (write-once).

Zero call, read-only on all inputs. The signed instrument is
``57-contract-v42-draft-20261012/r0-zero-call/contract-v4.2-review.md``
(``复核人 xyl／2026-10-12``，☑ 认可并签认 v4.2；备注为空 ⇒ 草案按原样接受).

v4.2 changes exactly one thing substantively: ``threshold_source.authority_source`` is re-pinned
from gate 28's frozen execution record (v1) to P13's basis-holding record (v2) — U's ruling (a)
on the item P16's validator flagged. All six threshold values are byte-identical.

Usage:
    uv run python .scratch/.../58-contract-v42-signed-20261012/r0-zero-call/apply_v42_signoff.py
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
E58 = HERE.parent
CLAIMS = E58.parent.parent
REPO_ROOT = HERE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from tools.evidence_guard import artifact_state, write_once  # noqa: E402

EV = CLAIMS / "evidence"
DRAFT_V42 = (
    EV / "57-contract-v42-draft-20261012" / "r0-zero-call" / "proposed-scoring-contract-v4.2.json"
)
REVIEW_V42 = EV / "57-contract-v42-draft-20261012" / "r0-zero-call" / "contract-v4.2-review.md"
SIGNED_V41 = (
    EV / "47-scoring-contract-v41-signed-20261012" / "r0-zero-call" / "scoring-contract-v4.1.json"
)
GATE_V1 = EV / "28-items-only-quality-gate-20261010" / "r0-zero-call" / "preregistered-gate.json"
GATE_V2 = EV / "28-items-only-quality-gate-20261010" / "r0-zero-call" / "preregistered-gate-v2.json"

SIGNED_BY = "xyl"
SIGNED_ON = "2026-10-12"
SHEET_UNSIGNED_SHA = "sha256:759e89c22dc8d070cab4f3af"


def sha256(path: Path) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    draft = json.loads(DRAFT_V42.read_text(encoding="utf-8"))
    sheet_text = REVIEW_V42.read_text(encoding="utf-8")
    sheet_hash = sha256(REVIEW_V42)

    if sheet_hash == SHEET_UNSIGNED_SHA:
        raise SystemExit("签认件仍是空白版，拒绝落地。")
    if artifact_state(REVIEW_V42) != "signed":
        raise SystemExit("签认件未检测到实际签认（复核人/勾选），拒绝落地。")
    if draft.get("status") != "draft_pending_human_signature":
        raise SystemExit(f"draft v4.2 状态异常：{draft.get('status')}")
    remark = sheet_text.split("备注：", 1)[1].splitlines()[0].strip()

    signed = copy.deepcopy(draft)
    signed["status"] = "frozen_signed"
    history = list(signed["revision_history"])
    history[-1]["signed_by"] = SIGNED_BY
    history[-1]["status"] = "frozen_signed"
    signed["revision_history"] = history
    signed["signoff"] = {
        "signed_by": SIGNED_BY,
        "signed_on": SIGNED_ON,
        "statement": (
            "核准本契约 v4.2 作为 items-only 质量门的已签认度量基准；"
            "本轮唯一实质改动是把 threshold_source.authority_source 改钉门 28 的基准持有记录（v2），"
            "落实 U 对 P16 校验器拦下项的裁定 (a)。"
        ),
        "instrument": {"path": str(REVIEW_V42.relative_to(REPO_ROOT)), "sha256": sheet_hash},
        "scope_note": (
            "签认只定读路径、口径与度量口径；不代表 items-only 真实复验通过、不代表发布或语境完整。"
        ),
        "reviewer_remark": remark,
        "remark_note": (
            "备注为空 ⇒ 草案按**原样接受**（含『3 处 authority pin、阈值逐字不变』的机器 diff 结论）。"
            "这是对空备注的解释，不等同逐条确认。"
        ),
    }

    record: dict[str, Any] = {
        "schema_version": "items-contract-v42-signoff-record-1",
        "created_on": SIGNED_ON,
        "zero_call": True,
        "signed_by": SIGNED_BY,
        "signed_on": SIGNED_ON,
        "instrument": {
            "path": str(REVIEW_V42.relative_to(REPO_ROOT)),
            "sha256": sheet_hash,
            "superseded_unsigned_sha256": SHEET_UNSIGNED_SHA,
            "reviewer_remark": remark,
        },
        "signed_contract": {
            "path": "scoring-contract-v4.2.json",
            "schema_version": signed["schema_version"],
            "status": signed["status"],
            "supersedes": signed["supersedes"]["sha256"],
        },
        "ruling_carried": {
            "item": "P16 校验器 needs_ruling：契约权威门钉 v1 而 P13 已产生继任 v2",
            "chosen": "(a) 契约出新版本改钉 v2",
            "decided_on": SIGNED_ON,
            "consequence": "契约绑定链现为 v2 → v3 → v4 → v4.1 → v4.2；P03 以 v4.2 为准。",
        },
        "changed_leaves": {
            "count": 9,
            "unexpected": 0,
            "threshold_values_unchanged": True,
            "diff_artifact": str(
                (
                    EV / "57-contract-v42-draft-20261012/r0-zero-call/contract-v4.2-diff.json"
                ).relative_to(REPO_ROOT)
            ),
        },
        "supersession": {
            "superseded_by_v42": [
                {
                    "path": str(SIGNED_V41.relative_to(REPO_ROOT)),
                    "sha256": sha256(SIGNED_V41),
                    "note": "已签 v4.1：其内容被 v4.2 只增不删地继承（仅 3 处 authority pin 变更）；v4.1 字节不变。",
                }
            ]
        },
        "outstanding_after_signoff": [
            "P03 阈值单源落地：评分器改为读契约（OPEN-1=A 的兑现）——现在以 v4.2 为准",
            "P04/P05 口径归一化实现与回归",
            "gate v2 的 metric_basis（…-v4.1）现落后于契约 v4.2：是否推进属『契约↔门 相互追逐』问题，"
            "建议以『阈值数值恒等』为不变量、由校验器持续核查（见 56-…/README.md §三 的选项 b 精神）",
            "route a/b 边际裁定与缺口 1/2",
        ],
        "bytes_left_untouched": {
            str(SIGNED_V41.relative_to(REPO_ROOT)): sha256(SIGNED_V41),
            str(GATE_V1.relative_to(REPO_ROOT)): sha256(GATE_V1),
            str(GATE_V2.relative_to(REPO_ROOT)): sha256(GATE_V2),
        },
        "in_place_edits": 0,
        "note": "签认只签契约条款；不等于 items-only 真实复验通过，也不等于门 33 出分。",
    }

    print(
        json.dumps(
            {
                "status": signed["status"],
                "signed_by": SIGNED_BY,
                "instrument": sheet_hash,
                "supersedes": signed["supersedes"]["sha256"],
                "authority_pin": signed["threshold_source"]["authority_source"]["sha256"],
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    if args.no_write:
        return

    target = HERE / "scoring-contract-v4.2.json"
    if target.exists() and artifact_state(target) == "signed":
        raise SystemExit("拒绝写入：scoring-contract-v4.2.json 已含签认标记。")

    write_once(HERE / "scoring-contract-v4.2.json", signed, reason="契约 v4.2 签认落地")
    write_once(HERE / "signoff-record.json", record, reason="v4.2 签认落地记录")
    write_once(HERE / "README.md", render_readme(record, signed), reason="v4.2 签认落地说明")
    manifest = {
        "schema_version": "items-contract-v42-signed-manifest-1",
        "created_on": SIGNED_ON,
        "zero_call": True,
        "inputs": {
            str(DRAFT_V42.relative_to(REPO_ROOT)): sha256(DRAFT_V42),
            str(REVIEW_V42.relative_to(REPO_ROOT)): sheet_hash,
            str(SIGNED_V41.relative_to(REPO_ROOT)): sha256(SIGNED_V41),
            str(GATE_V2.relative_to(REPO_ROOT)): sha256(GATE_V2),
        },
        "outputs": {
            item.name: sha256(item)
            for item in sorted(HERE.iterdir())
            if item.is_file() and item.name != "MANIFEST.json"
        },
        "in_place_edits": 0,
    }
    write_once(HERE / "MANIFEST.json", manifest, reason="v4.2 签认落地清单")


def render_readme(record: dict[str, Any], signed: dict[str, Any]) -> str:
    lines = [
        "# 契约 v4.2 · 已签认版",
        "",
        f"- 签署人：**{record['signed_by']}**　日期：**{record['signed_on']}**",
        f"- 签署工具：`{record['instrument']['path']}` `{record['instrument']['sha256']}`",
        f"- 产物：`scoring-contract-v4.2.json`（`status = {signed['status']}`）",
        f"- 取代：已签 v4.1 `{signed['supersedes']['sha256']}`（字节不变，留存可追溯）",
        "",
        "## 本轮唯一实质改动",
        "",
        "- `threshold_source.authority_source` 由门 28 **冻结执行门（v1，`987772e9…`）**改钉"
        "**基准持有记录（v2，`8cc11bcc…`）**——落实 U 的裁定 (a)。",
        "- 机器 diff：`changed 9 / unexpected 0 / 阈值六项逐字不变`。",
        "",
        "## 签认之后仍未完成（不得读成已过门）",
        "",
    ]
    lines += [f"- {item}" for item in record["outstanding_after_signoff"]]
    lines += [
        "",
        f"> {record['note']}",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
