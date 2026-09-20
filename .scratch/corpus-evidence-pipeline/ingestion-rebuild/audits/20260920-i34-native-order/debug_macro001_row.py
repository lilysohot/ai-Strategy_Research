"""只读调试：macro-001 a-3 p3（新增非农总计一行）为何在 I1+I2 后仍不命中。

打印：find_tables 网格行、我们发射的 table_row 文本、以及 I2 排序所依据的 native_pos。
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE
while not (ROOT / "plugins").is_dir():
    ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import pymupdf  # noqa: E402
import verify_native_order as V  # noqa: E402

from plugins.corpus.preparation.readers import pdf_reader as P  # noqa: E402
from plugins.corpus.preparation.readers import read_document  # noqa: E402

NEEDLE = "新增非农总计"


def main() -> None:
    for src, path in V.SRC.items():
        doc = pymupdf.open(path)
        for pno in range(doc.page_count):
            if NEEDLE not in doc[pno].get_text("text"):
                continue
            page = doc[pno]
            print("=" * 88)
            print(f"SRC {src[:12]} page={pno + 1}")
            lines = P._page_lines(page)
            native = "".join("".join(line.text.split()) for line in lines)
            tables, _ = P._extract_tables(page, lines)
            for table in tables:
                for ri, row in enumerate(table.rows):
                    joined = P._no_ws("".join(c.text for c in row.cells))
                    if NEEDLE in joined or "-156" in joined:
                        print(f"  tbl[{table.index}] r{ri} cells=")
                        for c in row.cells:
                            print(f"      col={c.col} native_pos={c.native_pos} text={c.text!r}")
                        print(f"    -> _row_text = {P._row_text(row)[0]!r}")
            print("  ---- 我们发射的 table_row 单元 ----")
            result = read_document(path)
            for unit in result.units:
                if unit.location.page == pno + 1 and NEEDLE in unit.raw_text:
                    print(f"    {unit.raw_text!r}")
            print(f"  ---- native_pos 参照：needle 在原生序的位置 = {native.find(NEEDLE)}")
            print(f"  ---- 原生序片段: {native[native.find(NEEDLE): native.find(NEEDLE) + 90]}")
        doc.close()


if __name__ == "__main__":
    main()
