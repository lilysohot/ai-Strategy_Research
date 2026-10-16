"""Bind adjudicated coverage gaps to a publication and exercise C4."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from plugins.corpus.structured.query import query_semantic
from plugins.corpus.structured.store import (
    COVERAGE_GAPS_PREFIX,
    EXPLICIT_GAPS,
    SCOPED_SELECTION_PREFIX,
    PublicationGap,
    publish_semantic,
    read_semantic,
)

INDUSTRIAL = "f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb"
OPTICAL = "48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f"
SOURCE_BY_RUN = {"industrial-fulian-md": INDUSTRIAL, "optical-module-docx": OPTICAL}
EXPECTED_GEN2 = {
    INDUSTRIAL: "sha256:c3dbd91bfa0fe2b1c905077f35fba04e27c9b8bdc678abbcb1515f982a8b3871",
    OPTICAL: "sha256:8395c900d91fe12d6507db5a1d8d16705dee7e95538f1785b86dcf083eb45aeb",
}


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise RuntimeError("repository root not found")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_gaps() -> dict[str, tuple[PublicationGap, ...]]:
    base = repo_root() / (
        ".scratch/claims-r2-role-isolation/evidence/"
        "109-items-extraction-and-publication-20261015/r0-zero-call"
    )
    item_path = base / "p4-remaining-gap-analysis.json"
    disposition_path = base / "p4-c1-disposition-final.json"
    listing_path = base / "p4-c1-review-listing.json"
    item_data = json.loads(item_path.read_text(encoding="utf-8"))
    disposition_data = json.loads(disposition_path.read_text(encoding="utf-8"))
    listing_data = json.loads(listing_path.read_text(encoding="utf-8"))
    rows = {row["c1_candidate_id"]: row for row in listing_data["rows"]}
    item_authority = f"{item_path.relative_to(repo_root())}#sha256={sha256(item_path)}"
    claim_authority = (
        f"{disposition_path.relative_to(repo_root())}#sha256={sha256(disposition_path)};"
        f"{listing_path.relative_to(repo_root())}#sha256={sha256(listing_path)}"
    )
    result: dict[str, list[PublicationGap]] = {INDUSTRIAL: [], OPTICAL: []}
    for row in item_data["gaps"]:
        source_id = SOURCE_BY_RUN[row["source"]]
        result[source_id].append(
            PublicationGap(
                gap_id=f"items:{row['gold_record_id']}",
                role="material_items",
                description=row["gold_text"],
                query_terms=(row["gold_text"],),
                authority=item_authority,
            )
        )
    for row in disposition_data["dispositions"]:
        if row["disposition"] != "no_candidate":
            continue
        listing = rows[row["c1_candidate_id"]]
        source_id = listing["source_id"].removeprefix("sha256:")
        if source_id not in result:
            raise RuntimeError(f"unknown claims gap source: {source_id}")
        result[source_id].append(
            PublicationGap(
                gap_id=f"claims:C1-{row['serial']:02d}",
                role="claims",
                description=row["claim_text"],
                query_terms=(row["claim_text"],),
                authority=claim_authority,
            )
        )
    frozen = {key: tuple(sorted(value, key=lambda gap: gap.gap_id)) for key, value in result.items()}
    assert sum(gap.role == "material_items" for gaps in frozen.values() for gap in gaps) == 7
    assert sum(gap.role == "claims" for gaps in frozen.values() for gap in gaps) == 12
    assert len(frozen[INDUSTRIAL]) == 16 and len(frozen[OPTICAL]) == 3
    return frozen


def db_state(root: Path) -> dict[str, Any]:
    database = root / "index/structured.sqlite3"
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        tables = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "attempts",
                "tasks",
                "semantic_publications",
                "semantic_publication_artifacts",
                "semantic_publication_heads",
            )
        }
        heads = [
            dict(row)
            for row in connection.execute(
                "SELECT source_id, build_id, generation, publication_id, lifecycle "
                "FROM semantic_publication_heads ORDER BY source_id, build_id"
            )
        ]
    finally:
        connection.close()
    stat = database.stat()
    return {"tables": tables, "heads": heads, "database_size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def same_gaps(left: tuple[PublicationGap, ...], right: tuple[PublicationGap, ...]) -> bool:
    dump = lambda values: sorted(  # noqa: E731
        (value.model_dump(mode="json") for value in values), key=lambda value: value["gap_id"]
    )
    return dump(left) == dump(right)


def run(root: Path) -> dict[str, Any]:
    root = root.resolve()
    gaps_by_source = load_gaps()
    before_db = db_state(root)
    publications: list[dict[str, Any]] = []
    probes: list[dict[str, Any]] = []
    controls: list[dict[str, Any]] = []
    for source_id in (INDUSTRIAL, OPTICAL):
        before = read_semantic(source_id, next(row["build_id"] for row in before_db["heads"] if row["source_id"] == source_id), store_root=root)
        expected_gaps = gaps_by_source[source_id]
        if before.coverage_gaps:
            if not same_gaps(before.coverage_gaps, expected_gaps):
                raise RuntimeError(f"unexpected existing gap registry for {source_id}")
            after = before
            action = "verified_existing"
        else:
            if before.manifest.publication_id != EXPECTED_GEN2[source_id] or before.manifest.generation != 2:
                raise RuntimeError(f"unexpected publication parent for {source_id}")
            if before.selected_record_ids or before.manifest.quality_status != "accepted":
                raise RuntimeError(f"source is not an unscoped accepted publication: {source_id}")
            preserved_reasons = tuple(
                code
                for code in before.manifest.reason_codes
                if code != EXPLICIT_GAPS
                and not code.startswith((COVERAGE_GAPS_PREFIX, SCOPED_SELECTION_PREFIX))
            )
            manifest = publish_semantic(
                source_id=source_id,
                build_id=before.manifest.build_id,
                snapshot_id=before.manifest.snapshot_id,
                artifacts=tuple(artifact.reference for artifact in before.artifacts),
                expected_parent_publication_id=before.manifest.publication_id,
                store_root=root,
                mappings=before.manifest.mappings,
                reason_codes=preserved_reasons,
                coverage_gaps=expected_gaps,
                lifecycle="rule_upgrade",
            )
            after = read_semantic(source_id, before.manifest.build_id, store_root=root)
            assert after.manifest.publication_id == manifest.publication_id
            action = "published_rule_upgrade"
        assert same_gaps(after.coverage_gaps, expected_gaps)
        assert after.manifest.artifacts == before.manifest.artifacts
        assert after.manifest.snapshot_id == before.manifest.snapshot_id
        assert after.manifest.mappings == before.manifest.mappings
        assert after.manifest.coverage == before.manifest.coverage
        assert after.manifest.quality_status == before.manifest.quality_status == "accepted"
        assert after.manifest.generation in {3}
        assert after.manifest.parent_publication_id == EXPECTED_GEN2[source_id]
        publications.append(
            {
                "source_id": source_id,
                "build_id": after.manifest.build_id,
                "action": action,
                "before_publication_id": before.manifest.publication_id,
                "after_publication_id": after.manifest.publication_id,
                "generation": after.manifest.generation,
                "gap_count": len(after.coverage_gaps),
                "roles": sorted({artifact.artifact.role for artifact in after.artifacts}),
                "coverage": after.manifest.coverage.model_dump(mode="json"),
                "quality_status": after.manifest.quality_status,
            }
        )
        for gap in expected_gaps:
            page = query_semantic(
                source_id,
                after.manifest.build_id,
                purpose="cite",
                query_text=gap.query_terms[0],
                field_filters={"role": gap.role},
                store_root=root,
            )
            if EXPLICIT_GAPS not in page.error_codes:
                raise RuntimeError(f"registered gap not reported: {gap.gap_id}")
            probes.append(
                {
                    "gap_id": gap.gap_id,
                    "source_id": source_id,
                    "role": gap.role,
                    "page_status": page.page_status,
                    "error_codes": list(page.error_codes),
                    "records": len(page.records),
                    "publication_id": page.publication_id,
                }
            )
        ordinary = query_semantic(
            source_id,
            after.manifest.build_id,
            purpose="cite",
            query_text="C4未登记的普通词法未命中控制项-7f63d6",
            field_filters={"role": "material_items"},
            store_root=root,
        )
        assert ordinary.page_status == "no_match" and EXPLICIT_GAPS not in ordinary.error_codes
        relation = query_semantic(
            source_id,
            after.manifest.build_id,
            purpose="cite",
            query_text="因果关系",
            field_filters={"role": "material_relations"},
            store_root=root,
        )
        assert (relation.page_status, relation.error_codes) == (
            "not_extracted",
            ("CS_DEPENDENCY_NOT_READY",),
        )
        controls.append(
            {
                "source_id": source_id,
                "ordinary_miss": ordinary.model_dump(mode="json"),
                "relations": relation.model_dump(mode="json"),
            }
        )
    after_db = db_state(root)
    assert len(probes) == 19
    assert before_db["tables"]["attempts"] == after_db["tables"]["attempts"] == 0
    assert before_db["tables"]["tasks"] == after_db["tables"]["tasks"]
    return {
        "schema": "c4-publication-and-probe-result-v1",
        "status": "PASS",
        "store_root": str(root.resolve()),
        "before_db": before_db,
        "after_db": after_db,
        "publications": publications,
        "registered_probe_summary": {"passed": len(probes), "expected": 19},
        "registered_probes": probes,
        "controls": controls,
        "extraction_attempts": 0,
        "production_pg_writes": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store-root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = run(args.store_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "registered_probe_summary": result["registered_probe_summary"], "publications": result["publications"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
