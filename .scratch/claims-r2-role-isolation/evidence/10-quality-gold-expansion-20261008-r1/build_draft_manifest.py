from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parents[3]
INPUT_NAMES = (
    "inventory_non_table_sources.py",
    "source-inventory.json",
    "export_non_table_units.py",
    "source-prose-units.json",
    "gold-review-candidates.json",
    "validate_and_render_review.py",
    "validation-report.json",
    "gold-review.md",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    review = json.loads((HERE / "gold-review-candidates.json").read_text(encoding="utf-8"))
    validation = json.loads((HERE / "validation-report.json").read_text(encoding="utf-8"))
    if validation["status"] != "valid_draft" or validation["errors"]:
        raise SystemExit("refusing to manifest an invalid review draft")
    source_hashes = {
        source["path"]: f"sha256:{_sha256(REPOSITORY_ROOT / source['path'])}"
        for source in review["sources"]
    }
    manifest = {
        "schema_version": "corpus-structured-non-table-gold-draft-manifest-v1",
        "created_on": "2026-10-08",
        "status": "draft_pending_human_review",
        "formal_gold_frozen": False,
        "candidate_execution_authorized": False,
        "inputs": {
            str((HERE / name).relative_to(REPOSITORY_ROOT)): f"sha256:{_sha256(HERE / name)}"
            for name in INPUT_NAMES
        },
        "approved_source_bytes": source_hashes,
        "counts": validation["counts"],
        "risk_or_condition_records": validation["risk_or_condition_records"],
        "holdout_accessed": False,
        "table_content_included": False,
    }
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
