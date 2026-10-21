"""Explicit acceptance of incomplete text coverage, never a completeness review.

Only known PDF image/table extraction gaps may be accepted. The immutable record
binds the exact build and complete gap ledger; original units and gaps are retained.
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
    GapLifecycle,
    GapRecord,
    blocking_gaps,
)

STAGE_PREFIX = "text-publication:"
SCHEMA_REV = "text-publication-1"
ALLOWED_GAPS = frozenset(
    {
        "image_only_page",
        "image_region_unreadable",
        "table_extraction_failed",
        "table_lines_without_extraction",
    }
)


@dataclass(frozen=True)
class TextPublication:
    """Operator-recorded user authorization to serve available text with gaps."""

    source_id: str
    build_id: str
    build_fingerprint: str
    operator: str
    authorized_at: str
    authorization_ref: str
    gap_keys: tuple[str, ...]
    schema_rev: str = SCHEMA_REV
    policy_rev: str = GAP_POLICY_REV
    coverage_claim: str = "available_text_only_incomplete"

    def __post_init__(self) -> None:
        for name in ("source_id", "build_id", "build_fingerprint"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)
            ):
                raise ValueError(f"invalid text publication {name}")
        for value in (self.operator, self.authorized_at, self.authorization_ref):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("text publication requires operator, time and authorization")
        if datetime.fromisoformat(self.authorized_at).utcoffset() is None:
            raise ValueError("text publication time requires timezone")
        if (self.schema_rev, self.policy_rev, self.coverage_claim) != (
            SCHEMA_REV,
            GAP_POLICY_REV,
            "available_text_only_incomplete",
        ):
            raise ValueError("invalid text publication schema, policy or coverage claim")
        if (
            not isinstance(self.gap_keys, tuple)
            or not self.gap_keys
            or any(not isinstance(key, str) for key in self.gap_keys)
            or len(set(self.gap_keys)) != len(self.gap_keys)
        ):
            raise ValueError("text publication requires unique nonempty gap keys")

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> TextPublication:
        def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate text publication field")
                result[key] = value
            return result

        data = json.loads(payload, object_pairs_hook=unique)
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise ValueError("invalid text publication fields")
        if not isinstance(data["gap_keys"], list):
            raise ValueError("invalid text publication gap keys")
        data["gap_keys"] = tuple(data["gap_keys"])
        return cls(**data)

    @property
    def acceptance_id(self) -> str:
        return canonical_fingerprint(asdict(self))


def apply_text_publication(
    acceptance: TextPublication,
    build: Build,
    units: Iterable[Unit],
    records: Iterable[GapRecord],
) -> tuple[GapRecord, ...]:
    """Accept known visual omissions without changing text, scope or gap identity."""
    acceptance = TextPublication.from_json(acceptance.to_json())
    if (acceptance.source_id, acceptance.build_id, acceptance.build_fingerprint) != (
        build.source_id,
        build.build_id,
        canonical_fingerprint(asdict(build)),
    ):
        raise ValueError("text publication build binding mismatch")
    records = tuple(records)
    blocking = blocking_gaps(records)
    if set(acceptance.gap_keys) != {r.key for r in blocking}:
        raise ValueError("text publication must cover exactly the blocking gap ledger")
    if any(
        r.code not in ALLOWED_GAPS
        or r.coordinates.kind is not GapCoordinateKind.PAGE
        or not r.coordinates.page
        or r.coordinates.page < 1
        for r in blocking
    ):
        raise ValueError("text publication cannot accept unknown or unlocated gaps")
    kept = [u for u in units if u.status is UnitStatus.KEPT and u.raw_text.strip()]
    if not kept or any(u.build_id != build.build_id for u in kept):
        raise ValueError("text publication requires retained text from this build")
    return tuple(
        replace(
            r,
            lifecycle=GapLifecycle.ACKNOWLEDGED,
            basis=f"text_publication:{acceptance.acceptance_id}",
            remedy="Available text only; image/table content remains missing. "
            "Use OCR or a readable source when that content is needed.",
        )
        if r.key in acceptance.gap_keys
        else r
        for r in records
    )
