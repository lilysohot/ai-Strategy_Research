from __future__ import annotations

import copy
import json
import socket
from pathlib import Path
from typing import Any

import p3_replay_review as p3
import p3h_review
import pytest


@pytest.fixture(scope="module")
def base() -> dict[str, Any]:
    return json.loads(p3.MICRO_GOLD.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def amendment() -> dict[str, Any]:
    return json.loads(p3h_review.AMENDMENT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effective(base: dict[str, Any], amendment: dict[str, Any]) -> dict[str, Any]:
    return p3h_review.apply_amendment(base, amendment)


@pytest.fixture(scope="module")
def built() -> tuple[dict[str, Any], dict[str, Any]]:
    return p3h_review.build()


def test_frozen_inputs_and_human_submission_are_valid() -> None:
    p3h_review.verify_pins()
    review = p3h_review.load_human_review()
    assert review["reviewer_name"] == "Xyl"
    assert review["approved_records"] == 31


def test_amendment_does_not_mutate_frozen_base(
    base: dict[str, Any], amendment: dict[str, Any]
) -> None:
    before = copy.deepcopy(base)
    result = p3h_review.apply_amendment(base, amendment)
    assert base == before
    assert result is not base
    assert p3h_review.sha(p3.MICRO_GOLD) == amendment["base_gold_sha256"]


def test_effective_counts_match_amendment(effective: dict[str, Any]) -> None:
    assert effective["expected_counts"] == {
        "scopes": 6,
        "items": 35,
        "positive_relations": 16,
        "negative_relations": 8,
        "excluded_fragments": 6,
    }


def test_rating_is_separate_from_target_price(effective: dict[str, Any]) -> None:
    scope = next(scope for scope in effective["scopes"] if scope["scope_id"] == "micro-company-recommendation")
    items = {item["item_id"]: item for item in scope["items"]}
    assert items["mc-rating-v2"]["quote"] == "“强推”评级"
    assert "2030" not in items["mc-rating-v2"]["quote"]
    assert "mc-rating" not in items


def test_industry_fragments_are_merged_with_one_answer_relation(
    effective: dict[str, Any]
) -> None:
    scope = next(scope for scope in effective["scopes"] if scope["scope_id"] == "micro-industry-q7-q8")
    item_ids = {item["item_id"] for item in scope["items"]}
    assert "mi-a-focus-balance" not in item_ids
    assert "mi-a-focus-spread" not in item_ids
    assert "mi-a-focus-balance-spread-v2" in item_ids
    relations = [
        relation
        for relation in scope["relations"]
        if relation["from_item"] == "mi-a-focus-balance-spread-v2"
    ]
    assert relations == [
        {
            "relation_id": "mir-03-v2",
            "type": "answers",
            "from_item": "mi-a-focus-balance-spread-v2",
            "to_item": "mi-q-bottom",
        }
    ]


def test_summary_is_split_into_three_pending_items(effective: dict[str, Any]) -> None:
    scope = next(scope for scope in effective["scopes"] if scope["scope_id"] == "micro-copper-summary")
    assert {item["item_id"] for item in scope["items"]} == {
        "mcs-industry-substitution-v2",
        "mcs-taijin-growth-v2",
        "mcs-surface-treatment-v2",
    }


def test_call_setup_is_removed_and_recorded_as_excluded(effective: dict[str, Any]) -> None:
    scope = next(scope for scope in effective["scopes"] if scope["scope_id"] == "micro-copper-audio")
    assert scope["items"] == []
    assert any(entry["reason"] == "human_rejected_call_setup_not_research_item" for entry in scope["excluded"])


def test_all_effective_relations_have_live_endpoints(effective: dict[str, Any]) -> None:
    ids = {item["item_id"] for scope in effective["scopes"] for item in scope["items"]}
    relations = [
        relation
        for scope in effective["scopes"]
        for relation in (*scope["relations"], *scope["negative_relations"])
    ]
    assert all(relation["from_item"] in ids and relation["to_item"] in ids for relation in relations)


def test_effective_denominator_replays_to_unique_nodes_and_scopes(
    built: tuple[dict[str, Any], dict[str, Any]]
) -> None:
    inventory, _ = built
    assert inventory["node_results"] == {
        "unique_minimum_mappings": 35,
        "distinct_mapped_nodes": 35,
    }
    assert inventory["scope_results"] == {
        "items_in_unique_generated_scope": 35,
        "positive_relation_endpoints_referencable": 16,
        "negative_relation_endpoints_referencable": 8,
    }


def test_only_unaffected_human_approvals_are_carried_forward(
    built: tuple[dict[str, Any], dict[str, Any]]
) -> None:
    inventory, template = built
    assert inventory["carry_forward_approved_items"] == 30
    assert inventory["replacement_items_pending_review"] == 5
    assert template["carried_forward_approved_records"] == 30


def test_remediation_template_contains_only_five_unsigned_replacements(
    built: tuple[dict[str, Any], dict[str, Any]]
) -> None:
    _, template = built
    assert {record["target_id"] for record in template["records"]} == p3h_review.PENDING_IDS
    assert template["approved_records"] == 0
    assert template["reviewer_name"] is None
    assert all(record["human_decision"] is None for record in template["records"])
    assert all(len(record["proposed_clause_nodes"]) == 1 for record in template["records"])


def test_blank_remediation_template_is_not_a_human_approval(
    built: tuple[dict[str, Any], dict[str, Any]]
) -> None:
    _, template = built
    with pytest.raises(ValueError, match="remediation_reviewer"):
        p3h_review.validate_remediation_review(template)


def test_completed_remediation_contract_is_machine_checkable(
    built: tuple[dict[str, Any], dict[str, Any]]
) -> None:
    _, frozen = built
    completed = copy.deepcopy(frozen)
    completed["reviewer_name"] = "Human Reviewer"
    completed["reviewed_at"] = "2026-09-14T17:00:00+08:00"
    for record in completed["records"]:
        record["human_decision"] = "approve"
        record["human_reason"] = "Reviewed against the proposed replacement span."
        record["checks"] = {key: True for key in record["checks"]}
    completed["approved_records"] = 5
    result = p3h_review.validate_remediation_review(completed)
    assert result == {
        "status": "complete",
        "records": 5,
        "decisions": {"approve": 5},
        "all_approved": True,
    }


def test_wrong_base_hash_is_rejected(base: dict[str, Any], amendment: dict[str, Any]) -> None:
    forged = copy.deepcopy(amendment)
    forged["base_gold_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="amendment_base_binding"):
        p3h_review.apply_amendment(base, forged)


def test_missing_remove_item_is_rejected(base: dict[str, Any], amendment: dict[str, Any]) -> None:
    forged = copy.deepcopy(amendment)
    forged["operations"][0]["remove_item_ids"] = ["missing"]
    with pytest.raises(ValueError, match="amendment_remove_item"):
        p3h_review.apply_amendment(base, forged)


def test_dangling_relation_is_rejected(base: dict[str, Any], amendment: dict[str, Any]) -> None:
    forged = copy.deepcopy(amendment)
    forged["operations"][1]["add_relations"][0]["to_item"] = "missing"
    with pytest.raises(ValueError, match="amendment_relation_endpoint"):
        p3h_review.apply_amendment(base, forged)


def test_build_uses_no_network_or_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("external access forbidden")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    try:
        import psycopg
    except ImportError:
        pass
    else:
        monkeypatch.setattr(psycopg, "connect", forbidden)
    inventory, template = p3h_review.build()
    assert inventory["model_calls"] == 0
    assert inventory["postgres_access"] == 0
    assert inventory["holdout_source_paths_opened"] == 0
    assert inventory["p4_budget_authorized"] is False
    assert template["approved_records"] == 0


def test_write_once_refuses_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "p3h.json"
    p3h_review.write_once(output, {"first": True})
    with pytest.raises(FileExistsError):
        p3h_review.write_once(output, {"second": True})
