"""I1 integration acceptance: synthetic sources, injected storage failures, no PG/model."""
from datetime import UTC, datetime

import pymupdf
import pytest

from plugins.corpus.preparation.admission import AdmissionPolicy, POLICY_REV_V1
from plugins.corpus.preparation.contract import (
    ResearchDomain, ReviewedDecision, ReviewDecision, LeaseConfig, source_id_from_bytes,
)
from plugins.corpus.preparation.engine import (
    EngineError, PlanEntry, plan_builds, execute_builds, publish_build,
)
from plugins.corpus.preparation.readers import read_document
from plugins.corpus.preparation.readers.base import ReaderError
from plugins.corpus.preparation.repository import MemoryStore, StoreError
from plugins.corpus.preparation.source import ingest_source, SourceIngestError

NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)
POLICY = AdmissionPolicy(POLICY_REV_V1, tuple(ResearchDomain))
LEASE = LeaseConfig(300, 60, 600, 3)
NORMAL = "# 证券公司研究\n\nApproved section.\n\nOutside approved scope: 987654.\n"


def source_and_review(tmp_path, store, text=NORMAL, scope=None):
    path = tmp_path / "report.md"
    path.write_text(text, encoding="utf-8")
    sid = source_id_from_bytes(path.read_bytes())
    locators = ("char:0-34",) if scope else ()
    store.put_reviewed_decision(ReviewedDecision(
        "r1", sid, "reviewer", NOW, ReviewDecision.ADMITTED, "synthetic approval",
        scope_ref=scope, locators=locators,
    ))
    return path, sid


def execute(tmp_path, store, path, reviews=("r1",), reader=read_document):
    plan = plan_builds([PlanEntry(str(path), domain_hint=ResearchDomain.COMPANY,
                                 review_decision_ids=reviews)], policy=POLICY)
    return execute_builds(store, plan, policy=POLICY, archive_root=tmp_path / "archive",
                          owner_id="audit", now=NOW, lease=LEASE, reader=reader).outcomes[0]


class RejectSourceStore(MemoryStore):
    def put_source(self, source):
        raise StoreError("injected source registration failure")


class FlakyChunkStore(MemoryStore):
    fail = True

    def put_chunks(self, build_id, chunks, **kwargs):
        if self.fail:
            raise StoreError("injected chunk write failure")
        return super().put_chunks(build_id, chunks, **kwargs)


def test_engine_stops_if_source_registration_fails(tmp_path):
    store = RejectSourceStore(clock=lambda: NOW)
    path, sid = source_and_review(tmp_path, store)
    try:
        outcome = execute(tmp_path, store, path)
    except (EngineError, StoreError):
        assert store.latest_admission(sid) is None
        return
    assert outcome.build is None, "source missing from store but engine reports a completed build"


def test_scoped_approval_cannot_publish_out_of_scope_chunk(tmp_path):
    store = MemoryStore(clock=lambda: NOW)
    path, _ = source_and_review(tmp_path, store, scope="char:0-34")
    try:
        outcome = execute(tmp_path, store, path)
    except (EngineError, StoreError):
        return  # Unsupported scope syntax must fail closed, not fall back to full text.
    if outcome.build is None:
        return
    # Full raw-source archival may be valid; publication/search must obey approved scope.
    chunk = store.get_chunk(f"{outcome.build.build_id[:16]}:body:0000")
    assert chunk is not None
    publish_build(store, outcome.build.build_id, activated_at=NOW)
    assert "987654" not in chunk.search_text, chunk.search_text


@pytest.mark.parametrize("kind", ["unread_image", "oversized"])
def test_quality_failure_blocks_regular_publication(tmp_path, kind):
    store = MemoryStore(clock=lambda: NOW)
    if kind == "oversized":
        # No heading: isolate the publication gate from the independent heading/oversized bug.
        path, _ = source_and_review(tmp_path, store, text="A" * 2000 + "\n")
    else:
        path = tmp_path / "证券公司研究.pdf"
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((72, 72), "Readable title", fontsize=11)
            page.insert_image(pymupdf.Rect(72, 100, 520, 700),
                              pixmap=pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 10, 10)))
            doc.save(str(path))
        sid = source_id_from_bytes(path.read_bytes())
        store.put_reviewed_decision(ReviewedDecision(
            "r1", sid, "reviewer", NOW, ReviewDecision.ADMITTED, "synthetic approval"))
    try:
        outcome = execute(tmp_path, store, path)
    except (EngineError, StoreError):
        return
    assert outcome.build is not None
    assert outcome.build.quality_report
    with pytest.raises((EngineError, StoreError)):
        publish_build(store, outcome.build.build_id, activated_at=NOW)


def test_failed_chunk_stage_cannot_publish_partial_build(tmp_path):
    store = FlakyChunkStore(clock=lambda: NOW)
    path, _ = source_and_review(tmp_path, store)
    captured = []
    original_put_build = store.put_build

    def capture_build(build):
        captured.append(build)
        return original_put_build(build)

    store.put_build = capture_build
    with pytest.raises(StoreError, match="injected chunk"):
        execute(tmp_path, store, path)
    assert captured
    with pytest.raises((EngineError, StoreError)):
        publish_build(store, captured[0].build_id, activated_at=NOW)


def test_explicit_exclusion_is_not_blocked_by_parser_failure(tmp_path):
    store = MemoryStore(clock=lambda: NOW)
    path, sid = source_and_review(tmp_path, store)
    outcome = execute(tmp_path, store, path)
    publish_build(store, outcome.build.build_id, activated_at=NOW)
    store.put_reviewed_decision(ReviewedDecision(
        "r2", sid, "reviewer", NOW, ReviewDecision.EXCLUDED, "explicit revocation", supersedes="r1"))

    def broken_reader(path):
        raise ReaderError("injected parser unavailable")

    try:
        execute(tmp_path, store, path, reviews=("r1", "r2"), reader=broken_reader)
    except ReaderError:
        pass
    assert store.get_publication(sid).active_build_id is None


def test_retry_does_not_reparse_completed_phase(tmp_path):
    store = FlakyChunkStore(clock=lambda: NOW)
    path, _ = source_and_review(tmp_path, store)
    reads = []

    def reader(archived_path):
        reads.append(archived_path)
        return read_document(archived_path)

    with pytest.raises(StoreError, match="injected chunk"):
        execute(tmp_path, store, path, reader=reader)
    store.fail = False
    outcome = execute(tmp_path, store, path, reader=reader)
    assert outcome.build is not None
    assert len(reads) == 1, "PARSED already succeeded but retry invokes reader again"


def test_archive_shard_symlink_cannot_escape_archive_root(tmp_path):
    store = MemoryStore(clock=lambda: NOW)
    path = tmp_path / "input.md"
    path.write_text("synthetic archive", encoding="utf-8")
    sid = source_id_from_bytes(path.read_bytes())
    archive = tmp_path / "archive"
    outside = tmp_path / "outside-archive"
    archive.mkdir()
    outside.mkdir()
    (archive / sid[:2]).symlink_to(outside, target_is_directory=True)
    with pytest.raises(SourceIngestError):
        ingest_source(store, path, archive)


def test_heading_before_oversized_unit_is_not_dropped(tmp_path):
    store = MemoryStore(clock=lambda: NOW)
    path, _ = source_and_review(tmp_path, store, text="# 证券公司研究\n\n" + "A" * 2000 + "\n")
    result = execute(tmp_path, store, path)
    assert result.build is not None
    assert store.get_unit(result.build.build_id, "unit:0001") is not None


def test_control_normal_chain_can_publish(tmp_path):
    store = MemoryStore(clock=lambda: NOW)
    path, sid = source_and_review(tmp_path, store)
    result = execute(tmp_path, store, path)
    assert store.get_source(sid) is not None
    pub = publish_build(store, result.build.build_id, activated_at=NOW)
    assert pub.active_build_id == result.build.build_id


def test_control_source_module_exposes_registration_failure(tmp_path):
    store = RejectSourceStore(clock=lambda: NOW)
    path, sid = source_and_review(tmp_path, store)
    result = ingest_source(store, path, tmp_path / "archive")
    assert not result.registered and result.error
    assert store.get_source(sid) is None
