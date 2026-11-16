"""§3.1 / §6: model-visible corpus projections, receipt recovery and replay baseline.

The complete tool result stays with internal observers; the model receives a
whitelist view. Every hidden coordinate must be recoverable from a cmeta
receipt, and "saved in the background" must never count as "delivered".
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from frontier_agent.core.loop_types import ToolResult
from plugins.corpus import projection, tool_refs
from plugins.corpus.context_reuse import CorpusContextReuseObserver
from plugins.corpus.ledger import DELIVERED, UNKNOWN, ConsumptionLedger
from plugins.corpus.retrieval.embedding import text_hash
from plugins.corpus.search_refs import compact_hit
from server.corpus_receipts import stage_corpus_receipts
from workflows.agent_team.subagent_runtime import SwarmToolResultPostProcessor
from workflows.stateful_react_agent._runtime import ReactToolResultPostProcessor

_BUILD_A = "a" * 64
_BUILD_B = "b" * 64
_LOCATOR_A = f"chunk:native1/{_BUILD_A[:16]}%3Abody%3A0001/0123456789abcdef"


def _full_hit(*, build: str = _BUILD_A, text: str = "认证周期构成优势。") -> dict:
    locator = _LOCATOR_A.replace(_BUILD_A[:16], build[:16])
    return {
        "doc_id": "cv2:" + build,
        "build_id": build,
        "source_id": build,
        "locator": locator,
        "chunk_id": "body:0001",
        "scope_id": "scope:" + build,
        "context_locators": [locator, locator.replace("0001", "0002")],
        "by_kind": {"body": 2},
        "total_chunks": 2,
        "title": "竞争优势",
        "published": "2026-10-24",
        "snippet": text,
        "evidence_contract": "native-search-evidence-v1",
        "evidence_spans": [
            {
                "member": 1,
                "start": 0,
                "end": len(text),
                "snippet_start": 0,
                "snippet_end": len(text),
                "text_chars": len(text),
                "text_sha256": text_hash(text),
                "quote_sha256": text_hash(text),
            }
        ],
    }


def _search_body(*hits: dict) -> str:
    return json.dumps(
        {
            "ok": True,
            "query": "认证周期",
            "count": len(hits),
            "hits": list(hits),
            "coverage": {
                "native": {"policy": "native1", "body_characters": 120, "blocks_ranked": 8},
                "query_status": "matched",
                "availability": "unknown",
                "reason_codes": ["scope_limited", "date_unknown"],
                "processing": "scoped",
            },
            "delivery": {"evidence_characters": 10, "evidence_blocks": 1},
            "hint": "证据足够时无需重复 fetch。",
        },
        ensure_ascii=False,
    )


def _fetch_body() -> dict:
    return {
        "ok": True,
        "view": "full",
        "doc_id": "cv2:" + _BUILD_A,
        "locator": "chunk:c1",
        "kind": "table",
        "build_id": _BUILD_A,
        "text": "收入 47.3 亿元，同比增长 30%。" * 20,
        "spans": [{"unit_id": f"u{i}", "start": i, "end": i + 1} for i in range(60)],
        "source_ranges": [[0, 420]],
        "hint": "提交清单优先用 evidence_ref。",
        "source_id": "src-1",
        "chunk_id": "c1",
        "active": True,
        "authority_rev": "rev-1",
        "context_unit_ids": ["u1", "u2"],
        "units": [
            {"unit_id": f"u{i}", "page": 3, "element": None, "cells": [[1, 2]]} for i in range(60)
        ],
        "semantic_cells": [
            {"unit_id": f"u{i}", "page": 3, "row": 1, "col": 1, "text": "细"} for i in range(180)
        ],
        "evidence_ref": "ce:" + "c" * 32,
        "meta_ref": {"doc_id": "cv2:" + _BUILD_A, "locator": "chunk:c1", "view": "full"},
    }


@pytest.fixture(autouse=True)
def _isolated_index():
    projection.reset_snapshot_index()
    yield
    projection.reset_snapshot_index()


def _processors():
    return [ReactToolResultPostProcessor(), SwarmToolResultPostProcessor()]


# ── step 1: field projection ───────────────────────────────────────────


def test_search_projection_hides_duplicate_coordinates_but_keeps_verbatim_originals():
    full = _full_hit()
    body = json.dumps(
        {"ok": True, "hits": [full], "coverage": {"native": {"policy": "native1"}}},
        ensure_ascii=False,
    )
    visible = json.loads(projection.project_tool_result("corpus_search", body, tool_call_id="s1"))
    hit = visible["hits"][0]

    assert visible["protocol"] == projection.VISIBLE_VERSION
    for hidden in ("source_id", "build_id", "chunk_id", "scope_id", "total_chunks", "by_kind"):
        assert hidden not in hit
    assert "coverage" not in visible and "delivery" not in visible
    # Everything needed by the current next call and by verbatim citation survives.
    for kept in ("doc_id", "title", "published", "snippet", "evidence_spans", "context_locators"):
        assert kept in hit
    assert hit["snippet"] == full["snippet"]
    assert (
        projection.materialize(
            "corpus_search", json.dumps(visible, ensure_ascii=False), tool_call_id="s1"
        )["hits"][0]
        == full
    )


def test_fetch_projection_keeps_text_and_handles_while_hiding_geometry():
    full = _fetch_body()
    body = json.dumps(full, ensure_ascii=False)
    visible_text = projection.project_tool_result("corpus_fetch", body, tool_call_id="f1")
    visible = json.loads(visible_text)

    assert len(visible_text) < len(body) // 4
    for hidden in (
        "build_id",
        "source_id",
        "chunk_id",
        "spans",
        "source_ranges",
        "units",
        "semantic_cells",
        "authority_rev",
        "context_unit_ids",
        "meta_ref",
        "active",
    ):
        assert hidden not in visible
    assert visible["text"] == full["text"]
    assert visible["evidence_ref"] == full["evidence_ref"]
    assert "cmeta" not in visible_text and "semantic_cells" not in visible_text
    assert projection.materialize("corpus_fetch", visible_text, tool_call_id="f1") == full


@pytest.mark.parametrize("processor", _processors())
def test_post_processors_project_only_after_the_protocol_budget_fitter(processor):
    full = _fetch_body()
    body = json.dumps(full, ensure_ascii=False)
    out = processor.process(
        ToolResult(
            name="corpus_fetch",
            args={},
            result=body,
            duration_ms=0,
            tool_call_id="call-1",
            is_error=False,
        )
    )
    payload = json.loads(out)
    assert payload["protocol"] == projection.VISIBLE_VERSION
    assert payload["text"] == full["text"]
    assert "semantic_cells" not in out
    # The fitter ran on the complete result; the projection is a pure subset.
    assert (
        projection.materialize("corpus_fetch", out, tool_call_id="call-1")["text"] == full["text"]
    )


def test_projection_is_idempotent_and_does_not_change_errors_or_other_tools():
    body = json.dumps(_fetch_body(), ensure_ascii=False)
    once = projection.project_tool_result("corpus_fetch", body, tool_call_id="f1")
    assert projection.project_tool_result("corpus_fetch", once, tool_call_id="f1") == once
    error = json.dumps({"ok": False, "error": "read_failed", "doc_id": "cv2:x"}, ensure_ascii=False)
    assert projection.project_tool_result("corpus_fetch", error) == error
    assert projection.project_tool_result("web_fetch", body) == body


# ── cmeta receipts: fail-closed and cross-run inheritance ──────────────


def test_snapshot_write_failure_degrades_to_marked_self_contained_result(monkeypatch):
    def unavailable(*args, **kwargs):
        raise tool_refs.ToolReferenceError("tool_receipt_too_large")

    monkeypatch.setattr(tool_refs, "store_metadata_snapshot", unavailable)
    body = json.dumps(_fetch_body(), ensure_ascii=False)
    out = json.loads(projection.project_tool_result("corpus_fetch", body, tool_call_id="f1"))
    assert out["protocol"] == projection.UNAVAILABLE_VERSION
    assert out["semantic_cells"] and out["text"]  # nothing was hidden
    assert any("快照不可用" in note for note in out["limitations"])
    assert projection.try_materialize("corpus_fetch", json.dumps(out, ensure_ascii=False)) == out


def test_missing_or_corrupt_snapshot_is_reported_not_guessed(tmp_path, monkeypatch):
    monkeypatch.setenv("CORPUS_TOOL_REF_ROOT", str(tmp_path / "tool-refs"))
    body = json.dumps(_fetch_body(), ensure_ascii=False)
    visible = projection.project_tool_result("corpus_fetch", body, tool_call_id="f1")
    for path in (tmp_path / "tool-refs").glob("*.json"):
        path.unlink()
    projection.reset_snapshot_index()

    assert projection.try_materialize("corpus_fetch", visible, tool_call_id="f1") is None
    with pytest.raises(projection.MetadataSnapshotError):
        projection.materialize("corpus_fetch", visible, tool_call_id="f1")

    from plugins.corpus import ledger as ledger_module
    from plugins.corpus.ledger import ConsumptionLedgerObserver

    message = {"role": "tool", "name": "corpus_fetch", "content": visible, "tool_call_id": "f1"}
    assert ledger_module._delivered_corpus_refs([message]) == set()
    ledger = ConsumptionLedger()
    ConsumptionLedgerObserver._sync_snapshots(ledger, [message])
    assert any("corpus_metadata_snapshot_unavailable" in note for note in ledger.notes)
    # The verbatim text is still visible, so plain fetch delivery verification
    # remains valid; what fails closed is any hidden-coordinate reconstruction.
    ledger.record_fetch_result(body)
    ledger.finalize([message])
    assert all(row["status"] == DELIVERED for row in ledger.to_dict()["delivered"])


def test_cross_run_receipt_inheritance_restores_the_full_result(tmp_path, monkeypatch):
    source = tmp_path / "old-run"
    target = tmp_path / "new-run"
    source_refs = source / "run" / "corpus" / "tool-refs"
    monkeypatch.setenv("CORPUS_TOOL_REF_ROOT", str(source_refs))
    body = json.dumps(_fetch_body(), ensure_ascii=False)
    visible = projection.project_tool_result("corpus_fetch", body, tool_call_id="f1")
    assert list(source_refs.glob("*.json"))

    stage_corpus_receipts(
        target_run_dir=target,
        source_runs=[("old", source)],
    )
    monkeypatch.setenv("CORPUS_TOOL_REF_ROOT", str(target / "run" / "corpus" / "tool-refs"))
    projection.reset_snapshot_index()  # simulate a fresh worker with inherited files

    restored = projection.try_materialize("corpus_fetch", visible, tool_call_id="f1")
    assert restored is not None
    assert restored["semantic_cells"] and restored["text"] == json.loads(body)["text"]


def test_receipt_inheritance_capacity_limit_is_explicit(tmp_path, monkeypatch):
    source = tmp_path / "old-run"
    monkeypatch.setenv("CORPUS_TOOL_REF_ROOT", str(source / "run" / "corpus" / "tool-refs"))
    body = json.dumps(_fetch_body(), ensure_ascii=False)
    visible = projection.project_tool_result("corpus_fetch", body, tool_call_id="f1")
    stage_corpus_receipts(
        target_run_dir=tmp_path / "new-run", source_runs=[("old", source)], max_bytes=1
    )
    monkeypatch.setenv(
        "CORPUS_TOOL_REF_ROOT", str(tmp_path / "new-run" / "run" / "corpus" / "tool-refs")
    )
    projection.reset_snapshot_index()
    # Nothing was inherited: materialization fails closed rather than silently
    # treating the visible view as the complete result.
    assert projection.try_materialize("corpus_fetch", visible, tool_call_id="f1") is None


# ── delivery / consumers must use the internal result, not the view ─────


def _ledger_for_search(full_hits: list[dict], message_content: str) -> ConsumptionLedger:
    ledger = ConsumptionLedger()
    ledger.record_search(_search_body(*full_hits))
    ledger.finalize(
        [
            {
                "role": "tool",
                "name": "corpus_search",
                "content": message_content,
                "tool_call_id": "s1",
            }
        ]
    )
    return ledger


def test_projected_search_originals_are_delivered_without_any_fetch():
    """第一步验收：search 原文足够时无需新增 fetch 即可引用。"""
    hit = compact_hit(_full_hit())
    full = json.dumps(
        {"ok": True, "hits": [hit], "coverage": {"native": {"policy": "native1"}}},
        ensure_ascii=False,
    )
    visible = projection.project_tool_result("corpus_search", full, tool_call_id="s1")
    ledger = _ledger_for_search([hit], visible)
    states = [row["status"] for row in ledger.to_dict()["delivered"]]
    assert states and all(state == DELIVERED for state in states)
    assert not ledger.requested  # no fetch was needed


def test_budget_elided_hit_is_not_delivered_by_its_background_receipt():
    from plugins.tools.corpus_search import fit_search_payload

    hits = [
        compact_hit(_full_hit(build=_BUILD_A, text="第一段认证周期构成优势。")),
        compact_hit(_full_hit(build=_BUILD_B, text="第二段认证周期构成优势。")),
    ]
    full = _search_body(*hits)
    fitted = None
    for budget in range(1_200, 300, -50):
        candidate = fit_search_payload(full, budget)
        if candidate and len(json.loads(candidate).get("hits") or []) == 1:
            fitted = candidate
            break
    assert fitted is not None
    visible = projection.project_tool_result("corpus_search", fitted, tool_call_id="s1")

    ledger = ConsumptionLedger()
    ledger.record_search(full)
    ledger.finalize(
        [{"role": "tool", "name": "corpus_search", "content": visible, "tool_call_id": "s1"}]
    )
    states = ledger.to_dict()["delivered"]
    assert len(states) == 2
    assert sum(row["status"] == DELIVERED for row in states) == 1
    assert sum(row["status"] == UNKNOWN for row in states) == 1


async def test_context_reuse_resolves_hidden_version_from_the_receipt():
    doc = "cv2:" + _BUILD_A
    full = {
        "ok": True,
        "doc_id": doc,
        "build_id": _BUILD_A,
        "locator": "chunk:c1",
        "kind": "body",
        "text": "原文证据。",
    }
    visible = projection.project_tool_result(
        "corpus_fetch", json.dumps(full, ensure_ascii=False), tool_call_id="old"
    )
    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "old",
                    "type": "function",
                    "function": {
                        "name": "corpus_fetch",
                        "arguments": json.dumps({"doc_id": doc, "locator": "chunk:c1"}),
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "old", "name": "corpus_fetch", "content": visible},
    ]
    result = await CorpusContextReuseObserver().on_tool_call(
        SimpleNamespace(messages=messages),
        {"name": "corpus_fetch", "args": {"doc_id": doc, "locator": "chunk:c1"}},
    )
    assert result is not None and result.skip_with_result
    assert json.loads(result.skip_with_result)["reused_from_context"] is True


# ── §6: fixed-result replay baseline (no model, no benchmark framework) ──


def test_fixed_replay_baseline_records_size_and_backend_cost(tmp_path, monkeypatch):
    """同一份完整结果、同一正文预算：旧返回 vs 新投影的本地固定回放。"""
    monkeypatch.setenv("CORPUS_TOOL_REF_ROOT", str(tmp_path / "tool-refs"))
    full = json.dumps(_fetch_body(), ensure_ascii=False)
    budget = 6_000

    from plugins.tools._overflow import structured_result_fit

    old = structured_result_fit("corpus_fetch", full, budget)
    assert old is not None
    new = projection.project_tool_result("corpus_fetch", old, tool_call_id="replay-1")
    old_payload, new_payload = json.loads(old), json.loads(new)

    text_chars = sum(len(str(value)) for key, value in old_payload.items() if key == "text")
    visible_text_chars = sum(len(str(value)) for key, value in new_payload.items() if key == "text")
    metadata_chars = len(old) - text_chars
    visible_metadata_chars = len(new) - visible_text_chars

    assert old_payload["text"] == new_payload["text"]
    assert old_payload["evidence_ref"] == new_payload["evidence_ref"]
    assert visible_metadata_chars < metadata_chars
    assert len(new) < len(old)
    assert projection.materialize("corpus_fetch", new, tool_call_id="replay-1") == old_payload

    # Backend cost: alternate projection / save / resolve on the same machine.
    # Content-addressed receipts are deduplicated by _store, so "首次写入" and
    # "已有 receipt" are measured as separate distributions. No model is called;
    # this is a local replay, not an end-to-end benchmark.
    def measure(call_ids: list[str]) -> tuple[list[float], list[float], str]:
        writes: list[float] = []
        reads: list[float] = []
        rendered = ""
        for tool_call_id in call_ids:
            started = time.perf_counter()
            rendered = projection.project_tool_result(
                "corpus_fetch", old, tool_call_id=tool_call_id
            )
            writes.append((time.perf_counter() - started) * 1000)
            started = time.perf_counter()
            assert projection.materialize("corpus_fetch", rendered, tool_call_id=tool_call_id)
            reads.append((time.perf_counter() - started) * 1000)
        return writes, reads, rendered

    # ``new`` above already created the replay-1 receipt; one fresh receipt is
    # timed separately, then six more fresh writes and six deduplicated repeats.
    first_write, first_resolve, _ = measure(["replay-first"])
    fresh_writes, resolve_ms, rendered = measure([f"replay-fresh-{i}" for i in range(6)])
    existing_writes, _, _ = measure(["replay-1"] * 6)
    projection_ms = fresh_writes + existing_writes
    written = list((tmp_path / "tool-refs").glob("*.json"))
    stats = {
        "kind": "fixed_result_local_replay_no_model",
        "samples": len(projection_ms),
        "old_chars": len(old),
        "new_chars": len(new),
        "text_chars": text_chars,
        "metadata_chars": metadata_chars,
        "visible_metadata_chars": visible_metadata_chars,
        "first_write_ms": first_write[0],
        "projection_ms_median": statistics.median(projection_ms),
        "projection_ms_max": max(projection_ms),
        "existing_receipt_ms_median": statistics.median(existing_writes),
        "existing_receipt_ms_max": max(existing_writes),
        "resolve_ms_median": statistics.median(first_resolve + resolve_ms),
        "resolve_ms_max": max(first_resolve + resolve_ms),
        "receipt_files": len(written),
        "receipt_bytes": sum(path.stat().st_size for path in written),
    }
    (tmp_path / "replay-baseline.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    assert projection.materialize("corpus_fetch", rendered) == old_payload
    assert stats["samples"] == 12 and stats["receipt_bytes"] > 0
    assert stats["receipt_files"] == 8  # 1 prior + 1 first + 6 fresh; repeats dedup
    assert stats["projection_ms_median"] >= 0 and stats["resolve_ms_max"] >= 0
    assert Path(tmp_path / "replay-baseline.json").is_file()


# ── v2 navigation: page-uniform provenance is stated once ───────────────
#
# A dense OCR page repeated ``"text_origin":"ocr"`` and ``"ocr_unverified":true``
# on all 76 items: 43 of the 125 characters of envelope per item, carrying no
# per-item information. These pin that the repetition is gone, that nothing
# else moved with it, and that a genuinely mixed page still tells the truth.


def _page_item(
    text: str, ref: str, page: int, **extra: object,
) -> dict:
    item: dict = {
        "text": text,
        "evidence_ref": ref,
        "locator": f"chunk:document1/unit%3A{page:04d}",
        "unit_id": f"unit:{page:04d}",
        "kind": "paragraph",
        "page": page,
    }
    item.update(extra)
    return item


def _document_body(items: list[dict], **extra: object) -> dict:
    body: dict = {
        "ok": True,
        "scope": "document",
        "doc_id": "cv2:" + _BUILD_A,
        "pagination_policy_version": 2,
        "items": items,
        "fetch_complete": False,
        "next_cursor": "cpage:" + "d" * 32,
    }
    body.update(extra)
    return body


def _dense_page(count: int = 76) -> dict:
    return _document_body([
        _page_item(
            "fragment " + "x" * 12,
            f"ce:{index:032x}",
            3,
            text_origin="ocr",
            ocr_unverified=True,
        )
        for index in range(count)
    ])


def test_uniform_item_provenance_is_stated_once() -> None:
    visible = projection.project_fetch_result(_dense_page(), navigation=True)

    assert visible["item_defaults"] == {
        "location": "第 3 页",
        "text_origin": "ocr",
        "ocr_unverified": True,
    }
    for row in visible["items"]:
        assert "location" not in row
        assert "text_origin" not in row
        assert "ocr_unverified" not in row


def test_hoisting_never_moves_an_item_or_its_evidence() -> None:
    body = _dense_page(76)
    visible = projection.project_fetch_result(body, navigation=True)

    assert len(visible["items"]) == len(body["items"])
    assert [(row["text"], row["evidence_ref"]) for row in visible["items"]] == [
        (item["text"], item["evidence_ref"]) for item in body["items"]
    ]


def test_mixed_provenance_stays_per_item() -> None:
    """Two page numbers and a native fragment: nothing is uniform, so nothing is
    hoisted. A page must never average away the fact that some of its text is
    unverified OCR and some is not."""
    body = _document_body([
        _page_item("a", "ce:" + "1" * 32, 3, text_origin="ocr", ocr_unverified=True),
        _page_item("b", "ce:" + "2" * 32, 7),
        _page_item("c", "ce:" + "3" * 32, 3, text_origin="ocr", ocr_unverified=True),
    ])

    visible = projection.project_fetch_result(body, navigation=True)

    assert "item_defaults" not in visible
    assert visible["items"][0]["text_origin"] == "ocr"
    assert visible["items"][0]["location"] == "第 3 页"
    assert visible["items"][1]["location"] == "第 7 页"
    assert "text_origin" not in visible["items"][1]


def test_a_single_item_page_does_not_grow_a_defaults_block() -> None:
    """Hoisting one item's fields to the page saves nothing and adds a key."""
    body = _document_body([_page_item("only", "ce:" + "4" * 32, 3, text_origin="ocr")])

    visible = projection.project_fetch_result(body, navigation=True)

    assert "item_defaults" not in visible
    assert visible["items"][0]["text_origin"] == "ocr"


def test_a_field_already_published_at_page_level_is_not_hoisted() -> None:
    """``content_status`` is only copied onto a row when it disagrees with the
    page, so hoisting must not re-publish the same value in two places."""
    body = _document_body(
        [_page_item("a", "ce:" + "5" * 32, 3), _page_item("b", "ce:" + "6" * 32, 3)],
        content_scope="ingested_text_only",
        content_status="ingested_text",
        structure_status="unknown",
    )

    visible = projection.project_fetch_result(body, navigation=True)

    assert visible.get("item_defaults", {}).get("content_status") is None
    assert visible["content_status"] == "ingested_text"


def test_the_dense_page_envelope_no_longer_costs_a_hundred_and_twenty_five_per_item() -> None:
    """The frozen budget target (baseline.md T1): 125 → ≤ 90 characters of
    per-item envelope. What remains is the evidence ref, the ``text`` key and the
    page label — irreducible without changing the reference wire format."""
    body = _dense_page(76)
    visible = projection.project_fetch_result(body, navigation=True)
    visible["protocol"] = projection.NAVIGATION_VERSION
    rendered = json.dumps(visible, ensure_ascii=False, separators=(",", ":"))
    text_chars = sum(len(row["text"]) for row in visible["items"])
    envelope = len(rendered) - text_chars

    assert envelope / len(visible["items"]) <= 90
    assert len(rendered) <= 9_000


def test_a_legacy_navigation_body_is_passed_through_untouched() -> None:
    """v1 bodies already exist in saved histories. Re-projecting one would change
    its shape and break the receipt its digest was stored under."""
    legacy = json.dumps({
        "ok": True,
        "protocol": "corpus-navigation-v1",
        "scope": "document",
        "items": [{"text": "old", "evidence_ref": "ce:" + "7" * 32,
                   "location": "第 3 页", "text_origin": "ocr"}],
        "fetch_complete": True,
    }, ensure_ascii=False)

    assert projection.project_tool_result("corpus_fetch", legacy) == legacy
    assert projection.is_navigation_protocol("corpus-navigation-v1")
    assert projection.is_navigation_protocol(projection.NAVIGATION_VERSION)
    assert not projection.is_navigation_protocol(projection.VISIBLE_VERSION)
