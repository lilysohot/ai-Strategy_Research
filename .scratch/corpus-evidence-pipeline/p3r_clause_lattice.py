"""Zero-model bounded clause lattice prototype for the P3-R development review.

The module is pure computation.  Its interface accepts only source coordinates and
hard limits; it cannot see gold labels, call a model, or approve atomicity.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, replace
from itertools import pairwise

from plugins.corpus._r2_plan import Scope, Source, digest, source_binding

VERSION = "r2-p3r-bounded-clause-lattice-1"


@dataclass(frozen=True)
class ClauseLimits:
    max_roots: int = 32
    max_root_chars: int = 4096
    max_total_chars: int = 32768
    max_segments_per_root: int = 64
    max_window_segments: int = 8
    max_nodes_per_root: int = 384
    max_edges_per_root: int = 768


DEFAULT_LIMITS = ClauseLimits()


@dataclass(frozen=True)
class LatticeSpan:
    span_id: str
    source_rev: str
    parse_rev: str
    packet_id: str
    locator: str
    start: int
    end: int
    text_sha256: str


@dataclass(frozen=True)
class ClauseNode:
    node_id: str
    root_id: str
    span: LatticeSpan
    role: str  # whole | clause | alternative | condition | attribution
    review_state: str = "proposed_not_approved"


@dataclass(frozen=True)
class ClauseEdge:
    edge_id: str
    root_id: str
    relation: str  # part_of | next | qualifies | attributes
    from_node_id: str
    to_node_id: str
    review_state: str = "proposed_not_approved"


@dataclass(frozen=True)
class RootLattice:
    root_id: str
    support: LatticeSpan
    status: str  # planned | unresolved_capacity | unsupported_packet
    reason: str
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    required_segments: int
    required_nodes: int
    required_edges: int


@dataclass(frozen=True)
class ClausePlan:
    plan_id: str
    version: str
    source_binding: str
    scopes: tuple[Scope, ...]
    limits: ClauseLimits
    roots: tuple[RootLattice, ...]
    nodes: tuple[ClauseNode, ...]
    edges: tuple[ClauseEdge, ...]
    selected_chars: int
    planned_roots: int
    unresolved_roots: int
    semantic_coverage: str = "not_evaluated"
    atomicity: str = "not_verified"
    calls_authorized: int = 0


_CONDITION = re.compile(r"(?:如果|若|只要|除非|否则)")
_ATTRIBUTION = re.compile(r"(?:我们认为|我认为|他说|她说|其表示|表示|指出|提到)")
_CONNECTOR = re.compile(
    r"(?:但是|但(?=[^a-zA-Z])|而且|并且|同时|以及|和(?=[“\"])|尤其|只是|那么|"
    r"\band\b|\bbut\b|\badding\b|\bthis\b|\bthe\s+CEO\b)",
    re.IGNORECASE,
)


def _span(source: Source, packet_id: str, locator: str, start: int, end: int) -> LatticeSpan:
    packet = next(packet for packet in source.packets if packet.packet_id == packet_id)
    text_hash = hashlib.sha256(packet.text[start:end].encode()).hexdigest()
    values = source.source_rev, source.parse_rev, packet_id, locator, start, end, text_hash
    return LatticeSpan(digest(values), *values)


def resolve_span(source: Source, span: LatticeSpan) -> str:
    """Resolve and verify one generated span against its bound source."""
    packets = [packet for packet in source.packets if packet.packet_id == span.packet_id]
    if len(packets) != 1:
        raise ValueError("packet_identity")
    packet = packets[0]
    if type(span.start) is not int or type(span.end) is not int:
        raise ValueError("coordinate_type")
    if not 0 <= span.start < span.end <= len(packet.text):
        raise ValueError("coordinate_range")
    if span != _span(source, packet.packet_id, packet.locator, span.start, span.end):
        raise ValueError("span_binding")
    return packet.text[span.start : span.end]


def _trim(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if start < end else None


def _punctuation_breaks(text: str) -> tuple[set[int], set[int]]:
    strong = {0, len(text)}
    weak = {0, len(text)}
    for match in re.finditer(r"[。！？?!；;]+|\n+", text):
        strong.add(match.end())
        weak.add(match.end())
    for index, char in enumerate(text):
        if char not in "，、,":
            continue
        if (
            char == ","
            and index
            and index + 1 < len(text)
            and text[index - 1].isdigit()
            and text[index + 1].isdigit()
        ):
            continue
        weak.add(index + 1)
    return strong, weak


def _marker_breaks(text: str) -> tuple[set[int], list[tuple[int, int, str]]]:
    positions: set[int] = set()
    markers: list[tuple[int, int, str]] = []
    for pattern, role in ((_CONDITION, "condition"), (_ATTRIBUTION, "attribution")):
        for match in pattern.finditer(text):
            positions.update((match.start(), match.end()))
            markers.append((match.start(), match.end(), role))
    for match in _CONNECTOR.finditer(text):
        positions.add(match.start())
    for line in re.finditer(r"(?:^|\n)([^\s：:\n]{1,16}[：:])", text):
        start, end = line.span(1)
        positions.update((start, end))
        markers.append((start, end, "attribution"))
    return positions, markers


def _parts(text: str, breaks: set[int]) -> list[tuple[int, int]]:
    ordered = sorted(breaks)
    result = []
    for start, end in pairwise(ordered):
        trimmed = _trim(text, start, end)
        if trimmed is not None:
            result.append(trimmed)
    return result


def _candidate_intervals(
    text: str, limits: ClauseLimits
) -> tuple[list[tuple[int, int]], list[tuple[int, int]], list[tuple[int, int, str]]]:
    strong, weak = _punctuation_breaks(text)
    marker_positions, markers = _marker_breaks(text)
    base = _parts(text, weak | marker_positions)
    intervals = {(0, len(text))}
    intervals.update(_parts(text, strong))
    intervals.update(_parts(text, weak))
    intervals.update((start, end) for start, end, _ in markers)
    for start_index in range(len(base)):
        upper = min(len(base), start_index + limits.max_window_segments)
        for end_index in range(start_index, upper):
            trimmed = _trim(text, base[start_index][0], base[end_index][1])
            if trimmed is not None:
                intervals.add(trimmed)
    return sorted(intervals), base, markers


def _role(text: str, interval: tuple[int, int], root_end: int, markers: list[tuple[int, int, str]]) -> str:
    if interval == (0, root_end):
        return "whole"
    exact_marker = next((kind for start, end, kind in markers if interval == (start, end)), None)
    if exact_marker is not None:
        return exact_marker
    value = text[interval[0] : interval[1]].lstrip()
    if _CONDITION.match(value):
        return "condition"
    return "clause" if not re.search(r"[，,、。！？?!；;\n]", value[:-1]) else "alternative"


def _make_edge(root_id: str, relation: str, source: str, target: str) -> ClauseEdge:
    edge_id = digest([VERSION, root_id, relation, source, target])
    return ClauseEdge(edge_id, root_id, relation, source, target)


def _root_lattice(
    source: Source,
    packet_id: str,
    locator: str,
    root_start: int,
    root_end: int,
    limits: ClauseLimits,
) -> tuple[RootLattice, list[ClauseNode], list[ClauseEdge]]:
    packet = next(packet for packet in source.packets if packet.packet_id == packet_id)
    support = _span(source, packet_id, locator, root_start, root_end)
    root_id = digest([VERSION, source_binding(source), asdict(support), asdict(limits)])
    text = packet.text[root_start:root_end]
    intervals, base, markers = _candidate_intervals(text, limits)
    whole_span = _span(source, packet_id, locator, root_start, root_end)
    whole_id = digest([root_id, asdict(whole_span), "whole"])
    whole = ClauseNode(whole_id, root_id, whole_span, "whole")
    if packet.kind != "prose" or packet.status != "available":
        result = RootLattice(
            root_id,
            support,
            "unsupported_packet",
            "packet_not_available_prose",
            (whole_id,),
            (),
            len(base),
            len(intervals),
            0,
        )
        return result, [whole], []
    if len(base) > limits.max_segments_per_root or len(intervals) > limits.max_nodes_per_root:
        result = RootLattice(
            root_id,
            support,
            "unresolved_capacity",
            "segment_or_node_capacity",
            (whole_id,),
            (),
            len(base),
            len(intervals),
            0,
        )
        return result, [whole], []

    nodes = []
    by_interval: dict[tuple[int, int], ClauseNode] = {}
    for interval in intervals:
        span = _span(
            source,
            packet_id,
            locator,
            root_start + interval[0],
            root_start + interval[1],
        )
        role = _role(text, interval, len(text), markers)
        node = ClauseNode(digest([root_id, asdict(span), role]), root_id, span, role)
        nodes.append(node)
        by_interval[interval] = node

    edges: dict[str, ClauseEdge] = {}
    for interval in base:
        node = by_interval[interval]
        if node.node_id != whole_id:
            edge = _make_edge(root_id, "part_of", node.node_id, whole_id)
            edges[edge.edge_id] = edge
    for left, right in pairwise(base):
        edge = _make_edge(root_id, "next", by_interval[left].node_id, by_interval[right].node_id)
        edges[edge.edge_id] = edge
    for start, end, kind in markers:
        marker = by_interval.get((start, end))
        if marker is None:
            continue
        following = next((interval for interval in base if interval[0] >= end), None)
        if following is None:
            continue
        relation = "qualifies" if kind == "condition" else "attributes"
        edge = _make_edge(root_id, relation, marker.node_id, by_interval[following].node_id)
        edges[edge.edge_id] = edge
    edge_values = list(edges.values())
    if len(edge_values) > limits.max_edges_per_root:
        result = RootLattice(
            root_id,
            support,
            "unresolved_capacity",
            "edge_capacity",
            (whole_id,),
            (),
            len(base),
            len(nodes),
            len(edge_values),
        )
        return result, [whole], []
    result = RootLattice(
        root_id,
        support,
        "planned",
        "finite_alternatives_not_atomicity_certification",
        tuple(node.node_id for node in nodes),
        tuple(edge.edge_id for edge in edge_values),
        len(base),
        len(nodes),
        len(edge_values),
    )
    return result, nodes, edge_values


def prepare_lattice(
    source: Source,
    expected_binding: str,
    scopes: tuple[Scope, ...],
    limits: ClauseLimits = DEFAULT_LIMITS,
) -> ClausePlan:
    """Return a finite locator-preserving lattice without semantic certification."""
    if source_binding(source) != expected_binding:
        raise ValueError("source_binding")
    if not all((source.evidence_run_id, source.source_rev, source.parse_rev)):
        raise ValueError("source_identity")
    if any(type(value) is not int or value <= 0 for value in asdict(limits).values()):
        raise ValueError("limits")
    if not scopes or len(scopes) > limits.max_roots:
        raise ValueError("root_capacity")
    packets = {packet.packet_id: packet for packet in source.packets}
    if len(packets) != len(source.packets):
        raise ValueError("packet_identity")
    order = {packet.packet_id: index for index, packet in enumerate(source.packets)}
    last_key = (-1, -1)
    previous_end: dict[str, int] = {}
    selected_chars = 0
    for scope in scopes:
        packet = packets.get(scope.packet_id)
        if packet is None or not packet.packet_id or not packet.locator:
            raise ValueError("packet_identity")
        if type(scope.start) is not int or type(scope.end) is not int:
            raise ValueError("coordinate_type")
        if not 0 <= scope.start < scope.end <= len(packet.text):
            raise ValueError("coordinate_range")
        key = order[scope.packet_id], scope.start
        if key <= last_key or scope.start < previous_end.get(scope.packet_id, 0):
            raise ValueError("scope_overlap_or_order")
        if scope.end - scope.start > limits.max_root_chars:
            raise ValueError("root_chars_capacity")
        last_key = key
        previous_end[scope.packet_id] = scope.end
        selected_chars += scope.end - scope.start
    if selected_chars > limits.max_total_chars:
        raise ValueError("total_chars_capacity")

    roots: list[RootLattice] = []
    nodes: list[ClauseNode] = []
    edges: list[ClauseEdge] = []
    for scope in scopes:
        packet = packets[scope.packet_id]
        root, root_nodes, root_edges = _root_lattice(
            source,
            packet.packet_id,
            packet.locator,
            scope.start,
            scope.end,
            limits,
        )
        roots.append(root)
        nodes.extend(root_nodes)
        edges.extend(root_edges)
    result = ClausePlan(
        "",
        VERSION,
        expected_binding,
        scopes,
        limits,
        tuple(roots),
        tuple(nodes),
        tuple(edges),
        selected_chars,
        sum(root.status == "planned" for root in roots),
        sum(root.status != "planned" for root in roots),
    )
    return replace(result, plan_id=digest(asdict(result)))


def verify_lattice(
    source: Source, expected_binding: str, plan: ClausePlan, expected_plan_id: str
) -> None:
    """Verify all identities by reconstructing through the same small interface."""
    if plan.plan_id != expected_plan_id:
        raise ValueError("plan_binding")
    if plan != prepare_lattice(source, expected_binding, plan.scopes, plan.limits):
        raise ValueError("plan_drift")
