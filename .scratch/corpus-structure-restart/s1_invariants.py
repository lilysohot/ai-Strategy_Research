"""Compare control and S1 persisted units while allowing label_path changes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import dotenv
import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / ".scratch/corpus-structure-restart"
CONTROL_DB = "e6_holdout_corpus"
CANDIDATE_DB = "v14_s1_table_corpus"


def _dsn(database: str) -> str:
    from plugins.corpus.service import dsn

    return make_conninfo(**{**conninfo_to_dict(dsn()), "dbname": database})


def _units(database: str, source_id: str) -> tuple[str, list[dict[str, Any]]]:
    with psycopg.connect(_dsn(database)) as connection:
        build_id = connection.execute(
            "select active_build_id from corpus.corpus_publications where source_id=%s",
            (source_id,),
        ).fetchone()[0]
        rows = connection.execute(
            "select ordinal,kind,status,reasons,raw_text,location from corpus.corpus_units "
            "where build_id=%s order by ordinal",
            (build_id,),
        ).fetchall()
    return build_id, [
        {
            "ordinal": row[0],
            "kind": row[1],
            "status": row[2],
            "reasons": row[3],
            "raw_text": row[4],
            "location": row[5],
        }
        for row in rows
    ]


def _without_labels(row: dict[str, Any]) -> dict[str, Any]:
    clone = {**row, "location": dict(row["location"])}
    clone["location"].pop("label_path", None)
    return clone


def main() -> None:
    dotenv.load_dotenv(ROOT / ".env")
    os.environ.pop("PGOPTIONS", None)
    build = json.loads((HERE / "s1-candidate-build.json").read_text(encoding="utf-8"))
    sources = []
    all_stable = True
    for source in build["sources"]:
        source_id = source["source_id"]
        control_build, control = _units(CONTROL_DB, source_id)
        candidate_build, candidate = _units(CANDIDATE_DB, source_id)
        stable = [_without_labels(row) for row in control] == [
            _without_labels(row) for row in candidate
        ]
        label_changes = sum(
            left["location"].get("label_path") != right["location"].get("label_path")
            for left, right in zip(control, candidate, strict=True)
        )
        all_stable &= stable
        sources.append(
            {
                "sample_id": source["sample_id"],
                "source_id": source_id,
                "control_build_id": control_build,
                "candidate_build_id": candidate_build,
                "unit_count": len(candidate),
                "raw_order_coordinates_stable": stable,
                "label_path_changes": label_changes,
            }
        )
    result = {
        "artifact": "s1-unit-invariants",
        "control_db": CONTROL_DB,
        "candidate_db": CANDIDATE_DB,
        "sources": sources,
        "summary": {
            "sources": len(sources),
            "raw_order_coordinates_stable": all_stable,
            "label_path_changes": sum(row["label_path_changes"] for row in sources),
        },
    }
    output = HERE / "s1-unit-invariants.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"artifact={output}")
    raise SystemExit(0 if all_stable else 1)


if __name__ == "__main__":
    main()
