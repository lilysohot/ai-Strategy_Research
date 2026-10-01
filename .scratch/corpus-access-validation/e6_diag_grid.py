"""只读：计算横线/竖线的交叉点，验证「闭合网格」能否区分图表页与真表格。"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "e6-holdout-archive"

import pymupdf  # noqa: E402

CASES = [
    # 图表假阳性页
    ("M1 图表", "c1ddcd8aecb80e39c555459e3ea007db1419ed9f3b844724ac90fc65bda8a885.pdf", [3, 8, 16]),
    # 真表格页（从 e6 预筛里 find_tables 成功的页面找：M1 page2 是无线表）
    ("M7", "d179b615e82e4f6b47184ead5a34027abbd7bf2ef65ca4d599d03d31368c7595.pdf", [8]),
    ("M9", "f3b28791e1355dc371206b10a003dc2ef6c65f88f631c77ea7578be145f28279.pdf", [8]),
]


def main() -> int:
    for label, pdf_name, pages in CASES:
        pdf = next(ARCHIVE.rglob(pdf_name))
        doc = pymupdf.open(pdf)
        print(f"\n===== {label} =====")
        for pno in pages:
            page = doc[pno - 1]
            h_lines = []
            v_lines = []
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
            # 只统计长线（>50pt）构成网格
            h_long = [h for h in h_lines if h[1] - h[0] > 50]
            v_long = [v for v in v_lines if v[1] - v[0] > 50]
            # 交叉：横线跨度覆盖竖线的 x，竖线跨度覆盖横线的 y
            crossings = 0
            for hx0, hx1, hy in h_long:
                for vy0, vy1, vx in v_long:
                    if hx0 <= vx <= hx1 and vy0 <= hy <= vy1:
                        crossings += 1
            H, V = len(h_long), len(v_long)
            print(f"  page {pno}: h_long={H} v_long={V} crossings={crossings} "
                  f"grid_sig={H >= 3 and V >= 3 and crossings >= (H - 1) * (V - 1)}")
        doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
