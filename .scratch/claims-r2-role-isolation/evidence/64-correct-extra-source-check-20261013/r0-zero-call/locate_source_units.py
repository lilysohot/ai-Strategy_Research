"""Locate the source document's units inside the corpus DB.

The snapshot that fed the extraction run is not present in the DB (0 rows for its
build_id), so we locate the same document by probing for segment text carried by the
candidates themselves. Read-only, zero model calls.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[5]
sys.path.insert(0, str(REPO_ROOT))

import psycopg

PROBES = (
    "美元短贷",
    "保理额度收紧",
    "利润增速回到收入增速",
    "存货继续堆",
    "中期不分红",
    "利润质量相对扣非是干净的",
)


def main() -> None:
    conn = psycopg.connect(
        "postgresql://postgres:postgres@127.0.0.1:5432/e6_holdout_corpus", autocommit=True
    )
    for p in PROBES:
        rows = conn.execute(
            "select build_id, unit_id, length(raw_text) from corpus.corpus_units "
            "where replace(raw_text, ' ', '') like %s limit 3",
            (f"%{p}%",),
        ).fetchall()
        print(p, "->", [(r[0][:12], r[1][:16], r[2]) for r in rows])


if __name__ == "__main__":
    main()
