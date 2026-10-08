from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from plugins.corpus.preparation.readers import CandidateUnit, read_document

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SOURCE_PATHS = (
    "data/corpus/工业富联_投委会决策报告_20260829.md",
    "data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _locator(unit: CandidateUnit) -> str:
    location = unit.location
    if location.char_span is not None:
        return f"char:{location.char_span.start}-{location.char_span.end}"
    if location.element is not None:
        return location.element
    if location.page is not None:
        return f"page:{location.page}"
    raise ValueError("unit has no auditable locator")


def build_export() -> dict[str, object]:
    sources: list[dict[str, object]] = []
    for relative in SOURCE_PATHS:
        path = REPOSITORY_ROOT / relative
        result = read_document(path)
        units = [
            {
                "ordinal": unit.ordinal,
                "kind": unit.kind,
                "status": unit.status.value,
                "reasons": list(unit.reasons),
                "locator": _locator(unit),
                "text_sha256": unit.content_hash,
                "text": unit.raw_text,
            }
            for unit in result.units
            if unit.kind not in {"table", "table_row"}
        ]
        sources.append(
            {
                "source_sha256": _sha256(path),
                "path": relative,
                "format": result.format.value,
                "extractor_rev": result.extractor_rev,
                "issues": [
                    {
                        "code": issue.code,
                        "location": issue.location,
                        "detail": issue.detail,
                    }
                    for issue in result.issues
                ],
                "units": units,
            }
        )
    return {
        "schema_version": "corpus-structured-non-table-review-source-v1",
        "created_on": "2026-10-08",
        "status": "source_export_for_human_gold_review",
        "candidate_outputs_observed_before_export": False,
        "holdout_accessed": False,
        "table_units_excluded": True,
        "sources": sources,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_export()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
