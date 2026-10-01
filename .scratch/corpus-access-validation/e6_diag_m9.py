"""只读：M9 页 8 的表格真伪 + 缺口页图片 bbox 与 lines 关系。"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "e6-holdout-archive"

import fitz  # noqa: E402

CASES = [
    ("holdout-macro-012", "f3b28791e1355dc371206b10a003dc2ef6c65f88f631c77ea7578be145f28279.pdf", [8]),
    ("holdout-industry-003", "c1ddcd8aecb80e39c555459e3ea007db1419ed9f3b844724ac90fc65bda8a885.pdf", [3, 16]),
]


def main() -> int:
    for sample, pdf_name, pages in CASES:
        pdf = next(ARCHIVE.rglob(pdf_name))
        doc = fitz.open(pdf)
        print(f"\n===== {sample} =====")
        for pno in pages:
            page = doc[pno - 1]
            imgs = page.get_images(full=True)
            img_bboxes = []
            for im in imgs:
                try:
                    rects = page.get_image_rects(im[0])
                    img_bboxes.extend([(r.x0, r.y0, r.x1, r.y1) for r in rects])
                except Exception:  # noqa: BLE001
                    pass
            print(f"  page {pno}: images={len(imgs)} bboxes={img_bboxes[:3]}")
            # text 策略的表格内容
            ft = page.find_tables(strategy="text")
            for t in ft.tables:
                cells = t.extract()
                for r in cells[:6]:
                    print(f"    row: {[c.strip()[:12] for c in r]}")
        doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
