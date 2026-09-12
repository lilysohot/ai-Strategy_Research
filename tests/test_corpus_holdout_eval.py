"""Test evaluation instrumentation, not a claim that business gates pass."""

import json

import pytest

from plugins.corpus.evidence import EvidenceDocument, EvidencePacket
from plugins.corpus.evidence_pipeline import extract_evidence
from scripts.corpus_holdout_eval import negative_checks, score_prose, synthetic_probes

TARGET = {
    "number": "16.2",
    "quote_terms": ["非农", "16.2"],
    "metrics": ["NFP"],
    "subject": "US",
    "units": ["万人"],
    "state": "actual",
    "basis": None,
    "period_end": None,
}


def macro_run(payload):
    source = "美国8月新增非农就业16.2万，高于预期5.6万。"
    packet = EvidencePacket(packet_id="p", locator="1", kind="prose", text=source)
    document = EvidenceDocument(
        doc_id="test",
        title="宏观周报",
        source_path="test",
        source_rev="test",
        parse_rev="test",
        parser_version="test",
        subject=None,
        published="2026-09-06",
        pages=(),
        packets=(packet,),
    )
    return extract_evidence(
        document, llm=lambda _: json.dumps(payload, ensure_ascii=False), max_prose_calls=1
    )


def test_missed_target_is_not_a_pass_even_when_negative_checks_are_vacuous():
    run = macro_run([])
    check = score_prose(run, TARGET)
    assert not check["retrieved"] and not check["coordinate_pass"]
    negative = negative_checks(run, ["no_calculate"])[0]
    assert negative["passed"] and negative["vacuous"]


def test_negative_rule_names_fail_closed():
    with pytest.raises(ValueError, match="Unknown negative"):
        negative_checks(macro_run([]), ["typo"])


def test_adversarial_probe_inventory_and_positive_control():
    probes = synthetic_probes()
    assert len(probes) == 6
    assert probes[0]["name"] == "valid_control" and probes[0]["passed"]
    assert len({p["name"] for p in probes}) == 6
    # Do not encode current vulnerabilities as permanently desired behavior.
    for probe in probes[1:]:
        assert probe["expected_calculate"] is False
        assert probe["passed"] == (not probe["actual_calculate"])


def test_wrong_state_does_not_count_as_complete_coordinate():
    run = macro_run(
        [
            {
                "claim_text": "美国8月新增非农就业16.2万",
                "scope": "macro",
                "subject": "US",
                "metric": "NFP",
                "value_text": "16.2万人",
                "unit_raw": "万人",
                "evidence_quote": "美国8月新增非农就业16.2万",
                "period_raw": "8月",
                "qualifiers": {"state": "consensus"},
                "kind": "fact",
            }
        ]
    )
    check = score_prose(run, TARGET)
    assert check["retrieved"]
    assert not check["coordinate_pass"]


def test_negative_scope_includes_short_quotes_with_nfp_in_claim_text():
    run = macro_run(
        [
            {
                "claim_text": "美国8月非农就业市场预期5.6万",
                "scope": "macro",
                "subject": "US",
                "metric": "新增非农就业预期",
                "value_text": "5.6万",
                "unit_raw": "万",
                "evidence_quote": "高于预期5.6万",
                "period_raw": "8月",
                "qualifiers": {"state": "consensus"},
                "kind": "forecast",
            }
        ]
    )
    check = negative_checks(run, ["no_inferred_year"])[0]
    assert check["observed_nfp_facts"] == 1
    assert not check["vacuous"]
