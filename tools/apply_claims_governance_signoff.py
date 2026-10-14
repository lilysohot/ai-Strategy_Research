"""Materialise a human-signed governance instrument into a machine-readable signed record.

The 93-号 instrument is signed *by a human* on the Markdown signoff sheet. Nothing here signs
anything: it only reads the three filled slots and the signature line, validates them, and writes a
**new** signed plan record. The instrument and the 93-号 plan are never modified -- the signature
lands as a separate artifact, exactly as the 86 号 -> 88 号 flow did for contract v4.4.

Instrument format expected (see ``claims-governance-signoff.md``)::

    M1 = b_scaled_floor
    M2 = report_only
    M3 = O1_status_quo

    reviewer: xyl    adjudicator: xyl    signed_on: 2026-10-14

Refusals: a blank or unknown slot value, a blank signature field, a missing slot, or an attempt to
overwrite an existing output.

Usage:
    uv run python tools/apply_claims_governance_signoff.py                 # dry run
    uv run python tools/apply_claims_governance_signoff.py --apply         # write the signed plan
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRATCH = REPO_ROOT / ".scratch/claims-r2-role-isolation"

DEFAULT_INSTRUMENT = (
    SCRATCH
    / "evidence/93-claims-governance-plan-20261014/r0-zero-call/claims-governance-signoff.md"
)
DEFAULT_PLAN = (
    SCRATCH / "evidence/93-claims-governance-plan-20261014/r0-zero-call/claims-governance-plan.json"
)
DEFAULT_OUT = SCRATCH / "evidence/96-claims-governance-signed-20261014/r0-zero-call"

SLOT_PATTERN = re.compile(r"^\s*(M[123])\s*=\s*(\S+)\s*(?:#.*)?$", re.MULTILINE)
SIGNATURE_PATTERN = re.compile(r"reviewer:\s*(\S+)\s+adjudicator:\s*(\S+)\s+signed_on:\s*(\S+)")
BLANK_CHARS = set("_-")


class SignoffError(RuntimeError):
    """Raised when the instrument is unsigned, blank or carries an unknown value."""


def is_blank(value: str) -> bool:
    return not value or set(value) <= BLANK_CHARS


def parse_instrument(text: str) -> dict[str, Any]:
    slots = {name: value for name, value in SLOT_PATTERN.findall(text)}
    missing = sorted({"M1", "M2", "M3"} - set(slots))
    if missing:
        raise SignoffError(f"签认件缺少格位 {missing}（须写成 `M1 = <值>` 形式）")
    blanks = sorted(name for name, value in slots.items() if is_blank(value))
    if blanks:
        raise SignoffError(f"格位 {blanks} 仍为空白（`____`）⇒ 未签，拒绝物化")

    signature = SIGNATURE_PATTERN.search(text)
    if signature is None:
        raise SignoffError("找不到签名行（须为 `reviewer: X    adjudicator: Y    signed_on: Z`）")
    reviewer, adjudicator, signed_on = signature.groups()
    blank_fields = [
        name
        for name, value in (
            ("reviewer", reviewer),
            ("adjudicator", adjudicator),
            ("signed_on", signed_on),
        )
        if is_blank(value)
    ]
    if blank_fields:
        raise SignoffError(f"签名栏未填：{blank_fields} ⇒ 拒绝物化")
    if slots["M1"] not in M1_VALUES_ALLOWED:
        raise SignoffError(f"M1 取值未知：{slots['M1']!r}（可选 {M1_VALUES_ALLOWED}）")
    if slots["M2"] not in M2_VALUES_ALLOWED:
        raise SignoffError(f"M2 取值未知：{slots['M2']!r}（可选 {M2_VALUES_ALLOWED}）")
    if slots["M3"] not in M3_VALUES_ALLOWED:
        raise SignoffError(f"M3 取值未知：{slots['M3']!r}（可选 {M3_VALUES_ALLOWED}）")
    return {
        "decisions": {name: slots[name] for name in ("M1", "M2", "M3")},
        "signoff": {"reviewer": reviewer, "adjudicator": adjudicator, "signed_on": signed_on},
        "signature_line": signature.group(0).strip(),
    }


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Kept in sync with tools/apply_claims_governance_decisions.py; duplicated deliberately so this
# module can refuse an unknown value without importing the executor.
M1_VALUES_ALLOWED = ("a_transplant", "b_scaled_floor", "b_scaled_ceil", "c_diagnostic")
M2_VALUES_ALLOWED = ("exists", "report_only")
M3_VALUES_ALLOWED = ("O1_status_quo", "O2_remap_two_codes", "O3_extend_vocabulary")


def build_signed_plan(
    plan: dict[str, Any],
    parsed: dict[str, Any],
    *,
    plan_sha: str,
    instrument_sha: str,
    instrument_relative: str,
) -> dict[str, Any]:
    signed = json.loads(json.dumps(plan))
    signed["status"] = "signed"
    signed["decision_signoff"] = {
        **parsed["signoff"],
        "instrument": {
            "path": instrument_relative,
            "sha256": instrument_sha,
            "signature_line": parsed["signature_line"],
        },
        "scope": "M1/M2/M3 三格取值（R1-R4 规则随 93 号签署一并生效）",
    }
    for cell in signed["cells"]:
        cell_id = cell["id"]
        if cell_id not in parsed["decisions"]:
            continue
        cell["status"] = "decided"
        cell["value"] = parsed["decisions"][cell_id]
        cell["decided_on"] = parsed["signoff"]["signed_on"]
        cell["pending_caliber"] = False
        cell["decided_by"] = parsed["signoff"]["reviewer"]
    signed["rules_in_force"]["status"] = "signed"
    signed["rules_in_force"]["signed_on"] = parsed["signoff"]["signed_on"]
    signed["rules_in_force"]["signed_by"] = parsed["signoff"]["reviewer"]
    signed["_materialised_from"] = {
        "plan": "evidence/93-claims-governance-plan-20261014/r0-zero-call/claims-governance-plan.json",
        "plan_sha256": plan_sha,
        "instrument_sha256": instrument_sha,
        "note": "93 号字节未改；本件是签名物化后的新记录",
    }
    return signed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instrument", type=Path, default=DEFAULT_INSTRUMENT)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--apply", action="store_true", help="写入 96 号已签记录")
    args = parser.parse_args(argv)

    if not args.instrument.exists():
        raise SignoffError(f"签认件不存在：{args.instrument}")
    text = args.instrument.read_text(encoding="utf-8")
    parsed = parse_instrument(text)
    plan = load_json(args.plan)
    instrument_sha = sha256(args.instrument)
    try:
        instrument_relative = str(args.instrument.relative_to(SCRATCH)).replace("\\", "/")
    except ValueError:
        instrument_relative = args.instrument.as_posix()

    signed = build_signed_plan(
        plan,
        parsed,
        plan_sha=sha256(args.plan),
        instrument_sha=instrument_sha,
        instrument_relative=f"evidence/{instrument_relative}",
    )

    summary = {
        "decisions": parsed["decisions"],
        "signoff": parsed["signoff"],
        "instrument_sha256": instrument_sha,
        "plan_status_before": plan["status"],
        "plan_status_after": signed["status"],
    }
    if not args.apply:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print("[dry-run] 未写盘；加 --apply 物化签名。")
        return 0

    outputs = {
        "claims-governance-plan.signed.json": (
            json.dumps(signed, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
    }
    manifest = {
        "schema_version": "claims-governance-signed-manifest-1",
        "status": "signed",
        "signed_by": parsed["signoff"]["reviewer"],
        "signed_on": parsed["signoff"]["signed_on"],
        "model_calls": 0,
        "inputs": {
            "unsigned_plan_93": sha256(args.plan),
            "signoff_instrument": instrument_sha,
        },
        "outputs": {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()},
        "does_not_touch": [
            "evidence/93-claims-governance-plan-20261014/**",
        ],
    }
    outputs["MANIFEST.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )

    args.out.mkdir(parents=True, exist_ok=True)
    existing = [name for name in outputs if (args.out / name).exists()]
    if existing:
        raise SignoffError(f"refusing to overwrite existing outputs {existing}")
    for name, data in outputs.items():
        (args.out / name).write_bytes(data)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"wrote {len(outputs)} files to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
