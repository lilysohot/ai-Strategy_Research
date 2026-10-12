"""Quote-in-source coverage grouped by judgement (control vs suspect).

Zero model calls; read-only. Purpose: decide whether "quote not found in source"
is a property of the *candidates* or an artefact of the *lookup*. If `matched`
candidates' quotes are found at a much higher rate than `correct_extra` ones, the
lookup works and the unmatched ones are genuinely unsupported.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLAIMS = HERE.parents[2]
REPO_ROOT = HERE.parents[5]
sys.path.insert(0, str(REPO_ROOT))

import psycopg


def norm(s: str) -> str:
    return "".join(s.split())


def find_probe(conn, quote: str) -> str | None:
    q = norm(quote)
    for size in (len(q), 16, 12, 8, 6):
        p = q[:size]
        if len(p) < 6:
            break
        row = conn.execute(
            "select 1 from corpus.corpus_units where replace(raw_text, ' ', '') like %s limit 1",
            (f"%{p}%",),
        ).fetchone()
        if row:
            return p
    return None


def main() -> None:
    ws = json.loads((CLAIMS / "adjudication" / "worksheet.json").read_text(encoding="utf-8"))
    conn = psycopg.connect(
        "postgresql://postgres:postgres@127.0.0.1:5432/e6_holdout_corpus", autocommit=True
    )
    stat: collections.Counter = collections.Counter()
    for r in ws["records"]:
        q = (r.get("evidence") or {}).get("quote", "") or ""
        if not q:
            stat[(r["judgement"], "no_quote")] += 1
            continue
        stat[(r["judgement"], "hit" if find_probe(conn, q) else "miss")] += 1
    for k in sorted(stat):
        print(k, stat[k])


if __name__ == "__main__":
    main()
