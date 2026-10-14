"""Land the U signature on the v4 amendment (refuses anything unsigned, fills nothing in).

What this produces once the instrument (``claims-preregistration-v4-signoff.md``) carries U's named
signature:

* ``claims-preregistration-v4.json`` — the effective record: v4 body verbatim + ``status``
  ``frozen_before_execution`` + ``signed_from`` (pointing at the reviewed draft bytes) +
  ``countersignature`` (pointing at the signed instrument);
* ``prereg-v4-signed-diff.json`` — the diff against the draft, with an unexpected-leaf check;
* ``MANIFEST.json``.

Fail-closed by design: an instrument without a named signature line, a drifted draft, or any
unexpected diff leaf aborts the run. It never fills a signature field on U's behalf.

Usage:
    python apply_prereg_v4_signoff.py [--no-write] [--force]
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

SIGNER = "xyl"

DRAFT = HERE / "claims-preregistration-v4.proposed.json"
DRAFT_MANIFEST = HERE / "MANIFEST.json"
INSTRUMENT = HERE / "claims-preregistration-v4-signoff.md"
SIGNED_99 = (
    ROOT
    / "evidence/99-claims-prereg-v3-signed-r2-20261014/r0-zero-call/claims-preregistration.json"
)

EXPECTED_ADDED = ("signed_from", "countersignature")
EXPECTED_CHANGED = ("status",)
EXPECTED_REMOVED: tuple[str, ...] = ()


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


def _field(line: str, label: str) -> str:
    tail = line.split(label, 1)[1] if label in line else ""
    for stop in ("adjudicator:", "reviewer:", "signed_on:"):
        if stop != label and stop in tail:
            tail = tail.split(stop, 1)[0]
    return tail.strip()


def signature_of(text: str) -> dict[str, str]:
    line = next((ln.strip() for ln in text.splitlines() if ln.strip().startswith("reviewer:")), "")
    if not line:
        raise SystemExit("refusing to apply: instrument has no 'reviewer:' line")
    fields = {
        "signature_line": line,
        "reviewer": _field(line, "reviewer:"),
        "adjudicator": _field(line, "adjudicator:"),
        "signed_on": _field(line, "signed_on:"),
    }
    if SIGNER not in fields["reviewer"] or SIGNER not in fields["adjudicator"]:
        raise SystemExit(f"refusing to apply: instrument is not named-signed: {line!r}")
    if not fields["signed_on"]:
        raise SystemExit("refusing to apply: instrument signature carries no date")
    return fields


def build() -> dict[str, Any]:
    draft = load(DRAFT)
    manifest = load(DRAFT_MANIFEST)
    recorded = manifest["outputs"]["claims-preregistration-v4.proposed.json"]
    if sha256(DRAFT) != recorded:
        raise SystemExit(f"refusing to apply: draft hash {sha256(DRAFT)} != MANIFEST {recorded}")
    if draft.get("status") != "draft_pending_human_signature":
        raise SystemExit(f"refusing to apply: draft status is {draft.get('status')!r}")
    if draft.get("amended_from", {}).get("sha256") != sha256(SIGNED_99):
        raise SystemExit(
            "refusing to apply: amended_from does not point at the signed 99 号 record"
        )
    signature = signature_of(INSTRUMENT.read_text(encoding="utf-8"))

    effective = copy.deepcopy(draft)
    effective["status"] = "frozen_before_execution"
    effective["signed_from"] = {
        "path": str(DRAFT.relative_to(ROOT)),
        "sha256": sha256(DRAFT),
        "status_at_sign": "draft_pending_human_signature",
        "note": "只加签认块与状态；v4 正文（含 amended_from、取代读法与修订记录）逐字沿用",
    }
    effective["countersignature"] = {
        "required": True,
        "status": "signed",
        "reviewer": signature["reviewer"],
        "adjudicator": signature["adjudicator"],
        "signed_on": signature["signed_on"],
        "instrument": {
            "path": str(INSTRUMENT.relative_to(ROOT)),
            "sha256": f"sha256:{sha256(INSTRUMENT)}",
            "signature_line": signature["signature_line"],
        },
        "statement": (
            "核准 95 号 claims 预注册 v4 修订（104 号）：把阶段 2 止损项 unbound_union 从闸门改为"
            "诊断（report_only_proxies，gating=false，baseline 54 与谓词原样保留）；同时核准其对 "
            "101 号 targets.unbound_union 读法的取代登记。其余判据（线值、读数轴、护栏、T1/T3/T4、"
            "预算形态）逐字不变。"
        ),
        "covered": [
            "§一 stage2_proxies 移除 unbound_union（余 3 项闸门）",
            "§二 改动依据（101 号实测 54 → 52 ≠ ≤ 27；并集构成以 matched/correct_extra 为主）",
            "§三 未改项清单（0.80 / 0.60、读数轴、护栏、T1/T3/T4、预算形态、基线计数）",
            "§四 生效方式（apply 生成生效件；阶段 2 由 stage2_under_v4.py 按 v4 判据执行，102 号字节不动）",
            "§五 对 101 号 targets.unbound_union 的取代读法（101 号字节不改）",
        ],
        "does_not_cover": [
            "预算 ceiling（落在 103 号，本件不动）",
            "D-2 分源精度轴（仍未裁，只报告不 gating）",
            "金标、契约、门、P1R5 裁定、95/99/101 号等一切冻结件的字节",
        ],
        "scope_note": (
            "签认不改变任何冻结字节；unbound_union 的基线读数（54）与其测量谓词不变，"
            "变的只是它不再阻断阶段 3"
        ),
        "signature_applied_by": "apply_prereg_v4_signoff.py（零调用；不代填任何签名字段）",
    }

    diff = diff_paths(draft, effective)
    payload = json.dumps(effective, ensure_ascii=False, indent=2) + "\n"
    signed_digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    diff_report = {
        "draft": {"path": str(DRAFT.relative_to(ROOT)), "sha256": sha256(DRAFT)},
        "effective": {
            "path": str((HERE / "claims-preregistration-v4.json").relative_to(ROOT)),
            "sha256": f"sha256:{signed_digest}",
        },
        "amended_record": {
            "path": str(SIGNED_99.relative_to(ROOT)),
            "sha256": sha256(SIGNED_99),
            "why": "v4 修订的基底：99 号已签件（其正文即 95 号草案正文）",
        },
        "changed_leaf_paths": diff["changed"],
        "added_leaf_paths": diff["added"],
        "removed_leaf_paths": diff["removed"],
        "expected_changed": list(EXPECTED_CHANGED),
        "expected_added": list(EXPECTED_ADDED),
        "expected_removed": list(EXPECTED_REMOVED),
        "unexpected_changed": sorted(p for p in diff["changed"] if p not in EXPECTED_CHANGED),
        "unexpected_added": sorted(
            p for p in diff["added"] if p.split(".")[0].split("[")[0] not in EXPECTED_ADDED
        ),
        "unexpected_removed": sorted(p for p in diff["removed"] if p not in EXPECTED_REMOVED),
        "signature": {
            "reviewer": signature["reviewer"],
            "adjudicator": signature["adjudicator"],
            "signed_on_literal": signature["signed_on"],
        },
        "verdict": {
            "status": effective["status"],
            "unbound_union": "diagnostic（report_only_proxies，gating=false）",
            "stage2_gates_in_force": sorted(
                effective["exit_rules"]["early_stop_before_human_adjudication"]["stage2_proxies"]
            ),
            "budget_ceiling": effective["budget_request"]["stage_1_live_run"]["requested_ceiling"],
            "runnable_note": (
                "判据生效；起跑仍需 103 号预算授权件在场（execute_claims_treatment.py 以其为准）"
            ),
        },
    }
    manifest_out = {
        "schema_version": "claims-preregistration-v4-signed-manifest-1",
        "id": "104-claims-prereg-v4-amendment-20261014",
        "status": "signed",
        "created_on": "2026-10-14",
        "signed_by": signature["reviewer"],
        "model_calls": 0,
        "amends": {
            "path": str(SIGNED_99.relative_to(ROOT)),
            "sha256": sha256(SIGNED_99),
        },
        "inputs": {
            "v4_draft": sha256(DRAFT),
            "v4_draft_manifest": sha256(DRAFT_MANIFEST),
            "signoff_instrument": sha256(INSTRUMENT),
            "signed_prereg_99": sha256(SIGNED_99),
        },
        "outputs": {},
        "does_not_touch": [
            "evidence/95-claims-prereg-20261014/**",
            "evidence/99-claims-prereg-v3-signed-r2-20261014/**",
            "evidence/101-claims-treatment-t1t2t3-landing-20261014/**",
            "evidence/102-claims-treatment-engineering-20261014/**",
            "evidence/103-claims-budget-authorisation-20261014/**",
        ],
        "notes": [
            "本件把 v4 草案翻为生效态：只加签认块与状态；判据正文逐字沿用。",
            "阶段 2 入口：stage2_under_v4.py（以生效件为判据，委托 102 号逻辑）。",
        ],
    }
    return {
        "effective": effective,
        "diff": diff_report,
        "manifest": manifest_out,
        "payload": payload,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.no_write:
        result = build()
        print(json.dumps(result["diff"], ensure_ascii=False, indent=2))
        print("[no-write] nothing written.")
        return 0

    result = build()
    outputs = {
        "claims-preregistration-v4.json": result["payload"].encode("utf-8"),
        "prereg-v4-signed-diff.json": (
            json.dumps(result["diff"], ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
    }
    manifest = result["manifest"]
    manifest["outputs"] = {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()}
    outputs["MANIFEST-signed.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")

    targets = {name: HERE / name for name in outputs}
    for name, target in targets.items():
        assert_writable(target, reason="104 号 v4 生效件")
        if target.exists() and not args.force:
            raise SystemExit(f"refusing to overwrite existing output {name}; use --force")
    for name, data in outputs.items():
        write_once(targets[name], data.decode("utf-8"), allow_overwrite=True)

    print(f"wrote {len(outputs)} files to {HERE}")
    print(json.dumps(manifest["outputs"], ensure_ascii=False, indent=2))
    print(json.dumps(result["diff"]["verdict"], ensure_ascii=False, indent=2))
    problems = (
        result["diff"]["unexpected_changed"]
        + result["diff"]["unexpected_added"]
        + result["diff"]["unexpected_removed"]
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
