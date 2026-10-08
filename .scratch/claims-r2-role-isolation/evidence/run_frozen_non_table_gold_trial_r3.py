"""Run the r3 remediation against the same signed 24-unit non-table scope."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

HERE = Path(__file__).resolve().parent
BASE_RUNNER = HERE / "run_frozen_non_table_gold_trial_r2.py"
REMEDIATION = HERE / "12-r3-quality-remediation-freeze-20261008" / "freeze-manifest.json"
RUN_NAME = "13-live-20261008-non-table-gold-r3"
RUN = HERE / RUN_NAME


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_base() -> ModuleType:
    spec = importlib.util.spec_from_file_location("claims_r3_bounded_base", BASE_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen r2 runner implementation")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base: Any = load_base()
base.__file__ = str(Path(__file__).resolve())
base.RUN_NAME = RUN_NAME
base.RUN = RUN
_base_verify = base.verify


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def replace_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def verify_remediation(expected_hash: str | None = None) -> tuple[str, dict[str, Any]]:
    remediation_hash = sha256(REMEDIATION)
    if expected_hash is not None and remediation_hash != expected_hash:
        raise ValueError("r3 remediation freeze changed")
    remediation = read_json(REMEDIATION)
    if remediation["status"] != "frozen_ready_for_bounded_r3":
        raise ValueError("r3 remediation is not frozen for bounded execution")
    for group in ("parent_evidence", "frozen_files"):
        for relative, expected in remediation[group].items():
            path = base.REPO / relative
            if sha256(path) != expected:
                raise ValueError(f"frozen r3 input changed: {relative}")
    return remediation_hash, remediation


def prepare() -> None:
    remediation_hash, remediation = verify_remediation()
    base.prepare()
    for source in read_json(RUN / "manifest.json")["sources"]:
        freeze_path = RUN / source["slug"] / "freeze.json"
        freeze = read_json(freeze_path)
        freeze.update(
            {
                "stage": "signed_non_table_gold_r3_remediation_evaluation",
                "remediation_freeze_sha256": remediation_hash,
                "frozen_versions": remediation["versions"],
                "frozen_files": remediation["frozen_files"],
            }
        )
        replace_json(freeze_path, freeze)
    manifest_path = RUN / "manifest.json"
    manifest = read_json(manifest_path)
    manifest.update(
        {
            "stage": "signed_non_table_gold_r3_remediation_evaluation",
            "remediation_freeze_sha256": remediation_hash,
            "frozen_versions": remediation["versions"],
        }
    )
    replace_json(manifest_path, manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def verify(target: Path) -> tuple[Any, dict[str, Any]]:
    plan, frozen = _base_verify(target)
    verify_remediation(frozen.get("remediation_freeze_sha256"))
    return plan, frozen


base.verify = verify


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
        return int(base.execute(args.slug))
    base.check(args.slug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
