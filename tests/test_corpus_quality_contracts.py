"""Financial invariants through the existing parser/normalizer interfaces."""

from dataclasses import replace
from decimal import Decimal

from plugins.corpus.claims import Claim
from plugins.corpus.claims_v2 import ClaimRecord, apply_lint, records_from_payload
from plugins.corpus.ingest import _strip_boilerplate
from plugins.corpus.service import _dedup_claims


def _record():
    return ClaimRecord(
        doc_id="probe",
        source_rev="probe",
        seq=1,
        locator="1",
        claim_text="Company revenue is 100",
        evidence_quote="Company revenue is 100",
        scope="company",
        subject="600519.SH",
        metric="revenue",
        value_text="100",
        value_num=Decimal("100"),
    )


def test_integer_zero_and_negative_values_survive_cleaning():
    text = "Revenue\n100\n0\n-120\n(325)"
    assert _strip_boilerplate(text) == text


def test_table_requires_verified_source_not_a_model_supplied_label():
    candidate = replace(_record(), evidence_kind="table", table_ref={"row": "invented"})
    assert apply_lint(candidate, block_text="Unrelated source").quality_status == "rejected"


def test_number_must_match_whole_token_and_sign():
    for source in ("Revenue 120", "Revenue -20", "Revenue 20.5"):
        candidate = replace(
            _record(), evidence_quote=source, value_text="20", value_num=Decimal("20")
        )
        assert apply_lint(candidate, block_text=source).quality_status == "rejected"


def test_numeric_fact_without_unit_and_period_is_review():
    verdict = apply_lint(_record(), block_text="Company revenue is 100")
    assert verdict.quality_status == "review"
    assert {"unit_missing", "period_missing"} <= set(verdict.reason_codes)


def test_money_value_and_unit_are_normalized_together():
    candidate = records_from_payload(
        [
            {
                "claim_text": "营收 2 亿元",
                "subject": "600519.SH",
                "metric": "营业收入",
                "value_text": "2 亿元",
            }
        ],
        doc_id="probe",
        source_rev="probe",
        seq=1,
        locator="1",
        doc_kind="company",
        model=None,
    )[0]
    assert (candidate.value_num, candidate.unit) == (Decimal("200000000"), "元")
    assert (candidate.value_text, candidate.unit_raw) == ("2 亿元", "亿元")


def test_dedup_does_not_merge_companies_or_conflicting_values():
    first = Claim(
        doc_id="probe",
        seq=1,
        locator="1",
        claim_text="A revenue 100",
        tickers=("600519.SH",),
        metric="revenue",
        period="2026E",
        value_text="100",
    )
    second = replace(first, tickers=("000001.SZ",), claim_text="B revenue 200", value_text="200")
    conflict = replace(first, claim_text="A revenue 101", value_text="101")
    assert len(_dedup_claims([first, second, conflict])) == 3


def test_stored_numeric_projection_cannot_disagree_with_raw_unit():
    record = replace(
        _record(),
        value_text="2亿元",
        value_num=Decimal("2"),
        unit_raw="亿元",
        unit="元",
        evidence_quote="营收2亿元",
    )
    result = apply_lint(record, block_text="营收2亿元")
    assert result.quality_status == "rejected"
    assert "normalized_value_mismatch" in result.reason_codes
