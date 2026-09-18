"""Bounded synthetic checks of repaired scope, lifecycle, archive and checkpoint seams."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from plugins.corpus.preparation.admission import AdmissionPolicy, POLICY_REV_V1
from plugins.corpus.preparation.contract import (
    LeaseConfig, ResearchDomain, ReviewedDecision, ReviewDecision, source_id_from_bytes,
)
from plugins.corpus.preparation.engine import (
    EngineCancelled, EngineError, PlanEntry, execute_builds, plan_builds, publish_build,
)
from plugins.corpus.preparation.readers import read_document
from plugins.corpus.preparation.repository import MemoryStore, StoreError
from plugins.corpus.preparation.source import ingest_source, SourceIngestError
from plugins.corpus.preparation import source as source_module

ROOT = Path(__file__).resolve().parents[5]
NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)
POLICY = AdmissionPolicy(POLICY_REV_V1, tuple(ResearchDomain))
LEASE = LeaseConfig(300, 60, 600, 3)
TEXT = "# Report\n\nApproved beginning.\n\nOutside 987654.\n"


def setup(tmp_path, scope=None, *, clock=None):
    path = tmp_path / "report.md"
    path.write_text(TEXT, encoding="utf-8")
    store = MemoryStore(clock=clock or (lambda: NOW))
    approve(store, path, scope)
    return store, path


def approve(store, path, scope=None):
    sid = source_id_from_bytes(path.read_bytes())
    store.put_reviewed_decision(ReviewedDecision(
        "r1", sid, "synthetic-reviewer", NOW, ReviewDecision.ADMITTED, "audit approval",
        scope_ref=scope, locators=(scope,) if scope else (),
    ))


def execute(store, path, tmp_path, *, reviews=("r1",), reader=read_document,
            cancel_check=None, clock=None, lease=LEASE):
    plan = plan_builds([PlanEntry(str(path), domain_hint=ResearchDomain.COMPANY,
                                 review_decision_ids=reviews)], policy=POLICY)
    return execute_builds(store, plan, policy=POLICY, archive_root=tmp_path / "archive",
                          owner_id="audit", now=NOW, lease=lease, reader=reader,
                          cancel_check=cancel_check, clock=clock).outcomes[0]


@pytest.mark.parametrize("scope", [" ", ",", " , "])
def test_nonempty_but_invalid_scope_never_means_full_document(tmp_path, scope):
    store, path = setup(tmp_path, scope)
    try:
        result = execute(store, path, tmp_path)
        if result.build is None:
            return
        publish_build(store, result.build.build_id, activated_at=NOW)
    except (EngineError, StoreError):
        return
    pytest.fail("invalid nonempty scope silently published all text")


def test_partial_unit_overlap_cannot_publish_as_complete_scope(tmp_path):
    # Heading fits; the next unit contains approved characters but extends past scope.
    store, path = setup(tmp_path, "char:0-18")
    try:
        result = execute(store, path, tmp_path)
        if result.build is None:
            return
        publish_build(store, result.build.build_id, activated_at=NOW)
    except (EngineError, StoreError):
        return  # Rejecting unsupported partial-unit scopes is safe.
    rendered = "\n".join(c.search_text for c in store.get_chunks(result.build.build_id))
    assert "Approved" in rendered, "approved text was dropped, but scope was published as complete"


def test_preexisting_cancellation_prevents_expensive_reader_call(tmp_path):
    store, path = setup(tmp_path)
    reads = []
    def reader(p):
        reads.append(p)
        return read_document(p)
    with pytest.raises(EngineCancelled):
        execute(store, path, tmp_path, reader=reader, cancel_check=lambda: True)
    assert reads == [], "cancel already true, but full parsing still ran before checking it"


def test_parse_time_counts_toward_stage_deadline(tmp_path):
    current = [NOW]
    store, path = setup(tmp_path, clock=lambda: current[0])
    def reader(p):
        current[0] += timedelta(seconds=2)
        return read_document(p)
    # No sleep: two simulated seconds exceed the configured one-second stage budget.
    with pytest.raises(EngineError, match="超时"):
        execute(store, path, tmp_path, reader=reader, clock=lambda: current[0],
                lease=LeaseConfig(300, 60, 1, 3))


def test_checkpoint_issue_loss_is_detected_before_publication(tmp_path):
    path = ROOT / "tests/fixtures/corpus_preparation/synthetic-company-report.pdf"
    store = MemoryStore(clock=lambda: NOW)
    result = execute(store, path, tmp_path, reviews=())
    assert result.build is None  # Parse-only pending admission leaves a checkpoint.
    sid = result.source.source_id
    payload = json.loads(store.get_source_checkpoint(sid, "parse"))
    assert any(i["code"] == "image_only_page" for i in payload["issues"])
    payload["issues"] = []  # Simulate checkpoint damage; raw-text hashes are unchanged.
    store.put_source_checkpoint(sid, "parse", json.dumps(payload))
    approve(store, path)
    result = execute(store, path, tmp_path)
    assert result.build is not None
    with pytest.raises((EngineError, StoreError)):
        publish_build(store, result.build.build_id, activated_at=NOW)


def test_staging_symlink_must_not_write_outside_archive_root(tmp_path, monkeypatch):
    archive = tmp_path / "archive"
    outside = tmp_path / "outside"
    archive.mkdir()
    outside.mkdir()
    (archive / "_staging").symlink_to(outside, target_is_directory=True)
    path = tmp_path / "report.md"
    path.write_text(TEXT, encoding="utf-8")
    original = source_module.tempfile.mkstemp
    actual_locations = []
    def observed(*args, **kwargs):
        fd, name = original(*args, **kwargs)
        actual_locations.append(Path(name).resolve())
        return fd, name
    monkeypatch.setattr(source_module.tempfile, "mkstemp", observed)
    try:
        ingest_source(MemoryStore(clock=lambda: NOW), path, archive)
    except SourceIngestError:
        pass
    assert not any(outside in p.parents for p in actual_locations), actual_locations


def test_control_valid_scope_and_intact_checkpoint_publish(tmp_path):
    store, path = setup(tmp_path, "char:0-29")
    reads = []
    def reader(p):
        reads.append(p)
        return read_document(p)
    first = execute(store, path, tmp_path, reader=reader)
    second = execute(store, path, tmp_path, reader=reader)
    assert first.build == second.build and len(reads) == 1
    publication = publish_build(store, second.build.build_id, activated_at=NOW)
    assert publication.active_build_id == second.build.build_id
    chunks = store.get_chunks(second.build.build_id)
    assert "Approved beginning." in "\n".join(c.search_text for c in chunks)
    assert "987654" not in "\n".join(c.search_text for c in chunks)
