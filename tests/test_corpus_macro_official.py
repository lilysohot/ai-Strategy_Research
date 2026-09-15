"""M2 synthetic layout fixtures, NOT a real-event holdout or a downloaded BLS archive."""

import dataclasses
import hashlib
from datetime import date
from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError

from plugins.corpus.evidence_pipeline import EvidenceRun, validation_is_current
from plugins.corpus.macro_models import SourceTime, load_record, resolve_reference
from plugins.corpus.macro_official import (
    MAX_ARCHIVE_BYTES,
    BlsReleaseAdapter,
    CapturedArchive,
    OfficialReleaseRequest,
)
from plugins.corpus.macro_verification import normalize_jobs

URI = "https://www.bls.gov/news.release/archives/empsit_06062025.htm"
POLICY = "The establishment survey revises its initial monthly estimates twice, in the immediately succeeding 2 months."


def html(*, winter=False, benchmark=False):
    title = "JANUARY 2025" if winter else "MAY 2025"
    stamp = "Friday, February 7, 2025" if winter else "Friday, June 6, 2025"
    headers = (
        ["Jan. 2024", "Nov. 2024", "Dec. 2024(p)", "Jan. 2025(p)"]
        if winter
        else [
            "May 2024",
            "Mar. 2025",
            "Apr. 2025(p)",
            "May 2025(p)",
        ]
    )
    annual = (
        """<pre>
In accordance with annual practice, the establishment survey data released today have been
benchmarked to reflect comprehensive counts of payroll jobs for March 2024.
Table A. Revisions to total nonfarm employment, January to December 2024, seasonally adjusted
(Numbers in thousands)
                     |                Level              |      Over-the-month change
     Year and month  |           |    As     |           |           |    As    |
                     |    As     |previously | Difference|    As     |previously| Difference
                     |  revised  |published  |           |  revised  |published |
           2024      |           |           |           |           |          |
November........ |  158,619  |  159,280  |    -661   |    261    |    212   |    49
December(p)..... |  158,926  |  159,536  |    -610   |    307    |    256   |    51
</pre>"""
        if benchmark
        else ""
    )
    return f"""<!doctype html><html><body>
<pre>Transmission of material in this news release is embargoed until USDL-25-0000
8:30 a.m. (ET) {stamp}
THE EMPLOYMENT SITUATION -- {title}
Synthetic layout fixture. Values here are test inputs, not independently verified observations.
</pre>{annual}
<table><caption>Summary table B. Establishment data, seasonally adjusted</caption>
<thead><tr><th>Category</th>{"".join("<th>" + h + "</th>" for h in headers)}</tr></thead>
<tbody><tr><th colspan="5">EMPLOYMENT BY SELECTED INDUSTRY<br/>(Over-the-month change, in thousands)</th></tr>
<tr><th>Total nonfarm</th><td>193</td><td>120</td><td>147</td><td>139</td></tr>
<tr><th>Total private</th><td>160</td><td>114</td><td>146</td><td>140</td></tr>
<tr><th colspan="5">(3-month average change, in thousands)</th></tr>
<tr><th>Total nonfarm</th><td>186</td><td>111</td><td>123</td><td>135</td></tr>
</tbody><tfoot><tr><td colspan="5">(p) Preliminary</td></tr></tfoot></table>
<pre>{POLICY}</pre></body></html>"""


def inputs(raw=None, *, month="2025-05", kind="first", winter=False):
    body = (html(winter=winter) if raw is None else raw).encode()
    uri = URI.replace("06062025", "02072025") if winter else URI
    archive = CapturedArchive(
        uri, 200, "text/html; charset=utf-8", body, SourceTime(raw="2026-09-13T10:00:00+08:00")
    )
    request = OfficialReleaseRequest(
        archive_uri=uri,
        expected_sha256=archive.sha256,
        release_date=date(2025, 2, 7) if winter else date(2025, 6, 6),
        reference_month=month,
        vintage_kind=kind,
    )
    return request, archive


@pytest.mark.parametrize(
    ("month", "kind", "value"),
    [
        ("2025-05", "first", "139"),
        ("2025-04", "second", "147"),
        ("2025-03", "third", "120"),
    ],
)
def test_monthly_versions_raw_evidence_trust_and_replay(month, kind, value):
    request, archive = inputs(month=month, kind=kind)
    adapter = BlsReleaseAdapter()
    result = adapter.replay(request, archive)
    assert result.blocked is None
    assert result.observation.amount.value_raw == value
    assert result.observation.amount.unit_raw == "in thousands"
    assert result.vintage.vintage_kind == kind
    assert result.event.reference_month == "2025-05"
    assert result.observation.reference_month == month
    assert result.observation.known_at.raw == "2025-06-06T08:30:00-04:00"
    assert result.observation.ingested_at == archive.retrieved_at
    assert result.run.document.source_rev == hashlib.sha256(archive.body).hexdigest()
    assert not validation_is_current(result.run)
    assert not result.run.facts  # No generic financial computation permission.
    assert result.calculation_permitted is False
    restored_run = EvidenceRun.model_validate_json(result.run.model_dump_json())
    restored_run.verify_identity()
    for binding in result.observation.evidence:
        assert resolve_reference(binding.reference, restored_run) == binding.reference.quote
        assert (
            archive.body.decode()[binding.reference.start : binding.reference.end]
            == binding.reference.quote
        )
    receipt = result.verifications[-1]
    assert adapter.authority.accepts(receipt.record_id, result.observation, ("value", "vintage"))
    assert normalize_jobs(result.observation).status == "blocked"
    scaled = normalize_jobs(
        result.observation, authority=adapter.authority, verification_ref=receipt.record_id
    )
    assert scaled.value_jobs == Decimal(value) * 1000
    assert scaled.calculation_permitted is False
    assert load_record(result.observation.to_json()) == result.observation
    assert adapter.replay(request, archive) is result
    fresh = BlsReleaseAdapter()
    assert not fresh.authority.accepts(receipt.record_id, result.observation, ("value",))
    assert fresh.replay(request, archive).observation == result.observation


def test_one_release_keeps_all_vintages_without_changing_event_or_prior_result():
    adapter = BlsReleaseAdapter()
    first = adapter.replay(*inputs())
    original = first.observation.to_json()
    second = adapter.replay(*inputs(month="2025-04", kind="second"))
    third = adapter.replay(*inputs(month="2025-03", kind="third"))
    assert first.event == second.event == third.event
    assert len({r.vintage.record_id for r in (first, second, third)}) == 3
    assert first.observation.to_json() == original


def test_winter_and_year_rollover():
    result = BlsReleaseAdapter().replay(*inputs(month="2024-12", kind="second", winter=True))
    assert result.blocked is None
    assert result.observation.known_at.raw == "2025-02-07T08:30:00-05:00"


@pytest.mark.parametrize(("month", "value"), [("2024-11", "261"), ("2024-12", "307")])
def test_annual_benchmark_is_revised_change_not_level_or_revision_delta(month, value):
    request, archive = inputs(
        html(winter=True, benchmark=True), month=month, kind="benchmark", winter=True
    )
    adapter = BlsReleaseAdapter()
    result = adapter.replay(request, archive)
    assert result.blocked is None
    assert result.vintage.vintage_kind == "benchmark"
    assert result.observation.amount.value_raw == value
    assert result.observation.amount.unit_raw == "Numbers in thousands"
    assert (
        normalize_jobs(
            result.observation,
            authority=adapter.authority,
            verification_ref=result.verifications[-1].record_id,
        ).value_jobs
        == Decimal(value) * 1000
    )
    wrong = adapter.replay(request.model_copy(update={"vintage_kind": "second"}), archive)
    assert wrong.blocked.reason_codes == ("vintage_mismatch",)


def test_benchmark_release_current_month_still_first():
    result = BlsReleaseAdapter().replay(
        *inputs(html(winter=True, benchmark=True), month="2025-01", winter=True)
    )
    assert result.blocked is None
    assert result.vintage.vintage_kind == "first"


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        ("(ET)", "", "time_provenance_unverified"),
        ("(ET)", "(EST)", "time_provenance_unverified"),
        ("8:30 a.m.", "June 6", "time_provenance_unverified"),
        ("Friday, June 6", "Thursday, June 6", "time_provenance_unverified"),
        ("June 6, 2025", "June 5, 2025", "time_provenance_unverified"),
        ("MAY 2025", "MAY", "period_unverified"),
        ("MAY 2025", "APRIL 2025", "vintage_mismatch"),
        ("seasonally adjusted", "not seasonally adjusted", "atomic_evidence_mismatch"),
        ("May 2025(p)", "May 2025", "vintage_mismatch"),
        ("May 2025(p)", "May (p)", "period_unverified"),
        ("Apr. 2025(p)", "Mar. 2025(p)", "period_unverified"),
        ("Over-the-month change", "Over-the-year change", "atomic_evidence_mismatch"),
        ("<td>139</td>", "<td></td>", "value_unverified"),
        ("<td>139</td>", "<td>13,9</td>", "value_unverified"),
        ("<td>139</td>", "<td>139%</td>", "value_unverified"),
        (POLICY, "Revisions may occur.", "atomic_evidence_mismatch"),
        ("</table>", "", "atomic_evidence_mismatch"),
        ("<td>139</td>", '<td colspan="2">139</td>', "atomic_evidence_mismatch"),
        ("<th>May 2025(p)</th>", '<th rowspan="2">May 2025(p)</th>', "atomic_evidence_mismatch"),
        ("(p) Preliminary", "p = revised", "vintage_mismatch"),
    ],
)
def test_missing_conflicting_or_ambiguous_source_is_blocked(old, new, reason):
    request, archive = inputs(html().replace(old, new))
    result = BlsReleaseAdapter().replay(request, archive)
    assert result.blocked.reason_codes == (reason,)
    assert result.blocked.value is None
    assert result.observation is None
    assert not result.verifications
    assert result.archive == archive


@pytest.mark.parametrize("value", ["-20", "0", "+139", "1,234"])
def test_signed_zero_and_comma_values(value):
    result = BlsReleaseAdapter().replay(
        *inputs(html().replace("<td>139</td>", f"<td>{value}</td>"))
    )
    assert result.blocked is None
    assert result.observation.amount.value_raw == value


@pytest.mark.parametrize(
    ("month", "kind"),
    [
        ("2025-05", "second"),
        ("2025-04", "first"),
        ("2024-05", "third"),
        ("2025-06", "first"),
        ("2025-05", "benchmark"),
    ],
)
def test_never_relabel_a_requested_vintage(month, kind):
    result = BlsReleaseAdapter().replay(*inputs(month=month, kind=kind))
    assert result.blocked is not None
    assert result.observation is None


@pytest.mark.parametrize(
    "uri",
    [
        "https://www.bls.gov/news.release/empsit.htm",
        URI + "?latest=1",
        URI + "#x",
        URI.replace("https:", "http:"),
        URI.replace("www.bls.gov", "evil.test"),
        URI.replace("www.bls.gov", "www.bls.gov.evil.test"),
        URI.replace("06062025", "07032025"),
    ],
)
def test_noncanonical_or_wrong_event_url_rejected_before_transport(uri):
    request, _ = inputs()
    with pytest.raises(ValidationError):
        request.model_copy(update={"archive_uri": uri})


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"body": b"changed"}, "source_hash_mismatch"),
        ({"status_code": 403}, "source_conflict"),
        ({"uri": URI + "?redirected=1"}, "source_conflict"),
        ({"content_type": "application/json"}, "source_conflict"),
        (
            {"retrieved_at": SourceTime(raw="2025-06-06T08:29:59-04:00")},
            "time_provenance_unverified",
        ),
    ],
)
def test_capture_changes_fail_closed(changes, reason):
    request, archive = inputs()
    result = BlsReleaseAdapter().replay(request, dataclasses.replace(archive, **changes))
    assert result.blocked.reason_codes == (reason,)


def test_explicit_archive_save_is_content_addressed_and_never_overwrites(tmp_path):
    _, archive = inputs()
    blob, receipt = archive.save(tmp_path)
    assert blob.read_bytes() == archive.body
    original = blob.stat().st_mtime_ns
    assert archive.save(tmp_path) == (blob, receipt)
    assert blob.stat().st_mtime_ns == original
    changed = dataclasses.replace(archive, body=b"new content")
    assert changed.save(tmp_path)[0] != blob
    assert blob.read_bytes() == archive.body
    blob.write_bytes(b"corrupted existing blob")
    with pytest.raises(ValueError, match="source_hash_mismatch"):
        archive.save(tmp_path)
    assert blob.read_bytes() == b"corrupted existing blob"


def test_no_repinning_changed_source_into_same_historical_event():
    request, archive = inputs()
    adapter = BlsReleaseAdapter()
    first = adapter.replay(request, archive)
    changed = dataclasses.replace(
        archive, body=archive.body.replace(b"<td>139</td>", b"<td>140</td>")
    )
    updated_pin = request.model_copy(update={"expected_sha256": changed.sha256})
    rejected = adapter.replay(updated_pin, changed)
    assert rejected.blocked.reason_codes == ("source_hash_mismatch",)
    assert rejected.blocked.missing_fields == ("previous_archive_pin",)
    assert adapter.replay(request, archive) is first
    assert first.observation.amount.value_raw == "139"


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        (
            "|  revised  |published  |           |  revised  |published |",
            "|  published  |revised  |           |  published  |revised |",
            "atomic_evidence_mismatch",
        ),
        ("           2024      |", "           2023      |", "period_unverified"),
        ("Over-the-month change\n", "Over-the-year change\n", "indicator_mismatch"),
    ],
)
def test_benchmark_headers_cannot_be_swapped_or_year_guessed(old, new, reason):
    raw = html(winter=True, benchmark=True)
    assert old in raw
    result = BlsReleaseAdapter().replay(
        *inputs(raw.replace(old, new), month="2024-12", kind="benchmark", winter=True)
    )
    assert result.blocked.reason_codes == (reason,)


def test_duplicate_rows_tables_and_deep_html_are_not_accepted():
    raw = html()
    row = "<tr><th>Total nonfarm</th><td>193</td><td>120</td><td>147</td><td>139</td></tr>"
    table = raw[raw.index("<table>") : raw.index("</table>") + len("</table>")]
    for altered in (
        raw.replace(row, row + row),
        raw.replace(table, table + table),
        raw.replace("<body>", "<body>" + "<div>" * 100),
    ):
        result = BlsReleaseAdapter().replay(*inputs(altered))
        assert result.blocked.reason_codes == ("atomic_evidence_mismatch",)


@pytest.mark.parametrize("status", [200, 302, 403, 500])
def test_bounded_transport_no_redirect_no_retry_and_raw_response_retained(status):
    request, archive = inputs()
    calls = []

    def transport(req):
        calls.append(req)
        return httpx.Response(
            status,
            content=archive.body,
            headers={"content-type": "text/html", "location": "https://evil.test"},
        )

    with httpx.Client(transport=httpx.MockTransport(transport), follow_redirects=True) as client:
        result = BlsReleaseAdapter(client).fetch(request)
    assert len(calls) == 1
    assert str(calls[0].url) == URI
    assert result.archive.body == archive.body
    assert (result.blocked is None) == (status == 200)


def test_transport_size_limit_and_timeout():
    request, _ = inputs()
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                content=b"a" * (MAX_ARCHIVE_BYTES + 1),
                headers={"content-type": "text/html"},
            )
        )
    ) as client:
        assert BlsReleaseAdapter(client).fetch(request).blocked.missing_fields == (
            "archive_size_limit",
        )

    def timeout(req):
        raise httpx.ReadTimeout("not persisted: secret provider details", request=req)

    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        result = BlsReleaseAdapter(client).fetch(request)
    assert result.blocked.missing_fields == ("archive_transport",)
    assert "secret" not in result.blocked.to_json()
