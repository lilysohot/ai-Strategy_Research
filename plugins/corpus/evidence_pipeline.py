"""Evidence → verified facts → computation-ready observations.

Table facts are projected from parser-owned cells. Prose may use an injected LLM,
but the same deterministic evidence and dimensional checks govern its output.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from pydantic import BaseModel, ConfigDict

from plugins.corpus._semantic_validation import prose_binding_reasons
from plugins.corpus.claims import LlmCallError, LlmFn, LlmResponse, parse_value
from plugins.corpus.claims_detail import (
    EXTRACTOR_VERSION_V2,
    LINT_VERSION,
    ClaimRecord,
    apply_lint,
    build_prompt_v2,
    classify_doc_kind_detail,
    parse_claims_json_detail,
    records_from_payload,
    triage_block_detail,
)
from plugins.corpus.evidence import (
    Cell,
    EvidenceDocument,
    EvidencePacket,
    Span,
    fingerprint,
    parse_evidence,
)

if TYPE_CHECKING:
    from plugins.corpus.structured.snapshot import EvidenceSnapshot, SnapshotUnit

PIPELINE_VERSION = "evidence-pipeline-7"
# Only controlled metrics enter generic numeric computations. Unmapped facts remain readable.
METRICS: dict[str, tuple[str, str]] = {
    "营业收入": ("revenue", "元"),
    "营业总收入": ("revenue", "元"),
    "营收": ("revenue", "元"),
    "revenue": ("revenue", "元"),
    "归属母公司净利润": ("parent_net_profit", "元"),
    "归母净利润": ("parent_net_profit", "元"),
    "归属于母公司净利润": ("parent_net_profit", "元"),
    "净利润": ("net_profit", "元"),
    "经营活动现金流": ("operating_cash_flow", "元"),
    "经营活动产生的现金流量净额": ("operating_cash_flow", "元"),
    "研发费用": ("research_expense", "元"),
    "财务费用": ("finance_expense", "元"),
    "应收票据": ("notes_receivable", "元"),
    "资产合计": ("assets", "元"),
    "资产总计": ("assets", "元"),
    "负债合计": ("liabilities", "元"),
    "所有者权益合计": ("equity", "元"),
    "少数股东损益": ("minority_profit", "元"),
    "净利率": ("net_margin", "%"),
    "毛利率": ("gross_margin", "%"),
    "P/E": ("pe", "倍"),
    "PE": ("pe", "倍"),
    "P/B": ("pb", "倍"),
    "PB": ("pb", "倍"),
    "市盈率（PE）": ("pe", "倍"),
    "市净率（PB）": ("pb", "倍"),
    "EV/EBITDA": ("ev_ebitda", "倍"),
}


class EvidenceFact(BaseModel):
    model_config = ConfigDict(frozen=True)
    fact_id: str
    packet_id: str
    claim: ClaimRecord
    metric_id: str | None = None
    usable_for: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    evidence_alignment: dict[str, object] | None = None


class PacketRun(BaseModel):
    model_config = ConfigDict(frozen=True)
    packet_id: str
    status: str
    method: str
    records: int = 0
    reasons: tuple[str, ...] = ()
    diagnostics: dict[str, object] | None = None


class EvidenceRun(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: str
    document: EvidenceDocument
    pipeline_version: str = PIPELINE_VERSION
    extractor_version: str = EXTRACTOR_VERSION_V2
    lint_version: str = LINT_VERSION
    model: str | None = None
    facts: tuple[EvidenceFact, ...]
    packet_runs: tuple[PacketRun, ...]

    def summary(self) -> dict[str, object]:
        return {
            "doc_id": self.document.doc_id,
            "run_id": self.run_id,
            "packets": len(self.document.packets),
            "facts": len(self.facts),
            "quality": dict(Counter(f.claim.quality_status for f in self.facts)),
            "calculation_ready": sum("calculate" in f.usable_for for f in self.facts),
            "packet_status": dict(Counter(r.status for r in self.packet_runs)),
            "complete": all(
                r.status not in {"failed", "unknown", "deferred"} for r in self.packet_runs
            ),
            "coverage_verified": False,
            "completeness_meaning": "packet_execution_only_not_target_recall",
        }

    def verify_identity(self) -> None:
        payload = self.model_dump(mode="json")
        claimed = payload.pop("run_id")
        if self.pipeline_version in {"evidence-pipeline-1", "evidence-pipeline-2"}:
            # Historical versions did not carry this field. Preserve their original hash contract.
            for packet in payload["packet_runs"]:
                if packet.get("diagnostics") is None:
                    packet.pop("diagnostics", None)
        if self.pipeline_version in {
            "evidence-pipeline-1",
            "evidence-pipeline-2",
            "evidence-pipeline-3",
        }:
            for fact in payload["facts"]:
                if fact.get("evidence_alignment") is None:
                    fact.pop("evidence_alignment", None)
        if fingerprint(payload) != claimed:
            raise ValueError("evidence run content hash mismatch")


def align_quote(quote: str, text: str) -> dict[str, object] | None:
    """Find a unique original substring, allowing ONLY whitespace layout differences.

    Numeric validation still runs on the recovered ORIGINAL text, so joining
    source '1 20' into a fabricated '120' never passes the numeric gate.
    """
    needle = re.sub(r"\s+", "", quote)
    if not needle:
        return None
    positions = [i for i, char in enumerate(text) if not char.isspace()]
    compact = "".join(text[i] for i in positions)
    first = compact.find(needle)
    if first < 0 or compact.find(needle, first + 1) >= 0:
        return None
    start, end = positions[first], positions[first + len(needle) - 1] + 1
    return {
        "model_quote": quote,
        "source_quote": text[start:end],
        "start": start,
        "end": end,
        "method": "exact" if quote == text[start:end] else "whitespace_only",
    }


def validation_is_current(run: EvidenceRun) -> bool:
    """Old revisions remain readable, but must not inherit newer validation guarantees."""
    return (
        run.pipeline_version == PIPELINE_VERSION
        and run.extractor_version == EXTRACTOR_VERSION_V2
        and run.lint_version == LINT_VERSION
    )


def duplicate_fact_ids(run: EvidenceRun) -> set[str]:
    """Never let a keyed projection silently choose one of several facts."""
    return {key for key, count in Counter(f.fact_id for f in run.facts).items() if count > 1}


def claim_run_context(run: EvidenceRun) -> dict[str, object]:
    """Always qualify completeness by the actual parsed scope, never the whole corpus."""
    run.verify_identity()
    duplicates = duplicate_fact_ids(run)
    return {
        **run.summary(),
        "origin": "evidence",
        "source_rev": run.document.source_rev,
        "parse_rev": run.document.parse_rev,
        "pipeline_version": run.pipeline_version,
        "extractor_version": run.extractor_version,
        "lint_version": run.lint_version,
        "validation_current": validation_is_current(run),
        "known_at_basis": "document_publication_candidate",
        "point_in_time_verified": False,
        "calculation_ready": (
            sum("calculate" in f.usable_for and f.fact_id not in duplicates for f in run.facts)
            if validation_is_current(run)
            else 0
        ),
        "scope": {
            "locators": [page.locator for page in run.document.pages],
            "completeness_applies_to": "selected_source_scope_only",
        },
        "packet_runs": [packet.model_dump(mode="json") for packet in run.packet_runs],
    }


def project_claims(
    run: EvidenceRun,
    *,
    subject: str | None = None,
    kind: str | None = None,
    quality_status: str | None = "ok",
    purpose: str = "cite",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, object]:
    """One read contract for source, quality, purpose, version and pagination gates."""
    if purpose not in {"audit", "cite", "compare", "calculate"}:
        raise ValueError("invalid claim purpose")
    if quality_status not in {None, "ok", "review", "rejected"}:
        raise ValueError("invalid quality status")
    if kind not in {None, "fact", "forecast", "opinion"}:
        raise ValueError("invalid claim kind")
    if not 1 <= limit <= 1000 or offset < 0:
        raise ValueError("invalid pagination")
    context = claim_run_context(run)
    current = validation_is_current(run)
    duplicates = duplicate_fact_ids(run)
    rows = []
    for fact in run.facts:
        claim = fact.claim
        if subject is not None and claim.subject != subject:
            continue
        if kind is not None and claim.kind != kind:
            continue
        if quality_status is not None and claim.quality_status != quality_status:
            continue
        allowed = [
            p
            for p in fact.usable_for
            if (current and fact.fact_id not in duplicates) or p == "cite"
        ]
        if purpose != "audit" and purpose not in allowed:
            continue
        data = fact.model_dump(mode="json")
        raw_claim = data.pop("claim")
        rows.append(
            {
                **raw_claim,
                **data,
                "run_id": run.run_id,
                "source_rev": run.document.source_rev,
                "parse_rev": run.document.parse_rev,
                "usable_for": allowed,
                "reasons": list(fact.reasons)
                + ([] if current else ["validation_version_stale"])
                + (["duplicate_fact_ids"] if fact.fact_id in duplicates else []),
            }
        )
    unknown = (
        not context["complete"]
        or any(p.status == "not_candidate" for p in run.packet_runs)
        or (purpose in {"compare", "calculate"} and (not current or bool(duplicates)))
    )
    return {
        **context,
        "purpose": purpose,
        "coverage_status": "available" if rows else "unknown" if unknown else "absent",
        "coverage_applies_to": "matching_claims_in_selected_source_scope_only",
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < len(rows),
        "items": rows[offset : offset + limit],
    }


def _fact(
    record: ClaimRecord,
    packet: EvidencePacket,
    document: EvidenceDocument,
) -> EvidenceFact:
    record = replace(record, extracted_at=None)
    time_reasons = []
    model_known_at = record.known_at
    if record.known_at != document.published:
        time_reasons.append("known_at_unverified_override")
        record = replace(record, known_at=document.published)
    alignment = None
    if packet.kind == "prose" and record.evidence_quote:
        alignment = align_quote(record.evidence_quote, packet.text)
        if alignment is not None:
            record = replace(record, evidence_quote=str(alignment["source_quote"]))
            if time_reasons:
                alignment["model_known_at"] = model_known_at
    if record.period_raw and re.sub(r"\s+", "", record.period_raw) not in re.sub(
        r"\s+", "", packet.text
    ):
        record = replace(
            record,
            period_end=None,
            period_grain=None,
            reason_codes=(*record.reason_codes, "period_unanchored", "period_not_in_packet"),
        )
    record = apply_lint(record, block_text=packet.text, table_lookup=packet.lookup)
    metric_name = re.sub(r"[（(](?:百万元|亿元|万元|元)[）)]$", "", record.metric or "")
    spec = METRICS.get(metric_name)
    reasons = [*record.reason_codes, *time_reasons]
    usable: list[str] = []
    if record.quality_status != "rejected":
        usable.append("cite")
    if not spec:
        reasons.append("metric_not_registered")
    elif record.unit != spec[1]:
        reasons.append("metric_unit_mismatch")
    if spec and spec[0] == "net_margin":
        # A source label is not a verified numerator/denominator definition.
        # Keep it citable; only explicitly selected amount facts may form a ratio.
        reasons.append("ratio_definition_unverified")
    if not record.known_at:
        reasons.append("known_at_missing")
    # A document ticker is only a permissible source context, never a free model assertion.
    if record.scope == "company" and record.subject != document.subject:
        reasons.append("subject_not_anchored")
    if record.period_raw and re.sub(r"\s+", "", record.period_raw) not in re.sub(
        r"\s+", "", packet.text
    ):
        reasons.append("period_not_in_packet")
    if not record.subject:
        reasons.append("subject_missing")
    if packet.kind == "prose" and spec and record.kind != "opinion":
        reasons.extend(prose_binding_reasons(record, METRICS))
        quote = record.evidence_quote or ""
        aliases = [name for name, mapping in METRICS.items() if mapping[0] == spec[0]]
        if not any(name in quote for name in aliases):
            reasons.append("metric_not_in_quote")
        # A true number with a fabricated multiplier must not become calculable.
        pairs = re.findall(
            r"([+\-−]?\(?\d[\d,]*(?:\.\d+)?\)?)\s*"
            r"(百万元|亿美元|亿元|万元|万人|元/股|元/吨|美元|元|%|倍|天|人)",
            quote,
        )
        raw_value = parse_value(record.value_text)[0]
        if not any(
            parse_value(number)[0] == raw_value and unit == record.unit_raw
            for number, unit in pairs
        ):
            reasons.append("value_unit_pair_not_in_quote")
    if record.kind != "opinion" and record.value_num is not None and not reasons:
        usable.extend(["compare", "calculate"])
    semantic_reasons = [
        reason
        for reason in reasons
        if reason.startswith(
            (
                "atomic_evidence_",
                "kind_source_",
                "known_at_unverified_",
                "qualifier_definition_",
            )
        )
    ]
    if semantic_reasons and record.quality_status == "ok":
        record = replace(
            record,
            quality_status="review",
            reason_codes=tuple(dict.fromkeys((*record.reason_codes, *semantic_reasons))),
        )
    return EvidenceFact(
        fact_id=fingerprint(
            [
                packet.packet_id,
                record.claim_text,
                record.table_ref,
                record.subject,
                record.metric,
                record.period_raw,
                record.value_text,
                record.kind,
                record.qualifiers,
                record.unit,
                record.known_at,
                record.evidence_quote,
            ]
        ),
        packet_id=packet.packet_id,
        claim=record,
        metric_id=spec[0] if spec else None,
        usable_for=tuple(usable),
        reasons=tuple(dict.fromkeys(reasons)),
        evidence_alignment=alignment,
    )


def _table_records(packet: EvidencePacket, document: EvidenceDocument) -> list[ClaimRecord]:
    payload = []
    for cell in packet.cells:
        customer_column = cell.column.startswith("销售额") or cell.column == "占收入比例"
        years = set(re.findall(r"(?<!\d)20\d{2}(?!\d)", " ".join(packet.context)))
        period = (
            next(iter(years))
            if customer_column and len(years) == 1
            else (None if customer_column else cell.column)
        )
        payload.append(
            {
                "claim_text": f"{cell.row} {cell.column} {cell.value} {cell.unit}",
                "evidence_quote": packet.text,
                "evidence_kind": "table",
                "table_ref": cell.reference(),
                "scope": "company",
                "subject": document.subject,
                "metric": ("客户销售额" if cell.column.startswith("销售额") else "客户收入占比")
                if customer_column
                else cell.row,
                "qualifiers": {"customer": cell.row, "table_basis": "source_customer_sales"}
                if customer_column
                else {},
                "value_text": cell.value,
                "unit_raw": cell.unit,
                "period_raw": period,
                "kind": "forecast" if cell.column.upper().endswith(("E", "F")) else "fact",
            }
        )
    return records_from_payload(
        payload,
        doc_id=document.doc_id,
        source_rev=document.parse_rev,
        seq=_locator_sequence(packet.locator),
        locator=packet.locator,
        doc_kind="company",
        model="deterministic-table",
        known_at_fallback=document.published,
    )


def _locator_sequence(locator: str) -> int:
    """Retain historical numeric locators and deterministically map versioned handles."""
    try:
        return int(locator)
    except ValueError:
        return int(fingerprint(locator)[:8], 16)


def _mark_conflicts(facts: list[EvidenceFact]) -> list[EvidenceFact]:
    # Detect contradictory classifications even when one member already failed validation.
    semantic: dict[tuple[object, ...], list[int]] = defaultdict(list)
    ids = Counter(f.fact_id for f in facts)
    for index, fact in enumerate(facts):
        c = fact.claim
        semantic[
            (fact.packet_id, c.subject, fact.metric_id, c.metric, c.period_raw, c.value_num, c.unit)
        ].append(index)
    for indices in semantic.values():
        if len({facts[i].claim.kind for i in indices}) > 1:
            for index in indices:
                f = facts[index]
                facts[index] = f.model_copy(
                    update={
                        "usable_for": tuple(p for p in f.usable_for if p == "cite"),
                        "reasons": (*f.reasons, "conflicting_fact_kinds"),
                        "claim": replace(f.claim, quality_status="review")
                        if f.claim.quality_status == "ok"
                        else f.claim,
                    }
                )
    for index, fact in enumerate(facts):
        if ids[fact.fact_id] > 1:
            facts[index] = fact.model_copy(
                update={
                    "usable_for": tuple(p for p in fact.usable_for if p == "cite"),
                    "reasons": (*fact.reasons, "duplicate_fact_ids"),
                    "claim": replace(fact.claim, quality_status="review")
                    if fact.claim.quality_status == "ok"
                    else fact.claim,
                }
            )
    groups: dict[tuple[object, ...], list[int]] = defaultdict(list)
    for index, fact in enumerate(facts):
        c = fact.claim
        if "calculate" in fact.usable_for:
            key = (
                c.subject,
                fact.metric_id,
                c.period_end,
                c.period_grain,
                c.kind,
                c.unit,
                tuple(sorted(c.qualifiers.items())),
            )
            groups[key].append(index)
    for indices in groups.values():
        if len({facts[i].claim.value_num for i in indices}) <= 1:
            continue
        for index in indices:
            f = facts[index]
            facts[index] = f.model_copy(
                update={"usable_for": ("cite",), "reasons": (*f.reasons, "conflicting_values")}
            )
    return facts


def extract_evidence(
    document: EvidenceDocument,
    *,
    llm: LlmFn | None = None,
    model: str | None = None,
    max_prose_calls: int = 0,
    on_packet: Callable[[PacketRun], None] | None = None,
) -> EvidenceRun:
    """Extract all table rows; prose budget/unsupported pages are explicitly deferred."""
    facts: list[EvidenceFact] = []
    runs: list[PacketRun] = []
    calls = 0
    for packet in document.packets:
        records: list[ClaimRecord] = []
        reasons: tuple[str, ...] = ()
        diagnostics: dict[str, object] | None = None
        status, method = "completed", "deterministic-table"
        if packet.status != "available":
            status, method, reasons = "unknown", "none", packet.reasons
        elif packet.kind == "table":
            records = _table_records(packet, document)
        elif not triage_block_detail(packet.text).candidate:
            status, method = "not_candidate", "triage"
        elif llm is None or calls >= max_prose_calls:
            status, method, reasons = "deferred", "none", ("prose_not_processed",)
        else:
            calls += 1
            method = "llm"
            try:
                kind = classify_doc_kind_detail(document.title, (packet.text,)).kind
                prompt = build_prompt_v2(packet.text, doc_kind=kind)
                prompt += "\n来源上下文（不可当作正文引文）：" + str(
                    {
                        "title": document.title,
                        "subject": document.subject,
                        "published": document.published,
                        "section": packet.context,
                    }
                )
                raw = llm(prompt)
                diagnostics = dict(raw.diagnostics) if isinstance(raw, LlmResponse) else {}
                parsed = parse_claims_json_detail(raw)
                diagnostics.update(
                    parse_failed=parsed.failed,
                    parse_truncated=parsed.truncated,
                    parsed_items=len(parsed.items),
                    parse_error=parsed.error,
                )
                finish = diagnostics.get("finish_reason")
                if finish == "length" or parsed.truncated:
                    status, reasons = "failed", ("response_incomplete", "output_truncated")
                elif finish not in {None, "stop"}:
                    status, reasons = "failed", ("response_incomplete", "unexpected_finish_reason")
                elif not raw.strip():
                    status, reasons = "failed", ("response_incomplete", "empty_response")
                elif parsed.failed:
                    status, reasons = "failed", ("response_incomplete", "invalid_json")
                else:
                    records = records_from_payload(
                        parsed.items,
                        doc_id=document.doc_id,
                        source_rev=document.parse_rev,
                        seq=len(runs),
                        locator=packet.locator,
                        doc_kind=kind,
                        model=model,
                        known_at_fallback=document.published,
                    )
                    if len(records) != len(parsed.items):
                        diagnostics["discarded_records"] = len(parsed.items) - len(records)
                        status, reasons, records = "failed", ("invalid_record_schema",), []
            except Exception as exc:
                # Credential-bearing provider messages must not be persisted or printed.
                status, reasons = "failed", (f"extraction_error:{type(exc).__name__}",)
                if isinstance(exc, LlmCallError):
                    diagnostics = dict(exc.diagnostics)
                    reasons = (f"extraction_error:{diagnostics['error_type']}",)
        facts.extend(_fact(record, packet, document) for record in records)
        run = PacketRun(
            packet_id=packet.packet_id,
            status=status,
            method=method,
            records=len(records),
            reasons=reasons,
            diagnostics=diagnostics,
        )
        runs.append(run)
        if on_packet:
            on_packet(run)
    result = EvidenceRun(
        run_id="",
        document=document,
        model=model,
        facts=tuple(_mark_conflicts(facts)),
        packet_runs=tuple(runs),
    )
    payload = result.model_dump(mode="json")
    payload.pop("run_id")
    return result.model_copy(update={"run_id": fingerprint(payload)})


def build_evidence_run(
    path: str | Path,
    *,
    pages: tuple[int, ...] | None = None,
    llm: LlmFn | None = None,
    model: str | None = None,
    max_prose_calls: int = 0,
    packet_chars: int = 2000,
) -> EvidenceRun:
    """Small caller interface covering parsing, extraction, verification and projection."""
    return extract_evidence(
        parse_evidence(path, pages=pages, packet_chars=packet_chars),
        llm=llm,
        model=model,
        max_prose_calls=max_prose_calls,
    )


#: units 投影的解析器版本（R1：不再走 evidence.py 的 PDF/DOCX/MD 二次解析）。
UNITS_PROJECTION_VERSION = "evidence-units-projection-1"


def _packet_from_unit(parse_rev: str, locator: str, text: str) -> EvidencePacket:
    """把单个同源 unit 投影为 prose packet（packet_id 由内容寻址决定）。"""
    preliminary = EvidencePacket(
        packet_id="",
        locator=locator,
        kind="prose",
        text=text,
        context=(),
    )
    key = fingerprint([parse_rev, preliminary.model_dump(mode="json")])
    return preliminary.model_copy(update={"packet_id": key})


def build_evidence_run_from_units(
    source_id: str,
    units: list[dict[str, object]],
    *,
    title: str = "",
    subject: str | None = None,
    published: str | None = None,
    llm: LlmFn | None = None,
    model: str | None = None,
    max_prose_calls: int = 0,
) -> EvidenceRun:
    """从同源 units 投影 Evidence（I2-7 canonical units 投影，R1）。

    不二次解析原文件：权威正文来自已入链的 ``corpus_units.raw_text``，按 ordinal
    顺序投影为 prose packets（``parse_evidence`` 的 PDF/DOCX/MD 独立解析不再是
    canonical 入口）。``title``/``subject``/``published`` 由调用方从 source/
    admission 元数据给出（发布日期唯一落点=admission.report_publication，R4），
    不再由解析器从文件名/正文重推。``run_id`` 与 ``parse_rev`` 由投影内容寻址
    决定，绑定 source/build 身份；无 units（来源未入链）返回空 packets 的确定性
    空 run。
    """
    texts = [str(unit["text"]) for unit in units]
    parse_rev = fingerprint([source_id, UNITS_PROJECTION_VERSION, texts])
    packets = tuple(
        _packet_from_unit(parse_rev, str(unit["locator"]), str(unit["text"])) for unit in units
    )
    document = EvidenceDocument(
        doc_id=f"cv2:{source_id}",
        title=title,
        source_path=f"cv2:{source_id}",
        source_rev=source_id,
        parse_rev=parse_rev,
        parser_version=UNITS_PROJECTION_VERSION,
        subject=subject,
        published=published,
        pages=(Span(locator="document", text="\n".join(texts)),) if texts else (),
        packets=packets,
    )
    return extract_evidence(
        document,
        llm=llm,
        model=model,
        max_prose_calls=max_prose_calls,
    )


def _snapshot_document_metadata(snapshot: EvidenceSnapshot) -> dict[str, object]:
    documents = [unit.metadata.get("document") for unit in snapshot.units]
    if not documents or not isinstance(documents[0], dict):
        raise ValueError("snapshot lacks document metadata")
    first = documents[0]
    if any(document != first for document in documents):
        raise ValueError("snapshot document metadata is inconsistent across units")
    return first


def _snapshot_context(unit: SnapshotUnit, snapshot: EvidenceSnapshot) -> tuple[str, ...]:
    from plugins.corpus.structured.snapshot import dependency_closure

    return tuple(item.text for item in dependency_closure(snapshot, unit))


def _snapshot_packet_status(units: list[SnapshotUnit]) -> tuple[str, tuple[str, ...]]:
    statuses = {str(unit.metadata.get("context_status") or "complete") for unit in units}
    if statuses == {"complete"}:
        return "available", ()
    reasons = tuple(sorted(f"context_{status}" for status in statuses if status != "complete"))
    return "partial", reasons or ("context_partial",)


def _snapshot_label_span(
    snapshot: EvidenceSnapshot, unit: SnapshotUnit, raw: dict[str, object], name: str
) -> Span:
    from plugins.corpus.structured.snapshot import source_unit_id

    text = str(raw.get(name) or "")
    reference = raw.get(f"{name}_ref")
    if isinstance(reference, dict):
        chunk = str(reference["target_chunk_id"]).removeprefix("chunk:")
        for target in snapshot.units:
            if (
                target.chunk_id == f"chunk:{chunk}"
                and source_unit_id(target) == reference["target_unit_id"]
            ):
                return Span(
                    locator=target.unit_id,
                    text=text,
                    start=reference["start"],
                    end=reference["end"],
                )
    # Unproven labels are retained for audit only; the packet is partial.
    return Span(locator=unit.unit_id, text=text)


def _snapshot_cells(units: list[SnapshotUnit], snapshot: EvidenceSnapshot) -> tuple[Cell, ...]:
    cells: list[Cell] = []
    for unit in units:
        raw_cells = unit.metadata.get("cells")
        if not isinstance(raw_cells, list):
            continue
        for raw in raw_cells:
            if not isinstance(raw, dict):
                continue
            value = str(raw.get("value") or "")
            start = raw.get("start")
            end = raw.get("end")
            if not isinstance(start, int) or not isinstance(end, int):
                raise ValueError(f"snapshot cell lacks code-point interval: {unit.unit_id}")
            value_span = Span(
                locator=unit.unit_id,
                text=value,
                start=start,
                end=end,
            )
            cells.append(
                Cell(
                    table_id=unit.chunk_id,
                    row=str(raw.get("row") or ""),
                    column=str(raw.get("column") or ""),
                    value=value,
                    unit=str(raw.get("unit") or ""),
                    span=value_span,
                    row_span=_snapshot_label_span(snapshot, unit, raw, "row"),
                    column_span=_snapshot_label_span(snapshot, unit, raw, "column"),
                    unit_span=_snapshot_label_span(snapshot, unit, raw, "unit")
                    if raw.get("unit")
                    else None,
                )
            )
    return tuple(cells)


def evidence_document_from_snapshot(
    snapshot: EvidenceSnapshot,
    *,
    role: Literal["claims", "material_items"],
) -> EvidenceDocument:
    """Project one immutable snapshot into the existing business document schema."""
    from plugins.corpus.structured.snapshot import dependency_closure, select_snapshot

    snapshot.verify_identity()
    selection = select_snapshot(snapshot, role)
    selected_ids = {unit.unit_id for unit in selection.units}
    packets: list[EvidencePacket] = []
    table_chunks = tuple(
        dict.fromkeys(unit.chunk_id for unit in selection.units if unit.kind == "table")
    )
    for chunk_id in table_chunks:
        table_units = [
            unit for unit in selection.units if unit.chunk_id == chunk_id and unit.kind == "table"
        ]
        included = {unit.unit_id for unit in table_units}
        for unit in table_units:
            included.update(item.unit_id for item in dependency_closure(snapshot, unit))
        evidence_units = [unit for unit in snapshot.units if unit.unit_id in included]
        parts: list[str] = []
        spans: list[Span] = []
        cursor = 0
        for index, unit in enumerate(evidence_units):
            if index:
                cursor += 1
            parts.append(unit.text)
            spans.append(
                Span(
                    locator=unit.unit_id,
                    text=unit.text,
                    start=cursor,
                    end=cursor + len(unit.text),
                )
            )
            cursor += len(unit.text)
        text = "\n".join(parts)
        context = tuple(
            dict.fromkeys(
                dependency_text
                for unit in table_units
                for dependency_text in _snapshot_context(unit, snapshot)
            )
        )
        status, reasons = _snapshot_packet_status(table_units)
        packet = EvidencePacket(
            packet_id="",
            locator=chunk_id,
            kind="table",
            text=text,
            spans=tuple(spans),
            cells=_snapshot_cells(table_units, snapshot),
            context=context,
            status=status,
            reasons=reasons,
        )
        packet_id = fingerprint([snapshot.snapshot_id, role, packet.model_dump(mode="json")])
        packets.append(packet.model_copy(update={"packet_id": packet_id}))

    prose_kinds = (
        {"prose", "image_text"}
        if role == "claims"
        else {"prose", "image_text", "table_note", "heading"}
    )
    for unit in selection.units:
        if unit.unit_id not in selected_ids or unit.kind not in prose_kinds:
            continue
        context = _snapshot_context(unit, snapshot)
        status, reasons = _snapshot_packet_status([unit])
        packet = EvidencePacket(
            packet_id="",
            locator=unit.chunk_id,
            kind="prose",
            text=unit.text,
            spans=(
                Span(
                    locator=unit.unit_id,
                    text=unit.text,
                    start=0,
                    end=len(unit.text),
                ),
            ),
            context=context,
            status=status,
            reasons=reasons,
        )
        packet_id = fingerprint(
            [snapshot.snapshot_id, role, unit.unit_id, packet.model_dump(mode="json")]
        )
        packets.append(packet.model_copy(update={"packet_id": packet_id}))

    # Preserve source order for the R2 previous/following context windows.
    order = {unit.unit_id: index for index, unit in enumerate(snapshot.units)}
    chunks = {unit.unit_id: unit.chunk_id for unit in snapshot.units}
    packets.sort(
        key=lambda packet: min(
            order[span.locator] for span in packet.spans if chunks[span.locator] == packet.locator
        )
    )
    document = _snapshot_document_metadata(snapshot)
    pages = tuple(
        Span(
            locator=unit.unit_id,
            text=unit.text,
            start=0,
            end=len(unit.text),
        )
        for unit in snapshot.units
    )
    return EvidenceDocument(
        doc_id=f"cv2:{snapshot.build_id}",
        title=str(document.get("title") or ""),
        source_path=f"cv2:{snapshot.build_id}",
        source_rev=snapshot.snapshot_id,
        parse_rev=snapshot.snapshot_id,
        parser_version=snapshot.parser_versions["snapshot"],
        subject=str(document["subject"]) if document.get("subject") is not None else None,
        published=str(document["published"]) if document.get("published") is not None else None,
        pages=pages,
        packets=tuple(packets),
    )


def _bind_snapshot_facts(snapshot: EvidenceSnapshot, run: EvidenceRun) -> EvidenceRun:
    """Keep exact evidence and source qualifications through the existing Claims payload."""
    from plugins.corpus.structured.mapping import resolve_packet_span, resolve_unit_span
    from plugins.corpus.structured.snapshot import dependency_closure

    by_id = {unit.unit_id: unit for unit in snapshot.units}
    facts = []
    for fact in run.facts:
        packet = run.document.fetch(fact.packet_id)
        source_units = [by_id[span.locator] for span in packet.spans]
        dependency_ids = {
            dependency.unit_id
            for unit in source_units
            for dependency in dependency_closure(snapshot, unit)
        }
        dependencies = [unit for unit in snapshot.units if unit.unit_id in dependency_ids]
        context_units = {unit.unit_id: unit for unit in (*source_units, *dependencies)}
        details = [
            detail
            for unit in context_units.values()
            for detail in cast(list[dict[str, object]], unit.metadata["dependency_details"])
        ]
        qualifications = sorted(
            {
                str(detail["kind"])
                for detail in details
                if detail["kind"] in {"condition", "negation", "attribution"}
            }
        )
        reasons = list(fact.reasons)
        reasons.extend(f"source_{kind}_dependency" for kind in qualifications)
        alignment = align_quote(fact.claim.evidence_quote or "", packet.text)
        if alignment is None:
            reasons.append("source_evidence_mapping_missing")
            source_spans = []
        else:
            source_spans = [
                asdict(ref)
                for ref in resolve_packet_span(
                    snapshot,
                    packet,
                    int(str(alignment["start"])),
                    int(str(alignment["end"])),
                )
            ]
        dependency_spans = [
            asdict(resolve_unit_span(snapshot, unit.unit_id, 0, len(unit.text)))
            for unit in dependencies
        ]
        usable = fact.usable_for
        if qualifications:
            usable = tuple(purpose for purpose in usable if purpose == "cite")
        if not source_spans:
            usable = ()
        facts.append(
            fact.model_copy(
                update={
                    "usable_for": usable,
                    "reasons": tuple(dict.fromkeys(reasons)),
                    "evidence_alignment": {
                        **(fact.evidence_alignment or {}),
                        "source_spans": source_spans,
                        "dependency_spans": dependency_spans,
                        "dependency_details": details,
                    },
                }
            )
        )
    result = run.model_copy(update={"facts": tuple(facts)})
    payload = result.model_dump(mode="json")
    payload.pop("run_id")
    return result.model_copy(update={"run_id": fingerprint(payload)})


def build_evidence_run_from_snapshot(
    snapshot: EvidenceSnapshot,
    *,
    role: Literal["claims", "material_items"] = "claims",
    llm: LlmFn | None = None,
    model: str | None = None,
    max_prose_calls: int = 0,
) -> EvidenceRun:
    """Run existing Claims extraction against one frozen source/build snapshot."""
    document = evidence_document_from_snapshot(snapshot, role=role)
    if role == "material_items":
        # EvidenceRun remains the historical document envelope, not a Claims prerequisite.
        result = EvidenceRun(run_id="", document=document, facts=(), packet_runs=())
        payload = result.model_dump(mode="json")
        payload.pop("run_id")
        return result.model_copy(update={"run_id": fingerprint(payload)})
    return _bind_snapshot_facts(
        snapshot,
        extract_evidence(
            document,
            llm=llm,
            model=model,
            max_prose_calls=max_prose_calls,
        ),
    )
