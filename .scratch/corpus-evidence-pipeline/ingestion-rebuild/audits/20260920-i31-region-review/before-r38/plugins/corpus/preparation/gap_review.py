"""Build-bound human gap credentials; no OCR, source rewriting, or grading overrides.

The named reviewer attests that required_locators is the COMPLETE approved evidence
set for evidence_scope_ref. This is a human credential, like ReviewedDecision, not
an automatic derivation from retrieval hits or a cryptographic identity service.
The verifier independently checks identity, ledger closure, retained evidence and
coordinate disjointness. It cannot infer the meaning of unread visual content.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from datetime import datetime

from plugins.corpus.preparation.contract import Build, Unit, UnitStatus, canonical_fingerprint
from plugins.corpus.preparation.gaps import (
    GAP_POLICY_REV,
    GapCoordinateKind,
    GapCoordinates,
    GapLifecycle,
    GapRecord,
    blocking_gaps,
    parse_gap_location,
)

SCHEMA_REV = "human-gap-review-1"
REVIEW_STAGE_PREFIX = "human-gap-review:"
ATTESTATION = "human_verified_complete_scope_and_nonintersection"


class GapReviewError(ValueError):
    """Invalid, conflicting, stale or unverifiable human credential."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GapReviewError(f"duplicate gap review field: {key}")
        result[key] = value
    return result


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GapReviewError(f"gap review requires nonempty {name}")
    return value


def _coordinate(locator: str) -> GapCoordinates:
    coordinate = parse_gap_location(locator)
    if coordinate.kind is GapCoordinateKind.PAGE and coordinate.page and coordinate.page > 0:
        return coordinate
    if (
        coordinate.kind is GapCoordinateKind.CHAR
        and coordinate.char_start is not None
        and coordinate.char_end is not None
        and 0 <= coordinate.char_start < coordinate.char_end
    ):
        return coordinate
    raise GapReviewError(f"gap review coordinate cannot be verified: {locator!r}")


@dataclass(frozen=True)
class GapReview:
    """One immutable, fully signed review per build; each blocking gap has a rationale."""

    schema_rev: str
    policy_rev: str
    source_id: str
    build_id: str
    build_fingerprint: str
    reviewer: str
    reviewed_at: str
    evidence_scope_ref: str
    required_locators: tuple[str, ...]
    scope_rationale: str
    attestation: str
    gaps: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        for name in (
            "source_id",
            "build_id",
            "build_fingerprint",
            "reviewer",
            "reviewed_at",
            "evidence_scope_ref",
            "scope_rationale",
        ):
            _text(getattr(self, name), name)
        for name in ("source_id", "build_id", "build_fingerprint"):
            value = getattr(self, name)
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise GapReviewError(f"invalid gap review hash: {name}")
        if self.schema_rev != SCHEMA_REV or self.policy_rev != GAP_POLICY_REV:
            raise GapReviewError("unknown or stale gap review schema/policy_rev")
        if self.attestation != ATTESTATION:
            raise GapReviewError("missing human attestation of complete scope and nonintersection")
        try:
            reviewed_at = datetime.fromisoformat(self.reviewed_at)
        except ValueError as exc:
            raise GapReviewError("invalid gap review reviewed_at") from exc
        if reviewed_at.utcoffset() is None:
            raise GapReviewError("gap review reviewed_at must include timezone")
        if not isinstance(self.required_locators, tuple) or not self.required_locators:
            raise GapReviewError("gap review requires the complete nonempty required_locators")
        for locator in self.required_locators:
            _coordinate(_text(locator, "required_locator"))
        if len(set(self.required_locators)) != len(self.required_locators):
            raise GapReviewError("duplicate required locator")
        if not isinstance(self.gaps, tuple) or not self.gaps:
            raise GapReviewError("gap review requires per-gap rationales")
        for key, rationale in self.gaps:
            _text(key, "gap key")
            _text(rationale, "gap rationale")
        if len(dict(self.gaps)) != len(self.gaps):
            raise GapReviewError("duplicate reviewed gap")

    @classmethod
    def from_json(cls, payload: str) -> GapReview:
        """Strict parser: duplicate, missing, unknown and malformed fields reject."""
        try:
            data = json.loads(payload, object_pairs_hook=_unique_object)
            if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
                raise GapReviewError("gap review fields do not match schema")
            if not isinstance(data["required_locators"], list) or not isinstance(
                data["gaps"], dict
            ):
                raise GapReviewError("gap review locators/gaps have invalid shape")
            data["required_locators"] = tuple(data["required_locators"])
            data["gaps"] = tuple(sorted(data["gaps"].items()))
            return cls(**data)
        except (TypeError, ValueError) as exc:
            raise GapReviewError(f"invalid human gap review: {exc}") from exc

    def as_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["required_locators"] = list(self.required_locators)
        payload["gaps"] = dict(self.gaps)
        return payload

    def to_json(self) -> str:
        return json.dumps(self.as_payload(), ensure_ascii=False, sort_keys=True)

    @property
    def review_id(self) -> str:
        return canonical_fingerprint(self.as_payload())


def review_template(build: Build, records: Iterable[GapRecord]) -> dict[str, object]:
    """Unsigned template; never auto-fill reviewer, scope, rationale or attestation."""
    return {
        "schema_rev": SCHEMA_REV,
        "policy_rev": GAP_POLICY_REV,
        "source_id": build.source_id,
        "build_id": build.build_id,
        "build_fingerprint": canonical_fingerprint(asdict(build)),
        "reviewer": "",
        "reviewed_at": "",
        "evidence_scope_ref": "",
        "required_locators": [],
        "scope_rationale": "",
        "attestation": "",
        "gaps": {record.key: "" for record in blocking_gaps(records)},
    }


def _retained(coordinate: GapCoordinates, units: tuple[Unit, ...]) -> bool:
    if coordinate.kind is GapCoordinateKind.PAGE:
        return any(unit.location.page == coordinate.page for unit in units)
    # Require complete coverage of the required character range, not merely one hit.
    cursor = coordinate.char_start
    end = coordinate.char_end
    if cursor is None or end is None:
        return False
    spans = sorted(
        (unit.location.char_span.start, unit.location.char_span.end)
        for unit in units
        if unit.location.char_span is not None
    )
    for low, high in spans:
        if low > cursor:
            break
        cursor = max(cursor, high)
        if cursor >= end:
            return True
    return False


def _disjoint(left: GapCoordinates, right: GapCoordinates) -> bool:
    # No invented page→character mapping, and no artificial bbox inside a page gap.
    if left.kind is not right.kind:
        return False
    if left.kind is GapCoordinateKind.PAGE:
        return left.page != right.page
    if left.kind is GapCoordinateKind.CHAR:
        assert left.char_start is not None and left.char_end is not None
        assert right.char_start is not None and right.char_end is not None
        return left.char_end <= right.char_start or right.char_end <= left.char_start
    return False


def apply_gap_review(
    review: GapReview,
    build: Build,
    units: Iterable[Unit],
    records: Iterable[GapRecord],
) -> tuple[GapRecord, ...]:
    """Revalidate the signed credential at registration AND each publication/read gate."""
    review = GapReview.from_json(review.to_json())
    if (
        review.source_id != build.source_id
        or review.build_id != build.build_id
        or review.build_fingerprint != canonical_fingerprint(asdict(build))
    ):
        raise GapReviewError(
            "gap review binding mismatch: source/build/decision/revisions/scope/ledger"
        )
    records = tuple(records)
    blocking = blocking_gaps(records)
    if set(dict(review.gaps)) != {record.key for record in blocking}:
        raise GapReviewError("review must cover exactly all currently blocking gap_regions")
    kept = tuple(unit for unit in units if unit.status is UnitStatus.KEPT)
    if any(unit.build_id != build.build_id for unit in kept):
        raise GapReviewError("required evidence units belong to another build")
    required = tuple(_coordinate(locator) for locator in review.required_locators)
    if not all(_retained(coordinate, kept) for coordinate in required):
        raise GapReviewError("required evidence locator is absent or not fully retained")
    for record in blocking:
        if record.status is None:
            raise GapReviewError("unclassified gap cannot be acknowledged by human review")
        coordinate = _coordinate(record.location)
        if not all(_disjoint(coordinate, target) for target in required):
            raise GapReviewError(f"gap/evidence overlap or incomparable coordinates: {record.key}")
    return tuple(
        replace(
            record,
            lifecycle=GapLifecycle.ACKNOWLEDGED,
            basis=f"human_gap_review:{review.review_id}:{review.reviewer}",
            remedy="Human reviewed for this evidence scope; gap remains visible and coverage scoped.",
        )
        if record.key in dict(review.gaps)
        else record
        for record in records
    )
