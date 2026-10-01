"""只读：打印 chart3(page4) / table1(page10) 命中 probe 的单元全文。"""
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
    ("chart3", "fc7ab34ae8cc16e8f805096db5fb6ab7d2ec221e410a335b4d6032d4278a8519", 4,
     ["被动补库", "万得全", "南华商品", "1.83", "0.29", "沪深"]),
    ("table1", "fa066c5a178c02128b5058d62ccaff442fa3004bd6d43e1189f6f75257900209", 10,
     ["光学光电子", "27.1", "京东方", "惠科", "TCL", "上修"]),
]


def main() -> int:
    target = make_conninfo(**{**conninfo_to_dict(dsn()), "dbname": "e6_holdout_corpus"})
    with psycopg.connect(target) as conn:
        for name, build_id, page, probes in CASES:
            print(f"\n===== {name} :: build {build_id[:12]} page {page} =====")
            rows = conn.execute(
                "select unit_id, kind, status, coalesce(clean_view, raw_text, '') "
                "from corpus.corpus_units "
                "where build_id = %s and (location ->> 'page')::int = %s order by ordinal",
                (build_id, page),
            ).fetchall()
            for probe in probes:
                hits = [r for r in rows if probe in r[3]]
                print(f"  probe {probe!r}: {len(hits)} 单元")
                for r in hits:
                    print(f"    [{r[0]}] {r[1]}/{r[2]}: {r[3]!r}")
            # 全页 table_row 打印
            print("  -- 全部 table_row --")
            for r in rows:
                if r[1] == "table_row":
                    print(f"    [{r[0]}] {r[1]}/{r[2]}: {r[3]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
