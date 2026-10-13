#!/usr/bin/env python3
"""Verify the R2 P03 binding catch-up (scorer snapshot follows the newly signed gate v3 / contract v4.3).

Zero model calls, read-only. Each check states the predicate it measures. Exit 1 on any failure.

Authority for this change (no new decision was taken here):
  * contract v4.3 ``threshold_source.effective.implementation_required`` — "评分器 … 现以
    PILOT_CANDIDATE_POLICY 硬编码 0.95/0.90，与本节冲突；须改为读取本契约" (signed OPEN-1 = A)；
  * signed gate v3 — sentinel list 16 → 11 and the five exclusions with mechanisms;
  * the dataclass field set is deliberately unchanged (no data-structure change).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT))

E = REPO_ROOT / ".scratch/claims-r2-role-isolation/evidence"
SIGNED = E / "75-r2-signed-20261013" / "r0-zero-call"
SCORE_77 = E / "77-gate33-rescore-under-v3-20261013" / "r1-score"

from plugins.corpus.structured_scoring import (  # noqa: E402
    CONTRACT_GATE_REQUIREMENTS,
    PILOT_CANDIDATE_POLICY,
    CandidateRecord,
    ContractGateRequirements,
    GoldRecord,
    MatchingMode,
    QualityPolicy,
    RecordOrigin,
    Role,
    RoleThreshold,
    score_structured_quality,
)

SOURCE = "sha256:" + "a" * 64

EXPECTED_CONTRACT_FIELDS = (
    "schema_version",
    "role_scope",
    "target_recall_overall_min",
    "target_recall_per_source_min",
    "candidate_precision_min",
    "accepted_records_total_min",
    "accepted_records_per_source_min",
    "unresolved_candidates_max",
    "material_items_target_total",
    "high_risk_item_assertions_required",
)
EXPECTED_POLICY_FIELDS = (
    "role_thresholds",
    "risk_condition_recall_min",
    "report_support_min",
    "min_gold_per_role",
)

THRESHOLD_KEYS = (
    "target_recall_overall_min",
    "target_recall_per_source_min",
    "candidate_precision_min",
    "accepted_records_total_min",
    "accepted_records_per_source_min",
    "unresolved_candidates_max",
)


def sha256_of(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    contract = load(SIGNED / "scoring-contract-v4.3.json")
    gate = load(SIGNED / "gate-v3.json")
    results: list[dict[str, Any]] = []

    def check(name: str, predicate: str, ok: bool, detail: Any) -> None:
        results.append({"check": name, "predicate": predicate, "ok": bool(ok), "detail": detail})

    # 1. snapshot == signed contract effective thresholds
    effective = contract["threshold_source"]["effective"]
    mismatched = {
        key: (str(effective[key]), str(getattr(CONTRACT_GATE_REQUIREMENTS, key)))
        for key in THRESHOLD_KEYS
        if Fraction(str(effective[key])) != Fraction(str(getattr(CONTRACT_GATE_REQUIREMENTS, key)))
        if key not in ("accepted_records_total_min", "accepted_records_per_source_min", "unresolved_candidates_max")
    }
    numeric_ok = not mismatched and all(
        effective[key] == getattr(CONTRACT_GATE_REQUIREMENTS, key)
        for key in ("accepted_records_total_min", "accepted_records_per_source_min", "unresolved_candidates_max")
    )
    check(
        "snapshot_equals_signed_contract",
        "评分器快照 == 契约 v4.3 threshold_source.effective（六项）",
        numeric_ok,
        {"mismatched": mismatched, "schema_version": CONTRACT_GATE_REQUIREMENTS.schema_version},
    )
    check(
        "snapshot_schema_version_is_v4.3",
        "快照 schema_version == 契约 schema_version",
        CONTRACT_GATE_REQUIREMENTS.schema_version == contract["schema_version"],
        {"snapshot": CONTRACT_GATE_REQUIREMENTS.schema_version, "contract": contract["schema_version"]},
    )

    # 2. sentinel follows the signed gate, exclusions disjoint and annotated
    gate_required = tuple(gate["quality_requirements"]["high_risk_item_assertions_required"])
    gate_excluded = gate["quality_requirements"]["high_risk_item_assertions_excluded"]
    ok_sentinel = (
        CONTRACT_GATE_REQUIREMENTS.high_risk_item_assertions_required == gate_required
        and len(gate_required) == 11
        and not set(gate_required) & set(gate_excluded)
    )
    check(
        "sentinel_follows_signed_gate",
        "哨兵清单 == 门 v3 清单（11 项）且与被移出 5 项互斥",
        ok_sentinel,
        {"required": list(gate_required), "excluded": sorted(gate_excluded)},
    )

    # 3. no data-structure change
    contract_fields = tuple(ContractGateRequirements.__dataclass_fields__)
    policy_fields = tuple(QualityPolicy.__dataclass_fields__)
    check(
        "dataclass_field_sets_unchanged",
        "ContractGateRequirements / QualityPolicy 字段集逐字未变",
        contract_fields == EXPECTED_CONTRACT_FIELDS and policy_fields == EXPECTED_POLICY_FIELDS,
        {"contract": list(contract_fields), "policy": list(policy_fields)},
    )

    # 4. single authority: policy cannot move the verdict
    gold = (
        GoldRecord("NT-I01", Role.MATERIAL_ITEMS, SOURCE, RecordOrigin.LLM_PROSE, (("proposition", "甲"),)),
        GoldRecord("NT-I02", Role.MATERIAL_ITEMS, SOURCE, RecordOrigin.LLM_PROSE, (("proposition", "乙"),)),
    )
    candidate = CandidateRecord("c1", Role.MATERIAL_ITEMS, SOURCE, RecordOrigin.LLM_PROSE, (("proposition", "甲"),))
    mapping = type("M", (), {"candidate_id": "c1", "gold_record_id": "NT-I01", "judgement": "matched", "stage": "raw"})()

    def run(recall_min: Fraction) -> Any:
        policy = replace(
            PILOT_CANDIDATE_POLICY,
            role_thresholds=tuple(
                RoleThreshold(item.role, item.precision_min, recall_min)
                if item.role is Role.MATERIAL_ITEMS
                else item
                for item in PILOT_CANDIDATE_POLICY.role_thresholds
            ),
        )
        return score_structured_quality(
            gold,
            raw_candidates=(candidate,),
            validated_candidates=(candidate,),
            matching_mode=MatchingMode.ADJUDICATED,
            raw_mappings=(mapping,),
            validated_mappings=(mapping,),
            policy=policy,
        )

    lenient, strict = run(Fraction(1, 2)), run(Fraction(9, 10))
    check(
        "policy_cannot_move_the_verdict",
        "改 pilot 策略阈值 ⇒ rate_gate_passed 与 rate_blockers 不变（唯一权威布尔）",
        lenient.gate.rate_gate_passed == strict.gate.rate_gate_passed
        and lenient.gate.rate_blockers == strict.gate.rate_blockers
        and lenient.gate.pilot_policy_blockers != strict.gate.pilot_policy_blockers,
        {
            "lenient_passed": lenient.gate.rate_gate_passed,
            "strict_passed": strict.gate.rate_gate_passed,
            "pilot_blockers_differ": lenient.gate.pilot_policy_blockers != strict.gate.pilot_policy_blockers,
        },
    )

    # 5. two "20" axes stay distinct
    check(
        "two_twenty_axes_are_distinct",
        "角色轴 min_gold_per_role(20) 与源轴 accepted_records_per_source_min(20) 未被混用",
        PILOT_CANDIDATE_POLICY.min_gold_per_role == 20
        and CONTRACT_GATE_REQUIREMENTS.accepted_records_per_source_min == 20
        and CONTRACT_GATE_REQUIREMENTS.role_scope is Role.MATERIAL_ITEMS,
        {
            "min_gold_per_role": PILOT_CANDIDATE_POLICY.min_gold_per_role,
            "accepted_records_per_source_min": CONTRACT_GATE_REQUIREMENTS.accepted_records_per_source_min,
        },
    )

    # 6. the already-published score record is byte-invariant under this change
    score_path = SCORE_77 / "gate33-score-under-v3.json"
    recorded = load(SCORE_77 / "MANIFEST.json")["artifacts"]["gate33-score-under-v3.json"]
    check(
        "published_score_record_unchanged",
        "77 出分记录在本改动后逐字节不变",
        sha256_of(score_path) == recorded,
        {"recorded": recorded, "now": sha256_of(score_path)},
    )

    # 7. the freeze-chain validator agrees
    finished = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools/check_freeze_chain.py"), "--json", "/tmp/fc.json", "--quiet"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    fc = load(Path("/tmp/fc.json")) if Path("/tmp/fc.json").exists() else {}
    check(
        "freeze_chain_validator_clean",
        "check_freeze_chain.py 退出 0，drift=0，needs_ruling=0",
        finished.returncode == 0
        and fc.get("drift") == 0
        and fc.get("needs_ruling") == 0,
        {"exit": finished.returncode, "ok": fc.get("ok"), "covered": fc.get("covered_by_record"),
         "drift": fc.get("drift"), "needs_ruling": fc.get("needs_ruling")},
    )

    # 8. record the exact files carrying the change
    changed = {
        str(path.relative_to(REPO_ROOT)): sha256_of(path)
        for path in (
            REPO_ROOT / "plugins/corpus/structured_scoring.py",
            REPO_ROOT / "tools/check_freeze_chain.py",
            REPO_ROOT / "tests/test_corpus_contract_gate.py",
            REPO_ROOT / "tests/test_corpus_structured_scoring_adjudicated.py",
        )
    }

    out = {
        "schema_version": "p03-binding-catchup-verification-1",
        "created_on": "2026-10-13",
        "zero_model_calls": True,
        "read_only": True,
        "authority": {
            "contract": {
                "path": str((SIGNED / "scoring-contract-v4.3.json").relative_to(REPO_ROOT)),
                "sha256": sha256_of(SIGNED / "scoring-contract-v4.3.json"),
                "clause": "threshold_source.effective.implementation_required + required_alignment(OPEN-1=A)",
            },
            "gate": {
                "path": str((SIGNED / "gate-v3.json").relative_to(REPO_ROOT)),
                "sha256": sha256_of(SIGNED / "gate-v3.json"),
                "clause": "high_risk_item_assertions_required(11) + high_risk_item_assertions_excluded(5)",
            },
        },
        "changed_files": changed,
        "not_changed": {
            "PILOT_CANDIDATE_POLICY": (
                "数值未动：P03 已把 rate_gate_passed 单源到契约快照，pilot 策略只剩诊断语义；"
                "改它无功能收益且会动到历史 pilot 基线"
            ),
            "claims_and_relations_axes": "契约 role_scope=material_items，未覆盖；保持原值并记为未推进",
            "min_gold_per_role": "角色轴，与源轴 accepted_records_per_source_min 分属两轴，未混用",
        },
        "checks": results,
        "passed": sum(1 for item in results if item["ok"]),
        "failed": sum(1 for item in results if not item["ok"]),
    }

    if not args.no_write:
        here = Path(__file__).resolve().parent
        (here / "verification.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (here / "verification.md").write_text(render_md(out), encoding="utf-8")
        manifest = {
            "schema_version": "evidence-manifest-1",
            "created_on": "2026-10-13",
            "zero_model_calls": True,
            "artifacts": {
                name: sha256_of(here / name)
                for name in ("verify_p03_binding.py", "verification.json", "verification.md")
            },
            "inputs": {
                "contract_v4.3": sha256_of(SIGNED / "scoring-contract-v4.3.json"),
                "gate_v3": sha256_of(SIGNED / "gate-v3.json"),
                "score_77_record": sha256_of(SCORE_77 / "gate33-score-under-v3.json"),
                **changed,
            },
            "reproduce": (
                "uv run python .scratch/claims-r2-role-isolation/evidence/"
                "78-p03-binding-catchup-20261013/r0-zero-call/verify_p03_binding.py"
            ),
        }
        (here / "MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    print(json.dumps({"passed": out["passed"], "failed": out["failed"],
                      "failures": [i["check"] for i in results if not i["ok"]]}, ensure_ascii=False, indent=2))
    return 0 if out["failed"] == 0 else 1


def render_md(out: dict[str, Any]) -> str:
    lines = [
        "# P03 绑定追平（评分器快照 → 已签门 v3 / 契约 v4.3）核验记录",
        "",
        f"- 2026-10-13　零模型调用、只读　通过 {out['passed']} / 失败 {out['failed']}",
        f"- 依据契约：`{out['authority']['contract']['path']}` `{out['authority']['contract']['sha256']}`",
        f"  （{out['authority']['contract']['clause']}）",
        f"- 依据门：`{out['authority']['gate']['path']}` `{out['authority']['gate']['sha256']}`",
        f"  （{out['authority']['gate']['clause']}）",
        "",
        "## 一、逐项核验",
        "",
        "| 检查 | 谓词 | 结果 | 实测 |",
        "|---|---|---|---|",
    ]
    for item in out["checks"]:
        lines.append(
            f"| `{item['check']}` | {item['predicate']} | {'PASS' if item['ok'] else 'FAIL'} | "
            f"`{json.dumps(item['detail'], ensure_ascii=False)[:150]}` |"
        )
    lines += ["", "## 二、改动文件（哈希）", ""]
    for name, digest in out["changed_files"].items():
        lines.append(f"- `{name}` `{digest}`")
    lines += ["", "## 三、明确未改动的部分", ""]
    for name, why in out["not_changed"].items():
        lines.append(f"- **{name}**：{why}")
    lines += [
        "",
        "## 四、复现",
        "",
        "```bash",
        "uv run python .scratch/claims-r2-role-isolation/evidence/"
        "78-p03-binding-catchup-20261013/r0-zero-call/verify_p03_binding.py",
        "```",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
