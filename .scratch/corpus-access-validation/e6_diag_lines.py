"""只读：对比真表格页（M1 页2）与图表假阳性页（M1 页3）的制表线分布，确定判据。"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "e6-holdout-archive"

import pymupdf  # noqa: E402

PDF = ARCHIVE / "c1" / "c1ddcd8aecb80e39c555459e3ea007db1419ed9f3b844724ac90fc65bda8a885.pdf"
PAGES = [2, 3, 8, 11, 16, 18, 19]


def main() -> int:
    doc = pymupdf.open(PDF)
    for pno in PAGES:
        page = doc[pno - 1]
        h = []
        v = []
        for d in page.get_drawings():
            for item in d.get("items", []):
                if item[0] != "l":
                    continue
                p1, p2 = item[1], item[2]
                if abs(p1.y - p2.y) < 0.5 and abs(p1.x - p2.x) > 20:
                    h.append(abs(p1.x - p2.x))
                elif abs(p1.x - p2.x) < 0.5 and abs(p1.y - p2.y) > 20:
                    v.append(abs(p1.y - p2.y))
        hl = sorted(h, reverse=True)
        vl = sorted(v, reverse=True)
        # 长线（>50pt）计数
        h_long = sum(1 for x in h if x > 50)
        v_long = sum(1 for x in v if x > 50)
        # 相交网格：横线 x 跨度 ∩ 竖线 y 跨度
        n_tables = len(page.find_tables().tables)
        print(f"page {pno}: find_tables={n_tables} h={len(h)}[long={h_long}] v={len(v)}[long={v_long}] "
              f"h_top={hl[:5]} v_top={vl[:5]}")
    doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
