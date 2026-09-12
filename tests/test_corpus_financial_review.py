"""Financial review keeps source ratios separate from explicitly defined arithmetic."""

import json
import sys
from dataclasses import replace
from decimal import Decimal

import pytest

from plugins.corpus.derivation import reconcile_net_margin
from plugins.corpus.evidence import EvidenceDocument, EvidencePacket, Span, fingerprint
from plugins.corpus.evidence_pipeline import extract_evidence, project_claims
from plugins.corpus.service import CorpusService, _main


def report_run(*, source_margin="50.2", revenue="178657", duplicates=False):
    import json

    values = [
        ("营业总收入", revenue, "元"),
        ("净利润", "87841", "元"),
        ("归母净利润", "84679", "元"),
        ("少数股东损益", "3162", "元"),
        ("净利率", source_margin, "%"),
    ]
    payload = []
    text = "。".join(f"2026E {metric}{value}{unit}" for metric, value, unit in values)
    for metric, value, unit in values:
        payload.append(
            {
                "claim_text": f"2026E {metric}{value}{unit}",
                "evidence_quote": f"2026E {metric}{value}{unit}",
                "scope": "company",
                "subject": "600519.SH",
                "metric": metric,
                "value_text": value,
                "unit_raw": unit,
                "period_raw": "2026E",
                "kind": "forecast",
            }
        )
    if duplicates:
        payload.append(payload[1])
    packet = EvidencePacket(packet_id="p", locator="3", kind="prose", text=text)
    doc = EvidenceDocument(
        doc_id="d",
        title="600519.SH 财务预测",
        source_path="synthetic",
        source_rev="s",
        parse_rev="r",
        parser_version="test",
        subject="600519.SH",
        published="2026-08-16",
        pages=(Span(locator="3", text=text),),
        packets=(packet,),
    )
    return extract_evidence(doc, llm=lambda _: json.dumps(payload), max_prose_calls=1)


def test_review_preserves_source_and_marks_unresolved_definition():
    run = report_run()
    before = run.model_dump_json()
    review = reconcile_net_margin(run)[0]
    assert review["source_value"] == "50.2"
    assert Decimal(review["derived_value"]) == Decimal("87841") / Decimal("178657") * 100
    assert review["status"] == "review_definition_or_source"
    assert review["definition_verified"] is False
    assert review["source_usable_for"] == ["cite"]
    assert len(review["input_fact_ids"]) == 2
    assert review["profit_residual"] == "0"
    assert run.model_dump_json() == before
    assert project_claims(run, purpose="calculate")["total"] == 4
    margin = next(f for f in run.facts if f.metric_id == "net_margin")
    assert margin.usable_for == ("cite",)


def test_matching_number_does_not_prove_the_author_formula():
    review = reconcile_net_margin(report_run(source_margin="49.2"))[0]
    assert review["status"] == "consistent_with_candidate_definition"
    assert review["definition_verified"] is False
    assert review["source_usable_for"] == ["cite"]


def test_source_display_precision_controls_rounding_tolerance():
    loose = reconcile_net_margin(report_run(source_margin="49.2"))[0]
    tight = reconcile_net_margin(report_run(source_margin="49.20"))[0]
    assert loose["status"] == "consistent_with_candidate_definition"
    assert tight["status"] == "review_definition_or_source"
    assert loose["tolerance_percentage_points"] == "0.05"
    assert tight["tolerance_percentage_points"] == "0.005"


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"revenue": "0"}, "zero_denominator"),
        ({"duplicates": True}, "duplicate_fact_ids"),
    ],
)
def test_review_does_not_guess_invalid_inputs(kwargs, reason):
    reviews = reconcile_net_margin(report_run(**kwargs))
    assert reviews[0]["status"] == "unverifiable"
    assert reviews[0]["reason"] == reason


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"period_end": "2025-12-31"}, "missing_or_ambiguous:net_profit"),
        ({"kind": "fact"}, "missing_or_ambiguous:net_profit"),
        ({"qualifiers": {"statement": "parent_only"}}, "missing_or_ambiguous:net_profit"),
        ({"unit": "美元"}, "unit_mismatch"),
    ],
)
def test_review_rejects_mismatched_financial_coordinates(changes, reason):
    run = report_run()
    facts = tuple(
        f.model_copy(update={"claim": replace(f.claim, **changes)})
        if f.metric_id == "net_profit"
        else f
        for f in run.facts
    )
    modified = run.model_copy(update={"facts": facts})
    payload = modified.model_dump(mode="json")
    payload.pop("run_id")
    modified = modified.model_copy(update={"run_id": fingerprint(payload)})
    review = reconcile_net_margin(modified)[0]
    assert review["status"] == "unverifiable" and review["reason"] == reason


def test_financial_review_service_and_cli_do_not_write(monkeypatch, capsys):
    run = report_run()
    service = CorpusService("postgresql://unused")
    monkeypatch.setattr(service, "load_evidence_run", lambda run_id: run)
    monkeypatch.setattr("plugins.corpus.service.get_service", lambda _: service)
    monkeypatch.setattr(sys, "argv", ["corpus", "reconcile-claims", "--run-id", run.run_id])
    assert _main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result == service.reconcile_claims(run_id=run.run_id)
    assert result[0]["status"] == "review_definition_or_source"
