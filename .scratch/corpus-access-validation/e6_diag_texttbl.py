"""只读：打印缺口页 text 策略提取表格的前几行，判断是真实表格还是正文误聚类。"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "e6-holdout-archive"

import fitz  # noqa: E402

CASES = [
    ("holdout-industry-003", "c1ddcd8aecb80e39c555459e3ea007db1419ed9f3b844724ac90fc65bda8a885.pdf",
     [3, 8, 11, 16, 18, 19]),
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
            ft = page.find_tables(strategy="text")
            for i, t in enumerate(ft.tables):
                cells = t.extract()
                row0 = cells[0] if cells else []
                row1 = cells[1] if len(cells) > 1 else []
                print(f"  page {pno} tbl#{i}: rows={len(cells)} cols={len(row0)}")
                print(f"    row0: {row0[:6]}")
                print(f"    row1: {row1[:6]}")
            if not ft.tables:
                print(f"  page {pno}: text 策略也无表")
        doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
