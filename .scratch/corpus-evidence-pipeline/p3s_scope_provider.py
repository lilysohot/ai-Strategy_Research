"""Pure, finite scope-provider prototype for the P3-S development review."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace
from itertools import pairwise

from plugins.corpus._r2_plan import Source, digest, source_binding

VERSION = "r2-p3s-scope-provider-1"


@dataclass(frozen=True)
class ScopeLimits:
    max_packets: int = 64
    max_scope_chars: int = 320
    max_scopes_per_packet: int = 64
    max_total_scopes: int = 256
    max_context_edges: int = 512
    max_table_cells: int = 32


DEFAULT_LIMITS = ScopeLimits()


@dataclass(frozen=True)
class ResearchScope:
    scope_id: str
    packet_id: str
    locator: str
    start: int
    end: int
    kind: str  # prose | turn | heading_context | table_row | unresolved
    state: str  # candidate | unresolved
    reason: str


@dataclass(frozen=True)
class ScopeEdge:
    edge_id: str
    relation: str  # next_scope
    from_scope_id: str
    to_scope_id: str


@dataclass(frozen=True)
class PacketScopeResult:
    packet_id: str
    status: str  # planned | unresolved
    reason: str
    scope_ids: tuple[str, ...]
    source_chars: int
    covered_chars: int
    non_whitespace_chars: int
    covered_non_whitespace_chars: int


@dataclass(frozen=True)
class ScopePlan:
    plan_id: str
    version: str
    source_binding: str
    limits: ScopeLimits
    packets: tuple[PacketScopeResult, ...]
    scopes: tuple[ResearchScope, ...]
    edges: tuple[ScopeEdge, ...]
    planned_packets: int
    unresolved_packets: int
    candidate_scopes: int
    unresolved_scopes: int
    calls_authorized: int = 0


_SPEAKER = re.compile(r"(?:^|\n)[^\s：:\n]{1,20}[：:]")
_HEADING = re.compile(
    r"^(?:[一二三四五六七八九十]+、|\d+[.、]|事项[：:]|评论[：:]|风险提示[：:]|投资建议[：:])"
)


def _punctuation_positions(text: str) -> tuple[set[int], set[int]]:
    strong = {0, len(text)}
    weak = {0, len(text)}
    for match in re.finditer(r"[。！？?!；;]+|\n{2,}", text):
        strong.add(match.end())
        weak.add(match.end())
    for match in _SPEAKER.finditer(text):
        start = match.start()
        if text[start : start + 1] == "\n":
            start += 1
        strong.add(start)
    for index, char in enumerate(text):
        if char == "\n":
            weak.add(index + 1)
        elif char in "，、,":
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


def _partition(text: str, limits: ScopeLimits) -> tuple[list[tuple[int, int]], str | None]:
    strong, weak = _punctuation_positions(text)
    result = []
    start = 0
    while start < len(text):
        if len(text) - start <= limits.max_scope_chars:
            result.append((start, len(text)))
            break
        ceiling = start + limits.max_scope_chars
        strong_choices = [position for position in strong if start < position <= ceiling]
        weak_choices = [position for position in weak if start < position <= ceiling]
        if strong_choices:
            end = max(strong_choices)
        elif weak_choices:
            end = max(weak_choices)
        else:
            return [], "no_safe_break_within_scope_capacity"
        result.append((start, end))
        start = end
    if len(result) > limits.max_scopes_per_packet:
        return [], "scope_count_capacity"
    return result, None


def _kind(text: str) -> str:
    stripped = text.strip()
    if _SPEAKER.match(stripped):
        return "turn"
    first_line = stripped.splitlines()[0] if stripped else ""
    if len(first_line) <= 80 and _HEADING.match(first_line):
        return "heading_context"
    return "prose"


def _scope(
    source: Source,
    packet_id: str,
    locator: str,
    start: int,
    end: int,
    kind: str,
    state: str,
    reason: str,
    limits: ScopeLimits,
) -> ResearchScope:
    scope_id = digest(
        [
            VERSION,
            source_binding(source),
            packet_id,
            locator,
            start,
            end,
            kind,
            state,
            reason,
            asdict(limits),
        ]
    )
    return ResearchScope(scope_id, packet_id, locator, start, end, kind, state, reason)


def _coverage(text: str, scopes: list[ResearchScope]) -> tuple[int, int]:
    covered = [False] * len(text)
    for scope in scopes:
        for index in range(scope.start, scope.end):
            if covered[index]:
                raise ValueError("scope_overlap")
            covered[index] = True
    covered_chars = sum(covered)
    covered_non_whitespace = sum(
        flag and not char.isspace() for flag, char in zip(covered, text, strict=True)
    )
    return covered_chars, covered_non_whitespace


def _edge(left: ResearchScope, right: ResearchScope) -> ScopeEdge:
    edge_id = digest([VERSION, "next_scope", left.scope_id, right.scope_id])
    return ScopeEdge(edge_id, "next_scope", left.scope_id, right.scope_id)


def prepare_scopes(
    source: Source,
    expected_binding: str,
    limits: ScopeLimits = DEFAULT_LIMITS,
) -> ScopePlan:
    """Partition every packet or return an explicit packet-level failure."""
    if source_binding(source) != expected_binding:
        raise ValueError("source_binding")
    if not all((source.evidence_run_id, source.source_rev, source.parse_rev)):
        raise ValueError("source_identity")
    if any(type(value) is not int or value <= 0 for value in asdict(limits).values()):
        raise ValueError("limits")
    if not source.packets or len(source.packets) > limits.max_packets:
        raise ValueError("packet_capacity")
    if len({packet.packet_id for packet in source.packets}) != len(source.packets):
        raise ValueError("packet_identity")

    packet_results = []
    all_scopes: list[ResearchScope] = []
    all_edges: list[ScopeEdge] = []
    for packet in source.packets:
        if not packet.packet_id or not packet.locator:
            raise ValueError("packet_identity")
        packet_scopes: list[ResearchScope]
        failure = None
        if packet.status != "available" or not packet.text:
            failure = "packet_unavailable_or_blank"
            packet_scopes = [
                _scope(
                    source,
                    packet.packet_id,
                    packet.locator,
                    0,
                    max(1, len(packet.text)),
                    "unresolved",
                    "unresolved",
                    failure,
                    limits,
                )
            ] if packet.text else []
        elif packet.kind == "table":
            cells = packet.text.count("|") + 1
            if cells > limits.max_table_cells:
                failure = "table_cell_capacity"
                kind, state, reason = "unresolved", "unresolved", failure
            else:
                kind, state, reason = "table_row", "candidate", "structural_table_row"
            packet_scopes = [
                _scope(
                    source,
                    packet.packet_id,
                    packet.locator,
                    0,
                    len(packet.text),
                    kind,
                    state,
                    reason,
                    limits,
                )
            ]
        elif packet.kind == "prose":
            intervals, failure = _partition(packet.text, limits)
            if failure:
                packet_scopes = [
                    _scope(
                        source,
                        packet.packet_id,
                        packet.locator,
                        0,
                        len(packet.text),
                        "unresolved",
                        "unresolved",
                        failure,
                        limits,
                    )
                ]
            else:
                packet_scopes = [
                    _scope(
                        source,
                        packet.packet_id,
                        packet.locator,
                        start,
                        end,
                        _kind(packet.text[start:end]),
                        "candidate",
                        "bounded_structural_scope",
                        limits,
                    )
                    for start, end in intervals
                ]
        else:
            failure = "unsupported_packet_kind"
            packet_scopes = [
                _scope(
                    source,
                    packet.packet_id,
                    packet.locator,
                    0,
                    len(packet.text),
                    "unresolved",
                    "unresolved",
                    failure,
                    limits,
                )
            ]

        covered_chars, covered_non_whitespace = _coverage(packet.text, packet_scopes)
        non_whitespace = sum(not char.isspace() for char in packet.text)
        if covered_chars != len(packet.text) or covered_non_whitespace != non_whitespace:
            raise ValueError("scope_coverage")
        candidate_scopes = [scope for scope in packet_scopes if scope.state == "candidate"]
        packet_edges = [_edge(left, right) for left, right in pairwise(candidate_scopes)]
        all_scopes.extend(packet_scopes)
        all_edges.extend(packet_edges)
        packet_results.append(
            PacketScopeResult(
                packet.packet_id,
                "unresolved" if failure else "planned",
                failure or "complete_partition",
                tuple(scope.scope_id for scope in packet_scopes),
                len(packet.text),
                covered_chars,
                non_whitespace,
                covered_non_whitespace,
            )
        )
    if len(all_scopes) > limits.max_total_scopes:
        raise ValueError("total_scope_capacity")
    if len(all_edges) > limits.max_context_edges:
        raise ValueError("context_edge_capacity")
    result = ScopePlan(
        "",
        VERSION,
        expected_binding,
        limits,
        tuple(packet_results),
        tuple(all_scopes),
        tuple(all_edges),
        sum(packet.status == "planned" for packet in packet_results),
        sum(packet.status == "unresolved" for packet in packet_results),
        sum(scope.state == "candidate" for scope in all_scopes),
        sum(scope.state == "unresolved" for scope in all_scopes),
    )
    return replace(result, plan_id=digest(asdict(result)))


def verify_scope_plan(
    source: Source, expected_binding: str, plan: ScopePlan, expected_plan_id: str
) -> None:
    """Reconstruct a scope plan through its interface and reject drift."""
    if plan.plan_id != expected_plan_id:
        raise ValueError("plan_binding")
    if plan != prepare_scopes(source, expected_binding, plan.limits):
        raise ValueError("plan_drift")
