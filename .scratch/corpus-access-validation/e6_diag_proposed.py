"""只读：用拟议实现验证 - 在缺口页与真表格页上的区分力（>20 阈值 + crossings 判据）。"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "e6-holdout-archive"

import pymupdf  # noqa: E402


def proposed_count(page) -> int:
    """拟议实现：长线（>40pt）交叉成网才算制表线。"""
    MIN_LEN = 40.0
    horizontal: list[tuple[float, float, float]] = []
    vertical: list[tuple[float, float, float]] = []
    for drawing in page.get_drawings():
        for item in drawing.get("items", []):
            if item[0] != "l":
                continue
            p1, p2 = item[1], item[2]
            if abs(p1.y - p2.y) < 0.5 and abs(p1.x - p2.x) > MIN_LEN:
                horizontal.append((min(p1.x, p2.x), max(p1.x, p2.x), p1.y))
            elif abs(p1.x - p2.x) < 0.5 and abs(p1.y - p2.y) > MIN_LEN:
                vertical.append((min(p1.y, p2.y), max(p1.y, p2.y), p1.x))
    if len(horizontal) < 3 or len(vertical) < 3:
        return 0
    crossings = sum(
        1
        for hx0, hx1, hy in horizontal
        for vy0, vy1, vx in vertical
        if hx0 <= vx <= hx1 and vy0 <= hy <= vy1
    )
    if crossings < len(horizontal) + len(vertical):
        return 0
    return len(horizontal) + len(vertical)


def old_count(page) -> int:
    horizontal = vertical = 0
    for drawing in page.get_drawings():
        for item in drawing.get("items", []):
            if item[0] != "l":
                continue
            p1, p2 = item[1], item[2]
            if abs(p1.y - p2.y) < 0.5 and abs(p1.x - p2.x) > 20:
                horizontal += 1
            elif abs(p1.x - p2.x) < 0.5 and abs(p1.y - p2.y) > 20:
                vertical += 1
    return horizontal + vertical if (horizontal >= 3 and vertical >= 3) else 0


CASES = [
    # (label, pdf, pages, 期望: True=应有表格缺口, False=图表假阳性)
    ("M1 图表假阳性", "c1ddcd8aecb80e39c555459e3ea007db1419ed9f3b844724ac90fc65bda8a885.pdf", [3, 8, 11, 16, 18, 19], False),
    ("M1 page2 真表(已提取)", "c1ddcd8aecb80e39c555459e3ea007db1419ed9f3b844724ac90fc65bda8a885.pdf", [2], False),
    ("M2 图表假阳性", "b7e932c80e88d00931374d29ab8a786e4dc42cd194309f126301f58192e5d160.pdf", [4, 5, 6, 13, 16, 17, 18, 19], False),
    ("M2 page7 真表(已提取)", "b7e932c80e88d00931374d29ab8a786e4dc42cd194309f126301f58192e5d160.pdf", [7], False),
    ("M3", "f86c6d2c054a835de4de3707c984529580e8ce57628d59f60b6aeca7a0f61fd2.pdf", [3, 14], False),
    ("M4", "a91d95c71fd0558c054bd2374139b1c24d85f58a305bc8dd83628e380d564961.pdf", [6, 7], False),
    ("M5", "5e30537691c88e4eee8790af34876323cef08e3cd22d388dee8a7bbe1e8f44e9.pdf", [4, 5, 9, 14, 15], False),
    ("M7 图表", "d179b615e82e4f6b47184ead5a34027abbd7bf2ef65ca4d599d03d31368c7595.pdf", [8], False),
    ("M8 page11", "2f8aa70958184296f74bc9a78193c49f5966608bd3ff2330331472eaa3b90339.pdf", [11], False),
    ("M9 page8 真表", "f3b28791e1355dc371206b10a003dc2ef6c65f88f631c77ea7578be145f28279.pdf", [8], True),
    ("M9 page10 真表(已提取)", "f3b28791e1355dc371206b10a003dc2ef6c65f88f631c77ea7578be145f28279.pdf", [10], False),
]


def main() -> int:
    ok = True
    for label, pdf_name, pages, expect in CASES:
        pdf = next(ARCHIVE.rglob(pdf_name))
        doc = pymupdf.open(pdf)
        for pno in pages:
            page = doc[pno - 1]
            o = old_count(page)
            n = proposed_count(page)
            trig_old = o >= 6
            trig_new = n >= 6
            status = "OK" if trig_new == expect else "MISMATCH"
            if trig_new != expect:
                ok = False
            print(f"  [{status}] {label} page {pno}: old={o}(trig={trig_old}) "
                  f"new={n}(trig={trig_new}) expect={expect}")
        doc.close()
    print(f"\n{'ALL MATCH' if ok else 'HAS MISMATCHES'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
