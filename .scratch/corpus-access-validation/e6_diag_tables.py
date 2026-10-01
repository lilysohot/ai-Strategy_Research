"""诊断 3 份 re-extract 材料缺口页的表格性质（只读，零模型）。

判断每个缺口页的表格是文本型（find_tables 可识别、缺提取是解析缺陷，可修复）
还是扫描图片型（页面无可提取文本，属 protocol §1 暂不支持项）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ARCHIVE = HERE / "e6-holdout-archive"

import fitz  # noqa: E402

# (材料, 缺口页列表)
CASES = {
    "holdout-industry-003": ("c1ddcd8aecb80e39c555459e3ea007db1419ed9f3b844724ac90fc65bda8a885.pdf", [3, 8, 11, 16, 18, 19]),
    "holdout-macro-010": ("d179b615e82e4f6b47184ead5a34027abbd7bf2ef65ca4d599d03d31368c7595.pdf", [8]),
    "holdout-macro-012": ("f3b28791e1355dc371206b10a003dc2ef6c65f88f631c77ea7578be145f28279.pdf", [8]),
}


def find_pdf(name: str) -> Path:
    for p in ARCHIVE.rglob(name):
        return p
    raise FileNotFoundError(name)


def main() -> int:
    for sample, (pdf_name, pages) in CASES.items():
        print(f"\n===== {sample} :: {pdf_name} =====")
        doc = fitz.open(find_pdf(pdf_name))
        for pno in pages:
            page = doc[pno - 1]
            text = page.get_text("text").strip()
            ntext_chars = len(text)
            finder = page.find_tables()
            n_tables = len(finder.tables)
            drawings = page.get_drawings()
            n_lines = sum(
                1
                for d in drawings
                for item in d.get("items", [])
                if item[0] == "l"
            )
            images = page.get_images(full=True)
            print(f"  page {pno}: text_chars={ntext_chars} find_tables={n_tables} "
                  f"draw_lines={n_lines} images={len(images)}")
            if n_tables:
                for t in finder.tables:
                    cells = t.extract()
                    print(f"    table rows={len(cells)} first_row={cells[0] if cells else []}")
            else:
                # 无表但页面是否有类表格文本？
                preview = " ".join(text.split())[:200]
                print(f"    NO_TABLE text_preview={preview!r}")
        doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
