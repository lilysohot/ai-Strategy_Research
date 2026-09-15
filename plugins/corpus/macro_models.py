"""M1: immutable macro candidates and audit records, NOT computation permission.

JSON is untrusted, including a structurally valid verification record. Trust is
established separately by the application-owned authority in macro_verification.
No changes to historical EvidenceRun serialization, database tables or registries.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from plugins.corpus.evidence import fingerprint
from plugins.corpus.evidence_pipeline import EvidenceRun, align_quote

Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
SourceHash = Annotated[str, Field(pattern=r"^(?:[0-9a-f]{16}|[0-9a-f]{64})$")]
Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Month = Annotated[
    str,
    Field(pattern=r"^(?:[1-9][0-9]{3}|0[1-9][0-9]{2}|00[1-9][0-9]|000[1-9])-(?:0[1-9]|1[0-2])$"),
]
Scope = Literal[
    "indicator", "period", "value", "release_at", "known_at", "vintage", "snapshot", "unit_mapping"
]
ReasonCode = Literal[
    "indicator_mismatch",
    "period_unverified",
    "unit_unverified",
    "role_mismatch",
    "atomic_evidence_mismatch",
    "vintage_mismatch",
    "consensus_snapshot_missing",
    "lookahead_bias",
    "time_provenance_unverified",
    "duplicate_identity",
    "source_conflict",
    "validation_outdated",
    "source_hash_mismatch",
    "value_unverified",
    "verification_untrusted",
]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        """Pydantic's default copy(update=...) skips validation; do not expose that shortcut."""
        return type(self).model_validate({**self.model_dump(), **(update or {})})


class SourceTime(FrozenModel):
    """Preserve the source UTC offset; compare only via utc, never a guessed midnight."""

    raw: Text

    @field_validator("raw")
    @classmethod
    def offset_required(cls, value: str) -> str:
        if not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value
        ):
            raise ValueError("explicit datetime with UTC offset required")
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError("UTC offset required")
        return value

    @property
    def utc(self) -> datetime:
        return datetime.fromisoformat(self.raw).astimezone(UTC)


class CellReference(FrozenModel):
    table: Text
    row: Text
    column: Text
    cell: Text


class EvidenceReference(FrozenModel):
    run_id: Hash
    source_rev: SourceHash
    packet_id: Hash
    locator: Text
    quote: Text
    start: Annotated[int, Field(ge=0, strict=True)]
    end: Annotated[int, Field(gt=0, strict=True)]
    fact_id: Hash | None = None
    cell: CellReference | None = None

    @model_validator(mode="after")
    def valid_range(self) -> Self:
        if self.end <= self.start or self.end - self.start != len(self.quote):
            raise ValueError("invalid evidence character range")
        return self


def reference_from_run(
    run: EvidenceRun, packet_id: str, quote: str, *, fact_id: str | None = None
) -> EvidenceReference:
    """Build an exact reference without rewriting or upgrading the source run."""
    run.verify_identity()
    packet = run.document.fetch(packet_id)
    alignment = align_quote(quote, packet.text)
    if alignment is None:
        raise ValueError("atomic_evidence_mismatch")
    reference = EvidenceReference(
        run_id=run.run_id,
        source_rev=run.document.source_rev,
        packet_id=packet_id,
        locator=packet.locator,
        quote=str(alignment["source_quote"]),
        start=int(str(alignment["start"])),
        end=int(str(alignment["end"])),
        fact_id=fact_id,
    )
    resolve_reference(reference, run)
    return reference


def resolve_reference(reference: EvidenceReference, run: EvidenceRun) -> str:
    run.verify_identity()
    if reference.run_id != run.run_id or reference.source_rev != run.document.source_rev:
        raise ValueError("source_hash_mismatch")
    packet = run.document.fetch(reference.packet_id)
    if (
        packet.locator != reference.locator
        or packet.text[reference.start : reference.end] != reference.quote
    ):
        raise ValueError("atomic_evidence_mismatch")
    if reference.fact_id is not None:
        facts = [f for f in run.facts if f.fact_id == reference.fact_id]
        if len(facts) != 1 or facts[0].packet_id != reference.packet_id:
            raise ValueError("duplicate_identity" if len(facts) > 1 else "atomic_evidence_mismatch")
    if reference.cell and packet.lookup(reference.cell.model_dump()) is None:
        raise ValueError("atomic_evidence_mismatch")
    return reference.quote


class EvidenceBinding(FrozenModel):
    field: Scope
    reference: EvidenceReference


class Dimensions(FrozenModel):
    country: Literal["US"] | None = None
    indicator: Literal["US.NFP_CHANGE_SA", "US.NFP_LEVEL_YOY", "US.NFP_REVISION_SUM"] | None = None
    population: Literal["nonfarm_payroll_jobs", "persons"] | None = None
    transform: Literal["month_change", "yoy_rate", "revision_sum", "level"] | None = None
    adjustment: Literal["SA", "NSA"] | None = None


class Qualifier(FrozenModel):
    name: Literal["basis", "scope", "method"]
    value: Text


class RawAmount(FrozenModel):
    value_raw: str | None = None
    unit_raw: str | None = None

    @property
    def numeric(self) -> Decimal | None:
        if self.value_raw is None:
            return None
        # No extraction from surrounding prose and no permissive removal of commas.
        raw = self.value_raw.strip()
        if not re.fullmatch(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", raw):
            return None
        return Decimal(raw.replace(",", ""))


class MacroRecord(FrozenModel):
    schema_version: Literal["macro-input-1"] = "macro-input-1"

    @property
    def record_id(self) -> str:
        return fingerprint(self.model_dump(mode="json"))

    def to_json(self) -> str:
        return json.dumps(
            {"record_id": self.record_id, "payload": self.model_dump(mode="json")},
            ensure_ascii=False,
            sort_keys=True,
        )


class ReleaseEvent(MacroRecord):
    record_type: Literal["release_event"] = "release_event"
    publisher: Text
    release_key: Text
    reference_month: Month | None = None
    release_at: SourceTime | None = None
    archive_uri: Text | None = None
    archive_hash: Hash | None = None
    evidence: tuple[EvidenceBinding, ...] = ()


class Vintage(MacroRecord):
    record_type: Literal["vintage"] = "vintage"
    release_event_id: Hash
    reference_month: Month | None = None
    vintage_kind: Literal["first", "second", "third", "benchmark"] | None = None
    published_at: SourceTime | None = None
    supersedes_id: Hash | None = None
    evidence: tuple[EvidenceBinding, ...] = ()


class ConsensusSnapshot(MacroRecord):
    record_type: Literal["consensus_snapshot"] = "consensus_snapshot"
    provider: Text | None = None
    release_event_id: Hash | None = None
    reference_month: Month | None = None
    statistic: Literal["mean", "median"] | None = None
    survey_cutoff_at: SourceTime | None = None
    snapshot_known_at: SourceTime | None = None
    archive_uri: Text | None = None
    archive_hash: Hash | None = None
    evidence: tuple[EvidenceBinding, ...] = ()


class MacroObservation(MacroRecord):
    record_type: Literal["observation"] = "observation"
    dimensions: Dimensions
    reference_month: Month | None = None
    role: Literal["actual", "consensus"]
    kind: Literal["observed", "forecast"]
    amount: RawAmount
    release_event_id: Hash | None = None
    vintage_id: Hash | None = None
    consensus_snapshot_id: Hash | None = None
    known_at: SourceTime | None = None
    ingested_at: SourceTime | None = None
    qualifiers: tuple[Qualifier, ...] = ()
    evidence: tuple[EvidenceBinding, ...] = ()

    @model_validator(mode="after")
    def explicit_role(self) -> Self:
        if (self.role, self.kind) not in {("actual", "observed"), ("consensus", "forecast")}:
            raise ValueError("role_mismatch")
        if self.role == "actual" and self.consensus_snapshot_id is not None:
            raise ValueError("role_mismatch")
        if self.role == "consensus" and self.vintage_id is not None:
            raise ValueError("role_mismatch")
        if len({q.name for q in self.qualifiers}) != len(self.qualifiers):
            raise ValueError("duplicate qualifier")
        return self


class VerificationRecord(MacroRecord):
    """An audit statement, not trusted merely because this schema validates."""

    record_type: Literal["verification_record"] = "verification_record"
    subject_id: Hash
    issuer_id: Text
    issuer_role: Literal["human_reviewer", "source_adapter"]
    policy_version: Text
    reviewed_at: SourceTime
    decision: Literal["approved", "rejected", "unknown"]
    scopes: Annotated[tuple[Scope, ...], Field(min_length=1)]
    evidence: Annotated[tuple[EvidenceReference, ...], Field(min_length=1)]
    reason_codes: tuple[ReasonCode, ...] = ()

    @model_validator(mode="after")
    def decision_reasons(self) -> Self:
        if len(set(self.scopes)) != len(self.scopes):
            raise ValueError("duplicate verification scope")
        if (self.decision == "approved") == bool(self.reason_codes):
            raise ValueError("approved has no reasons; rejected/unknown requires reasons")
        return self


class BlockedInput(MacroRecord):
    record_type: Literal["blocked_input"] = "blocked_input"
    status: Literal["blocked"] = "blocked"
    value: None = None
    input_ids: tuple[Hash, ...]
    reason_codes: Annotated[tuple[ReasonCode, ...], Field(min_length=1)]
    missing_fields: tuple[Text, ...] = ()


Record = Annotated[
    ReleaseEvent
    | Vintage
    | ConsensusSnapshot
    | MacroObservation
    | VerificationRecord
    | BlockedInput,
    Field(discriminator="record_type"),
]


class _Envelope(FrozenModel):
    record_id: Hash
    payload: Record

    @model_validator(mode="after")
    def content_identity(self) -> Self:
        if self.record_id != self.payload.record_id:
            raise ValueError("source_hash_mismatch")
        return self


def load_record(serialized: str) -> Record:
    """Validate shape and content identity, NEVER promote a verification record to trusted."""

    def unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    return _Envelope.model_validate(json.loads(serialized, object_pairs_hook=unique_fields)).payload


def index_unique(records: Iterable[MacroRecord]) -> dict[str, MacroRecord]:
    result = {}
    for record in records:
        if record.record_id in result:
            raise ValueError("duplicate_identity")
        result[record.record_id] = record
    return result
