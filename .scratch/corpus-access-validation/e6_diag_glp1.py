"""只读：确认 M3 页6 glp1 证据单元 bbox 与该页图像不相交（region 证明可行性）。"""
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
BUILD = "3cc347ca9ed8d18af25b6e8db1e7e40b52f1d46e1a8a03a30d0f8e5c7b6d2a123"[:0] or None

# 读取最新 build_id
import json  # noqa: E402

d = json.loads((HERE / "e6-holdout-build.json").read_text(encoding="utf-8"))
for s in d["sources"]:
    if s["sample_id"] == "holdout-industry-006":
        BUILD = s["build_id"]
PDF = ARCHIVE / "f8" / "f86c6d2c054a835de4de3707c984529580e8ce57628d59f60b6aeca7a0f61fd2.pdf"
QUOTE = "2026H1，两款 GLP-1 减重降糖大单品替尔泊肽、司美格鲁肽全球销售额合计超 450 亿美元， 分别登顶全球药品销售额第一名/第二名。"


def main() -> int:
    print("build:", BUILD)
    target = make_conninfo(**{**conninfo_to_dict(dsn()), "dbname": "e6_holdout_corpus"})
    conn = psycopg.connect(target)
    rows = conn.execute(
        "select unit_id, kind, status, raw_text, location from corpus.corpus_units "
        "where build_id = %s and status='kept' and (location ->> 'page')::int = 6",
        (BUILD,),
    ).fetchall()
    exact = [r for r in rows if QUOTE in (r[3] or "")]
    print(f"页6 kept 单元数={len(rows)} 精确引文命中={len(exact)}")
    doc = pymupdf.open(PDF)
    pg = doc[5]
    images = [tuple(i["bbox"]) for i in pg.get_image_info()]
    print(f"页6 图像({len(images)}): {[tuple(round(x,1) for x in b) for b in images]}")
    for r in exact:
        box = tuple(r[4].get("bbox"))
        bad = [b for b in images if not (
            box[2] < b[0] or b[2] < box[0] or box[3] < b[1] or b[3] < box[1])]
        print(f"  [{r[0]}] {r[1]} len={len(r[3])} bbox={tuple(round(x,1) for x in box)} "
              f"与图相交={len(bad)}")
    conn.close()
    doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
