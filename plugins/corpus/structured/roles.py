"""Strict role-isolated execution facade for structured corpus extraction.

The facade owns deterministic routing, protocol allowlisting, role artifact
envelopes, and the explicit items-to-relations dependency.  It does not own
attempt reservation or persistence; those seams remain with the execution
ledger introduced by the next implementation stage.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict

from plugins.corpus.claims import LlmCallError, LlmFn, LlmResponse
from plugins.corpus.evidence_pipeline import (
    CLAIMS_ATOMIC_PROTOCOL,
    CLAIMS_ATOMIC_PROTOCOL_V1,
    CLAIMS_PROSE_PROTOCOL,
    CLAIMS_TABLE_PROTOCOL,
    EvidenceRun,
    evidence_document_from_snapshot,
    extract_claims_role_from_snapshot,
)
from plugins.corpus.material_semantics import (
    MATERIAL_ITEMS_VALIDATION_VERSION,
    MATERIAL_RELATION_JSONL_VERSION,
    MATERIAL_SLOT_JSONL_VERSION,
    RELATION_CANDIDATE_RULE_VERSION,
    MaterialRun,
    MaterialType,
    RelationCandidateSet,
    build_candidate_slots,
    build_material_structure,
    extract_material_items_role_from_snapshot,
    extract_material_relations_role_from_snapshot,
)
from plugins.corpus.structured.adapter import ExtractionAdapter
from plugins.corpus.structured.config import canonical_hash
from plugins.corpus.structured.snapshot import EvidenceSnapshot, SnapshotUnit, dependency_closure

ROLE_ARTIFACT_SCHEMA_VERSION = "corpus-role-artifact-v1"
ROUTING_RULE_VERSION = "corpus-role-routing-v2"

Role = Literal["claims", "material_items", "material_relations"]
ExecutionStatus = Literal[
    "succeeded", "failed", "cancelled", "deferred", "outcome_unknown", "blocked"
]
ProtocolStatus = Literal["not_checked", "valid", "invalid", "unsupported"]
ContextStatus = Literal["complete", "partial", "missing", "ambiguous", "budget_exceeded"]
QualityStatus = Literal["unassessed", "accepted", "review_required", "rejected"]

_QUANTITATIVE_UNIT = re.compile(
    r"\d+(?:\.\d+)?\s*(?:万|亿)?\s*(?:人民币|美元|元|%|％|百分点|倍|个|只|台|人|天|吨|股)"
)
_QUANTITATIVE_METRIC = re.compile(
    r"(?:收入|营收|利润|现金流|费用|资产|负债|权益|毛利率|净利率|估值|PE|PB)", re.I
)
_NON_YEAR_NUMBER = re.compile(r"(?<!\d)(?!20\d{2}(?!\d))\d+(?:\.\d+)?")
_MATERIAL_SIGNAL = re.compile(
    r"(?:认为|预计|可能|风险|条件|如果|若|因为|所以|表示|称|承诺|并未|没有|"
    r"question|answer|risk|forecast|because|if\b)",
    re.I,
)
_CONTEXT_RANK = {
    "complete": 0,
    "partial": 1,
    "ambiguous": 2,
    "budget_exceeded": 3,
    "missing": 4,
}


class RoleRoute(BaseModel):
    """Auditable routing decision for every unit, including intentionally unrouted ones."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_id: str
    unit_kind: str
    claims_protocol: Literal["claims-deterministic-v1", "claims-json-v2"] | None = None
    material_items: bool = False
    reason_codes: tuple[str, ...]
    context_status: ContextStatus


class RoleRoutingPlan(BaseModel):
    """Versioned deterministic routing output whose misses remain scoreable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_version: Literal["corpus-role-routing-v1", "corpus-role-routing-v2"] = (
        ROUTING_RULE_VERSION
    )
    snapshot_id: str
    decisions: tuple[RoleRoute, ...]
    unrouted_gap_ids: tuple[str, ...] = ()

    def claims_scope(self, protocol: str) -> tuple[str, ...]:
        """Return exact root units routed to the chosen Claims protocol."""
        routed_protocol = (
            CLAIMS_PROSE_PROTOCOL
            if protocol in {CLAIMS_ATOMIC_PROTOCOL_V1, CLAIMS_ATOMIC_PROTOCOL}
            else protocol
        )
        return tuple(
            decision.unit_id
            for decision in self.decisions
            if decision.claims_protocol == routed_protocol
        )

    @property
    def material_items_scope(self) -> tuple[str, ...]:
        """Return root units routed to the independent items role."""
        return tuple(decision.unit_id for decision in self.decisions if decision.material_items)

    @property
    def unrouted_unit_ids(self) -> tuple[str, ...]:
        """Retain unrouted units in the scoring denominator."""
        return tuple(
            decision.unit_id
            for decision in self.decisions
            if decision.claims_protocol is None and not decision.material_items
        )


class RoleCoverage(BaseModel):
    """Root and dependency scope with explicitly incomplete units."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scoped_unit_ids: tuple[str, ...]
    omitted_unit_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()


class RoleArtifact(BaseModel):
    """Schema-compatible envelope around an existing business payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["corpus-role-artifact-v1"] = ROLE_ARTIFACT_SCHEMA_VERSION
    artifact_id: str
    role: Role
    snapshot_id: str
    task_id: str
    protocol: Literal[
        "claims-deterministic-v1",
        "claims-json-v2",
        "claims-atomic-json-v1",
        "claims-atomic-json-v2",
        "material-atomic-jsonl-v4",
        "material-atomic-jsonl-v5",
        "material-relations-jsonl-v1",
    ]
    business_contract: Literal["EvidenceRun/EvidenceFact", "MaterialRun/MaterialUnderstanding"]
    payload_sha256: str
    payload_media_type: Literal["application/json", "application/x-ndjson"] = "application/json"
    upstream_artifact_ids: tuple[str, ...] = ()
    coverage: RoleCoverage
    execution_status: ExecutionStatus
    protocol_status: ProtocolStatus
    context_status: ContextStatus
    quality_status: QualityStatus
    error_codes: tuple[str, ...] = ()

    def verify_identity(self) -> None:
        """Reject mutation of any artifact field after its identity was frozen."""
        if self.artifact_id != canonical_hash(
            self.model_dump(mode="json", exclude={"artifact_id"})
        ):
            raise ValueError("CS_ARTIFACT_CORRUPT: role artifact identity mismatch")


@dataclass(frozen=True)
class RoleRequest:
    """One request handed to issue 05 before any model execution."""

    task_id: str
    role: Role
    protocol: str
    snapshot_id: str
    input_sha256: str
    request_sha256: str
    prompt: str
    sequence: int


@dataclass(frozen=True)
class RoleCallResult:
    """Result receipt for one dispatch, including unknown usage and failures."""

    request: RoleRequest
    response_sha256: str | None
    execution_status: str
    diagnostics: dict[str, Any]


RoleDispatch = Callable[[RoleRequest], str]


class _RoleCalls:
    def __init__(
        self,
        snapshot: EvidenceSnapshot,
        task_id: str,
        role: Role,
        protocol: str,
        inputs: object,
        llm: LlmFn | None,
        dispatch: RoleDispatch | None,
    ) -> None:
        if not task_id.strip():
            raise ValueError("CS_INPUT_INVALID: empty role task_id")
        supported = {
            "claims": {
                CLAIMS_TABLE_PROTOCOL,
                CLAIMS_PROSE_PROTOCOL,
                CLAIMS_ATOMIC_PROTOCOL_V1,
                CLAIMS_ATOMIC_PROTOCOL,
            },
            "material_items": {MATERIAL_SLOT_JSONL_VERSION},
            "material_relations": {MATERIAL_RELATION_JSONL_VERSION},
        }
        if protocol not in supported[role]:
            raise ValueError("CS_PROTOCOL_UNSUPPORTED: role/protocol mismatch")
        if llm is not None and dispatch is not None:
            raise ValueError("CS_INPUT_INVALID: choose llm or dispatcher")
        if isinstance(llm, ExtractionAdapter) and (
            llm.binding.role != role or llm.binding.protocol != protocol
        ):
            raise ValueError("CS_INPUT_INVALID: extraction adapter role/protocol mismatch")
        self.snapshot_id = snapshot.snapshot_id
        self.task_id = task_id
        self.role: Role = role
        self.protocol = protocol
        self.input_sha256 = canonical_hash(inputs)
        self.llm, self.dispatch = llm, dispatch
        self.results: list[RoleCallResult] = []

    @property
    def callback(self) -> LlmFn | None:
        return self if self.llm is not None or self.dispatch is not None else None

    def __call__(self, prompt: str) -> str:
        binding = {
            "task_id": self.task_id,
            "role": self.role,
            "protocol": self.protocol,
            "snapshot_id": self.snapshot_id,
            "input_sha256": self.input_sha256,
        }
        prompt = "固定角色与输入版本：" + json.dumps(binding, ensure_ascii=False) + "\n" + prompt
        request = RoleRequest(
            task_id=self.task_id,
            role=self.role,
            protocol=self.protocol,
            snapshot_id=self.snapshot_id,
            input_sha256=self.input_sha256,
            request_sha256=canonical_hash(prompt),
            prompt=prompt,
            sequence=len(self.results) + 1,
        )
        try:
            if self.dispatch is not None:
                raw = self.dispatch(request)
            else:
                assert self.llm is not None
                raw = self.llm(prompt)
        except Exception as exc:
            diagnostics = dict(exc.diagnostics) if isinstance(exc, LlmCallError) else {}
            self.results.append(
                RoleCallResult(
                    request,
                    None,
                    str(diagnostics.get("execution_status", "failed")),
                    diagnostics,
                )
            )
            raise
        diagnostics = dict(raw.diagnostics) if isinstance(raw, LlmResponse) else {}
        self.results.append(
            RoleCallResult(request, canonical_hash(str(raw)), "succeeded", diagnostics)
        )
        return raw


@dataclass(frozen=True)
class RoleExecution:
    """Envelope plus the unchanged EvidenceRun or MaterialRun business payload."""

    artifact: RoleArtifact
    payload: EvidenceRun | MaterialRun
    relation_candidates: RelationCandidateSet | None = None
    calls: tuple[RoleCallResult, ...] = ()


def _context_status(unit: SnapshotUnit) -> ContextStatus:
    value = str(unit.metadata.get("context_status") or "complete")
    if value not in _CONTEXT_RANK:
        return "ambiguous"
    return cast(ContextStatus, value)


def route_snapshot(snapshot: EvidenceSnapshot) -> RoleRoutingPlan:
    """Route each exact unit with no model call and no hidden generic extraction pass."""
    snapshot.verify_identity()
    decisions: list[RoleRoute] = []
    for unit in snapshot.units:
        reasons: list[str] = []
        claims_protocol: Literal["claims-deterministic-v1", "claims-json-v2"] | None = None
        material_items = False
        text = unit.text.strip()
        if unit.kind == "gap" or not text:
            reasons.append("source_gap_or_empty")
        elif unit.kind == "table":
            cells = unit.metadata.get("cells")
            if isinstance(cells, list) and cells:
                claims_protocol = CLAIMS_TABLE_PROTOCOL
                reasons.append("parser_owned_table_cells")
            else:
                reasons.append("table_without_verified_cells")
        elif unit.kind in {"table_note", "heading"}:
            material_items = True
            reasons.append("structural_material_context")
        elif unit.kind in {"prose", "image_text"}:
            has_quantity = bool(_QUANTITATIVE_UNIT.search(text)) or bool(
                _QUANTITATIVE_METRIC.search(text) and _NON_YEAR_NUMBER.search(text)
            )
            if has_quantity:
                claims_protocol = CLAIMS_PROSE_PROTOCOL
                reasons.append("source_anchored_quantitative_statement")
            material_items = True
            if _MATERIAL_SIGNAL.search(text):
                reasons.append("qualitative_or_relational_signal")
            elif has_quantity:
                reasons.append("quantitative_statement_also_preserves_material_semantics")
            else:
                reasons.append("unclassified_prose_conservatively_retained")
        else:
            reasons.append("unsupported_unit_kind")
        status = _context_status(unit)
        if status != "complete":
            reasons.append(f"context_{status}")
        decisions.append(
            RoleRoute(
                unit_id=unit.unit_id,
                unit_kind=unit.kind,
                claims_protocol=claims_protocol,
                material_items=material_items,
                reason_codes=tuple(reasons),
                context_status=status,
            )
        )
    return RoleRoutingPlan(
        snapshot_id=snapshot.snapshot_id,
        decisions=tuple(decisions),
        unrouted_gap_ids=tuple(gap.gap_id for gap in snapshot.gaps),
    )


def _worst_context(snapshot: EvidenceSnapshot, scoped_unit_ids: tuple[str, ...]) -> ContextStatus:
    by_id = {unit.unit_id: unit for unit in snapshot.units}
    statuses = [_context_status(by_id[unit_id]) for unit_id in scoped_unit_ids]
    if not statuses:
        return "missing"
    return cast(ContextStatus, max(statuses, key=_CONTEXT_RANK.__getitem__))


def _run_state(
    run: EvidenceRun | MaterialRun,
) -> tuple[ExecutionStatus, ProtocolStatus, tuple[str, ...]]:
    packet_runs = run.packet_runs
    statuses = {packet.status for packet in packet_runs}
    if isinstance(run, MaterialRun):
        statuses.update(entry.status for entry in run.understanding.coverage.slot_ledger)

    execution_states: set[str] = set()
    error_codes: set[str] = set()

    def collect(value: object) -> None:
        if isinstance(value, dict):
            state = value.get("execution_status")
            if isinstance(state, str):
                execution_states.add(state)
            code = value.get("error_code")
            if isinstance(code, str) and code.startswith("CS_"):
                error_codes.add(code)
            for child in value.values():
                collect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect(child)

    for packet in packet_runs:
        collect(packet.diagnostics)
    if "outcome_unknown" in execution_states:
        error_codes.add("CS_OUTCOME_UNKNOWN")
        return "outcome_unknown", "not_checked", tuple(sorted(error_codes))
    for state in ("cancelled", "blocked", "deferred"):
        if state in execution_states:
            return cast(ExecutionStatus, state), "not_checked", tuple(sorted(error_codes))
    if "failed" in statuses:
        return "failed", "not_checked", tuple(sorted(error_codes))
    if statuses & {"deferred", "unknown"}:
        return "deferred", "not_checked", ()
    if "partial" in statuses:
        return "succeeded", "invalid", ()
    return "succeeded", "valid", ()


def _artifact(
    *,
    role: Role,
    snapshot: EvidenceSnapshot,
    task_id: str,
    protocol: str,
    payload: EvidenceRun | MaterialRun,
    scoped_unit_ids: tuple[str, ...],
    upstream_artifact_ids: tuple[str, ...] = (),
    reason_codes: tuple[str, ...] = (),
    omitted_unit_ids: tuple[str, ...] = (),
) -> RoleArtifact:
    if not task_id.strip():
        raise ValueError("CS_INPUT_INVALID: empty role task_id")
    execution, protocol_status, error_codes = _run_state(payload)
    roots = set(scoped_unit_ids)
    expanded = roots | {
        dependency.unit_id
        for unit in snapshot.units
        if unit.unit_id in roots
        for dependency in dependency_closure(snapshot, unit)
    }
    scoped_unit_ids = tuple(unit.unit_id for unit in snapshot.units if unit.unit_id in expanded)
    context = _worst_context(snapshot, scoped_unit_ids)
    document = (
        payload.document
        if isinstance(payload, EvidenceRun)
        else evidence_document_from_snapshot(snapshot, role="material_items")
    )
    incomplete_ids = {
        packet.packet_id for packet in payload.packet_runs if packet.status != "completed"
    }
    if isinstance(payload, MaterialRun):
        incomplete_slots = {
            entry.candidate_slot_id
            for entry in payload.understanding.coverage.slot_ledger
            if entry.status not in {"extracted", "no_supported_item", "not_candidate"}
        }
        incomplete_ids.update(
            slot.packet_id
            for slot in payload.candidate_slots
            if slot.candidate_slot_id in incomplete_slots
        )
    omitted = tuple(
        unit_id
        for unit_id in scoped_unit_ids
        if unit_id in omitted_unit_ids
        or any(
            packet.packet_id in incomplete_ids
            and any(span.locator == unit_id for span in packet.spans)
            for packet in document.packets
        )
    )
    reasons = list(reason_codes)
    reasons.extend(reason for packet in payload.packet_runs for reason in packet.reasons)
    if not scoped_unit_ids:
        reasons.append("no_routed_candidates")
    if omitted:
        reasons.append("role_scope_not_fully_covered")
    if isinstance(payload, MaterialRun):
        invalid_quality = any(
            entry.status not in {"extracted", "no_supported_item", "not_candidate"}
            for entry in payload.understanding.coverage.slot_ledger
        )
    else:
        invalid_quality = any(fact.claim.quality_status != "ok" for fact in payload.facts)
    quality: QualityStatus = (
        "accepted"
        if execution == "succeeded"
        and protocol_status == "valid"
        and context == "complete"
        and not omitted
        and not invalid_quality
        else "review_required"
    )
    base = RoleArtifact(
        artifact_id="sha256:" + "0" * 64,
        role=role,
        snapshot_id=snapshot.snapshot_id,
        task_id=task_id,
        protocol=protocol,  # type: ignore[arg-type]
        business_contract=(
            "EvidenceRun/EvidenceFact"
            if isinstance(payload, EvidenceRun)
            else "MaterialRun/MaterialUnderstanding"
        ),
        payload_sha256=canonical_hash(payload.model_dump(mode="json")),
        upstream_artifact_ids=upstream_artifact_ids,
        coverage=RoleCoverage(
            scoped_unit_ids=scoped_unit_ids,
            omitted_unit_ids=omitted,
            reason_codes=tuple(dict.fromkeys(reasons)),
        ),
        execution_status=execution,
        protocol_status=protocol_status,
        context_status=context,
        quality_status=quality,
        error_codes=error_codes,
    )
    identity = base.model_dump(mode="json", exclude={"artifact_id"})
    return base.model_copy(update={"artifact_id": canonical_hash(identity)})


def execute_claims_role(
    snapshot: EvidenceSnapshot,
    *,
    task_id: str,
    protocol: str,
    llm: LlmFn | None = None,
    model: str | None = None,
    max_calls: int = 0,
    scoped_unit_ids: tuple[str, ...] | None = None,
    dispatch: RoleDispatch | None = None,
) -> RoleExecution:
    """Execute exactly one supported Claims protocol and wrap its EvidenceRun."""
    plan = route_snapshot(snapshot)
    scope = plan.claims_scope(protocol) if scoped_unit_ids is None else scoped_unit_ids
    calls = _RoleCalls(
        snapshot,
        task_id,
        "claims",
        protocol,
        {
            "scope": scope,
            "routing_rule": ROUTING_RULE_VERSION,
        },
        llm,
        dispatch,
    )
    run = extract_claims_role_from_snapshot(
        snapshot,
        protocol=protocol,
        llm=calls.callback,
        model=model,
        max_calls=max_calls,
        scoped_unit_ids=scope,
    )
    return RoleExecution(
        artifact=_artifact(
            role="claims",
            snapshot=snapshot,
            task_id=task_id,
            protocol=protocol,
            payload=run,
            scoped_unit_ids=scope,
        ),
        payload=run,
        calls=tuple(calls.results),
    )


def execute_material_items_role(
    snapshot: EvidenceSnapshot,
    *,
    task_id: str,
    protocol: str,
    llm: LlmFn | None = None,
    max_calls: int,
    material_type: MaterialType | None = None,
    max_items_per_packet: int = 30,
    max_slots_per_batch: int = 8,
    candidate_slot_ids: tuple[str, ...] | None = None,
    dispatch: RoleDispatch | None = None,
) -> RoleExecution:
    """Execute items/speakers only; relations are neither prompted nor scored here."""
    scope = route_snapshot(snapshot).material_items_scope
    calls = _RoleCalls(
        snapshot,
        task_id,
        "material_items",
        protocol,
        {
            "scope": scope,
            "candidate_slot_ids": candidate_slot_ids,
            "max_items_per_packet": max_items_per_packet,
            "max_slots_per_batch": max_slots_per_batch,
            "material_type": material_type,
            "routing_rule": ROUTING_RULE_VERSION,
        },
        llm,
        dispatch,
    )
    run = extract_material_items_role_from_snapshot(
        snapshot,
        protocol=protocol,
        llm=calls.callback,
        max_calls=max_calls,
        material_type=material_type,
        max_items_per_packet=max_items_per_packet,
        max_slots_per_batch=max_slots_per_batch,
        candidate_slot_ids=candidate_slot_ids,
    )
    omitted_units: tuple[str, ...] = ()
    if candidate_slot_ids is not None:
        packet_ids = {slot.packet_id for slot in run.candidate_slots}
        document = evidence_document_from_snapshot(snapshot, role="material_items")
        ids = {
            span.locator
            for packet in document.packets
            if packet.packet_id in packet_ids
            for span in packet.spans
        }
        scope = tuple(unit_id for unit_id in scope if unit_id in ids)
        unselected_packets = {
            slot.packet_id
            for slot in build_candidate_slots(document, build_material_structure(document))
            if slot.candidate_slot_id not in candidate_slot_ids
        }
        omitted_units = tuple(
            dict.fromkeys(
                span.locator
                for packet in document.packets
                if packet.packet_id in packet_ids & unselected_packets
                for span in packet.spans
            )
        )
    return RoleExecution(
        artifact=_artifact(
            role="material_items",
            snapshot=snapshot,
            task_id=task_id,
            protocol=protocol,
            payload=run,
            scoped_unit_ids=scope,
            reason_codes=("relations_not_requested",),
            omitted_unit_ids=omitted_units,
        ),
        payload=run,
        calls=tuple(calls.results),
    )


def execute_material_relations_role(
    snapshot: EvidenceSnapshot,
    *,
    task_id: str,
    protocol: str,
    items_execution: RoleExecution,
    endpoint_item_ids: tuple[str, ...],
    items_validation_version: str = MATERIAL_ITEMS_VALIDATION_VERSION,
    candidate_rule_version: str = RELATION_CANDIDATE_RULE_VERSION,
    llm: LlmFn | None = None,
    max_calls: int,
    dispatch: RoleDispatch | None = None,
) -> RoleExecution:
    """Execute relations from one exact accepted items artifact and endpoint set."""
    calls = _RoleCalls(
        snapshot,
        task_id,
        "material_relations",
        protocol,
        {
            "items_artifact": items_execution.artifact.artifact_id,
            "items_run": items_execution.payload.run_id,
            "endpoints": sorted(endpoint_item_ids),
            "validation_version": items_validation_version,
            "candidate_rule": candidate_rule_version,
        },
        llm,
        dispatch,
    )
    items_execution.artifact.verify_identity()
    if items_execution.artifact.role != "material_items" or not isinstance(
        items_execution.payload, MaterialRun
    ):
        raise ValueError("CS_INPUT_INVALID: relations require a material_items artifact")
    if items_execution.artifact.snapshot_id != snapshot.snapshot_id:
        raise ValueError("CS_INPUT_INVALID: upstream items artifact uses another snapshot")
    if items_execution.artifact.payload_sha256 != canonical_hash(
        items_execution.payload.model_dump(mode="json")
    ):
        raise ValueError("CS_INPUT_INVALID: upstream items payload hash mismatch")
    if items_execution.artifact.protocol != MATERIAL_SLOT_JSONL_VERSION:
        raise ValueError("CS_INPUT_INVALID: upstream items protocol is unsupported")
    if (
        items_execution.artifact.quality_status == "rejected"
        or items_execution.artifact.execution_status
        in {
            "cancelled",
            "blocked",
            "outcome_unknown",
            "deferred",
        }
    ):
        raise ValueError("CS_DEPENDENCY_NOT_READY: upstream items are unavailable")
    run, candidates = extract_material_relations_role_from_snapshot(
        snapshot,
        items_execution.payload,
        protocol=protocol,
        endpoint_item_ids=endpoint_item_ids,
        items_validation_version=items_validation_version,
        llm=calls.callback,
        max_calls=max_calls,
        candidate_rule_version=candidate_rule_version,
    )
    reason_codes = ("no_relation_candidates",) if not candidates.candidates else ()
    document = evidence_document_from_snapshot(snapshot, role="material_items")
    endpoint_packets = {
        item.evidence[0].packet_id
        for item in items_execution.payload.understanding.items
        if item.item_id in endpoint_item_ids
    }
    scope = tuple(
        dict.fromkeys(
            span.locator
            for packet in document.packets
            if packet.packet_id in endpoint_packets
            for span in packet.spans
        )
    )
    return RoleExecution(
        artifact=_artifact(
            role="material_relations",
            snapshot=snapshot,
            task_id=task_id,
            protocol=protocol,
            payload=run,
            scoped_unit_ids=scope,
            upstream_artifact_ids=(items_execution.artifact.artifact_id,),
            reason_codes=reason_codes,
        ),
        payload=run,
        relation_candidates=candidates,
        calls=tuple(calls.results),
    )


__all__ = [
    "MATERIAL_ITEMS_VALIDATION_VERSION",
    "MATERIAL_RELATION_JSONL_VERSION",
    "MATERIAL_SLOT_JSONL_VERSION",
    "RELATION_CANDIDATE_RULE_VERSION",
    "ROLE_ARTIFACT_SCHEMA_VERSION",
    "ROUTING_RULE_VERSION",
    "RoleArtifact",
    "RoleCallResult",
    "RoleDispatch",
    "RoleExecution",
    "RoleRequest",
    "RoleRoute",
    "RoleRoutingPlan",
    "execute_claims_role",
    "execute_material_items_role",
    "execute_material_relations_role",
    "route_snapshot",
]
