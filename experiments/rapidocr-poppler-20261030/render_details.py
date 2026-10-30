"""Read-only crops rendered from original PDF copies to verify ambiguous glyphs."""
from pathlib import Path
import pymupdf
for doc,rect in [('d007',(.05,.38,.63,.49)),('d017',(.40,.30,.96,.39)),('d050',(.08,.55,.66,.67))]:
    with pymupdf.open(f'/samples/{doc}.pdf') as pdf:
        page=pdf[0];w,h=page.rect.width,page.rect.height
        clip=pymupdf.Rect(rect[0]*w,rect[1]*h,rect[2]*w,rect[3]*h)
        page.get_pixmap(dpi=240,clip=clip,alpha=False).save(f'/lab/outputs/{doc}-source-detail.png')
