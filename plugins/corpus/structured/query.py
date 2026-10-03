"""Read-only semantic query over one verified publication snapshot."""

from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from plugins.corpus.cursor import SEMANTIC_QUERY, CursorError, decode_cursor, encode_cursor
from plugins.corpus.evidence_pipeline import EvidenceRun, evidence_document_from_snapshot
from plugins.corpus.material_semantics import MaterialEvidence, MaterialRun
from plugins.corpus.structured.config import canonical_hash
from plugins.corpus.structured.ledger import StructuredExecutionError
from plugins.corpus.structured.mapping import resolve_packet_span, resolve_unit_span
from plugins.corpus.structured.snapshot import EvidenceSnapshot, SnapshotUnit, source_unit_id
from plugins.corpus.structured.store import MappingStatus, PublicationView, read_semantic

QUERY_SCHEMA_VERSION = "corpus-semantic-query-page-v1"
QUERY_SORT_VERSION = "semantic-lexical-sort-v1"
QUERY_RULE_VERSION = "semantic-query-rule-v2"
QUERY_RESPONSE_BUDGET_VERSION = "semantic-query-budget-v2"
_RAW_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
_PREFIXED_HASH_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_HASH_PATTERN = r"^sha256:[0-9a-f]{64}$"
_HANDLE_PATTERN = r"^cv2:[A-Za-z0-9._:-]+#chunk:[A-Za-z0-9._:-]+$"
Purpose = Literal["cite", "compare", "calculate"]
Role = Literal["claims", "material_items", "material_relations"]
DependencyKind = Literal[
    "value",
    "period",
    "unit",
    "header",
    "footnote",
    "condition",
    "negation",
    "attribution",
]
PageStatus = Literal[
    "complete",
    "more_available",
    "budget_limited",
    "no_match",
    "not_extracted",
    "not_published",
    "cursor_stale",
]


class QueryEvidence(BaseModel):
    """One exact Unicode code-point range in the authoritative source unit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    handle: str = Field(pattern=_HANDLE_PATTERN)
    unit_id: str
    locator: str
    quote: str = Field(min_length=1)
    coordinate_system: Literal["unicode_code_points"] = "unicode_code_points"
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    text_sha256: str = Field(pattern=_HASH_PATTERN)


class QueryDependency(BaseModel):
    """Purpose-sensitive context requirement bound to one evidence range."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: DependencyKind
    evidence_index: int = Field(ge=0)
    required_for: tuple[Purpose, ...] = Field(min_length=1)
    status: Literal["present", "missing", "ambiguous"]


class SemanticQueryRecord(BaseModel):
    """Published business record plus its complete evidence unit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: str
    role: Role
    usable_for: tuple[Purpose, ...]
    evidence: tuple[QueryEvidence, ...] = Field(min_length=1)
    dependencies: tuple[QueryDependency, ...] = ()
    context_status: Literal["complete", "partial", "missing", "ambiguous", "budget_exceeded"]
    mapping_status: MappingStatus
    quality_status: Literal["accepted", "review_required", "rejected"]

    @model_validator(mode="after")
    def validate_references(self) -> SemanticQueryRecord:
        if len(set(self.usable_for)) != len(self.usable_for):
            raise ValueError("usable_for must be unique")
        if any(
            dependency.evidence_index >= len(self.evidence)
            or len(set(dependency.required_for)) != len(dependency.required_for)
            for dependency in self.dependencies
        ):
            raise ValueError("dependency references or purposes are invalid")
        return self


class SemanticQueryPage(BaseModel):
    """Schema-compatible page returned by the Python and tool interfaces."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["corpus-semantic-query-page-v1"] = QUERY_SCHEMA_VERSION
    query_id: str
    publication_id: str = Field(pattern=_HASH_PATTERN)
    query_sha256: str = Field(pattern=_HASH_PATTERN)
    sort_version: Literal["semantic-lexical-sort-v1"] = QUERY_SORT_VERSION
    purpose: Purpose
    records: tuple[SemanticQueryRecord, ...] = ()
    next_cursor: str | None = None
    page_status: PageStatus
    error_codes: tuple[str, ...] = ()


def _mapping_status(view: PublicationView, record_id: str, role: str) -> MappingStatus:
    statuses = {
        mapping.mapping_status
        for mapping in view.manifest.mappings
        if (role == "claims" and mapping.claim_fact_id == record_id)
        or (role == "material_items" and mapping.material_item_id == record_id)
    }
    # One conflicting or unresolved link must not be hidden by another match.
    for status in ("conflict", "suspected", "unlinked", "confirmed"):
        if status in statuses:
            return cast(MappingStatus, status)
    return "unlinked"


def _evidence(value: object, build_id: str) -> QueryEvidence:
    if not isinstance(value, dict):
        raise ValueError("query evidence must be an object")
    chunk_id = str(value["chunk_id"]).removeprefix("chunk:")
    return QueryEvidence(
        handle=f"cv2:{build_id}#chunk:{chunk_id}",
        unit_id=str(value["unit_id"]),
        locator=str(value["locator"]),
        quote=str(value["quote"]),
        coordinate_system=cast(Literal["unicode_code_points"], value["coordinate_system"]),
        start=int(value["start"]),
        end=int(value["end"]),
        text_sha256=str(value["text_sha256"]),
    )


def _append_evidence(values: list[QueryEvidence], value: QueryEvidence) -> int:
    try:
        return values.index(value)
    except ValueError:
        values.append(value)
        return len(values) - 1


def _dependency_unit(
    snapshot: EvidenceSnapshot, evidence: list[QueryEvidence]
) -> tuple[QueryDependency, ...]:
    allowed = {
        "value",
        "period",
        "unit",
        "header",
        "footnote",
        "condition",
        "negation",
        "attribution",
    }
    by_internal = {unit.unit_id: unit for unit in snapshot.units}
    by_source = {
        (unit.chunk_id.removeprefix("chunk:"), source_unit_id(unit)): unit
        for unit in snapshot.units
    }
    pending: list[SnapshotUnit] = []
    for proof in tuple(evidence):
        chunk = proof.handle.split("#chunk:", 1)[1]
        unit = by_source.get((chunk, proof.unit_id))
        if unit is not None and unit not in pending:
            pending.append(unit)
    result: list[QueryDependency] = []
    seen: set[tuple[str, int, tuple[Purpose, ...], str]] = set()
    cursor = 0
    while cursor < len(pending):
        unit = pending[cursor]
        cursor += 1
        details = unit.metadata.get("dependency_details", [])
        if not isinstance(details, list):
            continue
        for detail in details:
            if not isinstance(detail, dict) or detail.get("kind") not in allowed:
                continue
            raw_required = detail.get("required_for", [])
            required: tuple[Purpose, ...] = (
                tuple(
                    cast(Purpose, value)
                    for value in raw_required
                    if value in {"cite", "compare", "calculate"}
                )
                if isinstance(raw_required, list)
                else ()
            )
            if not required:
                continue
            status = str(detail.get("status"))
            status = status if status in {"present", "missing", "ambiguous"} else "missing"
            target = by_internal.get(str(detail.get("target_unit_id")))
            evidence_index = 0
            if status == "present" and target is not None:
                reference = resolve_unit_span(snapshot, target.unit_id, 0, len(target.text))
                evidence_index = _append_evidence(
                    evidence, _evidence(asdict(reference), snapshot.build_id)
                )
                if target not in pending:
                    pending.append(target)
            elif status == "present":
                status = "missing"
            key = (str(detail["kind"]), evidence_index, required, status)
            if key in seen:
                continue
            seen.add(key)
            result.append(
                QueryDependency(
                    kind=cast(DependencyKind, detail["kind"]),
                    evidence_index=evidence_index,
                    required_for=required,
                    status=cast(Literal["present", "missing", "ambiguous"], status),
                )
            )
    return tuple(result)


def _complete_evidence(
    snapshot: EvidenceSnapshot, values: tuple[QueryEvidence, ...]
) -> tuple[tuple[QueryEvidence, ...], tuple[QueryDependency, ...]]:
    evidence = list(values)
    dependencies = _dependency_unit(snapshot, evidence)
    return tuple(evidence), dependencies


def _claim_records(view: PublicationView) -> list[tuple[str, SemanticQueryRecord]]:
    output: list[tuple[str, SemanticQueryRecord]] = []
    for published in view.artifacts:
        if published.artifact.role != "claims":
            continue
        run = published.payload
        if not isinstance(run, EvidenceRun):
            continue
        for fact in run.facts:
            alignment = fact.evidence_alignment or {}
            source_spans = alignment.get("source_spans", [])
            if not isinstance(source_spans, list) or not source_spans:
                continue
            evidence, dependencies = _complete_evidence(
                view.snapshot,
                tuple(_evidence(span, view.manifest.build_id) for span in source_spans),
            )
            purposes: tuple[Purpose, ...] = tuple(
                cast(Purpose, purpose)
                for purpose in view.effective_claim_purposes.get(fact.fact_id, ())
            )
            quality = {
                "ok": "accepted",
                "review": "review_required",
                "rejected": "rejected",
            }.get(fact.claim.quality_status, "review_required")
            record = SemanticQueryRecord(
                record_id=fact.fact_id,
                role="claims",
                usable_for=purposes,
                evidence=evidence,
                dependencies=dependencies,
                context_status=published.artifact.context_status,
                mapping_status=_mapping_status(view, fact.fact_id, "claims"),
                quality_status=cast(Literal["accepted", "review_required", "rejected"], quality),
            )
            searchable = " ".join(
                filter(
                    None,
                    (
                        fact.claim.claim_text,
                        fact.claim.subject,
                        fact.claim.metric_raw,
                        fact.claim.period_raw,
                        fact.claim.value_text,
                    ),
                )
            )
            output.append((searchable, record))
    return output


def _material_records(view: PublicationView) -> list[tuple[str, SemanticQueryRecord]]:
    output: list[tuple[str, SemanticQueryRecord]] = []
    document = evidence_document_from_snapshot(view.snapshot, role="material_items")
    packets = {packet.packet_id: packet for packet in document.packets}
    for published in view.artifacts:
        run = published.payload
        if not isinstance(run, MaterialRun):
            continue
        speakers = {speaker.speaker_id: speaker for speaker in run.understanding.speakers}
        records: list[tuple[str, str, str, tuple[MaterialEvidence, ...]]] = []
        for item in run.understanding.items:
            speaker = speakers.get(item.speaker_ref)
            searchable = " ".join(
                filter(
                    None,
                    (
                        item.text,
                        item.value,
                        item.semantic_type,
                        item.statement_role,
                        item.polarity,
                        speaker.display_name if speaker else None,
                        speaker.role if speaker else None,
                    ),
                )
            )
            records.append((item.item_id, item.text, searchable, item.evidence))
        if published.artifact.role == "material_relations":
            items = {item.item_id: item for item in run.understanding.items}
            records = [
                (
                    relation.relation_id,
                    relation.type,
                    " ".join(
                        [relation.type]
                        + [proof.quote for proof in relation.evidence]
                        + [
                            items[endpoint].text
                            for endpoint in (relation.from_item, relation.to_item)
                            if endpoint in items
                        ]
                    ),
                    relation.evidence,
                )
                for relation in run.understanding.relations
                if relation.relation_id in view.active_relation_ids
            ]
        for record_id, _text, searchable, proofs in records:
            main: list[QueryEvidence] = []
            for proof in proofs:
                packet = packets.get(proof.packet_id)
                if packet is None:
                    continue
                for reference in resolve_packet_span(view.snapshot, packet, proof.start, proof.end):
                    _append_evidence(main, _evidence(asdict(reference), view.manifest.build_id))
            if not main:
                continue
            evidence, dependencies = _complete_evidence(view.snapshot, tuple(main))
            role = published.artifact.role
            output.append(
                (
                    searchable,
                    SemanticQueryRecord(
                        record_id=record_id,
                        role=role,
                        usable_for=("cite",),
                        evidence=evidence,
                        dependencies=dependencies,
                        context_status=published.artifact.context_status,
                        mapping_status=_mapping_status(view, record_id, role),
                        quality_status="accepted",
                    ),
                )
            )
    return output


def _query_identity(
    source_id: str,
    build_id: str,
    purpose: Purpose,
    query_text: str,
    field_filters: dict[str, str],
    max_chars: int,
) -> tuple[str, str]:
    digest = canonical_hash(
        {
            "source_id": source_id,
            "build_id": build_id,
            "purpose": purpose,
            "query_text": query_text,
            "field_filters": field_filters,
            "sort_version": QUERY_SORT_VERSION,
            "query_rule_version": QUERY_RULE_VERSION,
            "response_budget_version": QUERY_RESPONSE_BUDGET_VERSION,
            "max_chars": max_chars,
        }
    )
    return f"query:{digest[7:23]}", digest


def _empty_page(
    *,
    query_id: str,
    query_sha: str,
    source_id: str,
    build_id: str,
    purpose: Purpose,
    status: PageStatus,
    error_codes: tuple[str, ...],
    publication_id: str | None = None,
) -> SemanticQueryPage:
    return SemanticQueryPage(
        query_id=query_id,
        publication_id=publication_id
        or canonical_hash({"source_id": source_id, "build_id": build_id, "state": status}),
        query_sha256=query_sha,
        purpose=purpose,
        page_status=status,
        error_codes=error_codes,
    )


def _cursor(*, view: PublicationView, query_sha: str, position: int) -> str:
    return encode_cursor(
        {
            "type": SEMANTIC_QUERY,
            "query_sha256": query_sha,
            "sort_version": QUERY_SORT_VERSION,
            "publication_id": view.manifest.publication_id,
            "generation": view.manifest.generation,
            "position": position,
        }
    )


def _valid_cursor_payload(value: dict[str, object], query_sha: str) -> bool:
    publication_id = value.get("publication_id")
    generation = value.get("generation")
    position = value.get("position")
    return (
        value.get("type") == SEMANTIC_QUERY
        and value.get("query_sha256") == query_sha
        and value.get("sort_version") == QUERY_SORT_VERSION
        and isinstance(publication_id, str)
        and _PREFIXED_HASH_RE.fullmatch(publication_id) is not None
        and type(generation) is int
        and generation >= 1
        and type(position) is int
        and position >= 0
    )


def _cursor_publication(value: dict[str, object] | None) -> str | None:
    publication_id = value.get("publication_id") if value else None
    if isinstance(publication_id, str) and _PREFIXED_HASH_RE.fullmatch(publication_id) is not None:
        return publication_id
    return None


def _filtered(record: SemanticQueryRecord, field_filters: dict[str, str]) -> bool:
    values = {
        "record_id": record.record_id,
        "role": record.role,
        "mapping_status": record.mapping_status,
        "quality_status": record.quality_status,
        "context_status": record.context_status,
    }
    return all(values[key] == expected for key, expected in field_filters.items())


def _purpose_context(record: SemanticQueryRecord, purpose: Purpose) -> SemanticQueryRecord:
    applicable = [
        dependency for dependency in record.dependencies if purpose in dependency.required_for
    ]
    if any(dependency.status == "missing" for dependency in applicable):
        return record.model_copy(update={"context_status": "missing"})
    if any(dependency.status == "ambiguous" for dependency in applicable):
        return record.model_copy(update={"context_status": "ambiguous"})
    return record


def _make_page(
    *,
    query_id: str,
    publication_id: str,
    query_sha: str,
    purpose: Purpose,
    records: tuple[SemanticQueryRecord, ...],
    next_cursor: str | None,
    status: PageStatus,
    error_codes: tuple[str, ...] = (),
) -> SemanticQueryPage:
    return SemanticQueryPage(
        query_id=query_id,
        publication_id=publication_id,
        query_sha256=query_sha,
        purpose=purpose,
        records=records,
        next_cursor=next_cursor,
        page_status=status,
        error_codes=error_codes,
    )


def query_semantic(
    source_id: str,
    build_id: str,
    *,
    purpose: Purpose,
    query_text: str = "",
    limit: int = 10,
    cursor: str | None = None,
    max_chars: int = 5_500,
    field_filters: dict[str, str] | None = None,
    store_root: str | Path | None = None,
) -> SemanticQueryPage:
    """Query one current accepted publication without extraction or writes."""
    if (
        not isinstance(source_id, str)
        or _RAW_HASH_RE.fullmatch(source_id) is None
        or not isinstance(build_id, str)
        or _RAW_HASH_RE.fullmatch(build_id) is None
        or purpose not in {"cite", "compare", "calculate"}
    ):
        raise ValueError("source_id/build_id must be lowercase SHA-256 and purpose is required")
    if not isinstance(query_text, str):
        raise ValueError("query_text must be a string")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if type(max_chars) is not int or not 700 <= max_chars <= 1_000_000:
        raise ValueError("max_chars must be between 700 and 1000000")
    if field_filters is None:
        field_filters = {}
    elif not isinstance(field_filters, dict):
        raise ValueError("field_filters must be an object")
    if any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in field_filters.items()
    ):
        raise ValueError("semantic field filter keys and values must be strings")
    field_filters = dict(sorted(field_filters.items()))
    allowed_filters = {
        "record_id",
        "role",
        "mapping_status",
        "quality_status",
        "context_status",
    }
    if any(
        key not in allowed_filters or not isinstance(value, str) or not value.strip()
        for key, value in field_filters.items()
    ):
        raise ValueError("unsupported or empty semantic field filter")
    enum_filters = {
        "role": {"claims", "material_items", "material_relations"},
        "mapping_status": {"confirmed", "suspected", "unlinked", "conflict"},
        "quality_status": {"accepted", "review_required", "rejected"},
        "context_status": {"complete", "partial", "missing", "ambiguous", "budget_exceeded"},
    }
    if any(
        key in enum_filters and value not in enum_filters[key]
        for key, value in field_filters.items()
    ):
        raise ValueError("invalid semantic field filter value")
    query_text = query_text.strip()
    query_id, query_sha = _query_identity(
        source_id, build_id, purpose, query_text, field_filters, max_chars
    )
    decoded: dict[str, object] | None = None
    if cursor is not None:
        try:
            decoded = decode_cursor(cursor)
        except CursorError:
            return _empty_page(
                query_id=query_id,
                query_sha=query_sha,
                source_id=source_id,
                build_id=build_id,
                purpose=purpose,
                status="cursor_stale",
                error_codes=("CS_CURSOR_STALE",),
            )
        if not _valid_cursor_payload(decoded, query_sha):
            return _empty_page(
                query_id=query_id,
                query_sha=query_sha,
                source_id=source_id,
                build_id=build_id,
                purpose=purpose,
                status="cursor_stale",
                error_codes=("CS_CURSOR_STALE",),
                publication_id=_cursor_publication(decoded),
            )
    try:
        view = read_semantic(source_id, build_id, store_root=store_root)
    except StructuredExecutionError as exc:
        if cursor is not None and exc.code == "CS_NOT_PUBLISHED":
            return _empty_page(
                query_id=query_id,
                query_sha=query_sha,
                source_id=source_id,
                build_id=build_id,
                purpose=purpose,
                status="cursor_stale",
                error_codes=("CS_CURSOR_STALE",),
                publication_id=_cursor_publication(decoded),
            )
        if exc.code == "CS_NOT_PUBLISHED":
            return _empty_page(
                query_id=query_id,
                query_sha=query_sha,
                source_id=source_id,
                build_id=build_id,
                purpose=purpose,
                status="not_published",
                error_codes=("CS_NOT_PUBLISHED",),
            )
        raise
    if decoded is not None and (
        decoded.get("publication_id") != view.manifest.publication_id
        or decoded.get("generation") != view.manifest.generation
    ):
        return _empty_page(
            query_id=query_id,
            query_sha=query_sha,
            source_id=source_id,
            build_id=build_id,
            purpose=purpose,
            status="cursor_stale",
            error_codes=("CS_CURSOR_STALE",),
            publication_id=_cursor_publication(decoded),
        )
    needle = "".join(query_text.lower().split())
    eligible = [
        (searchable, _purpose_context(record, purpose))
        for searchable, record in (*_claim_records(view), *_material_records(view))
        if purpose in record.usable_for
    ]
    candidates = [item for item in eligible if _filtered(item[1], field_filters)]
    matches = [
        ("".join(searchable.lower().split()), record)
        for searchable, record in candidates
        if not needle or needle in "".join(searchable.lower().split())
    ]
    role_order = {"claims": 0, "material_items": 1, "material_relations": 2}
    matches.sort(
        key=lambda item: (
            -item[0].count(needle) if needle else 0,
            role_order[item[1].role],
            item[1].record_id,
        )
    )
    published_roles = {artifact.artifact.role for artifact in view.artifacts}
    requested_role = field_filters.get("role")
    relevant_roles: set[str] = (
        {requested_role}
        if requested_role is not None
        else ({"claims"} if purpose in {"compare", "calculate"} else set(role_order))
    )
    if not (published_roles & relevant_roles):
        return _empty_page(
            query_id=query_id,
            query_sha=query_sha,
            source_id=source_id,
            build_id=build_id,
            purpose=purpose,
            status="not_extracted",
            error_codes=("CS_DEPENDENCY_NOT_READY",),
            publication_id=view.manifest.publication_id,
        )
    if not matches:
        return _make_page(
            query_id=query_id,
            publication_id=view.manifest.publication_id,
            query_sha=query_sha,
            purpose=purpose,
            records=(),
            next_cursor=None,
            status="no_match",
            error_codes=("CS_NOT_FOUND",)
            if not any(record.role in relevant_roles for _, record in eligible)
            else (),
        )
    start = 0
    if decoded is not None:
        position = decoded.get("position")
        if type(position) is not int or not 0 <= position < len(matches):
            return _empty_page(
                query_id=query_id,
                query_sha=query_sha,
                source_id=source_id,
                build_id=build_id,
                purpose=purpose,
                status="cursor_stale",
                error_codes=("CS_CURSOR_STALE",),
                publication_id=view.manifest.publication_id,
            )
        start = position
    selected: list[SemanticQueryRecord] = []
    position = start
    budget_limited = False
    while position < len(matches) and len(selected) < limit:
        proposed = (*selected, matches[position][1])
        next_position = position + 1
        more = next_position < len(matches)
        proposed_page = _make_page(
            query_id=query_id,
            publication_id=view.manifest.publication_id,
            query_sha=query_sha,
            purpose=purpose,
            records=proposed,
            next_cursor=_cursor(view=view, query_sha=query_sha, position=next_position)
            if more
            else None,
            status="more_available" if more else "complete",
        )
        if len(proposed_page.model_dump_json()) > max_chars:
            budget_limited = True
            break
        selected.append(matches[position][1])
        position = next_position
    more = position < len(matches)
    if budget_limited:
        status: PageStatus = "budget_limited"
        errors = ("CS_BUDGET_EXHAUSTED",)
    elif more:
        status = "more_available"
        errors = ()
    else:
        status = "complete"
        errors = ()
    page = _make_page(
        query_id=query_id,
        publication_id=view.manifest.publication_id,
        query_sha=query_sha,
        purpose=purpose,
        records=tuple(selected),
        next_cursor=_cursor(view=view, query_sha=query_sha, position=position) if more else None,
        status=status,
        error_codes=errors,
    )
    while len(page.model_dump_json()) > max_chars and selected:
        selected.pop()
        position -= 1
        page = _make_page(
            query_id=query_id,
            publication_id=view.manifest.publication_id,
            query_sha=query_sha,
            purpose=purpose,
            records=tuple(selected),
            next_cursor=_cursor(view=view, query_sha=query_sha, position=position),
            status="budget_limited",
            error_codes=("CS_BUDGET_EXHAUSTED",),
        )
    if len(page.model_dump_json()) > max_chars:
        page = page.model_copy(update={"next_cursor": None})
    if len(page.model_dump_json()) > max_chars:
        raise StructuredExecutionError("CS_BUDGET_EXHAUSTED", "query_envelope_budget_too_small")
    return page


__all__ = [
    "QUERY_RESPONSE_BUDGET_VERSION",
    "QUERY_RULE_VERSION",
    "QUERY_SCHEMA_VERSION",
    "QUERY_SORT_VERSION",
    "QueryDependency",
    "QueryEvidence",
    "SemanticQueryPage",
    "SemanticQueryRecord",
    "query_semantic",
]
