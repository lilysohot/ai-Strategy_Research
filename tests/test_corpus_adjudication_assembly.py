"""Contract v4.1 adjudication -> scorer input assembly (P01)."""

from __future__ import annotations

import inspect

import pytest

from plugins.corpus.adjudication_assembly import (
    ABSENT,
    ADJUDICATION_FIELDS,
    ROLE_REQUIRED_FIELDS,
    AdjudicatedMapping,
    Judgement,
    Stage,
    assemble_scoring_input,
    condition_role_needs_human_basis,
    matching_view,
)
from plugins.corpus.structured_scoring import RecordOrigin, Role, ScoringInputError

SOURCE_ID = "sha256:" + "a" * 64


def _candidate(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "candidate_id": "itm_1",
        "role": "material_items",
        "source_id": SOURCE_ID,
        "origin": "llm_prose",
        "text": "卖方讲的三条核心发现是 CSP/GPU 机柜量。",
        "semantic_type": "fact",
        "statement_role": "claim",
        "speech_role": "answer",
        "perspective": "source_explicit",
        "polarity": "affirmed",
        "speaker_ref": "spk_1",
        "attribution": "document_voice",
        "condition": "unconditional",
    }
    row.update(overrides)
    return row


def _adjudication(candidate: dict[str, object], **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "candidate_id": candidate["candidate_id"],
        "stage": "raw",
        "role": candidate["role"],
        "source_id": candidate["source_id"],
        "original_candidate": candidate,
        "judgement": "matched",
        "matched_gold_id": "NT-I09",
        "canonical_observed_fields": {
            "proposition": candidate["text"],
            "semantic_type": candidate["semantic_type"],
            "statement_role": candidate["statement_role"],
            "speech_role": candidate["speech_role"],
            "perspective": candidate["perspective"],
            "speaker_ref": candidate["speaker_ref"],
            "polarity": candidate["polarity"],
            "attribution": candidate["attribution"],
            "source_stance": ABSENT,
            "condition": ABSENT,
        },
        "reviewer": "xyl",
        "reason": "逐字比对通过",
        "evidence": {"quote": "CSP/GPU 机柜量", "locator": "char:1393-1655"},
    }
    row.update(overrides)
    return row


def _assemble(candidate: dict[str, object], adjudication: dict[str, object]):
    return assemble_scoring_input(
        [adjudication], catalog={str(candidate["candidate_id"]): candidate}
    )


def test_assembles_matched_candidate_into_raw_stage() -> None:
    candidate = _candidate()
    result = _assemble(candidate, _adjudication(candidate))

    assert len(result.raw) == 1
    assert result.validated == ()
    assert len(result.mappings) == 1
    mapping = result.mappings[0]
    assert isinstance(mapping, AdjudicatedMapping)
    assert mapping.gold_record_id == "NT-I09"
    assert mapping.judgement is Judgement.MATCHED

    record = result.raw[0]
    assert record.candidate_id == "itm_1"
    assert record.role is Role.MATERIAL_ITEMS
    assert record.origin is RecordOrigin.LLM_PROSE
    assert dict(record.semantic_fields)["proposition"] == candidate["text"]


def test_excluded_fields_never_enter_the_matching_basis() -> None:
    candidate = _candidate()
    result = _assemble(candidate, _adjudication(candidate))

    names = {name for name, _ in result.raw[0].semantic_fields}
    assert "speaker_ref" not in names
    assert "attribution" not in names
    audit = result.audit[0]
    assert audit.excluded_from_matching_basis == ("attribution", "speaker_ref")
    # ... but they are still recorded for review.
    assert audit.canonical_observed_fields["speaker_ref"] == "spk_1"


def test_caliber_normalization_touches_only_the_matching_view() -> None:
    candidate = _candidate(speech_role="answer", perspective="source_explicit")
    result = _assemble(candidate, _adjudication(candidate))

    fields = dict(result.raw[0].semantic_fields)
    assert fields["speech_role"] == "statement"
    assert fields["perspective"] == "unknown"
    audit = result.audit[0]
    # Originals retained: canonical keeps the candidate's own values.
    assert audit.canonical_observed_fields["speech_role"] == "answer"
    assert audit.normalized_fields == {
        "perspective": "source_explicit -> unknown",
        "speech_role": "answer -> statement",
    }


def test_matching_view_leaves_other_fields_alone() -> None:
    assert matching_view("polarity", "affirmed") == "affirmed"
    assert matching_view("semantic_type", "fact") == "fact"
    assert matching_view("proposition", "任何文本") == "任何文本"
    assert matching_view("speech_role", "statement") == "statement"


def test_absent_required_fields_are_recorded_not_guessed() -> None:
    candidate = _candidate()
    result = _assemble(candidate, _adjudication(candidate))

    audit = result.audit[0]
    assert "source_stance" in audit.absent_required_fields
    assert dict(result.raw[0].semantic_fields)["source_stance"] == ABSENT


def test_blank_canonical_field_is_rejected() -> None:
    candidate = _candidate()
    adjudication = _adjudication(candidate)
    adjudication["canonical_observed_fields"]["source_stance"] = ""  # type: ignore[index]

    with pytest.raises(ScoringInputError, match="explicit 'absent'"):
        _assemble(candidate, adjudication)


def test_gold_injected_proposition_is_rejected() -> None:
    candidate = _candidate()
    adjudication = _adjudication(candidate)
    # A record whose "proposition" was copied from the target gold record.
    adjudication["canonical_observed_fields"]["proposition"] = "金标里的另一句话"  # type: ignore[index]

    with pytest.raises(ScoringInputError, match="never rewritten or filled from a target record"):
        _assemble(candidate, adjudication)


def test_human_only_fields_are_never_overwritten_by_the_assembler() -> None:
    candidate = _candidate(semantic_type="unknown")
    adjudication = _adjudication(candidate)
    # semantic_type is human_only: the adjudicator's read wins over the raw value.
    adjudication["canonical_observed_fields"]["semantic_type"] = "fact"  # type: ignore[index]
    result = _assemble(candidate, adjudication)
    assert dict(result.raw[0].semantic_fields)["semantic_type"] == "fact"


def test_unresolved_is_rejected() -> None:
    candidate = _candidate()
    adjudication = _adjudication(candidate, judgement="unresolved", matched_gold_id=None)
    with pytest.raises(ScoringInputError, match="unresolved_max = 0"):
        _assemble(candidate, adjudication)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"matched_gold_id": None}, "matched requires a matched_gold_id"),
        ({"judgement": "incorrect"}, "must not carry a matched_gold_id"),
        ({"reviewer": "  "}, "reviewer is required"),
        ({"evidence": ""}, "evidence must cite"),
        ({"stage": "both"}, "invalid stage"),
        ({"role": "not_a_role"}, "invalid role"),
        ({"judgement": "maybe"}, "invalid judgement"),
        ({"source_id": "sha256:" + "b" * 64}, "contradicts"),
    ],
)
def test_illegal_adjudications_fail_closed(overrides: dict[str, object], message: str) -> None:
    candidate = _candidate()
    adjudication = _adjudication(candidate, **overrides)
    with pytest.raises(ScoringInputError, match=message):
        _assemble(candidate, adjudication)


def test_missing_required_per_record_field_is_rejected() -> None:
    candidate = _candidate()
    adjudication = _adjudication(candidate)
    adjudication.pop("reason")
    with pytest.raises(ScoringInputError, match="missing required_per_record_fields"):
        _assemble(candidate, adjudication)


def test_duplicate_adjudication_is_rejected() -> None:
    candidate = _candidate()
    adjudication = _adjudication(candidate)
    with pytest.raises(ScoringInputError, match="duplicate adjudication"):
        assemble_scoring_input([adjudication, adjudication], catalog={"itm_1": candidate})


def test_out_of_scope_is_registered_but_not_scored() -> None:
    candidate = _candidate()
    adjudication = _adjudication(candidate, judgement="out_of_scope", matched_gold_id=None)
    result = _assemble(candidate, adjudication)

    assert result.raw == () and result.validated == () and result.mappings == ()
    assert result.out_of_scope == ("itm_1",)


def test_validated_stage_keeps_raw_and_validated_separate() -> None:
    candidate = _candidate()
    raw = _adjudication(candidate, stage="raw")
    validated = _adjudication(candidate, stage="validated")
    result = assemble_scoring_input([raw, validated], catalog={"itm_1": candidate})

    assert [item.candidate_id for item in result.raw] == ["itm_1"]
    assert [item.candidate_id for item in result.validated] == ["itm_1"]
    assert len(result.mappings) == 2


def test_allowed_source_ids_scope_is_enforced() -> None:
    candidate = _candidate()
    adjudication = _adjudication(candidate)
    with pytest.raises(ScoringInputError, match="outside candidate_input_scope"):
        assemble_scoring_input(
            [adjudication], catalog={"itm_1": candidate}, allowed_source_ids={"sha256:" + "c" * 64}
        )


def test_condition_role_without_carrier_is_flagged_for_human_basis() -> None:
    condition_candidate = _candidate(statement_role="condition")
    condition_adjudication = _adjudication(
        condition_candidate,
        canonical_observed_fields={
            **_adjudication(condition_candidate)["canonical_observed_fields"],  # type: ignore[arg-type]
            "statement_role": "condition",
            "condition": ABSENT,
        },
    )
    assert condition_role_needs_human_basis(condition_adjudication) is True

    claim_candidate = _candidate()
    assert condition_role_needs_human_basis(_adjudication(claim_candidate)) is False


def test_assembler_cannot_read_gold() -> None:
    parameters = set(inspect.signature(assemble_scoring_input).parameters)
    assert parameters == {"adjudications", "catalog", "allowed_source_ids"}
    assert ROLE_REQUIRED_FIELDS[Role.MATERIAL_ITEMS] == (
        "proposition",
        "semantic_type",
        "statement_role",
        "speech_role",
        "perspective",
        "speaker_ref",
        "polarity",
        "attribution",
        "source_stance",
    )
    assert "gold" not in ADJUDICATION_FIELDS
    assert Stage.RAW.value == "raw" and Stage.VALIDATED.value == "validated"
