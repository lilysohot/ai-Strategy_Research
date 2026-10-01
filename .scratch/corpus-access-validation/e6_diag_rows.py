"""只读：打印 3 个 absent 目标所在页的 table_row 单元全文，判断引文是否整行存在。"""
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
os.environ.pop("PGOPTIONS", None)

import psycopg  # noqa: E402
from psycopg.conninfo import conninfo_to_dict, make_conninfo  # noqa: E402

from plugins.corpus.service import dsn  # noqa: E402

CASES = [
    ("summarytable", "907957c865f6b551f70e6254a270a29b2baab31adf98d24c3250d964278432db", 2, "螺纹钢"),
    ("chart3", "fc7ab34ae8cc16e8f805096db5fb6ab7d2ec221e410a335b4d6032d4278a8519", 4, "被动补库"),
    ("table1", "fa066c5a178c02128b5058d62ccaff442fa3004bd6d43e1189f6f75257900209", 10, "光学光电子"),
]


def main() -> int:
    target = make_conninfo(**{**conninfo_to_dict(dsn()), "dbname": "e6_holdout_corpus"})
    with psycopg.connect(target) as conn:
        for name, build_id, page, probe in CASES:
            print(f"\n===== {name} :: build {build_id[:12]} page {page} =====")
            rows = conn.execute(
                "select unit_id, kind, status, coalesce(clean_view, raw_text, '') "
                "from corpus.corpus_units "
                "where build_id = %s and (location ->> 'page')::int = %s "
                "and (kind = 'table_row' or coalesce(clean_view, raw_text, '') like %s) "
                "order by ordinal",
                (build_id, page, f"%{probe}%"),
            ).fetchall()
            for r in rows:
                if probe in r[3] or r[1] == "table_row":
                    print(f"  [{r[0]}] {r[1]}/{r[2]}: {r[3]!r}")
            if not rows:
                print("  (无匹配单元)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
