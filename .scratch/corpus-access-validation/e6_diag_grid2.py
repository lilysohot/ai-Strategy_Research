"""只读：验证候选判据 crossings >= H+V（长线闭合网格）在更多页面上的区分力。"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "e6-holdout-archive"

import pymupdf  # noqa: E402

CASES = [
    ("M1 图表页", "c1ddcd8aecb80e39c555459e3ea007db1419ed9f3b844724ac90fc65bda8a885.pdf", [2, 3, 8, 11, 16, 18, 19]),
    ("M7", "d179b615e82e4f6b47184ead5a34027abbd7bf2ef65ca4d599d03d31368c7595.pdf", [1, 4, 7, 8]),
    ("M9", "f3b28791e1355dc371206b10a003dc2ef6c65f88f631c77ea7578be145f28279.pdf", [1, 6, 8, 10]),
    ("M2", "b7e932c80e88d00931374d29ab8a786e4dc42cd194309f126301f58192e5d160.pdf", [2, 3, 4, 5, 7, 13]),
    # 生产回归：M4 (国金通信) 真表格页 page 2 有很多 table_row
    ("M4", "a91d95c71fd0558c054bd2374139b1c24d85f58a305bc8dd83628e380d564961.pdf", [1, 2, 8]),
    # M5 宏观
    ("M5", "5e30537691c88e4eee8790af34876323cef08e3cd22d388dee8a7bbe1e8f44e9.pdf", [1]),
    ("M6", "f7f65d7ee16db19e79766a9f0f13b16f22b56ff318530fedf64d9240fbb87826.pdf", [1, 7]),
    ("M8", "2f8aa70958184296f74bc9a78193c49f5966608bd3ff2330331472eaa3b90339.pdf", [4, 8, 11]),
]


def main() -> int:
    for label, pdf_name, pages in CASES:
        pdf = next(ARCHIVE.rglob(pdf_name))
        doc = pymupdf.open(pdf)
        print(f"\n===== {label} =====")
        for pno in pages:
            page = doc[pno - 1]
            h_lines, v_lines = [], []
            for d in page.get_drawings():
                for item in d.get("items", []):
                    if item[0] != "l":
                        continue
                    p1, p2 = item[1], item[2]
                    if abs(p1.y - p2.y) < 0.5 and abs(p1.x - p2.x) > 20:
                        x0, x1 = sorted((p1.x, p2.x))
                        h_lines.append((x0, x1, p1.y))
                    elif abs(p1.x - p2.x) < 0.5 and abs(p1.y - p2.y) > 20:
                        y0, y1 = sorted((p1.y, p2.y))
                        v_lines.append((y0, y1, p1.x))
            h_long = [h for h in h_lines if h[1] - h[0] > 40]
            v_long = [v for v in v_lines if v[1] - v[0] > 40]
            crossings = sum(
                1
                for hx0, hx1, hy in h_long
                for vy0, vy1, vx in v_long
                if hx0 <= vx <= hx1 and vy0 <= hy <= vy1
            )
            H, V = len(h_long), len(v_long)
            n_tables = len(page.find_tables().tables)
            pred = H >= 3 and V >= 3 and crossings >= H + V
            print(f"  page {pno}: find_tables={n_tables} h_long={H} v_long={V} "
                  f"crossings={crossings} C>=(H+V)={crossings >= H + V} 触发候选={pred}")
        doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
