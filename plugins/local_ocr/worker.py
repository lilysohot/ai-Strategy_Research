"""One bounded OCR request, executed only in the pinned model image."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any


def recognize(path: str, page: int) -> dict[str, Any]:
    import numpy as np
    import pymupdf

    rapid = importlib.import_module("rapidocr")
    config = importlib.import_module("config")
    orientation = importlib.import_module("page_orientation")
    body = importlib.import_module("body_reader")
    with pymupdf.open(path) as doc:
        if not 1 <= page <= len(doc):
            raise ValueError("page_out_of_range")
        pg = doc[page - 1]
        if pg.rect.width * pg.rect.height * (300 / 72) ** 2 > 25_000_000:
            raise ValueError("pixel_budget_exceeded")
        pix = pg.get_pixmap(dpi=300, alpha=False, colorspace=pymupdf.csRGB)
    rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    decision = orientation.orient_image(rgb, rapid.RapidOCR(params=config.params("small")))
    if decision["status"] != "oriented":
        return {"status": "orientation_unknown", "text": "", "orientation": decision}
    raw = decision["raw"]
    width, height = raw["render_pixels"]
    payload = {
        "status": "ok",
        "text": "\n".join(raw["lines"]),
        "lines": raw["lines"],
        "scores": raw["scores"],
        "render_pixels": [width, height],
        "boxes": [[[x * width, y * height] for x, y in box] for box in raw["boxes_normalized"]],
    }
    result = body.read_page(
        path, page, enabled=True, native_reader=lambda *_: "", ocr_reader=lambda *_: payload
    )
    return {
        "status": "ok" if result["source"] == "ocr" and result["text"].strip() else "empty",
        "text": result["text"],
        "lines": raw["lines"],
        "scores": raw["scores"],
        "boxes_normalized_input": decision["boxes_normalized_input"],
        "correction_clockwise": decision["correction_clockwise"],
        "issues": result["issues"],
        "orientation": decision,
    }


if __name__ == "__main__":
    try:
        response = recognize(sys.argv[1], int(sys.argv[2]))
    except Exception as exc:
        response = {"status": "error", "text": "", "error_type": type(exc).__name__}
    Path(sys.argv[3]).write_text(json.dumps(response, ensure_ascii=False), encoding="utf8")
