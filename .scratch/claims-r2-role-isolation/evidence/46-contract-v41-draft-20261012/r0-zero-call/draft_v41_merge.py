"""P10: merge the parallel v4 proposal's 18 unique leaves into the signed v4 and emit v4.1.

Zero call. Base = the SIGNED v4 (`43-…/scoring-contract-v4.json`); donor = the parallel proposal
(`41-items-chain-accounting-…/scoring-contract-v4.proposed.json`, never signed).

Merge rule (declared, machine-applied):
  * add-only: a donor leaf is written **only if the base lacks that path**;
  * if the path exists with a different value, the base value is KEPT and the conflict is recorded
    with an explicit declared resolution (never silently overwritten);
  * v4.1 is a new draft: status -> draft_pending_human_signature, signoff cleared.

The signed v4, the signed review sheet and the donor are never modified.

Usage:
    uv run python .scratch/claims-r2-role-isolation/evidence/46-contract-v41-draft-20261012/r0-zero-call/draft_v41_merge.py
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
E46 = HERE.parent
CLAIMS = E46.parent.parent
REPO_ROOT = HERE.parents[4]
E36_R0 = CLAIMS / "evidence" / "36-l9-redo-and-baseline-20261011" / "r0-zero-call"
for path in (str(REPO_ROOT), str(E36_R0)):
    if path not in sys.path:
        sys.path.insert(0, path)

from l9_redo import digest, read_json  # noqa: E402

EV = CLAIMS / "evidence"
SIGNED_V4 = EV / "43-scoring-contract-v4-signed-20261012" / "r0-zero-call" / "scoring-contract-v4.json"
DONOR = (
    EV
    / "41-items-chain-accounting-20261012"
    / "r3-signoff-apply"
    / "scoring-contract-v4.proposed.json"
)
PREREG = HERE / "preregistered-v41-merge.json"

ROOT_MAP = {
    "items_field_carrier_read_path": "read_path",
    "threshold_single_source": "threshold_source",
}

# Declared resolutions for the two places where the donor overlaps the signed base.
DECLARED_RESOLUTIONS: dict[str, dict[str, Any]] = {
    "threshold_source.required_alignment": {
        "action": "resolve_by_signed_decision",
        "value": "OPEN-1 = A（2026-10-12 已签认）：以门 28 为单一口径，评分器改为读契约",
        "why": "donor 记为 PENDING_SIGNOFF，但该分叉已由 U 于 2026-10-12 签认（OPEN-1=A）；保留 pending 会与已签状态矛盾。",
    },
    "threshold_source.pending_signoff_detail": {
        "action": "rename_to_decision_history",
        "value_key": "threshold_source.decision_history",
        "why": "该叶子描述分叉本身，仍有追溯价值；但名称含 pending，故改名为 decision_history 并更新说明，避免与已签状态冲突。",
    },
}

# Donor subtrees that must be moved as a whole (prefix match), not leaf-by-leaf.
RENAME_SUBTREE: dict[str, str] = {
    "threshold_source.pending_signoff_detail": "threshold_source.decision_history",
}

SIGNATURE_MARKERS = ("☑ 认可并签认", "☑ 认可本口径", "复核人：xyl", "复核人：　xyl")


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


def set_path(target: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    node = target
    for part in parts[:-1]:
        if not isinstance(node.get(part), dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value


def get_path(target: dict[str, Any], path: str) -> Any:
    node: Any = target
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def deep_diff(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--force", action="store_true", help="允许覆盖已签认产物（默认拒绝）")
    args = parser.parse_args()

    prereg = read_json(PREREG)
    base = read_json(SIGNED_V4)
    donor = read_json(DONOR)
    if base.get("status") != "frozen_signed":
        raise SystemExit("base is not the signed v4: %s" % base.get("status"))

    merged = copy.deepcopy(base)
    base_flat = flatten(base)
    merged_flat = flatten(merged)

    added: list[str] = []
    conflicts: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []

    for donor_root, base_root in ROOT_MAP.items():
        donor_section = donor.get(donor_root)
        if donor_section is None:
            continue
        donor_flat = flatten(donor_section, base_root)
        for path, value in donor_flat.items():
            if any(path == key or path.startswith(key + ".") for key in RENAME_SUBTREE):
                continue  # handled as a whole subtree below
            if path in DECLARED_RESOLUTIONS:
                rule = DECLARED_RESOLUTIONS[path]
                if rule["action"] == "resolve_by_signed_decision":
                    set_path(merged, path, rule["value"])
                    resolved.append({"path": path, "action": rule["action"], "why": rule["why"]})
                else:
                    target = rule["value_key"]
                    set_path(merged, target, value)
                    resolved.append(
                        {
                            "path": path,
                            "action": rule["action"],
                            "moved_to": target,
                            "why": rule["why"],
                        }
                    )
                continue
            if path not in base_flat:
                set_path(merged, path, value)
                added.append(path)
            elif base_flat[path] != value:
                conflicts.append({"path": path, "kept": base_flat[path], "donor": value})

    # Whole-subtree rename: the donor's pending-named node becomes decision_history, with its
    # "why_not_chosen" updated because the fork has since been signed (OPEN-1 = A).
    reverse_map = {base_root: donor_root for donor_root, base_root in ROOT_MAP.items()}
    for src, dst in RENAME_SUBTREE.items():
        # `src` is in the merged namespace; translate the root back to the donor's own root.
        root, _, rest = src.partition(".")
        donor_src = f"{reverse_map.get(root, root)}.{rest}" if rest else reverse_map.get(root, root)
        subtree = get_path(donor, donor_src)
        if subtree is None:
            continue
        subtree = copy.deepcopy(subtree)
        if isinstance(subtree, dict) and "why_not_chosen" in subtree:
            subtree["why_not_chosen"] = (
                "决策前状态（保留供追溯）：当时 U 的签认为文件级「准予继续」，未勾选该分叉。"
                "该分叉已于 2026-10-12 由 OPEN-1 = A 裁定，见同节 required_alignment。"
            )
        if isinstance(subtree, dict):
            subtree["renamed_from"] = f"donor:{src}"
        set_path(merged, dst, subtree)
        resolved.append(
            {
                "path": src,
                "action": "rename_subtree",
                "moved_to": dst,
                "why": DECLARED_RESOLUTIONS[src]["why"],
            }
        )

    # Reconciliation note for the one place where donor and base describe the same rule
    # with different mechanics (add-only, so the base wording is preserved).
    alignment_note = (
        "与 caliber_rules 并用，不冲突：`absent_required_fields` 规定候选未携带时在 "
        "`canonical_observed_fields` 中**显式记为 absent**（不得留空、不得猜测），"
        "`caliber_rules` 规定 attribution/speaker_ref **移出匹配基**。两者叠加的正确读法是："
        "先按 caliber_rules 决定哪些字段参与匹配，再对不参与的字段按本条显式记 absent 以备审。"
    )
    set_path(
        merged,
        "read_path.absent_required_fields.alignment_with_caliber_rules",
        alignment_note,
    )
    added.append("read_path.absent_required_fields.alignment_with_caliber_rules")

    # Version / status bookkeeping
    merged["schema_version"] = "non-table-selected-target-scoring-contract-v4.1"
    merged["status"] = "draft_pending_human_signature"
    merged["supersedes"] = {
        "schema_version": base["schema_version"],
        "status_at_supersede": base["status"],
        "sha256": digest(SIGNED_V4),
        "note": (
            "v4.1 以已签 v4 为基，只增不删地把并行草案的独有叶子并入；"
            "v4.1 未签认前不生效，v4 字节不变、哈希留存可追溯。"
        ),
    }
    merged["revision_history"] = list(base["revision_history"]) + [
        {
            "revision": "v4.1",
            "status": "draft_pending_human_signature",
            "created_on": "2026-10-12",
            "authors": "agent",
            "signed_by": None,
            "basis": "P10（replan）：以已签 v4 为基，并入并行草案 "
            f"`{str(DONOR.relative_to(REPO_ROOT))}`（`{digest(DONOR)}`）的独有叶子。",
            "changes": [
                f"新增 {len(added)} 条叶子（含 3 条核心读路径条款：carrier_mapping.rule、"
                "absent_required_fields.rule、equivalence_judgement.scorer_contract）",
                f"按已签结论落地 {len(resolved)} 条（threshold_source.required_alignment 由 pending 改为已定）",
                "status 退回 draft_pending_human_signature（v4.1 未签认）",
                "未改动已签 v4 的任何既有叶子（只增不删）",
            ],
        }
    ]
    merged["signoff"] = {
        "signed_by": "",
        "signed_on": "",
        "statement": "【待签认】v4.1 = 已签 v4 + 并行草案独有叶子；签认前不生效。",
        "scope_note": (
            "签认只定读路径、口径与度量口径；不代表 items-only 真实复验通过、不代表发布或语境完整。"
            "material_relations 按 OPEN-2=C 本轮不纳入评分。"
        ),
        # Kept (not dropped) so the merge stays add-only: the pending instrument is this
        # directory's review sheet; the previous, signed instrument stays reachable via supersedes.
        "instrument": {
            "path": str((HERE / "contract-v4.1-review.md").relative_to(REPO_ROOT)),
            "sha256": "pending_signature",
            "note": (
                "签认后回填本文件实际哈希。v4 的签署工具（已签 review 件 "
                "`753532e8…`）见 supersedes 指向的已签 v4 的 signoff.instrument。"
            ),
        },
    }

    diff = deep_diff(base, merged)
    removed = [item["path"] for item in diff if item["op"] == "remove"]
    changed = [item["path"] for item in diff if item["op"] == "change"]
    consistency = {
        "base_removals": removed,
        "base_leaf_changes": [
            path
            for path in changed
            if path.split(".", 1)[0] not in ("status", "schema_version", "supersedes", "revision_history", "signoff")
        ],
        "status_is_draft": merged["status"] == "draft_pending_human_signature",
        "no_signer_filled": merged["signoff"]["signed_by"] == ""
        and merged["revision_history"][-1]["signed_by"] is None,
        "donor_has_no_signoff": not (donor.get("signoff") or {}).get("signed_by"),
        "add_only": not removed,
    }

    reconciliation = {
        "schema_version": "items-contract-v41-merge-reconciliation-1",
        "created_on": "2026-10-12",
        "base": {"path": str(SIGNED_V4.relative_to(REPO_ROOT)), "sha256": digest(SIGNED_V4)},
        "donor": {
            "path": str(DONOR.relative_to(REPO_ROOT)),
            "sha256": digest(DONOR),
            "status_in_file": donor.get("status"),
            "note": "donor 从未签认（signoff.signed_by 为空）；并入后由 v4.1 一并取代。",
        },
        "added_leaf_paths": sorted(added),
        "resolved_leaf_paths": resolved,
        "conflicts_kept_base_value": conflicts,
        "consistency": consistency,
        "open_for_reviewer": [
            "threshold_source.decision_history：由 donor 的 pending_signoff_detail 改名而来，"
            "其 why_not_chosen 描述的是决策前的状态，已签 OPEN-1=A；请确认该历史条目保留与否。",
            "read_path.absent_required_fields.alignment_with_caliber_rules：由本脚本撰写，"
            "用于调和 donor「记 absent」与 base「移出匹配基」两种表述，属可质疑项。",
        ],
    }

    print(
        json.dumps(
            {
                "added": len(added),
                "resolved": len(resolved),
                "conflicts": len(conflicts),
                "removals": len(removed),
                "status": merged["status"],
                "version": merged["schema_version"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.no_write:
        return

    review_path = HERE / "contract-v4.1-review.md"
    if review_path.exists() and not args.force:
        existing = review_path.read_text(encoding="utf-8")
        if any(marker in existing for marker in SIGNATURE_MARKERS):
            raise SystemExit("拒绝写入：contract-v4.1-review.md 已含签认标记。")

    (HERE / "proposed-scoring-contract-v4.1.json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "contract-v4.1-diff.json").write_text(
        json.dumps(
            {
                "schema_version": "items-contract-v41-diff-1",
                "base_sha256": digest(SIGNED_V4),
                "entries": diff,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (HERE / "contract-v4.1-diff.md").write_text(render_diff(diff), encoding="utf-8")
    (HERE / "merge-reconciliation.json").write_text(
        json.dumps(reconciliation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    review_path.write_text(render_review(reconciliation, merged), encoding="utf-8")
    manifest = {
        "schema_version": "items-contract-v41-draft-manifest-1",
        "created_on": "2026-10-12",
        "inputs": {
            str(PREREG.relative_to(REPO_ROOT)): digest(PREREG),
            str(SIGNED_V4.relative_to(REPO_ROOT)): digest(SIGNED_V4),
            str(DONOR.relative_to(REPO_ROOT)): digest(DONOR),
        },
        "outputs": {
            name: digest(HERE / name)
            for name in (
                "preregistered-v41-merge.json",
                "proposed-scoring-contract-v4.1.json",
                "contract-v4.1-diff.json",
                "contract-v4.1-diff.md",
                "merge-reconciliation.json",
                "contract-v4.1-review.md",
                "draft_v41_merge.py",
            )
        },
        "signed_v4_unchanged": True,
    }
    (HERE / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if get_path(merged, "threshold_source.required_alignment") is None:
        raise SystemExit("merge sanity failed")


def render_diff(diff: list[dict[str, Any]]) -> str:
    lines = [
        "# 契约 v4 → v4.1 差异（机器计算）",
        "",
        f"- 差异条目：{len(diff)}",
        "",
        "| JSON 路径 | 操作 | 旧值 | 新值 |",
        "|---|---|---|---|",
    ]

    def brief(value: Any, limit: int = 140) -> str:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        text = str(text).replace("|", "\\|").replace("\n", " ")
        return text if len(text) <= limit else text[:limit] + "…"

    for item in diff:
        lines.append(
            "| `{0}` | {1} | {2} | {3} |".format(
                item["path"], item["op"], brief(item.get("before", "—")), brief(item.get("after", "—"))
            )
        )
    lines += ["", "> 由脚本递归 diff 计算，非手写。"]
    return "\n".join(lines) + "\n"


def render_review(reconciliation: dict[str, Any], merged: dict[str, Any]) -> str:
    lines = [
        "# 契约 v4.1 审阅件（合并草案）",
        "",
        "> **草案，未签认**；签认前不生效。已签 v4 与 donor 草案字节均未改动。",
        "",
        f"- 基：已签 v4 `{reconciliation['base']['sha256']}`",
        f"- 供方：并行草案 `{reconciliation['donor']['sha256']}`"
        f"（`{reconciliation['donor']['status_in_file']}`，**从未签认**）",
        f"- 结果：`status = {merged['status']}`；只增不删（删项 {len(reconciliation['consistency']['base_removals'])}）",
        "",
        "## 一、并入了什么",
        "",
        f"共新增 **{len(reconciliation['added_leaf_paths'])}** 条叶子；其中 3 条是核心读路径条款：",
        "",
        "| 核心条款 | 作用 |",
        "|---|---|",
        "| `read_path.carrier_mapping.rule` | 只允许确定性载体映射（候选 `text`→契约 `proposition`），**只改字段名**，不生成/改写/摘要语义文本 |",
        "| `read_path.absent_required_fields.rule` | 缺字段记 `absent`，**不得因缺字段直接判不匹配**，也不得补造 |",
        "| `read_path.equivalence_judgement.scorer_contract` | **评分器不得以身份相等为匹配前提**，只消费裁定完成的映射 |",
        "",
        "完整清单见 `merge-reconciliation.json` 的 `added_leaf_paths`。",
        "",
        "## 二、按已签结论落地的条目",
        "",
        "| 路径 | 处置 | 理由 |",
        "|---|---|---|",
    ]
    for item in reconciliation["resolved_leaf_paths"]:
        lines.append(f"| `{item['path']}` | {item['action']} | {item['why']} |")
    lines += [
        "",
        "## 三、需要你确认的两处（可质疑项）",
        "",
    ]
    lines += [f"- {item}" for item in reconciliation["open_for_reviewer"]]
    lines += [
        "",
        f"- 冲突（基值保留、未覆盖）：{len(reconciliation['conflicts_kept_base_value'])} 条",
        "",
        "## 四、签认栏（草案）",
        "",
        "- 复核人：　　　　日期：",
        "- 结论：☐ 认可并签认 v4.1　☐ 退回修改",
        "- 备注：",
        "",
        "> 签认 v4.1 后：并行草案标 `superseded_by`；契约绑定再绑定（P12）以 v4.1 哈希为准；"
        "门 28 `metric_basis` 随之推进（P13）。",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
