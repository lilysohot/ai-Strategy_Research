from __future__ import annotations

import copy
import inspect
import socket
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from typing import Any

import p3_replay_review as p3
import p3s_review
import p3s_scope_provider as provider
import pytest

from plugins.corpus._r2_plan import Packet, Source, source_binding


def synthetic(text: str, *, kind: str = "prose", status: str = "available") -> Source:
    return Source("run-1", "source-1", "parse-1", (Packet("packet-1", "line:1", text, kind, status),))


@pytest.fixture(scope="module")
def built() -> tuple[dict[str, Any], dict[str, Any]]:
    return p3s_review.build()


def test_frozen_parent_and_scope_pins() -> None:
    p3s_review.verify_pins()


def test_interface_is_small_and_pure() -> None:
    assert tuple(inspect.signature(provider.prepare_scopes).parameters) == (
        "source",
        "expected_binding",
        "limits",
    )
    assert tuple(inspect.signature(provider.verify_scope_plan).parameters) == (
        "source",
        "expected_binding",
        "plan",
        "expected_plan_id",
    )


def test_partition_is_contiguous_and_complete() -> None:
    source = synthetic("第一句。\n第二句较长，但是仍可定位。\n\n专家：第三句。")
    plan = provider.prepare_scopes(source, source_binding(source), replace(provider.DEFAULT_LIMITS, max_scope_chars=12))
    ordered = sorted(plan.scopes, key=lambda scope: scope.start)
    assert ordered[0].start == 0
    assert ordered[-1].end == len(source.packets[0].text)
    assert all(left.end == right.start for left, right in pairwise(ordered))
    assert plan.unresolved_packets == 0


def test_no_safe_break_is_explicit_unresolved_not_truncation() -> None:
    source = synthetic("甲" * 100)
    limits = replace(provider.DEFAULT_LIMITS, max_scope_chars=20)
    plan = provider.prepare_scopes(source, source_binding(source), limits)
    assert plan.unresolved_packets == 1
    assert plan.scopes[0].state == "unresolved"
    assert plan.scopes[0].reason == "no_safe_break_within_scope_capacity"
    assert plan.scopes[0].start == 0 and plan.scopes[0].end == 100


def test_scope_count_capacity_is_explicit() -> None:
    source = synthetic("一句。二句。三句。四句。")
    limits = replace(provider.DEFAULT_LIMITS, max_scope_chars=3, max_scopes_per_packet=2)
    plan = provider.prepare_scopes(source, source_binding(source), limits)
    assert plan.unresolved_packets == 1
    assert plan.scopes[0].reason == "scope_count_capacity"
    assert plan.scopes[0].end == len(source.packets[0].text)


def test_table_row_is_typed_and_not_relabelled_as_prose() -> None:
    source = synthetic("收入 | 2026E: 10 | 2027E: 12", kind="table")
    plan = provider.prepare_scopes(source, source_binding(source))
    assert plan.planned_packets == 1
    assert [(scope.kind, scope.state) for scope in plan.scopes] == [("table_row", "candidate")]


def test_table_cell_capacity_is_explicit() -> None:
    source = synthetic(" | ".join(str(index) for index in range(5)), kind="table")
    limits = replace(provider.DEFAULT_LIMITS, max_table_cells=3)
    plan = provider.prepare_scopes(source, source_binding(source), limits)
    assert plan.unresolved_packets == 1
    assert plan.scopes[0].reason == "table_cell_capacity"


def test_unavailable_packet_is_explicit_unresolved() -> None:
    source = synthetic("source unavailable", status="unavailable")
    plan = provider.prepare_scopes(source, source_binding(source))
    assert plan.unresolved_packets == 1
    assert plan.scopes[0].reason == "packet_unavailable_or_blank"


def test_unknown_packet_kind_is_explicit_unresolved() -> None:
    source = synthetic("image payload", kind="image")
    plan = provider.prepare_scopes(source, source_binding(source))
    assert plan.unresolved_packets == 1
    assert plan.scopes[0].reason == "unsupported_packet_kind"


def test_wrong_source_binding_is_rejected() -> None:
    source = synthetic("需求改善。")
    with pytest.raises(ValueError, match="source_binding"):
        provider.prepare_scopes(source, "wrong")


def test_plan_drift_is_rejected() -> None:
    source = synthetic("需求改善。风险仍在。")
    first = provider.prepare_scopes(source, source_binding(source))
    second = provider.prepare_scopes(
        source,
        source_binding(source),
        replace(provider.DEFAULT_LIMITS, max_scope_chars=10),
    )
    forged = replace(first, plan_id=second.plan_id)
    with pytest.raises(ValueError, match="plan_drift"):
        provider.verify_scope_plan(source, source_binding(source), forged, second.plan_id)


def test_speaker_turns_have_context_edges() -> None:
    source = synthetic("投资者：问题一？\n\n专家：回答一。\n\n投资者：问题二？")
    plan = provider.prepare_scopes(
        source,
        source_binding(source),
        replace(provider.DEFAULT_LIMITS, max_scope_chars=14),
    )
    assert sum(scope.kind == "turn" for scope in plan.scopes) >= 2
    assert all(edge.relation == "next_scope" for edge in plan.edges)


@pytest.mark.parametrize("sample_id", p3.DEV_IDS)
def test_each_development_source_has_complete_coverage(
    sample_id: str, built: tuple[dict[str, Any], dict[str, Any]]
) -> None:
    inventory, _ = built
    row = next(row for row in inventory["sources"] if row["sample_id"] == sample_id)
    assert row["planned_packets"] == row["packets"]
    assert row["unresolved_packets"] == 0
    assert row["source_chars"] == row["covered_chars"]
    assert row["source_non_whitespace_chars"] == row["covered_non_whitespace_chars"]


def test_all_four_sources_and_fourteen_packets_are_accounted(
    built: tuple[dict[str, Any], dict[str, Any]]
) -> None:
    inventory, _ = built
    assert len(inventory["sources"]) == 4
    assert inventory["totals"]["packets"] == 14
    assert inventory["totals"]["unresolved_packets"] == 0
    assert inventory["totals"]["unresolved_scopes"] == 0


def test_table_scopes_are_preserved_outside_clause_lattice(
    built: tuple[dict[str, Any], dict[str, Any]]
) -> None:
    inventory, _ = built
    assert inventory["totals"]["table_scopes"] == 7
    assert inventory["totals"]["table_scopes_sent_to_clause_lattice"] == 0


def test_every_prose_scope_fits_the_frozen_clause_lattice(
    built: tuple[dict[str, Any], dict[str, Any]]
) -> None:
    inventory, _ = built
    assert inventory["totals"]["clause_lattice_capacity_or_kind_failures"] == 0
    assert all(
        set(row["clause_lattice_root_statuses"]) <= {"planned"}
        for row in inventory["sources"]
    )


def test_all_targets_and_relation_endpoints_have_scope_references(
    built: tuple[dict[str, Any], dict[str, Any]]
) -> None:
    inventory, _ = built
    totals = inventory["totals"]
    assert totals["items_in_unique_generated_scope"] == 35
    assert totals["positive_relation_endpoints_referencable"] == 17
    assert totals["negative_relation_endpoints_referencable"] == 8


def test_human_template_is_complete_and_unsigned(
    built: tuple[dict[str, Any], dict[str, Any]]
) -> None:
    _, template = built
    assert len(template["records"]) == 35
    assert template["approved_records"] == 0
    assert template["reviewer_name"] is None
    assert all(record["human_decision"] is None for record in template["records"])
    assert all(set(record["checks"].values()) == {None} for record in template["records"])


def test_blank_human_template_cannot_be_validated(
    built: tuple[dict[str, Any], dict[str, Any]]
) -> None:
    _, template = built
    with pytest.raises(ValueError, match="human_reviewer"):
        p3s_review.validate_human_review(template)


def test_completed_human_review_contract_is_machine_checkable(
    built: tuple[dict[str, Any], dict[str, Any]]
) -> None:
    _, frozen_template = built
    completed = copy.deepcopy(frozen_template)
    completed["reviewer_name"] = "Human Reviewer"
    completed["reviewed_at"] = "2026-09-14T12:00:00+08:00"
    for record in completed["records"]:
        record["human_decision"] = "approve"
        record["human_reason"] = "Reviewed against the quoted source span."
        record["checks"] = {key: True for key in record["checks"]}
    completed["approved_records"] = len(completed["records"])
    result = p3s_review.validate_human_review(completed)
    assert result["status"] == "complete"
    assert result["records"] == 35
    assert result["all_approved"] is True


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
    inventory, template = p3s_review.build()
    assert inventory["model_calls"] == 0
    assert inventory["postgres_access"] == 0
    assert inventory["holdout_source_paths_opened"] == 0
    assert inventory["p4_budget_authorized"] is False
    assert template["approved_records"] == 0


def test_write_once_refuses_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "scope.json"
    p3s_review.write_once(output, {"first": True})
    with pytest.raises(FileExistsError):
        p3s_review.write_once(output, {"second": True})


@pytest.mark.parametrize("field", ("max_scope_chars", "max_total_scopes"))
def test_non_positive_limits_are_rejected(field: str) -> None:
    source = synthetic("需求改善。")
    limits = replace(provider.DEFAULT_LIMITS, **{field: 0})
    with pytest.raises(ValueError, match="limits"):
        provider.prepare_scopes(source, source_binding(source), limits)
