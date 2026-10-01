"""只读：验证缺口页的 drawings 线段是图表曲线还是真制表线网格。"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "e6-holdout-archive"

import fitz  # noqa: E402

CASES = [
    ("holdout-industry-003", "c1ddcd8aecb80e39c555459e3ea007db1419ed9f3b844724ac90fc65bda8a885.pdf", [3, 8, 11, 16, 18, 19]),
    ("holdout-macro-010", "d179b615e82e4f6b47184ead5a34027abbd7bf2ef65ca4d599d03d31368c7595.pdf", [8]),
    ("holdout-macro-012", "f3b28791e1355dc371206b10a003dc2ef6c65f88f631c77ea7578be145f28279.pdf", [8]),
]


def main() -> int:
    for sample, pdf_name, pages in CASES:
        pdf = next(ARCHIVE.rglob(pdf_name))
        doc = fitz.open(pdf)
        print(f"\n===== {sample} =====")
        for pno in pages:
            page = doc[pno - 1]
            h = v = 0
            h_len = []
            v_len = []
            for d in page.get_drawings():
                for item in d.get("items", []):
                    if item[0] != "l":
                        continue
                    p1, p2 = item[1], item[2]
                    if abs(p1.y - p2.y) < 0.5 and abs(p1.x - p2.x) > 20:
                        h += 1
                        h_len.append(abs(p1.x - p2.x))
                    elif abs(p1.x - p2.x) < 0.5 and abs(p1.y - p2.y) > 20:
                        v += 1
                        v_len.append(abs(p1.y - p2.y))
            # 网格线通常是长直线（>50pt）；曲线碎片短
            hl = sorted(h_len)
            vl = sorted(v_len)
            short_h = sum(1 for x in hl if x < 50)
            short_v = sum(1 for x in vl if x < 50)
            # 表格网格的水平线数通常与行数一致（<30），垂直与列数一致（<20）
            print(
                f"  page {pno}: h_lines={h} v_lines={v} "
                f"h_short(<50)={short_h}/{h} v_short(<50)={short_v}/{v} "
                f"h_len_max={max(hl) if hl else 0:.0f} v_len_max={max(vl) if vl else 0:.0f}"
            )
        doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
