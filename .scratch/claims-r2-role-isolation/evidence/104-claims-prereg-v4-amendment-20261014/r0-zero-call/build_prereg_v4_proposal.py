"""Build the v4 amendment of the claims pre-registration (104 号): `unbound_union` → diagnostic.

Why this exists: the signed v3 record (99 号) carries `unbound_union ≤ baseline × 0.5` as a *stage-2
gate*, proposed by the assistant rather than decided by U. The 101-号 zero-call replay measured it at
52 against a target of ≤ 27 and showed its composition is dominated by matched/correct_extra rows, so
it measures *annotation coverage*, not precision: halving it is neither necessary nor sufficient for
the release line, yet it is the only red light and therefore single-handedly blocks the one live run.

U decided on 2026-10-14 to change it into a diagnostic. Because 99 号 is a *signed* record, the change
is landed the way this repo requires: a new version record plus old-hash retention. The 95 draft
(`signed_from` of 99 号) and 99 号 itself are byte-for-byte untouched.

What this script produces (draft status only — no signature is filled in, ever):

* ``claims-preregistration-v4.proposed.json`` — the v4 body: 99-号 body plus exactly this amendment;
* ``claims-preregistration-v4-signoff.md`` — the instrument U signs; signature line left blank;
* ``MANIFEST.json`` — inputs/outputs with hashes, ``blocked_on`` = signature.

Usage:
    python build_prereg_v4_proposal.py [--no-write]
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
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.evidence_guard import assert_writable, write_once  # noqa: E402

CREATED_ON = "2026-10-14"

SIGNED_99 = (
    ROOT
    / "evidence/99-claims-prereg-v3-signed-r2-20261014/r0-zero-call/claims-preregistration.json"
)
ROOT_99 = ROOT / "evidence/99-claims-prereg-v3-signed-r2-20261014"
DRAFT_95 = ROOT / "evidence/95-claims-prereg-20261014/r0-zero-call/claims-preregistration.json"
MANIFEST_95 = ROOT / "evidence/95-claims-prereg-20261014/r0-zero-call/MANIFEST.json"
LANDING_101 = (
    ROOT
    / "evidence/101-claims-treatment-t1t2t3-landing-20261014/r0-zero-call/treatment-landing-record.json"
)
GATE_V3 = ROOT / "evidence/91-claims-gate-v3-signed-20261014/r0-zero-call/claims-gate-v3.json"
REFUSAL_97 = (
    ROOT
    / "evidence/97-claims-governance-refusal-20261014/r0-zero-call/claims-governance-refusal.json"
)
CONTRACT_V44 = (
    ROOT / "evidence/88-claims-contract-v44-signed-20261014/r0-zero-call/scoring-contract-v4.4.json"
)

# Hashes of the frozen inputs this record reads; asserted so drift cannot pass silently.
EXPECTED_SHA256 = {
    SIGNED_99: "a2d174407daa5a1b88ba9ca44e698cf4512a399b2a4895254d0a3ab4b57edf04",
    DRAFT_95: "443df86f559f973efa7d43fa636390463b0a5538922f19d1ef9c452157c7c657",
    LANDING_101: "79c93cd9bb6f6220d6a356db55117708dc4cd8ac58db83b8e7c2e9e790478b70",
}

# Keys that belong to the *signature layer* of 99 号, not to the body it signs. `status` stays in the
# body so the amendment shows up as a `status` change (frozen_before_execution → draft) rather than as
# an added leaf.
SIGNATURE_LAYER = ("signed_from", "countersignature", "supersedes")

# The amendment is expected to touch exactly these leaf paths (no more, no fewer).
EXPECTED_CHANGED = (
    "status",
    "pre_registered_treatment_rules.coverage_rule",
    "pre_registered_treatment_rules.rules",
    "prior_record_readings",
    "revisions",
    "not_done",
)
EXPECTED_ADDED = (
    "amended_from",
    "downstream_followups",
    "exit_rules.early_stop_before_human_adjudication.report_only_proxies",
    "exit_rules.early_stop_before_human_adjudication.stage2_proxies_protocol",
)
EXPECTED_REMOVED = ("exit_rules.early_stop_before_human_adjudication.stage2_proxies.unbound_union",)

AMENDMENT_REASON = (
    "101 号冻结池零调用回放实测：unbound_union 54 → 52，达不到预注册的 ≤ 27；且其并集构成中 "
    "matched/correct_extra 占多数 ⇒ 它量的是『标注覆盖率』而不是精度代理——减半它既不是过放行线的"
    "必要条件，也不是充分条件。作为闸门它单点阻断唯一实跑（其余三项已由 T1/T3/T4 落地回放达成），"
    "却说明不了 claims 质量。U 于 2026-10-14 裁示：改为诊断项，不再参与阶段 2 止损。"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def diff_paths(old: Any, new: Any, prefix: str = "") -> dict[str, list[str]]:
    changed: list[str] = []
    added: list[str] = []
    removed: list[str] = []
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            path = f"{prefix}.{key}" if prefix else key
            if key not in old:
                added.append(path)
            elif key not in new:
                removed.append(path)
            else:
                sub = diff_paths(old[key], new[key], path)
                changed += sub["changed"]
                added += sub["added"]
                removed += sub["removed"]
    elif old != new:
        changed.append(prefix)
    return {"changed": changed, "added": added, "removed": removed}


def check_inputs() -> None:
    for path, digest in EXPECTED_SHA256.items():
        if sha256(path) != digest:
            raise SystemExit(f"refusing to build: {path.name} hash drifted from the frozen value")


def amend(body: dict[str, Any], landing: dict[str, Any], signed_sha: str) -> dict[str, Any]:
    """Apply exactly the one amendment: `unbound_union` leaves the gate and becomes a diagnostic."""
    amended = copy.deepcopy(body)
    amended["status"] = "draft_pending_human_signature"

    early = amended["exit_rules"]["early_stop_before_human_adjudication"]
    diagnostic = early["stage2_proxies"].pop("unbound_union")
    diagnostic["classification"] = "diagnostic"
    diagnostic["gating"] = False
    diagnostic["moved_from"] = "stage2_proxies"
    diagnostic["basis"] = AMENDMENT_REASON
    diagnostic["reading"] = (
        "仍然测量、仍然报告（同一条 field-first 并集谓词），但不再判定是否进入阶段 3；"
        "阶段 2 由余下三项闸门裁决"
    )
    # Rebuild the block so `report_only_proxies` sits next to the gate it was moved out of.
    early["stage2_proxies_protocol"] = (
        "止损项↔治疗规则的一一对账要求只覆盖仍在 stage2_proxies 中的代理；移出 gating 的代理"
        "（unbound_union）保留为诊断读数，不再要求 owner 对账，也不参与 if_failed 判定"
    )
    early["report_only_proxies"] = {
        "why": (
            "这些读数零调用可算、仍按原谓词测量，但不作为进入阶段 3 的条件：它们与精度不同轴，"
            "过与不过都说明不了 claims 质量"
        ),
        "gating": False,
        "unbound_union": diagnostic,
    }

    rules = amended["pre_registered_treatment_rules"]
    rules["coverage_rule"] = (
        "四条规则与阶段 2 的止损项一一对账（每项恰有一个 owner_treatment_rule）；任何止损项若无"
        "对应治疗规则，该闸门在无治疗时恒不可达，本轮不得起跑。自 v4 起，对账范围 = 仍在 "
        "stage2_proxies 中的代理；已移出 gating 的代理（unbound_union，见 report_only_proxies）"
        "不再要求此项对账，T2 保留为其诊断读数的 owner"
    )
    for rule in rules["rules"]:
        if rule["id"] == "T2_unbound_disposition":
            rule["stop_loss_gate"] = False
            rule["gate_note"] = (
                "v4：unbound_union 已移出 stage2 闸门、降为诊断读数（见 exit_rules."
                "early_stop_before_human_adjudication.report_only_proxies）；T2 仍为该诊断读数的 owner"
            )

    measured = landing["replay"]["stage2_proxies"]
    replay = measured["after_replay"]
    amended["prior_record_readings"].append(
        {
            "registration_id": "REG-101-UNBOUND-UNION-DIAGNOSTIC",
            "what": (
                "101 号冻结池回放的 targets.unbound_union（≤ 27）与 replay_verdict."
                "unbound_union_passed 的读法"
            ),
            "record": str(LANDING_101.relative_to(ROOT)),
            "record_sha256": sha256(LANDING_101),
            "field": (
                "replay.stage2_proxies.targets.unbound_union / "
                "replay.stage2_proxies.replay_verdict.unbound_union_passed"
            ),
            "recorded_text": (
                "targets.unbound_union = '≤ 27'；replay_verdict.unbound_union_passed = false"
                f"（after_replay.union = {replay['union']}，before.union = {measured['before']['union']}）"
            ),
            "reading_in_force": (
                "诊断读数：该计数仍按同一谓词测量并报告，但自 v4 起不作为进入阶段 3（人工裁定）的"
                "条件；阶段 2 由余下三项闸门（角色外 = 0、冗余渲染 = 0、缺字段无码 = 0）裁决"
            ),
            "why": AMENDMENT_REASON,
            "supersedes": {
                "record": str(LANDING_101.relative_to(ROOT)),
                "record_sha256": sha256(LANDING_101),
                "field": "replay.stage2_proxies.targets.unbound_union",
                "superseded_text": "unbound_union: ≤ 27（与 replay_verdict.unbound_union_passed 并列的止损判据）",
                "why_superseded": (
                    "该 targets 行写在 95/99 号把 unbound_union 当闸门的语境里；本件把该代理移出 gating "
                    "⇒ 该行不再是现行判据。101 号字节一字不改，本项即其取代读法。"
                ),
            },
            "does_not_change": [
                "101 号任何字节：targets / replay_verdict / composition 保留为当时语境的档案（含哈希）",
                "冻结池上的读数（54、52、并集构成）与其复算脚本",
            ],
        }
    )

    amended["revisions"].append(
        {
            "revision": "v3 → v4（2026-10-14，零调用，签认后修订：新版本记录 + 旧哈希留存）",
            "reason": AMENDMENT_REASON,
            "changes": [
                "exit_rules.early_stop_before_human_adjudication.stage2_proxies 移除 unbound_union"
                "（余 3 项：角色外候选 = 0、冗余渲染 = 0、缺字段无码 = 0）",
                "同层新增 report_only_proxies.unbound_union（baseline 54、原 definition、owner T2、"
                "gating=false、classification=diagnostic）与 stage2_proxies_protocol：保留读数与基线，"
                "只解除闸门",
                "pre_registered_treatment_rules.rules[T2] 增 stop_loss_gate=false 与 gate_note；"
                "coverage_rule 的对账要求限定为仍在 stage2_proxies 中的代理",
                "prior_record_readings 新增第二条：登记 101 号 targets.unbound_union / "
                "unbound_union_passed 的读法变更（101 号字节不改，只记取代读法）",
                "新增 amended_from（指向 99 号已签件）与 downstream_followups（阶段 2 入口判据"
                "指针推进到 v4）",
            ],
            "unchanged": [
                "退出规则 A/B/C 三档的线值（0.80 / 0.60）与质量护栏条款",
                "读数轴（4 项）与主指标分子/分母定义（分子 = matched + correct_extra）",
                "治疗规则 T1 / T3 / T4 及其闸门（角色外 = 0、冗余渲染 = 0、缺字段无码 = 0）",
                "预算请求形态（ceiling 仍为 null；预算落在 103 号）、金标冻结与判据数值",
                "evidence_chain.proxies 的基线计数（54 仍是基线；改的是它的用法，不是它的值）",
            ],
            "changed_after_signature": True,
            "no_signature_existed_before": False,
            "old_hash_retained": str(SIGNED_99.relative_to(ROOT)),
        }
    )

    amended["not_done"].append(
        "阶段 2 入口的判据指针：102 号脚本内的 SIGNED_PREREG 常量仍指向 99 号（其字节不动）；"
        "本件另给 stage2_under_v4.py 作为显式入口，v4 生效后由它按 v4 判据执行阶段 2"
    )

    amended["amended_from"] = {
        "path": str(SIGNED_99.relative_to(ROOT)),
        "sha256": signed_sha,
        "status_at_amend": "frozen_before_execution",
        "decided_by": "U（2026-10-14 裁示：把 unbound_union 改为诊断项）",
        "applied_by": "build_prereg_v4_proposal.py（零调用；草案态产出，未代签）",
        "note": (
            "99 号与 95 号草案的字节均未改动；99 号保留为其自身的已签记录（并继续 supersedes 98 号），"
            "本件是判据的新版本"
        ),
    }
    amended["downstream_followups"] = {
        "why": (
            "避免『签了但没入口读』的纸面生效：102 号已把阶段 2 判据实现为"
            "『逐字读已签件』，但它的常量指向 99 号"
        ),
        "items": [
            {
                "target": "evidence/102-…/build_treatment_adjudication_worksheet.py::SIGNED_PREREG",
                "state": "仍指向 99 号（该脚本为已落地证据件，字节按纪律不改）",
                "resolution": (
                    "本件提供 stage2_under_v4.py：加载 102 号脚本模块、把 SIGNED_PREREG 覆盖为 v4 "
                    "生效件、再委托其阶段 2/3 逻辑 ⇒ 行为跟随 v4，102 号字节不动"
                ),
            },
            {
                "target": "evidence/102-…/execute_claims_treatment.py::SIGNED_PREREG",
                "state": "仍指向 99 号（用于预算闸门与治疗规则清单）",
                "resolution": (
                    "v4 未改动 budget_request 与治疗规则 id ⇒ 该入口无需推进；若日后需要，按同一"
                    "包装方式处理"
                ),
            },
        ],
    }
    return amended


def signoff_md() -> str:
    return f"""# Claims 预注册判据 v4 修订（104 号）· 签认件

状态：草稿，**未签认**。`status = draft_pending_human_signature`。
本件只做一件事：把阶段 2 止损项 `unbound_union` 从**闸门**改为**诊断**（只报告，不阻断）。
零模型调用；不改 95 / 99 / 101 号任何字节（99 号保留为其自身的已签记录）。

## 一、改了什么（仅此一项）

| 位置 | v3（99 号，现行） | v4（本件） |
|---|---|---|
| `stage2_proxies` | 4 项：角色外候选 = 0 / **未绑并集 ≤ 54 × 0.5** / 冗余渲染 = 0 / 缺字段无码 = 0 | **3 项**：角色外候选 = 0 / 冗余渲染 = 0 / 缺字段无码 = 0 |
| `unbound_union` | 闸门（quality proxy） | **诊断**（`report_only_proxies`，`gating=false`，baseline 54 与谓词原样保留） |
| `coverage_rule` | 四条治疗规则 ↔ 四个止损项一一对账 | 对账要求限定为仍在 `stage2_proxies` 中的代理；T2 保留为诊断读数的 owner |

## 二、为什么改（101 号零调用实测）

- 冻结池上 `unbound_union` 实测 **54 → 52**，达不到预注册的 **≤ 27**（T2 的确定性部分只补到 4 条）。
- 并集构成里 `matched / correct_extra` 占多数 ⇒ 它量的是**标注覆盖率**，不是精度代理：减半它
  **既不是过放行线的必要条件，也不是充分条件**（决定去留的是 FP / `incorrect` 那一支）。
- 它是阶段 2 四项里**唯一还亮红**的一项，因而单点阻断唯一实跑；其余三项已由 T1/T3/T4 落地回放达成。

U 于 2026-10-14 裁示：改为诊断项。以下为随之生效的读法变更登记。

## 三、没改什么（逐条冻结）

- A/B/C 三档的线值 **0.80 / 0.60** 与质量护栏条款；
- 读数轴 4 项与主指标分子/分母定义（分子 = matched + correct_extra，与已签 C2 同源）；
- 治疗规则 T1 / T3 / T4 及其闸门；
- 预算请求形态（ceiling 仍为 null；预算落在 103 号）、金标冻结、判据数值；
- `evidence_chain.proxies` 的基线计数（**54 仍是基线**，改的是用法不是值）。

## 四、生效方式（避免纸面生效）

1. U 在本件末尾签署（`reviewer` / `adjudicator` / `signed_on`）；
2. `apply_prereg_v4_signoff.py` 生成生效件 `claims-preregistration-v4.json`
   （`status=frozen_before_execution`，签认块指向本签认件哈希；**未签一律拒绝**，且不代填任何签名字段）；
3. 阶段 2 由 `stage2_under_v4.py` 执行：它以生效件为判据、委托 102 号的阶段 2/3 逻辑
   ⇒ 行为跟随 v4，**102 号字节不动**。

## 五、登记的对既有记录的取代读法

| 被取代的读法 | 记录 | 取代后读法 | 记录字节 |
|---|---|---|---|
| `targets.unbound_union = ≤ 27` 且 `unbound_union_passed = false` | 101 号 landing-record | 诊断读数：仍测量、仍报告，但不作为进入阶段 3 的条件 | **不改** |

## 签名

reviewer:            adjudicator:            signed_on:
"""


def build() -> dict[str, Any]:
    check_inputs()
    signed = load(SIGNED_99)
    if signed.get("status") != "frozen_before_execution":
        raise SystemExit(f"refusing to build: 99 号 status is {signed.get('status')!r}")
    body = {k: v for k, v in signed.items() if k not in SIGNATURE_LAYER}
    landing = load(LANDING_101)
    amended = amend(body, landing, sha256(SIGNED_99))

    diff = diff_paths(body, amended)
    unexpected = {
        "unexpected_changed": sorted(p for p in diff["changed"] if p not in EXPECTED_CHANGED),
        "unexpected_added": sorted(p for p in diff["added"] if p not in EXPECTED_ADDED),
        "unexpected_removed": sorted(p for p in diff["removed"] if p not in EXPECTED_REMOVED),
    }
    missing = {
        "missing_changed": sorted(p for p in EXPECTED_CHANGED if p not in diff["changed"]),
        "missing_added": sorted(p for p in EXPECTED_ADDED if p not in diff["added"]),
        "missing_removed": sorted(p for p in EXPECTED_REMOVED if p not in diff["removed"]),
    }
    # Frozen values that must survive the amendment verbatim.
    invariants = {
        "tiers": amended["exit_rules"]["tiers"] == body["exit_rules"]["tiers"],
        "reading_axes": amended["reading_axes"] == body["reading_axes"],
        "guardrails": amended["metrics"]["guardrails_must_not_regress"]
        == body["metrics"]["guardrails_must_not_regress"],
        "treatment_definition_checks": amended["metrics"]["treatment_definition_checks"]
        == body["metrics"]["treatment_definition_checks"],
        "trial_validity": amended["exit_rules"]["trial_validity"]
        == body["exit_rules"]["trial_validity"],
        "proxies": amended["evidence_chain"]["proxies"] == body["evidence_chain"]["proxies"],
        "budget_request": amended["budget_request"] == body["budget_request"],
        "thresholds": amended["gold_and_caliber_freezes"] == body["gold_and_caliber_freezes"],
        "diagnostic_keeps_baseline": (
            amended["exit_rules"]["early_stop_before_human_adjudication"]["report_only_proxies"][
                "unbound_union"
            ]["baseline"]
            == body["exit_rules"]["early_stop_before_human_adjudication"]["stage2_proxies"][
                "unbound_union"
            ]["baseline"]
            == 54
        ),
    }
    if not all(invariants.values()):
        raise SystemExit(f"refusing to build: frozen invariants broken: {invariants}")
    if any(unexpected.values()) or any(missing.values()):
        raise SystemExit(f"refusing to build: diff is not the planned one: {unexpected} {missing}")

    return {
        "amended": amended,
        "diff": diff,
        "unexpected": unexpected,
        "invariants": invariants,
        "payload": json.dumps(amended, ensure_ascii=False, indent=2) + "\n",
    }


def manifest(result: dict[str, Any], outputs: dict[str, str]) -> dict[str, Any]:
    return {
        "schema_version": "claims-preregistration-amendment-manifest-1",
        "id": "104-claims-prereg-v4-amendment-20261014",
        "status": "draft_pending_human_signature",
        "created_on": CREATED_ON,
        "model_calls": 0,
        "purpose": (
            "把阶段 2 止损项 unbound_union 从闸门改为诊断（U 2026-10-14 裁示）；"
            "以新版本记录 + 旧哈希留存落地，不改 95/99/101 号字节"
        ),
        "inputs": {
            "signed_prereg_99": sha256(SIGNED_99),
            "prereg_draft_95": sha256(DRAFT_95),
            "treatment_landing_101": sha256(LANDING_101),
            "claims_gate_v3_signed": sha256(GATE_V3),
            "governance_refusal_97": sha256(REFUSAL_97),
            "signed_scoring_contract_v4.4": sha256(CONTRACT_V44),
            "prereg_draft_95_manifest": sha256(MANIFEST_95),
        },
        "outputs": outputs,
        "amendment_diff": {
            "changed_leaf_paths": result["diff"]["changed"],
            "added_leaf_paths": result["diff"]["added"],
            "removed_leaf_paths": result["diff"]["removed"],
            "unexpected": result["unexpected"],
        },
        "invariants_kept": result["invariants"],
        "does_not_touch": [
            "evidence/95-claims-prereg-20261014/**",
            "evidence/99-claims-prereg-v3-signed-r2-20261014/**",
            "evidence/101-claims-treatment-t1t2t3-landing-20261014/**",
            "evidence/102-claims-treatment-engineering-20261014/**",
            "evidence/103-claims-budget-authorisation-20261014/**",
            "evidence/88-claims-contract-v44-signed-20261014/**",
            "evidence/91-claims-gate-v3-signed-20261014/**",
            "evidence/97-claims-governance-refusal-20261014/**",
            "evidence/10-quality-gold-freeze-20261008-r2/**",
        ],
        "blocked_on": ["U 在本件签认件上具名签署；未签不得生成生效件"],
        "notes": [
            "草案产出；签名字段一律留空，实施脚本不代签、不预填。",
            "生效需另跑 apply_prereg_v4_signoff.py；阶段 2 由 stage2_under_v4.py 按 v4 判据执行。",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = build()
    outputs = {
        "claims-preregistration-v4.proposed.json": result["payload"],
        "claims-preregistration-v4-signoff.md": signoff_md(),
    }
    digests = {
        name: hashlib.sha256(data.encode("utf-8")).hexdigest() for name, data in outputs.items()
    }
    record = manifest(result, digests)
    outputs["MANIFEST.json"] = json.dumps(record, ensure_ascii=False, indent=2) + "\n"

    if args.no_write:
        print(json.dumps(record["amendment_diff"], ensure_ascii=False, indent=2))
        print(json.dumps(record["invariants_kept"], ensure_ascii=False, indent=2))
        print("[no-write] nothing written.")
        return 0

    for name, data in outputs.items():
        target = HERE / name
        assert_writable(target, reason="104 号 v4 修订草案")
        if target.exists() and not args.force:
            raise SystemExit(f"refusing to overwrite existing output {name}; use --force")
        write_once(target, data, allow_overwrite=True)
    print(f"wrote {len(outputs)} files to {HERE}")
    print(json.dumps(record["outputs"], ensure_ascii=False, indent=2))
    print(json.dumps(record["amendment_diff"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
