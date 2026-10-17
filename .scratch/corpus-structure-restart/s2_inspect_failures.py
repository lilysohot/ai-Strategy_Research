"""Read-only source/unit/chunk inspection for the S2 quote failures."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import dotenv
import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[2]
REPRO = ROOT / ".scratch/corpus-structure-restart/s2-quote-repro.json"
TARGET_DB = "v14_s1_table_corpus"
MARKERS = {
    "c1ddcd8a-summarytable": "螺纹钢",
    "b7e932c8-index": "本周主要宽基指数",
    "b7e932c8-industry": "行业层面",
}
_WS = re.compile(r"[\s\u3000\xa0\u200b]+")


def _norm(value: object) -> str:
    return _WS.sub("", str(value or ""))


def _target_dsn() -> str:
    from plugins.corpus.service import dsn

    return make_conninfo(**{**conninfo_to_dict(dsn()), "dbname": TARGET_DB})


def _units(connection: psycopg.Connection[Any], build_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        "select unit_id,ordinal,kind,raw_text,location from corpus.corpus_units "
        "where build_id=%s order by ordinal",
        (build_id,),
    ).fetchall()
    return [
        {
            "unit_id": row[0],
            "ordinal": row[1],
            "kind": row[2],
            "raw_text": row[3],
            "location": row[4],
        }
        for row in rows
    ]


def main() -> None:
    dotenv.load_dotenv(ROOT / ".env")
    os.environ.pop("PGOPTIONS", None)
    repro = json.loads(REPRO.read_text(encoding="utf-8"))
    definition_by_id = {row["target_id"]: row for row in repro["definitions"]}
    result_by_id = {row["target_id"]: row for row in repro["results"]}
    findings = []
    with psycopg.connect(_target_dsn()) as connection:
        for target_id in sorted(MARKERS):
            definition = definition_by_id[target_id]
            result = result_by_id[target_id]
            source_id = str(result["doc_identity"])
            build_id = connection.execute(
                "select active_build_id from corpus.corpus_publications where source_id=%s",
                (source_id,),
            ).fetchone()[0]
            units = _units(connection, build_id)
            marker = MARKERS[target_id]
            matching = [index for index, unit in enumerate(units) if marker in unit["raw_text"]]
            neighbors = []
            for index in matching:
                neighbors.extend(units[max(0, index - 2) : index + 3])
            neighbor_ids = list(dict.fromkeys(unit["unit_id"] for unit in neighbors))
            chunks = connection.execute(
                "select chunk_id,unit_refs,context_refs,search_text from corpus.corpus_chunks "
                "where build_id=%s and unit_refs && %s order by chunk_id",
                (build_id, neighbor_ids),
            ).fetchall()
            delivered = set(result["delivered_locators"])
            quote = str(definition["verbatim_quote"])
            full_text = "\n".join(unit["raw_text"] for unit in units)
            tokens = [_norm(token) for token in quote.split() if len(_norm(token)) >= 2]
            findings.append(
                {
                    "target_id": target_id,
                    "source_id": source_id,
                    "build_id": build_id,
                    "quote": quote,
                    "quote_exact_in_full_units": _norm(quote) in _norm(full_text),
                    "missing_tokens_in_full_units": [
                        token for token in tokens if token not in _norm(full_text)
                    ],
                    "matching_ordinals": [units[index]["ordinal"] for index in matching],
                    "neighbor_units": neighbors,
                    "neighbor_chunks": [
                        {
                            "chunk_id": row[0],
                            "delivered": f"chunk:{row[0]}" in delivered,
                            "unit_refs": row[1],
                            "context_refs": row[2],
                            "search_text": row[3],
                        }
                        for row in chunks
                    ],
                }
            )
    output = ROOT / ".scratch/corpus-structure-restart/s2-failure-inspection.json"
    output.write_text(json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8")
    for finding in findings:
        print("\n===", finding["target_id"], "===")
        print("exact_full", finding["quote_exact_in_full_units"])
        print("missing_full", finding["missing_tokens_in_full_units"])
        for unit in finding["neighbor_units"]:
            print(
                "unit",
                unit["ordinal"],
                unit["kind"],
                unit["location"].get("page"),
                repr(unit["raw_text"]),
            )
        for chunk in finding["neighbor_chunks"]:
            print("chunk", chunk["chunk_id"], "delivered", chunk["delivered"])
            print(repr(chunk["search_text"]))
    print(f"artifact={output}")


if __name__ == "__main__":
    main()
