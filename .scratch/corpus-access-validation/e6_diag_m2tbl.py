"""只读：检查 M2 表格缺口页（4/5/6/13/16/17/18/19）是否也是图表/假阳性。"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "e6-holdout-archive"

import pymupdf  # noqa: E402

PDF = ARCHIVE / "b7" / "b7e932c80e88d00931374d29ab8a786e4dc42cd194309f126301f58192e5d160.pdf"
PAGES = [4, 5, 6, 13, 16, 17, 18, 19]


def main() -> int:
    doc = pymupdf.open(PDF)
    for pno in PAGES:
        page = doc[pno - 1]
        ft = page.find_tables()
        n = len(ft.tables)
        # text 策略
        try:
            tft = page.find_tables(strategy="text")
            ntext = len(tft.tables)
        except Exception:  # noqa: BLE001
            ntext = -1
        h = v = 0
        for d in page.get_drawings():
            for item in d.get("items", []):
                if item[0] != "l":
                    continue
                p1, p2 = item[1], item[2]
                if abs(p1.y - p2.y) < 0.5 and abs(p1.x - p2.x) > 20:
                    h += 1
                elif abs(p1.x - p2.x) < 0.5 and abs(p1.y - p2.y) > 20:
                    v += 1
        text = " ".join(page.get_text("text").split())
        print(f"page {pno}: find_tables={n} text_strat={ntext} h_lines={h} v_lines={v} "
              f"text={len(text)}")
        print(f"   preview: {text[:120]!r}")
    doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
