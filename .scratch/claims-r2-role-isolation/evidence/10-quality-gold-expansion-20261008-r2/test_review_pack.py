"""Explicit opt-in tests of the approved review pack; mutations stay in memory."""

from __future__ import annotations

import copy
import runpy
from pathlib import Path
from typing import Any

import pytest

type Pack = tuple[dict[str, Any], dict[str, Any], dict[str, Any]]

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / "review_pack.py"))


@pytest.fixture
def pack() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    review = API["read_json"](HERE / "gold-review-candidates.json")
    contract = API["read_json"](HERE / "scoring-contract.json")
    sources = API["read_json"](HERE / contract["source_export"])
    return review, contract, sources


def record(review: dict[str, Any], rid: str) -> dict[str, Any]:
    return next(r for r in review["records"] if r["record_id"] == rid)


def test_corrected_pack_is_consistent_but_not_frozen(pack: Pack) -> None:
    result = API["validate"](*pack)
    assert result["errors"] == []
    assert result["draft_counts"] == {"claims": 20, "material_items": 48, "material_relations": 24}
    assert not result["formal_gold_frozen"]
    assert not result["mechanical_checks_prove_semantic_correctness"]


@pytest.mark.parametrize(
    ("rid", "key", "value", "error"),
    [
        ("NT-C02", "period", "2099H1", "period_normalization_mismatch"),
        ("NT-C02", "value", "999999", "value_normalization_mismatch"),
        ("NT-C14", "value", "75000", "value_normalization_mismatch"),
        ("NT-C02", "metric", "invented_metric", "invalid_metric_unit"),
        ("NT-C02", "unit", "万元", "invalid_metric_unit"),
        ("NT-C11", "source_stance", "endorsed", "review_assertion_mismatch"),
        ("NT-I13", "condition", "现金转换改善", "condition_threshold_missing"),
        ("NT-I17", "condition", "毛利率继续下降", "condition_threshold_missing"),
        ("NT-I38", "polarity", "affirmed", "review_assertion_mismatch"),
        ("NT-I37", "semantic_type", "fact", "review_assertion_mismatch"),
        ("NT-I16", "behavior_status", "claimed_executed", "behavior_intent_required"),
        ("NT-R10", "relation", "supports", "review_assertion_mismatch"),
        ("NT-R01", "provenance", "system_inferred", "inferred_relation_forbidden"),
        ("NT-R09", "to_gold_record_id", "NT-I18", "invalid_relation_endpoint"),
    ],
)
def test_review_regressions_are_rejected(
    pack: Pack, rid: str, key: str, value: str, error: str
) -> None:
    review, contract, sources = pack
    record(review, rid)["semantic_fields"][key] = value
    result = API["validate"](review, contract, sources)
    assert any(e.startswith(f"{error}:{rid}") for e in result["errors"])


def test_identical_behavior_cannot_be_counted_twice_with_new_wording(pack: Pack) -> None:
    review, contract, sources = pack
    duplicate = copy.deepcopy(record(review, "NT-I16"))
    duplicate["record_id"] = "new-wording-same-action"
    duplicate["semantic_fields"]["proposition"] = "另一种措辞的止损动作"
    review["records"].append(duplicate)
    result = API["validate"](review, contract, sources)
    assert any(e.startswith("duplicate_behavior_evidence:") for e in result["errors"])


def test_source_offset_corruption_is_rejected(pack: Pack) -> None:
    review, contract, sources = pack
    record(review, "NT-C02")["evidence"][0]["start"] += 1
    assert "quote_mismatch:NT-C02" in API["validate"](review, contract, sources)["errors"]


def test_loss_of_inner_condition_uncertainty_is_rejected(pack: Pack) -> None:
    review, contract, sources = pack
    record(review, "NT-I17")["unknown_fields"] = []
    assert "condition_ambiguity_lost:NT-I17" in API["validate"](review, contract, sources)["errors"]


def test_condition_group_requires_every_edge(pack: Pack) -> None:
    review, contract, sources = pack
    review["records"] = [r for r in review["records"] if r["record_id"] != "NT-R21"]
    assert "missing_condition_edge:NT-I42" in API["validate"](review, contract, sources)["errors"]


def test_human_accepted_state_is_rendered_without_claiming_freeze(pack: Pack) -> None:
    review, contract, sources = pack
    r = record(review, "NT-C02")
    r["review_status"] = "accepted"
    r["adjudication"] = {
        "reviewer": "test-reviewer",
        "decision": "accepted",
        "reason": "test only",
        "changes": [],
    }
    report = API["validate"](review, contract, sources)
    assert report["errors"] == []
    assert report["human_accepted_counts"] == {"claims": 1}
    assert "NT-C02 · accepted" in API["render"](review, report)
    assert not report["formal_gold_frozen"]


def test_rejected_claim_no_longer_satisfies_minimum(pack: Pack) -> None:
    review, contract, sources = pack
    r = record(review, "NT-C02")
    r["review_status"] = "rejected"
    r["adjudication"] = {
        "reviewer": "test-reviewer",
        "decision": "rejected",
        "reason": "test only",
        "changes": [],
    }
    report = API["validate"](review, contract, sources)
    assert report["draft_counts"]["claims"] == 19
    assert "insufficient_draft_records:claims" in report["errors"]


def judgement(cid: str, outcome: str, target: str | None = None) -> dict[str, Any]:
    return {
        "candidate_id": cid,
        "stage": "raw",
        "role": "material_items",
        "judgement": outcome,
        "matched_gold_id": target,
        "reviewer": "test-reviewer",
        "reason": "synthetic test",
        "original_candidate": {"text": "synthetic"},
        "evidence": ["synthetic"],
    }


def tally(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return API["candidate_precision"](
        rows, expected_candidate_ids={r["candidate_id"] for r in rows}
    )


def test_extra_correct_output_is_not_fp_and_duplicate_is_fp() -> None:
    report = tally(
        [
            judgement("a", "matched", "gold-1"),
            judgement("b", "correct_extra"),
            judgement("c", "duplicate", "gold-1"),
        ]
    )
    assert report["precision"] == "2/3"


def test_unresolved_output_prevents_precision_claim() -> None:
    assert (
        tally([judgement("a", "matched", "gold-1"), judgement("b", "unresolved")])["precision"]
        is None
    )


def test_missing_candidate_from_adjudication_cannot_disappear() -> None:
    with pytest.raises(ValueError, match="full candidate roster"):
        API["candidate_precision"](
            [judgement("a", "matched", "gold-1")], expected_candidate_ids={"a", "b"}
        )


def test_second_match_requires_duplicate_classification() -> None:
    with pytest.raises(ValueError, match="classified duplicate"):
        tally([judgement("a", "matched", "gold-1"), judgement("b", "matched", "gold-1")])


def test_mixed_raw_validated_scores_are_rejected() -> None:
    a, b = judgement("a", "correct_extra"), judgement("b", "correct_extra")
    b["stage"] = "validated"
    with pytest.raises(ValueError, match="separately"):
        tally([a, b])


def test_unsigned_candidate_correctness_is_rejected() -> None:
    a = judgement("a", "correct_extra")
    a["reviewer"] = None
    with pytest.raises(ValueError, match="named reviewer"):
        tally([a])
