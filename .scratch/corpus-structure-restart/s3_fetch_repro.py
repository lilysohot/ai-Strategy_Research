"""Inspect the failing S3 fetch plans for the frozen fed-rate target."""

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
TARGET_DB = os.environ.get("S3_CORPUS_DB", "v14_s2_quote_corpus")
TARGET_ID = "5e305376-fedrate"
OUTPUT = ROOT / ".scratch/corpus-structure-restart/s3-fetch-repro.json"


def _configure() -> None:
    dotenv.load_dotenv(ROOT / ".env")
    from plugins.corpus.service import dsn

    target_dsn = make_conninfo(**{**conninfo_to_dict(dsn()), "dbname": TARGET_DB})
    os.environ["CORPUS_DSN"] = target_dsn
    os.environ["CORPUS_TARGET_DB"] = TARGET_DB
    os.environ.pop("PGOPTIONS", None)


def _load_delivery() -> Any:
    path = HERE / "e5_data_delivery.py"
    spec = importlib.util.spec_from_file_location("s3_delivery", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load delivery scorer: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _run(delivery: Any) -> dict[str, Any]:
    sample = next(
        row
        for row in delivery._load_samples("holdout", set())
        if any(target.get("target_id") == TARGET_ID for target in row.get("targets") or [])
    )
    target = next(target for target in sample["targets"] if target.get("target_id") == TARGET_ID)
    search, delivered_search = await delivery._search(target["question"])
    doc_short = str(target.get("doc_identity") or sample["doc_identity"])[:8]
    source_hits = [
        hit for hit in search.get("hits") or [] if doc_short in str(hit.get("source_id") or "")
    ]
    plans: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for hit in source_hits:
        plan = hit.get("fetch_plan") or {
            "doc_id": hit.get("doc_id"),
            "locators": hit.get("context_locators") or [hit.get("locator")],
            "scope_id": hit.get("scope_id"),
        }
        key = (
            str(plan.get("doc_id") or ""),
            tuple(str(locator) for locator in plan.get("locators") or []),
        )
        if key not in seen:
            seen.add(key)
            plans.append(plan)
    fetches = [await delivery._fetch_plan(plan) for plan in plans]
    score = await delivery._score_target(sample, target, {}, {})
    return {
        "artifact": "s3-fetch-repro",
        "target_db": TARGET_DB,
        "target": target,
        "delivered_search_chars": len(delivered_search),
        "source_hits": source_hits,
        "plans": plans,
        "fetches": fetches,
        "score": score,
    }


def main() -> int:
    _configure()
    artifact = asyncio.run(_run(_load_delivery()))
    OUTPUT.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "score": artifact["score"],
                "fetches": artifact["fetches"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"artifact={OUTPUT}")
    return 0 if artifact["score"]["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
