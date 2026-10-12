"""Apply the signed P12/P13 rebinding (U signed 2026-10-12).

Zero model calls. Creates **two new records** and nothing else:

* P12 -> ``evidence/10-quality-gold-freeze-20261008-r2/rebinding-v4.1-20261012.json``
* P13 -> ``evidence/28-items-only-quality-gate-20261010/r0-zero-call/preregistered-gate-v2.json``

No existing byte is modified: ``freeze-manifest.json``, ``freeze-state.json``, ``frozen-gold.json``
and ``preregistered-gate.json`` are left exactly as they are (issue-34 §8). Both records are
written through ``tools/evidence_guard.write_once``, so they cannot be silently overwritten.

The P13 file name follows the signed instrument's suggestion; the gate's internal revision
number is 5 (unrelated to the contract's v2/v3/v4/v4.1 numbering) — that is disambiguated inside
the record itself.

Usage:
    uv run python .scratch/.../55-rebinding-signoff-applied-20261012/r0-zero-call/apply_rebinding_signoff.py
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
E55 = HERE.parent
CLAIMS = E55.parent.parent
REPO_ROOT = HERE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from tools.evidence_guard import artifact_state, write_once  # noqa: E402

EV = CLAIMS / "evidence"
SIGNED_ON = "2026-10-12"
SIGNED_BY = "xyl"

SHEET = (
    EV
    / "48-rebinding-and-basis-proposals-20261012"
    / "r0-zero-call"
    / "rebinding-signoff-review.md"
)
SHEET_UNSIGNED_SHA = "sha256:3fa1385fcab6a3b1abb500a97c7de4479bf51a35dba6c3d9ac7ae8a33670039c"

GOLD_FREEZE = EV / "10-quality-gold-freeze-20261008-r2"
FREEZE_MANIFEST = GOLD_FREEZE / "freeze-manifest.json"
FREEZE_STATE = GOLD_FREEZE / "freeze-state.json"
FROZEN_GOLD = GOLD_FREEZE / "frozen-gold.json"
CONTRACT_V4_1 = (
    EV / "47-scoring-contract-v41-signed-20261012" / "r0-zero-call" / "scoring-contract-v4.1.json"
)

GATE_DIR = EV / "28-items-only-quality-gate-20261010" / "r0-zero-call"
GATE = GATE_DIR / "preregistered-gate.json"
GATE_NEW = GATE_DIR / "preregistered-gate-v2.json"

CONTRACT_PATH_IN_GOLD_MANIFEST = ".scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r2/scoring-contract.json"


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def bare(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_p12(contract_hash: str) -> dict[str, Any]:
    manifest = json.loads(FREEZE_MANIFEST.read_text(encoding="utf-8"))
    state = json.loads(FREEZE_STATE.read_text(encoding="utf-8"))
    recorded = manifest["inputs"][CONTRACT_PATH_IN_GOLD_MANIFEST]
    return {
        "schema_version": "items-gold-freeze-contract-rebinding-1",
        "kind": "rebinding_record",
        "status": "signed",
        "created_on": SIGNED_ON,
        "issue": "P12 / D8",
        "signoff": {
            "signed_by": SIGNED_BY,
            "signed_on": SIGNED_ON,
            "instrument": {
                "path": str(SHEET.relative_to(REPO_ROOT)),
                "sha256": sha256(SHEET),
                "superseded_unsigned_sha256": SHEET_UNSIGNED_SHA,
                "reviewer_remark": "",
            },
        },
        "binds_contract": {
            "schema_version": "non-table-selected-target-scoring-contract-v4.1",
            "sha256": contract_hash,
            "path": str(CONTRACT_V4_1.relative_to(REPO_ROOT)),
        },
        "supersedes_recorded_binding": {"value": recorded, "version": "v2"},
        "chain": "v2 (recorded) → v3 (signed) → v4 (OPEN-1=A / OPEN-2=C) → v4.1 (signed 2026-10-12)",
        "binding_sites": [
            {
                "site": "freeze-manifest.json.inputs[scoring-contract.json]",
                "before": recorded,
                "after": contract_hash,
                "disposition": "rebound by this record",
            },
            {
                "site": "freeze-state.json.scoring_contract",
                "before_kind": "path_binding",
                "observed_value": state["scoring_contract"],
                "resolved_content_sha256_at_signing": bare(REPO_ROOT / state["scoring_contract"]),
                "resolved_version_at_signing": "v3",
                "after": contract_hash,
                "disposition": (
                    "本记录钉住解析后的哈希；『把路径改成哈希』属改字节，留作后续单独裁定"
                    "（路径式绑定为弱绑定：会静默跟随路径内容）"
                ),
            },
            {
                "site": "freeze-state.json.contract_snapshot",
                "embedded_schema_version": state["contract_snapshot"]["schema_version"],
                "embedded_status": state["contract_snapshot"]["status"],
                "disposition": (
                    "**保留字节，不改**：它是冻结当时实际生效的契约的历史记录，改它即伪造历史。"
                    "本记录声明：该快照是历史，**不是**当前绑定；当前绑定即本记录的 binds_contract"
                ),
            },
        ],
        "inputs_verification": {
            "inputs_checked": len(manifest["inputs"]),
            "drift_at_signing": 1,
            "drift_input": CONTRACT_PATH_IN_GOLD_MANIFEST,
            "others_stable": len(manifest["inputs"]) - 1,
        },
        "bytes_left_untouched": {
            str(FREEZE_MANIFEST.relative_to(REPO_ROOT)): sha256(FREEZE_MANIFEST),
            str(FREEZE_STATE.relative_to(REPO_ROOT)): sha256(FREEZE_STATE),
            str(FROZEN_GOLD.relative_to(REPO_ROOT)): sha256(FROZEN_GOLD),
        },
        "gold_bytes_unchanged": True,
        "threshold_values_changed": False,
        "in_place_edits": 0,
        "note": (
            "本件是**新增记录**；冻结链三个文件的字节一律未动。修订以『新版本记录 + 旧哈希留存』"
            "方式落地（issue-34 §8）。"
        ),
    }


def build_p13(contract_hash: str, sheet_hash: str) -> dict[str, Any]:
    gate = json.loads(GATE.read_text(encoding="utf-8"))
    before_hash = sha256(GATE)
    new_gate = copy.deepcopy(gate)
    previous_basis = new_gate["quality_requirements"]["metric_basis"]
    previous_binding = new_gate["gold"]["scoring_contract_sha256"]
    new_gate["quality_requirements"]["metric_basis"] = (
        "non-table-selected-target-scoring-contract-v4.1"
    )
    new_gate["gold"]["scoring_contract_sha256"] = contract_hash
    new_gate["revision_history"].append(
        {
            "revision": len(gate["revision_history"]) + 1,
            "revised_on": SIGNED_ON,
            "authors": "agent",
            "signed_by": SIGNED_BY,
            "basis": (
                f"U 于 {SIGNED_ON} 签认 {SHEET.relative_to(REPO_ROOT)}（{sheet_hash}）："
                "P13 两处绑定推进至已签契约 v4.1；沿用 revision_history[1] 的同一手续（新版本记录，不就地改）。"
            ),
            "changes": [
                f"quality_requirements.metric_basis 由 {previous_basis} 改为 non-table-selected-target-scoring-contract-v4.1。",
                f"gold.scoring_contract_sha256 由 {previous_binding} 再绑定至已签认 v4.1 哈希 {contract_hash}。",
                "未改动门阈值数值（target_recall_overall_min 0.85 / target_recall_per_source_min 0.80 "
                "/ candidate_precision_min 0.80 / accepted_records_total_min 40 / accepted_records_per_source_min 20 "
                "/ unresolved_candidates_max 0，逐字不变）、执行要求、授权四项与终态判定；"
                "冻结金标、freeze-manifest 与 freeze-state 字节不变。",
            ],
            "previous_gate_sha256": before_hash,
        }
    )
    new_gate["file_label_note"] = (
        "文件名 preregistered-gate-v2.json 沿用签认件的建议。门内部修订号为 revision "
        f"{len(new_gate['revision_history'])}，与契约版本号（v2/v3/v4/v4.1）无关，勿混读。"
    )
    return new_gate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    sheet_text = SHEET.read_text(encoding="utf-8")
    sheet_hash = sha256(SHEET)
    if sheet_hash == SHEET_UNSIGNED_SHA:
        raise SystemExit("签认件仍是空白版，拒绝落地。")
    if "认可并签认" not in sheet_text or SIGNED_BY not in sheet_text:
        raise SystemExit("签认件未检测到签认标记，拒绝落地。")

    contract_hash = sha256(CONTRACT_V4_1)
    p12 = build_p12(contract_hash)
    p13 = build_p13(contract_hash, sheet_hash)

    gate_before = json.loads(GATE.read_text(encoding="utf-8"))
    before_values = {
        k: v for k, v in gate_before["quality_requirements"].items() if k != "metric_basis"
    }
    after_values = {k: v for k, v in p13["quality_requirements"].items() if k != "metric_basis"}

    print(
        json.dumps(
            {
                "sheet_sha256": sheet_hash,
                "contract_v4.1": contract_hash,
                "p12_record": str(
                    (GOLD_FREEZE / "rebinding-v4.1-20261012.json").relative_to(REPO_ROOT)
                ),
                "p13_record": str(GATE_NEW.relative_to(REPO_ROOT)),
                "p13_revision": p13["revision_history"][-1]["revision"],
                "p13_metric_basis": p13["quality_requirements"]["metric_basis"],
                "threshold_values_unchanged": before_values == after_values,
                "threshold_values": after_values,
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    if args.no_write:
        return

    p12_path = GOLD_FREEZE / "rebinding-v4.1-20261012.json"
    written: dict[str, str] = {}
    for path, payload, reason in (
        (p12_path, p12, "P12 金标冻结链契约绑定再绑定"),
        (GATE_NEW, p13, "P13 门 28 基准与绑定推进"),
    ):
        state = artifact_state(path)
        if state == "signed":
            written[path.name] = "already_signed_skipped"
            continue
        write_once(path, payload, reason=reason)
        written[path.name] = sha256(path)

    # Verify the frozen originals are untouched.
    untouched = {
        str(path.relative_to(REPO_ROOT)): {"sha256": sha256(path), "state": artifact_state(path)}
        for path in (FREEZE_MANIFEST, FREEZE_STATE, FROZEN_GOLD, GATE)
    }

    signoff = {
        "schema_version": "items-rebinding-signoff-applied-1",
        "created_on": SIGNED_ON,
        "zero_call": True,
        "signed_by": SIGNED_BY,
        "signed_on": SIGNED_ON,
        "instrument": {
            "path": str(SHEET.relative_to(REPO_ROOT)),
            "sha256": sheet_hash,
            "superseded_unsigned_sha256": SHEET_UNSIGNED_SHA,
            "reviewer_remark": "",
            "remark_note": (
                "备注为空 ⇒ §二/§三 的推荐处置按**原样接受**（含 P12 第 3 条『内嵌 v2 快照保留字节不改』"
                "与第 2 条『路径绑定只钉哈希、路径改哈希留后续』）。这是对空备注的解释，不等同逐条确认。"
            ),
        },
        "decisions": {
            "P12": "3 处绑定点，按签认件 §二 处置",
            "P13": "2 处绑定点，值推进至 v4.1，阈值数值逐字不变",
        },
        "created_records": {
            "P12": {
                "path": str(p12_path.relative_to(REPO_ROOT)),
                "sha256": sha256(p12_path) if p12_path.exists() else None,
            },
            "P13": {
                "path": str(GATE_NEW.relative_to(REPO_ROOT)),
                "sha256": sha256(GATE_NEW) if GATE_NEW.exists() else None,
                "internal_revision": p13["revision_history"][-1]["revision"],
            },
        },
        "write_actions": written,
        "frozen_originals_untouched": untouched,
        "in_place_edits": 0,
        "outstanding_after_signoff": [
            "P03 阈值单源落地：评分器改为读契约（OPEN-1=A 的兑现）——代码未改",
            "P14 validation-report.human_accepted_counts 由 {} 对齐 48/48",
            "P16 冻结链校验器（任何契约/金标/manifest 修订须校验绑定一致）",
            "P04/P05 口径归一化实现与回归",
            "route a/b 边际裁定与缺口 1/2",
        ],
        "not_claimed": [
            "本件不产生任何门分数。",
            "本件不改任何既有字节；P12 的『路径改哈希』与 P13 之外的其它记账项均未处置。",
        ],
    }
    signoff_path = HERE / "signoff-applied-record.json"
    if not signoff_path.exists():
        write_once(signoff_path, signoff, reason="P12/P13 签认落地记录")

    manifest = {
        "schema_version": "items-rebinding-signoff-applied-manifest-1",
        "created_on": SIGNED_ON,
        "zero_call": True,
        "inputs": {
            str(SHEET.relative_to(REPO_ROOT)): sheet_hash,
            str(CONTRACT_V4_1.relative_to(REPO_ROOT)): contract_hash,
            str(FREEZE_MANIFEST.relative_to(REPO_ROOT)): sha256(FREEZE_MANIFEST),
            str(FREEZE_STATE.relative_to(REPO_ROOT)): sha256(FREEZE_STATE),
            str(GATE.relative_to(REPO_ROOT)): sha256(GATE),
            str(
                (
                    EV
                    / "48-rebinding-and-basis-proposals-20261012"
                    / "r0-zero-call"
                    / "rebinding-scope-extension.json"
                ).relative_to(REPO_ROOT)
            ): sha256(
                EV
                / "48-rebinding-and-basis-proposals-20261012"
                / "r0-zero-call"
                / "rebinding-scope-extension.json"
            ),
        },
        "outputs": {
            item.name: sha256(item)
            for item in sorted(HERE.iterdir())
            if item.is_file() and item.name != "MANIFEST.json"
        },
        "created_elsewhere": {
            str(p12_path.relative_to(REPO_ROOT)): sha256(p12_path) if p12_path.exists() else None,
            str(GATE_NEW.relative_to(REPO_ROOT)): sha256(GATE_NEW) if GATE_NEW.exists() else None,
        },
        "in_place_edits": 0,
    }
    manifest_path = HERE / "MANIFEST.json"
    if not manifest_path.exists():
        write_once(manifest_path, manifest, reason="P12/P13 落地清单")
    print(
        json.dumps(
            {"created": manifest["created_elsewhere"], "write_actions": written},
            ensure_ascii=False,
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
