"""Build the S1 table-relation candidate in a dedicated database."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".scratch/corpus-access-validation/e6_prepare_holdout_db.py"
TARGET_DB = "v14_s1_table_corpus"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("s1_candidate_builder", SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load builder: {SOURCE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    module = _load()
    module.TARGET_DB = TARGET_DB
    module.ARCHIVE = ROOT / ".scratch/corpus-structure-restart/s1-candidate-archive"
    module.RESULT = ROOT / ".scratch/corpus-structure-restart/s1-candidate-build.json"
    os.environ["CORPUS_TARGET_DB"] = TARGET_DB
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
