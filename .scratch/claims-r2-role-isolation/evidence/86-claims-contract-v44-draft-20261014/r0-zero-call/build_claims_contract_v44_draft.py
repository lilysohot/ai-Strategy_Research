"""Build the claims-carrying contract v4.4 draft (additions only, v4.3 bytes untouched).

This is the decision carrier for the claims gate: the six pending cells (C1–C6) are written as
**agent proposals**, every added leaf is listed as ``pending_human_signature``, and the diff
against the signed v4.3 is computed rather than claimed. Purposeful changes to existing leaves
are limited to ``supersedes`` / ``status`` / ``signoff`` (the v4.2 → v4.3 precedent); the six
threshold values must stay byte-identical.

It also *verifies* the loader path end to end without producing a signed artifact: a temp copy
flipped to ``frozen_signed`` is loaded through
``load_contract_gate_requirements(..., role=Role.CLAIMS)``.

Usage:
    python build_claims_contract_v44_draft.py [--no-write] [--force]
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.structured_scoring import (  # noqa: E402
    ContractGateRequirements,
    Role,
    load_contract_gate_requirements,
)

DRAFT_ON = "2026-10-14"
BASE = ROOT / "evidence/75-r2-signed-20261013/r0-zero-call/scoring-contract-v4.3.json"
GATE_V2 = (
    ROOT / "evidence/84-claims-gate-v2-draft-20261014/r0-zero-call/claims-gate-v2.proposed.json"
)
MEASUREMENTS_V2 = (
    ROOT / "evidence/84-claims-gate-v2-draft-20261014/r0-zero-call/claims-caliber-measurements.json"
)
ITEMS_GATE_V3 = ROOT / "evidence/75-r2-signed-20261013/r0-zero-call/gate-v3.json"
FROZEN_GOLD = ROOT / "evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json"
CLAIMS_ADJ = (
    ROOT
    / "evidence/17-structured-extraction-convergence-closure-20261009"
    / "p1r5-claims-adjudication-v2/candidate-adjudications.signed.json"
)
V44_SCHEMA = "non-table-selected-target-scoring-contract-v4.4"

INPUTS = {
    "scoring_contract_v4.3_signed": BASE,
    "items_gate_v3_signed": ITEMS_GATE_V3,
    "frozen_gold_r2": FROZEN_GOLD,
    "p1r5_candidate_adjudications_signed": CLAIMS_ADJ,
    "claims_gate_v2_draft": GATE_V2,
    "claims_caliber_measurements_v2": MEASUREMENTS_V2,
}

# --- agent proposals, one entry per pending decision cell ---------------------
CLAIMS_ROLE_SECTION = {
    "review_assertions": ["NT-C11", "NT-C12", "NT-C13"],
    "target_total": 20,
    "_basis": "契约 v4.3 review_assertions 的 NT-C* 子集恒等；target_total = 冻结金标 claims 目标数",
}

CLAIMS_SCOPE = {  # C1
    "status": "agent_proposal_pending_human_signature",
    "id": "C1",
    "mode": "in_role_only",
    "predicate": "candidate.kind != 'opinion' AND candidate.value_text 非空",
    "excluded_handling": [
        "移出 claims 角色判据（不计入 claims 分母）",
        "必须在 material_items / material_relations 侧登记为待覆盖，不得就地丢弃",
        "不得改判为 matched，不得改动候选或金标字节",
    ],
    "rejected_alternative": {
        "option": "按与全部 92 条金标相似度 <0.15 移出（83 号草案 B/C）",
        "reason": "该规则按与金标的相似度定义分母，实测删 0 条 matched ⇒ 只删负例不删正例",
    },
    "measured": {
        "D1_all_candidates": "56/110 = 0.5091",
        "D2_in_role_only": "51/81 = 0.6296",
        "per_source_D2": {"f16e7fde9553": "33/56 = 0.5893", "dca4bad7f85b": "18/25 = 0.7200"},
        "target_recall_D2": "20/20 = 1.0000",
    },
}

PRECISION_SINGLE_SOURCE = {  # C2
    "status": "agent_proposal_pending_human_signature",
    "id": "C2",
    "defect": "契约文字公式分母含 duplicate；plugins/corpus/structured_scoring.py::RoleMetrics.precision 分母不含",
    "observed_values": {
        "contract_text_formula": "56/110 = 0.5091",
        "scorer_implemented_formula": "56/107 = 0.5234",
    },
    "proposed_single_source": "分母含 duplicate（与已签 P1R5 gate result 的 0.5091 一致）",
    "required_implementation_change": "RoleMetrics.precision 计入 duplicate_fp；评分器改为读契约声明",
    "note": "该改动会改变评分器对含 duplicate 池的输出，须与契约同轮具名签认",
}

CLAIMS_READ_PATH = {  # C3
    "status": "agent_proposal_pending_human_signature",
    "id": "C3",
    "implemented_in_this_revision": False,
    "reason_not_implemented": "四项字段生产端零载体，carrier/handling 取值须先经签认；本草案只给提案",
    "measured_carriers_out_of_110": {
        "subject": 108,
        "metric": 102,
        "period": 74,
        "unit": 80,
        "value": 97,
        "factuality": 110,
        "qualifier": 109,
        "attribution": 0,
        "perspective": 0,
        "source_stance": 0,
        "estimate_status": 0,
    },
    "carriers_proposed": {
        "subject": {"carrier": "claim.subject", "requires": "normalization"},
        "metric": {"carrier": "claim.metric", "requires": "caliber_normalization"},
        "period": {"carrier": "claim.period_raw", "requires": "normalization"},
        "unit": {"carrier": "claim.unit_raw", "requires": "normalization"},
        "value": {"carrier": "claim.value_text", "requires": "normalization"},
        "factuality": {
            "carrier": "claim.kind",
            "requires": "caliber_normalization",
            "proposed_rule": "fact -> actual；candidate 的 opinion 属角色外（见 claims_scope）",
            "domain_note": "候选 fact/opinion/forecast vs 金标 actual/forecast；词表不同轴",
        },
        "qualifier": {"carrier": "claim.qualifiers", "requires": "none"},
        "attribution": {"carrier": "none", "requires": "excluded_from_matching_basis"},
        "perspective": {"carrier": "none", "requires": "human_only"},
        "source_stance": {"carrier": "none", "requires": "human_only"},
        "estimate_status": {"carrier": "none", "requires": "human_only"},
    },
    "precedent": "items 先例：attribution/speaker_ref 移出匹配基、source_stance 记 human_only（契约 v4.3 caliber_rules）",
}

USE_GRADING = {  # C4
    "status": "agent_proposal_pending_human_signature",
    "id": "C4",
    "current_behaviour": "evidence_pipeline.py:404 『零 reason 才授予 compare/calculate』（全或无）",
    "measured_impact": {
        "correct_records_with_at_least_one_reason": "45/56",
        "records_that_can_compare_or_calculate_today": "11/56",
        "reason_codes_as_hard_gate_cost": "召回 12/20 ⇒ reason 粒度太粗，不能当匹配门",
    },
    "proposed_rule": "按受影响轴撤去用途：缺 period/unit/value 只撤去 compare/calculate；缺 attribution/perspective 只撤去 cite 的归属声明；不得整条判不可用",
    "axes": {
        "value": ["compare", "calculate"],
        "unit": ["compare", "calculate"],
        "period": ["compare", "calculate"],
        "attribution": ["cite_attributed"],
        "perspective": ["cite_attributed"],
        "source_stance": ["cite_stance"],
    },
    "implementation_note": "须先拆 reason_codes 为『阻断匹配』与『阻断某项用途』两类，再落地；属改默认行为，须具名签认",
}

THRESHOLDS_CLAIMS = {  # C5 / C6
    "status": "agent_proposal_pending_human_signature",
    "id": "C5/C6",
    "target_line": {
        "basis": "与已签 items 门 v3 / 契约六项逐字恒等（0.85 / 0.80 / 0.80 / 0 / 哨兵 3 条）",
        "target_recall_overall_min": 0.85,
        "target_recall_per_source_min": 0.8,
        "candidate_precision_min": 0.8,
        "unresolved_candidates_max": 0,
        "sentinels_required": ["NT-C11", "NT-C12", "NT-C13"],
        "granularity_warning": "目标仅 20 条 ⇒ 0.85 ≙ 17/20，每错 1 条 −5.0pp",
    },
    "release_line_proposed": {
        "candidate_precision_min": 0.6,
        "target_recall_per_source_min": 0.55,
        "basis": "D2 口径实测值 0.6296 / 分源 0.5893（源1）",
        "tolerance": "再容忍 4 条新增假阳性（契约式公式，分母 81）",
        "role": "功能线：只判『可交付 / 需更换路线』，不等于质量达标",
        "preregistration_rule": "禁止在看到本轮分数之后再定值",
    },
    "unreachable_registration": {
        "target_line_on_frozen_pool": "不可达",
        "evidence": "D2 分子上限 51/81 = 0.6296 < 0.80；分源 0.5893 < 0.80",
        "implication": "要达目标线须另立授权的重跑（新池），不得通过改分母实现",
    },
}

ADDITIONS: dict[str, Any] = {
    "claims_scope": CLAIMS_SCOPE,
    "claims_precision_single_source": PRECISION_SINGLE_SOURCE,
    "claims_use_grading": USE_GRADING,
    "claims_thresholds": THRESHOLDS_CLAIMS,
    "agent_proposals": {
        "pending_human_signature": [
            "C1 claims_scope",
            "C2 claims_precision_single_source",
            "C3 claims_read_path（只提案，未实施）",
            "C4 claims_use_grading（未实施）",
            "C5/C6 claims_thresholds",
        ],
        "not_changed_by_this_draft": [
            "契约 v4.3 的任何既有叶子值（只增不删）",
            "items 六项阈值与 11 条 NT-I 哨兵",
            "frozen-gold.json / P1R5 已签裁定 / items 门 v3 字节",
        ],
    },
}
ADDITIONS["read_path"] = {
    "roles_proposed": {"claims": CLAIMS_READ_PATH},
    "_note": "既有 read_path（material_items）逐字未改；claims 分支以 roles_proposed 另立，避免与已签叶子混写",
}

EXPECTED_CHANGED_LEAVES = ("schema_version", "status", "supersedes", "signoff")
EXPECTED_ADDED_TOP_LEVEL = tuple(ADDITIONS)
THRESHOLD_KEYS = (
    "target_recall_overall_min",
    "target_recall_per_source_min",
    "candidate_precision_min",
    "accepted_records_total_min",
    "accepted_records_per_source_min",
    "unresolved_candidates_max",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def diff_paths(old: Any, new: Any, prefix: str = "") -> dict[str, list[str]]:
    """Recursive leaf diff: which paths were added, removed or changed."""
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


def build_v44() -> dict[str, Any]:
    base = load(BASE)
    draft = copy.deepcopy(base)
    draft["schema_version"] = V44_SCHEMA
    draft["status"] = "draft_pending_human_signature"
    draft["supersedes"] = {
        "schema_version": base["schema_version"],
        "status_at_supersede": base["status"],
        "sha256": f"sha256:{sha256(BASE)}",
        "note": "v4.4 只增叶子：新增 role_sections/claims_scope/claims_precision_single_source/"
        "claims_use_grading/claims_thresholds/read_path.roles_proposed 与 agent_proposals；"
        "既有叶子仅 schema_version/status/supersedes/signoff 四处按新版本手续改动，六项阈值逐字不变。",
    }
    draft["signoff"] = {
        "signed_by": None,
        "signed_on": None,
        "statement": None,
        "instrument": {
            "path": str((HERE / "claims-contract-v4.4-signoff.md").relative_to(ROOT)),
            "sha256": None,
        },
        "scope_note": "草案未签认；claims 分支在签认前不得被任何评分入口读取（role_sections 缺失时 fail-closed）",
        "reviewer_remark": None,
        "remark_note": "草案未签认：备注栏留空；签认时按 v4.3 同款手续填写，不得以留空代替逐格确认",
    }
    for key, value in ADDITIONS.items():
        if key == "read_path":
            draft.setdefault("read_path", {})
            draft["read_path"]["roles_proposed"] = value["roles_proposed"]
            draft["read_path"]["_proposal_note"] = value["_note"]
        else:
            draft[key] = copy.deepcopy(value)
    draft["role_sections"] = {
        "material_items": {
            "review_assertions": sorted(
                key for key in base["review_assertions"] if key.startswith("NT-I")
            ),
            "target_total": 48,
            "_basis": "逐字镜像 v4.3 review_assertions 的 NT-I* 子集与既有 target_total（48），"
            "使同一份契约同时服务 items 与 claims",
        },
        "claims": copy.deepcopy(CLAIMS_ROLE_SECTION),
    }
    return draft


def _items_equal_except_schema(left: Any, right: Any) -> bool:
    """True when two requirements differ only in ``schema_version``."""
    names = [name for name in ContractGateRequirements.__dataclass_fields__ if name != "schema_version"]
    return all(getattr(left, name) == getattr(right, name) for name in names)


def verify_loader(draft: dict[str, Any]) -> dict[str, Any]:
    """Load the draft through the role-aware loader using a temp copy flipped to signed."""
    signed_like = copy.deepcopy(draft)
    signed_like["status"] = "frozen_signed"
    signed_like["signoff"] = {"signed_by": "verify-only", "signed_on": DRAFT_ON}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "v44-signed-like.json"
        path.write_text(json.dumps(signed_like, ensure_ascii=False), encoding="utf-8")
        requirements = load_contract_gate_requirements(path, role=Role.CLAIMS)
        items_from_v44 = load_contract_gate_requirements(path)
        items_from_v43 = load_contract_gate_requirements(BASE)
        claims_legacy = None
        try:
            load_contract_gate_requirements(BASE, role=Role.CLAIMS)
        except Exception as error:  # noqa: BLE001 - the point is the message
            claims_legacy = str(error)
        return {
            "claims_role_scope": requirements.role_scope.value,
            "claims_sentinels": list(requirements.high_risk_item_assertions_required),
            "claims_target_total": requirements.role_target_total,
            "claims_precision_min": str(requirements.candidate_precision_min),
            "items_unchanged_role_scope": items_from_v43.role_scope.value,
            "items_target_total": items_from_v43.role_target_total,
            "items_fields_equal_v43_except_schema": _items_equal_except_schema(
                items_from_v44, items_from_v43
            ),
            "v43_claims_load_message": claims_legacy,
        }


def build() -> dict[str, Any]:
    base = load(BASE)
    draft = build_v44()
    diff = diff_paths(base, draft)
    gold = load(FROZEN_GOLD)
    claims_gold = [r for r in gold["records"] if r["role"] == "claims"]
    thresholds_unchanged = {
        key: {
            "v4.3": base["threshold_source"]["effective"][key],
            "v4.4": draft["threshold_source"]["effective"][key],
        }
        for key in THRESHOLD_KEYS
    }
    diff_report = {
        "base": {"path": str(BASE.relative_to(ROOT)), "sha256": sha256(BASE)},
        "changed_leaf_paths": diff["changed"],
        "added_leaf_paths": diff["added"],
        "removed_leaf_paths": diff["removed"],
        "expected_changed_leaves": list(EXPECTED_CHANGED_LEAVES),
        "unexpected_changed": sorted(
            path for path in diff["changed"] if path.split(".")[0] not in EXPECTED_CHANGED_LEAVES
        ),
        "thresholds_unchanged": thresholds_unchanged,
        "thresholds_byte_identical": all(
            entry["v4.3"] == entry["v4.4"] for entry in thresholds_unchanged.values()
        ),
        "role_sections_claims_target_total_equals_gold": draft["role_sections"]["claims"][
            "target_total"
        ]
        == len(claims_gold),
        "removed_is_empty": not diff["removed"],
    }
    loader_verification = verify_loader(draft)
    manifest = {
        "schema_version": "claims-contract-v44-draft-manifest-1",
        "status": "draft",
        "created_on": DRAFT_ON,
        "model_calls": 0,
        "production_pg_access": 0,
        "inputs": {name: sha256(path) for name, path in INPUTS.items()},
        "outputs": {},
        "does_not_touch": [
            str(BASE.relative_to(ROOT)),
            str(ITEMS_GATE_V3.relative_to(ROOT)),
            str(FROZEN_GOLD.relative_to(ROOT)),
            str(CLAIMS_ADJ.relative_to(ROOT)),
        ],
    }
    return {
        "contract": draft,
        "diff": diff_report,
        "loader_verification": loader_verification,
        "manifest": manifest,
    }


SIGNOFF_MD = """# Claims 契约 v4.4 草案 · 签认件（六格提案）

状态：草稿，**未签认**。`status = draft_pending_human_signature`，`signoff` 三项为 null。
以已签 `scoring-contract-v4.3.json`（{base_sha}）为基，**只增叶子**；六项阈值逐字不变；
不改 frozen-gold / P1R5 已签裁定 / items 门 v3 的任何字节。

## 一、机检结论（可复跑本目录 `build_claims_contract_v44_draft.py`）

| 检查 | 结果 |
|---|---|
| 删除叶子 | {removed} |
| 计划外改动叶子 | {unexpected} |
| 六项阈值逐字不变 | {thresholds} |
| role_sections.claims.target_total == 冻结金标 claims 目标数 | {total_ok} |
| 载入器验证（临时副本置 frozen_signed） | {loader} |

## 二、六格提案（请逐格签认或改写）

| 编号 | 提案 | 实测依据 |
|---|---|---|
| C1 | claims 角色范围 = 指标断言（`kind != opinion` 且 value 非空）；剔出项须在 items/relations 侧登记覆盖 | D1 {d1} → D2 {d2}；分源 {per_source}；召回 {recall} |
| C2 | 精度分母单一源 = 含 duplicate（与已签 P1R5 的 {d1} 一致）；评分器 `RoleMetrics.precision` 计入 duplicate_fp | 契约文字 {c2_contract} vs 实现 {c2_impl} |
| C3 | claims 读路径：六字段有载体；attribution 移出匹配基；perspective/source_stance/estimate_status 记 human_only | 11 字段载体实测（四字段 0/110） |
| C4 | compare/calculate 由全或无改为按受影响轴撤去 | 现规则下仅 11/56 条可用；reason 当硬门召回掉到 12/20 |
| C5 | 目标线不动（0.85/0.80/0.80/0 + 哨兵 NT-C11/C12/C13）；新增放行线 0.60 / 分源 0.55 | 容忍度：再容忍 4 条新增假阳性 |
| C6 | 登记「目标线在冻结池不可达」，要达标须另立授权的重跑 | D2 分子上限 {d2} < 0.80 |

## 三、硬约束（不属于待裁）

- 签发后 `role_sections.claims` 才生效；未签认时 `load_contract_gate_requirements(..., role=claims)`
  以 `contract_role_section_missing:claims` 失败关闭（已实测）。
- C3/C4 本草案**只提案、未实施**；未签认前不改任何默认行为。

## 签名

reviewer: ____________    adjudicator: ____________    signed_on: ____________
"""


def render_signoff(result: dict[str, Any]) -> str:
    diff = result["diff"]
    loader = result["loader_verification"]
    gate = load(GATE_V2)
    d1 = gate["calibers"]["D1_all_candidates"]["precision_contract_formula"]["display"]
    d2 = gate["calibers"]["D2_in_role_only"]["precision_contract_formula"]["display"]
    return SIGNOFF_MD.format(
        base_sha=f"sha256:{diff['base']['sha256']}",
        removed=diff["removed_leaf_paths"] or "无",
        unexpected=diff["unexpected_changed"] or "无",
        thresholds="是" if diff["thresholds_byte_identical"] else "否",
        total_ok="是" if diff["role_sections_claims_target_total_equals_gold"] else "否",
        loader=(
            f"claims scope={loader['claims_role_scope']}、哨兵 {len(loader['claims_sentinels'])} 条、"
            f"target_total={loader['claims_target_total']}；v4.3 上 claims 载入被拒："
            f"{loader['v43_claims_load_message']}"
        ),
        d1=d1,
        d2=d2,
        per_source="源1 0.5893 / 源2 0.7200",
        recall=gate["calibers"]["D2_in_role_only"]["target_recall"]["display"],
        c2_contract=gate["calibers"]["D1_all_candidates"]["precision_contract_formula"]["display"],
        c2_impl=gate["calibers"]["D1_all_candidates"][
            "precision_scorer_implemented_formula"
        ]["display"],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = build()
    outputs = {
        "scoring-contract-v4.4.proposed.json": (
            json.dumps(result["contract"], ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
        "contract-v4.4-diff.json": (
            json.dumps(result["diff"], ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
        "claims-contract-v4.4-signoff.md": render_signoff(result).encode("utf-8"),
    }
    manifest = result["manifest"]
    manifest["outputs"] = {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()}
    manifest["loader_verification"] = result["loader_verification"]
    manifest["diff_summary"] = {
        "removed_leaf_paths": result["diff"]["removed_leaf_paths"],
        "unexpected_changed": result["diff"]["unexpected_changed"],
        "thresholds_byte_identical": result["diff"]["thresholds_byte_identical"],
    }
    outputs["MANIFEST.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")

    if args.no_write:
        print(json.dumps(result["diff"], ensure_ascii=False, indent=2))
        print(json.dumps(result["loader_verification"], ensure_ascii=False, indent=2))
        print(f"[no-write] {len(outputs)} outputs computed; nothing written.")
        return 0

    existing = [name for name in outputs if (HERE / name).exists()]
    if existing and not args.force:
        raise SystemExit(f"refusing to overwrite existing outputs {existing}; use --force")
    for name, data in outputs.items():
        (HERE / name).write_bytes(data)
    print(f"wrote {len(outputs)} files to {HERE}")
    print(json.dumps(manifest["outputs"], ensure_ascii=False, indent=2))
    return 0 if result["diff"]["removed_is_empty"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
