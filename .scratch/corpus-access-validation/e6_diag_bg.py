"""只读：确认 M2 每页整页图是否为背景水印（验证 image_region_unreadable 假阳性）。"""
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

ARCHIVE = HERE / "e6-holdout-archive"
PDF = ARCHIVE / "b7" / "b7e932c80e88d00931374d29ab8a786e4dc42cd194309f126301f58192e5d160.pdf"


def main() -> int:
    doc = pymupdf.open(PDF)
    print(f"pages={len(doc)}")
    for pno in (1, 2, 3, 7, 27):
        page = doc[pno - 1]
        rect = page.rect
        area = rect.width * rect.height
        print(f"\npage {pno}: page_rect=({rect.x0:.0f},{rect.y0:.0f},{rect.x1:.0f},{rect.y1:.0f}) "
              f"area={area:.0f} rotation={page.rotation}")
        for image in page.get_images(full=True):
            xref = image[0]
            info = doc.extract_image(xref)
            for r in page.get_image_rects(xref):
                a = (r.x1 - r.x0) * (r.y1 - r.y0)
                note = ""
                if abs(r.x0 - rect.x0) < 1 and abs(r.y0 - rect.y0) < 1 and abs(r.x1 - rect.x1) < 1 and abs(r.y1 - rect.y1) < 1:
                    note = " <== 整页背景图"
                print(f"  image xref={xref} w={info.get('width')} h={info.get('height')} "
                      f"ext={info.get('ext')} bbox=({r.x0:.0f},{r.y0:.0f},{r.x1:.0f},{r.y1:.0f}) "
                      f"area%={a / area:.0%}{note}")
        # 页面文本字符数（判断文字层是否存在）
        n = len(page.get_text("text").strip())
        print(f"  页文本字符: {n}")
    doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
