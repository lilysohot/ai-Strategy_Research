"""native1 → document1 后台映射表：权威坐标、不猜、范围完整性折算。

映射只来自检索后端取证时生成的 ``native_slices``（unit_id + 权威原文
``[start, end)`` + raw_sha256）；缺表时检索范围必须如实留在 ``unmapped``，
绝不按 chunk 序号或名称相似度补造。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from frontier_agent.core.loop_types import ToolResult, TurnContext
from plugins.corpus.coverage import (
    MAPPING_CONTRACT,
    NATIVE_PREFIX,
    Delivery,
    UnitRange,
    build_native_mapping,
    map_native_to_document,
    mapping_from_dict,
    mappings_from_dict,
    mappings_from_fetch,
    merge_native_mappings,
    native_to_units,
    native_unit_intervals,
)
from plugins.corpus.ledger import DELIVERED, ConsumptionLedger, ConsumptionLedgerObserver
from plugins.corpus.preparation.document_read import unit_locator

DOC = "cv2:" + "c" * 64
BUILD = DOC[4:]
UID = "unit:0001"
UNIT_LOC = unit_locator(UID)
NATIVE = NATIVE_PREFIX + "c5370b93f2af2f91%3Abody%3A0001/52d83c3455210e13"
TEXT = "ABCDEF"
SHA = "a" * 64


def _slice(*, unit_id: str = UID, start: int = 0, end: int = 6, **extra: Any):
    return {"unit_id": unit_id, "start": start, "end": end, "raw_sha256": SHA, **extra}


def _fetch_payload(*, text: str = TEXT, end: int | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "locator": UNIT_LOC,
        "unit_id": UID,
        "text": text,
        "evidence_ref": "ce:receipt",
    }
    if end is not None:
        item["fragment"] = {"start": 0, "end": end}
    return {
        "ok": True,
        "scope": "document",
        "doc_id": DOC,
        "build_id": BUILD,
        "items": [item],
        "item_errors": [],
        "unresolved": [],
        "next_cursor": None,
        "exhausted": True,
        "fetch_complete": True,
    }


def _mapping(**kw: Any):
    return build_native_mapping(locator=NATIVE, doc_id=DOC, build_id=BUILD, rows=[_slice(**kw)])


# ── 契约 ───────────────────────────────────────────────────────────────


def test_build_mapping_accepts_authoritative_slices() -> None:
    mapping = _mapping()
    assert mapping is not None
    assert mapping.locator == NATIVE and mapping.doc_id == DOC
    assert mapping.slices[0].unit_id == UID
    assert (mapping.slices[0].start, mapping.slices[0].end) == (0, 6)


@pytest.mark.parametrize(
    "bad",
    [
        {"unit_id": "", "start": 0, "end": 6},
        {"unit_id": UID, "start": -1, "end": 6},
        {"unit_id": UID, "start": 6, "end": 6},
        {"unit_id": UID, "start": 0, "end": 7, "raw_sha256": "not-a-digest"},
        {"start": 0, "end": 6},
        "not-a-row",
    ],
)
def test_build_mapping_rejects_any_invalid_row(bad: Any) -> None:
    """任一非法行整条拒绝，绝不留下"部分映射"冒充完整。"""
    assert (
        build_native_mapping(locator=NATIVE, doc_id=DOC, build_id=BUILD, rows=[_slice(), bad])
        is None
    )


def test_build_mapping_rejects_non_native_locators() -> None:
    assert (
        build_native_mapping(locator=UNIT_LOC, doc_id=DOC, build_id=BUILD, rows=[_slice()]) is None
    )


def test_mappings_from_fetch_single_and_envelope() -> None:
    single = {
        "ok": True,
        "doc_id": DOC,
        "build_id": BUILD,
        "locator": NATIVE,
        "native_slices": [_slice(text_start=0, text_end=6)],
    }
    envelope = {
        "ok": True,
        "doc_id": DOC,
        "build_id": BUILD,
        "items": [
            {"locator": NATIVE, "native_slices": [_slice()]},
            {"locator": UNIT_LOC, "text": TEXT, "native_slices": [_slice()]},
        ],
    }
    assert [row.locator for row in mappings_from_fetch(single)] == [NATIVE]
    assert [row.locator for row in mappings_from_fetch(envelope)] == [NATIVE]
    assert mappings_from_fetch({"ok": False}) == []


def test_round_trip_contract_and_merge() -> None:
    mapping = _mapping()
    assert mapping is not None
    row = mapping.to_dict()
    assert row["contract"] == MAPPING_CONTRACT
    assert mapping_from_dict(row) == mapping
    assert mapping_from_dict({**row, "contract": "other"}) is None
    merged = merge_native_mappings([mapping, mapping])
    assert len(merged) == 1 and len(merged[0].slices) == 1
    assert mappings_from_dict([row, "junk"]) == merged


def test_native_to_units_feeds_the_coverage_lookup() -> None:
    mapping = _mapping()
    assert mapping is not None
    known = {UID: UnitRange(UNIT_LOC, UID, len(TEXT))}
    out = map_native_to_document(
        [NATIVE, "chunk:native1/unknown"],
        native_to_units=native_to_units([mapping]),
        known_units=known,
    )
    assert out["mapped"] == {NATIVE: [UNIT_LOC]}
    assert out["unmapped"] == ["chunk:native1/unknown"]
    assert out["mapped_count"] == 1 and out["unmapped_count"] == 1
    assert native_unit_intervals([mapping])[NATIVE] == mapping.slices


# ── 账本：范围完整性折算 ───────────────────────────────────────────────


def _ledger_with_offer() -> ConsumptionLedger:
    ledger = ConsumptionLedger()
    ledger.offered.append({"scope_id": "scope:1", "doc_id": DOC, "locators": [NATIVE]})
    return ledger


def _mark_delivered(ledger: ConsumptionLedger) -> None:
    for ref in ledger.fetched:
        ledger.delivered[ref.identity] = DELIVERED


def test_range_completeness_uses_mapping_instead_of_string_matching() -> None:
    ledger = _ledger_with_offer()
    ledger.record_fetch_result(json.dumps(_fetch_payload(), ensure_ascii=False))
    _mark_delivered(ledger)
    assert ledger.range_completeness()[0]["fetched"] == 0  # 两套 locator 不归一

    mapping = _mapping()
    assert mapping is not None
    ledger.record_native_mappings([mapping])
    row = ledger.range_completeness()[0]
    assert row["fetched"] == 1 and row["delivered"] == 1
    assert row["unmapped"] == [] and row["complete"] is True
    assert ledger.all_offered_fetched() is True
    assert ledger.to_dict()["native_mappings"] == [mapping.to_dict()]


def test_missing_mapping_is_visible_as_unmapped() -> None:
    ledger = _ledger_with_offer()
    ledger.record_fetch_result(json.dumps(_fetch_payload(), ensure_ascii=False))
    row = ledger.range_completeness()[0]
    assert row["fetched"] == 0
    assert row["unmapped"] == [NATIVE]
    assert row["complete"] is False


def test_partial_unit_delivery_is_still_incomplete() -> None:
    ledger = _ledger_with_offer()
    ledger.record_native_mappings([_mapping()])
    ledger.record_fetch_result(json.dumps(_fetch_payload(text="ABC", end=3), ensure_ascii=False))
    row = ledger.range_completeness()[0]
    assert row["fetched"] == 0 and row["missing"] == [NATIVE]
    assert row["unmapped"] == []  # 有表，只是没送全


def test_mapped_unit_not_fetched_at_all_is_incomplete() -> None:
    ledger = _ledger_with_offer()
    mapping = _mapping()
    assert mapping is not None
    ledger.record_native_mappings([mapping])
    assert ledger.range_completeness()[0]["fetched"] == 0


async def test_observer_records_mapping_from_the_raw_fetch_result() -> None:
    payload = {
        "ok": True,
        "doc_id": DOC,
        "build_id": BUILD,
        "locator": NATIVE,
        "text": TEXT,
        "native_slices": [_slice()],
    }
    ledger = ConsumptionLedger()
    observer = ConsumptionLedgerObserver(ledger=ledger)
    ctx = TurnContext(1, 2, "task", "test", "", "", [], [], None, {})
    await observer.on_tool_result(
        ctx,
        ToolResult(
            name="corpus_fetch",
            args={"locator": NATIVE},
            result=json.dumps(payload, ensure_ascii=False),
            duration_ms=0,
            tool_call_id="call_native",
            is_error=False,
        ),
    )
    assert len(ledger.native_mappings) == 1
    assert ledger.native_mappings[0]["locator"] == NATIVE


# ── 离线重放工具 ───────────────────────────────────────────────────────


def test_replay_loads_ledger_mapping_and_external_table(tmp_path) -> None:
    from scripts.replay_corpus_coverage import (
        load_native_mappings,
        retrieval_scope_coverage,
    )

    mapping = _mapping()
    assert mapping is not None
    corpus = tmp_path / "run" / "corpus"
    corpus.mkdir(parents=True)
    (corpus / "ledger.json").write_text(
        json.dumps({"native_mappings": [mapping.to_dict()]}), encoding="utf-8"
    )
    loaded = load_native_mappings(tmp_path, None)
    assert loaded == [mapping]

    external = tmp_path / "map.json"
    external.write_text(json.dumps([mapping.to_dict()]), encoding="utf-8")
    assert load_native_mappings(tmp_path, external) == [mapping]

    deliveries = [Delivery(DOC, UNIT_LOC, 0, 6)]
    scope = retrieval_scope_coverage(loaded, deliveries, doc_id=DOC, expected_locators=[NATIVE])
    assert scope["mapped_blocks"] == 1
    assert scope["denominator_chars"] == 6
    assert scope["delivered_chars"] == 6
    assert scope["ratio"] == 1.0 and scope["complete"] is True

    partial = retrieval_scope_coverage(loaded, [Delivery(DOC, UNIT_LOC, 0, 3)], doc_id=DOC)
    assert partial["delivered_chars"] == 3 and partial["complete"] is False
    empty = retrieval_scope_coverage([], deliveries, doc_id=DOC)
    assert empty["ratio"] is None and empty["complete"] is False
