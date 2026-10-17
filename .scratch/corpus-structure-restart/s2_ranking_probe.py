"""Explain the two b7 quote failures at the lexical and band-selection seams."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any

import dotenv
import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo


ROOT = Path(__file__).resolve().parents[2]
TARGET_DB = os.environ.get("S2_CORPUS_DB", "v14_s1_table_corpus")
TARGET_IDS = {"b7e932c8-index", "b7e932c8-industry"}
OUTPUT = ROOT / ".scratch/corpus-structure-restart/s2-ranking-probe.json"


def _configure() -> str:
    dotenv.load_dotenv(ROOT / ".env")
    from plugins.corpus.service import dsn

    target_dsn = make_conninfo(**{**conninfo_to_dict(dsn()), "dbname": TARGET_DB})
    os.environ["CORPUS_DSN"] = target_dsn
    os.environ["CORPUS_TARGET_DB"] = TARGET_DB
    os.environ.pop("PGOPTIONS", None)
    return target_dsn


def _load_samples() -> list[dict[str, Any]]:
    path = ROOT / ".scratch/corpus-access-validation/e5_data_delivery.py"
    spec = importlib.util.spec_from_file_location("s2_delivery", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load delivery scorer: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._load_samples("holdout", set())


def main() -> None:
    target_dsn = _configure()
    from plugins.corpus.preparation.chunk import normalize_search_text
    from plugins.corpus.preparation.negative_query import retrieval_query
    from plugins.corpus.preparation.search_pg import _rank_query_on, query_lexemes

    targets = {
        target["target_id"]: (target.get("question") or sample["question"], sample["doc_identity"])
        for sample in _load_samples()
        for target in sample.get("targets") or []
        if target.get("target_id") in TARGET_IDS
    }
    artifact: dict[str, Any] = {"target_db": TARGET_DB, "targets": {}}
    with psycopg.connect(target_dsn, autocommit=True) as conn, conn.cursor() as cur:
        for target_id, (question, source_id) in targets.items():
            cur.execute(
                "SELECT source_id FROM corpus.corpus_sources WHERE source_id LIKE %s",
                (f"%{source_id}",),
            )
            source_row = cur.fetchone()
            if source_row is None:
                raise RuntimeError(f"source not found: {source_id}")
            source_id = str(source_row[0])
            lexemes = query_lexemes(target_dsn, question, sandbox_db=TARGET_DB)
            candidate_query = retrieval_query(lexemes) or question
            rank_query = _rank_query_on(cur, normalize_search_text(candidate_query))
            cur.execute(
                """
                SELECT p.active_build_id,
                       count(c.chunk_id),
                       websearch_to_tsquery('zhcfg', %(query)s)::text,
                       bool_or(c.search_tsv @@ websearch_to_tsquery('zhcfg', %(query)s)),
                       to_tsvector('zhcfg', array_to_string(s.original_names, ' '))::text,
                       to_tsvector('zhcfg', array_to_string(s.original_names, ' '))
                         @@ websearch_to_tsquery('zhcfg', %(query)s)
                FROM corpus.corpus_publications p
                JOIN corpus.corpus_sources s ON s.source_id = p.source_id
                LEFT JOIN corpus.corpus_chunks c ON c.build_id = p.active_build_id
                WHERE p.source_id = %(source_id)s
                GROUP BY p.active_build_id, s.original_names
                """,
                {"query": normalize_search_text(candidate_query), "source_id": source_id},
            )
            debug = cur.fetchone()
            cur.execute(
                """
                WITH q AS (
                  SELECT websearch_to_tsquery('zhcfg', %(query)s) AS tsq,
                         websearch_to_tsquery('zhcfg', %(rank_query)s) AS tsq_rank
                )
                SELECT c.chunk_id, c.kind, c.unit_refs,
                       (ts_rank(c.search_tsv, q.tsq_rank)
                        + 2 * ts_rank(to_tsvector('zhcfg', array_to_string(s.original_names, ' ')),
                                      q.tsq_rank)) AS score,
                       ts_rank_cd(c.search_tsv, q.tsq_rank) AS cover_density,
                       left(c.search_text, 360) AS text
                FROM q
                JOIN corpus.corpus_chunks c ON true
                JOIN corpus.corpus_publications p ON p.active_build_id = c.build_id
                JOIN corpus.corpus_sources s ON s.source_id = p.source_id
                WHERE p.source_id = %(source_id)s
                  AND (c.search_tsv @@ q.tsq
                       OR to_tsvector('zhcfg', array_to_string(s.original_names, ' ')) @@ q.tsq)
                ORDER BY score DESC, c.chunk_id
                """,
                {
                    "query": normalize_search_text(candidate_query),
                    "rank_query": rank_query,
                    "source_id": source_id,
                },
            )
            raw_rows = cur.fetchall()
            unit_ids = sorted({str(unit_id) for row in raw_rows for unit_id in (row[2] or ())})
            cur.execute(
                """
                SELECT unit_id, location->'label_path'
                FROM corpus.corpus_units
                WHERE build_id = (
                  SELECT active_build_id FROM corpus.corpus_publications WHERE source_id = %s
                ) AND unit_id = ANY(%s::text[])
                """,
                (source_id, unit_ids),
            )
            labels_by_unit = {str(row[0]): list(row[1] or ()) for row in cur.fetchall()}
            rows = [
                {
                    "lexical_rank": index,
                    "chunk_id": str(row[0]),
                    "kind": str(row[1]),
                    "label_path": list(
                        dict.fromkeys(
                            label
                            for unit_id in (row[2] or ())
                            for label in labels_by_unit.get(str(unit_id), ())
                        )
                    ),
                    "score": float(row[3]),
                    "cover_density": float(row[4]),
                    "text": str(row[5]),
                }
                for index, row in enumerate(raw_rows, 1)
            ]
            artifact["targets"][target_id] = {
                "question": question,
                "source_id": source_id,
                "lexemes": lexemes,
                "candidate_query": candidate_query,
                "rank_query": rank_query,
                "debug": [str(value) for value in debug] if debug else None,
                "matches": len(rows),
                "body_0002": next(
                    (row for row in rows if row["chunk_id"].endswith(":body:0002")), None
                ),
                "top_20": rows[:20],
            }
    OUTPUT.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(artifact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
