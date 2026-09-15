# ruff: noqa: ANN001, ANN201
from __future__ import annotations

import copy

import p3i_contract_bridge as bridge
import pytest


@pytest.fixture(scope="module")
def built():
    return bridge.build()


def completed_review(template):
    review = copy.deepcopy(template)
    review.update(
        reviewer_name="human",
        reviewed_at="2026-09-14T18:00:00+08:00",
        policy_decision="approve",
        policy_reason="rules preserve the reviewed source semantics",
    )
    review["policy_checks"] = {key: True for key in review["policy_checks"]}
    for row in review["speaker_entries"]:
        row.update(
            human_decision="approve",
            human_reason="mapping is reversible",
            reversible_mapping_ok=True,
        )
    for row in review["value_records"]:
        row.update(
            human_decision="approve",
            human_reason="value and unit remain source bound",
            value_expression_lossless=True,
            unit_treatment_acceptable=True,
        )
    review["approved_speaker_entries"] = len(review["speaker_entries"])
    review["approved_value_records"] = len(review["value_records"])
    return review


def test_projection_has_all_35_unique_targets(built):
    projection, _ = built
    ids = [row["target_id"] for row in projection["records"]]
    assert len(ids) == len(set(ids)) == 35


def test_projection_is_evaluation_only(built):
    projection, _ = built
    assert projection["purpose"] == "evaluation_target_projection_only_never_model_input"
    assert all(row["evaluation_only"] is True for row in projection["records"])


def test_axes_match_p1_contract(built):
    projection, _ = built
    assert tuple(projection["contract"]["axes"]) == bridge.P1_AXES
    assert all(tuple(row["projected_fields"]) == bridge.P1_AXES for row in projection["records"])


def test_all_nodes_are_human_approved_and_bound(built):
    projection, _ = built
    assert all(row["approved_node"]["node_id"] for row in projection["records"])
    assert all(
        bridge.normalized(row["source_quote"]) in bridge.normalized(row["approved_node"]["text"])
        for row in projection["records"]
    )


def test_speaker_registry_is_reversible_and_scope_local(built):
    projection, _ = built
    registry = {row["speaker_ref"]: row for row in projection["speaker_registry"]}
    assert len(registry) == projection["counts"]["speaker_registry_entries"]
    for record in projection["records"]:
        speaker = record["speaker_projection"]
        entry = registry[speaker["speaker_ref"]]
        assert entry["scope_id"] == record["scope_id"]
        assert entry["speaker_role"] == speaker["speaker_role"]
        assert entry["identity_status"] == speaker["identity_status"]


def test_unknown_fields_are_losslessly_prefixed(built):
    projection, _ = built
    assert projection["counts"]["unknown_constraints"] > 0
    for record in projection["records"]:
        assert len(record["constraints"]) == len(set(record["constraints"]))
        assert all(value.startswith("unknown_field:") for value in record["constraints"])


def test_only_three_allowlisted_value_transforms(built):
    projection, _ = built
    transformed = {
        row["target_id"]: row["value_projection"]["transform_rule_id"]
        for row in projection["records"]
        if row["value_projection"]["value_origin"] == "validated_transform"
    }
    assert transformed == bridge.TRANSFORM_RULES


def test_literal_values_have_no_transform(built):
    projection, _ = built
    literal = [
        row for row in projection["records"]
        if row["value_projection"]["value_origin"] == "source_observed"
    ]
    assert len(literal) == 5
    assert all(row["value_projection"]["transform_rule_id"] is None for row in literal)


def test_null_values_remain_explicit_unknown(built):
    projection, _ = built
    nulls = [row for row in projection["records"] if row["projected_fields"]["value"] is None]
    assert len(nulls) == 27
    assert all(row["value_projection"]["value_origin"] == "unknown" for row in nulls)


def test_units_must_be_literal_in_source(built):
    projection, _ = built
    valued = [row for row in projection["records"] if row["projected_fields"]["unit"] is not None]
    assert len(valued) == 5
    assert all(row["projected_fields"]["unit"] in row["source_quote"] for row in valued)


def test_no_model_or_external_access_is_claimed(built):
    projection, _ = built
    assert projection["model_calls"] == 0
    assert projection["postgres_access"] == 0
    assert projection["holdout_reads"] == 0
    assert projection["ingestion_runs"] == 0
    assert projection["p4_budget_authorized"] is False


def test_review_interface_is_smaller_than_projection(built):
    projection, template = built
    assert len(template["value_records"]) == 8
    assert len(template["speaker_entries"]) == projection["counts"]["speaker_registry_entries"]
    assert len(template["value_records"]) + len(template["speaker_entries"]) < 35


def test_complete_review_passes(built):
    projection, template = built
    result = bridge.validate_review(completed_review(template), projection)
    assert result["all_approved"] is True


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda review: review.update(projection_sha256="bad"), "review_projection_binding"),
        (lambda review: review.update(approved_speaker_entries=0), "speaker_approved_count"),
        (lambda review: review.update(approved_value_records=0), "value_approved_count"),
        (lambda review: review["policy_checks"].update(unknown_fields_are_losslessly_preserved_as_constraints=False), "policy_approve_contradiction"),
        (lambda review: review["speaker_entries"][0].update(reversible_mapping_ok=False), "speaker_approve_contradiction"),
        (lambda review: review["value_records"][0].update(unit_treatment_acceptable=False), "value_approve_contradiction"),
    ],
)
def test_review_mutations_fail_closed(built, mutation, error):
    projection, template = built
    review = completed_review(template)
    mutation(review)
    with pytest.raises(ValueError, match=error):
        bridge.validate_review(review, projection)


def test_missing_speaker_review_fails(built):
    projection, template = built
    review = completed_review(template)
    review["speaker_entries"].pop()
    with pytest.raises(ValueError, match="speaker_review_identity"):
        bridge.validate_review(review, projection)


def test_duplicate_value_review_fails(built):
    projection, template = built
    review = completed_review(template)
    review["value_records"][-1] = copy.deepcopy(review["value_records"][0])
    with pytest.raises(ValueError, match="value_review_identity"):
        bridge.validate_review(review, projection)
