"""Run the frozen 51-target verifier with the S4 source ranking."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".scratch/corpus-access-validation/e6_verify_closure.py"
TARGET_DB = "v14_s2_quote_corpus"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("s4_candidate_verifier", SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load verifier: {SOURCE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    module = _load()
    module.TARGET_DB = TARGET_DB
    module.BUILD_ARTIFACT = ROOT / ".scratch/corpus-structure-restart/s2-candidate-build.json"
    module.RESULT = ROOT / ".scratch/corpus-structure-restart/s4-candidate-verification.json"
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
