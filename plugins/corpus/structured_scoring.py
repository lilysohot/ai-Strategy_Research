"""Pure deterministic quality scoring for independent Claims and R2 roles."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class ScoringInputError(ValueError):
    """Raised when a frozen gold or observation contradicts the scoring contract."""


class Role(StrEnum):
    """Independently scored structured-extraction roles."""

    CLAIMS = "claims"
    MATERIAL_ITEMS = "material_items"
    MATERIAL_RELATIONS = "material_relations"


class MatchingMode(StrEnum):
    """How candidates are matched to gold.

    ``ADJUDICATED`` is the contract path (read_path.equivalence_judgement.scorer_contract:
    身份相等不得作为匹配前提) — the scorer consumes a finished human mapping and only
    validates it. ``LEGACY_IDENTITY`` keeps the historical strict-equality matcher and must be
    requested explicitly, so it can never be reached by omission.
    """

    ADJUDICATED = "adjudicated"
    LEGACY_IDENTITY = "legacy_identity"


@runtime_checkable
class AdjudicatedMappingLike(Protocol):
    """Structural contract for one adjudication mapping, as consumed by the scorer."""

    candidate_id: str
    gold_record_id: str | None
    judgement: str


class AdjudicationJudgement(StrEnum):
    """The only judgements the scorer accepts (contract ``candidate_judgements``)."""

    MATCHED = "matched"
    CORRECT_EXTRA = "correct_extra"
    INCORRECT = "incorrect"
    DUPLICATE = "duplicate"
    UNRESOLVED = "unresolved"
    OUT_OF_SCOPE = "out_of_scope"


class RecordOrigin(StrEnum):
    """Extraction path kept separate for capability attribution."""

    DETERMINISTIC_TABLE = "deterministic_table"
    LLM_PROSE = "llm_prose"


class CoverageStage(StrEnum):
    """Separate denominators from source parsing through actual context use."""

    PARSE = "parse"
    PACKET = "packet"
    ROUTING = "routing"
    EXTRACTION = "extraction"
    QUERY = "query"
    DELIVERY = "delivery"
    CONTEXT_USE = "context_use"


class CoverageOutcome(StrEnum):
    """Observed outcome; every non-pass value remains in the denominator."""

    PASS = "pass"
    MISSED = "missed"
    FAILED = "failed"
    EMPTY = "empty"
    INVALID = "invalid"


@dataclass(frozen=True)
class CoverageTarget:
    """One frozen source/gold target and the stages it must traverse."""

    target_id: str
    source_id: str
    required_stages: tuple[CoverageStage, ...]
    groups: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.target_id or not self.source_id or not self.required_stages:
            raise ScoringInputError("coverage target id/source/stages must be non-empty")
        if len(set(self.required_stages)) != len(self.required_stages):
            raise ScoringInputError(f"{self.target_id}: duplicate coverage stage")
        if any(not group for group in self.groups) or len(set(self.groups)) != len(self.groups):
            raise ScoringInputError(f"{self.target_id}: groups must be non-empty and unique")


@dataclass(frozen=True)
class CoverageObservation:
    """One actual stage result for a frozen target."""

    target_id: str
    stage: CoverageStage
    outcome: CoverageOutcome
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.target_id:
            raise ScoringInputError("coverage observation target_id must be non-empty")


@dataclass(frozen=True)
class ReportConclusion:
    """One report claim and the exact gold records it requires and cites."""

    conclusion_id: str
    required_record_ids: tuple[str, ...]
    cited_record_ids: tuple[str, ...]
    critical: bool = False

    def __post_init__(self) -> None:
        if not self.conclusion_id or not self.required_record_ids:
            raise ScoringInputError("conclusion id and required records must be non-empty")
        if len(set(self.required_record_ids)) != len(self.required_record_ids):
            raise ScoringInputError(f"{self.conclusion_id}: duplicate required record")
        if len(set(self.cited_record_ids)) != len(self.cited_record_ids):
            raise ScoringInputError(f"{self.conclusion_id}: duplicate cited record")


@dataclass(frozen=True)
class GoldRecord:
    """One pre-candidate human reference record in a role-local denominator."""

    record_id: str
    role: Role
    source_id: str
    origin: RecordOrigin
    semantic_fields: tuple[tuple[str, str], ...]
    critical: bool = False
    risk_or_condition: bool = False

    def __post_init__(self) -> None:
        _validate_record(self.record_id, self.source_id, self.semantic_fields)

    @property
    def identity(self) -> tuple[object, ...]:
        """Strict role-local semantic identity used for one-to-one matching."""
        return (self.role, self.source_id, self.origin, self.semantic_fields)


@dataclass(frozen=True)
class CandidateRecord:
    """One raw or validated candidate record presented to the scorer."""

    candidate_id: str
    role: Role
    source_id: str
    origin: RecordOrigin
    semantic_fields: tuple[tuple[str, str], ...]
    critical_error_code: str | None = None

    def __post_init__(self) -> None:
        _validate_record(self.candidate_id, self.source_id, self.semantic_fields)
        if self.critical_error_code is not None and not self.critical_error_code:
            raise ScoringInputError(f"{self.candidate_id}: critical_error_code cannot be empty")

    @property
    def identity(self) -> tuple[object, ...]:
        """Strict semantic identity, including source and extraction path."""
        return (self.role, self.source_id, self.origin, self.semantic_fields)


@dataclass(frozen=True)
class RoleMetrics:
    """One role's exact TP/FP/FN ledger.

    ``correct_extra`` keeps the contract's ``metrics.candidate_precision`` numerator
    (``matched + correct_extra``) exact without inflating target recall: extraneous but
    correct output is neither a target hit nor an error. Defaulting to 0 keeps the formula
    identical to the historical ``tp / (tp + fp)``.
    """

    role: Role
    tp: int
    fp: int
    fn: int
    duplicate_fp: int
    correct_extra: int = 0

    @property
    def precision(self) -> Fraction | None:
        """Precision, or ``None`` when no candidate was produced.

        ``fp`` already includes duplicates: both matchers append DUPLICATE candidates to
        ``false_positive_ids`` (``_match_by_identity``, ``_match_by_adjudication``), and
        ``duplicate_fp`` is a *subset* counter used for diagnosis. The denominator is therefore
        ``numerator + fp``, which is exactly the contract's duplicate-inclusive
        ``(matched + correct_extra) / (matched + correct_extra + incorrect + duplicate)``.

        Do not add ``duplicate_fp`` here: the 2026-10-14 claims draft C2 read the adjudication
        file's ``incorrect`` count as if it were this ``fp`` and concluded the two formulas
        diverged (56/107 vs 56/110). They do not diverge; adding ``duplicate_fp`` would double
        count and yield 56/113 (see the 88-号 C2 re-check record).
        """
        numerator = self.tp + self.correct_extra
        denominator = numerator + self.fp
        return Fraction(numerator, denominator) if denominator else None

    @property
    def recall(self) -> Fraction | None:
        """Recall, or ``None`` for a zero gold denominator (correct_extra never counts)."""
        return Fraction(self.tp, self.tp + self.fn) if self.tp + self.fn else None


@dataclass(frozen=True)
class OriginMetrics:
    """One role/origin slice, preventing deterministic work from masking LLM quality."""

    role: Role
    origin: RecordOrigin
    tp: int
    fp: int
    fn: int
    correct_extra: int = 0

    @property
    def precision(self) -> Fraction | None:
        """Precision, or ``None`` when the slice produced no candidates.

        Deliberately not duplicate-inclusive: this slice carries no ``duplicate_fp`` counter
        (C2 applies to ``RoleMetrics``, which is where the contract formula is computed).
        """
        numerator = self.tp + self.correct_extra
        denominator = numerator + self.fp
        return Fraction(numerator, denominator) if denominator else None

    @property
    def recall(self) -> Fraction | None:
        """Recall, or ``None`` for an empty gold slice."""
        return Fraction(self.tp, self.tp + self.fn) if self.tp + self.fn else None


@dataclass(frozen=True)
class CandidateScore:
    """Role metrics for one candidate stage, without hiding missing gold."""

    roles: tuple[RoleMetrics, ...]
    origins: tuple[OriginMetrics, ...]
    matched_gold_ids: tuple[str, ...]
    missing_gold_ids: tuple[str, ...]

    def role(self, role: Role) -> RoleMetrics:
        """Return metrics for an exact role."""
        return next(item for item in self.roles if item.role is role)

    def role_origin(self, role: Role, origin: RecordOrigin) -> OriginMetrics:
        """Return one exact role/origin slice."""
        return next(item for item in self.origins if item.role is role and item.origin is origin)


@dataclass(frozen=True)
class SourceStageMetrics:
    """One document's denominator for a coverage stage."""

    source_id: str
    passed: int
    total: int

    @property
    def rate(self) -> Fraction:
        """Per-document success rate; a source slice always has a target."""
        return Fraction(self.passed, self.total)


@dataclass(frozen=True)
class GroupStageMetrics:
    """One frozen family/channel/risk slice with micro and document-macro rates."""

    group: str
    passed: int
    total: int
    sources: tuple[SourceStageMetrics, ...]

    @property
    def rate(self) -> Fraction:
        """Group micro success rate; a reported group always has a target."""
        return Fraction(self.passed, self.total)

    @property
    def macro_rate(self) -> Fraction:
        """Unweighted mean of the group's per-document rates."""
        return sum((item.rate for item in self.sources), start=Fraction()) / len(self.sources)


@dataclass(frozen=True)
class StageMetrics:
    """Micro/macro coverage rates and explicit failures for one pipeline stage."""

    stage: CoverageStage
    passed: int
    total: int
    failures: tuple[str, ...]
    sources: tuple[SourceStageMetrics, ...]
    groups: tuple[GroupStageMetrics, ...]

    @property
    def rate(self) -> Fraction | None:
        """Micro stage success rate; zero denominator is undefined, never perfect."""
        return Fraction(self.passed, self.total) if self.total else None

    @property
    def macro_rate(self) -> Fraction | None:
        """Mean of per-document rates, so large easy documents cannot dominate."""
        if not self.sources:
            return None
        return sum((item.rate for item in self.sources), start=Fraction()) / len(self.sources)

    def group(self, group: str) -> GroupStageMetrics:
        """Return one caller-frozen family/channel/risk slice."""
        return next(item for item in self.groups if item.group == group)


@dataclass(frozen=True)
class CoverageScore:
    """All stage denominators and failure attribution."""

    stages: tuple[StageMetrics, ...]

    def stage(self, stage: CoverageStage) -> StageMetrics:
        """Return one stage's complete denominator."""
        return next(item for item in self.stages if item.stage is stage)


@dataclass(frozen=True)
class ReportSupportScore:
    """Whether conclusions had complete evidence in the actual model context."""

    passed: int
    total: int
    failures: tuple[str, ...]
    critical_failures: tuple[str, ...]

    @property
    def rate(self) -> Fraction | None:
        """Supported-conclusion rate; no conclusions is an undefined denominator."""
        return Fraction(self.passed, self.total) if self.total else None


@dataclass(frozen=True)
class RoleThreshold:
    """Exact candidate precision/recall thresholds for one role."""

    role: Role
    precision_min: Fraction
    recall_min: Fraction

    def __post_init__(self) -> None:
        if not (0 < self.precision_min <= 1 and 0 < self.recall_min <= 1):
            raise ScoringInputError(f"{self.role}: thresholds must be in (0, 1]")


@dataclass(frozen=True)
class QualityPolicy:
    """Candidate pilot thresholds; sign-off is tracked separately as evidence."""

    role_thresholds: tuple[RoleThreshold, ...]
    risk_condition_recall_min: Fraction
    report_support_min: Fraction
    min_gold_per_role: int = 20

    def __post_init__(self) -> None:
        if {item.role for item in self.role_thresholds} != set(Role):
            raise ScoringInputError("quality policy requires exactly one threshold per role")
        if len(self.role_thresholds) != len(Role):
            raise ScoringInputError("quality policy role thresholds must be unique")
        if not (0 < self.risk_condition_recall_min <= 1):
            raise ScoringInputError("risk/condition recall threshold must be in (0, 1]")
        if not (0 < self.report_support_min <= 1):
            raise ScoringInputError("report support threshold must be in (0, 1]")
        if self.min_gold_per_role < 1:
            raise ScoringInputError("min_gold_per_role must be positive")

    def role(self, role: Role) -> RoleThreshold:
        """Return the threshold for an exact role."""
        return next(item for item in self.role_thresholds if item.role is role)


PILOT_CANDIDATE_POLICY = QualityPolicy(
    role_thresholds=(
        RoleThreshold(Role.CLAIMS, Fraction(49, 50), Fraction(19, 20)),
        RoleThreshold(Role.MATERIAL_ITEMS, Fraction(19, 20), Fraction(9, 10)),
        RoleThreshold(Role.MATERIAL_RELATIONS, Fraction(19, 20), Fraction(17, 20)),
    ),
    risk_condition_recall_min=Fraction(19, 20),
    report_support_min=Fraction(19, 20),
)


@dataclass(frozen=True)
class ContractGateRequirements:
    """The signed contract's gate axes, evaluated inside the gate's role scope.

    Values are loaded directly from signed contract v4.3
    ``threshold_source.effective`` and its item review assertions. Missing, malformed,
    unsigned, or differently versioned contracts fail closed.

    R2 note (2026-10-13): the sentinel list follows the signed gate v3, which moved five records
    to ``quality_requirements.high_risk_item_assertions_excluded``
    (``gold_split_finer_than_candidate``: NT-I09/NT-I19; ``candidate_side_cannot_carry_axis``:
    NT-I45/NT-I46/NT-I47). The dataclass field set is unchanged on purpose — the exclusions are
    recorded by the gate, not re-modelled here.
    """

    schema_version: str
    role_scope: Role
    target_recall_overall_min: Fraction
    target_recall_per_source_min: Fraction
    candidate_precision_min: Fraction
    accepted_records_total_min: int
    accepted_records_per_source_min: int
    unresolved_candidates_max: int
    material_items_target_total: int
    high_risk_item_assertions_required: tuple[str, ...]

    def __post_init__(self) -> None:
        if not (0 < self.target_recall_overall_min <= 1):
            raise ScoringInputError("target_recall_overall_min must be in (0, 1]")
        if not (0 < self.target_recall_per_source_min <= 1):
            raise ScoringInputError("target_recall_per_source_min must be in (0, 1]")
        if not (0 < self.candidate_precision_min <= 1):
            raise ScoringInputError("candidate_precision_min must be in (0, 1]")
        if self.accepted_records_total_min < 1 or self.accepted_records_per_source_min < 1:
            raise ScoringInputError("accepted_records minima must be positive")
        if self.unresolved_candidates_max < 0:
            raise ScoringInputError("unresolved_candidates_max must be non-negative")
        if len(set(self.high_risk_item_assertions_required)) != len(
            self.high_risk_item_assertions_required
        ):
            raise ScoringInputError("high_risk_item_assertions_required must be unique")

    @property
    def role_target_total(self) -> int:
        """The gate role's frozen target total.

        ``material_items_target_total`` keeps its historical name because the frozen field set
        is asserted by the P03 binding verifier; read the value through this alias by intent.
        """
        return self.material_items_target_total


SIGNED_SCORING_CONTRACT_SCHEMA = "non-table-selected-target-scoring-contract-v4.3"
SUPPORTED_SIGNED_CONTRACT_SCHEMAS: tuple[str, ...] = (
    SIGNED_SCORING_CONTRACT_SCHEMA,
    "non-table-selected-target-scoring-contract-v4.4",
)
"""Schema versions this loader accepts. v4.4 adds ``role_sections`` (items + claims).

Accepting the version string is not activation: the loader still requires
``status == frozen_signed`` and a complete signoff, so a draft contract carrying the v4.4 schema
stays unreadable until it is signed.
"""
SIGNED_SCORING_CONTRACT_PATH = (
    Path(__file__).resolve().parents[2]
    / ".scratch/claims-r2-role-isolation/evidence/75-r2-signed-20261013"
    / "r0-zero-call/scoring-contract-v4.3.json"
)
_CONTRACT_RATE_FIELDS = (
    "target_recall_overall_min",
    "target_recall_per_source_min",
    "candidate_precision_min",
)
_CONTRACT_COUNT_FIELDS = (
    "accepted_records_total_min",
    "accepted_records_per_source_min",
    "unresolved_candidates_max",
)


def _contract_object(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ScoringInputError(f"signed scoring contract field must be an object: {key}")
    return value


# A role section may override *only* these gate thresholds, and only with an explicit integer.
# The allow-list is deliberately narrow: a stray threshold-looking key must fail closed rather than
# silently re-scope the gate (e.g. a release-line 0.60 pasted into a target-line field). Rate
# thresholds therefore stay role-identical and come from ``threshold_source.effective``; extending
# this list is a deliberate, signed change.
_ROLE_SECTION_ALLOWED_KEYS = (
    "review_assertions",
    "target_total",
    "accepted_records_total_min",
    "accepted_records_per_source_min",
)
_ROLE_THRESHOLD_OVERRIDE_FIELDS = (
    "accepted_records_total_min",
    "accepted_records_per_source_min",
)

_ROLE_ASSERTION_PATTERN: Mapping[Role, str] = {
    Role.MATERIAL_ITEMS: r"NT-I\d{2}",
    Role.CLAIMS: r"NT-C\d{2}",
    # Relations has a sentinel pattern but no in-scope gate this round (contract OPEN-2 = C):
    # a declared section loads, and nothing scores it.
    Role.MATERIAL_RELATIONS: r"NT-R\d{2}",
}
_LEGACY_ITEMS_ASSERTION_COUNT = 11
_LEGACY_ITEMS_TARGET_TOTAL = 48


def _contract_role_section(payload: Mapping[str, Any], role: Role) -> Mapping[str, Any] | None:
    """Return the contract's ``role_sections.<role>`` entry, or None when not declared.

    Absent sections return None (the caller decides between the legacy branch and fail-closed);
    a present-but-malformed section raises, so a typo cannot silently downgrade to "missing".
    """
    sections = payload.get("role_sections")
    if sections is None:
        return None
    if not isinstance(sections, Mapping):
        raise ScoringInputError("contract_role_sections_invalid")
    section = sections.get(role.value)
    if section is None:
        return None
    if not isinstance(section, Mapping):
        raise ScoringInputError(f"contract_role_section_invalid:{role.value}")
    unexpected = sorted(
        str(key)
        for key in section
        if not str(key).startswith("_") and key not in _ROLE_SECTION_ALLOWED_KEYS
    )
    if unexpected:
        raise ScoringInputError(
            f"contract_role_section_invalid:{role.value}:unexpected_key:{unexpected[0]}"
        )
    return section


def _resolve_role_sentinels(
    section: Mapping[str, Any], role: Role, pattern: str
) -> tuple[tuple[str, ...], int]:
    """Validate one role section's sentinel list and target total; fail closed otherwise."""
    declared = section.get("review_assertions")
    if not isinstance(declared, (list, tuple)) or not declared:
        raise ScoringInputError(f"contract_role_section_invalid:{role.value}:review_assertions")
    names = tuple(sorted(str(name) for name in declared))
    if len(set(names)) != len(names):
        raise ScoringInputError(f"contract_role_section_invalid:{role.value}:duplicate_assertion")
    foreign = [name for name in names if not re.fullmatch(pattern, name)]
    if foreign:
        raise ScoringInputError(
            f"contract_role_section_invalid:{role.value}:foreign_assertion:{foreign[0]}"
        )
    total = section.get("target_total")
    if isinstance(total, bool) or not isinstance(total, int) or total < 1:
        raise ScoringInputError(f"contract_role_section_invalid:{role.value}:target_total")
    return names, total


def _resolve_role_thresholds(
    section: Mapping[str, Any] | None,
    role: Role,
    rates: dict[str, Fraction],
    counts: dict[str, int],
) -> tuple[dict[str, Fraction], dict[str, int]]:
    """Apply a role section's declared threshold overrides over ``threshold_source.effective``.

    Absent leaves keep today's behaviour byte-for-byte: the signed v4.3/v4.4 claims section declares
    none, so claims still inherits the items floors (40/20) until a signed revision says otherwise.
    A present-but-invalid leaf raises, so a typo cannot silently fall back to the items values.
    """
    if section is None:
        return rates, counts
    resolved_counts = dict(counts)
    for field in _ROLE_THRESHOLD_OVERRIDE_FIELDS:
        if field not in section:
            continue
        value = section[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ScoringInputError(f"contract_role_section_invalid:{role.value}:{field}")
        resolved_counts[field] = value
    return rates, resolved_counts


def load_contract_gate_requirements(
    contract_path: str | Path = SIGNED_SCORING_CONTRACT_PATH,
    role: Role = Role.MATERIAL_ITEMS,
) -> ContractGateRequirements:
    """Load the authoritative gate thresholds for one role from the signed contract.

    ``role`` selects the contract's ``role_sections.<role>`` entry when it declares one. The
    frozen v4.2/v4.3 contracts predate ``role_sections`` and only serve ``Role.MATERIAL_ITEMS``;
    their legacy shape (exactly eleven ``NT-I**`` sentinels, target total 48) is preserved
    byte-for-byte, and every other role fails closed with ``contract_role_section_missing``.

    The returned dataclass keeps its frozen field set (the P03 binding verifier asserts it):
    ``material_items_target_total`` is read as the *role's* target total, so a claims section
    carries 20 there. Use ``role_target_total`` for reading it by intent.

    Rate thresholds stay role-identical and come from ``threshold_source.effective``. A role section
    may override the two accepted-record *count* floors (``accepted_records_total_min``,
    ``accepted_records_per_source_min``); when it declares none -- every signed contract so far --
    the effective block applies unchanged, so this hook is inert until a signed revision uses it.
    Any other threshold-looking key in a role section fails closed.
    """
    path = Path(contract_path)
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ScoringInputError(f"contract_unavailable:{path}") from exc
    except json.JSONDecodeError as exc:
        raise ScoringInputError(f"contract_invalid_json:{path}") from exc
    if not isinstance(payload, dict):
        raise ScoringInputError("signed scoring contract must be a JSON object")
    schema_version = payload.get("schema_version")
    if schema_version not in SUPPORTED_SIGNED_CONTRACT_SCHEMAS:
        raise ScoringInputError(
            "signed scoring contract schema_version mismatch: "
            f"{schema_version!r} not in {SUPPORTED_SIGNED_CONTRACT_SCHEMAS!r}"
        )
    if payload.get("status") != "frozen_signed":
        raise ScoringInputError("signed scoring contract status must be frozen_signed")
    signoff = _contract_object(payload, "signoff")
    if (
        not str(signoff.get("signed_by") or "").strip()
        or not str(signoff.get("signed_on") or "").strip()
    ):
        raise ScoringInputError("signed scoring contract signoff is incomplete")

    threshold_source = _contract_object(payload, "threshold_source")
    effective = _contract_object(threshold_source, "effective")
    rates: dict[str, Fraction] = {}
    for field in _CONTRACT_RATE_FIELDS:
        value = effective.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ScoringInputError(f"signed scoring contract field is not numeric: {field}")
        rates[field] = Fraction(str(value))
    counts: dict[str, int] = {}
    for field in _CONTRACT_COUNT_FIELDS:
        value = effective.get(field)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ScoringInputError(f"signed scoring contract field is not an integer: {field}")
        counts[field] = value

    if not isinstance(role, Role):
        try:
            role = Role(role)
        except ValueError as exc:
            raise ScoringInputError(f"contract_role_unknown:{role}") from exc
    pattern = _ROLE_ASSERTION_PATTERN.get(role)
    if pattern is None:
        raise ScoringInputError(f"contract_role_unknown:{role.value}")
    section = _contract_role_section(payload, role)
    if section is not None:
        sentinels, target_total = _resolve_role_sentinels(section, role, pattern)
    elif role is Role.MATERIAL_ITEMS and schema_version == SIGNED_SCORING_CONTRACT_SCHEMA:
        assertions = _contract_object(payload, "review_assertions")
        sentinels = tuple(sorted(key for key in assertions if re.fullmatch(pattern, key)))
        if len(sentinels) != _LEGACY_ITEMS_ASSERTION_COUNT:
            raise ScoringInputError(
                "signed scoring contract must contain exactly 11 NT-I review assertions"
            )
        if any(not isinstance(assertions[key], dict) for key in sentinels):
            raise ScoringInputError("signed scoring contract item assertions must be objects")
        target_total = _LEGACY_ITEMS_TARGET_TOTAL
    else:
        raise ScoringInputError(f"contract_role_section_missing:{role.value}")

    rates, counts = _resolve_role_thresholds(section, role, rates, counts)

    return ContractGateRequirements(
        schema_version=schema_version,
        role_scope=role,
        target_recall_overall_min=rates["target_recall_overall_min"],
        target_recall_per_source_min=rates["target_recall_per_source_min"],
        candidate_precision_min=rates["candidate_precision_min"],
        accepted_records_total_min=counts["accepted_records_total_min"],
        accepted_records_per_source_min=counts["accepted_records_per_source_min"],
        unresolved_candidates_max=counts["unresolved_candidates_max"],
        # Diagnostic denominator metadata; not one of the six gate thresholds.
        # Holds the gate role's target total (items 48, claims 20); prefer role_target_total.
        material_items_target_total=target_total,
        high_risk_item_assertions_required=sentinels,
    )


CONTRACT_GATE_REQUIREMENTS = load_contract_gate_requirements()


@dataclass(frozen=True)
class EvaluationReadiness:
    """External evidence needed before code scores may unlock a live trial."""

    development_gold_frozen: bool = False
    gold_frozen_before_candidates: bool = False
    adjudications_resolved: bool = False
    thresholds_signed_off: bool = False


DEFAULT_EVALUATION_READINESS = EvaluationReadiness()


@dataclass(frozen=True)
class QualityGateScore:
    """Rate result and readiness result kept separate to avoid false release.

    ``rate_gate_passed`` is the **contract** gate (``ContractGateRequirements``), the single
    authoritative boolean. The historical per-role pilot policy survives only as the
    ``pilot_policy_blockers`` diagnostic list — it no longer gates, so there is exactly one
    pass/fail verdict and never two competing truths.
    """

    rate_gate_passed: bool
    live_trial_ready: bool
    risk_condition_recall: Fraction | None
    rate_blockers: tuple[str, ...]
    readiness_blockers: tuple[str, ...]
    pilot_policy_blockers: tuple[str, ...] = ()
    risk_condition_by_role: tuple[tuple[str, int, int], ...] = ()


@dataclass(frozen=True)
class StructuredQualityReport:
    """Raw and validated quality ledgers plus deduplicated supporting sources."""

    raw: CandidateScore
    validated: CandidateScore
    unique_supported_sources: tuple[str, ...]
    coverage: CoverageScore
    report_support: ReportSupportScore
    gate: QualityGateScore


def score_structured_quality(
    gold: tuple[GoldRecord, ...],
    *,
    raw_candidates: tuple[CandidateRecord, ...],
    validated_candidates: tuple[CandidateRecord, ...],
    coverage_targets: tuple[CoverageTarget, ...] = (),
    coverage_observations: tuple[CoverageObservation, ...] = (),
    conclusions: tuple[ReportConclusion, ...] = (),
    policy: QualityPolicy = PILOT_CANDIDATE_POLICY,
    readiness: EvaluationReadiness = DEFAULT_EVALUATION_READINESS,
    matching_mode: MatchingMode = MatchingMode.ADJUDICATED,
    raw_mappings: Sequence[AdjudicatedMappingLike] | None = None,
    validated_mappings: Sequence[AdjudicatedMappingLike] | None = None,
    gate_requirements: ContractGateRequirements = CONTRACT_GATE_REQUIREMENTS,
) -> StructuredQualityReport:
    """Score raw and validated candidates independently against frozen gold.

    Under ``MatchingMode.ADJUDICATED`` (the default) every candidate must carry a mapping
    produced by human adjudication; the scorer only validates it. Under
    ``MatchingMode.LEGACY_IDENTITY`` the historical strict-equality matcher runs and mappings
    must be absent — the two paths are never mixed.
    """
    _check_matching_mode(matching_mode, raw_mappings, validated_mappings)
    _unique(gold, lambda item: item.record_id, "gold record_id")
    _unique(gold, lambda item: item.identity, "gold semantic identity")
    _unique(raw_candidates, lambda item: item.candidate_id, "raw candidate_id")
    _unique(validated_candidates, lambda item: item.candidate_id, "validated candidate_id")
    _unique(coverage_targets, lambda item: item.target_id, "coverage target_id")
    _unique(
        coverage_observations,
        lambda item: (item.target_id, item.stage),
        "coverage target/stage observation",
    )
    _unique(conclusions, lambda item: item.conclusion_id, "conclusion_id")
    raw_by_id = {item.candidate_id: item for item in raw_candidates}
    for item in validated_candidates:
        if raw_by_id.get(item.candidate_id) != item:
            raise ScoringInputError(
                f"validated candidate must be an unchanged raw candidate: {item.candidate_id}"
            )
    raw = _score_candidates(
        gold, raw_candidates, matching_mode=matching_mode, mappings=raw_mappings
    )
    validated = _score_candidates(
        gold, validated_candidates, matching_mode=matching_mode, mappings=validated_mappings
    )
    by_id = {item.record_id: item for item in gold}
    sources = tuple(sorted({by_id[item].source_id for item in validated.matched_gold_ids}))
    coverage = _score_coverage(coverage_targets, coverage_observations)
    support = _score_report_support(gold, coverage_targets, coverage_observations, conclusions)
    gate = _score_gate(
        gold,
        validated_candidates,
        validated,
        support,
        policy,
        readiness,
        requirements=gate_requirements,
    )
    return StructuredQualityReport(
        raw=raw,
        validated=validated,
        unique_supported_sources=sources,
        coverage=coverage,
        report_support=support,
        gate=gate,
    )


def _validate_record(identity: str, source_id: str, fields: tuple[tuple[str, str], ...]) -> None:
    if not identity or not source_id:
        raise ScoringInputError("record/candidate id and source_id must be non-empty")
    if not fields or any(not key or not value for key, value in fields):
        raise ScoringInputError(f"{identity}: semantic_fields must contain non-empty pairs")
    if fields != tuple(sorted(fields)) or len({key for key, _ in fields}) != len(fields):
        raise ScoringInputError(f"{identity}: semantic_fields must be key-unique and sorted")


def _unique[T](values: tuple[T, ...], key: Callable[[T], object], label: str) -> None:
    seen: set[object] = set()
    for value in values:
        current = key(value)
        if current in seen:
            raise ScoringInputError(f"duplicate {label}: {current}")
        seen.add(current)


def _check_matching_mode(
    matching_mode: MatchingMode,
    raw_mappings: Sequence[AdjudicatedMappingLike] | None,
    validated_mappings: Sequence[AdjudicatedMappingLike] | None,
) -> None:
    """Reject the two ways of getting matching wrong: a silent fallback and a mixed run."""
    if matching_mode is MatchingMode.ADJUDICATED:
        if raw_mappings is None or validated_mappings is None:
            raise ScoringInputError(
                "MatchingMode.ADJUDICATED requires raw_mappings and validated_mappings; "
                "the scorer never falls back to identity equality "
                "(read_path.equivalence_judgement.scorer_contract)"
            )
    elif raw_mappings is not None or validated_mappings is not None:
        raise ScoringInputError(
            "MatchingMode.LEGACY_IDENTITY must not be combined with adjudication mappings"
        )


@dataclass(frozen=True)
class _MatchOutcome:
    """Which candidates matched which gold, under one matching mode."""

    matched_ids: tuple[str, ...]
    false_positive_ids: tuple[str, ...]
    duplicate_ids: frozenset[str]
    correct_extra_ids: frozenset[str]


def _score_candidates(
    gold: tuple[GoldRecord, ...],
    candidates: tuple[CandidateRecord, ...],
    *,
    matching_mode: MatchingMode,
    mappings: Sequence[AdjudicatedMappingLike] | None,
) -> CandidateScore:
    if matching_mode is MatchingMode.LEGACY_IDENTITY:
        outcome = _match_by_identity(gold, candidates)
    else:
        outcome = _match_by_adjudication(gold, candidates, mappings or ())
    matched = set(outcome.matched_ids)
    false_positive_ids = set(outcome.false_positive_ids)
    remaining = {item.record_id: item for item in gold if item.record_id not in matched}
    metrics: list[RoleMetrics] = []
    origin_metrics: list[OriginMetrics] = []
    for role in Role:
        tp = sum(1 for item in gold if item.record_id in matched and item.role is role)
        fp = sum(
            1
            for candidate in candidates
            if candidate.candidate_id in false_positive_ids and candidate.role is role
        )
        fn = sum(1 for item in remaining.values() if item.role is role)
        duplicates = sum(
            1
            for candidate in candidates
            if candidate.candidate_id in outcome.duplicate_ids and candidate.role is role
        )
        extra = sum(
            1
            for candidate in candidates
            if candidate.candidate_id in outcome.correct_extra_ids and candidate.role is role
        )
        metrics.append(RoleMetrics(role, tp, fp, fn, duplicates, extra))
        for origin in RecordOrigin:
            origin_tp = sum(
                1
                for item in gold
                if item.record_id in matched and item.role is role and item.origin is origin
            )
            origin_fp = sum(
                1
                for candidate in candidates
                if candidate.candidate_id in false_positive_ids
                and candidate.role is role
                and candidate.origin is origin
            )
            origin_fn = sum(
                1 for item in remaining.values() if item.role is role and item.origin is origin
            )
            origin_extra = sum(
                1
                for candidate in candidates
                if candidate.candidate_id in outcome.correct_extra_ids
                and candidate.role is role
                and candidate.origin is origin
            )
            origin_metrics.append(
                OriginMetrics(role, origin, origin_tp, origin_fp, origin_fn, origin_extra)
            )
    return CandidateScore(
        roles=tuple(metrics),
        origins=tuple(origin_metrics),
        matched_gold_ids=tuple(outcome.matched_ids),
        missing_gold_ids=tuple(remaining),
    )


def _match_by_identity(
    gold: tuple[GoldRecord, ...], candidates: tuple[CandidateRecord, ...]
) -> _MatchOutcome:
    """Historical strict-equality matcher, kept for diagnostics and control arms only."""
    remaining = {item.record_id: item for item in gold}
    matched: list[str] = []
    false_positives: list[str] = []
    duplicate_ids: set[str] = set()
    seen_candidate_identities: set[tuple[object, ...]] = set()
    for candidate in candidates:
        if candidate.identity in seen_candidate_identities:
            duplicate_ids.add(candidate.candidate_id)
        else:
            seen_candidate_identities.add(candidate.identity)
        match = next(
            (item for item in remaining.values() if item.identity == candidate.identity), None
        )
        if match is None:
            false_positives.append(candidate.candidate_id)
            continue
        matched.append(match.record_id)
        remaining.pop(match.record_id)
    return _MatchOutcome(
        matched_ids=tuple(matched),
        false_positive_ids=tuple(false_positives),
        duplicate_ids=frozenset(duplicate_ids),
        correct_extra_ids=frozenset(),
    )


def _match_by_adjudication(
    gold: tuple[GoldRecord, ...],
    candidates: tuple[CandidateRecord, ...],
    mappings: Sequence[AdjudicatedMappingLike],
) -> _MatchOutcome:
    """Consume the finished human mapping; validate it, never re-derive it from fields."""
    gold_by_id = {item.record_id: item for item in gold}
    by_candidate: dict[str, AdjudicatedMappingLike] = {}
    for mapping in mappings:
        candidate_id = str(getattr(mapping, "candidate_id", "") or "")
        if not candidate_id:
            raise ScoringInputError("adjudication mapping is missing candidate_id")
        if candidate_id in by_candidate:
            raise ScoringInputError(f"duplicate adjudication mapping: {candidate_id}")
        by_candidate[candidate_id] = mapping
    matched: list[str] = []
    false_positives: list[str] = []
    duplicate_ids: set[str] = set()
    correct_extra_ids: set[str] = set()
    claimed_by: dict[str, str] = {}
    for candidate in candidates:
        mapping = by_candidate.get(candidate.candidate_id)
        if mapping is None:
            raise ScoringInputError(
                f"{candidate.candidate_id}: no adjudication mapping; "
                "unresolved_candidates_max = 0 forbids scoring an unmapped candidate"
            )
        judgement = _adjudication_judgement(candidate.candidate_id, mapping)
        gold_record_id = getattr(mapping, "gold_record_id", None)
        if judgement is AdjudicationJudgement.MATCHED:
            record = gold_by_id.get(str(gold_record_id or ""))
            if record is None:
                raise ScoringInputError(
                    f"{candidate.candidate_id}: mapped gold record {gold_record_id!r} is not "
                    "in the frozen gold"
                )
            if record.role is not candidate.role or record.source_id != candidate.source_id:
                raise ScoringInputError(
                    f"{candidate.candidate_id}: mapped gold {record.record_id} carries "
                    f"{record.role}/{record.source_id}, outside the candidate's "
                    f"{candidate.role}/{candidate.source_id}"
                )
            owner = claimed_by.get(record.record_id)
            if owner is not None:
                raise ScoringInputError(
                    f"gold {record.record_id} matched twice: {owner} and {candidate.candidate_id}"
                )
            claimed_by[record.record_id] = candidate.candidate_id
            matched.append(record.record_id)
        elif judgement is AdjudicationJudgement.CORRECT_EXTRA:
            correct_extra_ids.add(candidate.candidate_id)
        elif judgement is AdjudicationJudgement.DUPLICATE:
            duplicate_ids.add(candidate.candidate_id)
            false_positives.append(candidate.candidate_id)
        elif judgement is AdjudicationJudgement.INCORRECT:
            false_positives.append(candidate.candidate_id)
        elif judgement is AdjudicationJudgement.UNRESOLVED:
            raise ScoringInputError(
                f"{candidate.candidate_id}: unresolved adjudication violates "
                "unresolved_candidates_max = 0"
            )
        else:
            raise ScoringInputError(
                f"{candidate.candidate_id}: out_of_scope candidates must be filtered before "
                "scoring (adjudication_clause.scope_rules)"
            )
    return _MatchOutcome(
        matched_ids=tuple(matched),
        false_positive_ids=tuple(false_positives),
        duplicate_ids=frozenset(duplicate_ids),
        correct_extra_ids=frozenset(correct_extra_ids),
    )


def _adjudication_judgement(
    candidate_id: str, mapping: AdjudicatedMappingLike
) -> AdjudicationJudgement:
    raw = getattr(mapping, "judgement", "")
    try:
        return AdjudicationJudgement(str(raw))
    except ValueError as error:
        raise ScoringInputError(
            f"{candidate_id}: judgement {raw!r} is outside candidate_judgements"
        ) from error


def _score_coverage(
    targets: tuple[CoverageTarget, ...], observations: tuple[CoverageObservation, ...]
) -> CoverageScore:
    target_by_id = {item.target_id: item for item in targets}
    for observation in observations:
        target = target_by_id.get(observation.target_id)
        if target is None or observation.stage not in target.required_stages:
            raise ScoringInputError(
                f"unexpected coverage observation: {observation.target_id}/{observation.stage}"
            )
    observed = {(item.target_id, item.stage): item for item in observations}
    stages: list[StageMetrics] = []
    for stage in CoverageStage:
        eligible = [item for item in targets if stage in item.required_stages]
        passed = 0
        failures: list[str] = []
        for target in eligible:
            observation = observed.get((target.target_id, stage))
            if observation is None:
                failures.append(f"{target.target_id}:missing_observation")
            elif observation.outcome is CoverageOutcome.PASS:
                passed += 1
            else:
                suffix = f":{observation.reason}" if observation.reason else ""
                failures.append(f"{target.target_id}:{observation.outcome}{suffix}")
        sources = _source_stage_metrics(eligible, observed, stage)
        groups: list[GroupStageMetrics] = []
        for group in sorted({group for item in eligible for group in item.groups}):
            group_targets = [item for item in eligible if group in item.groups]
            group_passed = sum(
                observed.get((item.target_id, stage)) is not None
                and observed[(item.target_id, stage)].outcome is CoverageOutcome.PASS
                for item in group_targets
            )
            groups.append(
                GroupStageMetrics(
                    group,
                    group_passed,
                    len(group_targets),
                    _source_stage_metrics(group_targets, observed, stage),
                )
            )
        stages.append(
            StageMetrics(
                stage,
                passed,
                len(eligible),
                tuple(failures),
                sources,
                tuple(groups),
            )
        )
    return CoverageScore(tuple(stages))


def _source_stage_metrics(
    targets: list[CoverageTarget],
    observed: dict[tuple[str, CoverageStage], CoverageObservation],
    stage: CoverageStage,
) -> tuple[SourceStageMetrics, ...]:
    metrics: list[SourceStageMetrics] = []
    for source_id in sorted({item.source_id for item in targets}):
        source_targets = [item for item in targets if item.source_id == source_id]
        source_passed = sum(
            observed.get((item.target_id, stage)) is not None
            and observed[(item.target_id, stage)].outcome is CoverageOutcome.PASS
            for item in source_targets
        )
        metrics.append(SourceStageMetrics(source_id, source_passed, len(source_targets)))
    return tuple(metrics)


def _score_report_support(
    gold: tuple[GoldRecord, ...],
    targets: tuple[CoverageTarget, ...],
    observations: tuple[CoverageObservation, ...],
    conclusions: tuple[ReportConclusion, ...],
) -> ReportSupportScore:
    gold_ids = {item.record_id for item in gold}
    target_ids = {item.target_id for item in targets}
    observed = {(item.target_id, item.stage): item.outcome for item in observations}
    passed = 0
    failures: list[str] = []
    critical: list[str] = []
    for conclusion in conclusions:
        unknown = (
            set(conclusion.required_record_ids) | set(conclusion.cited_record_ids)
        ) - gold_ids
        if unknown:
            raise ScoringInputError(
                f"{conclusion.conclusion_id}: unknown record ids {sorted(unknown)}"
            )
        reasons: list[str] = []
        for record_id in conclusion.required_record_ids:
            if record_id not in conclusion.cited_record_ids:
                reasons.append(f"uncited:{record_id}")
                continue
            if record_id not in target_ids:
                reasons.append(f"delivery_target_absent:{record_id}")
                continue
            for stage in (CoverageStage.DELIVERY, CoverageStage.CONTEXT_USE):
                if observed.get((record_id, stage)) is not CoverageOutcome.PASS:
                    reasons.append(f"{stage}_not_passed:{record_id}")
        if reasons:
            failures.append(f"{conclusion.conclusion_id}:" + ",".join(reasons))
            if conclusion.critical:
                critical.append(conclusion.conclusion_id)
        else:
            passed += 1
    return ReportSupportScore(passed, len(conclusions), tuple(failures), tuple(critical))


def _score_gate(
    gold: tuple[GoldRecord, ...],
    validated_candidates: tuple[CandidateRecord, ...],
    validated: CandidateScore,
    support: ReportSupportScore,
    policy: QualityPolicy,
    readiness: EvaluationReadiness,
    requirements: ContractGateRequirements = CONTRACT_GATE_REQUIREMENTS,
) -> QualityGateScore:
    """Produce the gate verdicts.

    ``rate_gate_passed`` is the **contract** gate (``requirements`` loaded from the signed
    contract),
    evaluated inside the gate's role scope — it is the only pass/fail boolean. The per-role
    pilot policy survives as the ``pilot_policy_blockers`` diagnostic list and never gates.
    ``risk_condition`` is reported (per role, counts and rate) because contract
    ``metrics.risk_condition`` keeps the existing computation but assigns no threshold; the
    signed authority's instrument for high-risk coverage is the sentinel-assertion requirement
    (11 items under the signed gate v3; 16 under the superseded gate v2), which is a different
    instrument and must not be read as a risk-recall axis (16∩risk=10 of 21 marked records).
    Report support is a readiness precondition (contract
    ``metrics.quality_gate``), not a rate. Zero-unresolved is enforced structurally: the
    assembler rejects unresolved adjudications and the scorer rejects unmapped candidates.
    """
    matched = set(validated.matched_gold_ids)
    rate_blockers: list[str] = []

    # ---- contract gate, inside the gate's role scope -------------------------------
    scope_gold = [item for item in gold if item.role is requirements.role_scope]
    scope_matched = [item for item in scope_gold if item.record_id in matched]
    scope_metrics = validated.role(requirements.role_scope)

    if scope_metrics.recall is None:
        rate_blockers.append("contract_zero_denominator:target_recall_overall")
    elif scope_metrics.recall < requirements.target_recall_overall_min:
        rate_blockers.append(
            f"contract_below_threshold:target_recall_overall:{scope_metrics.recall}"
            f"<{requirements.target_recall_overall_min}"
        )
    if scope_metrics.precision is None:
        rate_blockers.append("contract_zero_denominator:candidate_precision")
    elif scope_metrics.precision < requirements.candidate_precision_min:
        rate_blockers.append(
            f"contract_below_threshold:candidate_precision:{scope_metrics.precision}"
            f"<{requirements.candidate_precision_min}"
        )
    if len(scope_matched) < requirements.accepted_records_total_min:
        rate_blockers.append(
            f"contract_below_threshold:accepted_records_total:{len(scope_matched)}"
            f"<{requirements.accepted_records_total_min}"
        )
    for source_id in sorted({item.source_id for item in scope_gold}):
        source_gold = [item for item in scope_gold if item.source_id == source_id]
        source_matched = sum(item.record_id in matched for item in source_gold)
        source_recall = Fraction(source_matched, len(source_gold))
        if source_recall < requirements.target_recall_per_source_min:
            rate_blockers.append(
                f"contract_below_threshold:target_recall_per_source:{source_id}:"
                f"{source_recall}<{requirements.target_recall_per_source_min}"
            )
        if source_matched < requirements.accepted_records_per_source_min:
            rate_blockers.append(
                f"contract_below_threshold:accepted_records_per_source:{source_id}:"
                f"{source_matched}<{requirements.accepted_records_per_source_min}"
            )
    for record_id in requirements.high_risk_item_assertions_required:
        if record_id not in matched:
            rate_blockers.append(f"contract_high_risk_assertion_unmatched:{record_id}")

    # ---- critical handling: pre-existing, unchanged --------------------------------
    rate_blockers.extend(f"critical_report_failure:{item}" for item in support.critical_failures)
    rate_blockers.extend(
        f"critical_gold_missing:{item.record_id}"
        for item in gold
        if item.critical and item.record_id not in matched
    )
    rate_blockers.extend(
        f"critical_error:{item.critical_error_code}:{item.candidate_id}"
        for item in validated_candidates
        if item.critical_error_code is not None
    )

    # ---- per-role pilot policy: diagnostic only, never gating ----------------------
    pilot_blockers: list[str] = []
    for role in Role:
        metrics = validated.role(role)
        threshold = policy.role(role)
        for name, value, minimum in (
            ("precision", metrics.precision, threshold.precision_min),
            ("recall", metrics.recall, threshold.recall_min),
        ):
            if value is None:
                pilot_blockers.append(f"zero_denominator:{role}:{name}")
            elif value < minimum:
                pilot_blockers.append(f"below_threshold:{role}:{name}:{value}<{minimum}")

    # ---- risk_condition: reported, not gating (contract has no threshold) ----------
    risk_gold = [item for item in gold if item.risk_or_condition]
    risk_recall = (
        Fraction(sum(item.record_id in matched for item in risk_gold), len(risk_gold))
        if risk_gold
        else None
    )
    risk_by_role = tuple(
        (
            role.value,
            sum(1 for item in risk_gold if item.record_id in matched and item.role is role),
            sum(1 for item in risk_gold if item.role is role),
        )
        for role in Role
        if any(item.role is role for item in risk_gold)
    )

    # ---- readiness ----------------------------------------------------------------
    readiness_blockers: list[str] = []
    for role in Role:
        count = sum(item.role is role for item in gold)
        if count < policy.min_gold_per_role:
            readiness_blockers.append(
                f"insufficient_sample:{role}:{count}/{policy.min_gold_per_role}"
            )
    if support.rate is None:
        readiness_blockers.append("zero_denominator:report_support")
    elif support.rate < policy.report_support_min:
        readiness_blockers.append(
            f"below_threshold:report_support:{support.rate}<{policy.report_support_min}"
        )
    for ready, blocker in (
        (readiness.development_gold_frozen, "development_gold_not_frozen"),
        (readiness.gold_frozen_before_candidates, "gold_not_frozen_before_candidates"),
        (readiness.adjudications_resolved, "adjudications_unresolved"),
        (readiness.thresholds_signed_off, "thresholds_not_signed_off"),
    ):
        if not ready:
            readiness_blockers.append(blocker)
    rate_passed = not rate_blockers
    return QualityGateScore(
        rate_gate_passed=rate_passed,
        live_trial_ready=rate_passed and not readiness_blockers,
        risk_condition_recall=risk_recall,
        rate_blockers=tuple(rate_blockers),
        readiness_blockers=tuple(readiness_blockers),
        pilot_policy_blockers=tuple(pilot_blockers),
        risk_condition_by_role=risk_by_role,
    )
