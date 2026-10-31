"""Container-only adapter for the frozen, manually reviewed OCR shadow lane."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def oriented_payload(decision: dict[str, Any]) -> dict[str, Any]:
    """Only a selected orientation can become body-reader input."""
    if decision.get("status") != "oriented":
        return {"status": "error", "text": ""}
    raw = decision["raw"]
    width, height = raw["render_pixels"]
    return {
        "status": "ok" if raw["lines"] else "empty",
        "text": "\n".join(raw["lines"]),
        "lines": raw["lines"],
        "scores": raw["scores"],
        "render_pixels": [width, height],
        "boxes": [[[x * width, y * height] for x, y in box] for box in raw["boxes_normalized"]],
    }


def review_envelope(body: dict[str, Any], decision: dict[str, Any] | None) -> dict[str, Any]:
    """Keep errors and abstentions visible; no successful body result admits data."""
    status = body["status"]
    if decision is not None and decision.get("status") == "unknown":
        status = "orientation_unknown"
    elif status in {"ok", "needs_review"}:
        status = "needs_review"
    return {
        "status": status,
        "needs_review": True,
        "human_review": "pending",
        "eligible_for_ingestion": False,
        "production_ingestion": False,
        "body": body,
        "orientation": decision,
        "limitations": ["text_only", "table_associations_unverified", "chart_semantics_unread"],
    }


def run(pdf: str, page: int, out: Path) -> dict[str, Any]:
    sys.path.insert(0, "/frozen")
    body_module = importlib.import_module("body_reader")
    native = importlib.import_module("native_adapter")
    orientation = importlib.import_module("page_orientation")
    config = importlib.import_module("config")
    import numpy as np
    import pymupdf

    # Optional dependency is provided only by the pinned OCR container.
    from rapidocr import RapidOCR  # pyright: ignore[reportMissingImports]

    with pymupdf.open(pdf) as doc:
        if not 1 <= page <= len(doc):
            raise ValueError("Page outside source document")
        pg = doc[page - 1]
        if pg.rect.width * pg.rect.height * (300 / 72) ** 2 > 25_000_000:
            raise ValueError("25 MP rendering limit exceeded")
        pix = pg.get_pixmap(dpi=300, alpha=False, colorspace=pymupdf.csRGB)
        pg.get_pixmap(dpi=140, alpha=False).save(str(out / "source.png"))
    rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    # Existing reader output is a side-by-side artifact, never replaced by OCR.
    for mode in ("auto", "text", "image"):
        baseline = subprocess.run(
            [sys.executable, "/frozen/reader.py", pdf, "200000", "-", "0", mode, str(page)],
            capture_output=True,
            check=True,
            timeout=15,
        )
        (out / f"baseline-{mode}.txt").write_bytes(baseline.stdout)
    engine = RapidOCR(params=config.params("small"))
    decision: dict[str, Any] | None = None

    def ocr_reader(*_: object) -> dict[str, Any]:
        nonlocal decision
        selected: dict[str, Any] = orientation.orient_image(rgb, engine)
        decision = selected
        return oriented_payload(selected)

    def coverage_reader(*_: object) -> dict[str, Any]:
        detected = engine(rgb[:, :, ::-1].copy(), use_det=True, use_cls=False, use_rec=False)
        boxes = detected.boxes.tolist() if detected.boxes is not None else []
        return {
            "status": "ok",
            "source": "raster_text_detection",
            "render_pixels": [pix.width, pix.height],
            "rects": [
                [
                    min(p[0] for p in b) / pix.width,
                    min(p[1] for p in b) / pix.height,
                    max(p[0] for p in b) / pix.width,
                    max(p[1] for p in b) / pix.height,
                ]
                for b in boxes
            ],
        }

    body = body_module.read_page(
        pdf,
        page,
        enabled=True,
        native_reader=native.read_native,
        ocr_reader=ocr_reader,
        coverage_reader=coverage_reader,
    )
    result = review_envelope(body, decision)
    (out / "candidate.txt").write_text(body["text"], encoding="utf8")
    if decision is not None:
        for candidate in decision.get("candidates", []):
            angle = candidate["correction_clockwise"]
            (out / f"reference-{angle}.txt").write_text(
                "\n".join(candidate["raw"]["lines"]), encoding="utf8"
            )
    return result


def main() -> None:
    out = Path("/out")
    try:
        result = run(sys.argv[1], int(sys.argv[2]), out)
    except Exception as exc:
        result = {
            "status": "error",
            "error_type": type(exc).__name__,
            "needs_review": True,
            "human_review": "pending",
            "eligible_for_ingestion": False,
            "production_ingestion": False,
        }
    (out / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print(json.dumps({"status": result["status"]}))


if __name__ == "__main__":
    main()
