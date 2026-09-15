"""P0 protection plus externally pinned, additions-only P2-B scope."""

from __future__ import annotations

import argparse
import importlib.abc
import json
import sys
from pathlib import Path

import p0_baseline as p0

BASELINE_SHA = "4e2c45ce216a942137f60b863e236ae46f3a8870317ebdbe9ead6342b4698076"
SCOPE_SHA = "296db21dfd5ff9e890b5793767353060161e3a757453bf6718ad364c3583fc12"
BASELINE = p0.HERE / "p0-baselines/baseline-4e2c45ce216a9421/baseline-manifest.json"


def check_inventory(expected: dict[str, str], actual: dict[str, str], additions: set[str]) -> None:
    if additions & set(expected) or set(actual) != set(expected) | additions:
        raise ValueError("unexpected_inventory_delta")
    if any(actual[name] != sha for name, sha in expected.items()):
        raise ValueError("protected_file_changed")


def verify() -> dict[str, object]:
    data = BASELINE.read_bytes()
    if p0.sha(data) != BASELINE_SHA:
        raise ValueError("baseline_manifest_changed")
    manifest = json.loads(data)
    scope_data = (p0.HERE / "r2-p2b-change-scope.json").read_bytes()
    if p0.sha(scope_data) != SCOPE_SHA:
        raise ValueError("scope_manifest_changed")
    scope = json.loads(scope_data)
    guard_data = (BASELINE.parent / "protected-paths.json").read_bytes()
    if p0.sha(guard_data) != manifest["protected_paths_sha256"]:
        raise ValueError("protected_manifest_changed")
    expected = json.loads(guard_data)["file_sha256"]
    actual = p0.inventory(p0.ROOT)
    check_inventory(expected, actual, set(scope["new_protected_files"]))
    if p0.verify_files(p0.ROOT, manifest["asset_sha256"]):
        raise ValueError("old_asset_changed")
    if p0.environment() != manifest["environment"]:
        raise ValueError("environment_changed")
    if p0.git("rev-parse", "HEAD").decode().strip() != manifest["head"]:
        raise ValueError("head_changed")
    if (
        p0.sha((BASELINE.parent / "workspace-code.patch").read_bytes())
        != manifest["workspace_code_diff_sha256"]
    ):
        raise ValueError("old_workspace_patch_changed")
    for name, trusted in (
        (
            "r2-p1-contract-manifest.json",
            "a9477f7281287b0ce78b3fcc978b88fa5d48f5312094851e4e00d67cf2370603",
        ),
        (
            "r2-p2a-manifest.json",
            "72d5eb692bf44ad7f5dd61fa82e1db3e8e8cce72ee2fa461014c991e9e990cbf",
        ),
    ):
        raw = (p0.HERE / name).read_bytes()
        if p0.sha(raw) != trusted or p0.verify_files(p0.ROOT, json.loads(raw)["files"]):
            raise ValueError("frozen_phase_changed")
    return {
        "old_protected_unchanged": len(expected),
        "added_protected": len(actual) - len(expected),
        "addition_sha256": {name: actual[name] for name in scope["new_protected_files"]},
    }


class BlockAllR2(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
        if fullname == "plugins.corpus.material_semantics" or fullname.startswith(
            "plugins.corpus._r2_"
        ):
            raise ImportError("R2 intentionally unavailable")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("verify", "snapshot", "suite"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--suite", choices=("core", "platform", "isolation"))
    args = parser.parse_args()
    print(json.dumps(verify(), sort_keys=True))
    if args.action == "verify":
        return 0
    if args.out is None or args.out.exists():
        raise ValueError("new_output_path_required")
    # p0.suite is a library function: its old CLI, not suite(), installs this guard.
    # Install before collection too: existing tests probe PostgreSQL at import time.
    p0.block_external()
    if args.action == "snapshot":
        sys.meta_path.insert(0, BlockAllR2())
        data = p0.encoded(p0.snapshot())
        p0.write_once(args.out, data)
        print(json.dumps({"snapshot_sha256": p0.sha(data)}))
        return 0
    if args.suite is None:
        raise ValueError("suite_required")
    if args.suite == "isolation":
        sys.meta_path.insert(0, BlockAllR2())
        for module in ("plugins.corpus.material_semantics", "plugins.corpus._r2_runtime"):
            try:
                __import__(module)
            except ImportError:
                pass
            else:
                raise AssertionError("R2 poison control ineffective")
    result = p0.suite(args.suite, args.out)
    if args.suite == "isolation" and any(
        name.startswith("plugins.corpus._r2_") for name in sys.modules
    ):
        raise AssertionError("private R2 loaded during isolation")
    verify()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
