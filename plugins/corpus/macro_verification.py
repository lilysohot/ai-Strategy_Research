"""Application-owned M1 audit authority and controlled unit normalization.

Only trusted application code may configure/call this authority. It is not an
agent tool, authentication service, durable store, or M4 semantic verifier.
Serialized receipts alone confer no authority; restart defaults to no trust.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal, localcontext
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from plugins.corpus.macro_models import (
    Dimensions,
    EvidenceReference,
    FrozenModel,
    MacroObservation,
    MacroRecord,
    RawAmount,
    ReasonCode,
    Scope,
    SourceTime,
    VerificationRecord,
)


class VerificationAuthority:
    """Host-controlled append-only receipts; caller owns actual review and authentication."""

    def __init__(
        self,
        *,
        issuer_id: str,
        issuer_role: Literal["human_reviewer", "source_adapter"],
        policy_version: str,
        resolve: Callable[[EvidenceReference], str],
    ) -> None:
        self._issuer_id = issuer_id
        self._issuer_role: Literal["human_reviewer", "source_adapter"] = issuer_role
        self._policy_version = policy_version
        self._resolve = resolve
        self._issued: dict[str, VerificationRecord] = {}

    def issue(
        self,
        subject: MacroRecord,
        *,
        scopes: tuple[Scope, ...],
        evidence: tuple[EvidenceReference, ...],
        reviewed_at: SourceTime,
        decision: Literal["approved", "rejected", "unknown"],
        reason_codes: tuple[ReasonCode, ...] = (),
    ) -> VerificationRecord:
        # No arbitrary receipt import method: issuer identity is configuration, not payload.
        for reference in evidence:
            if self._resolve(reference) != reference.quote:
                raise ValueError("atomic_evidence_mismatch")
        receipt = VerificationRecord(
            subject_id=subject.record_id,
            issuer_id=self._issuer_id,
            issuer_role=self._issuer_role,
            policy_version=self._policy_version,
            reviewed_at=reviewed_at,
            decision=decision,
            scopes=scopes,
            evidence=evidence,
            reason_codes=reason_codes,
        )
        if receipt.record_id in self._issued:
            raise ValueError("duplicate_identity")
        self._issued[receipt.record_id] = receipt
        return receipt

    def accepts(
        self, receipt_id: str | None, subject: MacroRecord, scopes: tuple[Scope, ...]
    ) -> bool:
        receipt = self._issued.get(receipt_id or "")
        return bool(
            receipt
            and receipt.subject_id == subject.record_id
            and receipt.decision == "approved"
            and receipt.policy_version == self._policy_version
            and set(scopes) <= set(receipt.scopes)
        )


class UnitNormalization(FrozenModel):
    status: Literal["normalized", "blocked"]
    observation_id: str
    raw: RawAmount
    value_jobs: Annotated[Decimal, Field(allow_inf_nan=False)] | None
    conversion_version: Literal["nfp-jobs-1"] = "nfp-jobs-1"
    verification_ref: str | None = None
    reason_codes: tuple[ReasonCode, ...] = ()
    # Arithmetic normalization is explicitly not source verification or calculation permission.
    calculation_permitted: Literal[False] = False

    @model_validator(mode="after")
    def consistent_state(self) -> Self:
        if self.status == "blocked" and (self.value_jobs is not None or not self.reason_codes):
            raise ValueError("blocked normalization needs null value and reasons")
        if self.status == "normalized" and (self.value_jobs is None or self.reason_codes):
            raise ValueError("normalized result needs a finite value and no blocking reasons")
        return self


def normalize_jobs(
    observation: MacroObservation,
    *,
    authority: VerificationAuthority | None = None,
    verification_ref: str | None = None,
) -> UnitNormalization:
    """Explicit jobs scale directly; source-language units need an issued series mapping receipt."""
    reason: ReasonCode | None = None
    scale = None
    dimensions = Dimensions(
        country="US",
        indicator="US.NFP_CHANGE_SA",
        population="nonfarm_payroll_jobs",
        transform="month_change",
        adjustment="SA",
    )
    if observation.dimensions != dimensions or observation.qualifiers:
        reason = "indicator_mismatch"
    elif observation.amount.numeric is None:
        reason = "value_unverified"
    elif observation.amount.unit_raw in {"jobs", "thousand_jobs"}:
        scale = 1 if observation.amount.unit_raw == "jobs" else 1000
    elif observation.amount.unit_raw in {"万", "万人", "in thousands", "Numbers in thousands"}:
        if authority and authority.accepts(
            verification_ref, observation, ("indicator", "unit_mapping")
        ):
            scale = 10000 if observation.amount.unit_raw in {"万", "万人"} else 1000
        else:
            reason = "verification_untrusted"
    else:
        reason = "unit_unverified"
    value = None
    if scale is not None:
        number = observation.amount.numeric
        assert number is not None
        with localcontext() as context:
            context.prec = max(28, len(number.as_tuple().digits) + 8)
            value = number * scale
    return UnitNormalization(
        status="blocked" if reason else "normalized",
        observation_id=observation.record_id,
        raw=observation.amount,
        value_jobs=value,
        verification_ref=verification_ref,
        reason_codes=(reason,) if reason else (),
    )
