"""Read-only S1 inspection for the two table-relation holdout targets."""

from __future__ import annotations

import json
import os
from pathlib import Path

import dotenv
import psycopg
import pymupdf
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from plugins.corpus.preparation.readers import pdf_reader as pr
from plugins.corpus.preparation.readers import read_document
from plugins.corpus.service import dsn

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / ".scratch/corpus-access-validation"
CASES = {
    "f86c6d2c-cxotable": (
        "f86c6d2c054a835de4de3707c984529580e8ce57628d59f60b6aeca7a0f61fd2",
        4,
    ),
    "f3b28791-table1": (
        "f3b28791e1355dc371206b10a003dc2ef6c65f88f631c77ea7578be145f28279",
        10,
    ),
}


def main() -> int:
    dotenv.load_dotenv(ROOT / ".env")
    os.environ.pop("PGOPTIONS", None)
    target_dsn = make_conninfo(**{**conninfo_to_dict(dsn()), "dbname": "e6_holdout_corpus"})
    inventory = json.loads((HERE / "e2-inventory.json").read_text(encoding="utf-8"))
    file_by_hash = {row["sha256"]: row["file"] for row in inventory["entries"]}
    for target_id, (source_id, page_no) in CASES.items():
        path = ROOT / "data/corpus" / file_by_hash[source_id]
        print(f"\n===== {target_id} page={page_no} file={path.name} =====")
        result = read_document(path)
        for unit in result.units:
            if unit.location.page == page_no:
                print(
                    f"unit {unit.ordinal} {unit.kind} cells={unit.location.cells} "
                    f"labels={unit.location.label_path} text={unit.raw_text!r}"
                )
        with pymupdf.open(path) as document:
            page = document[page_no - 1]
            words = [
                word
                for word in page.get_text("words")
                if any(token in str(word[4]) for token in ("H1", "营业", "收入", "2026"))
            ]
            print("matching words:", words)
            lines = pr._page_lines(page)
            tables, issues = pr._extract_tables(page, lines)
            print("issues:", [(issue.code, issue.detail) for issue in issues])
            for table in tables:
                print(
                    f"table {table.index} bbox={table.bbox} groups={len(pr._native_groups(table))}"
                )
                if table.model is None:
                    print("  no model")
                    continue
                print("  headers:", table.model.header_rows)
                for row_index, row in enumerate(table.model.grid):
                    print(f"  grid[{row_index}]={row}")
        with psycopg.connect(target_dsn) as connection:
            build_id = connection.execute(
                "select active_build_id from corpus.corpus_publications where source_id=%s",
                (source_id,),
            ).fetchone()[0]
            chunks = connection.execute(
                "select c.chunk_id,c.unit_refs,c.context_refs,c.search_text "
                "from corpus.corpus_chunks c where c.build_id=%s and exists ("
                "select 1 from corpus.corpus_units u where u.build_id=c.build_id "
                "and u.unit_id=any(c.unit_refs) and (u.location->>'page')::int=%s) "
                "order by c.chunk_id",
                (build_id, page_no),
            ).fetchall()
            for chunk_id, unit_refs, context_refs, search_text in chunks:
                rows = connection.execute(
                    "select ordinal,kind,raw_text,location from corpus.corpus_units "
                    "where build_id=%s and unit_id=any(%s) order by ordinal",
                    (build_id, unit_refs),
                ).fetchall()
                print(
                    f"chunk {chunk_id} context={context_refs} search={search_text[:160]!r} "
                    f"units={[(row[0], row[1], row[2][:80], row[3].get('label_path')) for row in rows]}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
