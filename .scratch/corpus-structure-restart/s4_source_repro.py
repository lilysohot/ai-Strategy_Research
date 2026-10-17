"""Fast replay for the frozen S4 source-recall target."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path
from typing import Any

import dotenv
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / ".scratch/corpus-access-validation"
TARGET_DB = os.environ.get("S4_CORPUS_DB", "v14_s2_quote_corpus")
TARGET_ID = "f7f65d7e-risk"
OUTPUT = ROOT / ".scratch/corpus-structure-restart/s4-source-repro.json"


def _configure() -> None:
    dotenv.load_dotenv(ROOT / ".env")
    from plugins.corpus.service import dsn

    target_dsn = make_conninfo(**{**conninfo_to_dict(dsn()), "dbname": TARGET_DB})
    os.environ["CORPUS_DSN"] = target_dsn
    os.environ["CORPUS_TARGET_DB"] = TARGET_DB
    os.environ.pop("PGOPTIONS", None)


def _load_delivery() -> Any:
    path = HERE / "e5_data_delivery.py"
    spec = importlib.util.spec_from_file_location("s4_delivery", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load delivery scorer: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _run(delivery: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    sample = next(
        row
        for row in delivery._load_samples("holdout", set())
        if any(target.get("target_id") == TARGET_ID for target in row.get("targets") or [])
    )
    target = next(target for target in sample["targets"] if target.get("target_id") == TARGET_ID)
    result = await delivery._score_target(sample, target, {}, {})
    return target, result


def main() -> int:
    _configure()
    target, result = asyncio.run(_run(_load_delivery()))
    artifact = {
        "artifact": "s4-source-repro",
        "target_db": TARGET_DB,
        "target": target,
        "result": result,
    }
    OUTPUT.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"artifact={OUTPUT}")
    return 0 if result["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
