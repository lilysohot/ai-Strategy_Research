"""Locate the frozen risk target at each source-selection seam."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import dotenv
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[2]
TARGET_DB = os.environ.get("S4_CORPUS_DB", "v14_s2_quote_corpus")
TARGET_ID = "f7f65d7e-risk"
OUTPUT = ROOT / ".scratch/corpus-structure-restart/s4-source-probe.json"


def _configure() -> None:
    dotenv.load_dotenv(ROOT / ".env")
    from plugins.corpus.service import dsn

    target_dsn = make_conninfo(**{**conninfo_to_dict(dsn()), "dbname": TARGET_DB})
    os.environ["CORPUS_DSN"] = target_dsn
    os.environ["CORPUS_TARGET_DB"] = TARGET_DB
    os.environ.pop("PGOPTIONS", None)


def _load_target() -> tuple[dict[str, Any], dict[str, Any]]:
    path = ROOT / ".scratch/corpus-access-validation/e5_data_delivery.py"
    spec = importlib.util.spec_from_file_location("s4_delivery", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load delivery scorer: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sample = next(
        row
        for row in module._load_samples("holdout", set())
        if any(target.get("target_id") == TARGET_ID for target in row.get("targets") or [])
    )
    target = next(target for target in sample["targets"] if target.get("target_id") == TARGET_ID)
    return sample, target


def _hit(hit: Any, target_short: str) -> dict[str, Any]:
    return {
        "target_source": target_short in str(hit.source_id),
        "source_id": hit.source_id,
        "chunk_id": hit.chunk_id,
        "kind": hit.kind,
        "score": float(hit.score),
        "page": hit.page,
        "snippet": hit.snippet,
        "label_path": list(hit.label_path),
        "context_count": len(hit.context_chunk_ids),
    }


async def _run() -> dict[str, Any]:
    from plugins.corpus.preparation import read_pg
    from plugins.corpus.preparation.negative_query import retrieval_query
    from plugins.corpus.preparation.search_pg import query_lexemes
    from plugins.corpus.service import _SELECTION_POOL_MIN, get_service
    from plugins.tools.corpus_search import corpus_search

    sample, target = _load_target()
    question = str(target["question"])
    target_short = str(sample["doc_identity"])[:8]
    svc = get_service()
    lexemes = query_lexemes(svc._dsn, question, sandbox_db=TARGET_DB)
    candidate_query = retrieval_query(lexemes) or question
    raw_hits, chunk_order, _coverage = read_pg.search_with_coverage_bands(
        svc._dsn,
        candidate_query,
        limit=_SELECTION_POOL_MIN,
        sandbox_db=TARGET_DB,
    )
    source_rank: dict[str, int] = {}
    hits_by_source: dict[str, list[Any]] = defaultdict(list)
    for hit in raw_hits:
        source_rank.setdefault(hit.source_id, len(source_rank) + 1)
        hits_by_source[hit.source_id].append(hit)
    selected = svc._selected_context_hits(raw_hits, chunk_order, 10, lexemes=lexemes)
    public: dict[str, Any] = {}
    for limit in (10, 20):
        public[str(limit)] = json.loads(await corpus_search.func(question, limit=limit))
    target_hits = [_hit(hit, target_short) for hit in raw_hits if target_short in hit.source_id]
    return {
        "artifact": "s4-source-probe",
        "target_db": TARGET_DB,
        "target_id": TARGET_ID,
        "question": question,
        "expected_quote": target["verbatim_quote"],
        "target_source": sample["doc_identity"],
        "lexemes": list(lexemes),
        "candidate_query": candidate_query,
        "raw_hit_count": len(raw_hits),
        "source_count": len(source_rank),
        "source_order": [
            {
                "rank": rank,
                "source_id": source_id,
                "target_source": target_short in source_id,
                "hit_count": len(hits_by_source[source_id]),
                "max_score": max(float(hit.score) for hit in hits_by_source[source_id]),
                "score_sum": sum(float(hit.score) for hit in hits_by_source[source_id]),
                "top_two_sum": sum(
                    sorted((float(hit.score) for hit in hits_by_source[source_id]), reverse=True)[
                        :2
                    ]
                ),
                "snippets": [hit.snippet for hit in hits_by_source[source_id]],
            }
            for source_id, rank in source_rank.items()
        ],
        "target_raw_hits": target_hits,
        "selected_10": [_hit(hit, target_short) for hit in selected],
        "public": public,
    }


def main() -> None:
    _configure()
    artifact = asyncio.run(_run())
    OUTPUT.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        key: artifact[key]
        for key in (
            "target_id",
            "question",
            "lexemes",
            "candidate_query",
            "raw_hit_count",
            "source_count",
            "source_order",
            "target_raw_hits",
            "selected_10",
        )
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"artifact={OUTPUT}")


if __name__ == "__main__":
    main()
