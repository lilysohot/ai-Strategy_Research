"""One-shot application of the claims governance decisions (93 号 cells M1/M2/M3).

Reads a *signed* decision record and applies whichever branch each cell selected. Zero model calls,
read-only with respect to every frozen artifact: nothing in 75/83/84/88/90/91/92 号 is ever edited,
and this tool never signs anything -- it only produces drafts for the next signature.

Branch discipline (R1/R2 of the governance plan):

* ``code_landing: "ready"`` -- the mechanism already exists, so the branch lands as a contract leaf
  plus a recomputed gate draft. M1's count floors are such a hook
  (``load_contract_gate_requirements`` reads ``role_sections.<role>`` overrides, inert until used);
* ``code_landing: "requires_separate_change"`` -- the branch needs a further signed change (a new
  dataclass field with its P03 binding record, a new gate axis, a vocabulary extension). The branch
  emits a work order with file anchors instead of pretending to be a one-click edit.

Decision record requirements (fail-closed, in this order):

1. the record carries ``decision_signoff`` with reviewer / adjudicator / signed_on;
2. every cell has ``status == "decided"`` and a non-null ``value``;

``--simulate M1=b_scaled_floor,...`` bypasses 1-2 for dry runs and **never writes anything**, so a
simulated combination can never be mistaken for a decision.

Usage:
    uv run python tools/apply_claims_governance_decisions.py                      # refuse: unsigned
    uv run python tools/apply_claims_governance_decisions.py --simulate M1=b_scaled_floor
    uv run python tools/apply_claims_governance_decisions.py --apply              # after signoff
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRATCH = REPO_ROOT / ".scratch/claims-r2-role-isolation"

DEFAULT_PLAN = (
    SCRATCH / "evidence/93-claims-governance-plan-20261014/r0-zero-call/claims-governance-plan.json"
)
DEFAULT_CONTRACT_V44 = (
    SCRATCH
    / "evidence/88-claims-contract-v44-signed-20261014/r0-zero-call/scoring-contract-v4.4.json"
)
DEFAULT_GATE_V3 = (
    SCRATCH / "evidence/91-claims-gate-v3-signed-20261014/r0-zero-call/claims-gate-v3.json"
)
DEFAULT_OUT = SCRATCH / "evidence/94-claims-governance-apply-20261014/r0-zero-call"

M1_VALUES = {
    "a_transplant": (40, 20),
    "b_scaled_floor": (17, 8),
    "b_scaled_ceil": (17, 9),
}
M1_DIAGNOSTIC = "c_diagnostic"
M2_VALUES = ("exists", "report_only")
M3_VALUES = ("O1_status_quo", "O2_remap_two_codes", "O3_extend_vocabulary")

# Anchors for the work orders. Kept as strings so a moved line fails the referencing test rather
# than silently pointing at the wrong code.
GATE_EVALUATION_SITE = "plugins/corpus/structured_scoring.py::_score_gate"
CONTRACT_REQUIREMENTS_FIELD_SET = "tests/test_claims_contract_role.py::EXPECTED_FIELD_SET"
USE_AXES_SITE = "plugins/corpus/claim_use_axes.py"
USABLE_FOR_SITE = "plugins/corpus/structured/store.py:332"


class DecisionError(RuntimeError):
    """Raised when an unsigned or incomplete decision record is asked to apply."""


def _accepted_per_source(blockers: list[str]) -> dict[str, int]:
    """Recover the full per-source accepted counts from the signed gate's own blocker strings."""
    found: dict[str, int] = {}
    for text in blockers:
        match = re.match(
            r"contract_below_threshold:accepted_records_per_source:"
            r"(sha256:[0-9a-f]{64}):(\d+)<(\d+)",
            text,
        )
        if match:
            found[match.group(1)] = int(match.group(2))
    if not found:
        raise DecisionError("已签门里找不到分源 accepted 计数，无法复算变体")
    return found


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_decisions(plan: dict[str, Any]) -> dict[str, str]:
    """Return ``{cell_id: value}`` for a signed record; refuse anything else."""
    signoff = plan.get("decision_signoff") or {}
    missing = [key for key in ("reviewer", "adjudicator", "signed_on") if not signoff.get(key)]
    if missing:
        raise DecisionError(
            f"decision_signoff 不完整（缺 {','.join(missing)}）⇒ 拒绝执行；先由 U 具名签认，"
            "或改用 --simulate 做不计入决定的试算"
        )
    decisions: dict[str, str] = {}
    for cell in plan.get("cells") or []:
        cell_id = str(cell.get("id"))
        if cell.get("status") != "decided" or cell.get("value") in (None, ""):
            raise DecisionError(
                f"{cell_id} 未裁定（status={cell.get('status')}, value=null）⇒ 拒绝执行"
            )
        decisions[cell_id] = str(cell["value"])
    return decisions


def parse_simulation(spec: str) -> dict[str, str]:
    decisions: dict[str, str] = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise DecisionError(f"--simulate 需要 格=值 形式，收到 {part!r}")
        cell_id, value = (piece.strip() for piece in part.split("=", 1))
        decisions[cell_id] = value
    return decisions


def evaluate_variant(
    floors: tuple[int, int] | None,
    *,
    accepted_total: int,
    accepted_per_source: dict[str, int],
    precision: Fraction,
    precision_min: Fraction,
    recall: Fraction,
    recall_min: Fraction,
    per_source_recall: dict[str, Fraction],
    per_source_recall_min: Fraction,
    unresolved: int,
    unresolved_max: int,
    precision_line: str,
    recall_line: str,
) -> dict[str, Any]:
    """Recompute the rate gate for one accepted-floor variant (mirrors the signed gate's strings)."""
    blockers: list[str] = []
    if precision < precision_min:
        blockers.append(
            f"contract_below_threshold:candidate_precision:{precision_line}<{precision_min}"
        )
    if recall < recall_min:
        blockers.append(f"contract_below_threshold:target_recall:{recall_line}<{recall_min}")
    for source, value in sorted(per_source_recall.items()):
        if value < per_source_recall_min:
            blockers.append(
                f"contract_below_threshold:target_recall_per_source:{source}:{value}<{per_source_recall_min}"
            )
    if floors is not None:
        total_min, per_source_min = floors
        if accepted_total < total_min:
            blockers.append(
                f"contract_below_threshold:accepted_records_total:{accepted_total}<{total_min}"
            )
        for source, count in sorted(accepted_per_source.items()):
            if count < per_source_min:
                blockers.append(
                    f"contract_below_threshold:accepted_records_per_source:{source}:{count}<{per_source_min}"
                )
    if unresolved > unresolved_max:
        blockers.append(
            f"contract_above_threshold:unresolved_candidates:{unresolved}>{unresolved_max}"
        )
    return {
        "floors": None
        if floors is None
        else {
            "accepted_records_total_min": floors[0],
            "accepted_records_per_source_min": floors[1],
        },
        "enforcement": "diagnostic" if floors is None else "gating",
        "rate_blockers": blockers,
        "rate_gate_passed": not blockers,
    }


def apply_m1(value: str, context: dict[str, Any]) -> dict[str, Any]:
    if value == M1_DIAGNOSTIC:
        return {
            "cell": "M1",
            "selected": value,
            "contract_leaves": {},
            "code_landing": "requires_separate_change",
            "requires_new_signature": "契约 v4.5（该轴从 gating 降为 diagnostic，属契约语义变更）",
            "work_order": [
                {
                    "site": GATE_EVALUATION_SITE,
                    "change": "该轴在 diagnostic 声明下只报告、不参与 rate_gate_passed",
                }
            ],
            "recomputed": evaluate_variant(None, **context),
        }
    if value not in M1_VALUES:
        raise DecisionError(f"M1 取值未知：{value!r}（可选 {[*sorted(M1_VALUES), M1_DIAGNOSTIC]}）")
    total_min, per_source_min = M1_VALUES[value]
    return {
        "cell": "M1",
        "selected": value,
        "contract_leaves": {
            "role_sections.claims.accepted_records_total_min": total_min,
            "role_sections.claims.accepted_records_per_source_min": per_source_min,
        },
        "code_landing": "ready",
        "landing_note": (
            "load_contract_gate_requirements 已支持 role_sections.<role> 的两个条数下限覆盖"
            "（缺省回退到 threshold_source.effective，故本次签认前行为逐字不变）"
        ),
        "requires_new_signature": "契约 v4.5",
        "recomputed": evaluate_variant((total_min, per_source_min), **context),
    }


def apply_m2(value: str) -> dict[str, Any]:
    if value not in M2_VALUES:
        raise DecisionError(f"M2 取值未知：{value!r}（可选 {list(M2_VALUES)}）")
    if value == "report_only":
        return {
            "cell": "M2",
            "selected": value,
            "contract_leaves": {
                "claims_thresholds.release_line.per_source_precision_min": 0.55,
                "claims_thresholds.release_line.per_source_precision_axis": "report_only",
            },
            "code_landing": "ready",
            "landing_note": "该轴只报告，不参与 gating；与 91 号现状一致，无行为变化",
            "requires_new_signature": "契约 v4.5",
        }
    return {
        "cell": "M2",
        "selected": value,
        "contract_leaves": {},
        "code_landing": "requires_separate_change",
        "requires_new_signature": "契约 v4.5 + 新的 P03 绑定记录",
        "work_order": [
            {
                "site": GATE_EVALUATION_SITE,
                "change": "新增分源精度轴参与 rate_gate_passed（六项之外的第七轴）",
            },
            {
                "site": CONTRACT_REQUIREMENTS_FIELD_SET,
                "change": "ContractGateRequirements 需新增字段 ⇒ P03 绑定校验器字段元组变化，须同轮出新绑定记录",
            },
            {
                "site": "plugins/corpus/structured_scoring.py::_ROLE_SECTION_ALLOWED_KEYS",
                "change": "若把该轴放进 role_sections.claims，须同步扩充允许键（否则 fail-closed 拒绝）",
            },
        ],
        "blocked_on": "P03 绑定记录（新字段）",
    }


def apply_m3(value: str) -> dict[str, Any]:
    if value not in M3_VALUES:
        raise DecisionError(f"M3 取值未知：{value!r}（可选 {list(M3_VALUES)}）")
    if value == "O1_status_quo":
        return {
            "cell": "M3",
            "selected": value,
            "contract_leaves": {"claims_use_grading.implementation": "status_quo_axis_withdrawal"},
            "code_landing": "ready",
            "landing_note": "与 92 号落地的默认档一致（11/56 可 compare/calculate），无行为变化",
            "requires_new_signature": "契约 v4.5",
        }
    if value == "O2_remap_two_codes":
        return {
            "cell": "M3",
            "selected": value,
            "contract_leaves": {},
            "code_landing": "requires_separate_change",
            "requires_new_signature": "契约 v4.5 + C4 轴归属的具名签认",
            "proposed_patch": {
                "path": USE_AXES_SITE,
                "change": (
                    "source_qualified_context_requires_review 与 qualifier_definition_unverified "
                    "由 condition 轴改挂 attribution 轴"
                ),
                "measured_delta": {"usable_compare_or_calculate": "11/56 → 26/56", "delta": 15},
                "risk": "带条件/否定/转述语境的数值断言变为可计算，与报告 §5.1.2 相冲",
            },
        }
    return {
        "cell": "M3",
        "selected": value,
        "contract_leaves": {},
        "code_landing": "requires_separate_change",
        "requires_new_signature": "契约 v4.5 + 下游词表变更的具名签认",
        "work_order": [
            {
                "site": USABLE_FOR_SITE,
                "change": "usable_for 允许集合新增 cite_attributed / cite_stance（不放行 compare/calculate）",
            },
            {
                "site": "plugins/corpus/structured + query/consumption/derivation 消费点",
                "change": "消费点需认识新标签，并出回归证明",
            },
        ],
    }


def build_application(
    decisions: dict[str, str],
    *,
    contract: dict[str, Any],
    gate: dict[str, Any],
    simulated: bool,
) -> dict[str, Any]:
    measured = gate["measured_run"]
    variant_a = measured["variants"]["a_items_40_20"]
    per_source_accepted = _accepted_per_source(variant_a["rate_blockers"])
    pool_accepted_total = int(variant_a["rate_blockers"][1].rsplit(":", 1)[1].split("<")[0])
    ledger = variant_a["ledger"]
    numerator = ledger["tp"] + ledger["correct_extra"]
    denominator = numerator + ledger["fp_includes_duplicates"]
    precision = Fraction(numerator, denominator)
    per_source_precision = {
        source: Fraction(int(text.split("/")[0]), int(text.split("/")[1].split()[0]))
        for source, text in gate["thresholds"]["release_line"][
            "measured_per_source_precision"
        ].items()
    }
    context = {
        "accepted_total": pool_accepted_total,
        "accepted_per_source": per_source_accepted,
        "precision": precision,
        "precision_min": Fraction(
            str(gate["thresholds"]["target_line"]["candidate_precision_min"])
        ),
        "recall": Fraction(20, 20),
        "recall_min": Fraction(str(gate["thresholds"]["target_line"]["target_recall_overall_min"])),
        "per_source_recall": {source: Fraction(10, 10) for source in per_source_accepted},
        "per_source_recall_min": Fraction(
            str(gate["thresholds"]["target_line"]["target_recall_per_source_min"])
        ),
        "unresolved": 0,
        "unresolved_max": 0,
        # The signed gate prints reduced fractions; mirror that so the recomputation is comparable
        # string-for-string with the recorded blockers.
        "precision_line": str(precision),
        "recall_line": "20/20",
    }
    unknown = sorted(set(decisions) - {"M1", "M2", "M3"})
    if unknown:
        raise DecisionError(f"未知格：{unknown}")

    m1 = apply_m1(decisions["M1"], context) if "M1" in decisions else None
    m2 = apply_m2(decisions["M2"]) if "M2" in decisions else None
    m3 = apply_m3(decisions["M3"]) if "M3" in decisions else None
    blocks = [block for block in (m1, m2, m3) if block is not None]

    leaves: dict[str, Any] = {}
    for block in blocks:
        leaves.update(block.get("contract_leaves") or {})

    contract_v45 = _draft_contract(contract, leaves)
    gate_v4 = _draft_gate(gate, blocks, m1, context)
    release_enforced = bool(m2 and m2["selected"] == "exists")
    release_line = {
        "candidate_precision_min": contract["claims_thresholds"]["release_line_proposed"][
            "candidate_precision_min"
        ],
        "measured_candidate_precision": f"{numerator}/{denominator} = {float(precision):.4f}",
        "candidate_axis_passes": precision
        >= Fraction(
            str(contract["claims_thresholds"]["release_line_proposed"]["candidate_precision_min"])
        ),
        "per_source_precision_min": contract["claims_thresholds"]["release_line_proposed"].get(
            "target_recall_per_source_min"
        ),
        "measured_per_source_precision": gate["thresholds"]["release_line"][
            "measured_per_source_precision"
        ],
        "per_source_axis_enforced": release_enforced,
        "per_source_axis_passes": all(
            value
            >= Fraction(
                str(
                    contract["claims_thresholds"]["release_line_proposed"][
                        "target_recall_per_source_min"
                    ]
                )
            )
            for value in per_source_precision.values()
        ),
    }
    gate_v4["release_line"] = release_line
    # M1 is exactly the axis the 91-号 correction was registered for: once decided, the release line
    # is recomputed under the decided caliber (R3) and the precondition disappears.
    gate_v4["release_line"]["precondition"] = None
    gate_v4["release_line_note"] = (
        "M1 已裁定 ⇒ 按 R3 用新口径重算，91 号那处 'D-1 ≠ a' 前置条件由更正登记转为已消解"
        if m1
        else "M1 未裁定 ⇒ 该行仍须读作 pending_caliber（93 号 CORR-91-PRECONDITION）"
    )

    return {
        "schema_version": "claims-governance-application-1",
        "created_on": "2026-10-14",
        "zero_model_calls": True,
        "simulated": simulated,
        "decisions": decisions,
        "blocks": {block["cell"]: block for block in blocks},
        "contract_leaves": leaves,
        "contract_v45_draft": contract_v45,
        "gate_v4_draft": gate_v4,
        "measured": {
            "precision": f"{numerator}/{denominator} = {float(precision):.4f}",
            "per_source_precision": {
                source: str(value) for source, value in sorted(per_source_precision.items())
            },
            "accepted_records_total": pool_accepted_total,
            "accepted_records_per_source": per_source_accepted,
        },
        "regression": {
            "gate_v3_recorded_variant_a_blockers": variant_a["rate_blockers"],
            "recomputed_variant_a_blockers": evaluate_variant((40, 20), **context)["rate_blockers"],
        },
        "not_done": [
            "不代签：本件只产出 draft_pending_human_signature",
            "不改 88 号契约 / 91 号门 / 任何冻结件字节",
            "不执行 requires_separate_change 的工单项",
        ],
    }


def _draft_contract(contract: dict[str, Any], leaves: dict[str, Any]) -> dict[str, Any]:
    draft = json.loads(json.dumps(contract))
    draft["schema_version"] = "non-table-selected-target-scoring-contract-v4.5"
    draft["status"] = "draft_pending_human_signature"
    draft["supersedes"] = {
        "path": "evidence/88-claims-contract-v44-signed-20261014/r0-zero-call/scoring-contract-v4.4.json",
        "sha256": sha256(DEFAULT_CONTRACT_V44),
        "reason": "M1/M2/M3 三格裁定落地（只增叶子 + 一处命名缺陷更正）",
    }
    draft["signoff"] = {"signed_by": None, "signed_on": None}
    claims_section = draft.setdefault("role_sections", {}).setdefault("claims", {})
    release = draft["claims_thresholds"]["release_line_proposed"]
    defect_fixes: list[dict[str, Any]] = []
    if "target_recall_per_source_min" in release:
        # The signed v4.4 leaf is mis-named: it holds the per-source *precision* floor (0.55), which
        # collides with the target line's per-source recall name (0.80).
        release["per_source_precision_min"] = release.pop("target_recall_per_source_min")
        defect_fixes.append(
            {
                "leaf": "claims_thresholds.release_line_proposed.target_recall_per_source_min",
                "renamed_to": "claims_thresholds.release_line_proposed.per_source_precision_min",
                "reason": "该叶存的是分源精度下限（0.55），与目标线的分源召回同名，属命名缺陷",
                "value_preserved": 0.55,
            }
        )
    for path, value in leaves.items():
        parts = path.split(".")
        node: dict[str, Any] = draft
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    draft["_application"] = {
        "leaves_written": sorted(leaves),
        "defect_fixes": defect_fixes,
    }
    draft["_application"].update({"role_sections_claims_keys": sorted(claims_section)})
    return draft


def _accepted_floors(m1: dict[str, Any] | None) -> dict[str, Any]:
    """The target line's count floors after M1: the decided values, or diagnostic when c."""
    if m1 is None:
        return {}
    floors = m1["recomputed"]["floors"]
    if floors is None:
        return {
            "accepted_records_enforcement": "diagnostic",
            "accepted_records_total_min": None,
            "accepted_records_per_source_min": None,
        }
    return floors


def _draft_gate(
    gate: dict[str, Any],
    blocks: list[dict[str, Any]],
    m1: dict[str, Any] | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    draft: dict[str, Any] = {
        "schema_version": "claims-gate-v4-draft-1",
        "status": "draft_pending_human_signature",
        "role": "claims",
        "created_on": "2026-10-14",
        "zero_model_calls": True,
        "supersedes": {
            "path": "evidence/91-claims-gate-v3-signed-20261014/r0-zero-call/claims-gate-v3.json",
            "sha256": sha256(DEFAULT_GATE_V3),
        },
        "applied_cells": {block["cell"]: block["selected"] for block in blocks},
        "target_line": {
            **gate["thresholds"]["target_line"],
            # M1 is the axis that was unfrozen; the draft carries the decided floors, so the target
            # line no longer inherits the items' 40/20.
            **_accepted_floors(m1),
            "verdict": "FAIL" if not m1 or not m1["recomputed"]["rate_gate_passed"] else "PASS",
            "unreachable_registered": True,
            "note": "精度 0.6296 < 0.80 是硬结论；accepted 下限裁定不改变它",
        },
        "measured_run": {
            "accepted_records_total": context["accepted_total"],
            "accepted_records_per_source": context["accepted_per_source"],
            "selected_variant": None if m1 is None else m1["recomputed"],
        },
        "unfrozen_axes": [],
        "not_done": ["未签认；未改动 91 号任何字节"],
    }
    if m1 is not None:
        draft["measured_run"]["selected_variant"] = m1["recomputed"]
    return draft


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT_V44)
    parser.add_argument("--gate", type=Path, default=DEFAULT_GATE_V3)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--simulate", help="试算格=值，逗号分隔；只打印，不写盘、不计入决定")
    parser.add_argument("--apply", action="store_true", help="按已签决定写入 94 号产物")
    args = parser.parse_args(argv)

    plan = load_json(args.plan)
    contract = load_json(args.contract)
    gate = load_json(args.gate)

    if args.simulate:
        decisions = parse_simulation(args.simulate)
        simulated = True
    else:
        decisions = read_decisions(plan)
        simulated = False

    application = build_application(decisions, contract=contract, gate=gate, simulated=simulated)

    if not args.apply or simulated:
        print(json.dumps(application, ensure_ascii=False, indent=2))
        if simulated:
            print("[simulate] 未写盘、未计入决定。")
        else:
            print("[dry-run] 未写盘；加 --apply 落地。")
        return 0

    outputs = {
        "scoring-contract-v4.5.proposed.json": (
            json.dumps(application["contract_v45_draft"], ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
        "claims-gate-v4.proposed.json": (
            json.dumps(application["gate_v4_draft"], ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
        "governance-decision-application.json": (
            json.dumps(
                {key: value for key, value in application.items() if not key.endswith("_draft")},
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        ).encode("utf-8"),
    }
    manifest = {
        "schema_version": "claims-governance-application-manifest-1",
        "status": "draft",
        "created_on": "2026-10-14",
        "model_calls": 0,
        "inputs": {
            "governance_plan": sha256(args.plan),
            "signed_contract_v4.4": sha256(args.contract),
            "claims_gate_v3_signed": sha256(args.gate),
        },
        "outputs": {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()},
        "decision_signoff": plan.get("decision_signoff"),
    }
    outputs["MANIFEST.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )

    args.out.mkdir(parents=True, exist_ok=True)
    existing = [name for name in outputs if (args.out / name).exists()]
    if existing:
        raise DecisionError(f"refusing to overwrite existing outputs {existing}")
    for name, data in outputs.items():
        (args.out / name).write_bytes(data)
    print(f"wrote {len(outputs)} files to {args.out}")
    print(json.dumps(manifest["outputs"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
