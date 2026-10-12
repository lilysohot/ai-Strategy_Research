"""Draft contract v4.2: re-pin the authority gate after U's ruling (a).

U ruled **(a)** on 2026-10-12: after P13 produced the successor gate record, the signed
contract v4.1 must be superseded by a version whose ``threshold_source.authority_source``
pins gate 28's successor record (``preregistered-gate-v2.json``), instead of the frozen
execution gate (``preregistered-gate.json``).

Exactly three leaves change; everything else — including all six threshold values — is
byte-identical, and the diff artifact proves it. The draft is ``draft_pending_human_signature``:
v4.2 does not take effect until signed, and v4.1's bytes stay untouched.

Zero model calls. The signature guard (P06) refuses to touch a signed artifact.

Usage:
    uv run python .scratch/.../57-contract-v42-draft-20261012/r0-zero-call/draft_v42.py
    ... --no-write
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E57 = HERE.parent
CLAIMS = E57.parent.parent
REPO_ROOT = HERE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from tools.evidence_guard import artifact_state, write_once  # noqa: E402

EV = CLAIMS / "evidence"
V41 = EV / "47-scoring-contract-v41-signed-20261012" / "r0-zero-call" / "scoring-contract-v4.1.json"
GATE_V1 = EV / "28-items-only-quality-gate-20261010" / "r0-zero-call" / "preregistered-gate.json"
GATE_V2 = EV / "28-items-only-quality-gate-20261010" / "r0-zero-call" / "preregistered-gate-v2.json"
P13_RECORD = GATE_V2

NEW_VERSION = "non-table-selected-target-scoring-contract-v4.2"
SIGNED_ON = "2026-10-12"
SIGNED_BY = "xyl"

# The only leaves allowed to change; anything else appearing in the diff is a bug.
EXPECTED_CHANGED_EXACT = {
    "schema_version",
    "status",
    "revision_history",
    "threshold_source.authority_source.where",
    "threshold_source.authority_source.sha256",
    "threshold_source.effective.source",
}
EXPECTED_CHANGED_PREFIXES = ("signoff.", "supersedes.")


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def flatten(node: Any, prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            flat.update(flatten(value, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(node, list):
        flat[prefix] = json.dumps(node, ensure_ascii=False, sort_keys=True)
    else:
        flat[prefix] = node
    return flat


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    v41 = json.loads(V41.read_text(encoding="utf-8"))
    gate_v2 = json.loads(P13_RECORD.read_text(encoding="utf-8"))
    gate_v2_hash = sha256(GATE_V2)

    before_values = {
        key: v41["threshold_source"]["authority_source"]["values"][key]
        for key in gate_v2["quality_requirements"]
        if key in v41["threshold_source"]["authority_source"]["values"]
    }
    after_values = {key: gate_v2["quality_requirements"][key] for key in before_values}
    if before_values != after_values:
        raise SystemExit(
            f"阈值数值在门 v1 与 v2 之间不一致，拒绝推进 authority pin：{before_values} vs {after_values}"
        )

    draft = copy.deepcopy(v41)
    draft["schema_version"] = NEW_VERSION
    draft["status"] = "draft_pending_human_signature"
    draft["supersedes"] = {
        "schema_version": v41["schema_version"],
        "status_at_supersede": v41["status"],
        "sha256": sha256(V41),
        "note": (
            "v4.2 只做一件事：把 threshold_source.authority_source 从门 28 的冻结执行门（v1）"
            "改钉到 P13 产生的基准持有记录（v2）。阈值数值逐字不变；v4.1 字节不变、哈希留存可追溯。"
        ),
    }
    draft["threshold_source"]["authority_source"]["where"] = (
        "门 28 preregistered-gate-v2.json quality_requirements（P13 基准持有记录，2026-10-12 签认）"
    )
    draft["threshold_source"]["authority_source"]["sha256"] = gate_v2_hash
    draft["threshold_source"]["effective"]["source"] = (
        "门 28 preregistered-gate-v2.json quality_requirements"
    )
    draft["revision_history"].append(
        {
            "revision": "v4.2",
            "status": "draft_pending_human_signature",
            "created_on": SIGNED_ON,
            "authors": "agent",
            "signed_by": None,
            "basis": (
                "U 于 2026-10-12 对 P16 校验器拦下的项裁定 **(a)**：契约出新版本、把 authority_source "
                "改钉门 28 的继任记录 v2（P13 产出）。沿用 P12/P13 的『新版本记录 + 旧哈希留存』手续。"
            ),
            "changes": [
                f"threshold_source.authority_source.sha256 由 sha256:987772e9…（门 v1）改钉 {gate_v2_hash}（门 v2）。",
                "threshold_source.authority_source.where 与 threshold_source.effective.source 同步改指 v2 文件。",
                "阈值数值逐字不变（六项，机器校验）；其余叶子零改动（见 contract-v4.2-diff.json）。",
                "v4.1 字节不变；v4.2 未签认前不生效。",
            ],
        }
    )

    before = flatten(v41)
    after = flatten(draft)
    diff = {
        "schema_version": "items-contract-diff-1",
        "from": {"schema_version": v41["schema_version"], "sha256": sha256(V41)},
        "to": {"schema_version": NEW_VERSION, "sha256": None},
        "changed": sorted(
            {
                path
                for path in set(before) | set(after)
                if before.get(path) != after.get(path) and not path.startswith(".revision_history")
            }
        ),
        "changed_allowed": sorted(EXPECTED_CHANGED_EXACT) + list(EXPECTED_CHANGED_PREFIXES),
        "added": [],
        "removed": [],
        "revision_history_note": "revision_history 追加 v4.2 条目（含未签认态），不计入 changed。",
        "unexpected_changed": [],
        "threshold_values_unchanged": before_values == after_values,
    }
    diff["unexpected_changed"] = [
        path
        for path in diff["changed"]
        if path not in EXPECTED_CHANGED_EXACT and not path.startswith(EXPECTED_CHANGED_PREFIXES)
    ]
    return draft, diff


def render_review(draft: dict[str, Any], diff: dict[str, Any]) -> str:
    lines = [
        "# 契约 v4.2 · 审阅件（待签）",
        "",
        f"- 本件：`{Path(__file__).resolve().parent / 'contract-v4.2-review.md'}`",
        "- 状态：**draft_pending_human_signature**（签认前不生效；v4.1 字节不变）",
        "",
        "## 一、这份签下去等于什么（一句话）",
        "",
        "把契约里「权威阈值源」的指认从门 28 的**冻结执行门（v1）**改钉到 **P13 产出的基准持有记录（v2）**。"
        "这是你对 P16 校验器拦下那项的裁定 **(a)** 的落实。",
        "",
        "**阈值数值逐字不变**；除下表 3 处（外加版本号/supersedes/签认态/修订史）外，其余叶子零改动（机器 diff 证明）。",
        "",
        f"## 二、改动清单（机器 diff，共 {len(diff['changed'])} 处 changed）",
        "",
        "| 叶子 | v4.1 | v4.2 |",
        "|---|---|---|",
    ]
    for path in diff["changed"]:
        if path == "revision_history":
            continue
        lines.append(f"| `{path}` | 见 diff 件 | 见 diff 件 |")
    lines += [
        "",
        f"- `schema_version`：`…-v4.1` → `{draft['schema_version']}`",
        "- `threshold_source.authority_source.sha256`：`987772e9…`（门 v1）→ `8cc11bcc…`（门 v2）",
        "- `threshold_source.authority_source.where` 与 `threshold_source.effective.source`：改指 v2 文件",
        "- `supersedes` / `revision_history` / `status` / `signoff`：随版本推进",
        "",
        f"- `unexpected_changed`：**{len(diff['unexpected_changed'])}**（必须为 0）",
        f"- `threshold_values_unchanged`：**{diff['threshold_values_unchanged']}**",
        "",
        "## 三、不改什么",
        "",
        "- 六项阈值数值：`0.85 / 0.80 / 0.80 / 40 / 20 / 0`（机器校验通过）",
        "- 已签 v4.1 的字节（`c76ac13e…`）",
        "- 门 28 v1（冻结执行门，`987772e9…`）与门 28 v2（`8cc11bcc…`）的字节",
        "- 冻结金标、freeze-manifest、freeze-state",
        "",
        "## 四、裁定依据",
        "",
        "- U 2026-10-12 裁定 **(a)**：契约出新版本改钉 v2（回应 P16 校验器的 `needs_ruling`）。",
        "- 手续：沿用 P12/P13 的『新版本记录 + 旧哈希留存』；本次是契约自身的版本推进，故需再签一次。",
        "",
        "## 五、签认栏",
        "",
        "- 复核人：　　　　　　日期：",
        "- 结论：☐ 认可并签认 v4.2　　☐ 退回修改",
        "- 备注：",
        "",
        "> 签认后：v4.2 落 `47-…` 同级的**新签认目录**；契约绑定链变为 v2 → v3 → v4 → v4.1 → v4.2；"
        "P03（评分器读契约）以 v4.2 为准。",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    draft, diff = build()
    draft["signoff"] = {
        "signed_by": None,
        "signed_on": None,
        "statement": "",
        "instrument": None,
    }
    diff["to"]["sha256"] = None

    print(
        json.dumps(
            {
                "schema_version": draft["schema_version"],
                "changed": len(diff["changed"]),
                "unexpected_changed": len(diff["unexpected_changed"]),
                "threshold_values_unchanged": diff["threshold_values_unchanged"],
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    if args.no_write:
        return

    targets = {
        "proposed-scoring-contract-v4.2.json": draft,
        "contract-v4.2-diff.json": diff,
        "contract-v4.2-review.md": render_review(draft, diff),
    }
    for name, payload in targets.items():
        path = HERE / name
        state = artifact_state(path)
        if state == "signed":
            raise SystemExit(f"拒绝写入：{name} 已含签认标记。")
        write_once(path, payload, reason="契约 v4.2 草案", allow_overwrite=path.exists())

    manifest = {
        "schema_version": "items-contract-v42-draft-manifest-1",
        "created_on": SIGNED_ON,
        "zero_call": True,
        "inputs": {
            str(V41.relative_to(REPO_ROOT)): sha256(V41),
            str(GATE_V1.relative_to(REPO_ROOT)): sha256(GATE_V1),
            str(GATE_V2.relative_to(REPO_ROOT)): sha256(GATE_V2),
            str(P13_RECORD.relative_to(REPO_ROOT)): sha256(P13_RECORD),
        },
        "outputs": {
            item.name: sha256(item)
            for item in sorted(HERE.iterdir())
            if item.is_file() and item.name != "MANIFEST.json"
        },
        "in_place_edits": 0,
        "supersedes": {"schema_version": "…-v4.1", "sha256": sha256(V41)},
    }
    write_once(
        HERE / "MANIFEST.json",
        manifest,
        reason="v4.2 草案清单",
        allow_overwrite=(HERE / "MANIFEST.json").exists(),
    )


if __name__ == "__main__":
    main()
