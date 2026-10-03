"""Immutable role-artifact publication and read-only cross-run discovery.

The execution ledger owns model attempts and candidate artifacts.  This module
adds the semantic publication boundary: immutable manifests are written before
one SQLite transaction compares the expected parent and advances the
authoritative source/build head.  ``cache/heads`` is deliberately never read.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from plugins.corpus._semantic_validation import prose_binding_reasons
from plugins.corpus.claims import parse_value
from plugins.corpus.evidence_pipeline import METRICS, EvidenceRun, evidence_document_from_snapshot
from plugins.corpus.material_semantics import MaterialRun
from plugins.corpus.structured.config import canonical_hash
from plugins.corpus.structured.ledger import (
    BatchPlan,
    StructuredExecutionError,
    _hash_bytes,
    _read_object,
    _reader,
    _safe_path,
    _store_root,
    _writer,
)
from plugins.corpus.structured.mapping import resolve_packet_span
from plugins.corpus.structured.roles import ContextStatus, RoleArtifact
from plugins.corpus.structured.snapshot import EvidenceSnapshot, source_unit_id

PUBLICATION_SCHEMA_VERSION = "corpus-semantic-publication-v1"
PUBLICATION_INDEX_SCHEMA_VERSION = "1"
CROSS_ROLE_RULE_VERSION = "cross-role-map-v2"
SUPPORTED_MAPPING_RULES = frozenset({"cross-role-map-v1", "cross-role-map-v2"})
# Frozen v2 conversions: never silently inherit changes to extraction rules.
_QUANTITY_UNITS = {
    "元": (Decimal(1), "元"),
    "万元": (Decimal("1e4"), "元"),
    "百万元": (Decimal("1e6"), "元"),
    "亿元": (Decimal("1e8"), "元"),
    "%": (Decimal(1), "%"),
    "倍": (Decimal(1), "倍"),
}

MappingStatus = Literal["confirmed", "suspected", "unlinked", "conflict"]
ConflictField = Literal[
    "subject",
    "metric",
    "period",
    "value",
    "unit",
    "factuality",
    "polarity",
    "condition",
    "attribution",
]
Lifecycle = Literal["publish", "source_update", "rule_upgrade", "withdraw", "expire"]
Checkpoint = Callable[[str], None]


class ArtifactReference(BaseModel):
    """Exact execution-ledger row selected for one semantic publication."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    batch_id: str
    task_id: str
    artifact_sha256: str


class CrossRoleMapping(BaseModel):
    """Schema-compatible, evidence-bound Claims/R2 association."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_fact_id: str | None
    material_item_id: str | None
    mapping_status: MappingStatus
    rule_version: str = CROSS_ROLE_RULE_VERSION
    evidence_unit_ids: tuple[str, ...] = Field(min_length=1)
    conflict_fields: tuple[ConflictField, ...] = ()

    @model_validator(mode="after")
    def validate_shape(self) -> CrossRoleMapping:
        if not self.rule_version.strip() or len(set(self.evidence_unit_ids)) != len(
            self.evidence_unit_ids
        ):
            raise ValueError("invalid mapping rule or duplicate evidence units")
        both = self.claim_fact_id is not None and self.material_item_id is not None
        if self.mapping_status in {"confirmed", "conflict"} and not both:
            raise ValueError("confirmed/conflict mappings require both records")
        if self.mapping_status == "unlinked" and both:
            raise ValueError("unlinked mapping cannot join two records")
        if self.claim_fact_id is None and self.material_item_id is None:
            raise ValueError("mapping requires at least one record")
        if self.mapping_status == "conflict" and not self.conflict_fields:
            raise ValueError("conflict mapping requires conflict_fields")
        if self.mapping_status != "conflict" and self.conflict_fields:
            raise ValueError("only conflict mappings carry conflict_fields")
        return self


class PublicationCoverage(BaseModel):
    """Independent role coverage retained even for partial publications."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claims: ContextStatus
    material_items: ContextStatus
    material_relations: ContextStatus


class SemanticPublication(BaseModel):
    """Frozen v1 semantic publication manifest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["corpus-semantic-publication-v1"] = PUBLICATION_SCHEMA_VERSION
    publication_id: str
    source_id: str
    build_id: str
    snapshot_id: str
    generation: int = Field(ge=1)
    parent_publication_id: str | None
    artifacts: tuple[str, ...] = Field(min_length=1)
    mappings: tuple[CrossRoleMapping, ...] = ()
    coverage: PublicationCoverage
    publication_status: Literal["candidate", "published", "withdrawn", "superseded"]
    quality_status: Literal["unassessed", "accepted", "review_required", "rejected"]
    reason_codes: tuple[str, ...] = ()

    def verify_identity(self) -> None:
        expected = canonical_hash(self.model_dump(mode="json", exclude={"publication_id"}))
        if self.publication_id != expected:
            raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "publication_identity_mismatch")


class PublishedArtifact(BaseModel):
    """Read-only artifact projection; raw responses and credentials are excluded."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reference: ArtifactReference
    artifact: RoleArtifact
    payload: EvidenceRun | MaterialRun


class PublicationView(BaseModel):
    """Verified manifest plus effective use/relationship state for consumers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest: SemanticPublication
    snapshot: EvidenceSnapshot
    lifecycle: Lifecycle
    artifacts: tuple[PublishedArtifact, ...]
    effective_claim_purposes: dict[str, tuple[str, ...]]
    active_relation_ids: tuple[str, ...]


@dataclass(frozen=True)
class _RecordEvidence:
    unit_ids: frozenset[str]
    spans: frozenset[tuple[str, int, int]]
    text: str
    value: str | None = None
    factuality: str | None = None
    unit: str | None = None
    polarity: str | None = None
    condition: str | None = None
    attribution: str | None = None
    binding: tuple[str, ...] = ()
    unknown_fields: frozenset[str] = frozenset()


@dataclass(frozen=True)
class _Candidate:
    reference: ArtifactReference
    artifact: RoleArtifact
    payload: EvidenceRun | MaterialRun
    snapshot: EvidenceSnapshot
    claims: dict[str, _RecordEvidence]
    items: dict[str, _RecordEvidence]


def _noop_checkpoint(_name: str) -> None:
    return None


def _publication_schema(connection: sqlite3.Connection) -> None:
    try:
        row = connection.execute(
            "SELECT value FROM ledger_metadata WHERE key='semantic_publication_schema_version'"
        ).fetchone()
    except sqlite3.DatabaseError as exc:
        raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "publication_index_invalid") from exc
    if row is None or row[0] != PUBLICATION_INDEX_SCHEMA_VERSION:
        raise StructuredExecutionError("CS_SCHEMA_UNSUPPORTED", "publication_index_schema_version")


def _write_json_file(
    root: Path, path: Path, value: object, *, replace_existing: bool = False
) -> str:
    path = _safe_path(root, path, "publication_path_escape")
    directory = _safe_path(root, path.parent, "publication_path_escape")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    digest = _hash_bytes(raw)
    if path.exists() and not replace_existing:
        try:
            existing = path.read_bytes()
        except PermissionError as exc:
            raise StructuredExecutionError(
                "CS_STORE_ROOT_REQUIRED", "structured_store_permission_denied"
            ) from exc
        if existing != raw:
            raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "immutable_manifest_collision")
        return digest
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=".pending-", suffix=".json", dir=directory)
    except PermissionError as exc:
        raise StructuredExecutionError(
            "CS_STORE_ROOT_REQUIRED", "structured_store_permission_denied"
        ) from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except PermissionError as exc:
        raise StructuredExecutionError(
            "CS_STORE_ROOT_REQUIRED", "structured_store_permission_denied"
        ) from exc
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary)
    return digest


def _manifest_path(root: Path, publication_id: str) -> Path:
    if not publication_id.startswith("sha256:") or len(publication_id) != 71:
        raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "invalid_publication_id")
    return _safe_path(root, root / "manifests" / f"{publication_id}.json", "manifest_path_escape")


def _read_manifest(root: Path, relative: str, expected_sha: str) -> SemanticPublication:
    path = _safe_path(root, root / relative, "manifest_path_escape")
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise StructuredExecutionError("CS_NOT_FOUND", "manifest_not_found") from exc
    except PermissionError as exc:
        raise StructuredExecutionError(
            "CS_STORE_ROOT_REQUIRED", "structured_store_permission_denied"
        ) from exc
    if _hash_bytes(raw) != expected_sha:
        raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "manifest_hash_mismatch")
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "manifest_json_invalid") from exc
    if not isinstance(value, dict) or value.get("schema_version") != PUBLICATION_SCHEMA_VERSION:
        raise StructuredExecutionError("CS_SCHEMA_UNSUPPORTED", "publication_schema_version")
    try:
        manifest = SemanticPublication.model_validate(value)
    except ValueError as exc:
        raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "manifest_shape_invalid") from exc
    manifest.verify_identity()
    return manifest


def _unit_reference(
    snapshot: EvidenceSnapshot,
    value: dict[str, Any],
) -> tuple[str, tuple[str, int, int]]:
    if value.get("doc_id") != f"cv2:{snapshot.build_id}":
        raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "evidence_build_mismatch")
    start, end = value.get("start"), value.get("end")
    for unit in snapshot.units:
        if unit.chunk_id == value.get("chunk_id") and source_unit_id(unit) == value.get("unit_id"):
            if (
                value.get("locator") != unit.locator
                or value.get("text_sha256") != unit.text_sha256
                or type(start) is not int
                or type(end) is not int
                or not 0 <= start < end <= len(unit.text)
                or value.get("quote") != unit.text[start:end]
            ):
                break
            return unit.unit_id, (unit.chunk_id, start, end)
    raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "evidence_reference_invalid")


def _claim_records(run: EvidenceRun, snapshot: EvidenceSnapshot) -> dict[str, _RecordEvidence]:
    result: dict[str, _RecordEvidence] = {}
    for fact in run.facts:
        if fact.fact_id in result or not set(fact.usable_for) <= {"cite", "compare", "calculate"}:
            raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "claim_identity_or_purpose")
        alignment = fact.evidence_alignment
        if not isinstance(alignment, dict):
            raise StructuredExecutionError("CS_CONTEXT_INCOMPLETE", "claim_evidence_unmapped")
        spans = alignment.get("source_spans")
        if not isinstance(spans, list) or not spans:
            raise StructuredExecutionError("CS_CONTEXT_INCOMPLETE", "claim_evidence_unmapped")
        units: set[str] = set()
        ranges: set[tuple[str, int, int]] = set()
        quotes: list[str] = []
        for span in spans:
            if not isinstance(span, dict):
                raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "claim_evidence_shape")
            unit_id, interval = _unit_reference(snapshot, span)
            units.add(unit_id)
            ranges.add(interval)
            quotes.append(cast(str, span["quote"]))
        dependency_details = alignment.get("dependency_details", [])
        if not isinstance(dependency_details, list):
            raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "claim_dependency_shape")
        dependency_spans = alignment.get("dependency_spans", [])
        if not isinstance(dependency_spans, list):
            raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "claim_dependency_shape")
        dependency_units: set[str] = set()
        for span in dependency_spans:
            if not isinstance(span, dict):
                raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "claim_dependency_shape")
            unit_id, _interval = _unit_reference(snapshot, span)
            dependency_units.add(unit_id)
        for detail in dependency_details:
            if not isinstance(detail, dict):
                raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "claim_dependency_shape")
            required = detail.get("required_for", [])
            if not isinstance(required, list) or (
                set(fact.usable_for) & set(map(str, required)) and detail.get("status") != "present"
            ):
                raise StructuredExecutionError(
                    "CS_CONTEXT_INCOMPLETE", "claim_required_dependency_unavailable"
                )
            if (
                set(fact.usable_for) & set(map(str, required))
                and detail.get("status") == "present"
                and detail.get("target_unit_id") not in dependency_units | units
            ):
                raise StructuredExecutionError(
                    "CS_CONTEXT_INCOMPLETE", "claim_required_dependency_unmapped"
                )
        quote = fact.claim.evidence_quote or ""
        if quote and quote not in "\n".join(quotes):
            raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "claim_quote_mismatch")
        result[fact.fact_id] = _RecordEvidence(
            frozenset(units),
            frozenset(ranges),
            fact.claim.claim_text,
            fact.claim.value_text,
            fact.claim.kind,
            unit=fact.claim.unit_raw,
        )
        # Claims has no universal polarity/attribution fields. Only project the
        # small, verified affirmative numeric grammar; other language is unknown.
        binding = (fact.claim.subject, fact.claim.metric_raw, fact.claim.period_raw)
        atomic = (
            not prose_binding_reasons(fact.claim, METRICS)
            and all(token and _normalized(token) in _normalized(quote) for token in binding)
            and not re.search(r"否认|不是|并非|未|不|如果|只要|除非|称|表示|认为|[：:‘’“”]", quote)
            and not dependency_details
            and not re.search(r"[。；;！？!?].+", quote.rstrip("。；;！？!?"))
        )
        if atomic:
            result[fact.fact_id] = replace(
                result[fact.fact_id],
                polarity="affirmed",
                condition="unconditional",
                attribution="document_voice",
                binding=tuple(cast(str, token) for token in binding),
            )
    return result


def _material_record_evidence(
    run: MaterialRun,
    snapshot: EvidenceSnapshot,
    record_id: str,
    text: str,
    value: str | None,
    factuality: str | None,
    evidence: Sequence[Any],
) -> _RecordEvidence:
    document = evidence_document_from_snapshot(snapshot, role="material_items")
    packets = {packet.packet_id: packet for packet in document.packets}
    units: set[str] = set()
    ranges: set[tuple[str, int, int]] = set()
    if not evidence:
        raise StructuredExecutionError("CS_CONTEXT_INCOMPLETE", "material_evidence_missing")
    for proof in evidence:
        packet = packets.get(proof.packet_id)
        if (
            packet is None
            or proof.source_rev != snapshot.snapshot_id
            or proof.locator != packet.locator
            or type(proof.start) is not int
            or type(proof.end) is not int
            or not 0 <= proof.start < proof.end <= len(packet.text)
            or proof.quote != packet.text[proof.start : proof.end]
        ):
            raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "material_evidence_invalid")
        try:
            references = resolve_packet_span(snapshot, packet, proof.start, proof.end)
        except ValueError as exc:
            raise StructuredExecutionError(
                "CS_ARTIFACT_CORRUPT", "material_evidence_unmapped"
            ) from exc
        for reference in references:
            for unit in snapshot.units:
                if (
                    unit.chunk_id == reference.chunk_id
                    and source_unit_id(unit) == reference.unit_id
                ):
                    units.add(unit.unit_id)
                    ranges.add((unit.chunk_id, reference.start, reference.end))
                    break
            else:
                raise StructuredExecutionError(
                    "CS_ARTIFACT_CORRUPT", "material_evidence_reference_invalid"
                )
    if not units:
        raise StructuredExecutionError("CS_CONTEXT_INCOMPLETE", "material_evidence_unmapped")
    return _RecordEvidence(frozenset(units), frozenset(ranges), text, value, factuality)


def _material_records(
    run: MaterialRun, snapshot: EvidenceSnapshot
) -> tuple[dict[str, _RecordEvidence], set[str]]:
    items: dict[str, _RecordEvidence] = {}
    for item in run.understanding.items:
        if item.item_id in items or "evidence_context" in item.unknown_fields:
            raise StructuredExecutionError(
                "CS_CONTEXT_INCOMPLETE", "material_item_identity_or_context"
            )
        items[item.item_id] = _material_record_evidence(
            run,
            snapshot,
            item.item_id,
            item.text,
            item.value,
            item.semantic_type,
            item.evidence,
        )
        speaker = next(
            (
                speaker
                for speaker in run.understanding.speakers
                if speaker.speaker_id == item.speaker_ref
            ),
            None,
        )
        items[item.item_id] = replace(
            items[item.item_id],
            unknown_fields=frozenset(
                {
                    "semantic_type": "factuality",
                    "speaker_identity": "attribution",
                    "speaker_reference": "attribution",
                }.get(field, field)
                for field in item.unknown_fields
            ),
            polarity=item.polarity if item.polarity != "unknown" else None,
            condition=(
                "conditional"
                if item.statement_role == "condition"
                else None
                if re.search(r"如果|只要|除非|前提|取决于", item.text)
                else "unconditional"
            ),
            attribution=(
                "document_voice"
                if speaker and speaker.role == "document_voice"
                else speaker.display_name
                if speaker and speaker.identity_status == "explicit"
                else None
            ),
        )
    relation_ids: set[str] = set()
    for relation in run.understanding.relations:
        if relation.relation_id in relation_ids:
            raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "relation_identity_duplicate")
        relation_ids.add(relation.relation_id)
        _material_record_evidence(
            run,
            snapshot,
            relation.relation_id,
            relation.type,
            None,
            None,
            relation.evidence,
        )
    return items, relation_ids


def _load_candidate(
    connection: sqlite3.Connection, root: Path, reference: ArtifactReference
) -> _Candidate:
    row = connection.execute(
        "SELECT t.*, b.plan_json, b.snapshot_id AS batch_snapshot_id "
        "FROM tasks t JOIN batches b ON b.batch_id=t.batch_id "
        "WHERE t.batch_id=? AND t.task_id=?",
        (reference.batch_id, reference.task_id),
    ).fetchone()
    if row is None:
        raise StructuredExecutionError("CS_NOT_FOUND", "publication_task_not_found")
    if row["artifact_sha256"] != reference.artifact_sha256:
        raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "publication_artifact_binding")
    if (
        row["execution_status"] != "succeeded"
        or row["protocol_status"] != "valid"
        or row["quality_status"] != "accepted"
        or row["publication_status"] not in {"candidate", "published"}
        or not row["payload_object_sha256"]
    ):
        raise StructuredExecutionError("CS_DEPENDENCY_NOT_READY", "artifact_not_publishable")
    if row["method"] == "model":
        attempt = connection.execute(
            "SELECT 1 FROM attempts WHERE batch_id=? AND task_id=? "
            "AND execution_status='succeeded' LIMIT 1",
            (reference.batch_id, reference.task_id),
        ).fetchone()
        if attempt is None:
            raise StructuredExecutionError("CS_DEPENDENCY_NOT_READY", "attempt_reference_missing")
    try:
        plan = BatchPlan.model_validate_json(row["plan_json"])
        plan.verify_identity()
        artifact = RoleArtifact.model_validate(_read_object(root, reference.artifact_sha256))
        artifact.verify_identity()
        raw_payload = _read_object(root, row["payload_object_sha256"])
        payload: EvidenceRun | MaterialRun
        if artifact.business_contract == "EvidenceRun/EvidenceFact":
            payload = EvidenceRun.model_validate(raw_payload)
        else:
            payload = MaterialRun.model_validate(raw_payload)
        payload.verify_identity()
    except StructuredExecutionError:
        raise
    except (ValueError, TypeError) as exc:
        raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "role_artifact_invalid") from exc
    if (
        artifact.task_id != reference.task_id
        or artifact.snapshot_id != plan.snapshot.snapshot_id
        or artifact.role != row["role"]
        or artifact.protocol != row["protocol"]
        or artifact.payload_sha256 != canonical_hash(payload.model_dump(mode="json"))
    ):
        raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "role_artifact_binding")
    claims: dict[str, _RecordEvidence] = {}
    items: dict[str, _RecordEvidence] = {}
    if isinstance(payload, EvidenceRun):
        claims = _claim_records(payload, plan.snapshot)
    else:
        items, _relation_ids = _material_records(payload, plan.snapshot)
    return _Candidate(reference, artifact, payload, plan.snapshot, claims, items)


def _overlap(left: _RecordEvidence, right: _RecordEvidence) -> bool:
    for left_chunk, left_start, left_end in left.spans:
        for right_chunk, right_start, right_end in right.spans:
            if left_chunk == right_chunk and left_start < right_end and right_start < left_end:
                return True
    return False


def _normalized(value: str | None) -> str:
    return "".join((value or "").lower().split())


def _conflicts_v1(claim: _RecordEvidence, item: _RecordEvidence) -> tuple[ConflictField, ...]:
    """Frozen legacy rule, retained solely for reproducing v1 publications."""
    result: list[ConflictField] = []
    if claim.value and item.value and _normalized(claim.value) != _normalized(item.value):
        result.append("value")
    if (
        claim.factuality in {"fact", "forecast"}
        and item.factuality in {"fact", "forecast"}
        and claim.factuality != item.factuality
    ):
        result.append("factuality")
    return tuple(result)


def _quantity(record: _RecordEvidence) -> tuple[Decimal, str] | None:
    if record.unknown_fields & {"value", "unit"}:
        return None
    number, suffix = parse_value(record.value)
    unit = suffix or record.unit
    if number is None or unit not in _QUANTITY_UNITS:
        return None
    scale, dimension = _QUANTITY_UNITS[unit]
    return number * scale, dimension


def _conflicts(
    claim: _RecordEvidence, item: _RecordEvidence, rule_version: str
) -> tuple[ConflictField, ...]:
    if rule_version == "cross-role-map-v1":
        return _conflicts_v1(claim, item)
    result: list[ConflictField] = []
    left, right = _quantity(claim), _quantity(item)
    if left is not None and right is not None:
        if left[1] != right[1]:
            result.append("unit")
        elif left[0] != right[0]:
            result.append("value")
    for field in ("factuality", "polarity", "condition", "attribution"):
        a, b = getattr(claim, field), getattr(item, field)
        if (
            a is not None
            and b is not None
            and a != b
            and field not in claim.unknown_fields | item.unknown_fields
        ):
            result.append(cast(ConflictField, field))
    return tuple(result)


def _same_proposition(claim: _RecordEvidence, item: _RecordEvidence, rule: str) -> bool:
    if rule == "cross-role-map-v1":
        return _normalized(claim.text) in _normalized(item.text) or _normalized(
            item.text
        ) in _normalized(claim.text)
    # Exact atomic evidence plus source-bound subject/metric/period. No broad
    # item containing several propositions, or caller-supplied mapping, can
    # promote a mere overlapping locator to a confirmed association.
    return bool(
        claim.binding
        and "text" not in item.unknown_fields
        and claim.spans == item.spans
        and len(claim.spans) == 1
        and all(_normalized(item.text).count(_normalized(token)) == 1 for token in claim.binding)
        and not re.search(r"[。；;！？!?].+", item.text.rstrip("。；;！？!?"))
    )


def _comparison_complete(claim: _RecordEvidence, item: _RecordEvidence, rule: str) -> bool:
    return rule == "cross-role-map-v1" or (
        not (
            (claim.unknown_fields | item.unknown_fields)
            & {"text", "value", "unit", "factuality", "polarity", "condition", "attribution"}
        )
        and _quantity(claim) is not None
        and _quantity(item) is not None
        and all(
            getattr(record, field) is not None
            for record in (claim, item)
            for field in ("factuality", "polarity", "condition", "attribution")
        )
    )


def _auto_mappings(
    claims: dict[str, _RecordEvidence], items: dict[str, _RecordEvidence]
) -> tuple[CrossRoleMapping, ...]:
    mappings: list[CrossRoleMapping] = []
    claimed_items: set[str] = set()
    for fact_id, claim in sorted(claims.items()):
        candidates = [
            (item_id, item)
            for item_id, item in sorted(items.items())
            if claim.unit_ids & item.unit_ids and _overlap(claim, item)
        ]
        semantic = [
            (item_id, item)
            for item_id, item in candidates
            if _same_proposition(claim, item, CROSS_ROLE_RULE_VERSION)
        ]
        if len(semantic) == 1:
            item_id, item = semantic[0]
            fields = _conflicts(claim, item, CROSS_ROLE_RULE_VERSION)
            mappings.append(
                CrossRoleMapping(
                    claim_fact_id=fact_id,
                    material_item_id=item_id,
                    mapping_status=(
                        "conflict"
                        if fields
                        else "confirmed"
                        if _comparison_complete(claim, item, CROSS_ROLE_RULE_VERSION)
                        else "suspected"
                    ),
                    rule_version=CROSS_ROLE_RULE_VERSION,
                    evidence_unit_ids=tuple(sorted(claim.unit_ids & item.unit_ids)),
                    conflict_fields=fields,
                )
            )
            claimed_items.add(item_id)
        elif candidates:
            item_id, item = candidates[0]
            mappings.append(
                CrossRoleMapping(
                    claim_fact_id=fact_id,
                    material_item_id=item_id,
                    mapping_status="suspected",
                    rule_version=CROSS_ROLE_RULE_VERSION,
                    evidence_unit_ids=tuple(sorted(claim.unit_ids & item.unit_ids)),
                )
            )
            claimed_items.add(item_id)
        else:
            mappings.append(
                CrossRoleMapping(
                    claim_fact_id=fact_id,
                    material_item_id=None,
                    mapping_status="unlinked",
                    rule_version=CROSS_ROLE_RULE_VERSION,
                    evidence_unit_ids=tuple(sorted(claim.unit_ids)),
                )
            )
    for item_id, item in sorted(items.items()):
        if item_id not in claimed_items:
            mappings.append(
                CrossRoleMapping(
                    claim_fact_id=None,
                    material_item_id=item_id,
                    mapping_status="unlinked",
                    rule_version=CROSS_ROLE_RULE_VERSION,
                    evidence_unit_ids=tuple(sorted(item.unit_ids)),
                )
            )
    return tuple(mappings)


def _validate_mappings(
    mappings: Sequence[CrossRoleMapping],
    claims: dict[str, _RecordEvidence],
    items: dict[str, _RecordEvidence],
    snapshot: EvidenceSnapshot,
) -> tuple[CrossRoleMapping, ...]:
    known_units = {unit.unit_id for unit in snapshot.units}
    result = tuple(mappings)
    seen_claims: set[str] = set()
    seen_items: set[str] = set()
    for mapping in result:
        if (
            mapping.rule_version not in SUPPORTED_MAPPING_RULES
            or not set(mapping.evidence_unit_ids) <= known_units
        ):
            raise StructuredExecutionError("CS_INPUT_INVALID", "mapping_rule_or_evidence")
        claim = claims.get(mapping.claim_fact_id) if mapping.claim_fact_id else None
        item = items.get(mapping.material_item_id) if mapping.material_item_id else None
        if (mapping.claim_fact_id and claim is None) or (mapping.material_item_id and item is None):
            raise StructuredExecutionError("CS_INPUT_INVALID", "mapping_record_not_selected")
        if claim is not None:
            seen_claims.add(cast(str, mapping.claim_fact_id))
        if item is not None:
            seen_items.add(cast(str, mapping.material_item_id))
        evidence = set(mapping.evidence_unit_ids)
        if claim is not None and not evidence <= claim.unit_ids:
            raise StructuredExecutionError("CS_INPUT_INVALID", "mapping_claim_evidence_mismatch")
        if item is not None and not evidence <= item.unit_ids:
            raise StructuredExecutionError("CS_INPUT_INVALID", "mapping_item_evidence_mismatch")
        if claim is not None and item is not None:
            if not _overlap(claim, item):
                raise StructuredExecutionError("CS_INPUT_INVALID", "mapping_span_mismatch")
            bound = mapping.rule_version == "cross-role-map-v1" or _same_proposition(
                claim, item, mapping.rule_version
            )
            if mapping.mapping_status in {"confirmed", "conflict"} and not bound:
                raise StructuredExecutionError("CS_INPUT_INVALID", "mapping_proposition_unproven")
            actual = _conflicts(claim, item, mapping.rule_version) if bound else ()
            if mapping.mapping_status != "conflict" and actual:
                raise StructuredExecutionError("CS_INPUT_INVALID", "mapping_hides_conflict")
            if mapping.mapping_status == "conflict" and set(mapping.conflict_fields) != set(actual):
                raise StructuredExecutionError("CS_INPUT_INVALID", "mapping_conflict_unproven")
            if mapping.mapping_status == "confirmed" and not _comparison_complete(
                claim, item, mapping.rule_version
            ):
                raise StructuredExecutionError("CS_INPUT_INVALID", "mapping_comparison_incomplete")
    if seen_claims != set(claims) or seen_items != set(items):
        raise StructuredExecutionError("CS_INPUT_INVALID", "mapping_coverage_incomplete")
    return result


def _coverage(candidates: Sequence[_Candidate]) -> PublicationCoverage:
    rank = {"complete": 0, "partial": 1, "ambiguous": 2, "budget_exceeded": 3, "missing": 4}
    by_role: dict[str, list[ContextStatus]] = {
        "claims": [],
        "material_items": [],
        "material_relations": [],
    }
    for candidate in candidates:
        by_role[candidate.artifact.role].append(candidate.artifact.context_status)
    values: dict[str, ContextStatus] = {}
    for role, statuses in by_role.items():
        values[role] = max(statuses, key=rank.__getitem__) if statuses else "missing"
    return PublicationCoverage.model_validate(values)


def _validate_relations(candidates: Sequence[_Candidate], selected_items: set[str]) -> None:
    for candidate in candidates:
        if candidate.artifact.role != "material_relations":
            continue
        if not isinstance(candidate.payload, MaterialRun):
            raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "relation_payload_type")
        if not set(candidate.artifact.upstream_artifact_ids) <= {
            value.artifact.artifact_id
            for value in candidates
            if value.artifact.role == "material_items"
        }:
            raise StructuredExecutionError("CS_DEPENDENCY_NOT_READY", "relation_upstream_invalid")
        for relation in candidate.payload.understanding.relations:
            if relation.from_item not in selected_items or relation.to_item not in selected_items:
                raise StructuredExecutionError(
                    "CS_DEPENDENCY_NOT_READY", "relation_endpoint_not_published"
                )


def _cache_path(root: Path, source_id: str, build_id: str) -> Path:
    key = canonical_hash({"source_id": source_id, "build_id": build_id})[7:]
    return _safe_path(root, root / "cache" / "heads" / f"{key}.json", "cache_path_escape")


def _refresh_head_cache(
    connection: sqlite3.Connection, root: Path, source_id: str, build_id: str
) -> None:
    # Re-read the authoritative head under the writer lock: a delayed P1
    # callback must not overwrite P2's cache with its stale local manifest.
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute(
            "SELECT source_id, build_id, generation, publication_id, manifest_sha256 "
            "FROM semantic_publication_heads WHERE source_id=? AND build_id=?",
            (source_id, build_id),
        ).fetchone()
        if row is not None:
            _write_json_file(
                root, _cache_path(root, source_id, build_id), dict(row), replace_existing=True
            )
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise


def publish_semantic(
    *,
    source_id: str,
    build_id: str,
    snapshot_id: str,
    artifacts: Sequence[ArtifactReference],
    expected_parent_publication_id: str | None,
    store_root: str | Path | None = None,
    mappings: Sequence[CrossRoleMapping] | None = None,
    reason_codes: Sequence[str] = (),
    lifecycle: Literal["publish", "source_update", "rule_upgrade"] = "publish",
    checkpoint: Checkpoint = _noop_checkpoint,
) -> SemanticPublication:
    """Publish accepted ledger artifacts after an atomic expected-parent check."""
    root = _store_root(store_root, write=True)
    if not artifacts or len({item.artifact_sha256 for item in artifacts}) != len(artifacts):
        raise StructuredExecutionError("CS_INPUT_INVALID", "publication_artifacts_invalid")
    connection = _writer(root)
    try:
        _publication_schema(connection)
        candidates = [_load_candidate(connection, root, item) for item in artifacts]
        snapshots = {candidate.snapshot.snapshot_id for candidate in candidates}
        if snapshots != {snapshot_id} or any(
            candidate.snapshot.source_id != source_id or candidate.snapshot.build_id != build_id
            for candidate in candidates
        ):
            raise StructuredExecutionError("CS_INPUT_INVALID", "publication_source_binding")
        claims: dict[str, _RecordEvidence] = {}
        items: dict[str, _RecordEvidence] = {}
        for candidate in candidates:
            if set(claims) & set(candidate.claims) or set(items) & set(candidate.items):
                raise StructuredExecutionError("CS_INPUT_INVALID", "publication_record_ambiguous")
            claims.update(candidate.claims)
            items.update(candidate.items)
        _validate_relations(candidates, set(items))
        detected_mappings = _auto_mappings(claims, items)
        final_mappings = _validate_mappings(
            mappings if mappings is not None else detected_mappings,
            claims,
            items,
            candidates[0].snapshot,
        )
        if any(mapping.rule_version != CROSS_ROLE_RULE_VERSION for mapping in final_mappings):
            raise StructuredExecutionError("CS_INPUT_INVALID", "publication_requires_current_rules")
        detected_conflicts = {
            (mapping.claim_fact_id, mapping.material_item_id, mapping.conflict_fields)
            for mapping in detected_mappings
            if mapping.mapping_status == "conflict"
        }
        declared_conflicts = {
            (mapping.claim_fact_id, mapping.material_item_id, mapping.conflict_fields)
            for mapping in final_mappings
            if mapping.mapping_status == "conflict"
        }
        if not detected_conflicts <= declared_conflicts:
            raise StructuredExecutionError("CS_INPUT_INVALID", "mapping_hides_conflict")
        connection.execute("BEGIN IMMEDIATE")
        try:
            head = connection.execute(
                "SELECT generation, publication_id FROM semantic_publication_heads "
                "WHERE source_id=? AND build_id=?",
                (source_id, build_id),
            ).fetchone()
            actual_parent = head["publication_id"] if head is not None else None
            if actual_parent != expected_parent_publication_id:
                raise StructuredExecutionError(
                    "CS_PUBLICATION_CONFLICT", "publication_parent_changed"
                )
            if lifecycle == "source_update" and head is not None:
                raise StructuredExecutionError(
                    "CS_INPUT_INVALID", "source_update_requires_new_build_head"
                )
            if lifecycle == "rule_upgrade" and head is None:
                raise StructuredExecutionError("CS_INPUT_INVALID", "rule_upgrade_requires_parent")
            generation = (head["generation"] if head is not None else 0) + 1
            base = SemanticPublication(
                publication_id="sha256:" + "0" * 64,
                source_id=source_id,
                build_id=build_id,
                snapshot_id=snapshot_id,
                generation=generation,
                parent_publication_id=actual_parent,
                artifacts=tuple(sorted(item.artifact_sha256 for item in artifacts)),
                mappings=tuple(
                    sorted(
                        final_mappings,
                        key=lambda value: (
                            value.claim_fact_id or "",
                            value.material_item_id or "",
                            value.mapping_status,
                        ),
                    )
                ),
                coverage=_coverage(candidates),
                publication_status="published",
                quality_status="accepted",
                reason_codes=tuple(
                    dict.fromkeys(
                        (
                            *reason_codes,
                            *(
                                ("CROSS_ROLE_COMPARISON_UNPROVEN",)
                                if any(
                                    mapping.mapping_status == "suspected"
                                    for mapping in final_mappings
                                )
                                else ()
                            ),
                        )
                    )
                ),
            )
            publication_id = canonical_hash(
                base.model_dump(mode="json", exclude={"publication_id"})
            )
            manifest = base.model_copy(update={"publication_id": publication_id})
            manifest.verify_identity()
            manifest_path = _manifest_path(root, publication_id)
            manifest_sha = _write_json_file(root, manifest_path, manifest.model_dump(mode="json"))
            checkpoint("after_manifest_write")
            relative = manifest_path.relative_to(root).as_posix()
            connection.execute(
                "INSERT INTO semantic_publications("
                "publication_id, source_id, build_id, snapshot_id, generation, "
                "parent_publication_id, manifest_sha256, manifest_relpath, "
                "publication_status, quality_status, lifecycle) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'published', 'accepted', ?)",
                (
                    publication_id,
                    source_id,
                    build_id,
                    snapshot_id,
                    generation,
                    actual_parent,
                    manifest_sha,
                    relative,
                    lifecycle,
                ),
            )
            by_hash = {candidate.reference.artifact_sha256: candidate for candidate in candidates}
            for artifact_sha in manifest.artifacts:
                candidate = by_hash[artifact_sha]
                row = connection.execute(
                    "SELECT payload_object_sha256 FROM tasks WHERE batch_id=? AND task_id=?",
                    (candidate.reference.batch_id, candidate.reference.task_id),
                ).fetchone()
                assert row is not None
                connection.execute(
                    "INSERT INTO semantic_publication_artifacts("
                    "publication_id, artifact_sha256, batch_id, task_id, role, "
                    "artifact_id, payload_object_sha256) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        publication_id,
                        artifact_sha,
                        candidate.reference.batch_id,
                        candidate.reference.task_id,
                        candidate.artifact.role,
                        candidate.artifact.artifact_id,
                        row["payload_object_sha256"],
                    ),
                )
                connection.execute(
                    "UPDATE tasks SET publication_status='published' "
                    "WHERE batch_id=? AND task_id=?",
                    (candidate.reference.batch_id, candidate.reference.task_id),
                )
            connection.execute(
                "INSERT INTO semantic_publication_heads("
                "source_id, build_id, generation, publication_id, manifest_sha256, lifecycle) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(source_id, build_id) DO UPDATE SET "
                "generation=excluded.generation, publication_id=excluded.publication_id, "
                "manifest_sha256=excluded.manifest_sha256, lifecycle=excluded.lifecycle",
                (source_id, build_id, generation, publication_id, manifest_sha, lifecycle),
            )
            connection.execute("COMMIT")
        except BaseException:
            with suppress(sqlite3.DatabaseError):
                connection.execute("ROLLBACK")
            raise
        checkpoint("after_db_commit")
        with suppress(OSError, StructuredExecutionError, sqlite3.DatabaseError):
            _refresh_head_cache(connection, root, source_id, build_id)
        return manifest
    finally:
        connection.close()


def retire_semantic(
    *,
    source_id: str,
    build_id: str,
    expected_parent_publication_id: str,
    expired: bool = False,
    store_root: str | Path | None = None,
    checkpoint: Checkpoint = _noop_checkpoint,
) -> SemanticPublication:
    """Advance the head to a distinct withdrawn or expired immutable manifest."""
    root = _store_root(store_root, write=True)
    connection = _writer(root)
    try:
        _publication_schema(connection)
        row = connection.execute(
            "SELECT p.*, h.publication_id AS head_id FROM semantic_publications p "
            "JOIN semantic_publication_heads h ON h.source_id=p.source_id AND h.build_id=p.build_id "
            "WHERE p.publication_id=? AND p.source_id=? AND p.build_id=?",
            (expected_parent_publication_id, source_id, build_id),
        ).fetchone()
        if row is None or row["head_id"] != expected_parent_publication_id:
            raise StructuredExecutionError("CS_PUBLICATION_CONFLICT", "publication_parent_changed")
        previous = _read_manifest(root, row["manifest_relpath"], row["manifest_sha256"])
        if previous.publication_status != "published":
            raise StructuredExecutionError("CS_PUBLICATION_CONFLICT", "publication_already_retired")
        connection.execute("BEGIN IMMEDIATE")
        try:
            head = connection.execute(
                "SELECT generation, publication_id FROM semantic_publication_heads "
                "WHERE source_id=? AND build_id=?",
                (source_id, build_id),
            ).fetchone()
            if head is None or head["publication_id"] != expected_parent_publication_id:
                raise StructuredExecutionError(
                    "CS_PUBLICATION_CONFLICT", "publication_parent_changed"
                )
            base = previous.model_copy(
                update={
                    "publication_id": "sha256:" + "0" * 64,
                    "generation": head["generation"] + 1,
                    "parent_publication_id": expected_parent_publication_id,
                    "publication_status": "withdrawn",
                    "reason_codes": tuple(
                        dict.fromkeys(
                            (
                                *previous.reason_codes,
                                "SEMANTIC_EXPIRED" if expired else "SEMANTIC_WITHDRAWN",
                            )
                        )
                    ),
                }
            )
            publication_id = canonical_hash(
                base.model_dump(mode="json", exclude={"publication_id"})
            )
            manifest = base.model_copy(update={"publication_id": publication_id})
            path = _manifest_path(root, publication_id)
            manifest_sha = _write_json_file(root, path, manifest.model_dump(mode="json"))
            checkpoint("after_manifest_write")
            lifecycle: Lifecycle = "expire" if expired else "withdraw"
            connection.execute(
                "INSERT INTO semantic_publications VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    publication_id,
                    source_id,
                    build_id,
                    manifest.snapshot_id,
                    manifest.generation,
                    expected_parent_publication_id,
                    manifest_sha,
                    path.relative_to(root).as_posix(),
                    "withdrawn",
                    manifest.quality_status,
                    lifecycle,
                ),
            )
            prior_artifacts = connection.execute(
                "SELECT * FROM semantic_publication_artifacts WHERE publication_id=?",
                (expected_parent_publication_id,),
            ).fetchall()
            for artifact in prior_artifacts:
                connection.execute(
                    "INSERT INTO semantic_publication_artifacts VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        publication_id,
                        artifact["artifact_sha256"],
                        artifact["batch_id"],
                        artifact["task_id"],
                        artifact["role"],
                        artifact["artifact_id"],
                        artifact["payload_object_sha256"],
                    ),
                )
            connection.execute(
                "UPDATE semantic_publication_heads SET generation=?, publication_id=?, "
                "manifest_sha256=?, lifecycle=? WHERE source_id=? AND build_id=?",
                (
                    manifest.generation,
                    publication_id,
                    manifest_sha,
                    lifecycle,
                    source_id,
                    build_id,
                ),
            )
            connection.execute("COMMIT")
        except BaseException:
            with suppress(sqlite3.DatabaseError):
                connection.execute("ROLLBACK")
            raise
        checkpoint("after_db_commit")
        with suppress(OSError, StructuredExecutionError, sqlite3.DatabaseError):
            _refresh_head_cache(connection, root, source_id, build_id)
        return manifest
    finally:
        connection.close()


def read_semantic(
    source_id: str,
    build_id: str,
    *,
    publication_id: str | None = None,
    allow_historical: bool = False,
    store_root: str | Path | None = None,
) -> PublicationView:
    """Read one exact DB-indexed publication without writes, scans, or extraction."""
    root = _store_root(store_root, write=False)
    connection = _reader(root)
    try:
        _publication_schema(connection)
        head = connection.execute(
            "SELECT * FROM semantic_publication_heads WHERE source_id=? AND build_id=?",
            (source_id, build_id),
        ).fetchone()
        if head is None:
            raise StructuredExecutionError("CS_NOT_PUBLISHED", "publication_head_missing")
        selected_id = publication_id or head["publication_id"]
        if (
            publication_id is not None
            and publication_id != head["publication_id"]
            and not allow_historical
        ):
            raise StructuredExecutionError("CS_NOT_PUBLISHED", "publication_superseded")
        row = connection.execute(
            "SELECT * FROM semantic_publications WHERE publication_id=? "
            "AND source_id=? AND build_id=?",
            (selected_id, source_id, build_id),
        ).fetchone()
        if row is None:
            raise StructuredExecutionError("CS_NOT_PUBLISHED", "publication_not_indexed")
        manifest = _read_manifest(root, row["manifest_relpath"], row["manifest_sha256"])
        if (
            manifest.publication_id != row["publication_id"]
            or manifest.generation != row["generation"]
            or manifest.snapshot_id != row["snapshot_id"]
            or manifest.publication_status != row["publication_status"]
        ):
            raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "publication_index_mismatch")
        if row["lifecycle"] not in {
            "publish",
            "source_update",
            "rule_upgrade",
            "withdraw",
            "expire",
        }:
            raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "publication_lifecycle_invalid")
        lifecycle = cast(Lifecycle, row["lifecycle"])
        if not allow_historical and (
            manifest.publication_status != "published" or manifest.quality_status != "accepted"
        ):
            if manifest.publication_status == "withdrawn":
                reason = "publication_expired" if lifecycle == "expire" else "publication_withdrawn"
            elif manifest.publication_status == "superseded":
                reason = "publication_superseded"
            else:
                reason = "publication_not_usable"
            raise StructuredExecutionError("CS_NOT_PUBLISHED", reason)
        if not allow_historical and any(
            mapping.rule_version != CROSS_ROLE_RULE_VERSION for mapping in manifest.mappings
        ):
            raise StructuredExecutionError("CS_NOT_PUBLISHED", "publication_rule_upgrade_required")
        artifact_rows = connection.execute(
            "SELECT * FROM semantic_publication_artifacts "
            "WHERE publication_id=? ORDER BY artifact_sha256",
            (selected_id,),
        ).fetchall()
        if {value["artifact_sha256"] for value in artifact_rows} != set(manifest.artifacts):
            raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "publication_artifact_index")
        published: list[PublishedArtifact] = []
        candidates: list[_Candidate] = []
        for artifact_row in artifact_rows:
            reference = ArtifactReference(
                batch_id=artifact_row["batch_id"],
                task_id=artifact_row["task_id"],
                artifact_sha256=artifact_row["artifact_sha256"],
            )
            candidate = _load_candidate(connection, root, reference)
            if candidate.snapshot.snapshot_id != manifest.snapshot_id:
                raise StructuredExecutionError(
                    "CS_ARTIFACT_CORRUPT", "publication_snapshot_mismatch"
                )
            candidates.append(candidate)
            published.append(
                PublishedArtifact(
                    reference=reference,
                    artifact=candidate.artifact,
                    payload=candidate.payload,
                )
            )
        claims = {key: value for candidate in candidates for key, value in candidate.claims.items()}
        items = {key: value for candidate in candidates for key, value in candidate.items.items()}
        _validate_mappings(manifest.mappings, claims, items, candidates[0].snapshot)
        _validate_relations(candidates, set(items))
        restricted = {
            mapping.claim_fact_id
            for mapping in manifest.mappings
            if mapping.mapping_status == "conflict" and mapping.claim_fact_id is not None
        }
        purposes: dict[str, tuple[str, ...]] = {}
        relation_ids: list[str] = []
        for candidate in candidates:
            if isinstance(candidate.payload, EvidenceRun):
                for fact in candidate.payload.facts:
                    purposes[fact.fact_id] = tuple(
                        purpose
                        for purpose in fact.usable_for
                        if fact.fact_id not in restricted or purpose == "cite"
                    )
            elif candidate.artifact.role == "material_relations":
                relation_ids.extend(
                    relation.relation_id
                    for relation in candidate.payload.understanding.relations
                    if relation.from_item in items and relation.to_item in items
                )
        return PublicationView(
            manifest=manifest,
            snapshot=candidates[0].snapshot,
            lifecycle=lifecycle,
            artifacts=tuple(published),
            effective_claim_purposes=purposes,
            active_relation_ids=tuple(relation_ids),
        )
    except sqlite3.DatabaseError as exc:
        raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "publication_index_invalid") from exc
    finally:
        connection.close()
