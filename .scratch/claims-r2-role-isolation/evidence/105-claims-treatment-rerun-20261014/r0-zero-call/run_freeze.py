"""Thin re-freeze wrapper (105 号): the 102-号 prepare logic, output directory pointed here.

Zero model calls. Loads the 102-号 ``prepare_claims_treatment_plan`` module verbatim (its planning
logic is exactly what the treatment arm froze), overrides only its ``OUT`` constant to this record's
directory, and delegates ``main()``. The old freeze under 102 号 stays byte-for-byte untouched and is
registered as the interrupted archive in ``rerun-incident.json``.

Usage:
    python run_freeze.py [--no-write] [--force]
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

PREPARE = (
    ROOT
    / "evidence/102-claims-treatment-engineering-20261014"
    / "r0-zero-call/prepare_claims_treatment_plan.py"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    spec = importlib.util.spec_from_file_location("prepare_claims_treatment_plan", PREPARE)
    if spec is None or spec.loader is None:
        raise SystemExit(f"refusing: cannot load 102-号 prepare module at {PREPARE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OUT = HERE / "claims-treatment-plan-freeze"  # the only seam: output directory

    argv = ["prepare_claims_treatment_plan"]
    if args.no_write:
        argv.append("--no-write")
    if args.force:
        argv.append("--force")
    sys.argv = argv
    return module.main()


if __name__ == "__main__":
    raise SystemExit(main())
