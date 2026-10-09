"""Deterministic Claims obligations and coordinate binding.

The model proposes semantic coordinates; this module owns two invariants the
model must not self-certify:

* every atomic candidate span receives an explicit terminal outcome; and
* relative time and omitted document subjects are bound only from trusted
  source metadata.

Keeping these rules outside the prompt makes completeness observable and keeps
the same frozen source spans reusable across model versions.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from plugins.corpus.claims import parse_value_range
from plugins.corpus.claims_detail import ClaimRecord, normalize_period_in_context
from plugins.corpus.evidence import EvidenceDocument, EvidencePacket
from plugins.corpus.material_semantics import (
    CandidateSlot,
    build_candidate_slots,
    build_material_structure,
)

CLAIMS_SLOT_PROTOCOL_VERSION = "claims-slot-obligations-v2"
_RESOLVED_PERIOD_REASONS = {"period_ambiguous", "period_unanchored", "period_missing"}
_EVIDENCE_RANGE_RE = re.compile(
    r"(?<!\d)([+-]?\d[\d,]*(?:\.\d+)?\s*[万亿]?\s*"
    r"(?:-|~|～|—|–|至|到)\s*[+-]?\d[\d,]*(?:\.\d+)?\s*[万亿]?"
    r"(?:个|只|台|人|天|吨|股|元|美元|%|％|百分点|倍)?)(?!\d)"
)
_CATEGORICAL_STATUS = {
    "批量供应": "batch_supply",
    "批量出货": "batch_shipments",
    "实现量产": "mass_production",
    "开始量产": "mass_production",
}
_PRODUCT_TOKEN_RE = re.compile(r"(\d+(?:\.\d+)?T)(?:产品)?", re.I)
_COMPANY_COORDINATE_RE = re.compile(r"(?:客户.*收入|市占率|公司|我们的|我们\s*\d)")


def build_claim_candidate_slots(document: EvidenceDocument) -> tuple[CandidateSlot, ...]:
    """Return atomic obligations for packets admitted to the Claims prose role."""
    structure = build_material_structure(document)
    return tuple(
        slot
        for slot in build_candidate_slots(document, structure)
        if slot.text.strip() and any(char.isdigit() for char in slot.text)
    )


def slot_prompt_payload(slots: tuple[CandidateSlot, ...]) -> list[dict[str, object]]:
    """Serialize only the bounded, source-reproducible fields the model needs."""
    return [
        {
            "candidate_slot_id": slot.candidate_slot_id,
            "start": slot.start,
            "end": slot.end,
            "text": slot.text,
        }
        for slot in slots
    ]


def bind_claim_coordinates(
    record: ClaimRecord,
    *,
    packet: EvidencePacket,
    document: EvidenceDocument,
) -> ClaimRecord:
    """Bind omitted coordinates without replacing explicit conflicting values."""
    qualifiers = dict(record.qualifiers)
    updates: dict[str, Any] = {}
    quote = record.evidence_quote or ""

    if record.period_raw:
        period = normalize_period_in_context(
            record.period_raw,
            reference_date=document.published,
        )
        if period.period_end is not None and record.period_end is None:
            updates.update(period_end=period.period_end, period_grain=period.period_grain)
            qualifiers["period_basis"] = "document_publication_year"
            updates["reason_codes"] = tuple(
                code for code in record.reason_codes if code not in _RESOLVED_PERIOD_REASONS
            )
            if re.search(r"(?:左右|前后|附近|约)", record.period_raw):
                qualifiers["period_qualifier"] = "approximately"

    if qualifiers.get("value_shape") == "range":
        # Models sometimes return bare bounds while the exact evidence owns the
        # shared Chinese multiplier or count unit. Rebind only one exact range.
        current_bounds = (
            str(qualifiers.get("value_lower") or ""),
            str(qualifiers.get("value_upper") or ""),
        )
        candidates = []
        for match in _EVIDENCE_RANGE_RE.finditer(quote):
            parsed = parse_value_range(match.group(1))
            if parsed is not None:
                candidates.append(parsed)
        if len(candidates) == 1:
            lower, upper, unit = candidates[0]
            unscaled = parse_value_range(record.value_text, record.unit_raw)
            current_is_unscaled_match = unscaled is not None and (
                format(unscaled[0], "f"), format(unscaled[1], "f")
            ) == current_bounds
            if current_is_unscaled_match or current_bounds != (
                format(lower, "f"),
                format(upper, "f"),
            ):
                qualifiers.update(
                    value_lower=format(lower, "f"),
                    value_upper=format(upper, "f"),
                    value_basis="exact_evidence_range",
                )
                if unit and not record.unit:
                    updates.update(unit_raw=unit, unit=unit)

    if not record.value_text and not record.unit:
        statuses = [
            (phrase, value)
            for phrase, value in _CATEGORICAL_STATUS.items()
            if phrase in quote and (not record.metric or phrase in record.metric or record.metric in phrase)
        ]
        if len(statuses) == 1:
            phrase, value = statuses[0]
            updates.update(value_text=value, unit_raw="status", unit="status")
            qualifiers.update(value_basis=f"categorical_status:{phrase}")

    industry_subject = bool(document.subject and "行业" in document.subject)
    if industry_subject and record.scope == "company":
        if "我们" in quote:
            updates.update(subject_raw="材料所述公司", subject="材料所述公司")
            qualifiers["subject_basis"] = "source_first_person_unnamed_company"
    elif industry_subject and _COMPANY_COORDINATE_RE.search(quote):
        updates.update(scope="company", subject_raw="材料所述公司", subject="材料所述公司")
        qualifiers["subject_basis"] = "implicit_company_coordinate"

    if (
        industry_subject
        and record.scope in {"industry", "macro"}
        and record.subject
        and record.subject != document.subject
        and (record.metric or "") in {"量", "占比", "渗透率"}
    ):
        metric = f"{record.subject}{'出货量' if record.metric == '量' else record.metric}"
        updates.update(subject_raw=document.subject, subject=document.subject, metric_raw=metric, metric=metric)
        qualifiers["subject_basis"] = "document_industry_for_product_metric"

    if industry_subject and record.subject in {"行业", "整个行业", "全行业"}:
        updates.update(subject_raw=document.subject, subject=document.subject)
        qualifiers["subject_basis"] = "document_industry_for_generic_industry_subject"

    if industry_subject and (record.metric or "") in {"出货量", "销量"} and "我们" not in quote:
        products = _PRODUCT_TOKEN_RE.findall(f"{record.claim_text} {quote}")
        products = list(dict.fromkeys(product.upper() for product in products))
        if len(products) == 1:
            subject = f"{products[0]}产品（厂商口径不明）"
            updates.update(subject_raw=subject, subject=subject)
            qualifiers["subject_basis"] = "product_coordinate_in_claim"

    context_window = quote
    if quote and quote in packet.text:
        quote_start = packet.text.index(quote)
        quote_end = quote_start + len(quote)
        prior_boundaries = [packet.text.rfind(mark, 0, quote_start) for mark in "。！？"]
        next_boundaries = [packet.text.find(mark, quote_end) for mark in "。！？"]
        start = max(prior_boundaries) + 1
        ends = [boundary for boundary in next_boundaries if boundary >= 0]
        end = min(ends) + 1 if ends else len(packet.text)
        context_window = packet.text[start:end]
    if re.search(
        r"(?:比较早期|早期).{0,12}(?:预计|预测)|(?:预计|预测).{0,20}(?:比较早期|早期)",
        context_window,
    ):
        qualifiers["estimate_stage"] = "early_stage"
        qualifiers["estimate_stage_basis"] = "adjacent_source_context"
    if re.search(r"(?:左右|大约|约)", quote):
        qualifiers.setdefault("value_qualifier", "approximately")

    if (
        record.scope != "company"
        and not record.metric
        and record.subject
        and document.subject
        and record.subject != document.subject
    ):
        # In industry/macro prose, models often put the measured product in the
        # subject slot and leave metric empty.  Only repair that observable shape;
        # never overwrite an explicit metric or a matching document subject.
        updates.update(
            subject_raw=document.subject,
            subject=document.subject,
            metric_raw=record.subject_raw or record.subject,
            metric=record.subject,
        )
        qualifiers.update(
            subject_basis="document_metadata",
            metric_basis="promoted_model_subsubject",
        )

    if qualifiers != record.qualifiers:
        updates["qualifiers"] = qualifiers
    return replace(record, **updates) if updates else record


def validate_slot_outcomes(
    payload: list[dict[str, Any]],
    slots: tuple[CandidateSlot, ...],
) -> tuple[list[dict[str, Any]], list[dict[str, object]], tuple[str, ...]]:
    """Separate Claim rows from coverage markers and verify every slot terminal."""
    if not slots:
        return payload, [], ()
    by_id = {slot.candidate_slot_id: slot for slot in slots}
    outcomes: dict[str, list[str]] = {slot_id: [] for slot_id in by_id}
    claims: list[dict[str, Any]] = []
    errors: list[str] = []

    for item in payload:
        slot_id = str(item.get("candidate_slot_id") or "")
        slot = by_id.get(slot_id)
        quote = str(item.get("evidence_quote") or item.get("evidence") or "")
        if slot is None and not slot_id and quote:
            compact_quote = re.sub(r"\s+", "", quote)
            matches = [
                candidate
                for candidate in slots
                if compact_quote in re.sub(r"\s+", "", candidate.text)
            ]
            if len(matches) == 1:
                slot = matches[0]
                slot_id = slot.candidate_slot_id
        if slot is None:
            errors.append("claim_slot_unknown_or_missing")
            continue
        status = str(item.get("coverage_status") or "claim")
        if status == "no_supported_claim":
            if not str(item.get("reason_code") or "").strip():
                errors.append("claim_slot_reason_missing")
            outcomes[slot_id].append(status)
            continue
        if status != "claim":
            errors.append("claim_slot_status_invalid")
            continue
        if not quote or re.sub(r"\s+", "", quote) not in re.sub(r"\s+", "", slot.text):
            errors.append("claim_quote_outside_slot")
            continue
        outcomes[slot_id].append("claim")
        claims.append(item)

    ledger: list[dict[str, object]] = []
    for slot_id in by_id:
        statuses = outcomes[slot_id]
        if not statuses:
            status = "missing"
            errors.append("claim_slot_terminal_missing")
        elif "no_supported_claim" in statuses and len(statuses) > 1:
            status = "conflicting"
            errors.append("claim_slot_terminal_conflicting")
        else:
            status = "extracted" if "claim" in statuses else "no_supported_claim"
        ledger.append({"candidate_slot_id": slot_id, "status": status})
    return claims, ledger, tuple(dict.fromkeys(errors))
