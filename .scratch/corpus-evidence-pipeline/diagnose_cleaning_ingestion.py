"""Read-only diagnosis: real Python paths, in-memory sources and fake PG I/O.

No production modifications, real database, corpus source, gold, or model calls.
--assert-clean returns nonzero while the desired ingestion contracts are unmet.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import threading
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self
from unittest.mock import MagicMock, patch

import p0_baseline

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


@contextmanager
def source_text(path: Path, text: str) -> Iterator[None]:
    """Patch only one synthetic source's file I/O, leaving actual parsers intact."""
    original = Path.open

    def open_source(owner: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if owner == path:
            if any(flag in mode for flag in ("w", "a", "+", "x")):
                raise PermissionError("synthetic source is read-only")
            return io.BytesIO(text.encode()) if "b" in mode else io.StringIO(text)
        return original(owner, mode, *args, **kwargs)

    with patch.object(Path, "open", open_source):
        yield


def fake_service() -> tuple[Any, MagicMock, MagicMock]:
    from plugins.corpus.service import CorpusService

    owner: Any = object.__new__(CorpusService)
    owner._lock = threading.RLock()
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value
    cursor.__enter__.return_value = cursor
    owner._connect = MagicMock(return_value=connection)
    owner.refresh_metadata = MagicMock(
        return_value={
            "docs": 1,
            "org_filled": 0,
            "analysts_filled": 0,
            "published_backfilled": 0,
        }
    )
    return owner, connection, cursor


def investigate() -> dict[str, Any]:
    network = p0_baseline.block_external()
    import p4_item_trial as trial

    from plugins.corpus import evidence, ingest, service

    checks: list[dict[str, Any]] = []

    def check(name: str, expected: str, passed: bool, observed: object) -> None:
        checks.append({"id": name, "expected": expected, "passed": passed, "observed": observed})

    # Actual directory orchestrator: only the content hash changes in the control.
    for changed in (False, True):
        owner, _, _ = fake_service()
        owner._known_hashes = lambda: {"/virtual/company.md": "old-hash"}
        with (
            patch.object(service, "iter_corpus_files", return_value=[Path("/virtual/company.md")]),
            patch.object(
                service, "content_hash", return_value="new-hash" if changed else "old-hash"
            ),
            patch.object(
                service, "parse_document", side_effect=ValueError("parser-reached")
            ) as parser,
            patch.object(service.logger, "exception"),
        ):
            result = owner.ingest_dir("/virtual")
        check(
            "changed_source_reaches_parser" if changed else "same_source_new_cleaner_refresh",
            "The requested cleaning pass reaches the current parser",
            parser.call_count == 1,
            {"parser_calls": parser.call_count, "skipped_unchanged": result.skipped_unchanged},
        )

    # Single-file entry reparses, but content-only ON CONFLICT leaves old blocks.
    owner, _, cursor = fake_service()
    cursor.fetchone.side_effect = [{"inserted": True}, None]
    doc = ingest.ParsedDocument(
        "undated_abcd1234",
        "company",
        "/virtual/company.md",
        "same-hash",
        "text/markdown",
        [ingest.Block(0, "body", "OLD_TEXT")],
    )
    with patch.object(service, "parse_document", return_value=doc):
        first = owner.ingest_path("/virtual/company.md")
        doc.blocks = [ingest.Block(0, "body", "CLEANED_TEXT")]
        second = owner.ingest_path("/virtual/company.md")
    writes = cursor.executemany.call_args_list
    check(
        "single_file_reclean_updates_blocks",
        "Second parsed version can be published",
        len(writes) == 2,
        {
            "first_added": first[1],
            "second_added": second[1],
            "block_write_calls": len(writes),
            "persisted_text": writes[0].args[1][0][-1],
            "io": "fake PG cursor; not a live SQL test",
        },
    )

    # Data commit and metadata refresh are separate; retry takes duplicate path.
    owner, connection, cursor = fake_service()
    cursor.fetchone.side_effect = [{"inserted": True}, None]
    owner.refresh_metadata.side_effect = RuntimeError("synthetic-metadata-failure")
    with patch.object(service, "parse_document", return_value=doc):
        try:
            owner.ingest_path("/virtual/company.md")
        except RuntimeError:
            failed_after_commit = connection.commit.call_count > 0
        else:
            failed_after_commit = False
        owner.refresh_metadata.side_effect = None
        owner.ingest_path("/virtual/company.md")
    check(
        "retry_repairs_failed_metadata",
        "Retry completes interrupted metadata stage",
        owner.refresh_metadata.call_count == 2,
        {
            "failed_after_data_commit": failed_after_commit,
            "metadata_calls_after_retry": owner.refresh_metadata.call_count,
        },
    )

    path = Path("/virtual/industry.md")
    short = "# 行业点评\n需求仍弱，维持谨慎。\n"
    with source_text(path, short):
        short_doc = ingest.parse_document(path)
        short_evidence = evidence.parse_evidence(path)
    check(
        "readable_short_text_not_ocr",
        "Readable Markdown must not be classified as needing OCR",
        short_doc.status != "needs_ocr",
        {
            "legacy_status": short_doc.status,
            "evidence_status": [p.status for p in short_evidence.packets],
        },
    )

    duplicate = "# 风险\n需求不及预期。\n# 风险\n成本上涨。\n"
    with source_text(path, duplicate):
        blocks = ingest.parse_markdown(path)
        parsed = evidence.parse_evidence(path)
    counts = Counter(b.locator for b in blocks)
    check(
        "unique_fetch_locator",
        "Each exposed doc_id + locator identifies one block",
        len(counts) == len(blocks),
        {
            "blocks": len(blocks),
            "locator_counts": dict(counts),
            "evidence_has_offsets": all(
                s.start is not None for p in parsed.packets for s in p.spans
            ),
        },
    )

    # Same bytes, no hypothetical damaged database: the two parsers expose different views.
    mixed = "# 公司评级\n给予买入评级。\n分析师声明：若需求下降，上述盈利预测失效。\n"
    with source_text(path, mixed):
        index_view = ingest.parse_markdown(path)
        evidence_view = evidence.parse_evidence(path)
    qualifier = "若需求下降，上述盈利预测失效"
    check(
        "cleaning_preserves_substantive_qualifier",
        "Filtering a boilerplate prefix does not erase a substantive condition",
        any(qualifier in b.text for b in index_view),
        {
            "index_keeps_qualifier": any(qualifier in b.text for b in index_view),
            "evidence_keeps_qualifier": any(qualifier in p.text for p in evidence_view.pages),
            "scope": "synthetic prefix counterexample; no corpus frequency inferred",
        },
    )

    # Exercise actual PDF orchestration with page API doubles, not a generated PDF.
    page_texts = ["公司收入持续增长。" * 40, ""]

    class PDF:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> bool:
            return False

        def __iter__(self) -> Iterator[SimpleNamespace]:
            return iter([SimpleNamespace(get_text=lambda *_a, t=t: t) for t in page_texts])

    with (
        patch.object(ingest, "content_hash", return_value="mixed-pages"),
        patch.object(ingest, "extract_pdf_tables", return_value={}),
        patch.object(ingest.pymupdf, "open", return_value=PDF()),
    ):
        mixed_doc = ingest.parse_document("/virtual/company.pdf")
    check(
        "mixed_pdf_exposes_unreadable_page",
        "A text page cannot hide an empty/image page behind whole-document ok",
        mixed_doc.status != "ok",
        {
            "status": mixed_doc.status,
            "page_chars": [len(b.text) for b in mixed_doc.blocks],
            "scope": "synthetic page API; actual PDF rendering not tested",
        },
    )

    # Default candidate discovery is format-based, not admission policy.
    names = ["company.md", "会议纪要.md", "README.md"]
    with (
        patch.object(Path, "iterdir", return_value=iter(Path("/virtual") / n for n in names)),
        patch.object(Path, "is_file", return_value=True),
    ):
        admitted = [p.name for p in ingest.iter_corpus_files("/virtual")]
    check(
        "default_minutes_exclusion",
        "Confirmed minutes are excluded by the new default policy",
        "会议纪要.md" not in admitted,
        {
            "discovered_files": admitted,
            "note": "new requirement not implemented; filename alone is not a final classifier",
        },
    )

    # Real old service path requires neither a documents row nor a PG connection.
    owner, _, _ = fake_service()
    owner._connect.side_effect = AssertionError("unexpected database dependency")
    with source_text(path, "# 公司研究\n" + "需求可能增长，但盈利预测仍存在不确定性。" * 5):
        material = owner.understand_material(path=path, max_calls=0, extract_relations=False)
    check(
        "r2_direct_path_database_independent",
        "Path-based R2 can prepare a result without database I/O",
        owner._connect.call_count == 0,
        {
            "postgres_calls": owner._connect.call_count,
            "result_type": type(material).__name__,
            "model_calls": 0,
            "note": "no semantic quality claim at zero model budget",
        },
    )

    # Replay only frozen plan/wire. Do not call prepare(): it reads gold/source assets.
    pins = {
        "r2-p4-item-plan.json": "96ca9d113dab13a18e22a2f726ec2df04bdb9b747636d0183e6852cc25a1bc7e",
        "p4-runs/p4-items-1/audit-export.json": "0bcd1497e74195b6c44ec487794266fdd0749ebeb1547ee59ad093d63c883966",
        "p4_item_trial.py": "035af033498e59151509e4b771debdcd5214b046407f2689e67fb59a800911cc",
    }
    for relative, expected in pins.items():
        assert hashlib.sha256((HERE / relative).read_bytes()).hexdigest() == expected
    saved = json.loads((HERE / "r2-p4-item-plan.json").read_text())
    plan = trial.TrialPlan(
        **{
            **saved,
            "obligations": tuple(trial.Obligation(**row) for row in saved["obligations"]),
            **{
                key: tuple(saved[key])
                for key in ("scope_ids", "empty_scope_ids", "unknown_field_vocabulary")
            },
        }
    )
    audit = json.loads((HERE / "p4-runs/p4-items-1/audit-export.json").read_text())
    attempt = audit["attempts"][0]
    request = json.loads(attempt["request"].split("INPUT_JSON=", 1)[1])
    ids = {row["obligation_id"] for row in request["obligations"]}
    rows, errors = trial._parse_records(plan, (attempt["raw"],), ids)
    invalid = Counter(
        json.loads(line)["fields"]["semantic_type"]
        for line in attempt["raw"].splitlines()
        if line.strip() and json.loads(line)["fields"]["semantic_type"] not in trial.SEMANTIC_TYPES
    )
    check(
        "p4_protocol_valid_without_database",
        "Archived response passes its frozen protocol even without any database",
        len(rows) == len(ids) and not errors,
        {
            "attempted": len(ids),
            "valid": len(rows),
            "invalid_enums": dict(invalid),
            "postgres_calls": 0,
            "new_model_calls": 0,
        },
    )

    files = [
        "plugins/corpus/ingest.py",
        "plugins/corpus/service.py",
        "plugins/corpus/evidence.py",
        "plugins/corpus/metadata.py",
        "plugins/corpus/evidence_pipeline.py",
    ]
    return {
        "version": "cleaning-ingestion-diagnosis-v1",
        "purpose": "diagnosis_not_fix_or_business_acceptance",
        "checks": checks,
        "unmet_contract_count": sum(not row["passed"] for row in checks),
        "network": network,
        "real_postgres_connections": 0,
        "new_model_calls": 0,
        "corpus_source_reads": 0,
        "production_code_changes": 0,
        "code_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in files},
        "archived_input_sha256": pins,
        "limitations": [
            "synthetic fixtures, fake PG I/O; not live SQL durability or corpus-wide audit",
            "P4 replay checks archived wire only, not whole R2 capability",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    parser.add_argument("--assert-clean", action="store_true")
    args = parser.parse_args()
    result = investigate()
    if args.out:
        with args.out.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    for row in result["checks"]:
        print(
            ("PASS" if row["passed"] else "GAP"),
            row["id"],
            json.dumps(row["observed"], ensure_ascii=False),
        )
    print("unmet_contract_count=", result["unmet_contract_count"])
    if args.assert_clean and result["unmet_contract_count"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
