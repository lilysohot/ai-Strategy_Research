"""Build the 94 号 preflight record: the branch matrix, computed but *not* applied.

The governance cells are unsigned, so nothing may be decided and nothing may be written as a
decision. This script therefore exercises every branch of ``apply_claims_governance_decisions`` in
simulation mode and records:

* what each branch would write (contract leaves, landing class, work order);
* that the recomputation reproduces the signed gate v3 variant blockers string-for-string;
* that ``--apply`` on the unsigned 93 号 record is refused.

Nothing here is a decision, and no draft is produced: the record exists so that, the moment the
cells are signed, the "one-click" run is already known to work for that branch.

Usage:
    python build_preflight_record.py [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = HERE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from tools.apply_claims_governance_decisions import (  # noqa: E402
    DEFAULT_CONTRACT_V44,
    DEFAULT_GATE_V3,
    DEFAULT_PLAN,
    DecisionError,
    build_application,
    load_json,
    read_decisions,
    sha256,
)

RECORD_ON = "2026-10-14"


def _branches() -> list[dict[str, str]]:
    matrix: list[dict[str, str]] = []
    for m1 in ("a_transplant", "b_scaled_floor", "b_scaled_ceil", "c_diagnostic"):
        matrix.append({"M1": m1, "M2": "report_only", "M3": "O1_status_quo"})
    matrix.append({"M1": "b_scaled_floor", "M2": "exists", "M3": "O1_status_quo"})
    matrix.append({"M1": "b_scaled_floor", "M2": "report_only", "M3": "O2_remap_two_codes"})
    matrix.append({"M1": "b_scaled_floor", "M2": "report_only", "M3": "O3_extend_vocabulary"})
    return matrix


def build() -> dict[str, Any]:
    contract = load_json(DEFAULT_CONTRACT_V44)
    gate = load_json(DEFAULT_GATE_V3)
    plan = load_json(DEFAULT_PLAN)

    try:
        read_decisions(plan)
        refusal = "NOT REFUSED (unexpected: the 93 号 record is unsigned)"
        refused = False
    except DecisionError as exc:
        refusal = str(exc)
        refused = True

    rows = []
    for decisions in _branches():
        application = build_application(decisions, contract=contract, gate=gate, simulated=True)
        m1 = application["blocks"].get("M1", {}).get("recomputed")
        rows.append(
            {
                "decisions": decisions,
                "contract_leaves": application["contract_leaves"],
                "landing": {
                    cell: {
                        "code_landing": block["code_landing"],
                        "requires_new_signature": block.get("requires_new_signature"),
                        "blocked_on": block.get("blocked_on"),
                    }
                    for cell, block in application["blocks"].items()
                },
                "m1_recomputed": m1,
                "release_line": {
                    "precondition": application["gate_v4_draft"]["release_line"]["precondition"],
                    "note": application["gate_v4_draft"]["release_line_note"],
                    "per_source_axis_enforced": application["gate_v4_draft"]["release_line"][
                        "per_source_axis_enforced"
                    ],
                },
                "regression_match": application["regression"]["recomputed_variant_a_blockers"]
                == application["regression"]["gate_v3_recorded_variant_a_blockers"],
            }
        )

    return {
        "schema_version": "claims-governance-preflight-1",
        "created_on": RECORD_ON,
        "zero_model_calls": True,
        "status": "simulation_only_no_decision",
        "purpose": (
            "把‘签认后一键执行’在三个格子的每个分支上先跑通并留证：真跑时只需 --apply；"
            "本记录不含任何裁定，也未产出任何 draft。"
        ),
        "authority": {
            "plan": {"path": str(DEFAULT_PLAN.relative_to(ROOT)), "sha256": sha256(DEFAULT_PLAN)},
            "contract_v4.4_signed": {
                "path": str(DEFAULT_CONTRACT_V44.relative_to(ROOT)),
                "sha256": sha256(DEFAULT_CONTRACT_V44),
            },
            "gate_v3_signed": {
                "path": str(DEFAULT_GATE_V3.relative_to(ROOT)),
                "sha256": sha256(DEFAULT_GATE_V3),
            },
        },
        "apply_refusal_on_unsigned_record": {"refused": refused, "reason": refusal},
        "tool": {
            "path": "tools/apply_claims_governance_decisions.py",
            "entry_points": {
                "simulate": "--simulate M1=...,M2=...,M3=...（只打印，不写盘）",
                "apply": "--apply（需已签决定记录；写 draft_pending_human_signature 产物）",
            },
        },
        "branches": rows,
        "tool_outputs_on_apply": [
            "scoring-contract-v4.5.proposed.json",
            "claims-gate-v4.proposed.json",
            "governance-decision-application.json",
            "MANIFEST.json",
        ],
        "not_done": [
            "未产出任何 draft（三格未签认）",
            "未改动 88 号契约 / 91 号门 / 任何冻结件字节",
            "不代签；签认后由 U 触发 --apply",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="允许覆盖本目录内已存在的输出")
    args = parser.parse_args()

    record = build()
    outputs = {
        "preflight-record.json": (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        )
    }
    manifest = {
        "schema_version": "claims-governance-preflight-manifest-1",
        "status": "simulation_only_no_decision",
        "created_on": RECORD_ON,
        "model_calls": 0,
        "inputs": {
            "governance_plan": sha256(DEFAULT_PLAN),
            "signed_contract_v4.4": sha256(DEFAULT_CONTRACT_V44),
            "claims_gate_v3_signed": sha256(DEFAULT_GATE_V3),
        },
        "outputs": {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()},
        "touched_code": [
            "tools/apply_claims_governance_decisions.py",
            "tests/test_claims_governance_apply.py",
            "plugins/corpus/structured_scoring.py",
            "tests/test_claims_contract_role.py",
        ],
        "does_not_touch": [
            "evidence/93-claims-governance-plan-20261014/**",
            "evidence/88-claims-contract-v44-signed-20261014/**",
            "evidence/91-claims-gate-v3-signed-20261014/**",
        ],
    }
    outputs["MANIFEST.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )

    existing = [name for name in outputs if (HERE / name).exists()]
    if existing and not args.force:
        raise SystemExit(f"refusing to overwrite existing outputs {existing}; use --force")
    for name, data in outputs.items():
        (HERE / name).write_bytes(data)
    print(f"wrote {len(outputs)} files to {HERE}")
    print(json.dumps(manifest["outputs"], ensure_ascii=False, indent=2))
    print(
        f"apply-refused-on-unsigned-record: {record['apply_refusal_on_unsigned_record']['refused']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
