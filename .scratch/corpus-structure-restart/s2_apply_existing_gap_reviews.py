"""Reapply the frozen E6 gap-review criteria to S2 build identities."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".scratch/corpus-access-validation/e6_apply_gap_review.py"
TARGET_DB = "v14_s2_quote_corpus"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("s2_gap_reviews", SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load gap-review driver: {SOURCE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    module = _load()
    module.TARGET_DB = TARGET_DB
    module.RESULT = ROOT / ".scratch/corpus-structure-restart/s2-candidate-build.json"
    os.environ["CORPUS_TARGET_DB"] = TARGET_DB
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
