"""Independent I3-0 review: synthetic inputs only; no PG/model/source access.

Assertions encode expected contracts, not the current buggy behavior.
"""
from dataclasses import replace
from fractions import Fraction

import pytest

from plugins.corpus.scoring import (
    EvidenceTarget, FetchedEvidence, GoldQuestion, ObservationOutcome,
    QueryObservation, RetrievedDocument, ScoringInputError, SatisfyRule,
    gold_from_records, score,
)


def fixture():
    question = GoldQuestion(
        query_id="q", domain="company", critical=True,
        relevant_sources=("A",),
        evidence_targets=(EvidenceTarget("e", "营收 42", ("page:3",)),),
    )
    evidence = FetchedEvidence("营收 42", ("page:3",), verified=True)
    observation = QueryObservation("q", documents=(RetrievedDocument("A", (evidence,)),))
    return question, observation


def test_positive_control():
    q, o = fixture()
    assert score((q,), (o,)).passed


def test_duplicate_source_cannot_replace_missing_required_document():
    q, o = fixture()
    q = replace(q, relevant_sources=("A", "B"), satisfy_rule=SatisfyRule.ALL)
    o = replace(o, documents=(o.documents[0], o.documents[0]))
    try:
        report = score((q,), (o,))
    except ScoringInputError:
        return
    item = report.questions[0]
    assert (item.doc_recall, item.question_pass, report.passed) == (Fraction(1, 2), False, False)


def test_duplicate_sources_cannot_exceed_unit_recall():
    q, o = fixture()
    o = replace(o, documents=(o.documents[0], o.documents[0]))
    try:
        report = score((q,), (o,))
    except ScoringInputError:
        return
    assert report.questions[0].doc_recall <= 1


def test_unrelated_source_cannot_supply_required_evidence():
    q, o = fixture()
    evidence = o.documents[0].evidence
    o = replace(o, documents=(RetrievedDocument("A"), RetrievedDocument("unrelated", evidence)))
    report = score((q,), (o,))
    assert not report.questions[0].evidence_pass
    assert not report.passed


def test_no_match_with_stale_documents_cannot_pass():
    q, o = fixture()
    o = replace(o, outcome=ObservationOutcome.NO_MATCH)
    try:
        report = score((q,), (o,))
    except ScoringInputError:
        return
    assert not report.passed


def test_failed_observation_with_stale_payload_not_scored_success():
    q, o = fixture()
    o = replace(o, outcome=ObservationOutcome.FAILED)
    try:
        report = score((q,), (o,))
    except ScoringInputError:
        return
    item = report.questions[0]
    assert (item.doc_recall, item.question_pass, item.evidence_pass) == (0, False, False)


@pytest.mark.parametrize("rule", [None, "ALL"])
def test_missing_or_invalid_multidocument_rule_rejected(rule):
    record = dict(query_id="q", domain="company", answer_existence="answerable",
                  relevant_sources=["A", "B"], satisfy_rule=rule)
    with pytest.raises(ScoringInputError):
        gold_from_records([record])


def test_scalar_relevant_sources_not_split_into_characters():
    record = dict(query_id="q", domain="company", answer_existence="answerable",
                  relevant_sources="AB", satisfy_rule="all")
    with pytest.raises(ScoringInputError):
        gold_from_records([record])


def test_direct_empty_evidence_target_cannot_pass():
    q, o = fixture()
    try:
        q = replace(q, evidence_targets=(EvidenceTarget("e", ""),))
        o = replace(o, documents=(RetrievedDocument("A", (FetchedEvidence(""),)),))
        report = score((q,), (o,))
    except ScoringInputError:
        return
    assert not report.passed
