"""Role-parameterised contract gate loading: claims support without moving items bytes.

``load_contract_gate_requirements`` now takes a ``role``. The frozen v4.2/v4.3 contracts declare
no ``role_sections``, so they keep serving ``Role.MATERIAL_ITEMS`` exactly as before (eleven
``NT-I**`` sentinels, target total 48) and every other role fails closed. A contract that does
declare ``role_sections.<role>`` is read per role: sentinel prefix, sentinel list and target
total all come from the signed file, so the claims gate needs no further code change once the
claims section is signed.

The dataclass field set is asserted here as well: the P03 binding verifier pins it, so a field
rename or addition must be a deliberate, signed change rather than a side effect.
"""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

import pytest

from plugins.corpus.structured_scoring import (
    CONTRACT_GATE_REQUIREMENTS,
    SIGNED_SCORING_CONTRACT_PATH,
    CandidateRecord,
    ContractGateRequirements,
    GoldRecord,
    MatchingMode,
    RecordOrigin,
    Role,
    ScoringInputError,
    load_contract_gate_requirements,
    score_structured_quality,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_V43 = SIGNED_SCORING_CONTRACT_PATH
EXPECTED_FIELD_SET = (
    "schema_version",
    "role_scope",
    "target_recall_overall_min",
    "target_recall_per_source_min",
    "candidate_precision_min",
    "accepted_records_total_min",
    "accepted_records_per_source_min",
    "unresolved_candidates_max",
    "material_items_target_total",
    "high_risk_item_assertions_required",
)
CLAIMS_SECTION = {
    "review_assertions": ["NT-C11", "NT-C12", "NT-C13"],
    "target_total": 20,
}


def _contract_with_role_sections(tmp_path: Path, sections: object) -> Path:
    contract = json.loads(CONTRACT_V43.read_text(encoding="utf-8"))
    contract["role_sections"] = sections
    path = tmp_path / "contract-with-sections.json"
    path.write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")
    return path


# ------------------------------------------------------------------ items unchanged


def test_items_role_is_unchanged_on_the_signed_contract() -> None:
    requirements = load_contract_gate_requirements(CONTRACT_V43)
    assert requirements == CONTRACT_GATE_REQUIREMENTS
    assert requirements.role_scope is Role.MATERIAL_ITEMS
    assert requirements.role_target_total == 48
    assert len(requirements.high_risk_item_assertions_required) == 11
    assert all(key.startswith("NT-I") for key in requirements.high_risk_item_assertions_required)


def test_signed_contract_declares_no_role_sections() -> None:
    """v4.3 predates role_sections; the legacy items branch is the only reason it still loads."""
    contract = json.loads(CONTRACT_V43.read_text(encoding="utf-8"))
    assert "role_sections" not in contract


def test_contract_dataclass_field_set_is_frozen() -> None:
    assert tuple(ContractGateRequirements.__dataclass_fields__) == EXPECTED_FIELD_SET


# ------------------------------------------------------------------ fail closed


@pytest.mark.parametrize("role", [Role.CLAIMS, Role.MATERIAL_RELATIONS])
def test_roles_without_a_section_fail_closed_on_v43(role: Role) -> None:
    with pytest.raises(ScoringInputError, match=f"contract_role_section_missing:{role.value}"):
        load_contract_gate_requirements(CONTRACT_V43, role=role)


def test_unknown_role_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ScoringInputError, match="contract_role_unknown"):
        load_contract_gate_requirements(CONTRACT_V43, role="not_a_role")


# ------------------------------------------------------------------ claims section


def test_claims_section_supplies_scope_sentinels_and_total(tmp_path: Path) -> None:
    path = _contract_with_role_sections(tmp_path, {"claims": CLAIMS_SECTION})
    requirements = load_contract_gate_requirements(path, role=Role.CLAIMS)

    assert requirements.role_scope is Role.CLAIMS
    assert requirements.high_risk_item_assertions_required == ("NT-C11", "NT-C12", "NT-C13")
    assert requirements.role_target_total == 20
    assert requirements.material_items_target_total == 20
    # Rate thresholds stay contract-wide; the two accepted-record floors fall back to the effective
    # (items) block while the section declares no override of its own.
    assert requirements.target_recall_overall_min == Fraction("0.85")
    assert requirements.candidate_precision_min == Fraction("0.8")
    assert requirements.accepted_records_total_min == 40
    assert requirements.accepted_records_per_source_min == 20
    # The items role is unaffected by another role's section.
    assert load_contract_gate_requirements(path).role_scope is Role.MATERIAL_ITEMS


@pytest.mark.parametrize(
    ("section", "error"),
    [
        ({"review_assertions": [], "target_total": 20}, "review_assertions"),
        ({"review_assertions": ["NT-C11", "NT-C11"], "target_total": 20}, "duplicate_assertion"),
        ({"review_assertions": ["NT-C11", "NT-I13"], "target_total": 20}, "foreign_assertion"),
        ({"review_assertions": ["NT-C11"], "target_total": 0}, "target_total"),
        ({"review_assertions": ["NT-C11"]}, "target_total"),
        ("not-an-object", "contract_role_section_invalid"),
    ],
)
def test_malformed_claims_section_fails_closed(tmp_path: Path, section: object, error: str) -> None:
    path = _contract_with_role_sections(tmp_path, {"claims": section})
    with pytest.raises(ScoringInputError, match=error):
        load_contract_gate_requirements(path, role=Role.CLAIMS)


def test_claims_section_overrides_only_the_accepted_floors(tmp_path: Path) -> None:
    """M1's hook: a signed role section carries its own count floors; everything else is shared."""
    section = dict(CLAIMS_SECTION, accepted_records_total_min=17, accepted_records_per_source_min=8)
    path = _contract_with_role_sections(tmp_path, {"claims": section})

    claims = load_contract_gate_requirements(path, role=Role.CLAIMS)
    items = load_contract_gate_requirements(path, role=Role.MATERIAL_ITEMS)

    assert (claims.accepted_records_total_min, claims.accepted_records_per_source_min) == (17, 8)
    assert (items.accepted_records_total_min, items.accepted_records_per_source_min) == (40, 20)
    # The override does not leak into the rate thresholds.
    assert claims.candidate_precision_min == items.candidate_precision_min == Fraction("0.8")


@pytest.mark.parametrize(
    "section",
    [
        {"accepted_records_total_min": "17", "target_total": 20, "review_assertions": ["NT-C11"]},
        {
            "accepted_records_per_source_min": 8.0,
            "target_total": 20,
            "review_assertions": ["NT-C11"],
        },
        {"accepted_records_total_min": True, "target_total": 20, "review_assertions": ["NT-C11"]},
    ],
)
def test_role_section_non_integer_floor_fails_closed(tmp_path: Path, section: object) -> None:
    path = _contract_with_role_sections(tmp_path, {"claims": section})
    with pytest.raises(ScoringInputError, match="accepted_records"):
        load_contract_gate_requirements(path, role=Role.CLAIMS)


def test_role_section_unexpected_threshold_key_fails_closed(tmp_path: Path) -> None:
    """A release-line rate pasted into a role section must not silently re-scope the gate."""
    section = dict(CLAIMS_SECTION, candidate_precision_min=0.6)
    path = _contract_with_role_sections(tmp_path, {"claims": section})
    with pytest.raises(ScoringInputError, match="unexpected_key:candidate_precision_min"):
        load_contract_gate_requirements(path, role=Role.CLAIMS)


# ------------------------------------------------------------------ gate follows role_scope


def _claims_gold(record_id: str) -> GoldRecord:
    return GoldRecord(
        record_id=record_id,
        role=Role.CLAIMS,
        source_id="sha256:" + "b" * 64,
        origin=RecordOrigin.LLM_PROSE,
        semantic_fields=(("value", "1"),),
    )


def _claims_candidate(candidate_id: str) -> CandidateRecord:
    return CandidateRecord(
        candidate_id=candidate_id,
        role=Role.CLAIMS,
        source_id="sha256:" + "b" * 64,
        origin=RecordOrigin.LLM_PROSE,
        semantic_fields=(("value", "1"),),
    )


def _mapping(candidate_id: str, gold_id: str | None, judgement: str = "matched"):
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


def _claims_requirements(**overrides: object) -> ContractGateRequirements:
    values: dict[str, object] = {
        "schema_version": "synthetic-claims-gate",
        "role_scope": Role.CLAIMS,
        "target_recall_overall_min": Fraction(17, 20),
        "target_recall_per_source_min": Fraction(4, 5),
        "candidate_precision_min": Fraction(4, 5),
        "accepted_records_total_min": 1,
        "accepted_records_per_source_min": 1,
        "unresolved_candidates_max": 0,
        "material_items_target_total": 20,
        "high_risk_item_assertions_required": ("NT-C11", "NT-C12", "NT-C13"),
    }
    values.update(overrides)
    return ContractGateRequirements(**values)  # type: ignore[arg-type]


def test_gate_evaluates_the_declared_role_scope() -> None:
    gold = (_claims_gold("NT-C11"),)
    candidates = (_claims_candidate("c1"), _claims_candidate("c2"))
    mappings = (_mapping("c1", "NT-C11"), _mapping("c2", None, "incorrect"))
    report = score_structured_quality(
        gold,
        matching_mode=MatchingMode.ADJUDICATED,
        raw_candidates=candidates,
        validated_candidates=candidates,
        raw_mappings=mappings,
        validated_mappings=mappings,
        gate_requirements=_claims_requirements(high_risk_item_assertions_required=("NT-C11",)),
    )

    # Claims scope: precision 1/2 fails the 0.80 floor; the matched sentinel is covered.
    assert report.validated.role(Role.CLAIMS).precision == Fraction(1, 2)
    assert any(
        blocker.startswith("contract_below_threshold:candidate_precision")
        for blocker in report.gate.rate_blockers
    )
    assert not any(
        "high_risk_assertion_unmatched" in blocker for blocker in report.gate.rate_blockers
    )
    assert report.gate.rate_gate_passed is False

    # Same input, items scope: the claims records are out of scope, so the items denominator is
    # empty and the gate reports a zero denominator instead of silently passing.
    items_scoped = score_structured_quality(
        gold,
        matching_mode=MatchingMode.ADJUDICATED,
        raw_candidates=candidates,
        validated_candidates=candidates,
        raw_mappings=mappings,
        validated_mappings=mappings,
        gate_requirements=_claims_requirements(
            role_scope=Role.MATERIAL_ITEMS, high_risk_item_assertions_required=()
        ),
    )
    assert "contract_zero_denominator:target_recall_overall" in items_scoped.gate.rate_blockers
    assert items_scoped.gate.rate_gate_passed is False
