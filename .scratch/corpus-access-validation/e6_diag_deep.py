"""只读：深挖 summarytable/table1 提取缺失细节 + 3 项送达层失败原因。"""
from __future__ import annotations

import json
import os
import re
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

WS = re.compile(r"\s+")


def norm(s):
    return WS.sub("", s or "")


BUILD_RESULT = json.loads((HERE / "e6-holdout-build.json").read_text(encoding="utf-8"))
SAMPLE_OF = {
    "c1ddcd8a-summarytable": "holdout-industry-003",
    "c1ddcd8a-realestate": "holdout-industry-003",
    "b7e932c8-index": "holdout-industry-004",
    "b7e932c8-industry": "holdout-industry-004",
    "f3b28791-table1": "holdout-macro-012",
}
BID = {s["sample_id"]: s["build_id"] for s in BUILD_RESULT["sources"]}

SUMMARY_QUOTE = "螺纹钢 元/吨 3240 0.9% 4.2% -2.4% -0.6% 6000"
TABLE1_QUOTE = "板块 一级行业 二级行业 7 月以来 2026E 净利润上修幅度 2026 年预测净利润增速 7 月以来 涨跌幅 年初以来 涨跌幅 龙一 龙二 龙三 AI 算力硬件 电子 光学光电子 27.1% 194% -29.6% 6.9% 京东方A 惠科股份 TCL科技"


def main() -> int:
    target = make_conninfo(**{**conninfo_to_dict(dsn()), "dbname": "e6_holdout_corpus"})
    conn = psycopg.connect(target)

    # 1) summarytable：找 page 2 的 kept 单元里含「螺纹钢」的
    bid = BID["holdout-industry-003"]
    rows = conn.execute(
        "select unit_id, kind, status, raw_text, location from corpus.corpus_units "
        "where build_id = %s and status='kept'",
        (bid,),
    ).fetchall()
    print(f"===== summarytable (build {bid[:12]}) =====")
    qn = norm(SUMMARY_QUOTE)
    for r in rows:
        if "螺纹钢" in (r[3] or ""):
            print(f"  [{r[0]}] page={r[4].get('page')} kind={r[1]} len={len(r[3])}: {r[3]!r}")
    # 引文各 token 是否在 kept
    for tok in ["0.9%", "4.2%", "-2.4%", "-0.6%", "6000", "螺纹钢", "元/吨", "3240"]:
        hit = [r[0] for r in rows if norm(tok) in norm(r[3] or "")]
        print(f"  token {tok!r}: {len(hit)} 个单元 {hit[:5]}")

    # 2) table1：page 10 kept 单元
    bid2 = BID["holdout-macro-012"]
    rows2 = conn.execute(
        "select unit_id, kind, status, raw_text, location from corpus.corpus_units "
        "where build_id = %s and status='kept'",
        (bid2,),
    ).fetchall()
    print(f"\n===== table1 (build {bid2[:12]}) =====")
    qn2 = norm(TABLE1_QUOTE)
    for r in rows2:
        if r[4].get("page") == 10 and (r[1] == "table_row" or "光学光电子" in (r[3] or "")):
            print(f"  [{r[0]}] page=10 kind={r[1]} len={len(r[3])}: {r[3][:120]!r}")
    for tok in ["27.1%", "194%", "-29.6%", "6.9%", "京东方", "惠科", "光学光电子", "AI"]:
        hit = [r[0] for r in rows2 if norm(tok) in norm(r[3] or "")]
        print(f"  token {tok!r}: {len(hit)} 个单元 {hit[:5]}")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
