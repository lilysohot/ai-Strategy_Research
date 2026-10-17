"""Inspect the authoritative PDF text layer around the failed summary-table row."""

from __future__ import annotations

import json
from pathlib import Path

import pymupdf

from plugins.corpus.preparation.readers import read_document


ROOT = Path(__file__).resolve().parents[2]
PDF = next((ROOT / "data/corpus").glob("*46877bac.pdf"))
OUTPUT = ROOT / ".scratch/corpus-structure-restart/s2-pdf-probe.json"


def main() -> None:
    doc = pymupdf.open(PDF)
    page = doc[1]
    words = [
        {
            "x0": round(float(word[0]), 2),
            "y0": round(float(word[1]), 2),
            "x1": round(float(word[2]), 2),
            "y1": round(float(word[3]), 2),
            "text": str(word[4]),
            "block": int(word[5]),
            "line": int(word[6]),
            "word": int(word[7]),
        }
        for word in page.get_text("words", sort=True)
    ]
    anchors = [word for word in words if "螺纹钢" in word["text"]]
    neighborhoods = []
    for anchor in anchors:
        neighborhoods.append(
            {
                "anchor": anchor,
                "words": [
                    word
                    for word in words
                    if anchor["y0"] - 8 <= word["y0"] <= anchor["y1"] + 8
                ],
            }
        )
    tables = []
    for table in page.find_tables().tables:
        extracted = table.extract()
        rows = [row for row in extracted if any("螺纹钢" in str(cell or "") for cell in row)]
        if rows:
            tables.append(
                {
                    "bbox": [round(float(value), 2) for value in table.bbox],
                    "header": list(table.header.names),
                    "rows": rows,
                }
            )
    artifact = {
        "pdf": str(PDF.relative_to(ROOT)),
        "page": 2,
        "anchors": anchors,
        "neighborhoods": neighborhoods,
        "tables": tables,
        "page_text_matches": [
            line for line in page.get_text("text", sort=True).splitlines() if "螺纹钢" in line
        ],
    }
    reader_result = read_document(PDF)
    artifact["reader_units"] = [
        {
            "ordinal": unit.ordinal,
            "raw_text": unit.raw_text,
            "cells": unit.location.cells,
        }
        for unit in reader_result.units
        if unit.location.page == 2 and "螺纹钢" in unit.raw_text
    ]
    OUTPUT.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(artifact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
