"""P02: the scorer consumes human adjudication mappings, never identity equality (contract v4.1).

``read_path.equivalence_judgement.scorer_contract``: 评分器只消费裁定完成的映射，并校验其
role/source_id 合法性与 canonical_observed_fields 是否齐备；身份相等不得作为匹配前提。
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, replace
from fractions import Fraction

import pytest

from plugins.corpus.structured_scoring import (
    PILOT_CANDIDATE_POLICY,
    AdjudicationJudgement,
    CandidateRecord,
    GoldRecord,
    MatchingMode,
    RecordOrigin,
    Role,
    RoleThreshold,
    ScoringInputError,
    score_structured_quality,
)

SOURCE = "sha256:" + "a" * 64


@dataclass(frozen=True)
class Mapping:
    """Structural stand-in for the assembler's mapping (the scorer is duck-typed)."""

    candidate_id: str
    gold_record_id: str | None
    judgement: str
    stage: str = "raw"


def _gold(record_id: str, key: str, *, role: Role = Role.MATERIAL_ITEMS) -> GoldRecord:
    return GoldRecord(
        record_id=record_id,
        role=role,
        source_id=SOURCE,
        origin=RecordOrigin.LLM_PROSE,
        semantic_fields=(("proposition", key),),
    )


def _candidate(candidate_id: str, key: str, *, role: Role = Role.MATERIAL_ITEMS) -> CandidateRecord:
    return CandidateRecord(
        candidate_id=candidate_id,
        role=role,
        source_id=SOURCE,
        origin=RecordOrigin.LLM_PROSE,
        semantic_fields=(("proposition", key),),
    )


def _score(
    gold: tuple[GoldRecord, ...],
    candidates: tuple[CandidateRecord, ...],
    mappings: tuple[Mapping, ...],
):
    return score_structured_quality(
        gold,
        raw_candidates=candidates,
        validated_candidates=candidates,
        matching_mode=MatchingMode.ADJUDICATED,
        raw_mappings=mappings,
        validated_mappings=mappings,
    )


def test_adjudicated_is_the_default_matching_mode() -> None:
    signature = inspect.signature(score_structured_quality)
    assert signature.parameters["matching_mode"].default is MatchingMode.ADJUDICATED


def test_field_equality_alone_never_matches() -> None:
    """Identical fields but the adjudicator judged it wrong ⇒ FP, not TP."""
    gold = (_gold("NT-I01", "完全相同的命题"),)
    candidate = _candidate("itm_1", "完全相同的命题")
    report = _score(gold, (candidate,), (Mapping("itm_1", None, "incorrect"),))

    metrics = report.validated.role(Role.MATERIAL_ITEMS)
    assert (metrics.tp, metrics.fp, metrics.fn) == (0, 1, 1)
    assert report.validated.matched_gold_ids == ()


def test_mapping_matches_even_when_fields_differ_completely() -> None:
    """Different fields but a human mapped them ⇒ TP. Identity equality is not the precondition."""
    gold = (_gold("NT-I09", "金标措辞A"),)
    candidate = _candidate("itm_1", "候选措辞B（同义改写）")
    report = _score(gold, (candidate,), (Mapping("itm_1", "NT-I09", "matched"),))

    metrics = report.validated.role(Role.MATERIAL_ITEMS)
    assert (metrics.tp, metrics.fp, metrics.fn) == (1, 0, 0)
    assert report.validated.matched_gold_ids == ("NT-I09",)


def test_correct_extra_enters_precision_but_not_recall() -> None:
    gold = (_gold("NT-I01", "目标命题"),)
    candidates = (_candidate("itm_1", "目标命题"), _candidate("itm_2", "额外但正确的命题"))
    mappings = (
        Mapping("itm_1", "NT-I01", "matched"),
        Mapping("itm_2", None, "correct_extra"),
    )
    report = _score(gold, candidates, mappings)

    metrics = report.validated.role(Role.MATERIAL_ITEMS)
    assert metrics.correct_extra == 1
    assert (metrics.tp, metrics.fp, metrics.fn) == (1, 0, 0)
    assert metrics.precision == Fraction(2, 2)
    assert metrics.recall == Fraction(1, 1)
    # Target recall denominator must not absorb correct_extra.
    assert metrics.recall == Fraction(metrics.tp, metrics.tp + metrics.fn)


def test_duplicate_counts_as_false_positive() -> None:
    gold = (_gold("NT-I01", "目标命题"),)
    candidates = (
        _candidate("itm_1", "第一种说法"),
        _candidate("itm_2", "同义重复的说法"),
    )
    mappings = (
        Mapping("itm_1", "NT-I01", "matched"),
        Mapping("itm_2", None, "duplicate"),
    )
    report = _score(gold, candidates, mappings)

    metrics = report.validated.role(Role.MATERIAL_ITEMS)
    assert (metrics.tp, metrics.fp, metrics.fn, metrics.duplicate_fp) == (1, 1, 0, 1)
    origin = report.validated.role_origin(Role.MATERIAL_ITEMS, RecordOrigin.LLM_PROSE)
    assert (origin.tp, origin.fp) == (1, 1)


def test_precision_formula_is_unchanged_when_correct_extra_is_zero() -> None:
    gold = (_gold("NT-I01", "目标命题"),)
    candidates = (_candidate("itm_1", "目标命题"), _candidate("itm_2", "错的"))
    mappings = (Mapping("itm_1", "NT-I01", "matched"), Mapping("itm_2", None, "incorrect"))
    metrics = _score(gold, candidates, mappings).validated.role(Role.MATERIAL_ITEMS)
    assert metrics.correct_extra == 0
    assert metrics.precision == Fraction(1, 2)


def test_unmapped_candidate_fails_closed() -> None:
    gold = (_gold("NT-I01", "目标命题"),)
    candidates = (_candidate("itm_1", "目标命题"), _candidate("itm_2", "没裁定的"))
    with pytest.raises(ScoringInputError, match="no adjudication mapping"):
        _score(gold, candidates, (Mapping("itm_1", "NT-I01", "matched"),))


def test_missing_mappings_fail_closed_under_adjudicated_mode() -> None:
    gold = (_gold("NT-I01", "目标命题"),)
    with pytest.raises(ScoringInputError, match="never falls back to identity equality"):
        score_structured_quality(
            gold,
            raw_candidates=(_candidate("itm_1", "目标命题"),),
            validated_candidates=(),
            matching_mode=MatchingMode.ADJUDICATED,
            validated_mappings=(),
            raw_mappings=None,
        )


def test_legacy_mode_rejects_mappings() -> None:
    gold = (_gold("NT-I01", "目标命题"),)
    with pytest.raises(ScoringInputError, match="must not be combined"):
        score_structured_quality(
            gold,
            raw_candidates=(),
            validated_candidates=(),
            matching_mode=MatchingMode.LEGACY_IDENTITY,
            raw_mappings=(),
            validated_mappings=(),
        )


@pytest.mark.parametrize(
    ("mapping", "message"),
    [
        (Mapping("itm_1", "NT-I99", "matched"), "is not in the frozen gold"),
        (Mapping("itm_1", "NT-I01", "unresolved"), "unresolved_candidates_max = 0"),
        (Mapping("itm_1", "NT-I01", "out_of_scope"), "must be filtered before scoring"),
        (Mapping("itm_1", "NT-I01", "maybe"), "outside candidate_judgements"),
    ],
)
def test_illegal_adjudications_fail_closed(mapping: Mapping, message: str) -> None:
    gold = (_gold("NT-I01", "目标命题"),)
    with pytest.raises(ScoringInputError, match=message):
        _score(gold, (_candidate("itm_1", "目标命题"),), (mapping,))


def test_cross_role_mapping_is_rejected() -> None:
    """A material_items candidate may not be mapped onto a claims gold record."""
    gold = (_gold("NT-I01", "目标命题", role=Role.CLAIMS),)
    with pytest.raises(ScoringInputError, match="outside the candidate's"):
        _score(gold, (_candidate("itm_1", "目标命题"),), (Mapping("itm_1", "NT-I01", "matched"),))


def test_cross_source_mapping_is_rejected() -> None:
    gold = (
        GoldRecord(
            record_id="NT-I01",
            role=Role.MATERIAL_ITEMS,
            source_id="sha256:" + "b" * 64,
            origin=RecordOrigin.LLM_PROSE,
            semantic_fields=(("proposition", "目标命题"),),
        ),
    )
    with pytest.raises(ScoringInputError, match="outside the candidate's"):
        _score(gold, (_candidate("itm_1", "目标命题"),), (Mapping("itm_1", "NT-I01", "matched"),))


def test_one_gold_record_cannot_be_matched_twice() -> None:
    gold = (_gold("NT-I01", "目标命题"),)
    candidates = (_candidate("itm_1", "说法一"), _candidate("itm_2", "说法二"))
    mappings = (
        Mapping("itm_1", "NT-I01", "matched"),
        Mapping("itm_2", "NT-I01", "matched"),
    )
    with pytest.raises(ScoringInputError, match="matched twice"):
        _score(gold, candidates, mappings)


def test_duplicate_mapping_row_is_rejected() -> None:
    gold = (_gold("NT-I01", "目标命题"),)
    mappings = (
        Mapping("itm_1", "NT-I01", "matched"),
        Mapping("itm_1", "NT-I01", "matched"),
    )
    with pytest.raises(ScoringInputError, match="duplicate adjudication mapping"):
        _score(gold, (_candidate("itm_1", "目标命题"),), mappings)


def test_pilot_policy_is_diagnostic_only_and_cannot_move_the_verdict() -> None:
    """P03 已落地：唯一权威布尔来自契约快照，pilot 策略只出诊断。

    旧断言（"P02 is matching only: P03 owns the threshold single-source change"）描述的是 P03
    落地前的状态；P03 已把 ``rate_gate_passed`` 单源到 ``ContractGateRequirements``。
    本条保留原数值断言，并补：**改 policy 不得改变判定布尔**（否则又是两套真相）。
    """
    threshold = PILOT_CANDIDATE_POLICY.role(Role.MATERIAL_ITEMS)
    assert (threshold.precision_min, threshold.recall_min) == (Fraction(19, 20), Fraction(9, 10))

    gold = (_gold("NT-I01", "命题甲"), _gold("NT-I02", "命题乙"))
    candidates = (_candidate("itm_1", "命题甲"),)
    mappings = (Mapping("itm_1", "NT-I01", "matched"),)

    def run(recall_min: Fraction):
        policy = replace(
            PILOT_CANDIDATE_POLICY,
            role_thresholds=tuple(
                RoleThreshold(item.role, item.precision_min, recall_min)
                if item.role is Role.MATERIAL_ITEMS
                else item
                for item in PILOT_CANDIDATE_POLICY.role_thresholds
            ),
        )
        return score_structured_quality(
            gold,
            raw_candidates=candidates,
            validated_candidates=candidates,
            matching_mode=MatchingMode.ADJUDICATED,
            raw_mappings=mappings,
            validated_mappings=mappings,
            policy=policy,
        )

    lenient, strict = run(Fraction(1, 2)), run(Fraction(9, 10))
    # 判定布尔只由契约快照决定 ⇒ 两次必须一致（此例契约门槛下均为 False）
    assert lenient.gate.rate_gate_passed == strict.gate.rate_gate_passed
    # 但诊断列表必须随之变化 ⇒ 证明 policy 仍在被计算、只是不再判定
    assert lenient.gate.pilot_policy_blockers != strict.gate.pilot_policy_blockers
    assert lenient.gate.rate_blockers == strict.gate.rate_blockers


def test_legacy_mode_ledger_is_pinned() -> None:
    """Control-arm semantics stay exact under LEGACY_IDENTITY."""
    gold = (_gold("NT-I01", "命题甲"), _gold("NT-I02", "命题乙"))
    candidates = (
        _candidate("itm_1", "命题甲"),
        _candidate("itm_1b", "命题甲"),  # duplicate identity ⇒ duplicate FP
        _candidate("itm_2", "命题丙"),  # unmatched ⇒ FP
    )
    report = score_structured_quality(
        gold,
        raw_candidates=candidates,
        validated_candidates=candidates,
        matching_mode=MatchingMode.LEGACY_IDENTITY,
    )
    metrics = report.validated.role(Role.MATERIAL_ITEMS)
    assert (metrics.tp, metrics.fp, metrics.fn, metrics.duplicate_fp) == (1, 2, 1, 1)
    assert report.validated.missing_gold_ids == ("NT-I02",)


def test_adjudication_judgement_enum_is_the_single_vocabulary() -> None:
    from plugins.corpus.adjudication_assembly import Judgement

    assert Judgement is AdjudicationJudgement
    assert {item.value for item in AdjudicationJudgement} == {
        "matched",
        "correct_extra",
        "incorrect",
        "duplicate",
        "unresolved",
        "out_of_scope",
    }
