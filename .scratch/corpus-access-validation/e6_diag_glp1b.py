"""只读：检查 M3 页6 unit:0188 bbox 与图像几何（region 证明）。"""
from __future__ import annotations

import json
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

d = json.loads((HERE / "e6-holdout-build.json").read_text(encoding="utf-8"))
BUILD = next(s["build_id"] for s in d["sources"] if s["sample_id"] == "holdout-industry-006")
PDF = HERE / "e6-holdout-archive" / "f8" / "f86c6d2c054a835de4de3707c984529580e8ce57628d59f60b6aeca7a0f61fd2.pdf"


def main() -> int:
    target = make_conninfo(**{**conninfo_to_dict(dsn()), "dbname": "e6_holdout_corpus"})
    conn = psycopg.connect(target)
    row = conn.execute(
        "select unit_id, kind, raw_text, location from corpus.corpus_units "
        "where build_id = %s and unit_id = 'unit:0188'",
        (BUILD,),
    ).fetchone()
    if row:
        box = tuple(row[3].get("bbox"))
        print(f"[{row[0]}] kind={row[1]} len={len(row[2])} bbox={tuple(round(x,1) for x in box)}")
        print(f"raw_text: {row[2][:120]!r}")
    else:
        print("unit:0188 不存在")
        return 0
    doc = pymupdf.open(PDF)
    pg = doc[5]
    images = [tuple(i["bbox"]) for i in pg.get_image_info()]
    print(f"页6 图像({len(images)}): {[tuple(round(x,1) for x in b) for b in images]}")
    bad = []
    for b in images:
        overlap = not (box[2] < b[0] or b[2] < box[0] or box[3] < b[1] or b[3] < box[1])
        if overlap:
            bad.append(b)
    print(f"unit bbox 与图像相交数: {len(bad)} -> {'OK(不相交)' if not bad else 'FAIL'}")
    # 页面 get_textbox 校验
    clipped = pg.get_textbox(pymupdf.Rect(box))
    import re

    n_units = "".join(row[2].split())
    n_clip = "".join(clipped.split())
    print(f"textbox 回填匹配: {n_units in n_clip}")
    conn.close()
    doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
