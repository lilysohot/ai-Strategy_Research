"""逐调用送达判据：配对／未被预算替换／快照可恢复／区间与引用完整。

这是同轮同参去重的前置条件：只有第一份完整正文确实保留，才能省略第二份。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from plugins.corpus import projection, tool_refs
from plugins.corpus.ledger import (
    BLOCKED_BY_BUDGET,
    DELIVERED,
    SNAPSHOT_UNRECOVERABLE,
    TRUNCATED,
    UNKNOWN,
    ConsumptionLedger,
)

DOC = "cv2:" + "c" * 64
LOC = "chunk:document1/unit%3A0001"
LOC2 = "chunk:document1/unit%3A0002"
TEXT = "轨道算力 2028 年 1GW"
CALL = "call_receipt_probe"


@pytest.fixture(autouse=True)
def _isolated_snapshots(monkeypatch):
    projection.reset_snapshot_index()
    monkeypatch.setattr(tool_refs, "metadata_snapshot_index", lambda: {})
    yield
    projection.reset_snapshot_index()


def _item(locator: str, text: str, *, evidence_ref: str = "ce:receipt") -> dict[str, Any]:
    item: dict[str, Any] = {
        "locator": locator,
        "unit_id": locator.rsplit("%3A", 1)[-1],
        "text": text,
    }
    if evidence_ref:
        item["evidence_ref"] = evidence_ref
    return item


def _envelope(items: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "scope": "document",
        "doc_id": DOC,
        "build_id": DOC[4:],
        "filename": "report.pdf",
        "document_title": "report.pdf",
        "items": [_item(LOC, TEXT)] if items is None else items,
        "item_errors": [],
        "unresolved": [],
        "next_cursor": None,
        "exhausted": True,
        "fetch_complete": True,
        **extra,
    }


def _ledger(body: dict[str, Any] | None = None) -> tuple[ConsumptionLedger, str]:
    ledger = ConsumptionLedger()
    raw = json.dumps(body if body is not None else _envelope(), ensure_ascii=False)
    ledger.record_fetch_result(raw, turn=1, tool_call_id=CALL, exposed_chars=len(raw))
    return ledger, raw


def _finalize(ledger: ConsumptionLedger, visible: str, *, call_id: str = CALL) -> dict[str, Any]:
    ledger.finalize([{"role": "tool", "tool_call_id": call_id, "content": visible}])
    return ledger.responses[0]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def test_complete_message_with_recoverable_snapshot_is_delivered() -> None:
    ledger, raw = _ledger()
    row = _finalize(ledger, raw)
    assert row["delivery_state"] == DELIVERED
    assert row["error"] == ""
    assert row["ranges"] == [
        {"locator": LOC, "start": 0, "end": len(TEXT), "chars": len(TEXT)}
    ]


def test_budget_error_replacement_blocks_delivery() -> None:
    ledger, _raw = _ledger()
    row = _finalize(
        ledger,
        _json({"ok": False, "error": "budget_exceeded：本页未送达", "text_chars": 9000}),
    )
    assert row["delivery_state"] == BLOCKED_BY_BUDGET
    assert row["error"] == "budget_or_error_replacement"


def test_character_cut_json_blocks_delivery() -> None:
    ledger, raw = _ledger()
    row = _finalize(ledger, raw[:40])
    assert row["delivery_state"] == BLOCKED_BY_BUDGET
    assert row["error"] == "malformed_message_json"


def test_cursor_omitted_blocks_delivery() -> None:
    ledger, _raw = _ledger()
    row = _finalize(ledger, _json(_envelope(cursor_omitted=True)))
    assert row["delivery_state"] == BLOCKED_BY_BUDGET
    assert row["error"] == "continuation_contract_omitted"


def test_metadata_unavailable_view_blocks_delivery() -> None:
    ledger, _raw = _ledger()
    row = _finalize(
        ledger, _json(_envelope(protocol=projection.UNAVAILABLE_VERSION, items=[]))
    )
    assert row["delivery_state"] == BLOCKED_BY_BUDGET
    assert row["error"] == "metadata_unavailable_view"


def test_tool_call_mismatch_blocks_delivery() -> None:
    ledger, _raw = _ledger()
    row = _finalize(ledger, _json(_envelope(tool="corpus_search")))
    assert row["delivery_state"] == BLOCKED_BY_BUDGET
    assert row["error"] == "tool_call_mismatch"


def test_missing_metadata_snapshot_is_not_delivered() -> None:
    ledger, _raw = _ledger()
    row = _finalize(
        ledger,
        _json(
            {
                "protocol": projection.NAVIGATION_VERSION,
                "tool": "corpus_fetch",
                "doc_id": DOC,
                "items": [],
            }
        ),
    )
    assert row["delivery_state"] == SNAPSHOT_UNRECOVERABLE
    assert row["error"] == "metadata_snapshot_unavailable_or_invalid"


def test_recovered_result_without_evidence_ref_is_not_delivered() -> None:
    ledger, _raw = _ledger()
    row = _finalize(ledger, _json(_envelope([_item(LOC, "轨道算力 2028 年 1GW", evidence_ref="")])))
    assert row["delivery_state"] == TRUNCATED
    assert row["error"] == "recovered_reference_missing"


def test_partial_recovered_ranges_are_truncated() -> None:
    ledger, _raw = _ledger(
        _envelope([_item(LOC, "甲"), _item(LOC2, "乙")])
    )
    row = _finalize(ledger, _json(_envelope([_item(LOC, "甲")])))
    assert row["delivery_state"] == TRUNCATED


def test_altered_quote_is_not_delivered() -> None:
    ledger, _raw = _ledger()
    row = _finalize(ledger, _json(_envelope([_item(LOC, "被改写的正文")])))
    assert row["delivery_state"] == UNKNOWN


def test_missing_matching_tool_message_stays_unconfirmed() -> None:
    ledger, raw = _ledger()
    row = _finalize(ledger, raw, call_id="call_other")
    assert row["delivery_state"] == "unconfirmed"


def test_diagnostic_compaction_is_not_treated_as_body_truncation() -> None:
    ledger, raw = _ledger()
    compacted = _envelope(diagnostics_elided=True, view_fallback="compact")
    row = _finalize(ledger, _json(compacted))
    assert row["delivery_state"] == DELIVERED


def test_model_self_report_does_not_establish_delivery() -> None:
    """LLM 成功返回／自称已读，都不能替代消息边界的四条判据。"""
    ledger, _raw = _ledger()
    ledger.finalize(
        [
            {
                "role": "tool",
                "tool_call_id": CALL,
                "content": _json({"ok": False, "error": "budget_exceeded"}),
            },
            {"role": "assistant", "content": "我已完整读取全部原文，可以继续。"},
        ]
    )
    assert ledger.responses[0]["delivery_state"] == BLOCKED_BY_BUDGET
