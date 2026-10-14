"""Apply the U signature on the 90-号 instrument to produce the signed claims gate v3 record.

Reads (never writes) the 90 draft gate and its signed instrument; writes only inside this
directory. The signature must already exist in the instrument (a named ``reviewer:`` plus a
non-empty ``signed_on:``) — this script never fills a signature field on its own.

What the signature does and does not cover (registered explicitly, because the instrument's
section 三 was left unwritten):

* **Covered**: the caliber definitions, the dual threshold bookkeeping, the measured run, and the
  terminal verdict on the target line (FAIL, registered unreachable).
* **Not covered**: D-1 (accepted total/per-source floors) and D-2 (a per-source precision axis).
  They stay ``pending_human_decision``; the release line's verdict is therefore stated with its
  precondition spelled out, and the target-line verdict is proven variant-independent.

Status mirrors the items gate convention: ``frozen_before_execution`` + ``countersignature``,
with ``unfrozen_axes`` naming exactly what was not frozen.

Usage:
    python apply_gate_v3_signoff.py [--no-write] [--force]
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

from tools.check_claims_gate import Inputs, run_checks  # noqa: E402

SIGNED_ON = "2026-10-14"
SIGNER = "xyl"

DRAFT = (
    ROOT
    / "evidence/90-claims-gate-v3-and-run-20261014/r0-zero-call/claims-gate-v3.proposed.json"
)
DRAFT_MANIFEST = (
    ROOT / "evidence/90-claims-gate-v3-and-run-20261014/r0-zero-call/MANIFEST.json"
)
INSTRUMENT = (
    ROOT / "evidence/90-claims-gate-v3-and-run-20261014/r0-zero-call/claims-gate-v3-signoff.md"
)
SIGNED_CONTRACT = (
    ROOT
    / "evidence/88-claims-contract-v44-signed-20261014/r0-zero-call/scoring-contract-v4.4.json"
)
ITEMS_GATE_V3 = ROOT / "evidence/75-r2-signed-20261013/r0-zero-call/gate-v3.json"

INPUTS = {
    "claims_gate_v3_draft": DRAFT,
    "claims_gate_v3_draft_manifest": DRAFT_MANIFEST,
    "signoff_instrument": INSTRUMENT,
    "signed_scoring_contract_v4.4": SIGNED_CONTRACT,
    "items_gate_v3_signed_reference": ITEMS_GATE_V3,
}
EXPECTED_REMOVED = ("signoff",)
EXPECTED_ADDED = (
    "candidate_pool",
    "countersignature",
    "reporting_scope",
    "unfrozen_axes",
    "unfrozen_axes_note",
    "verdict",
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


def assert_signed_instrument(text: str) -> str:
    line = next((ln.strip() for ln in text.splitlines() if ln.strip().startswith("reviewer:")), "")
    if not line or SIGNER not in line or "signed_on:" not in line:
        raise SystemExit(f"refusing to apply: instrument has no named signature: {line!r}")
    if not line.split("signed_on:")[1].strip():
        raise SystemExit("refusing to apply: instrument signature has no date")
    return line


def verdict_of(variants: dict[str, Any], target_precision_min: float, release: dict[str, Any]) -> dict[str, Any]:
    target_fails = [name for name, value in variants.items() if not value["rate_gate_passed"]]
    precision_blocked = [
        name
        for name, value in variants.items()
        if any("candidate_precision" in blocker for blocker in value["rate_blockers"])
    ]
    floors_only_blocked = [
        name
        for name, value in variants.items()
        if value["rate_blockers"] and not any(
            "candidate_precision" in blocker for blocker in value["rate_blockers"]
        )
    ]
    return {
        "target_line": {
            "candidate_precision_min": target_precision_min,
            "verdict": "FAIL",
            "unreachable_registered": True,
            "variant_independence": {
                "fails_in_every_variant": len(target_fails) == len(variants),
                "blocked_on_precision_in_every_variant": len(precision_blocked) == len(variants),
                "variants": sorted(variants),
            },
            "note": "精度 0.6296 < 0.80 在所有 accepted 下限变体下都成立 ⇒ 目标线判定与 D-1 无关",
        },
        "release_line": {
            "candidate_precision_min": release["candidate_precision_min"],
            "per_source_precision_min": release["per_source_precision_min"],
            "verdict": (
                "PASS"
                if release["candidate_axis_passes"] and release["per_source_axis_passes"]
                else "FAIL"
            ),
            "precondition": "D-1 ≠ a（若取 a，放行线另受 accepted 下限 3 项阻断）",
            "per_source_axis_status": "报告项；六项里无该轴，D-2 未裁前不参与 gating",
            "not_a_quality_claim": "放行线是功能线：通过不等于质量达标",
        },
        "floors_only_blocked_variants": floors_only_blocked,
        "measured_run_ref": {
            "path": "evidence/90-claims-gate-v3-and-run-20261014/r0-zero-call/claims-run-record.json",
            "sha256": f"sha256:{sha256(DRAFT.parent / 'claims-run-record.json')}",
        },
    }


def build(verify_path: Path | None = None) -> dict[str, Any]:
    draft = load(DRAFT)
    instrument_text = INSTRUMENT.read_text(encoding="utf-8")
    signature_line = assert_signed_instrument(instrument_text)
    signed = copy.deepcopy(draft)
    signed["status"] = "frozen_before_execution"
    signed["unfrozen_axes"] = [
        "accepted_records_total_min",
        "accepted_records_per_source_min",
        "per_source_precision_axis",
    ]
    signed["unfrozen_axes_note"] = (
        "签认覆盖口径、双线登记、实测与目标线终态；D-1（accepted 下限）与 D-2（分源精度轴）"
        "在签认件的第三节留白，未被签认填入 ⇒ 保持 pending_human_decision"
    )
    original_signoff = signed.pop("signoff")
    signed["candidate_pool"] = (signed.get("measured_run") or {}).get("pool", {})
    signed["countersignature"] = {
        "required": True,
        "status": "signed",
        "reviewer": SIGNER,
        "signed_on": SIGNED_ON,
        "instrument": {
            "path": str(INSTRUMENT.relative_to(ROOT)),
            "sha256": f"sha256:{sha256(INSTRUMENT)}",
            "signature_line": signature_line,
        },
        "statement": (
            "核准 claims 门 v3：口径（C1–C4 已签契约）、双线阈值登记、110 条全量实测与目标线"
            "『不可达』终态。第三节两项（D-1 accepted 下限、D-2 分源精度轴）留白 ⇒ 不视为已决。"
        ),
        "scope_note": (
            "签认不改变任何冻结字节；不代表发布、query/delivery/context_use 或语境完整；"
            "放行线通过不构成质量达标声明"
        ),
        "draft_signoff_replaced": original_signoff,
    }
    signed["reporting_scope"] = {
        "role": "claims",
        "candidate_pool": "P1R5 冻结池（110 条，src 2026-10-09）",
        "caliber_in_force": "C1 角色范围（in_role_only）+ C2 单一口径（fp 含 duplicate）",
        "what_the_run_is": "已签契约阈值下对冻结池的全量评分；非新抽取、非新裁定",
        "what_the_run_is_not": "不是新池质量、不是整篇覆盖、不是生产可用",
    }
    signed["verdict"] = verdict_of(
        signed["measured_run"]["variants"],
        signed["thresholds"]["target_line"]["candidate_precision_min"],
        signed["thresholds"]["release_line"],
    )
    for decision in signed.get("open_decisions") or []:
        decision["status"] = "pending_human_decision"
        decision["signature_did_not_decide"] = True
    diff = diff_paths(draft, signed)
    payload = json.dumps(signed, ensure_ascii=False, indent=2) + "\n"
    out_path = verify_path or (HERE / "claims-gate-v3.json")
    out_path.write_text(payload, encoding="utf-8")
    signed_digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    checks = run_checks(Inputs(gate=out_path, manifest=DRAFT_MANIFEST))
    blocking = [c.check_id for c in checks if c.blocking and c.verdict == "fail"]
    divergences = [c.check_id for c in checks if c.verdict == "divergence"]
    diff_report = {
        "draft": {"path": str(DRAFT.relative_to(ROOT)), "sha256": sha256(DRAFT)},
        "signed": {
            "path": str((HERE / "claims-gate-v3.json").relative_to(ROOT)),
            "sha256": f"sha256:{signed_digest}",
        },
        "changed_leaf_paths": diff["changed"],
        "added_leaf_paths": diff["added"],
        "removed_leaf_paths": diff["removed"],
        "expected_changed_prefixes": ["status", "open_decisions", "thresholds"],
        "expected_removed": list(EXPECTED_REMOVED),
        "expected_added": list(EXPECTED_ADDED),
        "unexpected_changed": sorted(
            path
            for path in diff["changed"]
            if not any(
                path == prefix or path.startswith(f"{prefix}.")
                for prefix in ("status", "open_decisions", "thresholds")
            )
        ),
        "unexpected_removed": sorted(
            path for path in diff["removed"] if path not in EXPECTED_REMOVED
        ),
        "unexpected_added": sorted(
            path
            for path in diff["added"]
            if path.split(".")[0].split("[")[0] not in EXPECTED_ADDED
        ),
        "conformance": {
            "check_count": len(checks),
            "blocking_failures": blocking,
            "divergences": divergences,
            "verdict": "pass" if not blocking else "fail",
        },
        "verdict": signed["verdict"],
    }
    manifest = {
        "schema_version": "claims-gate-v3-signed-manifest-1",
        "status": "signed",
        "created_on": SIGNED_ON,
        "signed_by": SIGNER,
        "model_calls": 0,
        "inputs": {name: sha256(path) for name, path in INPUTS.items()},
        "outputs": {},
        "does_not_touch": [str(DRAFT.relative_to(ROOT)), str(INSTRUMENT.relative_to(ROOT))],
    }
    return {"gate": signed, "diff": diff_report, "manifest": manifest}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.no_write:
        with tempfile.TemporaryDirectory() as tmp:
            result = build(verify_path=Path(tmp) / "claims-gate-v3.json")
        print(json.dumps(result["diff"]["verdict"], ensure_ascii=False, indent=2))
        print(json.dumps(result["diff"]["conformance"], ensure_ascii=False, indent=2))
        print("[no-write] nothing written.")
        return 0

    result = build()
    outputs = {
        "claims-gate-v3.json": (HERE / "claims-gate-v3.json").read_bytes(),
        "gate-v3-signed-diff.json": (
            json.dumps(result["diff"], ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
    }
    manifest = result["manifest"]
    manifest["outputs"] = {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()}
    outputs["MANIFEST.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    existing = [
        name
        for name in ("gate-v3-signed-diff.json", "MANIFEST.json")
        if (HERE / name).exists()
    ]
    if existing and not args.force:
        raise SystemExit(f"refusing to overwrite existing outputs {existing}; use --force")
    for name, data in outputs.items():
        (HERE / name).write_bytes(data)
    print(f"wrote {len(outputs)} files to {HERE}")
    print(json.dumps(manifest["outputs"], ensure_ascii=False, indent=2))
    print(json.dumps(result["diff"]["verdict"], ensure_ascii=False, indent=2))
    problems = (
        result["diff"]["unexpected_changed"]
        + result["diff"]["unexpected_removed"]
        + result["diff"]["unexpected_added"]
        + result["diff"]["conformance"]["blocking_failures"]
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
