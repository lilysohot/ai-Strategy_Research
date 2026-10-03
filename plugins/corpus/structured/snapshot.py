"""Immutable same-source evidence snapshots for Claims and material semantics.

The reader is deliberately injected.  Production PG wiring can implement the small
read-only protocol with one repeatable-read transaction; tests use an in-memory
reader and never need database or network access.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict

SNAPSHOT_SCHEMA_VERSION = "corpus-evidence-snapshot-v1"
SNAPSHOT_BUILDER_VERSION = "structured-snapshot-2"
COORDINATE_SYSTEM = "unicode_code_points"

ContextStatus = Literal["complete", "partial", "missing", "ambiguous", "budget_exceeded"]
DependencyStatus = Literal["present", "missing", "ambiguous", "budget_exceeded"]
SnapshotRole = Literal["claims", "material_items"]
SnapshotUnitKind = Literal["prose", "table", "table_note", "heading", "image_text", "gap"]

_HASH_PREFIX = "sha256:"
_UNIT_KINDS = frozenset({"prose", "table", "table_note", "heading", "image_text", "gap"})
_REQUIRED_PIPELINE_VERSIONS = frozenset({"parse", "clean", "chunk"})
_CHUNK_LOCATOR = re.compile(r"chunk:[A-Za-z0-9._:-]+\Z")


class SnapshotError(ValueError):
    """Base class for fail-closed snapshot construction errors."""


class SnapshotChangedError(SnapshotError):
    """The active publication changed while the snapshot was being read."""


class SnapshotIntegrityError(SnapshotError):
    """The adapter returned inconsistent identity, content, or coordinates."""


class SnapshotSpan(BaseModel):
    """Half-open Unicode code-point interval over one exact snapshot unit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    coordinate_system: Literal["unicode_code_points"] = COORDINATE_SYSTEM
    text_sha256: str
    start: int
    end: int


class SnapshotUnit(BaseModel):
    """Immutable evidence unit with content, metadata, coordinates, and dependencies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_id: str
    chunk_id: str
    kind: SnapshotUnitKind
    locator: str
    text: str
    text_sha256: str
    span: SnapshotSpan
    metadata: dict[str, object]
    metadata_sha256: str
    dependencies: tuple[str, ...] = ()


class SnapshotGap(BaseModel):
    """Visible record of unavailable or incomplete source context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gap_id: str
    code: str
    locator: str
    context_status: Literal["partial", "missing", "ambiguous", "budget_exceeded"]


class SnapshotUnitIdentity(BaseModel):
    """Content-addressed identity fields for one immutable snapshot unit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_id: str
    chunk_id: str
    kind: str
    locator: str
    coordinate_system: Literal["unicode_code_points"] = COORDINATE_SYSTEM
    start: int
    end: int
    text_sha256: str
    metadata_sha256: str


class SnapshotIdentityInput(BaseModel):
    """Canonical, credential-free payload used to derive a snapshot identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["corpus-evidence-snapshot-v1"] = SNAPSHOT_SCHEMA_VERSION
    source_id: str
    build_id: str
    publication_generation: int
    parser_versions: dict[str, str]
    unit_identities: tuple[SnapshotUnitIdentity, ...]


class EvidenceSnapshot(BaseModel):
    """Schema-backed snapshot shared by independently selected role views."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["corpus-evidence-snapshot-v1"] = SNAPSHOT_SCHEMA_VERSION
    snapshot_id: str
    source_id: str
    build_id: str
    publication_generation: int
    parser_versions: dict[str, str]
    units: tuple[SnapshotUnit, ...]
    gaps: tuple[SnapshotGap, ...]
    identity_input: SnapshotIdentityInput

    def verify_identity(self) -> None:
        """Recompute every byte-sensitive identity component."""
        _validate_identifier(self.source_id, "source_id")
        _validate_identifier(self.build_id, "build_id")
        _validated_parser_versions(self.parser_versions, require_snapshot=True)
        if self.publication_generation < 1 or not self.units:
            raise SnapshotIntegrityError("snapshot requires units and a positive generation")
        if self.source_id == self.build_id:
            raise SnapshotIntegrityError("build_id must not reuse source_id")
        ids = {unit.unit_id for unit in self.units}
        if len(ids) != len(self.units):
            raise SnapshotIntegrityError("duplicate snapshot unit identity")
        gaps_hash = _canonical_hash([gap.model_dump(mode="json") for gap in self.gaps])
        for gap in self.gaps:
            if not gap.gap_id or not gap.code or not gap.locator:
                raise SnapshotIntegrityError("snapshot gap violates the frozen contract")
        for unit in self.units:
            source_unit_id(unit)
            if not _CHUNK_LOCATOR.fullmatch(unit.chunk_id):
                raise SnapshotIntegrityError("snapshot unit chunk_id violates the frozen contract")
            if not unit.locator:
                raise SnapshotIntegrityError("snapshot unit locator violates the frozen contract")
            if unit.text_sha256 != _text_hash(unit.text):
                raise SnapshotIntegrityError(f"text hash mismatch: {unit.unit_id}")
            if unit.span.text_sha256 != unit.text_sha256:
                raise SnapshotIntegrityError(f"span text hash mismatch: {unit.unit_id}")
            if (unit.span.start, unit.span.end) != (0, len(unit.text)):
                raise SnapshotIntegrityError(
                    f"unit span must cover exact unit text: {unit.unit_id}"
                )
            if unit.metadata_sha256 != _canonical_hash(unit.metadata):
                raise SnapshotIntegrityError(f"metadata hash mismatch: {unit.unit_id}")
            if unit.metadata.get("snapshot_gaps_sha256") != gaps_hash:
                raise SnapshotIntegrityError("snapshot gap hash mismatch")
            details = unit.metadata.get("dependency_details")
            if not isinstance(details, list) or any(not isinstance(d, dict) for d in details):
                raise SnapshotIntegrityError("snapshot dependency details missing")
            targets = tuple(
                dict.fromkeys(
                    str(detail["target_unit_id"])
                    for detail in details
                    if isinstance(detail, dict) and detail.get("target_unit_id")
                )
            )
            if targets != unit.dependencies or not set(targets) <= ids:
                raise SnapshotIntegrityError("snapshot dependency binding mismatch")
        expected = SnapshotIdentityInput(
            source_id=self.source_id,
            build_id=self.build_id,
            publication_generation=self.publication_generation,
            parser_versions=self.parser_versions,
            unit_identities=tuple(_identity_of(unit) for unit in self.units),
        )
        if expected != self.identity_input:
            raise SnapshotIntegrityError("snapshot identity input mismatch")
        if self.snapshot_id != _canonical_hash(expected.model_dump(mode="json")):
            raise SnapshotIntegrityError("snapshot content hash mismatch")


@dataclass(frozen=True)
class SnapshotHead:
    """One active semantic source/build publication pointer."""

    source_id: str
    build_id: str
    publication_generation: int


@dataclass(frozen=True)
class SnapshotDocumentSource:
    """Document metadata supplied by the read adapter for snapshot construction."""

    title: str
    subject: str | None = None
    published: str | None = None


@dataclass(frozen=True)
class SnapshotTextSource:
    """Exact adapter-supplied proof for a cell label, including external headers."""

    target_unit_id: str
    target_chunk_id: str
    start: int
    end: int


@dataclass(frozen=True)
class SnapshotCellSource:
    """One already-parsed table cell with exact offsets in its source unit text."""

    row: str
    column: str
    value: str
    unit: str
    start: int
    end: int
    source_row: int | None = None
    source_column: int | None = None
    row_ref: SnapshotTextSource | None = None
    column_ref: SnapshotTextSource | None = None
    unit_ref: SnapshotTextSource | None = None


@dataclass(frozen=True)
class SnapshotDependencySource:
    """An explicit, source-backed semantic dependency; never inferred by this layer."""

    kind: Literal[
        "value",
        "period",
        "unit",
        "header",
        "footnote",
        "condition",
        "negation",
        "attribution",
        "context",
    ]
    target_unit_id: str | None
    status: DependencyStatus = "present"
    target_chunk_id: str | None = None
    required_for: tuple[Literal["cite", "compare", "calculate"], ...] = ("cite",)
    reason: str | None = None


@dataclass(frozen=True)
class SnapshotUnitSource:
    """Read-adapter projection of one exact unit in one exact chunk."""

    source_unit_id: str
    chunk_id: str
    kind: str
    text: str
    locator: str
    content_hash: str | None = None
    page: int | None = None
    element: str | None = None
    cells: tuple[SnapshotCellSource, ...] = ()
    label_path: tuple[str, ...] = ()
    parent_id: str | None = None
    ordinal: int | None = None
    status: str = "kept"
    reasons: tuple[str, ...] = ()
    dependencies: tuple[SnapshotDependencySource, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SnapshotGapSource:
    """Adapter-supplied parsing or context gap retained in the snapshot."""

    code: str
    locator: str
    context_status: Literal["partial", "missing", "ambiguous", "budget_exceeded"]


@dataclass(frozen=True)
class SnapshotBuildSource:
    """All data read for one head; implementations should read it atomically."""

    head: SnapshotHead
    parser_versions: Mapping[str, str]
    document: SnapshotDocumentSource
    units: tuple[SnapshotUnitSource, ...]
    gaps: tuple[SnapshotGapSource, ...] = ()


class SnapshotReader(Protocol):
    """Small read-only seam used to detect publication switches."""

    def read_head(self, source_id: str) -> SnapshotHead:
        """Read the active source/build generation without changing publication state."""
        ...

    def read_build(self, head: SnapshotHead) -> SnapshotBuildSource:
        """Read the exact build pinned by ``head``, including its evidence and versions."""
        ...


@dataclass(frozen=True)
class SnapshotSelection:
    """Role-specific unit view that retains the shared immutable snapshot identity."""

    snapshot_id: str
    role: SnapshotRole
    units: tuple[SnapshotUnit, ...]


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{_HASH_PREFIX}{hashlib.sha256(encoded).hexdigest()}"


def _text_hash(text: str) -> str:
    return f"{_HASH_PREFIX}{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _normalize_hash(value: str) -> str:
    return value if value.startswith(_HASH_PREFIX) else f"{_HASH_PREFIX}{value}"


def _validate_identifier(value: str, name: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise SnapshotIntegrityError(f"{name} must be a lowercase 64-character SHA-256")


def _validated_parser_versions(
    versions: Mapping[str, str], *, require_snapshot: bool
) -> dict[str, str]:
    if any(
        not isinstance(key, str) or not key or not isinstance(value, str) or not value
        for key, value in versions.items()
    ):
        raise SnapshotIntegrityError("parser_versions must contain non-empty string pairs")
    result = dict(versions)
    missing = _REQUIRED_PIPELINE_VERSIONS - result.keys()
    if missing:
        raise SnapshotIntegrityError("parser_versions must include parse, clean and chunk")
    if require_snapshot and result.get("snapshot") != SNAPSHOT_BUILDER_VERSION:
        raise SnapshotIntegrityError("unsupported snapshot builder; rebuild from source")
    return result


def _chunk_locator(chunk_id: str) -> str:
    return chunk_id if chunk_id.startswith("chunk:") else f"chunk:{chunk_id}"


def _kind(kind: str) -> SnapshotUnitKind:
    normalized = {
        "paragraph": "prose",
        "list_item": "prose",
        "quote": "prose",
        "qa_question": "prose",
        "qa_answer": "prose",
        "footer": "prose",
        "title": "heading",
        "header": "heading",
        "unknown": "gap",
        "table_row": "table",
        "table_cell": "table",
        "footnote": "table_note",
    }.get(kind, kind)
    if normalized not in _UNIT_KINDS:
        raise SnapshotIntegrityError(f"unsupported snapshot unit kind: {kind!r}")
    return cast("SnapshotUnitKind", normalized)


def _source_key(unit: SnapshotUnitSource) -> tuple[str, str]:
    return (_chunk_locator(unit.chunk_id), unit.source_unit_id)


def _unit_key(unit: SnapshotUnitSource) -> str:
    payload = {
        "chunk_id": _chunk_locator(unit.chunk_id),
        "source_unit_id": unit.source_unit_id,
        "kind": _kind(unit.kind),
        "source_kind": unit.kind,
        "locator": unit.locator,
        "text_sha256": _text_hash(unit.text),
        "page": unit.page,
        "element": unit.element,
        "ordinal": unit.ordinal,
        "cells": [asdict(cell) for cell in unit.cells],
    }
    return f"snapshot-unit:{_canonical_hash(payload).removeprefix(_HASH_PREFIX)}"


def _identity_of(unit: SnapshotUnit) -> SnapshotUnitIdentity:
    return SnapshotUnitIdentity(
        unit_id=unit.unit_id,
        chunk_id=unit.chunk_id,
        kind=unit.kind,
        locator=unit.locator,
        start=unit.span.start,
        end=unit.span.end,
        text_sha256=unit.text_sha256,
        metadata_sha256=unit.metadata_sha256,
    )


def _context_status(statuses: list[DependencyStatus]) -> ContextStatus:
    if "missing" in statuses:
        return "missing"
    if "ambiguous" in statuses:
        return "ambiguous"
    if "budget_exceeded" in statuses:
        return "budget_exceeded"
    return "complete" if all(status == "present" for status in statuses) else "partial"


def _validate_cells(unit: SnapshotUnitSource) -> None:
    for cell in unit.cells:
        if (
            type(cell.start) is not int
            or type(cell.end) is not int
            or cell.start < 0
            or cell.end <= cell.start
            or cell.end > len(unit.text)
        ):
            raise SnapshotIntegrityError(
                f"cell interval outside unit text: {unit.source_unit_id}[{cell.start}:{cell.end}]"
            )
        if unit.text[cell.start : cell.end] != cell.value:
            raise SnapshotIntegrityError(
                f"cell interval does not reproduce value: {unit.source_unit_id}"
            )


def _cell_dependencies(
    source: SnapshotUnitSource, sources: dict[tuple[str, str], SnapshotUnitSource]
) -> tuple[list[SnapshotDependencySource], list[str]]:
    """Only explicit intervals prove labels; never infer headers from nearby text."""
    dependencies: list[SnapshotDependencySource] = []
    reasons: list[str] = []
    for cell in source.cells:
        for name in ("row", "column", "unit"):
            label = getattr(cell, name)
            reference: SnapshotTextSource | None = getattr(cell, f"{name}_ref")
            if not label:
                continue
            if reference is None:
                reasons.append(f"cell_{name}_reference_missing")
                continue
            key = (_chunk_locator(reference.target_chunk_id), reference.target_unit_id)
            target = sources.get(key)
            if target is None:
                reasons.append(f"cell_{name}_target_missing")
                continue
            if (
                type(reference.start) is not int
                or type(reference.end) is not int
                or reference.start < 0
                or reference.end <= reference.start
                or reference.end > len(target.text)
                or target.text[reference.start : reference.end] != label
            ):
                raise SnapshotIntegrityError(f"cell {name} reference does not reproduce label")
            if key != _source_key(source):
                dependencies.append(
                    SnapshotDependencySource(
                        kind="unit" if name == "unit" else "header",
                        target_unit_id=reference.target_unit_id,
                        target_chunk_id=reference.target_chunk_id,
                        required_for=("cite", "compare", "calculate"),
                    )
                )
    return dependencies, list(dict.fromkeys(reasons))


def _resolve_dependency(
    dependency: SnapshotDependencySource,
    source: SnapshotUnitSource,
    ids_by_key: dict[tuple[str, str], str],
    keys_by_source_unit: dict[str, list[tuple[str, str]]],
) -> tuple[DependencyStatus, str | None, str | None]:
    if dependency.status != "present":
        return dependency.status, None, dependency.reason
    if not dependency.target_unit_id:
        return "missing", None, dependency.reason or "dependency_target_missing"
    target_chunk = _chunk_locator(
        source.chunk_id if dependency.target_chunk_id is None else dependency.target_chunk_id
    )
    exact = ids_by_key.get((target_chunk, dependency.target_unit_id))
    if exact:
        return "present", exact, dependency.reason
    if dependency.target_chunk_id is not None:
        return "missing", None, dependency.reason or "dependency_target_chunk_mismatch"
    candidates = keys_by_source_unit.get(dependency.target_unit_id, [])
    if len(candidates) == 1:
        return "present", ids_by_key[candidates[0]], dependency.reason
    if len(candidates) > 1:
        return "ambiguous", None, dependency.reason or "dependency_target_ambiguous"
    return "missing", None, dependency.reason or "dependency_target_not_found"


def _worst_context(statuses: list[str]) -> ContextStatus:
    for status in ("missing", "ambiguous", "budget_exceeded", "partial"):
        if status in statuses:
            return cast("ContextStatus", status)
    return "complete"


def _bind_context_and_gaps(
    units: list[SnapshotUnit], gaps: list[SnapshotGap]
) -> list[SnapshotUnit]:
    """Propagate unavailable context over the dependency graph without recursion.

    Kahn's leaf-first pass resolves DAGs. Remaining nodes depend on a cycle and
    are ambiguous; a work queue then carries stronger failures through cycles.
    """
    by_id = {unit.unit_id: unit for unit in units}
    parents: dict[str, list[str]] = {key: [] for key in by_id}
    remaining = {unit.unit_id: len(unit.dependencies) for unit in units}
    statuses: dict[str, ContextStatus] = {}
    for unit in units:
        local = [str(unit.metadata["context_status"])]
        if unit.metadata["status"] != "kept" or unit.kind == "gap":
            local.append("partial")
        local.extend(gap.context_status for gap in gaps if gap.locator == unit.locator)
        statuses[unit.unit_id] = _worst_context(local)
        for target in unit.dependencies:
            parents[target].append(unit.unit_id)
    pending = deque(key for key, count in remaining.items() if not count)
    while pending:
        target = pending.popleft()
        for parent in parents[target]:
            statuses[parent] = _worst_context([statuses[parent], statuses[target]])
            remaining[parent] -= 1
            if not remaining[parent]:
                pending.append(parent)
    cyclic = [key for key, count in remaining.items() if count]
    for key in cyclic:
        statuses[key] = _worst_context([statuses[key], "ambiguous"])
    pending.extend(cyclic)
    while pending:
        target = pending.popleft()
        for parent in parents[target]:
            status = _worst_context([statuses[parent], statuses[target]])
            if status != statuses[parent]:
                statuses[parent] = status
                pending.append(parent)
    gaps_hash = _canonical_hash([gap.model_dump(mode="json") for gap in gaps])
    result = []
    for unit in units:
        metadata = deepcopy(unit.metadata)
        metadata.update(context_status=statuses[unit.unit_id], snapshot_gaps_sha256=gaps_hash)
        result.append(
            unit.model_copy(
                update={
                    "metadata": metadata,
                    "metadata_sha256": _canonical_hash(metadata),
                }
            )
        )
    return result


def build_snapshot(reader: SnapshotReader, source_id: str) -> EvidenceSnapshot:
    """Freeze one source/build publication or fail if the head moves during the read."""
    _validate_identifier(source_id, "source_id")
    before = reader.read_head(source_id)
    if before.source_id != source_id:
        raise SnapshotIntegrityError("reader returned a head for another source")
    _validate_identifier(before.build_id, "build_id")
    if before.build_id == source_id:
        raise SnapshotIntegrityError("build_id must not reuse source_id")
    if before.publication_generation < 1:
        raise SnapshotIntegrityError("publication_generation must be positive")

    payload = reader.read_build(before)
    after = reader.read_head(source_id)
    if before != after or payload.head != before:
        raise SnapshotChangedError("active build/publication changed during snapshot read")
    if not payload.units:
        raise SnapshotIntegrityError("snapshot requires at least one exact source unit")

    ids_by_key: dict[tuple[str, str], str] = {}
    keys_by_source_unit: dict[str, list[tuple[str, str]]] = {}
    for source in payload.units:
        if not source.text:
            raise SnapshotIntegrityError(
                f"empty source unit must be represented as a gap: {source}"
            )
        expected_hash = _text_hash(source.text)
        if source.content_hash and _normalize_hash(source.content_hash) != expected_hash:
            raise SnapshotIntegrityError(f"source content hash mismatch: {source.source_unit_id}")
        _validate_cells(source)
        key = _source_key(source)
        if key in ids_by_key:
            raise SnapshotIntegrityError(f"duplicate unit in one chunk: {key}")
        ids_by_key[key] = _unit_key(source)
        keys_by_source_unit.setdefault(source.source_unit_id, []).append(key)

    document_metadata = asdict(payload.document)
    sources_by_key = {_source_key(source): source for source in payload.units}
    units: list[SnapshotUnit] = []
    gaps: list[SnapshotGap] = []
    for source in payload.units:
        dependency_ids: list[str] = []
        dependency_details: list[dict[str, object]] = []
        dependency_statuses: list[DependencyStatus] = []
        cell_dependencies, cell_reasons = _cell_dependencies(source, sources_by_key)
        for dependency in (*source.dependencies, *cell_dependencies):
            status, target_id, reason = _resolve_dependency(
                dependency, source, ids_by_key, keys_by_source_unit
            )
            dependency_statuses.append(status)
            if target_id:
                dependency_ids.append(target_id)
            detail: dict[str, object] = {
                "kind": dependency.kind,
                "status": status,
                "target_unit_id": target_id,
                "required_for": list(dependency.required_for),
                "source_target_unit_id": dependency.target_unit_id,
                "source_target_chunk_id": dependency.target_chunk_id,
            }
            if reason:
                detail["reason"] = reason
            dependency_details.append(detail)
            if status != "present":
                gap_payload = {
                    "source_unit_id": source.source_unit_id,
                    "source_chunk_id": _chunk_locator(source.chunk_id),
                    "dependency": asdict(dependency),
                    "kind": dependency.kind,
                    "status": status,
                    "reason": reason,
                }
                gaps.append(
                    SnapshotGap(
                        gap_id=f"gap:{_canonical_hash(gap_payload).removeprefix(_HASH_PREFIX)}",
                        code=f"dependency_{dependency.kind}_{status}",
                        locator=source.locator,
                        context_status=status,
                    )
                )
        metadata: dict[str, object] = {
            **dict(source.metadata),
            "source_unit_id": source.source_unit_id,
            "source_kind": source.kind,
            "page": source.page,
            "element": source.element,
            "label_path": list(source.label_path),
            "parent_id": source.parent_id,
            "ordinal": source.ordinal,
            "status": source.status,
            "reasons": list(source.reasons),
            "document": document_metadata,
            "cells": [asdict(cell) for cell in source.cells],
            "cell_reasons": cell_reasons,
            "dependency_details": dependency_details,
            "context_status": _worst_context(
                [
                    _context_status(dependency_statuses),
                    "missing" if cell_reasons else "complete",
                ]
            ),
        }
        text_sha256 = _text_hash(source.text)
        units.append(
            SnapshotUnit(
                unit_id=ids_by_key[_source_key(source)],
                chunk_id=_chunk_locator(source.chunk_id),
                kind=_kind(source.kind),
                locator=source.locator,
                text=source.text,
                text_sha256=text_sha256,
                span=SnapshotSpan(
                    text_sha256=text_sha256,
                    start=0,
                    end=len(source.text),
                ),
                metadata=metadata,
                metadata_sha256=_canonical_hash(metadata),
                dependencies=tuple(dict.fromkeys(dependency_ids)),
            )
        )

    for gap in payload.gaps:
        gap_payload = asdict(gap)
        gaps.append(
            SnapshotGap(
                gap_id=f"gap:{_canonical_hash(gap_payload).removeprefix(_HASH_PREFIX)}",
                code=gap.code,
                locator=gap.locator,
                context_status=gap.context_status,
            )
        )
    units = _bind_context_and_gaps(units, gaps)
    parser_versions = _validated_parser_versions(payload.parser_versions, require_snapshot=False)
    parser_versions["snapshot"] = SNAPSHOT_BUILDER_VERSION
    identities = tuple(_identity_of(unit) for unit in units)
    identity_input = SnapshotIdentityInput(
        source_id=source_id,
        build_id=before.build_id,
        publication_generation=before.publication_generation,
        parser_versions=parser_versions,
        unit_identities=identities,
    )
    snapshot = EvidenceSnapshot(
        snapshot_id=_canonical_hash(identity_input.model_dump(mode="json")),
        source_id=source_id,
        build_id=before.build_id,
        publication_generation=before.publication_generation,
        parser_versions=parser_versions,
        units=tuple(units),
        gaps=tuple(gaps),
        identity_input=identity_input,
    )
    snapshot.verify_identity()
    return snapshot


def select_snapshot(snapshot: EvidenceSnapshot, role: SnapshotRole) -> SnapshotSelection:
    """Choose role candidates without changing the shared snapshot identity."""
    snapshot.verify_identity()
    if role == "claims":
        core = {
            unit.unit_id for unit in snapshot.units if unit.kind in {"prose", "table", "image_text"}
        }
        wanted = set(core)
        for unit in snapshot.units:
            if unit.unit_id in core:
                wanted.update(item.unit_id for item in dependency_closure(snapshot, unit))
        selected = tuple(unit for unit in snapshot.units if unit.unit_id in wanted)
    else:
        selected = tuple(unit for unit in snapshot.units if unit.kind != "gap")
    return SnapshotSelection(snapshot_id=snapshot.snapshot_id, role=role, units=selected)


def dependency_closure(snapshot: EvidenceSnapshot, unit: SnapshotUnit) -> tuple[SnapshotUnit, ...]:
    """Return all explicit dependencies once in snapshot order, including cycles safely."""
    by_id = {item.unit_id: item for item in snapshot.units}
    seen = {unit.unit_id}
    pending = list(unit.dependencies)
    while pending:
        key = pending.pop()
        if key not in by_id:
            raise SnapshotIntegrityError("dependency target not in snapshot")
        if key not in seen:
            seen.add(key)
            pending.extend(by_id[key].dependencies)
    seen.remove(unit.unit_id)
    return tuple(item for item in snapshot.units if item.unit_id in seen)


def source_unit_id(unit: SnapshotUnit) -> str:
    """Return the canonical source-unit identity retained in snapshot metadata."""
    value = unit.metadata.get("source_unit_id")
    if not isinstance(value, str) or not value:
        raise SnapshotIntegrityError(f"snapshot unit lacks source_unit_id: {unit.unit_id}")
    return value
