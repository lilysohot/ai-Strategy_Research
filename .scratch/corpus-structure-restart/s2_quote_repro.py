"""Fast red/green replay for the three S2 quote-delivery failures."""

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
TARGET_DB = os.environ.get("S2_CORPUS_DB", "v14_s1_table_corpus")
TARGET_IDS = {
    "c1ddcd8a-summarytable",
    "b7e932c8-index",
    "b7e932c8-industry",
}
OUTPUT = ROOT / ".scratch/corpus-structure-restart/s2-quote-repro.json"


def _configure() -> None:
    dotenv.load_dotenv(ROOT / ".env")
    from plugins.corpus.service import dsn

    target_dsn = make_conninfo(**{**conninfo_to_dict(dsn()), "dbname": TARGET_DB})
    os.environ["CORPUS_DSN"] = target_dsn
    os.environ["CORPUS_TARGET_DB"] = TARGET_DB
    os.environ.pop("PGOPTIONS", None)


def _load_delivery() -> Any:
    path = HERE / "e5_data_delivery.py"
    spec = importlib.util.spec_from_file_location("s2_delivery", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load delivery scorer: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _run(delivery: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    samples = delivery._load_samples("holdout", set())
    definitions: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    search_cache: dict[str, tuple[dict[str, Any], str]] = {}
    fetch_cache: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
    for sample in samples:
        for target in sample.get("targets") or []:
            if target.get("target_id") not in TARGET_IDS:
                continue
            definitions.append(target)
            results.append(
                await delivery._score_target(sample, target, search_cache, fetch_cache)
            )
    return definitions, results


def main() -> int:
    _configure()
    definitions, results = asyncio.run(_run(_load_delivery()))
    if {row["target_id"] for row in results} != TARGET_IDS:
        raise RuntimeError("S2 target set mismatch")
    artifact = {
        "artifact": "s2-quote-repro",
        "target_db": TARGET_DB,
        "definitions": definitions,
        "results": results,
        "passed": sum(row["all_pass"] for row in results),
        "targets": len(results),
    }
    OUTPUT.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            [
                {
                    "target_id": row["target_id"],
                    "first_fail": row["first_fail"],
                    "search_hits": row["search_hits"],
                    "source_offered": row["source_offered"],
                    "plans": row["plans"],
                    "delivered_locators": row["delivered_locators"],
                    "expected_quote": row["expected_quote"],
                }
                for row in results
            ],
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"artifact={OUTPUT}")
    return 0 if all(row["all_pass"] for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
