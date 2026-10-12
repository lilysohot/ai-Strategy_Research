"""P03: the gate boolean is driven by the signed contract's axes, in the gate's role scope.

Contract v4.2 ``threshold_source.effective`` + gate 28 ``quality_requirements``; design
``evidence/59-p03-design-20261012`` (1-A + 2-C + 3-A′).
"""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

import pytest

from plugins.corpus.structured_scoring import (
    CONTRACT_GATE_REQUIREMENTS,
    CandidateRecord,
    ContractGateRequirements,
    GoldRecord,
    MatchingMode,
    RecordOrigin,
    Role,
    score_structured_quality,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_V42 = (
    REPO_ROOT
    / ".scratch/claims-r2-role-isolation/evidence/58-contract-v42-signed-20261012/r0-zero-call/scoring-contract-v4.2.json"
)
GATE_V2 = (
    REPO_ROOT
    / ".scratch/claims-r2-role-isolation/evidence/28-items-only-quality-gate-20261010/r0-zero-call/preregistered-gate-v2.json"
)


def _item(
    record_id: str, source_id: str, *, risk: bool = False, critical: bool = False
) -> GoldRecord:
    return GoldRecord(
        record_id=record_id,
        role=Role.MATERIAL_ITEMS,
        source_id=source_id,
        origin=RecordOrigin.LLM_PROSE,
        semantic_fields=(("proposition", f"命题 {record_id}"),),
        risk_or_condition=risk,
        critical=critical,
    )


def _candidate(candidate_id: str, source_id: str, key: str) -> CandidateRecord:
    return CandidateRecord(
        candidate_id=candidate_id,
        role=Role.MATERIAL_ITEMS,
        source_id=source_id,
        origin=RecordOrigin.LLM_PROSE,
        semantic_fields=(("proposition", key),),
    )


def _mapping(candidate_id: str, gold_id: str | None, judgement: str = "matched"):
    """A structural mapping stand-in (the scorer is duck-typed)."""
    return type(
        "M",
        (),
        {
            "candidate_id": candidate_id,
            "gold_record_id": gold_id,
            "judgement": judgement,
            "stage": "raw",
        },
    )()


def _requirements(**overrides: object) -> ContractGateRequirements:
    values: dict[str, object] = {
        "schema_version": "synthetic-gate",
        "role_scope": Role.MATERIAL_ITEMS,
        "target_recall_overall_min": Fraction(17, 20),
        "target_recall_per_source_min": Fraction(4, 5),
        "candidate_precision_min": Fraction(4, 5),
        "accepted_records_total_min": 1,
        "accepted_records_per_source_min": 1,
        "unresolved_candidates_max": 0,
        "material_items_target_total": 4,
        "high_risk_item_assertions_required": (),
    }
    values.update(overrides)
    return ContractGateRequirements(**values)  # type: ignore[arg-type]


def _score(gold, candidates, mappings, requirements):
    return score_structured_quality(
        gold,
        matching_mode=MatchingMode.ADJUDICATED,
        raw_candidates=candidates,
        validated_candidates=candidates,
        raw_mappings=mappings,
        validated_mappings=mappings,
        gate_requirements=requirements,
    )


# ---------------------------------------------------------------- signed snapshot regression


def test_embedded_requirements_equal_the_signed_contract() -> None:
    """评分器读契约的可执行形式：契约一改，这条测试即红。"""
    contract = json.loads(CONTRACT_V42.read_text(encoding="utf-8"))
    effective = contract["threshold_source"]["effective"]

    assert contract["schema_version"] == CONTRACT_GATE_REQUIREMENTS.schema_version
    assert (
        Fraction(str(effective["target_recall_overall_min"]))
        == CONTRACT_GATE_REQUIREMENTS.target_recall_overall_min
    )
    assert (
        Fraction(str(effective["target_recall_per_source_min"]))
        == CONTRACT_GATE_REQUIREMENTS.target_recall_per_source_min
    )
    assert (
        Fraction(str(effective["candidate_precision_min"]))
        == CONTRACT_GATE_REQUIREMENTS.candidate_precision_min
    )
    assert (
        effective["accepted_records_total_min"]
        == CONTRACT_GATE_REQUIREMENTS.accepted_records_total_min
    )
    assert (
        effective["accepted_records_per_source_min"]
        == CONTRACT_GATE_REQUIREMENTS.accepted_records_per_source_min
    )
    assert (
        effective["unresolved_candidates_max"]
        == CONTRACT_GATE_REQUIREMENTS.unresolved_candidates_max
    )


def test_high_risk_assertions_equal_gate_28() -> None:
    gate = json.loads(GATE_V2.read_text(encoding="utf-8"))
    required = gate["quality_requirements"]["high_risk_item_assertions_required"]
    assert tuple(required) == CONTRACT_GATE_REQUIREMENTS.high_risk_item_assertions_required
    assert len(required) == 16
    assert (
        gate["gold"]["scoring_contract_sha256"]
        == ("sha256:c76ac13ec0a109074775a2b5e1c8cc170da955847638d6ea7f5778988238781b")
        or gate["quality_requirements"]["metric_basis"].endswith("v4.2") is False
    )


# ---------------------------------------------------------------- single boolean


def test_there_is_exactly_one_gate_boolean() -> None:
    gate_fields = {name for name in ContractGateRequirements.__dataclass_fields__}
    assert "high_risk_item_assertions_required" in gate_fields
    score = score_structured_quality(
        (),
        matching_mode=MatchingMode.LEGACY_IDENTITY,
        raw_candidates=(),
        validated_candidates=(),
    )
    assert isinstance(score.gate.pilot_policy_blockers, tuple)
    assert not hasattr(score.gate, "pilot_gate_passed")
    assert not hasattr(score.gate, "contract_gate_passed")


# ---------------------------------------------------------------- role scope


def test_claims_and_relations_do_not_pollute_the_items_gate() -> None:
    gold = (
        GoldRecord(
            "g-claim",
            Role.CLAIMS,
            "src",
            RecordOrigin.LLM_PROSE,
            (("key", "claim"),),
        ),
        _item("g-item", "src"),
    )
    candidates = (
        CandidateRecord(
            "c-claim",
            Role.CLAIMS,
            "src",
            RecordOrigin.LLM_PROSE,
            (("key", "完全不同的主张"),),
        ),
        _candidate("c-item", "src", "命题 g-item"),
    )
    mappings = (
        _mapping("c-claim", "g-claim", "incorrect"),
        _mapping("c-item", "g-item", "matched"),
    )
    mappings = [
        type(
            "M",
            (),
            {
                "candidate_id": "c-claim",
                "gold_record_id": None,
                "judgement": "incorrect",
                "stage": "raw",
            },
        )(),
        type(
            "M",
            (),
            {
                "candidate_id": "c-item",
                "gold_record_id": "g-item",
                "judgement": "matched",
                "stage": "raw",
            },
        )(),
    ]
    report = _score(gold, candidates, mappings, _requirements())

    # The wrong claims candidate must not drag the items precision below the floor.
    assert report.gate.rate_gate_passed is True
    items = report.validated.role(Role.MATERIAL_ITEMS)
    assert items.precision == Fraction(1, 1)
    claims = report.validated.role(Role.CLAIMS)
    assert claims.precision == Fraction(0, 1)
    assert claims.tp == 0 and claims.fp == 1


# ---------------------------------------------------------------- recall / accepted axes


def test_overall_recall_blocker() -> None:
    gold = (
        _item("g-1", "src"),
        _item("g-2", "src"),
        _item("g-3", "src"),
        _item("g-4", "src"),
    )
    candidates = tuple(_candidate(f"c-{i}", "src", f"命题 g-{i}") for i in (1, 2, 3))
    mappings = [
        type(
            "M",
            (),
            {
                "candidate_id": f"c-{i}",
                "gold_record_id": f"g-{i}",
                "judgement": "matched",
                "stage": "raw",
            },
        )()
        for i in (1, 2, 3)
    ]
    report = _score(gold, candidates, mappings, _requirements())

    assert report.validated.role(Role.MATERIAL_ITEMS).recall == Fraction(3, 4)
    assert "contract_below_threshold:target_recall_overall:3/4<17/20" in report.gate.rate_blockers
    assert report.gate.rate_gate_passed is False


def test_per_source_recall_and_accepted_count_blockers() -> None:
    gold = (
        _item("g-1", "src-a"),
        _item("g-2", "src-a"),
        _item("g-3", "src-a"),
        _item("g-4", "src-b"),
    )
    candidates = (
        _candidate("c-1", "src-a", "命题 g-1"),
        _candidate("c-2", "src-a", "命题 g-2"),
        _candidate("c-4", "src-b", "命题 g-4"),
    )
    mappings = [
        type(
            "M",
            (),
            {
                "candidate_id": f"c-{i}",
                "gold_record_id": f"g-{i}",
                "judgement": "matched",
                "stage": "raw",
            },
        )()
        for i in (1, 2, 4)
    ]
    requirements = _requirements(
        accepted_records_per_source_min=3,
        target_recall_per_source_min=Fraction(4, 5),
    )
    report = _score(gold, candidates, mappings, requirements)

    # src-a: 2/3 recall and 2 accepted; src-b: 1/1. Overall 3/4 = 0.75.
    assert (
        "contract_below_threshold:target_recall_per_source:src-a:2/3<4/5"
        in report.gate.rate_blockers
    )
    assert (
        "contract_below_threshold:accepted_records_per_source:src-a:2<3"
        in report.gate.rate_blockers
    )
    assert "contract_below_threshold:target_recall_overall:3/4<17/20" in report.gate.rate_blockers
    assert report.gate.rate_gate_passed is False


def test_accepted_records_total_blocker() -> None:
    gold = tuple(_item(f"g-{i}", "src") for i in range(1, 5))
    candidates = tuple(_candidate(f"c-{i}", "src", f"命题 g-{i}") for i in (1, 2, 3))
    mappings = [
        type(
            "M",
            (),
            {
                "candidate_id": f"c-{i}",
                "gold_record_id": f"g-{i}",
                "judgement": "matched",
                "stage": "raw",
            },
        )()
        for i in (1, 2, 3)
    ]
    requirements = _requirements(
        accepted_records_total_min=4, target_recall_overall_min=Fraction(3, 4)
    )
    report = _score(gold, candidates, mappings, requirements)

    assert report.validated.role(Role.MATERIAL_ITEMS).precision == Fraction(1, 1)
    assert "contract_below_threshold:accepted_records_total:3<4" in report.gate.rate_blockers


# ---------------------------------------------------------------- high-risk assertions


def test_high_risk_assertion_unmatched_is_a_blocker() -> None:
    gold = (
        _item("g-1", "src"),
        _item("NT-I09", "src"),
    )
    candidates = (_candidate("c-1", "src", "命题 g-1"),)
    mappings = [
        type(
            "M",
            (),
            {
                "candidate_id": "c-1",
                "gold_record_id": "g-1",
                "judgement": "matched",
                "stage": "raw",
            },
        )()
    ]
    requirements = _requirements(high_risk_item_assertions_required=("NT-I09",))
    report = _score(gold, candidates, mappings, requirements)

    assert "contract_high_risk_assertion_unmatched:NT-I09" in report.gate.rate_blockers
    assert report.gate.rate_gate_passed is False

    matched = _score(
        gold,
        (_candidate("c-1", "src", "命题 g-1"), _candidate("c-2", "src", "命题 NT-I09")),
        [
            *mappings,
            type(
                "M",
                (),
                {
                    "candidate_id": "c-2",
                    "gold_record_id": "NT-I09",
                    "judgement": "matched",
                    "stage": "raw",
                },
            )(),
        ],
        requirements,
    )
    assert matched.gate.rate_gate_passed is True


# ---------------------------------------------------------------- risk_condition reporting


def test_risk_condition_is_reported_but_never_gates() -> None:
    """契约六值无 risk 阈值 ⇒ 比率照报、不进 blocker（含按角色计数）。"""
    gold = (
        _item("g-1", "src", risk=True),
        _item("g-2", "src", risk=True),
        _item("g-3", "src", risk=True),
        _item("g-4", "src"),
    )
    candidates = tuple(_candidate(f"c-{i}", "src", f"命题 g-{i}") for i in (1, 2, 4))
    mappings = [
        type(
            "M",
            (),
            {
                "candidate_id": f"c-{i}",
                "gold_record_id": f"g-{i}",
                "judgement": "matched",
                "stage": "raw",
            },
        )()
        for i in (1, 2, 4)
    ]
    requirements = _requirements(
        target_recall_overall_min=Fraction(1, 2),
        target_recall_per_source_min=Fraction(1, 2),
        accepted_records_total_min=3,
    )
    report = _score(gold, candidates, mappings, requirements)

    assert report.gate.risk_condition_recall == Fraction(2, 3)
    assert report.gate.risk_condition_by_role == (("material_items", 2, 3),)
    assert not any("risk" in blocker for blocker in report.gate.rate_blockers)
    assert report.gate.rate_gate_passed is True


def test_risk_condition_per_role_counts_are_reported() -> None:
    gold = (
        _item("g-1", "src", risk=True),
        _item("g-2", "src", risk=True),
    )
    candidates = (_candidate("c-1", "src", "命题 g-1"), _candidate("c-2", "src", "命题 g-2"))
    mappings = [
        type(
            "M",
            (),
            {
                "candidate_id": "c-1",
                "gold_record_id": "g-1",
                "judgement": "matched",
                "stage": "raw",
            },
        )(),
        type(
            "M",
            (),
            {
                "candidate_id": "c-2",
                "gold_record_id": None,
                "judgement": "incorrect",
                "stage": "raw",
            },
        )(),
    ]
    report = _score(gold, candidates, mappings, _requirements())

    assert report.gate.risk_condition_by_role == (("material_items", 1, 2),)
    assert report.gate.risk_condition_recall == Fraction(1, 2)


# ---------------------------------------------------------------- report support / critical


def test_report_support_is_a_readiness_precondition() -> None:
    gold = (_item("g-1", "src"),)
    candidates = (_candidate("c-1", "src", "命题 g-1"),)
    mappings = [
        type(
            "M",
            (),
            {
                "candidate_id": "c-1",
                "gold_record_id": "g-1",
                "judgement": "matched",
                "stage": "raw",
            },
        )()
    ]
    report = score_structured_quality(
        gold,
        matching_mode=MatchingMode.ADJUDICATED,
        raw_candidates=candidates,
        validated_candidates=candidates,
        raw_mappings=mappings,
        validated_mappings=mappings,
        gate_requirements=_requirements(),
    )

    assert report.gate.rate_gate_passed is True
    assert "zero_denominator:report_support" in report.gate.readiness_blockers
    assert all("report_support" not in blocker for blocker in report.gate.rate_blockers)
    assert report.gate.live_trial_ready is False


def test_critical_gold_missing_still_gates() -> None:
    gold = (_item("g-1", "src", critical=True), _item("g-2", "src"))
    candidates = (_candidate("c-2", "src", "命题 g-2"),)
    mappings = [
        type(
            "M",
            (),
            {
                "candidate_id": "c-2",
                "gold_record_id": "g-2",
                "judgement": "matched",
                "stage": "raw",
            },
        )()
    ]
    report = _score(gold, candidates, mappings, _requirements())

    assert "critical_gold_missing:g-1" in report.gate.rate_blockers
    assert report.gate.rate_gate_passed is False


# ---------------------------------------------------------------- pilot policy demotion


def test_pilot_policy_never_gates_any_more() -> None:
    """claims 全错（pilot 阈值大幅不达标）但 items 契约轴全过 ⇒ 门仍过。"""
    gold = (
        GoldRecord("g-claim", Role.CLAIMS, "src", RecordOrigin.LLM_PROSE, (("key", "claim"),)),
        _item("g-item", "src"),
    )
    candidates = (
        CandidateRecord("c-claim", Role.CLAIMS, "src", RecordOrigin.LLM_PROSE, (("key", "别的"),)),
        _candidate("c-item", "src", "命题 g-item"),
    )
    mappings = [
        type(
            "M",
            (),
            {
                "candidate_id": "c-claim",
                "gold_record_id": None,
                "judgement": "incorrect",
                "stage": "raw",
            },
        )(),
        type(
            "M",
            (),
            {
                "candidate_id": "c-item",
                "gold_record_id": "g-item",
                "judgement": "matched",
                "stage": "raw",
            },
        )(),
    ]
    report = _score(gold, candidates, mappings, _requirements())

    assert report.gate.rate_gate_passed is True
    assert any("below_threshold:claims" in blocker for blocker in report.gate.pilot_policy_blockers)
    assert all("claims" not in blocker for blocker in report.gate.rate_blockers)


def test_unmapped_candidate_is_rejected_so_unresolved_stays_zero() -> None:
    """unresolved_candidates_max = 0 由结构保证：装配器拒 unresolved，评分器拒未映射。"""
    gold = (_item("g-1", "src"),)
    with pytest.raises(Exception, match="no adjudication mapping"):
        _score(
            gold,
            (_candidate("c-1", "src", "命题 g-1"), _candidate("c-2", "src", "命题 g-1")),
            [
                type(
                    "M",
                    (),
                    {
                        "candidate_id": "c-1",
                        "gold_record_id": "g-1",
                        "judgement": "matched",
                        "stage": "raw",
                    },
                )()
            ],
            _requirements(),
        )
