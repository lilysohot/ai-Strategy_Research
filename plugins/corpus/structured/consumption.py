"""Semantic evidence adapters for the existing ConsumptionLedger and A4 verifier.

No extraction, publication writes, fetch events, or independent report checker.
Delivery is confirmed only from successful model request messages, not resolver reads.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from frontier_agent.core.messages import Message, text_of
from plugins.corpus.structured.ledger import StructuredExecutionError
from plugins.corpus.structured.query import (
    DependencyKind,
    Purpose,
    QueryEvidence,
    SemanticQueryPage,
    SemanticQueryRecord,
    publication_records,
)
from plugins.corpus.structured.snapshot import source_unit_id
from plugins.corpus.structured.store import read_semantic

SEMANTIC_TOOL = "corpus_semantic_query"
_HASH = r"^sha256:[0-9a-f]{64}$"
_HANDLE = r"^cv2:[A-Za-z0-9._:-]+#chunk:[A-Za-z0-9._:-]+$"


def quote_hash(text: str) -> str:
    """Hash the quoted span, not the complete authoritative source unit."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class SemanticRange(BaseModel):
    """An exact source-unit interval bound to the hash of its quoted text."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    handle: str = Field(pattern=_HANDLE)
    unit_id: str
    coordinate_system: Literal["unicode_code_points"] = "unicode_code_points"
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    quote_sha256: str = Field(pattern=_HASH)


class SemanticDependency(BaseModel):
    """A purpose-sensitive context requirement tied to one evidence range."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: DependencyKind
    range_index: int = Field(ge=0)
    required_for: tuple[Purpose, ...] = Field(min_length=1)
    status: Literal["present", "missing", "ambiguous"]


class ReportSemanticReference(BaseModel):
    """Frozen report-semantic-reference-v1; reported statuses are never trusted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["corpus-report-semantic-reference-v1"] = (
        "corpus-report-semantic-reference-v1"
    )
    report_anchor: str = Field(min_length=1)
    report_quote: str = Field(min_length=1)
    publication_id: str = Field(pattern=_HASH)
    record_id: str = Field(min_length=1)
    purpose: Purpose
    evidence_ranges: tuple[SemanticRange, ...] = Field(min_length=1)
    dependency_assertions: tuple[SemanticDependency, ...] = ()
    delivery_status: Literal["pending", "delivered", "trimmed", "not_delivered"] = "pending"
    publication_status: Literal["published", "withdrawn", "superseded"] = "published"
    quality_status: Literal["accepted", "review_required", "rejected"] = "review_required"
    verification_status: Literal["pending", "verified", "degraded", "failed"] = "pending"
    error_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def check_ranges(self) -> ReportSemanticReference:
        if any(r.end <= r.start for r in self.evidence_ranges):
            raise ValueError("invalid evidence interval")
        if any(
            d.range_index >= len(self.evidence_ranges)
            or len(set(d.required_for)) != len(d.required_for)
            for d in self.dependency_assertions
        ):
            raise ValueError("invalid dependency range or purposes")
        return self


def range_for_evidence(proof: QueryEvidence) -> SemanticRange:
    """Bridge delivered query evidence to the frozen report range contract."""
    return SemanticRange(
        handle=proof.handle,
        unit_id=proof.unit_id,
        start=proof.start,
        end=proof.end,
        quote_sha256=quote_hash(proof.quote),
    )


def reference_for_record(
    publication_id: str,
    record: SemanticQueryRecord,
    purpose: Purpose,
    report_anchor: str,
    report_quote: str,
) -> ReportSemanticReference:
    """Build the frozen bridge, without claiming publication or delivery success."""
    return ReportSemanticReference(
        publication_id=publication_id,
        record_id=record.record_id,
        purpose=purpose,
        report_anchor=report_anchor,
        report_quote=report_quote,
        evidence_ranges=tuple(range_for_evidence(e) for e in record.evidence),
        dependency_assertions=tuple(
            SemanticDependency(
                kind=d.kind,
                range_index=d.evidence_index,
                required_for=d.required_for,
                status=d.status,
            )
            for d in record.dependencies
        ),
    )


@dataclass
class SemanticReceipt:
    """One query result and its independently confirmed per-record delivery state."""

    source_id: str
    build_id: str
    call_id: str
    turn: int
    page: SemanticQueryPage
    statuses: dict[str, str] = field(default_factory=dict)


@dataclass
class SemanticConsumption:
    """Owned by ConsumptionLedger; separate from legacy fetch counters."""

    calls: list[dict[str, Any]] = field(default_factory=list)
    receipts: list[SemanticReceipt] = field(default_factory=list)

    def record_call(self, args: dict[str, Any], call_id: str, turn: int) -> None:
        self.calls.append(
            {"tool": SEMANTIC_TOOL, "call_id": call_id, "turn": turn, "args": dict(args)}
        )

    def record_result(self, args: dict[str, Any], body: str, call_id: str, turn: int) -> None:
        try:
            page = SemanticQueryPage.model_validate_json(body)
        except ValueError:
            return
        self.receipts.append(
            SemanticReceipt(
                source_id=str(args.get("source_id") or ""),
                build_id=str(args.get("build_id") or ""),
                call_id=call_id,
                turn=turn,
                page=page,
                statuses={r.record_id: "pending" for r in page.records},
            )
        )

    def confirm_request(self, messages: list[Message]) -> None:
        """Match the exact tool call, publication, query and whole record, not substrings."""
        bodies = {
            str(m.get("tool_call_id") or ""): text_of(m.get("content"))
            for m in messages
            if m.get("role") == "tool"
        }
        for receipt in self.receipts:
            body = bodies.get(receipt.call_id, "")
            try:
                page = SemanticQueryPage.model_validate_json(body)
            except ValueError:
                page = None
            matching = (
                page is not None
                and page.publication_id == receipt.page.publication_id
                and page.query_sha256 == receipt.page.query_sha256
                and page.purpose == receipt.page.purpose
            )
            for record in receipt.page.records:
                if receipt.statuses[record.record_id] == "delivered":
                    continue
                if matching and page is not None and record in page.records:
                    status = "delivered"
                else:
                    status = "trimmed" if body else "not_delivered"
                receipt.statuses[record.record_id] = status

    def observations(self, publication_id: str, record_id: str) -> list[SemanticReceipt]:
        return [
            r
            for r in self.receipts
            if r.page.publication_id == publication_id and record_id in r.statuses
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "receipts": [
                {
                    "source_id": r.source_id,
                    "build_id": r.build_id,
                    "tool": SEMANTIC_TOOL,
                    "call_id": r.call_id,
                    "turn": r.turn,
                    "page": r.page.model_dump(mode="json"),
                    "delivery": r.statuses,
                }
                for r in self.receipts
            ],
        }


def verify_reference(
    ref: ReportSemanticReference,
    consumption: SemanticConsumption,
    *,
    final_text: str | None,
    pending_aware: bool,
) -> tuple[ReportSemanticReference, list[dict[str, str]]]:
    """Read-only source/publication adapter; A4 remains responsible for report outcomes."""
    problems: list[dict[str, str]] = []
    codes: list[str] = []
    publication_status = "published"
    quality_status = "review_required"
    delivery = "not_delivered"

    def problem(code: str, message: str, state_code: str) -> None:
        problems.append({"code": code, "message": message})
        codes.append(state_code)

    observations = consumption.observations(ref.publication_id, ref.record_id)
    if not observations:
        problem("source_unresolvable", "语义记录未在本运行查询结果中登记", "CS_NOT_FOUND")
    else:
        # A successful request dominates an earlier trim, but no resolver read
        # can advance delivery. Match the original record/ranges below as well.
        statuses = {r.statuses[ref.record_id] for r in observations}
        delivery = next(
            s for s in ("delivered", "pending", "trimmed", "not_delivered") if s in statuses
        )
        observed = observations[0]
        try:
            view = read_semantic(observed.source_id, observed.build_id)
            if view.manifest.publication_id != ref.publication_id:
                publication_status = "superseded"
                problem("publication_invalid", "语义发布版本已变更，必须重查", "CS_NOT_PUBLISHED")
            else:
                records = publication_records(view, ref.purpose)
                record = next((r for r in records if r.record_id == ref.record_id), None)
                if record is None:
                    problem("source_unresolvable", "当前发布无此记录", "CS_NOT_FOUND")
                else:
                    quality_status = record.quality_status
                    canonical = reference_for_record(
                        ref.publication_id,
                        record,
                        ref.purpose,
                        ref.report_anchor,
                        ref.report_quote,
                    )
                    if ref.evidence_ranges != canonical.evidence_ranges:
                        problem(
                            "invalid_evidence",
                            "原文范围不等于完整发布证据单元",
                            "CS_CONTEXT_INCOMPLETE",
                        )
                    if ref.dependency_assertions != canonical.dependency_assertions:
                        problem(
                            "missing_dependencies",
                            "必要依赖声明被删除或改写",
                            "CS_CONTEXT_INCOMPLETE",
                        )
                    if ref.purpose not in record.usable_for:
                        problem(
                            "purpose_not_allowed", "当前记录不许可该用途", "CS_CONTEXT_INCOMPLETE"
                        )
                    if record.context_status != "complete" or any(
                        ref.purpose in d.required_for and d.status != "present"
                        for d in record.dependencies
                    ):
                        problem(
                            "missing_dependencies", "当前证据语境不完整", "CS_CONTEXT_INCOMPLETE"
                        )
                    if record.quality_status != "accepted":
                        problem("quality_not_accepted", "记录质量未合格", "CS_CONTEXT_INCOMPLETE")
                    # Verify exact source-unit coordinates and hashes; never .find().
                    units = {
                        (
                            f"cv2:{view.snapshot.build_id}#chunk:"
                            f"{u.chunk_id.removeprefix('chunk:')}",
                            source_unit_id(u),
                        ): u
                        for u in view.snapshot.units
                    }
                    for proof in record.evidence:
                        unit = units.get((proof.handle, proof.unit_id))
                        if (
                            unit is None
                            or not 0 <= proof.start < proof.end <= len(unit.text)
                            or unit.text[proof.start : proof.end] != proof.quote
                            or unit.text_sha256 != proof.text_sha256
                        ):
                            problem(
                                "quote_not_found",
                                "权威同版本原文区间/引文不符",
                                "CS_ARTIFACT_CORRUPT",
                            )
                    # Query receipt must contain this exact evidence record too.
                    if delivery == "delivered" and not any(
                        record in r.page.records
                        for r in observations
                        if r.statuses[ref.record_id] == "delivered"
                    ):
                        delivery = "not_delivered"
        except StructuredExecutionError as exc:
            if exc.code == "CS_NOT_PUBLISHED":
                publication_status = "withdrawn"
                problem("publication_invalid", str(exc), exc.code)
            else:
                problem("verification_error", str(exc), exc.code)
        except Exception as exc:
            problem("verification_error", f"{type(exc).__name__}: {exc}", "CS_OUTCOME_UNKNOWN")

    if delivery != "delivered":
        problem(
            "pending_delivery" if delivery == "pending" and pending_aware else "not_delivered",
            "语义证据尚未完整进入实际模型请求",
            "CS_CONTEXT_INCOMPLETE",
        )
    if final_text is not None and ref.report_quote not in final_text:
        problem("not_in_report", "report_quote 未出现在最终报告", "CS_INPUT_INVALID")
    result = ref.model_copy(
        update={
            "delivery_status": delivery,
            "publication_status": publication_status,
            "quality_status": quality_status,
            "verification_status": "verified"
            if not problems
            else (
                "pending"
                if pending_aware and all(p["code"] == "pending_delivery" for p in problems)
                else "failed"
                if any(
                    p["code"]
                    in {
                        "verification_error",
                        "invalid_evidence",
                        "source_unresolvable",
                        "quote_not_found",
                    }
                    for p in problems
                )
                else "degraded"
            ),
            "error_codes": tuple(dict.fromkeys(codes)),
        }
    )
    return result, problems
