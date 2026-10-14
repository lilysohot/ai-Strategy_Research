"""Assemble scorer input from human adjudications under the signed contract v4.1.

Signed contract: ``non-table-selected-target-scoring-contract-v4.1``
(``evidence/47-scoring-contract-v41-signed-20261012/…/scoring-contract-v4.1.json``,
``sha256:c76ac13e…``, signed 2026-10-12).

Clauses implemented here:

* ``adjudication_clause`` — the 11 per-record fields, evidence required, forbidden operations.
* ``read_path.carrier_mapping`` — ``item.text`` -> ``proposition`` is a **rename only**.
* ``read_path.absent_required_fields`` — un-carried required fields are recorded as
  ``absent`` explicitly; absent never forces a non-match and is never guessed.
* ``caliber_rules`` — normalization applies to the **matching view** only; the candidate's
  original fields are retained untouched.
* ``read_path.equivalence_judgement.scorer_contract`` — the scorer consumes the finished
  mapping; identity equality is not a matching precondition.

This module never reads frozen gold, and structurally cannot: no parameter accepts gold
records. Deterministic fields are recomputed from the candidate's own native fields, so a
record whose declared value was copied from a gold record is rejected rather than scored.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

from plugins.corpus.structured_scoring import (
    AdjudicationJudgement,
    CandidateRecord,
    RecordOrigin,
    Role,
    ScoringInputError,
)

CONTRACT_SCHEMA_VERSION = "non-table-selected-target-scoring-contract-v4.1"
CONTRACT_SHA256 = "sha256:c76ac13ec0a109074775a2b5e1c8cc170da955847638d6ea7f5778988238781b"
CLAIMS_CONTRACT_PATH = (
    Path(__file__).resolve().parents[2]
    / ".scratch/claims-r2-role-isolation/evidence/88-claims-contract-v44-signed-20261014"
    / "r0-zero-call/scoring-contract-v4.4.json"
)
"""Signed claims-carrying contract (v4.4): source of the claims read path (C3)."""

ABSENT = "absent"
"""Explicit marker for a contract-required field the candidate does not carry."""

Judgement = AdjudicationJudgement
"""``adjudication_clause.candidate_judgements``; defined once by the scoring consumer."""


class Stage(StrEnum):
    """Raw and validated candidates are adjudicated separately (``scope_rules``)."""

    RAW = "raw"
    VALIDATED = "validated"


class Requirement(StrEnum):
    """``read_path.roles.<role>.carriers.<field>.requires``."""

    NORMALIZATION = "normalization"
    CALIBER_NORMALIZATION = "caliber_normalization"
    NONE = "none"
    HUMAN_ONLY = "human_only"
    EXCLUDED_FROM_MATCHING_BASIS = "excluded_from_matching_basis"


@dataclass(frozen=True)
class Carrier:
    """One contract field's carrier and the work its read path needs."""

    carrier: str
    requires: Requirement

    @property
    def is_deterministic(self) -> bool:
        """True when the assembler can derive the value without a human read."""
        return self.requires in (
            Requirement.NORMALIZATION,
            Requirement.CALIBER_NORMALIZATION,
            Requirement.NONE,
        )

    @property
    def in_matching_basis(self) -> bool:
        """Excluded carriers are recorded for audit but never enter the matching basis."""
        return self.requires is not Requirement.EXCLUDED_FROM_MATCHING_BASIS


MATERIAL_ITEMS_CARRIERS: Mapping[str, Carrier] = {
    "proposition": Carrier("item.text", Requirement.NORMALIZATION),
    "semantic_type": Carrier("item.semantic_type", Requirement.HUMAN_ONLY),
    "statement_role": Carrier("item.statement_role", Requirement.HUMAN_ONLY),
    "speech_role": Carrier("item.speech_role", Requirement.CALIBER_NORMALIZATION),
    "perspective": Carrier("item.perspective", Requirement.CALIBER_NORMALIZATION),
    "polarity": Carrier("item.polarity", Requirement.NONE),
    "speaker_ref": Carrier("item.speaker_ref", Requirement.EXCLUDED_FROM_MATCHING_BASIS),
    "attribution": Carrier("layer_b.attribution", Requirement.EXCLUDED_FROM_MATCHING_BASIS),
    "source_stance": Carrier("none", Requirement.HUMAN_ONLY),
    "condition": Carrier("item.text", Requirement.HUMAN_ONLY),
}

ROLE_CARRIERS: Mapping[Role, Mapping[str, Carrier]] = {
    Role.MATERIAL_ITEMS: MATERIAL_ITEMS_CARRIERS,
}
"""Static carriers for roles whose read path was implemented in-revision.

``Role.CLAIMS`` resolves lazily from the signed claims-carrying contract
(``read_path.roles.claims.carriers``, contract v4.4) — see ``_carriers_for``.
"""

ROLE_REQUIRED_FIELDS: Mapping[Role, tuple[str, ...]] = {
    Role.MATERIAL_ITEMS: (
        "proposition",
        "semantic_type",
        "statement_role",
        "speech_role",
        "perspective",
        "speaker_ref",
        "polarity",
        "attribution",
        "source_stance",
    ),
}


def required_fields_for(role: Role) -> tuple[str, ...]:
    """Contract-required fields for ``role``: static map first, else the signed contract."""
    declared = ROLE_REQUIRED_FIELDS.get(role)
    if declared is not None:
        return declared
    return tuple(sorted(_carriers_for(role)))


CALIBER_AUTO_NORMALIZE: Mapping[str, Mapping[str, str]] = {
    "perspective": {"source_explicit": "unknown"},
    "speech_role": {
        "question": "statement",
        "answer": "statement",
        "unknown": "statement",
    },
    # Signed caliber C3 (contract v4.4): claims carries ``kind`` for ``factuality``.
    # Inert for items, whose required fields have no ``factuality`` member.
    "factuality": {"fact": "actual"},
}
"""``caliber_rules.rules.<field>`` entries with ``auto_normalize: true``, matching view only."""

ADJUDICATION_FIELDS: tuple[str, ...] = (
    "candidate_id",
    "stage",
    "role",
    "source_id",
    "original_candidate",
    "judgement",
    "matched_gold_id",
    "canonical_observed_fields",
    "reviewer",
    "reason",
    "evidence",
)
"""``adjudication_clause.required_per_record_fields`` (contract v4.1)."""


@dataclass(frozen=True)
class AdjudicatedMapping:
    """The scorer's adjudication input: which gold record a candidate was mapped to, if any.

    ``gold_record_id is None`` means the adjudicator did not map the candidate to a target
    record (``correct_extra`` / ``incorrect`` / ``duplicate``). The scorer must honour this
    mapping and must not fall back to comparing semantic fields.
    """

    candidate_id: str
    gold_record_id: str | None
    judgement: Judgement
    stage: Stage


@dataclass(frozen=True)
class AssemblyAudit:
    """One record's deterministic provenance, for review without re-running a model."""

    candidate_id: str
    stage: Stage
    judgement: Judgement
    matched_gold_id: str | None
    reviewer: str
    canonical_observed_fields: Mapping[str, str]
    excluded_from_matching_basis: tuple[str, ...]
    absent_required_fields: tuple[str, ...]
    matching_basis: tuple[str, ...]
    normalized_fields: Mapping[str, str]
    contract_view: Mapping[str, Any] = field(default_factory=dict)
    field_provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssembledScoringInput:
    """Everything ``score_structured_quality`` needs, plus the audit trail."""

    raw: tuple[CandidateRecord, ...]
    validated: tuple[CandidateRecord, ...]
    mappings: tuple[AdjudicatedMapping, ...]
    out_of_scope: tuple[str, ...]
    audit: tuple[AssemblyAudit, ...]


def assemble_scoring_input(
    adjudications: Sequence[Mapping[str, Any]],
    *,
    catalog: Mapping[str, Mapping[str, Any]],
    allowed_source_ids: Iterable[str] | None = None,
) -> AssembledScoringInput:
    """Turn human adjudications into validated scorer input.

    ``catalog`` maps ``candidate_id`` to the workbench candidate that was adjudicated; it is
    the only source of the candidate's own fields. Adjudications that assert a different
    value for a deterministic field than the catalog-derived one are rejected.
    """
    permitted = set(allowed_source_ids) if allowed_source_ids is not None else None
    raw: list[CandidateRecord] = []
    validated: list[CandidateRecord] = []
    mappings: list[AdjudicatedMapping] = []
    out_of_scope: list[str] = []
    audit: list[AssemblyAudit] = []
    seen: set[tuple[Stage, str]] = set()

    for index, adjudication in enumerate(adjudications):
        declared = _validate_adjudication_shape(adjudication, index)
        candidate_id = declared["candidate_id"]
        stage = declared["stage"]
        role = declared["role"]
        judgement = declared["judgement"]

        if judgement is Judgement.UNRESOLVED:
            raise ScoringInputError(
                f"{candidate_id}: unresolved adjudication violates "
                "adjudication_clause.full_coverage_required.unresolved_max = 0"
            )
        key = (stage, candidate_id)
        if key in seen:
            raise ScoringInputError(f"duplicate adjudication: {stage}/{candidate_id}")
        seen.add(key)

        origin_candidate = catalog.get(candidate_id)
        if origin_candidate is None:
            raise ScoringInputError(f"{candidate_id}: not present in the adjudication catalog")
        _check_catalog_identity(candidate_id, declared, origin_candidate)
        if permitted is not None and declared["source_id"] not in permitted:
            raise ScoringInputError(
                f"{candidate_id}: source_id outside candidate_input_scope {declared['source_id']}"
            )

        canonical, matching_fields, normalized = _resolve_canonical_fields(
            candidate_id=candidate_id,
            role=role,
            declared=declared["canonical_observed_fields"],
            origin_candidate=origin_candidate,
        )

        if judgement is Judgement.OUT_OF_SCOPE:
            out_of_scope.append(candidate_id)
            continue

        carriers = _carriers_for(role)
        basis = tuple(sorted(matching_fields.items()))
        record = CandidateRecord(
            candidate_id=candidate_id,
            role=role,
            source_id=declared["source_id"],
            origin=_origin_of(origin_candidate),
            semantic_fields=basis,
        )
        (raw if stage is Stage.RAW else validated).append(record)
        mapping = AdjudicatedMapping(
            candidate_id=candidate_id,
            gold_record_id=declared["matched_gold_id"],
            judgement=judgement,
            stage=stage,
        )
        mappings.append(mapping)
        audit.append(
            AssemblyAudit(
                candidate_id=candidate_id,
                stage=stage,
                judgement=judgement,
                matched_gold_id=declared["matched_gold_id"],
                reviewer=declared["reviewer"],
                canonical_observed_fields=dict(canonical),
                excluded_from_matching_basis=tuple(
                    sorted(name for name in canonical if not carriers[name].in_matching_basis)
                ),
                absent_required_fields=tuple(
                    sorted(name for name, value in canonical.items() if value == ABSENT)
                ),
                matching_basis=tuple(name for name, _ in basis),
                normalized_fields=dict(normalized),
                contract_view=dict(origin_candidate.get("contract_view") or {}),
                field_provenance=dict(origin_candidate.get("field_provenance") or {}),
            )
        )

    return AssembledScoringInput(
        raw=tuple(raw),
        validated=tuple(validated),
        mappings=tuple(mappings),
        out_of_scope=tuple(sorted(out_of_scope)),
        audit=tuple(audit),
    )


def matching_view(field: str, value: str) -> str:
    """Apply ``caliber_rules`` to one field for the matching view only.

    Returns ``value`` unchanged when the field has no ``auto_normalize`` rule; the caller's
    original value must be retained separately.
    """
    return CALIBER_AUTO_NORMALIZE.get(field, {}).get(value, value)


def _carriers_for(role: Role) -> Mapping[str, Carrier]:
    carriers = ROLE_CARRIERS.get(role)
    if carriers is not None:
        return carriers
    if role is Role.CLAIMS:
        return _claims_carriers()
    raise ScoringInputError(
        f"role {role} has no implemented read path in contract v4.1 "
        "(read_path.roles.*.implemented_in_this_revision is false)"
    )


@lru_cache(maxsize=1)
def _claims_carriers() -> Mapping[str, Carrier]:
    """Cached claims carriers; the contract file is read at most once per process."""
    return load_claims_carriers()


def load_claims_carriers(
    contract_path: str | Path = CLAIMS_CONTRACT_PATH,
) -> Mapping[str, Carrier]:
    """Read the claims read path from the signed claims-carrying contract (C3).

    Prefers ``read_path.roles.claims.carriers``; falls back to the transitional
    ``read_path.roles_proposed.claims.carriers`` location used by the v4.4 signoff, and fails
    closed if both are declared (two sources) or if the carrier set does not match the
    contract's ``role_required_fields.claims``.
    """
    path = Path(contract_path)
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ScoringInputError(f"claims_contract_unavailable:{path}") from exc
    except json.JSONDecodeError as exc:
        raise ScoringInputError(f"claims_contract_invalid_json:{path}") from exc
    if not isinstance(payload, Mapping) or payload.get("status") != "frozen_signed":
        raise ScoringInputError("claims contract must be a frozen_signed JSON object")
    read_path = payload.get("read_path")
    if not isinstance(read_path, Mapping):
        raise ScoringInputError("claims_contract_read_path_missing")
    canonical = _nested(read_path, "roles", "claims")
    proposed = _nested(read_path, "roles_proposed", "claims")
    canonical_carriers = canonical.get("carriers") if isinstance(canonical, Mapping) else None
    proposed_carriers = proposed.get("carriers") if isinstance(proposed, Mapping) else None
    if canonical_carriers and proposed_carriers:
        raise ScoringInputError(
            "claims carriers declared twice (read_path.roles.claims and roles_proposed.claims)"
        )
    declared = canonical_carriers or proposed_carriers
    if not isinstance(declared, Mapping) or not declared:
        raise ScoringInputError("claims_contract_role_carriers_missing:claims")
    carriers: dict[str, Carrier] = {}
    for name, entry in declared.items():
        if not isinstance(entry, Mapping):
            raise ScoringInputError(f"claims carrier must be an object: {name}")
        carrier = str(entry.get("carrier") or "")
        requires = str(entry.get("requires") or "")
        if not carrier or not requires:
            raise ScoringInputError(f"claims carrier incomplete: {name}")
        try:
            requirement = Requirement(requires)
        except ValueError as exc:
            raise ScoringInputError(
                f"claims carrier {name} has unknown requires={requires!r}"
            ) from exc
        carriers[str(name)] = Carrier(carrier, requirement)
    required = set((payload.get("role_required_fields") or {}).get("claims") or ())
    if required and required != set(carriers):
        raise ScoringInputError(
            "claims carriers do not match role_required_fields.claims: "
            f"missing={sorted(required - set(carriers))} extra={sorted(set(carriers) - required)}"
        )
    return carriers


def _nested(parent: Mapping[str, Any], *keys: str) -> Mapping[str, Any]:
    current: Any = parent
    for key in keys:
        if not isinstance(current, Mapping):
            return {}
        current = current.get(key)
    return current if isinstance(current, Mapping) else {}


def _validate_adjudication_shape(adjudication: Mapping[str, Any], index: int) -> dict[str, Any]:
    missing = [name for name in ADJUDICATION_FIELDS if name not in adjudication]
    if missing:
        raise ScoringInputError(
            f"adjudication[{index}]: missing required_per_record_fields {missing}"
        )
    candidate_id = str(adjudication["candidate_id"] or "")
    if not candidate_id:
        raise ScoringInputError(f"adjudication[{index}]: candidate_id must be non-empty")
    reviewer = str(adjudication["reviewer"] or "").strip()
    if not reviewer:
        raise ScoringInputError(
            f"{candidate_id}: reviewer is required (adjudication_clause.responsible_party)"
        )
    evidence = adjudication["evidence"]
    if not _has_evidence(evidence):
        raise ScoringInputError(
            f"{candidate_id}: evidence must cite verbatim text or a source locator "
            "(adjudication_clause.evidence_required)"
        )
    try:
        stage = Stage(str(adjudication["stage"]))
    except ValueError as error:
        raise ScoringInputError(
            f"{candidate_id}: invalid stage {adjudication['stage']!r}"
        ) from error
    try:
        role = Role(str(adjudication["role"]))
    except ValueError as error:
        raise ScoringInputError(f"{candidate_id}: invalid role {adjudication['role']!r}") from error
    try:
        judgement = Judgement(str(adjudication["judgement"]))
    except ValueError as error:
        raise ScoringInputError(
            f"{candidate_id}: invalid judgement {adjudication['judgement']!r}"
        ) from error
    matched_gold_id = adjudication["matched_gold_id"]
    if judgement is Judgement.MATCHED:
        if not matched_gold_id:
            raise ScoringInputError(f"{candidate_id}: matched requires a matched_gold_id")
    elif matched_gold_id:
        raise ScoringInputError(
            f"{candidate_id}: judgement {judgement} must not carry a matched_gold_id"
        )
    declared_fields = adjudication["canonical_observed_fields"]
    if not isinstance(declared_fields, Mapping):
        raise ScoringInputError(f"{candidate_id}: canonical_observed_fields must be a mapping")
    return {
        "candidate_id": candidate_id,
        "stage": stage,
        "role": role,
        "source_id": str(adjudication["source_id"] or ""),
        "judgement": judgement,
        "matched_gold_id": str(matched_gold_id) if matched_gold_id else None,
        "canonical_observed_fields": declared_fields,
        "reviewer": reviewer,
        "reason": str(adjudication["reason"] or ""),
    }


def _has_evidence(evidence: Any) -> bool:
    if isinstance(evidence, str):
        return bool(evidence.strip())
    if isinstance(evidence, Mapping):
        return bool(str(evidence.get("quote") or "").strip()) or bool(
            str(evidence.get("locator") or "").strip()
        )
    if isinstance(evidence, Sequence) and not isinstance(evidence, (str, bytes)):
        return any(_has_evidence(item) for item in evidence)
    return False


def _check_catalog_identity(
    candidate_id: str, declared: Mapping[str, Any], origin_candidate: Mapping[str, Any]
) -> None:
    for name in ("role", "source_id"):
        expected = str(origin_candidate.get(name) or "")
        if expected and expected != str(declared[name]):
            raise ScoringInputError(
                f"{candidate_id}: adjudication {name} {declared[name]!r} contradicts "
                f"the candidate catalog {expected!r}"
            )


def _origin_of(origin_candidate: Mapping[str, Any]) -> RecordOrigin:
    raw = str(origin_candidate.get("origin") or RecordOrigin.LLM_PROSE.value)
    try:
        return RecordOrigin(raw)
    except ValueError as error:
        raise ScoringInputError(f"unknown candidate origin {raw!r}") from error


def _resolve_canonical_fields(
    *,
    candidate_id: str,
    role: Role,
    declared: Mapping[str, Any],
    origin_candidate: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Recompute deterministic fields and check the human-only ones are explicit.

    Returns ``(canonical_observed_fields, matching_basis, normalized)``. The canonical set
    keeps the **renamed original** values; caliber normalization is applied only to the
    matching basis, so the candidate's own text is never overwritten.
    """
    carriers = _carriers_for(role)
    canonical: dict[str, str] = {}
    basis: dict[str, str] = {}
    normalized: dict[str, str] = {}
    for name, carrier in carriers.items():
        value = declared.get(name)
        if value is None or str(value) == "":
            raise ScoringInputError(
                f"{candidate_id}: canonical_observed_fields.{name} is blank; "
                "read_path.absent_required_fields requires an explicit 'absent' "
                "(blank and guessing are both forbidden)"
            )
        text = str(value)
        if carrier.is_deterministic:
            expected = _deterministic_value(carrier, origin_candidate)
            if text != expected:
                raise ScoringInputError(
                    f"{candidate_id}: declared {name}={text!r} but the candidate's own "
                    f"carrier yields {expected!r}; deterministic carriers may be renamed "
                    "only, never rewritten or filled from a target record "
                    "(read_path.carrier_mapping.forbidden)"
                )
        canonical[name] = text
        if carrier.in_matching_basis:
            view = matching_view(name, text)
            if view != text:
                normalized[name] = f"{text} -> {view}"
            basis[name] = view
    return canonical, basis, normalized


_CARRIER_PREFIXES = ("layer_b.", "item.", "claim.")
"""Carrier namespaces: the candidate's own fields, its layer-B projection, and claims rows."""


def _deterministic_value(carrier: Carrier, origin_candidate: Mapping[str, Any]) -> str:
    if carrier.carrier == "none":
        return ABSENT
    key = None
    for prefix in _CARRIER_PREFIXES:
        if carrier.carrier.startswith(prefix):
            key = carrier.carrier[len(prefix) :]
            break
    if not key:
        raise ScoringInputError(
            f"carrier {carrier.carrier!r} has no known namespace {_CARRIER_PREFIXES}"
        )
    value = origin_candidate.get(key)
    if value is None or not str(value).strip():
        return ABSENT
    return str(value)


def condition_role_needs_human_basis(adjudication: Mapping[str, Any]) -> bool:
    """True when ``absent_required_fields.condition_role_addition`` applies to a record."""
    fields = adjudication.get("canonical_observed_fields") or {}
    if not isinstance(fields, Mapping):
        return False
    return (
        str(fields.get("statement_role") or "") == "condition"
        and str(fields.get("condition") or "") == ABSENT
    )
