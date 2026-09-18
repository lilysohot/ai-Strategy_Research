"""Render bounded source pages/contact sheets under the annotation guard."""
import hashlib
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT))
from plugins.corpus.preparation.guard import install

install(HERE / "annotation-guard.json")
import pymupdf
from PIL import Image, ImageDraw

sources = json.loads((HERE / "authorized-sources.json").read_text())["sources"]
records = []
for source in sources:
    data = (ROOT / source["path"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == source["sha256"]
    doc = pymupdf.open(stream=data, filetype="pdf")
    for start in range(0, len(doc), 6):
        sheet = Image.new("RGB", (1500, 2180), "#dddddd")
        draw = ImageDraw.Draw(sheet)
        for offset, index in enumerate(range(start, min(start + 6, len(doc)))):
            page = doc[index]
            pix = page.get_pixmap(matrix=pymupdf.Matrix(1.25, 1.25))
            pic = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
            pic.thumbnail((740, 1050))
            x, y = (offset % 2) * 750, (offset // 2) * 726
            # Refit to the 2-column x 3-row sheet, preserving aspect ratio.
            pic.thumbnail((740, 696))
            draw.text((x + 8, y + 4), f"{source['source_id']} PDF page {index + 1}", fill="black")
            sheet.paste(pic, (x + 8, y + 25))
        path = HERE / "pages" / f"{source['source_id']}-sheet-{start + 1}.png"
        assert not path.exists()
        sheet.save(path)
        records.append({"path": str(path.relative_to(HERE)), "pages": list(range(start + 1, min(start + 6, len(doc)) + 1))})
    # Render remaining pages individually too, for reading details from images.
    for index, page in enumerate(doc, 1):
        path = HERE / "pages" / f"{source['source_id']}-p{index}.png"
        if not path.exists():
            path.write_bytes(page.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6)).tobytes("png"))
    print(source["source_id"], len(doc), flush=True)
with (HERE / "render-manifest.json").open("x") as output:
    json.dump(records, output, indent=2)
