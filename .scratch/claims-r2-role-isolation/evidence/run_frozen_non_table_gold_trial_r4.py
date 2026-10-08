"""Run the r4 validator remediation against the signed 24-unit scope."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

HERE = Path(__file__).resolve().parent
BASE_RUNNER = HERE / "run_frozen_non_table_gold_trial_r3.py"
REMEDIATION = HERE / "14-r4-validator-remediation-freeze-20261008" / "freeze-manifest.json"
RUN_NAME = "15-live-20261008-non-table-gold-r4"
RUN = HERE / RUN_NAME


def load_base() -> ModuleType:
    spec = importlib.util.spec_from_file_location("claims_r4_bounded_base", BASE_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen r3 runner implementation")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base: Any = load_base()
base.REMEDIATION = REMEDIATION
base.RUN_NAME = RUN_NAME
base.RUN = RUN
base.base.__file__ = str(Path(__file__).resolve())
base.base.RUN_NAME = RUN_NAME
base.base.RUN = RUN


def verify_remediation(expected_hash: str | None = None) -> tuple[str, dict[str, Any]]:
    remediation_hash = base.sha256(REMEDIATION)
    if expected_hash is not None and remediation_hash != expected_hash:
        raise ValueError("r4 remediation freeze changed")
    remediation = base.read_json(REMEDIATION)
    if remediation["status"] != "frozen_ready_for_bounded_r4":
        raise ValueError("r4 remediation is not frozen for bounded execution")
    for group in ("parent_evidence", "frozen_files"):
        for relative, expected in remediation[group].items():
            if base.sha256(base.base.REPO / relative) != expected:
                raise ValueError(f"frozen r4 input changed: {relative}")
    return remediation_hash, remediation


base.verify_remediation = verify_remediation


def prepare() -> None:
    base.prepare()
    manifest_path = RUN / "manifest.json"
    manifest = base.read_json(manifest_path)
    manifest["stage"] = "signed_non_table_gold_r4_validator_evaluation"
    base.replace_json(manifest_path, manifest)
    for source in manifest["sources"]:
        freeze_path = RUN / source["slug"] / "freeze.json"
        freeze = base.read_json(freeze_path)
        freeze["stage"] = "signed_non_table_gold_r4_validator_evaluation"
        base.replace_json(freeze_path, freeze)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "execute", "check"))
    parser.add_argument("slug", nargs="?")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
        return 0
    if not args.slug:
        parser.error("slug required")
    if args.action == "execute":
        return int(base.base.execute(args.slug))
    base.base.check(args.slug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
