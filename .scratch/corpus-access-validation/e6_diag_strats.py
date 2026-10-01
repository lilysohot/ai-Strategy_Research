"""只读：缺口页用不同策略 find_tables，确认是否真无表格可提（排除策略问题）。"""
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

STRATS = ["lines", "text", "lines_strict", "lines_explicit"]


def main() -> int:
    for sample, pdf_name, pages in CASES:
        pdf = next(ARCHIVE.rglob(pdf_name))
        doc = fitz.open(pdf)
        print(f"\n===== {sample} =====")
        for pno in pages:
            page = doc[pno - 1]
            for s in STRATS:
                try:
                    ft = page.find_tables(strategy=s)
                    n = len(ft.tables)
                    nrows = ft.tables[0].row_count if n else 0
                    print(f"  page {pno} {s}: tables={n} rows={nrows}")
                except Exception as exc:  # noqa: BLE001
                    print(f"  page {pno} {s}: ERR {exc}")
        doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
