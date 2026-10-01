"""只读：用与预筛一致的查询核验 3 个 absent 目标所在页的实际提取。"""
from __future__ import annotations

import os
import sys
from collections import Counter
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

CASES = {
    "summarytable": ("907957c865f6b551f70e6254a270a29b2baab31adf98d24c3250d964278432db", [1, 2, 3]),
    "chart3": ("fc7ab34ae8cc16e8f805096db5fb6ab7d2ec221e410a335b4d6032d4278a8519", [1, 4]),
    "table1": ("fa066c5a178c02128b5058d62ccaff442fa3004bd6d43e1189f6f75257900209", [8, 10]),
}


def main() -> int:
    target = make_conninfo(**{**conninfo_to_dict(dsn()), "dbname": "e6_holdout_corpus"})
    with psycopg.connect(target) as conn:
        sample = conn.execute(
            "select unit_id, kind, status, location, left(coalesce(clean_view, raw_text, ''), 60) "
            "from corpus.corpus_units "
            "where build_id = %s order by ordinal limit 2",
            (next(iter(CASES.values()))[0],),
        ).fetchall()
        print("样例单元:")
        for r in sample:
            print("  unit_id:", r[0], "kind:", r[1], "status:", r[2])
            print("  location:", r[3])
            print("  text:", repr(r[4]))
        print()
        for name, (build_id, pages) in CASES.items():
            print(f"===== {name} :: build {build_id[:12]} =====")
            for page in pages:
                rows = conn.execute(
                    "select unit_id, kind, status, coalesce(clean_view, raw_text, '') "
                    "from corpus.corpus_units "
                    "where build_id = %s and (location ->> 'page')::int = %s order by ordinal",
                    (build_id, page),
                ).fetchall()
                kinds = Counter(r[1] for r in rows)
                statuses = Counter(r[2] for r in rows)
                print(f"  page {page}: units={len(rows)} kinds={dict(kinds)} status={dict(statuses)}")
                for probe in ("螺纹钢", "3240", "被动补库", "万得全", "光学光电子", "27.1", "京东方"):
                    hit = [r[0] for r in rows if probe in r[3]]
                    if hit:
                        print(f"    probe {probe!r}: {len(hit)} 个单元")
                if rows:
                    print("    样例:", [(r[1], r[3][:50].replace("\n", " ")) for r in rows[:3]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
