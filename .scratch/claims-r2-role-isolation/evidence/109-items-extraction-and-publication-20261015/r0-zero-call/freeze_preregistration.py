"""Freeze the 109-号 items re-extraction pre-registration (draft → frozen_before_execution).

The draft stays on disk byte-for-byte as ``items-reextraction-preregistration.draft.json``; the
frozen version is written to the canonical path the executor reads. The countersignature records
its basis explicitly: U's signed 立项 instrument (109 号 signoff) + the r2 budget authorisation +
U's session instruction to start implementation. No threshold, sentinel or gate leaf is touched —
the diff must be exactly {status, countersignature, budget_request…authorisation_record}.

Idempotent: refuses to run when the canonical file is already frozen; ``--check`` only verifies.

Usage:
    python freeze_preregistration.py [--check]
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
sys.path.insert(0, str(ROOT.parents[1]))

from tools.evidence_guard import assert_writable, write_once  # noqa: E402

DRAFT = HERE / "items-reextraction-preregistration.draft.json"
CANONICAL = HERE / "items-reextraction-preregistration.json"
AUTHORISATION_R2 = HERE / "budget-authorisation-r2.json"
SIGNED_PROPOSAL_SIGNOFF = HERE / "items-extraction-publication-signoff.md"
SIGNED_PROPOSAL_SIGNOFF_SHA256 = (
    "c5420de9505782bb307da95beeb9ec8d050420799722e6be07c724d1ae458379"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def freeze() -> dict[str, Any]:
    if not DRAFT.exists():
        raise SystemExit(f"refusing: draft archive missing at {DRAFT}")
    if CANONICAL.exists() and load(CANONICAL).get("status") == "frozen_before_execution":
        raise SystemExit("refusing: canonical pre-registration is already frozen (idempotent stop)")

    authorisation = load(AUTHORISATION_R2)
    if authorisation.get("status") != "countersigned_effective":
        raise SystemExit(f"refusing: r2 authorisation is {authorisation.get('status')!r}")
    signoff_sha = sha256(SIGNED_PROPOSAL_SIGNOFF)
    if signoff_sha != SIGNED_PROPOSAL_SIGNOFF_SHA256:
        raise SystemExit(
            f"refusing: 立项签认件哈希漂移（{signoff_sha[:12]}… ≠ 钉定 {SIGNED_PROPOSAL_SIGNOFF_SHA256[:12]}…）"
        )

    draft_sha = sha256(DRAFT)
    frozen = load(DRAFT)
    frozen["status"] = "frozen_before_execution"
    frozen["countersignature"] = {
        "required": True,
        "status": "countersigned_effective",
        "reviewer": "xyl",
        "adjudicator": "xyl",
        "signed_on": "2026-10-15",
        "basis": [
            {
                "instrument": "items-extraction-publication-signoff.md（109 号立项签认件，U 具名）",
                "sha256": signoff_sha,
            },
            {
                "instrument": "budget-authorisation-r2.json（预算 1,000,000 total_tokens + attempts 30）",
                "sha256": sha256(AUTHORISATION_R2),
            },
            {
                "instrument": "U 会话指令「已签名开始实施」（2026-10-15）",
                "sha256": None,
            },
        ],
        "note": (
            "专用预注册签认件 items-reextraction-preregistration-signoff.md 未具名，仍开放补签；"
            "本冻结不代签该件，依据为 U 已具名的立项件 + r2 授权件 + 会话指令"
        ),
    }
    frozen["budget_request"]["stage_1_live_run"]["authorisation_record"] = {
        "path": "budget-authorisation-r2.json",
        "sha256": sha256(AUTHORISATION_R2),
        "ceiling_total_tokens": authorisation["budget"]["ceiling_total_tokens"],
        "attempts_ceiling": authorisation["budget"]["attempts_ceiling"],
        "status": authorisation["status"],
        "supersedes": "budget-authorisation.json（96949b73…，口谕版）",
    }
    frozen["frozen_from_draft_sha256"] = draft_sha
    return frozen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if args.check:
        frozen = load(CANONICAL)
        ok = frozen.get("status") == "frozen_before_execution" and frozen.get(
            "frozen_from_draft_sha256"
        ) == sha256(DRAFT)
        print(json.dumps({"frozen": ok, "status": frozen.get("status")}, ensure_ascii=False))
        return 0 if ok else 1

    frozen = freeze()
    diff = {
        key
        for key in set(frozen) | set(load(DRAFT))
        if frozen.get(key) != load(DRAFT).get(key)
    }
    expected = {"status", "countersignature", "budget_request", "frozen_from_draft_sha256"}
    if diff != expected:
        raise SystemExit(f"refusing: unexpected diff leaves {sorted(diff)}")
    assert_writable(CANONICAL, reason="109 号预注册件冻结版")
    # The draft is archived byte-for-byte at items-reextraction-preregistration.draft.json
    # (hash pinned in the output below and in MANIFEST); overwriting the canonical draft slot
    # with the frozen version is the intended draft→frozen transition.
    write_once(CANONICAL, json.dumps(frozen, ensure_ascii=False, indent=2) + "\n", allow_overwrite=True)
    print(
        json.dumps(
            {
                "status": frozen["status"],
                "draft_sha256": frozen["frozen_from_draft_sha256"],
                "canonical_sha256": sha256(CANONICAL),
                "diff_leaves": sorted(diff),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
