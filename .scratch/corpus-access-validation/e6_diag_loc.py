"""只读：核对 e6_holdout_corpus 中 corpus_units 表与 build 存在性。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

import dotenv  # noqa: E402

dotenv.load_dotenv(ROOT / ".env")
os.environ["CORPUS_TARGET_DB"] = "e6_holdout_corpus"

import psycopg  # noqa: E402

from plugins.corpus.service import dsn  # noqa: E402

BUILD = "907957c865f6b551f70e6254a270a29b2baab31adf98d24c3250d964278432db"


def main() -> int:
    with psycopg.connect(dsn()) as conn:
        tables = conn.execute(
            "select table_schema, table_name from information_schema.tables "
            "where table_schema in ('corpus', 'public') order by 1, 2"
        ).fetchall()
        print("表:", tables)
        for tbl in ("corpus.corpus_units", "corpus.builds"):
            try:
                n = conn.execute(f"select count(*) from {tbl}").fetchone()[0]
                print(f"{tbl} 总行数: {n}")
            except Exception as exc:  # noqa: BLE001
                print(f"{tbl} ERR: {exc}")
        builds = conn.execute(
            "select build_id from corpus.corpus_units group by build_id order by 1"
        ).fetchall() if any(t[1] == "corpus_units" for t in tables) else []
        print("库内 build_id 列表:", [b[0][:16] for b in builds])
        hit = conn.execute(
            "select count(*) from corpus.corpus_units where build_id = %s", (BUILD,)
        ).fetchone()[0]
        print(f"目标 build {BUILD[:16]} 单元数: {hit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
