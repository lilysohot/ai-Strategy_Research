"""Diagnostic counterexamples, intentionally failing until the defects are fixed."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from plugins.corpus.claims import Claim
from plugins.corpus.claims_v2 import ClaimRecord, apply_lint, records_from_payload
from plugins.corpus.ingest import _strip_boilerplate
from plugins.corpus.service import _dedup_claims


def record():
    return ClaimRecord(
        doc_id="probe", source_rev="probe", seq=1, locator="1",
        claim_text="Company revenue is 100", evidence_quote="Company revenue is 100",
        scope="company", subject="600519.SH", metric="revenue",
        value_text="100", value_num=Decimal("100"),
    )


def test_financial_integer_lines_survive_cleaning():
    assert _strip_boilerplate("Revenue\n100\n120") == "Revenue\n100\n120"


def test_invented_table_evidence_is_not_accepted():
    candidate = replace(record(), evidence_kind="table", table_ref={"row": "invented"})
    assert apply_lint(candidate, block_text="Unrelated source").quality_status != "ok"


def test_numeric_substring_does_not_prove_value():
    candidate = replace(record(), evidence_quote="Company revenue is 120",
                        value_text="20", value_num=Decimal("20"))
    assert apply_lint(candidate, block_text="Company revenue is 120").quality_status != "ok"


def test_revenue_without_unit_or_period_is_not_calculation_ready():
    assert apply_lint(record(), block_text="Company revenue is 100").quality_status != "ok"


def test_normalized_unit_and_value_preserve_amount():
    candidate = records_from_payload(
        [{"claim_text": "Company revenue 2 亿元", "subject": "600519.SH",
          "metric": "revenue", "value_text": "2 亿元"}],
        doc_id="probe", source_rev="probe", seq=1, locator="1", doc_kind="company", model=None,
    )[0]
    assert (candidate.value_num, candidate.unit) == (Decimal("200000000"), "元")


def test_dedup_preserves_distinct_company_subjects():
    first = Claim(doc_id="probe", seq=1, locator="1", claim_text="A revenue 100",
                  tickers=("600519.SH",), metric="revenue", period="2026E")
    second = replace(first, tickers=("000001.SZ",), claim_text="B revenue 200")
    assert len(_dedup_claims([first, second])) == 2


if __name__ == "__main__":
    failures = 0
    for name, function in list(globals().items()):
        if name.startswith("test_") and callable(function):
            try:
                function()
            except AssertionError:
                failures += 1
                print(f"FAIL {name}")
            else:
                print(f"PASS {name}")
    print(f"{failures} violated quality contracts")
    raise SystemExit(1 if failures else 0)
