"""Audit S2 persisted units against S1 while allowing fragment regrouping."""

from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
from typing import Any

import dotenv
import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / ".scratch/corpus-structure-restart"
CONTROL_DB = "v14_s1_table_corpus"
CANDIDATE_DB = "v14_s2_quote_corpus"
QUOTE = "螺纹钢元/吨32400.9%4.2%-2.4%-0.6%6000"


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
    return str(build_id), [
        {
            "ordinal": int(row[0]),
            "kind": str(row[1]),
            "status": str(row[2]),
            "reasons": tuple(row[3] or ()),
            "raw_text": str(row[4]),
            "location": dict(row[5]),
        }
        for row in rows
    ]


def _norm(text: str) -> str:
    return "".join(character for character in text if not character.isspace())


def _page_counters(units: list[dict[str, Any]]) -> dict[int | None, Counter[str]]:
    out: dict[int | None, Counter[str]] = {}
    for unit in units:
        page = unit["location"].get("page")
        out.setdefault(page, Counter()).update(_norm(unit["raw_text"]))
    return out


def _page_sequences(units: list[dict[str, Any]]) -> dict[int | None, str]:
    out: dict[int | None, list[str]] = {}
    for unit in units:
        out.setdefault(unit["location"].get("page"), []).append(_norm(unit["raw_text"]))
    return {page: "".join(parts) for page, parts in out.items()}


def _non_table(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "kind": unit["kind"],
            "status": unit["status"],
            "reasons": unit["reasons"],
            "raw_text": unit["raw_text"],
            "location": {
                key: value
                for key, value in unit["location"].items()
                if key not in {"label_path", "cells"}
            },
        }
        for unit in units
        if unit["kind"] != "table_row"
    ]


def main() -> None:
    dotenv.load_dotenv(ROOT / ".env")
    os.environ.pop("PGOPTIONS", None)
    build = json.loads((HERE / "s2-candidate-build.json").read_text(encoding="utf-8"))
    sources = []
    for source in build["sources"]:
        source_id = source["source_id"]
        control_build, control = _units(CONTROL_DB, source_id)
        candidate_build, candidate = _units(CANDIDATE_DB, source_id)
        control_sequences = _page_sequences(control)
        candidate_sequences = _page_sequences(candidate)
        changed_pages = sorted(
            str(page)
            for page in set(control_sequences) | set(candidate_sequences)
            if control_sequences.get(page) != candidate_sequences.get(page)
        )
        sources.append(
            {
                "sample_id": source["sample_id"],
                "source_id": source_id,
                "control_build_id": control_build,
                "candidate_build_id": candidate_build,
                "unit_count": [len(control), len(candidate)],
                "table_unit_count": [
                    sum(unit["kind"] == "table_row" for unit in control),
                    sum(unit["kind"] == "table_row" for unit in candidate),
                ],
                "character_multiset_stable_by_page": (
                    _page_counters(control) == _page_counters(candidate)
                ),
                "non_table_units_stable": _non_table(control) == _non_table(candidate),
                "page_sequence_changed": changed_pages,
                "target_quote_present": (
                    any(QUOTE in _norm(unit["raw_text"]) for unit in candidate)
                    if source["sample_id"] == "holdout-industry-003"
                    else None
                ),
            }
        )
    result = {
        "artifact": "s2-unit-invariants",
        "control_db": CONTROL_DB,
        "candidate_db": CANDIDATE_DB,
        "sources": sources,
        "summary": {
            "sources": len(sources),
            "character_multiset_stable_by_page": all(
                row["character_multiset_stable_by_page"] for row in sources
            ),
            "non_table_units_stable": all(row["non_table_units_stable"] for row in sources),
            "sources_with_page_sequence_changes": [
                row["sample_id"] for row in sources if row["page_sequence_changed"]
            ],
            "target_quote_present": next(
                row["target_quote_present"]
                for row in sources
                if row["sample_id"] == "holdout-industry-003"
            ),
        },
    }
    output = HERE / "s2-unit-invariants.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"artifact={output}")
    ok = (
        result["summary"]["character_multiset_stable_by_page"]
        and result["summary"]["non_table_units_stable"]
        and result["summary"]["target_quote_present"]
    )
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
