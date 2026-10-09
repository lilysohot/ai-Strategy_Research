"""Claims slot coverage and deterministic coordinate binding."""

from __future__ import annotations

import json
from dataclasses import replace

from plugins.corpus.claims_binding import (
    bind_claim_coordinates,
    build_claim_candidate_slots,
    validate_slot_outcomes,
)
from plugins.corpus.claims_detail import ClaimRecord
from plugins.corpus.evidence import EvidenceDocument, EvidencePacket, Span
from plugins.corpus.evidence_pipeline import extract_evidence


def _document(text: str) -> EvidenceDocument:
    packet = EvidencePacket(
        packet_id="packet-1",
        locator="body[1]",
        kind="prose",
        text=text,
    )
    return EvidenceDocument(
        doc_id="doc-1",
        title="光模块行业交流",
        source_path="memory",
        source_rev="source-1",
        parse_rev="parse-1",
        parser_version="test",
        subject="光模块行业",
        published="2026-09-08",
        pages=(Span(locator="body[1]", text=text),),
        packets=(packet,),
    )


def test_claim_candidate_slots_include_omitted_range_sentence() -> None:
    document = _document("CPO市场成熟度不高，预计26年很少，27年5万到10万个水平，这是合理的。")
    slots = build_claim_candidate_slots(document)
    assert slots
    assert any("5万到10万个" in slot.text for slot in slots)


def test_slot_outcomes_fail_closed_on_missing_terminal() -> None:
    document = _document("27年CPO出货量预计为5万到10万个。")
    slots = build_claim_candidate_slots(document)
    claims, ledger, errors = validate_slot_outcomes([], slots)
    assert claims == []
    assert any(entry["status"] == "missing" for entry in ledger)
    assert "claim_slot_terminal_missing" in errors


def test_slot_outcomes_accept_claim_bound_to_exact_slot() -> None:
    document = _document("27年CPO出货量预计为5万到10万个。")
    slot = build_claim_candidate_slots(document)[0]
    payload = [
        {
            "candidate_slot_id": slot.candidate_slot_id,
            "coverage_status": "claim",
            "claim_text": "27年CPO出货量预计为5万到10万个",
            "evidence_quote": "27年CPO出货量预计为5万到10万个",
        }
    ]
    claims, ledger, errors = validate_slot_outcomes(payload, (slot,))
    assert claims == payload
    assert ledger == [{"candidate_slot_id": slot.candidate_slot_id, "status": "extracted"}]
    assert errors == ()


def test_slot_outcomes_rebind_missing_id_only_when_quote_is_unique() -> None:
    document = _document("27年CPO出货量预计为5万到10万个。")
    slot = build_claim_candidate_slots(document)[0]
    payload = [
        {
            "claim_text": "27年CPO出货量预计为5万到10万个",
            "evidence_quote": "CPO出货量预计为5万到10万个",
        }
    ]
    claims, ledger, errors = validate_slot_outcomes(payload, (slot,))
    assert claims == payload
    assert ledger[0]["status"] == "extracted"
    assert errors == ()


def test_no_claim_terminal_requires_auditable_reason() -> None:
    document = _document("27年CPO出货量预计为5万到10万个。")
    slot = build_claim_candidate_slots(document)[0]
    _claims, _ledger, errors = validate_slot_outcomes(
        [{"candidate_slot_id": slot.candidate_slot_id, "coverage_status": "no_supported_claim"}],
        (slot,),
    )
    assert "claim_slot_reason_missing" in errors


def test_binding_promotes_industry_subsubject_and_resolves_short_year() -> None:
    document = _document("29年NPO到10%。")
    record = ClaimRecord(
        doc_id="doc-1",
        source_rev="source-1",
        seq=1,
        locator="body[1]",
        claim_text="29年NPO到10%",
        evidence_quote="29年NPO到10%",
        scope="industry",
        subject_raw="NPO",
        subject="NPO",
        metric=None,
        value_text="10%",
        period_raw="29年",
        reason_codes=("period_ambiguous",),
    )
    bound = bind_claim_coordinates(record, packet=document.packets[0], document=document)
    assert bound.subject == "光模块行业"
    assert bound.metric == "NPO"
    assert bound.period_end == "2029-12-31"
    assert bound.qualifiers["metric_basis"] == "promoted_model_subsubject"
    assert "period_ambiguous" not in bound.reason_codes


def test_binding_completes_range_unit_from_exact_quote() -> None:
    document = _document("今年下半年预计将有2到3个新客户开始贡献收入。")
    packet = document.packets[0]
    record = ClaimRecord(
        doc_id=document.doc_id,
        source_rev=document.parse_rev,
        seq=1,
        locator=packet.locator,
        claim_text="预计2到3个新客户贡献收入",
        evidence_quote=packet.text,
        scope="macro",
        subject="光模块行业",
        metric="新客户贡献收入",
        value_text="2到3",
        qualifiers={"value_shape": "range", "value_lower": "2", "value_upper": "3"},
        period_raw="今年下半年",
    )
    bound = bind_claim_coordinates(record, packet=packet, document=document)
    assert bound.unit == "个"
    assert bound.subject == "材料所述公司"
    assert bound.scope == "company"


def test_binding_resolves_approximate_quarter_and_categorical_status() -> None:
    document = _document("我们3.2T预计将在27年三季度左右实现批量供应。")
    packet = document.packets[0]
    record = ClaimRecord(
        doc_id=document.doc_id,
        source_rev=document.parse_rev,
        seq=1,
        locator=packet.locator,
        claim_text=packet.text,
        evidence_quote=packet.text,
        scope="company",
        metric="批量供应",
        period_raw="27年三季度左右",
        reason_codes=("period_ambiguous",),
    )
    bound = bind_claim_coordinates(record, packet=packet, document=document)
    assert bound.period_end == "2027-09-30"
    assert bound.value_text == "batch_supply"
    assert bound.unit == "status"
    assert bound.subject == "材料所述公司"


def test_binding_restores_shared_range_multiplier_and_product_subject() -> None:
    document = _document("到28年预计增长至300至500万只，这个就是金像电的2.4T产品。")
    packet = document.packets[0]
    record = ClaimRecord(
        doc_id=document.doc_id,
        source_rev=document.parse_rev,
        seq=1,
        locator=packet.locator,
        claim_text="金像电2.4T产品出货量增长至300至500万只",
        evidence_quote=packet.text,
        scope="company",
        subject="光模块行业",
        metric="出货量",
        value_text="300至500",
        unit_raw="只",
        unit="只",
        qualifiers={"value_shape": "range", "value_lower": "300", "value_upper": "500"},
        period_raw="28年",
    )
    bound = bind_claim_coordinates(record, packet=packet, document=document)
    assert bound.qualifiers["value_lower"] == "3000000"
    assert bound.qualifiers["value_upper"] == "5000000"
    assert bound.subject == "2.4T产品（厂商口径不明）"


def test_early_stage_qualifier_does_not_leak_across_sentence_boundary() -> None:
    document = _document(
        "预计到28年整个行业出货量达到500万只。价格预计1800美元，这是比较早期的预计。"
    )
    packet = document.packets[0]
    volume = ClaimRecord(
        doc_id=document.doc_id,
        source_rev=document.parse_rev,
        seq=1,
        locator=packet.locator,
        claim_text="整个行业出货量达到500万只",
        evidence_quote="预计到28年整个行业出货量达到500万只",
        scope="industry",
        subject="整个行业",
        metric="出货量",
        value_text="500万只",
        unit_raw="万只",
        unit="只",
        period_raw="28年",
    )
    price = replace(
        volume,
        claim_text="价格预计1800美元",
        evidence_quote="价格预计1800美元",
        subject="光模块行业",
        metric="单价",
        value_text="1800美元",
        unit_raw="美元",
        unit="美元",
        period_raw=None,
    )
    bound_volume = bind_claim_coordinates(volume, packet=packet, document=document)
    bound_price = bind_claim_coordinates(price, packet=packet, document=document)
    assert bound_volume.subject == "光模块行业"
    assert "estimate_stage" not in bound_volume.qualifiers
    assert bound_price.qualifiers["estimate_stage"] == "early_stage"


def test_strict_claims_run_is_partial_when_model_omits_slot_terminal() -> None:
    document = _document("27年CPO出货量预计为5万到10万个。")
    run = extract_evidence(
        document,
        llm=lambda _prompt: json.dumps([]),
        max_prose_calls=1,
        strict_prose=True,
        claim_slot_coverage=True,
    )
    assert run.packet_runs[0].status == "partial"
    assert "claim_slot_terminal_missing" in run.packet_runs[0].reasons
    assert run.summary()["complete"] is False
    assert run.summary()["coverage_verified"] is False
