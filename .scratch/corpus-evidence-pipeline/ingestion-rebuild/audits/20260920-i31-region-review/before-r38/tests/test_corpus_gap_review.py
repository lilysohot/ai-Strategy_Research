"""Human review never changes default grading, source evidence, or scope coverage."""

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime

import pytest

from plugins.corpus.preparation.contract import (
    Build,
    CharSpan,
    Unit,
    UnitLocation,
    canonical_fingerprint,
    sha256_of_bytes,
)
from plugins.corpus.preparation.gap_review import (
    GapReview,
    GapReviewError,
    apply_gap_review,
    review_template,
)
from plugins.corpus.preparation.gaps import GapDisposition, GapLifecycle, gap_records

GAP = "issue:image_region_unreadable:page:2"
NOW = datetime(2026, 9, 20, tzinfo=UTC)


def build():
    return Build(
        "a" * 64,
        "b" * 64,
        "admission-1",
        "parse-1",
        "clean-1",
        "chunk-1",
        "index-1",
        quality_report=json.dumps({"gap_regions": [GAP], "oversized_chunks": []}),
    )


def units():
    return (
        Unit(
            "u1",
            "a" * 64,
            "paragraph",
            "evidence",
            sha256_of_bytes(b"evidence"),
            location=UnitLocation(page=1, char_span=CharSpan(0, 8)),
        ),
    )


def signed_record(target=None, **overrides):
    target = target or build()
    data = review_template(target, gap_records([GAP]))
    data.update(
        reviewer="test-human",
        reviewed_at=NOW.isoformat(),
        evidence_scope_ref="synthetic-approved-scope-1",
        required_locators=["page:1"],
        scope_rationale="Human confirms this is the complete required evidence set.",
        gaps={GAP: "Human inspected page 2: illustration unrelated to required page 1."},
        attestation="human_verified_complete_scope_and_nonintersection",
    )
    data.update(overrides)
    return GapReview.from_json(json.dumps(data))


def test_disjoint_human_review_changes_lifecycle_only():
    original = build()
    records = apply_gap_review(signed_record(), original, units(), gap_records([GAP]))
    assert records[0].disposition is GapDisposition.BLOCKING
    assert records[0].lifecycle is GapLifecycle.ACKNOWLEDGED
    assert records[0].basis.startswith("human_gap_review:")
    assert GAP in original.quality_report
    assert canonical_fingerprint(asdict(original)) == signed_record().build_fingerprint


@pytest.mark.parametrize("locator", ["page:2", "char:0-8", "page:0", "body[0]", "page:99"])
def test_overlap_unmapped_invalid_or_absent_evidence_fails_closed(locator):
    with pytest.raises(GapReviewError):
        apply_gap_review(
            signed_record(required_locators=[locator]), build(), units(), gap_records([GAP])
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("reviewer", " "),
        ("reviewed_at", "2026-09-20"),
        ("required_locators", []),
        ("scope_rationale", ""),
        ("evidence_scope_ref", ""),
        ("attestation", ""),
        ("gaps", {GAP: " "}),
        ("gaps", {}),
        ("policy_rev", "old-policy"),
    ],
)
def test_unsigned_incomplete_or_stale_record_rejected(field, value):
    with pytest.raises(GapReviewError):
        apply_gap_review(signed_record(**{field: value}), build(), units(), gap_records([GAP]))


@pytest.mark.parametrize(
    "change",
    [
        {"build_id": "c" * 64},
        {"source_id": "c" * 64},
        {"decision_id": "admission-2"},
        {"scope_ref": "char:0-8"},
        {"parse_rev": "parse-2"},
        {"quality_report": '{"gap_regions": [], "oversized_chunks": []}'},
    ],
)
def test_cross_build_source_scope_revision_or_ledger_replay_rejected(change):
    with pytest.raises(GapReviewError):
        apply_gap_review(signed_record(), replace(build(), **change), units(), gap_records([GAP]))


def test_template_cannot_be_used_as_a_signature():
    with pytest.raises(GapReviewError):
        GapReview.from_json(json.dumps(review_template(build(), gap_records([GAP]))))


def test_unknown_keys_and_duplicate_json_fields_rejected():
    with pytest.raises(GapReviewError):
        signed_record(extra="silently ignored?")
    data = signed_record().to_json()
    with pytest.raises(GapReviewError):
        GapReview.from_json(data[:-1] + ', "reviewer": "different"}')


@pytest.mark.parametrize(
    "location,accepted", [("char:8-10", True), ("char:7-10", False), ("char:8-", False)]
)
def test_character_nonintersection_uses_half_open_bounded_intervals(location, accepted):
    key = f"issue:table_lines_without_extraction:{location}"
    target = replace(
        build(), quality_report=json.dumps({"gap_regions": [key], "oversized_chunks": []})
    )
    review = signed_record(target, required_locators=["char:0-8"], gaps={key: "Synthetic review"})
    if accepted:
        assert (
            apply_gap_review(review, target, units(), gap_records([key]))[0].lifecycle
            is GapLifecycle.ACKNOWLEDGED
        )
    else:
        with pytest.raises(GapReviewError):
            apply_gap_review(review, target, units(), gap_records([key]))


def test_unknown_code_and_omitted_gap_cannot_be_signed_away():
    for key in ("issue:future_code:page:2", "unparseable"):
        target = replace(
            build(), quality_report=json.dumps({"gap_regions": [key], "oversized_chunks": []})
        )
        with pytest.raises(GapReviewError):
            apply_gap_review(
                signed_record(target, gaps={key: "Checked"}), target, units(), gap_records([key])
            )
    with pytest.raises(GapReviewError):
        apply_gap_review(
            signed_record(), build(), units(), gap_records([GAP, "issue:image_only_page:page:3"])
        )


def _build_pdf(tmp_path, store=None):
    import pymupdf

    from plugins.corpus.preparation.admission import POLICY_REV_V1, AdmissionPolicy
    from plugins.corpus.preparation.contract import (
        LeaseConfig,
        ResearchDomain,
        ReviewDecision,
        ReviewedDecision,
    )
    from plugins.corpus.preparation.engine import PlanEntry, execute_builds, plan_builds
    from plugins.corpus.preparation.repository import MemoryStore

    path = tmp_path / "synthetic-review.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((60, 80), "Research report: Company earnings rose 20 percent in 2026.")
        page = doc.new_page()
        page.insert_text((60, 80), "Supplemental illustration, unrelated to page one evidence.")
        page.insert_image(pymupdf.Rect(30, 200, 560, 700), stream=b"P6\n1 1\n255\n\xff\x00\x00")
        doc.save(path)
    store = store if store is not None else MemoryStore(clock=lambda: NOW)
    store.put_reviewed_decision(
        ReviewedDecision(
            "review-test",
            sha256_of_bytes(path.read_bytes()),
            "test-human",
            NOW,
            ReviewDecision.ADMITTED,
            "Synthetic report approval",
        )
    )
    policy = AdmissionPolicy(POLICY_REV_V1, tuple(ResearchDomain))
    plan = plan_builds(
        [
            PlanEntry(
                str(path), domain_hint=ResearchDomain.COMPANY, review_decision_ids=("review-test",)
            )
        ],
        policy=policy,
    )
    result = execute_builds(
        store,
        plan,
        policy=policy,
        archive_root=tmp_path / "archive",
        owner_id="test",
        now=NOW,
        lease=LeaseConfig(300, 60, 600, 3),
    )
    target = result.outcomes[0].build
    assert target is not None
    assert json.loads(target.quality_report)["gap_regions"] == [GAP]
    return store, target


@pytest.fixture
def built_pdf(tmp_path):
    return _build_pdf(tmp_path)


def test_real_reader_build_publish_and_retry_keep_gap_and_audit(built_pdf):
    from plugins.corpus.preparation.contract import JobStage
    from plugins.corpus.preparation.engine import (
        EngineError,
        check_build_publishable,
        gap_records_of,
        publish_build,
    )
    from plugins.corpus.preparation.read_pg import _coverage_from_row

    store, target = built_pdf
    before_units = store.get_units(target.build_id)
    before_chunks = store.get_chunks(target.build_id)
    with pytest.raises(EngineError, match="gap_regions"):
        publish_build(store, target.build_id, activated_at=NOW)
    review = signed_record(target)
    store.put_gap_review(review)
    assert check_build_publishable(store, target.build_id) == target
    publication = publish_build(store, target.build_id, activated_at=NOW, operator="publisher")
    assert publication.active_build_id == target.build_id
    assert publish_build(store, target.build_id, activated_at=NOW) == publication
    checkpoint = json.loads(store.get_job(target.build_id, JobStage.PUBLISHED).checkpoint)
    assert checkpoint["human_gap_review_id"] == review.review_id
    assert checkpoint["operator"] == "publisher"
    assert checkpoint["acknowledged_gaps"] == [GAP]
    assert gap_records_of(target, store=store)[0].lifecycle is GapLifecycle.ACKNOWLEDGED
    assert gap_records_of(target)[0].lifecycle is GapLifecycle.BLOCKING
    assert store.get_build(target.build_id) == target
    assert store.get_units(target.build_id) == before_units
    assert store.get_chunks(target.build_id) == before_chunks
    coverage = _coverage_from_row((1, 1, 0, 0, 0, 1, "snapshot", 1), "matched")
    assert coverage["processing"] == "scoped"
    assert coverage["availability"] == "unknown"
    assert "gap_regions_present" in coverage["reason_codes"]


def test_immutable_review_and_generic_checkpoint_bypass(built_pdf):
    from plugins.corpus.preparation.gap_review import REVIEW_STAGE_PREFIX
    from plugins.corpus.preparation.repository import StoreError

    store, target = built_pdf
    review = signed_record(target)
    store.put_gap_review(review)
    store.put_gap_review(review)
    with pytest.raises(StoreError, match="conflict"):
        store.put_gap_review(replace(review, reviewer="another human"))
    with pytest.raises(StoreError, match="namespace"):
        store.put_source_checkpoint(target.source_id, REVIEW_STAGE_PREFIX + target.build_id, "{}")
    assert store.get_gap_review(target.build_id) == review


@pytest.mark.parametrize("broken_gate", ["oversized_chunks", "unreferenced_unit"])
def test_human_review_does_not_bypass_other_publication_gates(built_pdf, broken_gate):
    from plugins.corpus.preparation.engine import EngineError, publish_build

    store, target = built_pdf
    if broken_gate == "oversized_chunks":
        target = replace(
            target,
            quality_report=json.dumps({"gap_regions": [GAP], "oversized_chunks": ["too-long"]}),
        )
        store._builds[target.build_id] = target  # Fault injection only.
    else:
        store._chunks.clear()  # Required retained units are no longer covered by chunks.
    store.put_gap_review(signed_record(target))
    with pytest.raises(EngineError, match=r"oversized_chunks|未被任何 chunk"):
        publish_build(store, target.build_id, activated_at=NOW)
    assert store.get_publication(target.source_id) is None


@pytest.mark.parametrize("corruption", [None, "{}"])
def test_missing_or_corrupt_review_rejects_published_retry(built_pdf, corruption):
    from plugins.corpus.preparation.engine import EngineError, publish_build
    from plugins.corpus.preparation.gap_review import REVIEW_STAGE_PREFIX

    store, target = built_pdf
    store.put_gap_review(signed_record(target))
    publication = publish_build(store, target.build_id, activated_at=NOW)
    key = target.source_id, REVIEW_STAGE_PREFIX + target.build_id
    if corruption is None:
        del store._source_checkpoints[key]
    else:
        store._source_checkpoints[key] = corruption
    with pytest.raises(EngineError, match="human review"):
        publish_build(store, target.build_id, activated_at=NOW)
    assert store.get_publication(target.source_id) == publication


def test_unsigned_cli_template_and_signed_import_share_check_status_view(
    built_pdf, monkeypatch, capsys, tmp_path
):
    from contextlib import contextmanager

    from plugins.corpus import cli

    store, target = built_pdf

    @contextmanager
    def open_store(args):
        yield store

    monkeypatch.setattr(cli, "_open_store", open_store)
    assert cli.main(["gap-review", "--build", target.build_id]) == 0
    template = json.loads(capsys.readouterr().out)
    assert template["reviewer"] == template["attestation"] == ""
    record_path = tmp_path / "signed-synthetic.json"
    record_path.write_text(signed_record(target).to_json())
    assert cli.main(["gap-review", "--build", target.build_id, "--record", str(record_path)]) == 0
    response = json.loads(capsys.readouterr().out)
    assert response["gap_summary"]["blocking"] == 0
    assert response["gaps"][0]["disposition"] == "blocking"
    assert cli._gap_view(target, store).gaps == response["gaps"]
