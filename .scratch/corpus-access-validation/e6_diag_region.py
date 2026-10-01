"""只读：验证 M2/M3 证据页是否满足 region 证明（精确 quote in raw_text + bbox 与图像不相交）。"""
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

import pymupdf  # noqa: E402

ARCHIVE = HERE / "e6-holdout-archive"

BUILDS = {
    "holdout-industry-004": "590bb1199568dd8a78083d2b6dc856c7b3b9cff32a2b8a811c34a3820ea23814",
    "holdout-industry-006": "00b99a5809fc5dd51f29588f10778e90f8a579ef68cf2bfe4a3710ba926e4af7",
}

# (pdf, page, quote)
CASES = [
    ("holdout-industry-004",
     "b7e932c80e88d00931374d29ab8a786e4dc42cd194309f126301f58192e5d160.pdf", 2,
     "本周主要宽基指数普遍下跌 ，上证综指、东财全A分别下跌0.56%、1.20%，沪深300下跌1.33%；成长风格方面 ，创业板指下跌 4.03%，科创50下跌5.10%"),
    ("holdout-industry-004",
     "b7e932c80e88d00931374d29ab8a786e4dc42cd194309f126301f58192e5d160.pdf", 2,
     "行业层面 ，本周申万 31个行业中 14个录得正收益 ，机构低配板块表现居前 ，传媒、银行和农林牧渔涨幅居前 ，分别上涨 6.0%、4.0%、3.3%；电子、有色金属和建筑材料表现较弱，分别下跌5.4%、5.0%、4.3%。"),
    ("holdout-industry-004",
     "b7e932c80e88d00931374d29ab8a786e4dc42cd194309f126301f58192e5d160.pdf", 3,
     "国家统计局发布数据显示 ，8月制造业采购经理指数 （PMI）为49.8%，较上月上升0.6个百分点；生产指数和新订单指数分别为 50.4%和50.6%，均位于扩张区间"),
    ("holdout-industry-004",
     "b7e932c80e88d00931374d29ab8a786e4dc42cd194309f126301f58192e5d160.pdf", 7,
     "电子 -5.4% -5.5% 1800 5394 8006 169.3% 48.6% 2.8% 6.8% 1.0% 4.0%"),
    ("holdout-industry-006",
     "f86c6d2c054a835de4de3707c984529580e8ce57628d59f60b6aeca7a0f61fd2.pdf", 6,
     "2026H1，两款 GLP-1 减重降糖大单品替尔泊肽、司美格鲁肽全球销售额合计超 450 亿美元， 分别登顶全球药品销售额第一名/第二名。"),
    ("holdout-industry-006",
     "f86c6d2c054a835de4de3707c984529580e8ce57628d59f60b6aeca7a0f61fd2.pdf", 3,
     "2026H1 年 20 家 CXO 企业合计实现收入 562 亿元，同比+24.5%，合计实现归母净利润 132 亿元，同比+17%；2026 年 Q2 共实现营业收入 307 亿元， 同比+29.4%， 合计实现归母净利润73 亿元，同比+13%。"),
]


def disjoint(box, image):
    x0, y0, x1, y1 = box
    i0, j0, i1, j1 = image
    return x1 < i0 or i1 < x0 or y1 < j0 or j1 < y0


def main() -> int:
    target = make_conninfo(**{**conninfo_to_dict(dsn()), "dbname": "e6_holdout_corpus"})
    conn = psycopg.connect(target)
    for sample, pdf_name, page, quote in CASES:
        print(f"\n===== {sample} page {page} =====")
        pdf = next(ARCHIVE.rglob(pdf_name))
        doc = pymupdf.open(pdf)
        pg = doc[page - 1]
        images = [tuple(i["bbox"]) for i in pg.get_image_info()]
        print(f"  images({len(images)}): {[tuple(round(x,1) for x in b) for b in images]}")
        rows = conn.execute(
            "select unit_id, kind, raw_text, location from corpus.corpus_units "
            "where build_id = %s and status='kept' and (location ->> 'page')::int = %s",
            (BUILDS[sample], page),
        ).fetchall()
        exact = [r for r in rows if quote in (r[2] or "")]
        print(f"  精确 quote in raw_text 的 kept 单元: {len(exact)}")
        for r in exact:
            box = tuple(r[3].get("bbox"))
            imgs_overlap = [b for b in images if not disjoint(box, b)]
            print(f"    [{r[0]}] kind={r[1]} len={len(r[2])} bbox={tuple(round(x,1) for x in box)} "
                  f"与图像相交: {len(imgs_overlap)}")
        if not exact:
            norm_q = "".join(quote.split())
            partial = [r for r in rows if any(tok and tok in "".join((r[2] or "").split()) for tok in norm_q.split("；")[:2])]
            print(f"  (无精确命中) 近似命中 {len(partial)} 个")
        doc.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
