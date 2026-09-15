"""Regression gates for wrong calculation permissions, through the real pipeline."""

import json

import pytest

from plugins.corpus.derivation import derive
from plugins.corpus.evidence import EvidenceDocument, EvidencePacket, fingerprint
from plugins.corpus.evidence_pipeline import extract_evidence, project_claims
from scripts.corpus_holdout_eval import synthetic_probes


@pytest.mark.parametrize(
    "name",
    [
        "wrong_period",
        "wrong_metric_value",
        "fabricated_known_at",
        "forecast_as_fact",
        "duplicate_identity",
    ],
)
def test_invalid_candidates_never_enter_calculation(name):
    probe = next(item for item in synthetic_probes() if item["name"] == name)
    assert probe["passed"], probe


def test_valid_control_remains_calculable():
    assert synthetic_probes()[0]["passed"]


def candidate(source, **changes):
    payload = {
        "claim_text": "2026E营业收入100元",
        "evidence_quote": source,
        "scope": "company",
        "subject": "600519.SH",
        "metric": "营业收入",
        "value_text": "100元",
        "period_raw": "2026E",
        "kind": "forecast",
        **changes,
    }
    packet = EvidencePacket(packet_id="p", locator="1", kind="prose", text=source)
    document = EvidenceDocument(
        doc_id="test",
        title="财务预测",
        source_path="test",
        source_rev="test",
        parse_rev="test",
        parser_version="test",
        subject="600519.SH",
        published="2026-09-01",
        pages=(),
        packets=(packet,),
    )
    return extract_evidence(
        document, llm=lambda _: json.dumps([payload], ensure_ascii=False), max_prose_calls=1
    )


@pytest.mark.parametrize(
    "source,changes",
    [
        ("2026E营业收入120元；净利润100元。", {}),
        ("2026E归母净利润100元。", {"metric": "净利润"}),
        ("2025A营业收入100元；2026E营业收入120元。", {}),
        ("2026E营业收入-100元。", {}),
        ("2026E营业收入100万元。", {}),
        ("2026E营业收入100元；2026E营业收入100元。", {}),
        ("2026E营业收入100元。", {"known_at": "2026-08-31"}),
    ],
)
def test_independent_atomic_variants_fail_closed(source, changes):
    run = candidate(source, **changes)
    assert all("calculate" not in f.usable_for for f in run.facts)


def rehash(run):
    payload = run.model_dump(mode="json")
    payload.pop("run_id")
    return run.model_copy(update={"run_id": fingerprint(payload)})


def test_duplicate_identity_rejected_at_read_and_compute_interfaces():
    run = candidate("2026E营业收入100元。")
    run = rehash(run.model_copy(update={"facts": (*run.facts, *run.facts)}))
    assert project_claims(run, purpose="calculate")["total"] == 0
    with pytest.raises(ValueError, match="duplicate_fact_ids"):
        derive(run, "revenue_growth", (run.facts[0].fact_id,))


def test_identity_distinguishes_qualifiers_and_kind():
    run = candidate("2026E营业收入100元。")
    other = candidate("2026E营业收入100元。", kind="fact")
    basis = candidate("2026E营业收入100元。", qualifiers={"basis": "adjusted"})
    assert len({r.facts[0].fact_id for r in (run, other, basis)}) == 3


def test_model_time_override_is_retained_only_as_audit_data():
    run = candidate("2026E营业收入100元。", known_at="1990-01-01")
    fact = run.facts[0]
    assert fact.claim.known_at == "2026-09-01"
    assert fact.evidence_alignment["model_known_at"] == "1990-01-01"
    assert "known_at_unverified_override" in fact.reasons


def test_historical_calculation_rejected_without_rewriting_citations():
    run = candidate("2026E营业收入100元。")
    run = rehash(run.model_copy(update={"pipeline_version": "evidence-pipeline-6"}))
    assert project_claims(run, purpose="cite")["total"] == 1
    with pytest.raises(ValueError, match="validation_version_stale"):
        derive(run, "revenue_growth", ())
