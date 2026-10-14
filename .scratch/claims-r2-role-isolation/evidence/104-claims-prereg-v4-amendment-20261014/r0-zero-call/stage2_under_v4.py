"""Stage-2 entry under the v4 judging criteria (104 号): the amendment takes effect here.

Why this exists: the 102-号 entry pair reads its stop-loss rules verbatim from the *signed*
pre-registration — good — but its ``SIGNED_PREREG`` constant still points at the 99-号 record, whose
bytes must not change. Rather than editing a landed evidence script, this thin wrapper loads the
102-号 module, points it at the effective v4 record, and delegates: the moment v4 is signed into
existence, stage 2 stops gating on ``unbound_union`` (it is a diagnostic there) without touching a
single byte of 102 号.

Fail-closed: without an effective v4 record (i.e. before U signs), this refuses to run — the signed
99-号 criteria stay in force and the 102-号 entry remains the way to run stage 2 under them.

Usage:
    python stage2_under_v4.py --freeze <dir> --out <dir> [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

WORKSHEET = (
    ROOT
    / "evidence/102-claims-treatment-engineering-20261014"
    / "r0-zero-call/build_treatment_adjudication_worksheet.py"
)
SIGNED_99 = (
    ROOT
    / "evidence/99-claims-prereg-v3-signed-r2-20261014/r0-zero-call/claims-preregistration.json"
)
ACTIVE = HERE / "claims-preregistration-v4.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_worksheet_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "build_treatment_adjudication_worksheet", WORKSHEET
    )
    if spec is None or spec.loader is None:
        raise SystemExit(f"refusing to run: cannot load 102-号 worksheet module at {WORKSHEET}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def active_prereg() -> Path:
    """The effective v4 record, fail-closed: absent or unsigned ⇒ refuse."""
    if not ACTIVE.exists():
        raise SystemExit(
            "refusing to run: v4 生效件不存在（claims-preregistration-v4.json）——"
            "需先在 104 号签认件上具名签署并运行 apply_prereg_v4_signoff.py；"
            "在此之前 99 号判据仍然生效，请用 102 号入口"
        )
    record = load(ACTIVE)
    if record.get("status") != "frozen_before_execution":
        raise SystemExit(f"refusing to run: v4 record status is {record.get('status')!r}")
    if record.get("amended_from", {}).get("sha256") != sha256(SIGNED_99):
        raise SystemExit("refusing to run: v4 record does not amend the signed 99 号 record")
    gates = record["exit_rules"]["early_stop_before_human_adjudication"]["stage2_proxies"]
    if "unbound_union" in gates:
        raise SystemExit(
            "refusing to run: v4 record still gates on unbound_union — not the v4 form"
        )
    return ACTIVE


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--freeze",
        type=Path,
        default=ROOT
        / "evidence/102-claims-treatment-engineering-20261014"
        / "r0-zero-call/claims-treatment-plan-freeze",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT
        / "evidence/102-claims-treatment-engineering-20261014"
        / "r0-zero-call/treatment-adjudication",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    active = active_prereg()
    module = load_worksheet_module()
    module.SIGNED_PREREG = active  # the single seam: rules now come from the effective v4 record

    argv = [
        "build_treatment_adjudication_worksheet",
        "--freeze",
        str(args.freeze),
        "--out",
        str(args.out),
    ]
    if args.force:
        argv.append("--force")
    sys.argv = argv
    return module.main()


if __name__ == "__main__":
    raise SystemExit(main())
