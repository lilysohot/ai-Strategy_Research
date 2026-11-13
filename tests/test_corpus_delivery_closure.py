"""Regressions at the pager -> workflow -> final-message -> ledger boundary."""

import json

import pytest

from frontier_agent.core.loop_types import ToolResult
from plugins.corpus import projection
from plugins.corpus.cursor import decode_cursor
from plugins.corpus.ledger import ConsumptionLedger
from plugins.corpus.preparation import document_read, read_pg
from plugins.tools import _corpus_document as pager
from workflows.agent_team.subagent_runtime import SwarmToolResultPostProcessor
from workflows.stateful_react_agent._runtime import ReactToolResultPostProcessor

DOC = "cv2:" + "a" * 64


class Service:
    def document_units(self, doc_id):
        return document_read.DocumentUnits(
            "source",
            DOC[4:],
            True,
            tuple(
                document_read.DocumentUnit(
                    read_pg.UnitEvidence(f"u{i}", str(i) + "正文" * 60, 1, None, ()), "body", "kept"
                )
                for i in range(80)
            ),
            ("report.pdf",),
        )


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("CORPUS_NAVIGATION_MODE", "on")
    monkeypatch.setenv("CORPUS_TOOL_REF_ROOT", str(tmp_path / "refs"))
    projection.reset_snapshot_index()
    yield
    projection.reset_snapshot_index()


@pytest.mark.parametrize("processor", [ReactToolResultPostProcessor, SwarmToolResultPostProcessor])
def test_document_page_survives_final_message_boundary(processor):
    raw = pager.document_page(Service(), DOC, 6000)
    payload = json.loads(raw)
    assert sum(len(i["text"]) for i in payload["items"]) > 5500
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(raw, tool_call_id="c")
    body = processor().process(
        ToolResult(
            name="corpus_fetch",
            args={},
            result=raw,
            duration_ms=0,
            is_error=False,
            tool_call_id="c",
        )
    )
    visible = json.loads(body)
    assert visible["ok"] and len(body) <= 12000
    assert [i["text"] for i in visible["items"]] == [i["text"] for i in payload["items"]]
    ledger.finalize([{"role": "tool", "tool_call_id": "c", "content": body}])
    assert ledger.responses[0]["delivery_state"] == "delivered"
    assert ledger.responses[0]["visible_chars"] == len(body)


def test_legacy_and_unknown_pagination_policy():
    first = json.loads(pager.document_page(Service(), DOC, 6000))
    cursor = decode_cursor(first["next_cursor"])
    cursor.pop("ppv")
    legacy = pager.document_page(Service(), DOC, 4000, cursor)
    assert json.loads(legacy)["pagination_policy_version"] == 1
    assert len(legacy) <= 4000
    cursor["ppv"] = 999
    assert not json.loads(pager.document_page(Service(), DOC, 4000, cursor))["ok"]


def test_page_identity_and_cursor_bind_reading_range():
    a = json.loads(pager.document_page(Service(), DOC, 256, unit_range=(1, 10)))
    b = json.loads(pager.document_page(Service(), DOC, 256, unit_range=(11, 20)))
    assert a["page_id"] != b["page_id"]
    cursor = decode_cursor(a["next_cursor"])
    assert not json.loads(pager.document_page(Service(), DOC, 256, cursor, (11, 20)))["ok"]


def test_page_identity_binds_the_view_used_for_packing(monkeypatch):
    nav = json.loads(pager.document_page(Service(), DOC, 6000))
    monkeypatch.setenv("CORPUS_NAVIGATION_MODE", "off")
    compatible = json.loads(pager.document_page(Service(), DOC, 6000))
    assert nav["page_id"] != compatible["page_id"]


@pytest.mark.parametrize("bad", ["wrong_call", "missing_ref"])
def test_failed_delivery_never_becomes_coverage(bad):
    payload = json.loads(pager.document_page(Service(), DOC, 6000))
    if bad == "missing_ref":
        payload["items"][0].pop("evidence_ref")
    raw = json.dumps(payload, ensure_ascii=False)
    ledger = ConsumptionLedger()
    ledger.record_fetch_result(raw, tool_call_id="c")
    ledger.finalize(
        [{"role": "tool", "tool_call_id": "other" if bad == "wrong_call" else "c", "content": raw}]
    )
    first = ledger.fetched[0]
    assert ledger.delivered_status(first.identity) != "delivered"


def test_navigation_keeps_structure_without_internal_coordinates():
    full = {
        "ok": True,
        "doc_id": DOC,
        "filename": "report.pdf",
        "document_title": "report.pdf",
        "items": [
            {
                "text": "A",
                "evidence_ref": "ce:a",
                "content_status": "ingested_text",
                "structure_status": "partial",
                "unit_id": "u1",
            }
        ],
        "display_groups": [
            {
                "kind": "table_row",
                "relation_status": "unverified",
                "row": "1:3",
                "unit_ranges": [{"unit_id": "u1", "evidence_ref": "ce:a"}],
            }
        ],
    }
    visible = projection.project_fetch_result(full, navigation=True)
    assert visible["items"][0]["structure_status"] == "partial"
    assert visible["display_groups"][0]["evidence_refs"] == ["ce:a"]
    assert "cv2:" not in json.dumps(visible) and "unit_id" not in json.dumps(visible)
    assert "document_title" not in visible["source"]


def test_identity_records_merge_with_provenance_and_keep_versions_separate():
    ledger = ConsumptionLedger()
    ledger._record_document_identity({"doc_id": DOC, "filename": "report.pdf"}, origin="search")
    ledger._record_document_identity(
        {
            "doc_id": DOC,
            "filename": "report.pdf",
            "document_title": "Report",
            "published": "2026-11-01",
            "publication_date_basis": "document",
        }
    )
    assert len(ledger.document_identities) == 1
    row = ledger.document_identities[0]
    assert {s["tool"] for s in row["field_sources"]["filename"]} == {"search", "fetch"}
    assert row["identity"]["publication_date_basis"] == "document"
    ledger._record_document_identity({"doc_id": DOC, "filename": "conflict.pdf"})
    assert "filename" not in row["identity"] and row["conflicts"]["filename"]
    ledger._record_document_identity({"doc_id": "cv2:" + "b" * 64, "filename": "report.pdf"})
    assert len(ledger.document_identities) == 2


def test_search_receipt_mapping_closes_document_only_read(monkeypatch, tmp_path):
    from plugins.corpus.search_refs import compact_hit

    monkeypatch.setenv("CORPUS_SEARCH_REF_ROOT", str(tmp_path / "search"))
    locators = ["chunk:native1/a", "chunk:native1/b"]
    hit = {
        "doc_id": DOC,
        "build_id": DOC[4:],
        "title": "",
        "published": "",
        "snippet": "",
        "context_locators": locators,
        "scope_id": "scope:test",
        "evidence_spans": [],
        "context_native_slices": [
            {"locator": loc, "native_slices": [{"unit_id": f"u{i}", "start": 0, "end": 121}]}
            for i, loc in enumerate(locators)
        ],
    }
    compact = compact_hit(hit)
    ledger = ConsumptionLedger()
    ledger.record_search(json.dumps({"ok": True, "hits": [{"ref": compact["scope_ref"]}]}))
    assert len(ledger.native_mappings) == 2
    raw = pager.document_page(Service(), DOC, 6000)
    ledger.record_fetch_result(raw, tool_call_id="c")
    body = ReactToolResultPostProcessor().process(
        ToolResult(
            name="corpus_fetch",
            args={},
            result=raw,
            duration_ms=0,
            is_error=False,
            tool_call_id="c",
        )
    )
    ledger.finalize([{"role": "tool", "tool_call_id": "c", "content": body}])
    assert ledger.range_completeness()[0]["complete"]
    assert "native_slices" not in body and "chunk:" not in body


def test_fragment_mapping_never_shrinks_target_denominator():
    from plugins.corpus.coverage import mappings_from_fetch

    payload = {
        "ok": True,
        "doc_id": DOC,
        "build_id": DOC[4:],
        "items": [
            {
                "locator": "chunk:native1/a",
                "fragment": {"start": 0, "end": 3},
                "native_slices": [{"unit_id": "u0", "start": 0, "end": 3}],
            }
        ],
    }
    assert mappings_from_fetch(payload) == []
    payload["items"][0]["native_target_slices"] = [{"unit_id": "u0", "start": 0, "end": 121}]
    assert mappings_from_fetch(payload)[0].slices[0].end == 121


def test_partial_mapping_report_does_not_claim_scope_complete():
    from plugins.corpus.coverage import Delivery, build_native_mapping
    from scripts.replay_corpus_coverage import retrieval_scope_coverage

    mapping = build_native_mapping(
        doc_id=DOC,
        build_id=DOC[4:],
        locator="chunk:native1/a",
        rows=[{"unit_id": "u0", "start": 0, "end": 3}],
    )
    report = retrieval_scope_coverage(
        [mapping],
        [Delivery(DOC, pager.unit_locator("u0"), 0, 3)],
        doc_id=DOC,
        expected_locators=["chunk:native1/a", "chunk:native1/missing"],
    )
    assert report["ratio"] == 1 and report["complete"] is False
    assert report["unmapped"] == ["chunk:native1/missing"]


def test_aggregate_budget_preserves_protocol_and_recoverable_snapshots():
    from frontier_agent.core.runtime.loop.tool_exec import _apply_aggregate_budget
    from plugins.tools._overflow import MAX_AGGREGATE_RESULT_CHARS

    raw = pager.document_page(Service(), DOC, 6000)
    results = [
        ToolResult(
            name="corpus_fetch",
            args={},
            result=raw,
            duration_ms=0,
            is_error=False,
            tool_call_id=str(i),
        )
        for i in range(30)
    ]
    bounded = _apply_aggregate_budget(results)
    from plugins.tools._overflow import result_budget_view

    assert (
        sum(len(result_budget_view(r.name, r.result)) for r in bounded)
        <= MAX_AGGREGATE_RESULT_CHARS
    )
    for result in bounded:
        payload = json.loads(result.result)
        if payload.get("ok"):
            assert projection.try_materialize("corpus_fetch", result.result) is not None
        else:
            assert not payload.get("next_cursor")


def test_hidden_metadata_does_not_consume_aggregate_allowance():
    from frontier_agent.core.runtime.loop.tool_exec import _apply_aggregate_budget
    from plugins.tools._overflow import MAX_AGGREGATE_RESULT_CHARS, result_budget_view

    raw = pager.document_page(Service(), DOC, 6000)
    count = MAX_AGGREGATE_RESULT_CHARS // len(raw) + 1
    results = [
        ToolResult(
            name="corpus_fetch",
            args={},
            result=raw,
            duration_ms=0,
            is_error=False,
            tool_call_id=str(i),
        )
        for i in range(count)
    ]
    assert sum(len(r.result) for r in results) > MAX_AGGREGATE_RESULT_CHARS
    assert (
        sum(len(result_budget_view(r.name, r.result)) for r in results) < MAX_AGGREGATE_RESULT_CHARS
    )
    assert _apply_aggregate_budget(results) == results


def test_changed_visible_message_cannot_reuse_call_snapshot():
    raw = pager.document_page(Service(), DOC, 6000)
    body = projection.project_tool_result("corpus_fetch", raw, tool_call_id="c")
    changed = json.loads(body)
    changed["items"][0]["text"] = "removed"
    assert projection.try_materialize("corpus_fetch", json.dumps(changed), tool_call_id="c") is None


def test_structured_failure_remains_json_with_recovery_tool_enabled():
    from frontier_agent.core.runtime.loop.agent_loop import _with_recovery_handle

    raw = pager.document_page(Service(), DOC, 6000)
    body = '{"ok":false,"code":"metadata_unavailable","fetch_complete":false}'
    result = ToolResult(name="corpus_fetch", args={}, result=raw, duration_ms=0,
                        is_error=False, tool_call_id="c")
    assert _with_recovery_handle(body, result, 1, enabled=True) == body


async def test_dedup_receipt_reports_failure_of_final_primary_message():
    from frontier_agent.core.loop_types import LoopConfig, TurnContext
    from frontier_agent.core.runtime.loop.agent_loop import _execute_tool_batch
    from frontier_agent.core.tool import tool
    from plugins.corpus.ledger import fetch_delivery_complete

    @tool
    async def corpus_fetch() -> str:
        """Return a version-bound page."""
        return pager.document_page(Service(), DOC, 6000)

    corpus_fetch.metadata.update(
        dedup_within_turn=True, dedup_delivery_validator=fetch_delivery_complete
    )

    class BlockFirst:
        def process(self, result):
            if result.tool_call_id == "a":
                return '{"ok":false,"error":"budget_exceeded"}'
            return result.result

    calls = [{"id": c, "name": "corpus_fetch", "args": {}} for c in ("a", "b")]
    messages = []
    ctx = TurnContext(1, 2, "task", "test", "", "", calls, messages, None, {})
    await _execute_tool_batch(
        LoopConfig(tool_result_post_processor=BlockFirst()),
        [],
        {"corpus_fetch": corpus_fetch},
        messages,
        {},
        1,
        0,
        ctx,
        calls,
    )
    receipt = json.loads(messages[-1]["content"])
    assert receipt["code"] == "dedup_target_not_delivered"
    assert "请勿重复" not in receipt["note"] and "重试" in receipt["note"]


def test_native_search_producer_keeps_every_context_member(monkeypatch):
    from types import SimpleNamespace

    from plugins.corpus.retrieval import native_live
    from plugins.corpus.retrieval.native import NativeSpan

    blocks = [
        SimpleNamespace(
            build_id=DOC[4:],
            chunk_id=f"c{i}",
            source_id="s",
            text=f"text{i}",
            published="",
            slices=(NativeSpan(f"u{i}", 1, 0, 5, "b" * 64),),
        )
        for i in range(2)
    ]
    index = SimpleNamespace(
        chunks=[
            {
                "build_id": DOC[4:],
                "chunk_id": b.chunk_id,
                "kind": "body",
                "title_text": "",
                "input_hash": "x",
            }
            for b in blocks
        ],
        dates=[],
        vectors={},
    )
    result = SimpleNamespace(
        blocks=blocks,
        query_terms=(),
        retrieval_mode="hybrid",
        fallback_reason=None,
        index_id="test",
        char_budget=6000,
        block_limit=20,
        cutoff="2026-11-13",
        unknown_date_sources=[],
    )
    monkeypatch.setattr(native_live, "configured_seed", lambda target: index)
    monkeypatch.setattr(native_live, "refresh", lambda *a: index)
    monkeypatch.setattr(native_live, "search_native", lambda *a, **kw: result)
    monkeypatch.setattr(native_live, "compose_with_evidence", lambda *a, **kw: ("", ()))
    hits, _ = native_live.search("", "postgres", "", 2)
    hit = hits[0]
    assert [m["locator"] for m in hit.context_native_slices] == list(hit.context_locators)
    assert [m["native_slices"][0]["unit_id"] for m in hit.context_native_slices] == ["u0", "u1"]
