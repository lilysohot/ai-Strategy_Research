"""只读探针：pymupdf Table 是否提供单元格矩形（用于几何法定位原生序）。"""
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

PATH = V.SRC["793b39673d31e8a8310e89a9171567dfb0008444b669cd6e225dc354329a880a"]

doc = pymupdf.open(PATH)
page = doc[2]
tables = list(page.find_tables())
print("tables:", len(tables))
tab = tables[2]
print("attrs:", [a for a in dir(tab) if not a.startswith("_")])
print("rows type:", type(getattr(tab, "rows", None)))
rows = tab.rows
print("len(rows):", len(rows))
row = rows[1]
print("row attrs:", [a for a in dir(row) if not a.startswith("_")])
cells = row.cells
print("cells:", cells)
for i, rect in enumerate(cells):
    if rect is None:
        continue
    print(f"  col{i} rect=({rect[0]:.0f},{rect[1]:.0f},{rect[2]:.0f},{rect[3]:.0f})"
          f" text={page.get_text('text', clip=pymupdf.Rect(rect))!r}")
doc.close()
