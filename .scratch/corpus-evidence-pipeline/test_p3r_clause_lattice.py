from __future__ import annotations

import inspect
import socket
from dataclasses import replace
from pathlib import Path

import p3_replay_review as p3
import p3r_clause_lattice as lattice
import p3r_review
import pytest

from plugins.corpus._r2_plan import Packet, Scope, Source, source_binding


def synthetic(text: str) -> tuple[Source, tuple[Scope, ...]]:
    packet = Packet("packet-1", "line:1", text)
    source = Source("run-1", "source-1", "parse-1", (packet,))
    return source, (Scope(packet.packet_id, 0, len(text)),)


def test_frozen_scope_and_parent_pins() -> None:
    p3r_review.verify_pins()


def test_external_interface_is_small_and_source_only() -> None:
    parameters = tuple(inspect.signature(lattice.prepare_lattice).parameters)
    assert parameters == ("source", "expected_binding", "scopes", "limits")
    assert tuple(inspect.signature(p3r_review.projected_source).parameters) == ("scope_header",)
    assert set(p3r_review.SOURCE_KEYS).isdisjoint(
        {"items", "relations", "negative_relations", "excluded"}
    )


@pytest.mark.parametrize("scope_id", p3.MICRO_IDS)
def test_each_frozen_micro_scope_is_deterministic_and_planned(scope_id: str) -> None:
    _, scopes = p3.load_inputs()
    frozen = next(scope for scope in scopes if scope["scope_id"] == scope_id)
    source, selected = p3r_review.projected_source(p3r_review.source_only_view(frozen))
    first = lattice.prepare_lattice(source, source_binding(source), selected)
    second = lattice.prepare_lattice(source, source_binding(source), selected)
    assert first == second
    assert first.planned_roots == 1
    assert first.unresolved_roots == 0
    assert first.calls_authorized == 0
    lattice.verify_lattice(source, source_binding(source), first, first.plan_id)


def test_every_node_resolves_and_whole_span_is_preserved() -> None:
    source, selected = synthetic("只要需求改善，行业仍有投资价值。")
    plan = lattice.prepare_lattice(source, source_binding(source), selected)
    assert any(node.role == "whole" for node in plan.nodes)
    assert {lattice.resolve_span(source, node.span) for node in plan.nodes}
    assert next(node for node in plan.nodes if node.role == "whole").span.start == 0
    assert next(node for node in plan.nodes if node.role == "whole").span.end == len(
        source.packets[0].text
    )


def test_wrong_source_binding_is_rejected() -> None:
    source, selected = synthetic("需求改善。")
    with pytest.raises(ValueError, match="source_binding"):
        lattice.prepare_lattice(source, "wrong", selected)


def test_forged_span_is_rejected() -> None:
    source, selected = synthetic("需求改善。")
    plan = lattice.prepare_lattice(source, source_binding(source), selected)
    forged = replace(plan.nodes[0].span, text_sha256="0" * 64)
    with pytest.raises(ValueError, match="span_binding"):
        lattice.resolve_span(source, forged)


def test_segment_capacity_is_explicit_and_preserves_only_whole_span() -> None:
    source, selected = synthetic("一，二，三，四，五，六。")
    limits = replace(lattice.DEFAULT_LIMITS, max_segments_per_root=3)
    plan = lattice.prepare_lattice(source, source_binding(source), selected, limits)
    root = plan.roots[0]
    assert root.status == "unresolved_capacity"
    assert root.reason == "segment_or_node_capacity"
    assert root.required_segments > limits.max_segments_per_root
    assert len(root.node_ids) == 1
    assert lattice.resolve_span(source, plan.nodes[0].span) == source.packets[0].text


def test_node_capacity_is_explicit_instead_of_truncated() -> None:
    source, selected = synthetic("甲，乙，丙。")
    limits = replace(lattice.DEFAULT_LIMITS, max_nodes_per_root=2)
    plan = lattice.prepare_lattice(source, source_binding(source), selected, limits)
    root = plan.roots[0]
    assert root.status == "unresolved_capacity"
    assert root.required_nodes > limits.max_nodes_per_root
    assert len(plan.nodes) == 1


def test_condition_span_has_explicit_qualifier_edge() -> None:
    source, selected = synthetic("只要未来供需改善，行业仍有投资价值。")
    plan = lattice.prepare_lattice(source, source_binding(source), selected)
    assert any(node.role == "condition" for node in plan.nodes)
    assert any(edge.relation == "qualifies" for edge in plan.edges)


def test_attribution_span_has_explicit_edge() -> None:
    source, selected = synthetic("专家：他说工艺占大头，但设备也不可缺少。")
    plan = lattice.prepare_lattice(source, source_binding(source), selected)
    assert sum(node.role == "attribution" for node in plan.nodes) >= 2
    assert any(edge.relation == "attributes" for edge in plan.edges)


def test_numeric_comma_is_not_used_as_a_clause_break() -> None:
    source, selected = synthetic("I added 10,000 shares, and sold 100 calls.")
    plan = lattice.prepare_lattice(source, source_binding(source), selected)
    texts = {lattice.resolve_span(source, node.span) for node in plan.nodes}
    assert "I added 10,000 shares," in texts
    assert "000 shares," not in texts


def test_fixed_development_targets_have_distinct_unique_minimum_nodes() -> None:
    _, scopes = p3.load_inputs()
    summaries, _ = p3r_review.micro_review(scopes)
    assert sum(row["mapping_statuses"].get("unique_minimum", 0) for row in summaries) == 35
    assert sum(row["distinct_mapped_nodes"] for row in summaries) == 35


def test_all_frozen_relation_endpoints_remain_referencable() -> None:
    _, scopes = p3.load_inputs()
    summaries, _ = p3r_review.micro_review(scopes)
    assert sum(row["positive_relation_endpoints_referencable"] for row in summaries) == 17
    assert sum(row["negative_relation_endpoints_referencable"] for row in summaries) == 8


def test_review_queue_never_approves_agent_proposals() -> None:
    _, scopes = p3.load_inputs()
    _, queue = p3r_review.micro_review(scopes)
    assert len(queue) == 35
    assert {row["review_status"] for row in queue} == {"proposed_not_approved"}


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
    inventory, queue = p3r_review.build()
    assert inventory["model_calls"] == 0
    assert inventory["postgres_access"] == 0
    assert inventory["holdout_source_paths_opened"] == 0
    assert inventory["p4_budget_authorized"] is False
    assert queue["approved_records"] == 0


def test_write_once_refuses_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "inventory.json"
    p3r_review.write_once(output, {"first": True})
    with pytest.raises(FileExistsError):
        p3r_review.write_once(output, {"second": True})


@pytest.mark.parametrize("field", ("max_window_segments", "max_edges_per_root"))
def test_non_positive_limits_are_rejected(field: str) -> None:
    source, selected = synthetic("需求改善。")
    limits = replace(lattice.DEFAULT_LIMITS, **{field: 0})
    with pytest.raises(ValueError, match="limits"):
        lattice.prepare_lattice(source, source_binding(source), selected, limits)


def test_plan_identity_covers_limits() -> None:
    source, selected = synthetic("需求改善，但是风险仍在。")
    first = lattice.prepare_lattice(source, source_binding(source), selected)
    limits = replace(lattice.DEFAULT_LIMITS, max_window_segments=2)
    second = lattice.prepare_lattice(source, source_binding(source), selected, limits)
    assert first.plan_id != second.plan_id
    forged = replace(first, plan_id=second.plan_id)
    with pytest.raises(ValueError, match="plan_drift"):
        lattice.verify_lattice(source, source_binding(source), forged, second.plan_id)
