"""只读诊断：5 项 quote_not_delivered 的根因归属层。

对每项：
1) expected_quote 归一经；
2) 源 PDF 页 get_text() 是否含 %/-（区分源页丢失 vs reader 提取丢失）；
3) kept 单元 raw_text 是否含 %/-（L2 提取层）；
4) 送达 chunk 文本是否含引文（L7/L8 送达层，比对为何失败）。
"""
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

import pymupdf  # noqa: E402

WS = re.compile(r"\s+")


def norm(s):
    return WS.sub("", s or "")


# 目标 -> (源PDF, 证据页, 引文)
CASES = {
    "c1ddcd8a-summarytable": (
        "c1ddcd8aecb80e39c555459e3ea007db1419ed9f3b844724ac90fc65bda8a885.pdf", 2,
        "螺纹钢 元/吨 3240 0.9% 4.2% -2.4% -0.6% 6000"),
    "c1ddcd8a-realestate": (
        "c1ddcd8aecb80e39c555459e3ea007db1419ed9f3b844724ac90fc65bda8a885.pdf", 1,
        "地产竣工链条：钛白粉、玻璃价格处于低位水平。 本周钛白粉、玻璃的价格环比分别-0.36%、-0.97%，平板玻璃本周开工率 67.19%。"),
    "b7e932c8-index": (
        "b7e932c80e88d00931374d29ab8a786e4dc42cd194309f126301f58192e5d160.pdf", 2,
        "本周主要宽基指数普遍下跌 ，上证综指、东财全A分别下跌0.56%、1.20%，沪深300下跌1.33%；成长风格方面 ，创业板指下跌 4.03%，科创50下跌5.10%"),
    "b7e932c8-industry": (
        "b7e932c80e88d00931374d29ab8a786e4dc42cd194309f126301f58192e5d160.pdf", 2,
        "行业层面 ，本周申万 31个行业中 14个录得正收益 ，机构低配板块表现居前 ，传媒、银行和农林牧渔涨幅居前 ，分别上涨 6.0%、4.0%、3.3%；电子、有色金属和建筑材料表现较弱，分别下跌5.4%、5.0%、4.3%。"),
    "f3b28791-table1": (
        "f3b28791e1355dc371206b10a003dc2ef6c65f88f631c77ea7578be145f28279.pdf", 10,
        "板块 一级行业 二级行业 7 月以来 2026E 净利润上修幅度 2026 年预测净利润增速 7 月以来 涨跌幅 年初以来 涨跌幅 龙一 龙二 龙三 AI 算力硬件 电子 光学光电子 27.1% 194% -29.6% 6.9% 京东方A 惠科股份 TCL科技"),
}

ARCHIVE = HERE / "e6-holdout-archive"
BUILD_RESULT = json.loads((HERE / "e6-holdout-build.json").read_text(encoding="utf-8"))
BUILDS = {s["sample_id"]: s["build_id"] for s in BUILD_RESULT["sources"]}
# sample -> build 映射
SAMPLE_OF = {
    "c1ddcd8a-summarytable": "holdout-industry-003",
    "c1ddcd8a-realestate": "holdout-industry-003",
    "b7e932c8-index": "holdout-industry-004",
    "b7e932c8-industry": "holdout-industry-004",
    "f3b28791-table1": "holdout-macro-012",
}


def main() -> int:
    target = make_conninfo(**{**conninfo_to_dict(dsn()), "dbname": "e6_holdout_corpus"})
    conn = psycopg.connect(target)
    for tgt_id, (pdf_name, page, quote) in CASES.items():
        print(f"\n===== {tgt_id} (page {page}) =====")
        pdf = next(ARCHIVE.rglob(pdf_name))
        doc = pymupdf.open(pdf)
        pg_text = doc[page - 1].get_text("text")
        print(f"  源页含'%'字符数: {pg_text.count('%')}  含'-'字符数: {pg_text.count('-')}")
        # 引文中的关键 token 在源页是否可逐字找到（去空白后）
        qn = norm(quote)
        src_n = norm(pg_text)
        print(f"  整条引文在源页(norm): {qn in src_n}")
        doc.close()

        bid = BUILDS[SAMPLE_OF[tgt_id]]
        rows = conn.execute(
            "select unit_id, kind, status, raw_text from corpus.corpus_units "
            "where build_id = %s and status='kept'",
            (bid,),
        ).fetchall()
        # 提取层：kept 单元文本是否含 %
        kept_all = "".join(norm(r[3] or "") for r in rows)
        print(f"  kept 单元含'%': {kept_all.count('%')}  整条引文在 kept(norm): {qn in kept_all}")
        # 找含引文片段的单元
        frags = [f for f in qn.split("；") if len(f) >= 4]
        for r in rows[:0]:
            pass
        hit = [r for r in rows if any(f in norm(r[3] or "") for f in frags[:1])]
        for r in hit[:2]:
            print(f"    [{r[0]}] {r[1]} len={len(r[3])}: {r[3][:110]!r}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
