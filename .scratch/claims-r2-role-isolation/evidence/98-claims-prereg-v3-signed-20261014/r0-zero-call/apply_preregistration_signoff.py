"""Apply the U signature on the 95-号 instrument to produce the signed pre-registration record.

Reads (never writes) the 95 draft pre-registration, its MANIFEST and the signed instrument; writes
only inside this directory. The signature must already exist in the instrument (a named
``reviewer:`` plus a non-empty ``signed_on:``) — this script never fills a signature field, and it
copies the signature line **verbatim**, including the literal ``2026-10=14`` date, which is recorded
as-is with a note rather than silently normalised.

What the signature covers (registered explicitly, because the instrument is a numbered document):

* **Covered**: the four reading axes and the primary metric's numerator/denominator (§三), the 91-号
  release-line reading as an unconditional PASS (§四), the exit rules with trial validity split from
  the quality guardrails (§五), the measured deterministic ceiling (§六), the four pre-registered
  treatment rules including T4 (§七), the corrections to prior records (§八), the fairness clause
  (§九) and the hard constraints (§十一).
* **Not covered**: §十's live-run budget ceiling — it is still ``null``, so the run must not start.
  D-2 (per-source precision axis) remains undecided and stays report-only.

Status mirrors the items/claims gate convention: ``frozen_before_execution`` + ``countersignature``.

Usage:
    python apply_preregistration_signoff.py [--no-write] [--force]
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

SIGNED_ON = "2026-10-14"
SIGNER = "xyl"

DRAFT = ROOT / "evidence/95-claims-prereg-20261014/r0-zero-call/claims-preregistration.json"
DRAFT_MANIFEST = ROOT / "evidence/95-claims-prereg-20261014/r0-zero-call/MANIFEST.json"
INSTRUMENT = (
    ROOT / "evidence/95-claims-prereg-20261014/r0-zero-call/claims-preregistration-signoff.md"
)
GATE_V3 = ROOT / "evidence/91-claims-gate-v3-signed-20261014/r0-zero-call/claims-gate-v3.json"
REFUSAL_97 = (
    ROOT
    / "evidence/97-claims-governance-refusal-20261014/r0-zero-call/claims-governance-refusal.json"
)

INPUTS = {
    "claims_preregistration_draft": DRAFT,
    "claims_preregistration_draft_manifest": DRAFT_MANIFEST,
    "signoff_instrument": INSTRUMENT,
    "claims_gate_v3_signed": GATE_V3,
    "governance_refusal_97": REFUSAL_97,
}

# The signature adds a selection block and changes the status; anything else is a defect.
EXPECTED_ADDED = ("countersignature", "signed_from")
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


def assert_signed_instrument(text: str) -> dict[str, str]:
    """Return the verbatim signature fields, refusing anything that is not a real signature."""
    line = next(
        (ln.strip() for ln in text.splitlines() if ln.strip().startswith("reviewer:")),
        "",
    )
    if not line:
        raise SystemExit("refusing to apply: instrument has no 'reviewer:' line")
    reviewer = _field(line, "reviewer:")
    adjudicator = _field(line, "adjudicator:")
    signed_on = _field(line, "signed_on:")
    if SIGNER not in reviewer or SIGNER not in adjudicator:
        raise SystemExit(f"refusing to apply: instrument is not named-signed: {line!r}")
    if not signed_on or set(signed_on) <= set("-_ "):
        raise SystemExit("refusing to apply: instrument signature carries no date")
    return {
        "signature_line": line,
        "reviewer": reviewer,
        "adjudicator": adjudicator,
        "signed_on": signed_on,
    }


def build() -> dict[str, Any]:
    draft = load(DRAFT)
    manifest = load(DRAFT_MANIFEST)
    # Sign the audited draft bytes, not a re-generated copy.
    recorded = manifest["outputs"]["claims-preregistration.json"]
    if sha256(DRAFT) != recorded:
        raise SystemExit(
            f"refusing to apply: draft hash {sha256(DRAFT)} != MANIFEST {recorded}（先跑生成器再签）"
        )
    if draft.get("status") != "draft_pending_human_signature":
        raise SystemExit(f"refusing to apply: draft status is {draft.get('status')!r}")
    signature = assert_signed_instrument(INSTRUMENT.read_text(encoding="utf-8"))

    signed = copy.deepcopy(draft)
    signed["status"] = "frozen_before_execution"
    signed["signed_from"] = {
        "path": str(DRAFT.relative_to(ROOT)),
        "sha256": sha256(DRAFT),
        "status_at_sign": "draft_pending_human_signature",
        "note": "只加签认块与状态；正文（含 v1→v2→v3 修订记录）逐字沿用",
    }
    signed["countersignature"] = {
        "required": True,
        "status": "signed",
        "reviewer": signature["reviewer"],
        "adjudicator": signature["adjudicator"],
        "signed_on": signature["signed_on"],
        "signed_on_normalised": SIGNED_ON,
        "signed_on_note": (
            "签认件日期字面为『2026-10=14』（『=』疑为『-』笔误）；本件逐字照录、不代改文面。"
            "若 U 认为需更正文面，应重写签认件并重跑本脚本。"
        ),
        "instrument": {
            "path": str(INSTRUMENT.relative_to(ROOT)),
            "sha256": f"sha256:{sha256(INSTRUMENT)}",
            "pre_signature_sha256": manifest["outputs"]["claims-preregistration-signoff.md"],
            "signature_line": signature["signature_line"],
        },
        "statement": (
            "核准 95 号 claims 预注册 v3：读数（4 轴 + 主指标分子/分母定义）、91 号放行线无条件 PASS "
            "登记、退出规则（治疗定义项失败 ⇒ 试验无效）、确定性天花板、四条治疗规则（含 T4）、"
            "对既有记录的更正与公平性条款。"
        ),
        "covered": [
            "§三 读数轴与主指标口径（分子 = matched + correct_extra，与已签 C2 同源）",
            "§四 91 号 release_line 读作无条件 PASS（取代 97 号 consequences[3]，97 字节不改）",
            "§五 退出规则 + trial_validity（治疗定义项失败 ⇒ 试验无效）+ 止损项↔治疗规则 owner 对账",
            "§六 零调用实测天花板（0.6456 / 0.7091）",
            "§七 四条治疗规则 T1–T4（T4 缺字段必标 reason 码，未删即生效）",
            "§八 对 83/84 号记录的更正、§九 公平性条款、§十一 硬约束",
        ],
        "does_not_cover": [
            "§十 阶段 1 实跑预算 ceiling（仍为 null）⇒ 未填预算前不得起跑",
            "D-2 分源精度轴仍未裁，保持只报告不 gating",
            "金标、契约、门、P1R5 裁定等一切冻结件的字节",
        ],
        "scope_note": (
            "签认不改变任何冻结字节；不代表已出分、不代表发布/查询/交付可用；"
            "放行线通过不等于质量达标"
        ),
        "signature_applied_by": "apply_preregistration_signoff.py（零调用；不代填任何签名字段）",
    }

    diff = diff_paths(draft, signed)
    payload = json.dumps(signed, ensure_ascii=False, indent=2) + "\n"
    signed_digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _top(path: str) -> str:
        return path.split(".")[0].split("[")[0]

    diff_report = {
        "draft": {"path": str(DRAFT.relative_to(ROOT)), "sha256": sha256(DRAFT)},
        "signed": {
            "path": str((HERE / "claims-preregistration.json").relative_to(ROOT)),
            "sha256": f"sha256:{signed_digest}",
        },
        "changed_leaf_paths": diff["changed"],
        "added_leaf_paths": diff["added"],
        "removed_leaf_paths": diff["removed"],
        "expected_changed": list(EXPECTED_CHANGED),
        "expected_added": list(EXPECTED_ADDED),
        "expected_removed": list(EXPECTED_REMOVED),
        "unexpected_changed": sorted(p for p in diff["changed"] if _top(p) not in EXPECTED_CHANGED),
        "unexpected_added": sorted(p for p in diff["added"] if _top(p) not in EXPECTED_ADDED),
        "unexpected_removed": sorted(p for p in diff["removed"] if p not in EXPECTED_REMOVED),
        "instrument_drift": {
            "pre_signature_sha256": manifest["outputs"]["claims-preregistration-signoff.md"],
            "signed_sha256": sha256(INSTRUMENT),
            "note": "签认件在草案 MANIFEST 写盘后被 U 填入签名 ⇒ 两哈希必然不同；草案 MANIFEST 未改。",
        },
        "signature": {
            "reviewer": signature["reviewer"],
            "adjudicator": signature["adjudicator"],
            "signed_on_literal": signature["signed_on"],
            "signed_on_normalised": SIGNED_ON,
        },
        "verdict": {
            "status": signed["status"],
            "reading_axes_in_verdict": signed["reading_axes"]["in_verdict"],
            "release_line_91": "无条件 PASS（见 prior_record_readings）",
            "treatments_in_force": [
                rule["id"] for rule in signed["pre_registered_treatment_rules"]["rules"]
            ],
            "budget_ceiling": signed["budget_request"]["stage_1_live_run"]["requested_ceiling"],
            "runnable": False,
            "runnable_note": "预算 ceiling 未填 ⇒ 尚未起跑条件",
        },
    }
    manifest_out = {
        "schema_version": "claims-preregistration-signed-manifest-1",
        "status": "signed",
        "created_on": SIGNED_ON,
        "signed_by": SIGNER,
        "model_calls": 0,
        "inputs": {name: sha256(path) for name, path in INPUTS.items()},
        "outputs": {},
        "does_not_touch": [
            str(DRAFT.relative_to(ROOT)),
            str(INSTRUMENT.relative_to(ROOT)),
            str(DRAFT_MANIFEST.relative_to(ROOT)),
            "evidence/91-claims-gate-v3-signed-20261014/**",
            "evidence/97-claims-governance-refusal-20261014/**",
        ],
        "blocked_on": ["budget_request.stage_1_live_run.requested_ceiling 由 U 填"],
        "notes": [
            "签认件日期字面为 2026-10=14，逐字照录（见 countersignature.signed_on_note）。",
            "本件只加签认块/状态；不修改 95 号草案目录的任何字节。",
        ],
    }
    return {"signed": signed, "diff": diff_report, "manifest": manifest_out, "payload": payload}


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
        "claims-preregistration.json": result["payload"].encode("utf-8"),
        "prereg-signed-diff.json": (
            json.dumps(result["diff"], ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
    }
    manifest = result["manifest"]
    manifest["outputs"] = {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()}
    outputs["MANIFEST.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )

    targets = {name: HERE / name for name in outputs}
    for name, target in targets.items():
        assert_writable(target, reason="98 号签认落地件")
        if target.exists() and not args.force:
            raise SystemExit(f"refusing to overwrite existing output {name}; use --force")
    for name, data in outputs.items():
        write_once(targets[name], data.decode("utf-8"), allow_overwrite=True)

    print(f"wrote {len(outputs)} files to {HERE}")
    print(json.dumps(manifest["outputs"], ensure_ascii=False, indent=2))
    problems = (
        result["diff"]["unexpected_changed"]
        + result["diff"]["unexpected_added"]
        + result["diff"]["unexpected_removed"]
    )
    print(json.dumps(result["diff"]["verdict"], ensure_ascii=False, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
