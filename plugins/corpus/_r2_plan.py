"""R2 private finite planner. Source coordinates are not semantic certification.

Promoted from the frozen P1 executable specification without changing its identity
algorithm. No imports from development evaluators, scratch, gold or benchmarks.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace

VERSION = "r2-p1-planner-spec-1"


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class Packet:
    packet_id: str
    locator: str
    text: str
    kind: str = "prose"
    status: str = "available"


@dataclass(frozen=True)
class Source:
    evidence_run_id: str
    source_rev: str
    parse_rev: str
    packets: tuple[Packet, ...]


@dataclass(frozen=True)
class Scope:
    packet_id: str
    start: int
    end: int


@dataclass(frozen=True)
class Limits:
    max_roots: int = 32
    max_children: int = 8
    max_obligations: int = 128
    max_root_chars: int = 4096
    max_total_chars: int = 32768
    max_depth: int = 1


DEFAULT_LIMITS = Limits()


@dataclass(frozen=True)
class Span:
    span_id: str
    source_rev: str
    parse_rev: str
    packet_id: str
    locator: str
    start: int
    end: int
    text_sha256: str


@dataclass(frozen=True)
class Obligation:
    obligation_id: str
    parent_id: str
    focus: Span
    support: Span
    context: tuple[Span, ...]
    state: str  # candidate | unresolved: planning state, NOT extraction terminal
    reason: str
    atomicity: str = "not_verified"


@dataclass(frozen=True)
class Plan:
    plan_id: str
    version: str
    source_binding: str
    scopes: tuple[Scope, ...]
    limits: Limits
    obligations: tuple[Obligation, ...]
    selected_chars: int
    candidate_count: int
    unresolved_count: int
    semantic_coverage: str = "not_evaluated"
    relation_status: str = "deferred"
    calls_authorized: int = 0


def source_binding(source: Source) -> str:
    """Synthetic normalized input hash, NOT a replacement for EvidenceRun identity."""
    return digest(asdict(source))


def _span(source: Source, packet: Packet, start: int, end: int) -> Span:
    text_hash = hashlib.sha256(packet.text[start:end].encode()).hexdigest()
    fields = (
        source.source_rev,
        source.parse_rev,
        packet.packet_id,
        packet.locator,
        start,
        end,
        text_hash,
    )
    return Span(digest(fields), *fields)


def resolve(source: Source, span: Span) -> str:
    packets = [p for p in source.packets if p.packet_id == span.packet_id]
    if len(packets) != 1:
        raise ValueError("packet_identity")
    packet = packets[0]
    if type(span.start) is not int or type(span.end) is not int:
        raise ValueError("coordinate_type")
    if not 0 <= span.start < span.end <= len(packet.text):
        raise ValueError("coordinate_range")
    if span != _span(source, packet, span.start, span.end):
        raise ValueError("span_binding")
    return packet.text[span.start : span.end]


def _ranges(text: str) -> tuple[list[tuple[int, int]], str]:
    # These signals can only WITHHOLD a split; they never certify a semantic label.
    # Retain all text, including punctuation, spaces, negation and attribution.
    if not text.strip():
        return [(0, len(text))], "blank_scope"
    if re.search(r"[，,、]|如果|若|只要|除非|否则|但是|而且|并且|同时|以及", text):
        return [(0, len(text))], "compound_or_condition"
    if any(char in text for char in "“”‘’「」『』\"'（）()[]【】"):
        return [(0, len(text))], "quoted_or_nested"
    if re.search(r"^(?:是的|不是|会的|不会|可能吧|这|它|其|上述|前述)", text.strip()):
        return [(0, len(text))], "context_dependent"
    ends = [match.end() for match in re.finditer(r"[。！？；?!;\n]+", text)]
    if not ends or ends[-1] < len(text):
        ends.append(len(text))
    starts = [0, *ends[:-1]]
    return list(zip(starts, ends, strict=True)), "structural_candidate_only"


def prepare(
    source: Source,
    expected_binding: str,
    scopes: tuple[Scope, ...],
    limits: Limits = DEFAULT_LIMITS,
) -> Plan:
    """Freeze a finite, lossless plan or reject the entire preparation before I/O.

    Input order is meaningful document order and is bound in plan_id. A context
    span is the previous/next selected root, not an inferred question or argument.
    """
    if source_binding(source) != expected_binding:
        raise ValueError("source_binding")
    if not all((source.evidence_run_id, source.source_rev, source.parse_rev)):
        raise ValueError("source_identity")
    if any(type(value) is not int or value <= 0 for value in asdict(limits).values()):
        raise ValueError("limits")
    if limits.max_depth != 1:
        raise ValueError("depth")
    if not scopes or len(scopes) > limits.max_roots:
        raise ValueError("root_capacity")
    packets = {p.packet_id: p for p in source.packets}
    if len(packets) != len(source.packets) or any(
        not p.packet_id or not p.locator for p in source.packets
    ):
        raise ValueError("packet_identity")
    packet_order = {p.packet_id: index for index, p in enumerate(source.packets)}
    roots: list[Span] = []
    last_key = (-1, -1)
    previous_end: dict[str, int] = {}
    for scope in scopes:
        packet = packets.get(scope.packet_id)
        if packet is None:
            raise ValueError("unknown_packet")
        if type(scope.start) is not int or type(scope.end) is not int:
            raise ValueError("coordinate_type")
        if not 0 <= scope.start < scope.end <= len(packet.text):
            raise ValueError("coordinate_range")
        key = (packet_order[scope.packet_id], scope.start)
        if key <= last_key or scope.start < previous_end.get(scope.packet_id, 0):
            raise ValueError("scope_overlap_or_order")
        if scope.end - scope.start > limits.max_root_chars:
            raise ValueError("root_chars_capacity")
        last_key = key
        previous_end[scope.packet_id] = scope.end
        roots.append(_span(source, packet, scope.start, scope.end))
    total = sum(root.end - root.start for root in roots)
    if total > limits.max_total_chars:
        raise ValueError("total_chars_capacity")
    obligations: list[Obligation] = []
    for index, root in enumerate(roots):
        packet = packets[root.packet_id]
        text = resolve(source, root)
        ranges, reason = _ranges(text)
        if packet.kind != "prose" or packet.status != "available":
            ranges, reason = [(0, len(text))], "unsupported_packet"
        # No silent truncation or relabeling capacity exhaustion as "no item".
        if len(ranges) > limits.max_children:
            raise ValueError("child_capacity")
        context = tuple(roots[j] for j in (index - 1, index + 1) if 0 <= j < len(roots))
        parent = digest([VERSION, expected_binding, asdict(root)])
        for start, end in ranges:
            focus = _span(source, packet, root.start + start, root.start + end)
            state = "candidate" if reason == "structural_candidate_only" else "unresolved"
            obligation_id = digest(
                [parent, asdict(focus), [asdict(c) for c in context], state, reason, asdict(limits)]
            )
            obligations.append(
                Obligation(obligation_id, parent, focus, root, context, state, reason)
            )
            if len(obligations) > limits.max_obligations:
                raise ValueError("obligation_capacity")
    candidate_count = sum(o.state == "candidate" for o in obligations)
    result = Plan(
        "",
        VERSION,
        expected_binding,
        scopes,
        limits,
        tuple(obligations),
        total,
        candidate_count,
        len(obligations) - candidate_count,
    )
    return replace(result, plan_id=digest(asdict(result)))


def verify_plan(source: Source, expected_binding: str, plan: Plan, expected_plan_id: str) -> None:
    """Verify semantic-free planning invariants by deterministic reconstruction."""
    if plan.plan_id != expected_plan_id:
        raise ValueError("plan_binding")
    if plan != prepare(source, expected_binding, plan.scopes, plan.limits):
        raise ValueError("plan_drift")
