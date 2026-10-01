"""只读：检查 4 份仍被阻断材料剩余缺口页的性质（背景图 or 真实大图 / 真网格 or 图表）。"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "e6-holdout-archive"

import pymupdf  # noqa: E402

CASES = [
    # (pdf, {page: 需要检查的缺口类型})
    ("f86c6d2c054a835de4de3707c984529580e8ce57628d59f60b6aeca7a0f61fd2.pdf", [3, 6, 14]),
    ("5e30537691c88e4eee8790af34876323cef08e3cd22d388dee8a7bbe1e8f44e9.pdf", [4, 5, 9, 11, 14, 15]),
    ("f7f65d7ee16db19e79766a9f0f13b16f22b56ff318530fedf64d9240fbb87826.pdf", [9]),
    ("f3b28791e1355dc371206b10a003dc2ef6c65f88f631c77ea7578be145f28279.pdf", [8]),
]


def main() -> int:
    for pdf_name, pages in CASES:
        pdf = next(ARCHIVE.rglob(pdf_name))
        doc = pymupdf.open(pdf)
        print(f"\n===== {pdf_name[:16]} =====")
        for pno in pages:
            page = doc[pno - 1]
            rect = page.rect
            page_area = rect.width * rect.height
            # 图片
            imgs = []
            for image in page.get_images(full=True):
                for r in page.get_image_rects(image[0]):
                    a = (r.x1 - r.x0) * (r.y1 - r.y0)
                    imgs.append((a / page_area, r))
            big = [x for x in imgs if x[0] >= 0.25]
            # 网格线
            h = []
            v = []
            for d in page.get_drawings():
                for item in d.get("items", []):
                    if item[0] != "l":
                        continue
                    p1, p2 = item[1], item[2]
                    if abs(p1.y - p2.y) < 0.5 and abs(p1.x - p2.x) > 40:
                        h.append((min(p1.x, p2.x), max(p1.x, p2.x), p1.y))
                    elif abs(p1.x - p2.x) < 0.5 and abs(p1.y - p2.y) > 40:
                        v.append((min(p1.y, p2.y), max(p1.y, p2.y), p1.x))
            crossings = sum(
                1 for hx0, hx1, hy in h for vy0, vy1, vx in v if hx0 <= vx <= hx1 and vy0 <= hy <= vy1
            )
            n_tables = len(page.find_tables().tables)
            text = " ".join(page.get_text("text").split())
            print(f"  page {pno}: 大图(>=25%)={len(big)} h_long={len(h)} v_long={len(v)} "
                  f"crossings={crossings} find_tables={n_tables}")
            for frac, r in big[:3]:
                print(f"    图占比 {frac:.0%} bbox=({r.x0:.0f},{r.y0:.0f},{r.x1:.0f},{r.y1:.0f})")
            print(f"    text: {text[:100]!r}")
        doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
