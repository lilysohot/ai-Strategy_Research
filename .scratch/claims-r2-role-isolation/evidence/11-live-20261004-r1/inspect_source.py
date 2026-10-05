"""Inspect the selected development PDF offline; do not generate candidate output."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pymupdf


def main() -> None:
    output = Path(__file__).resolve().parent
    repo = output.parents[3]
    source = (
        repo
        / "data/corpus"
        / (
            "2026-08-16_2026.08.16-华创证券-欧阳予-田晨曦-张慧-公司研究-业绩点评-"
            "贵州茅台-600519-报表实质扎实-经营底部已过-贵州茅台-600519-2026年中报点评-e034bdac.pdf"
        )
    )
    with pymupdf.open(source) as document:
        pages = [page.get_text(sort=True) for page in document]
        result = {
            "source_path": str(source),
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "page_count": len(pages),
            "page_characters": [len(page) for page in pages],
            "purpose": "development_source_review_only",
            "human_gold_status": "pending",
            "model_requests": 0,
        }
        with (output / "source-inspection.json").open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        with (output / "source-text.txt").open("x", encoding="utf-8") as stream:
            for index, page in enumerate(pages, start=1):
                stream.write(f"\n=== PDF page {index} ===\n{page}\n")
        for index in range(min(3, len(pages))):
            document[index].get_pixmap(matrix=pymupdf.Matrix(1.4, 1.4)).save(
                output / f"source-page-{index + 1}.png"
            )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
