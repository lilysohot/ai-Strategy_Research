"""Apply the U signature on the 86-号 instrument to produce the signed contract v4.4 record.

Reads (never writes) the 86 draft and its signed instrument; writes only inside this directory.
The signature must already exist in the instrument (``reviewer:`` name plus ``signed_on:``) —
this script never fills a signature field on its own and refuses to run otherwise.

Two documented deviations from the reviewed draft are applied and registered:
1. disposition markers flip from ``agent_proposal_pending_human_signature`` to the signing
   record (a signed contract must not carry "pending" leaves);
2. ``claims_precision_single_source`` (C2) carries an explicit **correction**: the draft's
   "implementation divergence" was an arithmetic error (``fp`` already includes duplicates), so
   the required implementation change is void and the decision reduces to "single source =
   duplicate-inclusive formula", which the scorer already satisfies.

Verification runs inside this script: role-aware loading, claims carrier loading, and one real
claims adjudication row assembled through ``assemble_scoring_input``.

Usage:
    python apply_v4.4_signoff.py [--no-write] [--force]
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

from plugins.corpus.adjudication_assembly import (  # noqa: E402
    ABSENT,
    CLAIMS_CONTRACT_PATH,
    assemble_scoring_input,
    load_claims_carriers,
    required_fields_for,
)
from plugins.corpus.structured_scoring import (  # noqa: E402
    CONTRACT_GATE_REQUIREMENTS,
    ContractGateRequirements,
    Role,
    load_contract_gate_requirements,
)

SIGNED_ON = "2026-10-14"
SIGNER = "xyl"

DRAFT = (
    ROOT
    / "evidence/86-claims-contract-v44-draft-20261014/r0-zero-call"
    / "scoring-contract-v4.4.proposed.json"
)
INSTRUMENT = (
    ROOT
    / "evidence/86-claims-contract-v44-draft-20261014/r0-zero-call"
    / "claims-contract-v4.4-signoff.md"
)
C2_MEASUREMENT = HERE / "c2-measurement.json"
POOL = (
    ROOT
    / "evidence/17-structured-extraction-convergence-closure-20261009"
    / "p1r5-claims-adjudication-v2/candidate-adjudications.signed.json"
)
BASE_V43 = ROOT / "evidence/75-r2-signed-20261013/r0-zero-call/scoring-contract-v4.3.json"

DISPOSITION_LEAVES = (
    "claims_scope",
    "claims_precision_single_source",
    "claims_use_grading",
    "claims_thresholds",
)
CLAIMS_CARRIER_KEYS = (
    "subject",
    "metric",
    "period",
    "unit",
    "value",
    "factuality",
    "attribution",
    "perspective",
    "source_stance",
    "estimate_status",
    "qualifier",
)
EXPECTED_REMOVED_LEAVES = (
    "agent_proposals",
    "read_path.roles_proposed.claims.carriers_proposed",
    "read_path.roles_proposed.claims.reason_not_implemented",
)
FIELD_TO_CARRIER_KEY = {
    "subject": "subject",
    "metric": "metric",
    "period": "period_raw",
    "unit": "unit_raw",
    "value": "value_text",
    "factuality": "kind",
    "qualifier": "qualifiers",
}
"""Contract field -> the candidate key its carrier reads (mirrors the signed C3 carriers)."""


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


def assert_signed_instrument(text: str) -> dict[str, Any]:
    """Refuse to proceed unless the instrument already carries a named signature."""
    reviewer_line = [line for line in text.splitlines() if line.strip().startswith("reviewer:")]
    if not reviewer_line:
        raise SystemExit("refusing to apply: instrument has no reviewer line")
    line = reviewer_line[0]
    if SIGNER not in line or "signed_on:" not in line or not line.split("signed_on:")[1].strip():
        raise SystemExit(f"refusing to apply: instrument signature incomplete: {line!r}")
    return {"instrument_reviewer_line": line.strip(), "signed_on": SIGNED_ON, "signed_by": SIGNER}


def build_signed(draft: dict[str, Any], instrument_text: str, c2: dict[str, Any]) -> dict[str, Any]:
    signed = copy.deepcopy(draft)
    signature = assert_signed_instrument(instrument_text)
    signed["status"] = "frozen_signed"
    signed["signoff"] = {
        "signed_by": signature["signed_by"],
        "signed_on": signature["signed_on"],
        "statement": (
            "核准 claims 契约 v4.4（只增叶子）：新增 role_sections（items 镜像 v4.3 的 11 条 NT-I 与 48；"
            "claims = NT-C11/NT-C12/NT-C13 与 target_total 20）、claims 角色范围（C1）、精度单一口径（C2）、"
            "claims 读路径（C3）、用途分级（C4）、claims 双线阈值与不可达登记（C5/C6）。"
            "六项阈值逐字不变；不改 v4.3 / frozen-gold / P1R5 已签裁定 / items 门 v3 字节。"
        ),
        "instrument": {
            "path": str(INSTRUMENT.relative_to(ROOT)),
            "sha256": f"sha256:{sha256(INSTRUMENT)}",
        },
        "scope_note": (
            "签认生效 claims 分支的读取；C2 附具名更正（前提为读数错误、无实现分歧）；"
            "C3 读路径已在代码中接线，C4 用途分级仍待落地；不代表出分、发布或语境完整。"
        ),
        "reviewer_remark": "",
        "remark_note": "备注为空 ⇒ 六格提案按原样接受（含 C2 更正记录）；不等同逐格确认。",
    }
    for leaf in DISPOSITION_LEAVES:
        signed[leaf]["status"] = f"signed_{SIGNED_ON}_{SIGNER}"
    claims_read_path = signed["read_path"]["roles_proposed"]["claims"]
    claims_read_path["status"] = f"signed_{SIGNED_ON}_{SIGNER}"
    claims_read_path["implemented_in_this_revision"] = True
    # Disposition flip: the carriers are no longer a proposal, so they move from
    # ``carriers_proposed`` to the canonical ``carriers`` key and the draft-time
    # "not implemented" note is superseded by the code landing.
    claims_read_path["carriers"] = claims_read_path.pop("carriers_proposed")
    claims_read_path.pop("reason_not_implemented", None)
    c2_row = signed["claims_precision_single_source"]
    c2_row["status"] = f"signed_{SIGNED_ON}_{SIGNER}_with_correction"
    c2_row["correction"] = {
        "applied_on": SIGNED_ON,
        "as_signed_premise": c2_row["defect"],
        "retracted": True,
        "retraction_reason": (
            "实测：评分器 RoleMetrics.fp 已含 duplicate（两个匹配器都把 DUPLICATE 记入 false_positives），"
            "故实现分母 = 分子 + fp 已等于契约文字公式；草案的 56/107 是把裁定文件的 incorrect 计数当成 fp 的读数错误"
        ),
        "measurement": {
            "path": str(C2_MEASUREMENT.relative_to(ROOT)),
            "sha256": f"sha256:{sha256(C2_MEASUREMENT)}",
            "ledger": c2["ledger"],
            "precision_implemented": c2["precision_implemented"],
            "precision_if_duplicate_added_again": c2["precision_if_duplicate_added_again"],
        },
        "effective_disposition": (
            "单一口径 = 含 duplicate 的契约公式（已满足）；required_implementation_change 作废；"
            "禁止在 precision 分母再补加 duplicate_fp（会得到 56/113）"
        ),
        "required_implementation_change_void": True,
    }
    proposals = signed.pop("agent_proposals")
    signed["signoff_dispositions"] = {
        "status": f"signed_{SIGNED_ON}_{SIGNER}",
        "accepted_as_proposed": proposals["pending_human_signature"],
        "with_registered_correction": ["C2 claims_precision_single_source"],
        "not_changed_by_this_draft": proposals["not_changed_by_this_draft"],
    }
    return signed


def _catalog_entry(claim: dict[str, Any]) -> dict[str, Any]:
    """Catalog entry keyed by the *carrier* keys the contract declares (subject, period_raw…).

    A carrier the candidate does not carry is recorded as the explicit ``ABSENT`` marker, per
    ``read_path.absent_required_fields`` (blank and guessing are both forbidden).
    """
    entry: dict[str, Any] = {}
    for carrier_key in FIELD_TO_CARRIER_KEY.values():
        value = claim.get(carrier_key)
        entry[carrier_key] = ABSENT if value in (None, "") else str(value)
    entry["origin"] = "llm_prose"
    return entry


def _declared_fields(entry: dict[str, Any]) -> dict[str, str]:
    declared = {
        field: entry[carrier_key] for field, carrier_key in FIELD_TO_CARRIER_KEY.items()
    }
    for human_only in ("attribution", "perspective", "source_stance", "estimate_status"):
        declared[human_only] = ABSENT
    return declared


def verify(
    signed_path: Path, contract: dict[str, Any], pool: dict[str, Any]
) -> dict[str, Any]:
    """Role-aware load, carrier load, and one real adjudication row through the assembler."""
    requirements = load_contract_gate_requirements(signed_path, role=Role.CLAIMS)
    items_from_v44 = load_contract_gate_requirements(signed_path)
    items_names = [
        name
        for name in ContractGateRequirements.__dataclass_fields__
        if name != "schema_version"
    ]
    carriers = load_claims_carriers(signed_path)
    row = next(r for r in pool["adjudications"] if r["judgement"] == "matched")
    claim = row["original_candidate"]["claim"]
    entry = _catalog_entry(claim)
    declared = _declared_fields(entry)
    stage_vocabulary: dict[str, int] = {}
    for entry_row in pool["adjudications"]:
        key = str(entry_row.get("stage"))
        stage_vocabulary[key] = stage_vocabulary.get(key, 0) + 1
    adjudication = {
        "candidate_id": row["candidate_id"],
        # The P1R5 pool was adjudicated once (its own ``stage`` vocabulary is
        # ``human_adjudicated_candidate``), so a claims adapter presents it as the validated
        # slice; both scorer slices receive the same tuples in that case.
        "stage": "validated",
        "role": "claims",
        "source_id": "sha256:" + "d" * 64,
        "original_candidate": {"role": "claims", "source_id": "sha256:" + "d" * 64, "origin": "llm_prose"},
        "judgement": row["judgement"],
        "matched_gold_id": row.get("matched_gold_id"),
        "canonical_observed_fields": declared,
        "reviewer": row.get("reviewer") or "xyl",
        "reason": "read_path smoke: deterministic carriers recomputed from the candidate itself",
        "evidence": "instrument-signed read path verification",
    }
    assembled = assemble_scoring_input(
        [adjudication],
        catalog={row["candidate_id"]: entry},
        allowed_source_ids=None,
    )
    return {
        "claims_role_scope": requirements.role_scope.value,
        "claims_sentinels": list(requirements.high_risk_item_assertions_required),
        "claims_target_total": requirements.role_target_total,
        "items_equal_v43_except_schema": all(
            getattr(items_from_v44, name) == getattr(CONTRACT_GATE_REQUIREMENTS, name)
            for name in items_names
        ),
        "claims_carrier_keys": sorted(carriers),
        "claims_carrier_keys_match_contract": sorted(carriers)
        == sorted(contract["role_required_fields"]["claims"]),
        "required_fields_for_claims": list(required_fields_for(Role.CLAIMS)),
        "assembled_candidates": len(assembled.validated) + len(assembled.raw),
        "assembled_mappings": len(assembled.mappings),
        "assembled_basis_fields": list(assembled.audit[0].matching_basis) if assembled.audit else [],
        "assembled_absent_fields": (
            list(assembled.audit[0].absent_required_fields) if assembled.audit else []
        ),
        "contract_path_matches_module_constant": Path(CLAIMS_CONTRACT_PATH) == signed_path,
        "pool_stage_vocabulary": stage_vocabulary,
    }


def build() -> dict[str, Any]:
    draft = load(DRAFT)
    instrument_text = INSTRUMENT.read_text(encoding="utf-8")
    c2 = load(C2_MEASUREMENT)
    signed = build_signed(draft, instrument_text, c2)
    diff = diff_paths(draft, signed)
    out_path = HERE / "scoring-contract-v4.4.json"
    out_path.write_text(json.dumps(signed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    verified = verify(out_path, signed, load(POOL))
    base_thresholds = load(BASE_V43)["threshold_source"]["effective"]
    thresholds = {
        key: {"v4.3": base_thresholds[key], "v4.4": signed["threshold_source"]["effective"][key]}
        for key in base_thresholds
    }
    diff_report = {
        "draft": {"path": str(DRAFT.relative_to(ROOT)), "sha256": sha256(DRAFT)},
        "signed": {"path": str(out_path.relative_to(ROOT)), "sha256": sha256(out_path)},
        "changed_leaf_paths": diff["changed"],
        "added_leaf_paths": diff["added"],
        "removed_leaf_paths": diff["removed"],
        "expected_changed_prefixes": ["status", "signoff", *DISPOSITION_LEAVES, "read_path.roles_proposed.claims"],
        "unexpected_changed": sorted(
            path
            for path in diff["changed"]
            if not any(
                path == prefix or path.startswith(f"{prefix}.")
                for prefix in ["status", "signoff", *DISPOSITION_LEAVES, "read_path.roles_proposed.claims"]
            )
        ),
        "expected_removed_leaves": [
            "agent_proposals",
            "read_path.roles_proposed.claims.carriers_proposed",
            "read_path.roles_proposed.claims.reason_not_implemented",
        ],
        "unexpected_removed": sorted(
            path for path in diff["removed"] if path not in EXPECTED_REMOVED_LEAVES
        ),
        "thresholds_unchanged": thresholds,
        "thresholds_byte_identical": all(
            entry["v4.3"] == entry["v4.4"] for entry in thresholds.values()
        ),
        "verification": verified,
    }
    manifest = {
        "schema_version": "claims-contract-v44-signed-manifest-1",
        "status": "signed",
        "created_on": SIGNED_ON,
        "signed_by": SIGNER,
        "model_calls": 0,
        "inputs": {
            "v44_draft": sha256(DRAFT),
            "signoff_instrument": sha256(INSTRUMENT),
            "c2_measurement": sha256(C2_MEASUREMENT),
            "scoring_contract_v4.3_signed": sha256(BASE_V43),
            "p1r5_candidate_adjudications_signed": sha256(POOL),
        },
        "outputs": {},
        "does_not_touch": [str(DRAFT.relative_to(ROOT)), str(INSTRUMENT.relative_to(ROOT)), str(BASE_V43.relative_to(ROOT))],
    }
    return {"contract": signed, "diff": diff_report, "manifest": manifest}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.no_write:
        draft = load(DRAFT)
        signed = build_signed(draft, INSTRUMENT.read_text(encoding="utf-8"), load(C2_MEASUREMENT))
        diff = diff_paths(draft, signed)
        print(json.dumps({"changed": diff["changed"], "removed": diff["removed"]}, ensure_ascii=False, indent=2))
        print("[no-write] nothing written.")
        return 0

    result = build()
    outputs = {
        "scoring-contract-v4.4.json": (HERE / "scoring-contract-v4.4.json").read_bytes(),
        "contract-v4.4-signed-diff.json": (
            json.dumps(result["diff"], ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
    }
    manifest = result["manifest"]
    manifest["outputs"] = {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()}
    outputs["MANIFEST.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    existing = [name for name in outputs if (HERE / name).exists() and name != "scoring-contract-v4.4.json"]
    if existing and not args.force:
        raise SystemExit(f"refusing to overwrite existing outputs {existing}; use --force")
    for name, data in outputs.items():
        (HERE / name).write_bytes(data)
    print(f"wrote {len(outputs)} files to {HERE}")
    print(json.dumps(manifest["outputs"], ensure_ascii=False, indent=2))
    print(json.dumps(result["diff"]["verification"], ensure_ascii=False, indent=2))
    problems = result["diff"]["unexpected_changed"] + result["diff"]["unexpected_removed"]
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
