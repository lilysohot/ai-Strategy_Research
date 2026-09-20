"""只读诊断：化工景气表（重点化工品景气一览表）的当前提取输出 vs pymupdf 原生表格能力。

定位含「价差分位」的页，打印：
1. reader 当前 KEPT 文本（表区域附近）
2. pymupdf find_tables() 的结构化行列 + 每个 cell 的 bbox
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

CANDIDATES = {
    "长江化工十问十答": V.SRC["174b64628f35aca60909d11b509bc7b7e87a9f4613a03a1da6c01d720a8cbcb0"],
    "华福新材料周报": V.SRC["f8e316969b7cfdcd3bfde7f25320d58e95527fbdc8304ced9ca6738980051560"],
}


def main() -> None:
    for name, path in CANDIDATES.items():
        doc = pymupdf.open(path)
        kept = V.kept_pages(path)
        for pno in range(doc.page_count):
            page = doc[pno]
            tabs = list(page.find_tables())
            has_price = "价差分位" in page.get_text("text")
            if not tabs and not has_price:
                continue
            print("#" * 88)
            print(f"DOC {name}  page={pno + 1}  tables={len(tabs)}  含价差分位={has_price}")
            for ti, tab in enumerate(tabs):
                print(f"[table {ti}] rows={tab.row_count} cols={tab.col_count} bbox={tab.bbox}")
                for ri, row in enumerate(tab.extract()):
                    print(f"   r{ri}: {row}")
            print("---- reader KEPT 文本（该页）----")
            print(kept.get(pno + 1, "(no kept text)")[:2600])
        doc.close()


if __name__ == "__main__":
    main()
