"""M1 contract tests: source identity, immutable candidates, explicit application trust."""

import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from plugins.corpus.evidence import EvidenceDocument, EvidencePacket, fingerprint
from plugins.corpus.evidence_pipeline import EvidenceRun, extract_evidence
from plugins.corpus.macro_models import (
    BlockedInput,
    ConsensusSnapshot,
    Dimensions,
    EvidenceBinding,
    MacroObservation,
    Qualifier,
    RawAmount,
    ReleaseEvent,
    SourceTime,
    VerificationRecord,
    Vintage,
    index_unique,
    load_record,
    reference_from_run,
    resolve_reference,
)
from plugins.corpus.macro_verification import (
    UnitNormalization,
    VerificationAuthority,
    normalize_jobs,
)


def moment(raw="2026-09-04T08:30:00-04:00"):
    return SourceTime(raw=raw)


def observation(**changes):
    return MacroObservation(
        **{
            "dimensions": Dimensions(
                country="US",
                indicator="US.NFP_CHANGE_SA",
                population="nonfarm_payroll_jobs",
                transform="month_change",
                adjustment="SA",
            ),
            "role": "actual",
            "kind": "observed",
            "reference_month": "2026-08",
            "amount": RawAmount(value_raw="16.2", unit_raw="万"),
            **changes,
        }
    )


@pytest.fixture
def source():
    text = "2026年8月新增非农就业为16.2万。"
    packet = EvidencePacket(packet_id=fingerprint(text), locator="1", kind="prose", text=text)
    document = EvidenceDocument(
        doc_id="synthetic",
        title="synthetic",
        source_path="synthetic",
        source_rev="f" * 16,
        parse_rev="e" * 64,
        parser_version="test",
        subject=None,
        published="2026-09-04",
        pages=(),
        packets=(packet,),
    )
    run = extract_evidence(document)
    ref = reference_from_run(run, packet.packet_id, text)
    return run, ref


@pytest.fixture
def authority(source):
    run, _ = source
    return VerificationAuthority(
        issuer_id="reviewer:test",
        issuer_role="human_reviewer",
        policy_version="mapping-test-1",
        resolve=lambda ref: resolve_reference(ref, run),
    )


def receipt(authority, source, subject, **changes):
    return authority.issue(
        subject,
        **{
            "scopes": ("indicator", "unit_mapping"),
            "evidence": (source[1],),
            "reviewed_at": moment(),
            "decision": "approved",
            **changes,
        },
    )


def test_all_record_types_roundtrip_and_content_identity(source, authority):
    event = ReleaseEvent(
        publisher="BLS",
        release_key="synthetic-event",
        reference_month="2026-08",
        release_at=moment(),
    )
    vintage = Vintage(
        release_event_id=event.record_id,
        reference_month="2026-08",
        vintage_kind="first",
        published_at=moment(),
    )
    snapshot = ConsensusSnapshot(
        provider="test-provider",
        release_event_id=event.record_id,
        statistic="median",
        snapshot_known_at=moment("2026-09-04T08:00:00-04:00"),
    )
    candidate = observation(
        release_event_id=event.record_id,
        vintage_id=vintage.record_id,
        evidence=(EvidenceBinding(field="value", reference=source[1]),),
    )
    reviewed = receipt(authority, source, candidate)
    blocked = BlockedInput(
        input_ids=(candidate.record_id,),
        reason_codes=("period_unverified",),
        missing_fields=("reference_month",),
    )
    for record in (event, vintage, snapshot, candidate, reviewed, blocked):
        restored = load_record(record.to_json())
        assert restored == record
        assert restored.record_id == record.record_id
        assert restored.to_json() == record.to_json()


@pytest.mark.parametrize(
    "value",
    [
        "2026-09-04",
        "2026-09-04T08:30:00",
        "2026-02-30T08:30:00Z",
        "2026-09-04T08:30:00+24:00",
        "",
        1788539400,
    ],
)
def test_time_rejects_date_only_naive_invalid_or_numeric(value):
    with pytest.raises((ValidationError, ValueError)):
        SourceTime(raw=value)


def test_time_preserves_offset_but_compares_in_utc():
    local = moment()
    utc = moment("2026-09-04T12:30:00Z")
    assert local.utc == utc.utc
    assert local.raw.endswith("-04:00")
    assert SourceTime.model_validate_json(local.model_dump_json()).raw == local.raw


def test_unknown_dates_not_filled_from_ingestion():
    candidate = observation(reference_month=None, ingested_at=moment())
    assert candidate.known_at is None and candidate.reference_month is None
    assert ReleaseEvent(publisher="BLS", release_key="unknown").release_at is None
    assert ConsensusSnapshot().snapshot_known_at is None
    for bad in ("8月", "2026-13", "2026-00", "2026-08-01", "0000-08"):
        with pytest.raises(ValidationError):
            observation(reference_month=bad)


def test_unknown_fields_and_self_approval_rejected_everywhere():
    with pytest.raises(ValidationError):
        observation(verified=True)
    with pytest.raises(ValidationError):
        observation(verification_ref="self-approved")
    with pytest.raises(ValidationError):
        observation(amount={"value_raw": "16.2", "unit_raw": "万", "verified": True})


def test_immutable_nested_values_and_validated_copy():
    candidate = observation(qualifiers=(Qualifier(name="basis", value="source"),))
    with pytest.raises(ValidationError):
        candidate.kind = "forecast"
    with pytest.raises(ValidationError):
        candidate.amount.value_raw = "999"
    with pytest.raises(ValidationError):
        candidate.qualifiers[0].value = "adjusted"
    with pytest.raises(ValidationError):
        candidate.model_copy(update={"kind": "forecast"})
    with pytest.raises(ValidationError):
        candidate.model_copy(update={"verified": True})


def test_identity_includes_roles_qualifiers_vintages_and_snapshots():
    base = observation()
    candidates = [
        base,
        base.model_copy(update={"role": "consensus", "kind": "forecast"}),
        base.model_copy(update={"vintage_id": "a" * 64}),
        base.model_copy(update={"vintage_id": "b" * 64}),
        base.model_copy(update={"qualifiers": (Qualifier(name="scope", value="adjusted"),)}),
        base.model_copy(update={"known_at": moment()}),
    ]
    assert len(index_unique(candidates)) == len(candidates)
    first = ConsensusSnapshot(provider="A", statistic="median")
    second = first.model_copy(update={"provider": "B"})
    assert first.record_id != second.record_id
    with pytest.raises(ValueError, match="duplicate_identity"):
        index_unique([base, load_record(base.to_json())])


def test_content_tampering_and_envelope_extras_rejected():
    data = json.loads(observation().to_json())
    data["payload"]["amount"]["value_raw"] = "999"
    with pytest.raises(ValidationError, match="source_hash_mismatch"):
        load_record(json.dumps(data))
    data = json.loads(observation().to_json())
    data["verified"] = True
    with pytest.raises(ValidationError):
        load_record(json.dumps(data))


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "forecast"},
        {"consensus_snapshot_id": "a" * 64},
        {"role": "consensus", "kind": "forecast", "vintage_id": "a" * 64},
    ],
)
def test_roles_cannot_be_relabelled(changes):
    with pytest.raises(ValidationError, match="role_mismatch"):
        observation(**changes)


@pytest.mark.parametrize(
    "raw,unit,expected",
    [
        ("162", "thousand_jobs", "162000"),
        ("-20", "thousand_jobs", "-20000"),
        ("0", "jobs", "0"),
        ("162,000", "jobs", "162000"),
        (
            "123456789012345678901234567890.1234",
            "thousand_jobs",
            "123456789012345678901234567890123.4",
        ),
    ],
)
def test_normalization_exact_signed_zero_and_raw_preserved(raw, unit, expected):
    candidate = observation(amount=RawAmount(value_raw=raw, unit_raw=unit))
    result = normalize_jobs(candidate)
    assert result.value_jobs == Decimal(expected)
    assert result.raw == candidate.amount and result.raw.unit_raw == unit
    assert result.status == "normalized" and result.calculation_permitted is False


@pytest.mark.parametrize("raw", [None, "", "—", "NaN", "Infinity", "1e10", "12,34", "16.2万"])
def test_missing_or_malformed_numbers_do_not_become_zero(raw):
    result = normalize_jobs(observation(amount=RawAmount(value_raw=raw, unit_raw="jobs")))
    assert result.value_jobs is None and result.status == "blocked"
    assert result.reason_codes == ("value_unverified",)


def test_chinese_units_require_real_application_receipt(source, authority):
    candidate = observation()
    assert normalize_jobs(candidate).status == "blocked"
    reviewed = receipt(authority, source, candidate)
    result = normalize_jobs(candidate, authority=authority, verification_ref=reviewed.record_id)
    assert result.value_jobs == Decimal("162000") and result.raw.unit_raw == "万"
    changed = candidate.model_copy(update={"amount": RawAmount(value_raw="5.6", unit_raw="万人")})
    assert (
        normalize_jobs(changed, authority=authority, verification_ref=reviewed.record_id).status
        == "blocked"
    )


def test_serialized_valid_receipt_is_not_a_trust_source(source, authority):
    candidate = observation()
    reviewed = receipt(authority, source, candidate)
    copied = load_record(reviewed.to_json())
    fresh = VerificationAuthority(
        issuer_id="reviewer:test",
        issuer_role="human_reviewer",
        policy_version="mapping-test-1",
        resolve=lambda ref: resolve_reference(ref, source[0]),
    )
    assert isinstance(copied, VerificationRecord)
    assert not fresh.accepts(copied.record_id, candidate, ("unit_mapping",))
    fake = reviewed.model_copy(update={"issuer_id": "llm-admin"})
    assert not authority.accepts(fake.record_id, candidate, ("unit_mapping",))


def test_rejected_insufficient_and_duplicate_reviews_do_not_grant_mapping(source, authority):
    candidate = observation()
    rejected = receipt(
        authority, source, candidate, decision="rejected", reason_codes=("unit_unverified",)
    )
    assert (
        normalize_jobs(candidate, authority=authority, verification_ref=rejected.record_id).status
        == "blocked"
    )
    partial = receipt(authority, source, candidate, scopes=("indicator",))
    assert (
        normalize_jobs(candidate, authority=authority, verification_ref=partial.record_id).status
        == "blocked"
    )
    with pytest.raises(ValueError, match="duplicate_identity"):
        receipt(authority, source, candidate, scopes=("indicator",))


def test_receipts_require_resolvable_evidence(source):
    broken = VerificationAuthority(
        issuer_id="reviewer:test",
        issuer_role="human_reviewer",
        policy_version="test",
        resolve=lambda ref: "not the source quote",
    )
    with pytest.raises(ValueError, match="atomic_evidence_mismatch"):
        receipt(broken, source, observation())


@pytest.mark.parametrize(
    "change",
    [
        {"indicator": "US.NFP_LEVEL_YOY", "transform": "yoy_rate"},
        {"indicator": "US.NFP_REVISION_SUM", "transform": "revision_sum"},
        {"population": "persons"},
        {"adjustment": "NSA"},
        {"country": None},
    ],
)
def test_other_series_or_unknown_dimensions_never_normalize_as_nfp_jobs(change):
    candidate = observation()
    candidate = candidate.model_copy(
        update={"dimensions": candidate.dimensions.model_copy(update=change)}
    )
    assert normalize_jobs(candidate).reason_codes == ("indicator_mismatch",)


def test_percent_not_a_jobs_unit_even_with_a_receipt(source, authority):
    candidate = observation(amount=RawAmount(value_raw="0.38", unit_raw="%"))
    reviewed = receipt(authority, source, candidate)
    assert normalize_jobs(
        candidate, authority=authority, verification_ref=reviewed.record_id
    ).reason_codes == ("unit_unverified",)


def test_blocked_result_cannot_hide_a_value_or_missing_reason():
    with pytest.raises(ValidationError):
        BlockedInput(input_ids=(), reason_codes=("period_unverified",), value=0)
    with pytest.raises(ValidationError):
        BlockedInput(input_ids=(), reason_codes=())


def test_old_run_reference_roundtrip_without_migration(source):
    run, _ = source
    old = run.model_copy(update={"pipeline_version": "evidence-pipeline-6"})
    payload = old.model_dump(mode="json")
    payload.pop("run_id")
    old = old.model_copy(update={"run_id": fingerprint(payload)})
    before = old.model_dump_json()
    ref = reference_from_run(old, old.document.packets[0].packet_id, old.document.packets[0].text)
    assert resolve_reference(ref, EvidenceRun.model_validate_json(before)) == ref.quote
    assert old.model_dump_json() == before
    with pytest.raises(ValueError, match="source_hash_mismatch"):
        resolve_reference(ref.model_copy(update={"source_rev": "0" * 16}), old)


def test_duplicate_json_keys_are_not_last_writer_wins():
    serialized = observation().to_json()
    with pytest.raises(ValueError, match="duplicate JSON field"):
        load_record(
            serialized.replace('"value_raw": "16.2"', '"value_raw": "999", "value_raw": "16.2"')
        )


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_normalized_values_must_be_finite(value):
    with pytest.raises(ValidationError):
        UnitNormalization(
            status="normalized", observation_id="test", raw=RawAmount(), value_jobs=value
        )


def test_normalization_status_cannot_contradict_value_or_reasons():
    with pytest.raises(ValidationError):
        UnitNormalization(
            status="blocked",
            observation_id="test",
            raw=RawAmount(),
            value_jobs=0,
            reason_codes=("unit_unverified",),
        )
    with pytest.raises(ValidationError):
        UnitNormalization(
            status="normalized", observation_id="test", raw=RawAmount(), value_jobs=None
        )


def test_reviewer_cannot_claim_approved_with_a_blocking_reason(source, authority):
    with pytest.raises(ValidationError):
        receipt(authority, source, observation(), reason_codes=("unit_unverified",))
    with pytest.raises(ValidationError):
        receipt(authority, source, observation(), decision="unknown")
