"""只读查询隔离库：absent 目标所在页的实际提取单元，判断引文为何未送达。"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
import os

import dotenv  # noqa: E402

dotenv.load_dotenv(ROOT / ".env")
os.environ["CORPUS_TARGET_DB"] = "e6_holdout_corpus"

import psycopg  # noqa: E402

from plugins.corpus.service import dsn  # noqa: E402

BUILDS = {
    "summarytable": ("907957c865f6b551f70e6254a270a29b2baab31adf98d24c3250d964278432db", 2),
    "chart3": ("fc7ab34ae8cc16e8f805096db5fb6ab7d2ec221e410a335b4d6032d4278a8519", 4),
    "table1": ("fa066c5a178c02128b5058d62ccaff442fa3004bd6d43e1189f6f75257900209", 10),
}

PROBES = {
    "summarytable": ["螺纹钢", "3240", "6000", "0.9%"],
    "chart3": ["被动补库", "万得全", "南华商品", "1.83", "0.29"],
    "table1": ["光学光电子", "27.1%", "京东方", "惠科", "27.1"],
}


def main() -> int:
    with psycopg.connect(dsn()) as conn:
        for name, (build_id, page) in BUILDS.items():
            print(f"\n===== {name} :: build {build_id[:12]} page {page} =====")
            rows = conn.execute(
                "select unit_id, kind, status, coalesce(clean_view, raw_text, ''), "
                "(location ->> 'page') "
                "from corpus.corpus_units where build_id = %s "
                "and (location ->> 'page') = %s order by ordinal",
                (build_id, str(page)),
            ).fetchall()
            print(f"  该页单元数: {len(rows)}")
            from collections import Counter

            kinds = Counter(r[1] for r in rows)
            print(f"  类型分布: {dict(kinds)}")
            for probe in PROBES[name]:
                hit = [(r[0], r[1], r[2], r[4]) for r in rows if probe in r[3]]
                print(f"  probe {probe!r}: {len(hit)} 命中 -> {hit[:5]}")
            # 打印若干 table_row / paragraph 文本样例
            for r in rows[:6]:
                text = r[3].replace("\n", " ")[:80]
                print(f"    [{r[4]}] {r[1]}/{r[2]}: {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
