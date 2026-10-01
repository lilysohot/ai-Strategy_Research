"""只读：用真实 pdf_reader 的 _count_grid_lines / _extract_tables 调试 M5 页 4。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
import dotenv  # noqa: E402

dotenv.load_dotenv(ROOT / ".env")

import pymupdf  # noqa: E402

import plugins.corpus.preparation.readers.pdf_reader as pr  # noqa: E402

ARCHIVE = HERE / "e6-holdout-archive"
PDF = next(ARCHIVE.rglob("5e30537691c88e4eee8790af34876323cef08e3cd22d388dee8a7bbe1e8f44e9.pdf"))


def main() -> int:
    doc = pymupdf.open(PDF)
    for pno in (4, 5, 9, 14, 15):
        page = doc[pno - 1]
        gl = pr._count_grid_lines(page)
        print(f"page {pno}: _count_grid_lines={gl} (min={pr._MIN_GRID_LINES}) "
              f"触发={gl >= pr._MIN_GRID_LINES}")
        # 检查该页 find_tables 与 wireless fallback
        ft = page.find_tables()
        n_default = len(ft.tables)
        lines = pr._collect_lines(page) if hasattr(pr, "_collect_lines") else None
        print(f"    find_tables默认={n_default}")
        try:
            tables, issues = pr._extract_tables(page, lines or [])
            print(f"    _extract_tables: tables={len(tables)} issues={[(i.code, i.location) for i in issues]}")
        except Exception as exc:  # noqa: BLE001
            print(f"    _extract_tables ERR: {type(exc).__name__}: {exc}")
    doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
