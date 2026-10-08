from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from plugins.corpus.preparation.readers import read_document

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SCOPE_MANIFEST = (
    REPOSITORY_ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/"
    "20260920-i31-dev-lane/dev-scope-manifest.json"
)
SEEN_SOURCE_SHA256 = "6f14cc145b798b3716bad47829c05d89d8a5e5955179f11d196ed9b9b8538f11"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_inventory() -> dict[str, object]:
    manifest = json.loads(SCOPE_MANIFEST.read_text(encoding="utf-8"))
    sources: list[dict[str, object]] = []
    for source in manifest["sources"]:
        relative = source["path"]
        path = REPOSITORY_ROOT / relative
        source_sha256 = _sha256(path)
        if source_sha256 == SEEN_SOURCE_SHA256:
            continue
        result = read_document(path)
        kinds = Counter(unit.kind for unit in result.units)
        prose_units = [unit for unit in result.units if unit.kind not in {"table_row", "table"}]
        table_units = [unit for unit in result.units if unit.kind in {"table_row", "table"}]
        sources.append(
            {
                "source_sha256": source_sha256,
                "path": relative,
                "domain_hint": source["domain_hint"],
                "approval_provenance": source["provenance"],
                "review_decision_ids": source["review_decision_ids"],
                "format": result.format.value,
                "extractor_rev": result.extractor_rev,
                "page_count": result.page_count,
                "unit_counts": dict(sorted(kinds.items())),
                "prose_units": len(prose_units),
                "prose_chars": sum(len(unit.raw_text) for unit in prose_units),
                "table_units_excluded": len(table_units),
                "issue_codes": sorted({issue.code for issue in result.issues}),
                "eligible_for_review": bool(prose_units),
            }
        )
    return {
        "schema_version": "corpus-structured-non-table-source-inventory-v1",
        "created_on": "2026-10-08",
        "purpose": "human_review_candidates_only_not_frozen_gold",
        "authority": str(SCOPE_MANIFEST.relative_to(REPOSITORY_ROOT)),
        "exclusions": {
            "seen_development_source_sha256": [SEEN_SOURCE_SHA256],
            "table_kinds": ["table", "table_row"],
            "holdout_accessed": False,
        },
        "sources": sources,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_inventory()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
