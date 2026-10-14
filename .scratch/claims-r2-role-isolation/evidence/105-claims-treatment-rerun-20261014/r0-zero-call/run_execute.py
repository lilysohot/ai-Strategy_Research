"""Thin execute wrapper (105 号): the 102-号 executor against the 105-号 freeze.

Same six fail-closed gates, same budget authorisation (103 号), same signed pre-registration leaf
(99 号 — v4 did not touch its budget or rule blocks, so the entry needs no repointing). Only the
freeze directory changes to this record's re-frozen plan, and the write-once
``execution-summary.json`` lands here.

Usage:
    python run_execute.py --dry-run
    python run_execute.py --allow-model
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

EXECUTOR = (
    ROOT
    / "evidence/102-claims-treatment-engineering-20261014"
    / "r0-zero-call/execute_claims_treatment.py"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-model", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    spec = importlib.util.spec_from_file_location("execute_claims_treatment", EXECUTOR)
    if spec is None or spec.loader is None:
        raise SystemExit(f"refusing: cannot load 102-号 executor module at {EXECUTOR}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.FREEZE = HERE / "claims-treatment-plan-freeze"  # the only seam: freeze directory

    argv = ["execute_claims_treatment"]
    if args.allow_model:
        argv.append("--allow-model")
    if args.dry_run:
        argv.append("--dry-run")
    sys.argv = argv
    return module.main()


if __name__ == "__main__":
    raise SystemExit(main())
