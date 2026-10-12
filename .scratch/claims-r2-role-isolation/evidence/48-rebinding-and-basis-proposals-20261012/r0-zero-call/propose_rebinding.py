"""P12/P13: propose the two bookkeeping fixes that follow from signing contract v4.1.

Zero call, read-only. Both are **proposals for a new version record** — nothing is edited in place
(issue-34 §8: 不就地修改门 28/32/33 既有产物与冻结链，修订以新版本记录、旧哈希留存).

  P12  gold freeze-manifest records the v2 contract digest; the signed contract is now v4.1.
  P13  gate 28's metric_basis still points at v3; the signed contract is now v4.1.

Usage:
    uv run python .scratch/claims-r2-role-isolation/evidence/48-rebinding-and-basis-proposals-20261012/r0-zero-call/propose_rebinding.py
    ... --no-write
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E48 = HERE.parent
CLAIMS = E48.parent.parent
REPO_ROOT = HERE.parents[4]
E36_R0 = CLAIMS / "evidence" / "36-l9-redo-and-baseline-20261011" / "r0-zero-call"
for path in (str(REPO_ROOT), str(E36_R0)):
    if path not in sys.path:
        sys.path.insert(0, path)

from l9_redo import digest, read_json  # noqa: E402


def bare(path: Path) -> str:
    """Freeze-chain manifests record bare hexdigests (no `sha256:` prefix)."""
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()

EV = CLAIMS / "evidence"
SIGNED_V41 = EV / "47-scoring-contract-v41-signed-20261012" / "r0-zero-call" / "scoring-contract-v4.1.json"
V41_SIGNOFF = EV / "47-scoring-contract-v41-signed-20261012" / "r0-zero-call" / "signoff-record.json"
GOLD_MANIFEST = EV / "10-quality-gold-freeze-20261008-r2" / "freeze-manifest.json"
GOLD_STATE = EV / "10-quality-gold-freeze-20261008-r2" / "freeze-state.json"
VALIDATION = EV / "10-quality-gold-expansion-20261008-r2" / "validation-report.json"
GATE28 = EV / "28-items-only-quality-gate-20261010" / "r0-zero-call" / "preregistered-gate.json"
CONTRACT_V3 = EV / "10-quality-gold-expansion-20261008-r2" / "scoring-contract.json"
GATE32_MANIFEST = EV / "32-items-v6-reasoning-refreeze-20261011" / "r0-zero-call" / "freeze-manifest.json"
DONOR_REBIND = (
    EV / "41-items-chain-accounting-20261012" / "r3-signoff-apply" / "freeze-rebinding-record.json"
)

CONTRACT_KEY_IN_GOLD = (
    ".scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r2/scoring-contract.json"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    signed = read_json(SIGNED_V41)
    signoff = read_json(V41_SIGNOFF)
    gold_manifest = read_json(GOLD_MANIFEST)
    gold_state = read_json(GOLD_STATE)
    validation = read_json(VALIDATION)
    gate28 = read_json(GATE28)
    gate32 = read_json(GATE32_MANIFEST)
    donor_rebind = read_json(DONOR_REBIND)

    if signed.get("status") != "frozen_signed":
        raise SystemExit("v4.1 is not signed: %s" % signed.get("status"))

    # ---------------------------------------------------------------- P12
    recorded = gold_manifest["inputs"][CONTRACT_KEY_IN_GOLD]
    input_status = []
    for rel, expected in gold_manifest["inputs"].items():
        path = REPO_ROOT / rel
        if not path.exists():
            input_status.append({"input": rel, "status": "missing"})
            continue
        actual = bare(path)
        input_status.append(
            {"input": rel, "status": "match" if actual == expected else "drift",
             "recorded": expected, "actual": actual}
        )
    drift = [item for item in input_status if item["status"] != "match"]

    p12 = {
        "schema_version": "items-gold-freeze-rebinding-proposal-1",
        "created_on": "2026-10-12",
        "status": "proposal_pending_signoff",
        "purpose": (
            "金标冻结链记录的契约哈希为 v2，而当前已签契约是 v4.1（经 v3、v4）⇒ 出**新版本记录**修正绑定，"
            "不就地改 `freeze-manifest.json`（issue-34 §8）。"
        ),
        "drift_found": {
            "input": CONTRACT_KEY_IN_GOLD,
            "recorded": recorded,
            "actual_now": digest(SIGNED_V41),
            "intermediate_actual": {
                "v3_signed": digest(CONTRACT_V3),
            },
            "chain": "v2 (recorded) → v3 (signed) → v4 (OPEN-1=A/OPEN-2=C) → v4.1 (signed 2026-10-12)",
        },
        "all_inputs_checked": input_status,
        "drift_count": len(drift),
        "other_inputs_stable": [item["input"] for item in input_status if item["status"] == "match"],
        "proposed_new_version_record": {
            "record_path_suggestion": (
                "evidence/10-quality-gold-freeze-20261008-r2/rebinding-v4.1-<date>.json"
                "（新文件；`freeze-manifest.json` 与 `freeze-state.json` 字节不变）"
            ),
            "fields": {
                "binds_contract": digest(SIGNED_V41),
                "binds_contract_schema_version": signed["schema_version"],
                "contract_instrument": signoff["instrument"],
                "supersedes_recorded": recorded,
                "gold_bytes_untouched": True,
                "gold_frozen_on": gold_state.get("frozen_on"),
            },
            "requires": "具名签认（冻结链修订）",
        },
        "related_prior_art": {
            "parallel_record": str(DONOR_REBIND.relative_to(REPO_ROOT)),
            "sha256": digest(DONOR_REBIND),
            "note": "并行会话的再绑定记录针对 v2→v3；本次实际为 v2→v4.1，故须出新记录，不能沿用。",
        },
        "validation_report_note": {
            "status_in_file": validation.get("status"),
            "human_accepted_counts": validation.get("human_accepted_counts"),
            "required": "与 frozen-gold 的 48/48 accepted 对齐（P14）",
        },
    }

    # ---------------------------------------------------------------- P13
    gate28_basis = gate28["quality_requirements"]["metric_basis"]
    gate28_contract_binding = gate28.get("gold", {}).get("scoring_contract_sha256")
    p13 = {
        "schema_version": "items-gate28-metric-basis-proposal-1",
        "created_on": "2026-10-12",
        "status": "proposal_pending_signoff",
        "purpose": (
            "门 28 是 OPEN-1=A 选定的**唯一权威阈值源**，但其 `metric_basis` 仍指向 v3；"
            "契约已签 v4.1 ⇒ 权威源自身的基准版本过期（循环引用）。须以**新版本门记录**推进，"
            "不就地改 `preregistered-gate.json`（issue-34 §8）。"
        ),
        "cycle_detected": {
            "edge_1": "契约 v4.1 的 `threshold_source.effective` 取自门 28 `quality_requirements`",
            "edge_2": f"门 28 的 `metric_basis` 指向 `{gate28_basis}`（v3），不是 v4.1",
            "consequence": "『权威源』的基准版本落后于引用它的契约 ⇒ 单一口径并未真正闭合，须同轮修。",
        },
        "gate28_recorded": {
            "path": str(GATE28.relative_to(REPO_ROOT)),
            "sha256": digest(GATE28),
            "metric_basis_path": "quality_requirements.metric_basis",
            "metric_basis": gate28_basis,
            "contract_binding_path": "gold.scoring_contract_sha256",
            "contract_binding": gate28_contract_binding,
            "quality_requirements": gate28["quality_requirements"],
            "countersigned": (gate28.get("countersignature") or {}).get("status"),
        },
        "drift_second_edge": {
            "path": "gold.scoring_contract_sha256",
            "recorded": gate28_contract_binding,
            "actual_now": digest(SIGNED_V41),
            "note": "门 28 自身也把契约绑在 v3；该绑定与 metric_basis 必须同轮推进，否则门记录内部不一致。",
        },
        "established_precedent": (
            "门 28 已有同类先例：`revision_history[1].changes` = "
            "『gold.scoring_contract_sha256 由 v2 哈希 2eb24be7 再绑定至已签认 v3 哈希』+"
            "『quality_requirements.metric_basis 由 -v2 改为 -v3』。"
            "故本次推进不是新发明，而是沿用同一手续（新版本记录，不就地改）。"
        ),
        "proposed_new_version_record": {
            "record_path_suggestion": (
                "evidence/28-items-only-quality-gate-20261010/r0-zero-call/preregistered-gate-v2.json"
                "（新文件；原 `preregistered-gate.json` 字节不变、哈希留存可追溯）"
            ),
            "delta": {
                "metric_basis": signed["schema_version"],
                "gold.scoring_contract_sha256": digest(SIGNED_V41),
                "quality_requirements_values": "逐字不变（0.85 / 0.80 / 0.80 / 40 / 20 / 0）",
            },
            "requires": "具名签认（门记录修订）",
        },
        "threshold_single_source_effect": {
            "authority": "门 28（推进后为 v2 记录，绑定 v4.1）",
            "scorer_must_change": (
                "`plugins/corpus/structured_scoring.py` 仍硬编码 0.95/0.90（PILOT_CANDIDATE_POLICY），"
                "与已签口径冲突；改为读契约属 **P03，尚未执行**。"
            ),
        },
        "gate32_note": {
            "manifest": str(GATE32_MANIFEST.relative_to(REPO_ROOT)),
            "extractor_version": gate32.get("extractor_version"),
            "protocols": gate32.get("protocols"),
            "note": "门 32 判据与被测对象同轴问题另见并行提案 `gate-32-v2-criteria.proposed.json`（P15）。",
        },
    }

    print(
        json.dumps(
            {
                "P12_drift_count": len(drift),
                "P12_recorded_contract": recorded[:26] + "…",
                "P12_actual_contract": digest(SIGNED_V41)[:26] + "…",
                "P13_gate28_metric_basis": gate28_basis,
                "P13_proposed_basis": signed["schema_version"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.no_write:
        return

    (HERE / "gold-freeze-rebinding-proposal.json").write_text(
        json.dumps(p12, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "gate28-metric-basis-proposal.json").write_text(
        json.dumps(p13, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "README.md").write_text(render_readme(p12, p13), encoding="utf-8")
    manifest = {
        "schema_version": "items-rebinding-proposals-manifest-1",
        "created_on": "2026-10-12",
        "inputs": {
            str(SIGNED_V41.relative_to(REPO_ROOT)): digest(SIGNED_V41),
            str(V41_SIGNOFF.relative_to(REPO_ROOT)): digest(V41_SIGNOFF),
            str(GOLD_MANIFEST.relative_to(REPO_ROOT)): digest(GOLD_MANIFEST),
            str(GOLD_STATE.relative_to(REPO_ROOT)): digest(GOLD_STATE),
            str(VALIDATION.relative_to(REPO_ROOT)): digest(VALIDATION),
            str(GATE28.relative_to(REPO_ROOT)): digest(GATE28),
            str(GATE32_MANIFEST.relative_to(REPO_ROOT)): digest(GATE32_MANIFEST),
            str(DONOR_REBIND.relative_to(REPO_ROOT)): digest(DONOR_REBIND),
        },
        "outputs": {
            name: digest(HERE / name)
            for name in (
                "gold-freeze-rebinding-proposal.json",
                "gate28-metric-basis-proposal.json",
                "README.md",
                "propose_rebinding.py",
            )
        },
        "in_place_edits": 0,
    }
    (HERE / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def render_readme(p12: dict[str, Any], p13: dict[str, Any]) -> str:
    lines = [
        "# P12 / P13 记账提案（均需具名签认；**未就地改任何产物**）",
        "",
        "- 本目录只出**提案**：`freeze-manifest.json`／`freeze-state.json`／`preregistered-gate.json` 字节不变。",
        "",
        "## P12 金标冻结链契约绑定再绑定",
        "",
        f"- 记录值：`{p12['drift_found']['recorded'][:26]}…`（v2）",
        f"- 实际值：`{p12['drift_found']['actual_now'][:26]}…`（v4.1）",
        f"- 链：{p12['drift_found']['chain']}",
        f"- 8 条输入中漂移：**{p12['drift_count']}** 条；其余稳定：{len(p12['other_inputs_stable'])} 条",
        "",
        "| 输入 | 状态 |",
        "|---|---|",
    ]
    for item in p12["all_inputs_checked"]:
        lines.append(f"| `{item['input']}` | {item['status']} |")
    lines += [
        "",
        f"- 建议落位：{p12['proposed_new_version_record']['record_path_suggestion']}",
        f"- 需：{p12['proposed_new_version_record']['requires']}",
        f"- 并行先行记录（针对 v2→v3，**不能沿用**）：`{p12['related_prior_art']['parallel_record']}`",
        "",
        "## P13 门 28 `metric_basis` 推进",
        "",
        f"- 门 28 现记：`{p13['gate28_recorded']['metric_basis']}`",
        f"- 建议改为：`{p13['proposed_new_version_record']['delta']['metric_basis']}`",
        f"- 循环引用：{p13['cycle_detected']['edge_1']}；{p13['cycle_detected']['edge_2']}",
        f"- 后果：{p13['cycle_detected']['consequence']}",
        f"- **第二处漂移**：门 28 `{p13['drift_second_edge']['path']}` = "
        f"`{(p13['drift_second_edge']['recorded'] or '')[:26]}…`（v3），须与 `metric_basis` 同轮推进",
        f"- 先例：{p13['established_precedent']}",
        f"- 阈值逐字不变：{p13['proposed_new_version_record']['delta']['quality_requirements_values']}",
        f"- 评分器仍硬编码 0.95/0.90（P03 未执行）：见 `threshold_single_source_effect`",
        "",
        "## 顺序",
        "",
        "1. P12 与 P13 可同一轮签认（都是记账，不改语义）。",
        "2. 签认后：**P03 评分器读契约** 才有完整依据（契约 v4.1 + 门 28 推进记录）。",
        "3. **P01/P02（装配器与匹配改造）不依赖本目录**，可并行开工。",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
