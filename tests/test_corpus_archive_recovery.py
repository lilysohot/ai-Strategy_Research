"""Recovering one archived fragment must never become "restore the document".

After a body retires, the only honest way back to it is the receipt: it names the
version, the unit and the exact text. These tests pin the four ways that can go
wrong — a hand-built handle, an unresolvable receipt, a receipt outside this
task's slice, and a quote that no longer matches — and require each to fail
explicitly. The failure mode this guards against is the quiet one: substituting
the archived statement (or another document's text) for the quote.
"""

from __future__ import annotations

import json
import sys

import pytest

from plugins.corpus import context_reuse
from plugins.tools.corpus_fetch import _fetch_evidence_ref

#: The package re-exports the decorated ``Tool`` under the module's own name, so
#: ``from plugins.tools import corpus_fetch`` yields the tool, not the module.
fetch_module = sys.modules["plugins.tools.corpus_fetch"]

DOC = "cv2:" + "a" * 64
REF = "ce:" + "b" * 32
QUOTE = "2025 财年营收 123 百万美元。"
LOCATOR = "chunk:c1/unit%3A0194"


def _evidence(**overrides):
    data = {
        "doc_id": DOC,
        "locator": LOCATOR,
        "quote": QUOTE,
        "source_start": 1000,
        "source_end": 1000 + len(QUOTE),
    }
    data.update(overrides)

    def resolve(ref: str) -> dict:
        return data

    return resolve


def _page_body(text: str = QUOTE, *, ok: bool = True) -> str:
    return json.dumps(
        {
            "ok": ok,
            "doc_id": DOC,
            "items": [{"text": text, "locator": LOCATOR, "evidence_ref": REF}],
        },
        ensure_ascii=False,
    )


@pytest.fixture
def calls(monkeypatch):
    """Capture how the page reader was called, and let each test script its reply."""
    recorded: dict = {"page": []}
    reply = {"body": _page_body()}

    def fake_page(doc_id, request, view, max_chars, member_index, offset, unresolved):
        recorded["page"].append(
            {
                "doc_id": doc_id,
                "request": request,
                "view": view,
                "max_chars": max_chars,
            }
        )
        return reply["body"]

    monkeypatch.setattr(fetch_module, "_page", fake_page)
    monkeypatch.setattr(fetch_module, "_current_unit_range", lambda: None)
    recorded["reply"] = reply
    return recorded


def test_a_receipt_recovers_only_its_own_unit(monkeypatch, calls) -> None:
    monkeypatch.setattr(
        "plugins.corpus.tool_refs.resolve_evidence_reference",
        _evidence(),
    )

    body = json.loads(_fetch_evidence_ref(REF, "compact", 6_000))

    assert body["ok"] is True
    # One unit, not the document: the locator came from the receipt.
    assert calls["page"][0]["request"] == [LOCATOR]
    assert calls["page"][0]["doc_id"] == DOC
    assert calls["page"][0]["max_chars"] == 6_000


def test_the_recovery_reports_its_range_and_size(monkeypatch, calls) -> None:
    """Task 08 has to judge whether a re-read was necessary and how much it
    returned; that cannot be reconstructed after the fact."""
    monkeypatch.setattr(
        "plugins.corpus.tool_refs.resolve_evidence_reference",
        _evidence(),
    )

    body = json.loads(_fetch_evidence_ref(REF, "compact", 1_500))

    recovered = body["recovered_from_archive"]
    assert recovered["ref"] == REF
    assert recovered["locator"] == LOCATOR
    assert recovered["source_start"] == 1000
    assert recovered["requested_chars"] == 1_500
    assert recovered["returned_chars"] > 0


def test_a_hand_built_handle_is_refused_without_a_lookup(monkeypatch, calls) -> None:
    called: list[str] = []
    monkeypatch.setattr(
        "plugins.corpus.tool_refs.resolve_evidence_reference",
        lambda ref: called.append(ref) or {},
    )

    body = json.loads(_fetch_evidence_ref("ce:not-a-real-digest", "compact", 6_000))

    assert body["ok"] is False
    assert body["error"].startswith("invalid_evidence_reference")
    assert called == [], "a malformed handle must not reach the receipt store"


def test_an_unresolvable_receipt_fails_instead_of_substituting(monkeypatch, calls) -> None:
    from plugins.corpus.tool_refs import ToolReferenceError

    def broken(ref: str) -> dict:
        raise ToolReferenceError("tool_receipt_unavailable_or_invalid；请重新取回原文")

    monkeypatch.setattr("plugins.corpus.tool_refs.resolve_evidence_reference", broken)

    body = json.loads(_fetch_evidence_ref(REF, "compact", 6_000))

    assert body["ok"] is False
    assert body["error"].startswith("evidence_reference_unavailable")
    assert body["fetch_complete"] is False
    # Nothing was read, and above all nothing was made up.
    assert calls["page"] == []
    assert "items" not in body


def test_a_quote_that_moved_is_a_version_mismatch(monkeypatch, calls) -> None:
    """The receipt is valid; its text is not where it was. That is a different
    document version, and quoting it would attribute words to a source that no
    longer says them."""
    monkeypatch.setattr(
        "plugins.corpus.tool_refs.resolve_evidence_reference",
        _evidence(),
    )
    calls["reply"]["body"] = _page_body("完全不同的正文。")

    body = json.loads(_fetch_evidence_ref(REF, "compact", 6_000))

    assert body["ok"] is False
    assert body["error"].startswith("evidence_quote_mismatch")
    assert body["doc_id"] == DOC
    assert "items" not in body


def test_a_receipt_outside_the_assigned_slice_is_refused(monkeypatch, calls) -> None:
    """A teammate must not reach another member's material through a receipt."""
    monkeypatch.setattr(
        "plugins.corpus.tool_refs.resolve_evidence_reference",
        _evidence(),
    )
    monkeypatch.setattr(fetch_module, "_current_unit_range", lambda: (1, 5))
    monkeypatch.setattr(
        fetch_module,
        "_locator_outside_range",
        lambda locator, locators, unit_range, doc_id="": LOCATOR,
    )

    body = json.loads(_fetch_evidence_ref(REF, "compact", 6_000))

    assert body["ok"] is False
    assert body["error"].startswith("unit_range_violation")
    assert body["unit_range"] == [1, 5]
    assert calls["page"] == []


def test_an_unreadable_block_is_reported_not_summarised(monkeypatch, calls) -> None:
    monkeypatch.setattr(
        "plugins.corpus.tool_refs.resolve_evidence_reference",
        _evidence(),
    )
    calls["reply"]["body"] = json.dumps({"ok": False, "error": "block_withdrawn"})

    body = json.loads(_fetch_evidence_ref(REF, "compact", 6_000))

    assert body["ok"] is False
    assert body["error"] == "block_withdrawn"
    # The archived statement is never offered as a stand-in for the text.
    assert QUOTE not in json.dumps(body, ensure_ascii=False)


def test_a_receipt_without_a_locator_is_incomplete(monkeypatch, calls) -> None:
    monkeypatch.setattr(
        "plugins.corpus.tool_refs.resolve_evidence_reference",
        _evidence(locator=""),
    )

    body = json.loads(_fetch_evidence_ref(REF, "compact", 6_000))

    assert body["ok"] is False
    assert body["error"].startswith("evidence_reference_incomplete")
    assert calls["page"] == []


# ── the reuse hint must stop claiming what is no longer there ────────────


def _messages_with(content: str) -> list[dict]:
    return [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "读"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "old",
                    "type": "function",
                    "function": {
                        "name": "corpus_fetch",
                        "arguments": json.dumps({"doc_id": DOC, "locator": "chunk:c1"}),
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "old", "content": content},
    ]


@pytest.mark.asyncio
async def test_a_retired_body_never_claims_the_original_is_still_in_context() -> None:
    """The retired marker is valid JSON, so a naive check would sail past the
    parse and then claim reuse. Saying "原文仍在当前上下文" about a pointer would be
    a false statement, and the model would cite from a hint instead of a source."""
    from types import SimpleNamespace

    from frontier_agent.core.runtime.reading.stage import archive_marker

    retired = json.dumps(
        {"retired": True, "checkpoint": "ck:run/001", "note": archive_marker("ck:run/001")},
        ensure_ascii=False,
    )
    observer = context_reuse.CorpusContextReuseObserver()

    result = await observer.on_tool_call(
        SimpleNamespace(messages=_messages_with(retired)),
        {
            "name": "corpus_fetch",
            "args": {"doc_id": DOC, "locator": "chunk:c1"},
        },
    )

    assert result is None, "a retired body must not short-circuit the fetch"


@pytest.mark.asyncio
async def test_the_same_body_before_retirement_still_reuses(monkeypatch) -> None:
    """The guard must not disable reuse in general — only the false claim."""
    from types import SimpleNamespace

    monkeypatch.setattr(
        context_reuse.projection,
        "try_materialize",
        lambda *args, **kwargs: {
            "ok": True,
            "doc_id": DOC,
            "build_id": DOC[4:],
            "items": [{"text": QUOTE, "evidence_ref": REF}],
        },
    )
    observer = context_reuse.CorpusContextReuseObserver()

    result = await observer.on_tool_call(
        SimpleNamespace(messages=_messages_with(json.dumps({"ok": True, "items": []}))),
        {
            "name": "corpus_fetch",
            "args": {"doc_id": DOC, "locator": "chunk:c1"},
        },
    )

    assert result is not None
    payload = json.loads(result.skip_with_result)
    assert payload["reused_from_context"] is True


# ── the recovered resource outlives the process, by construction ─────────


def test_a_checkpoint_and_its_references_survive_a_restart(tmp_path, monkeypatch) -> None:
    """Task 06's resource-lifecycle claim, made checkable.

    Nothing about recovery lives in memory: the checkpoint is a file and the refs
    are receipts, both under the same durable root. A new process therefore
    recovers the same fragment with no session state — which is what makes the
    next human turn, a worker restart and a watch-triggered run all work without
    a special carrier in the continuity payload.
    """
    from frontier_agent.core.runtime.reading.contract import (
        CheckpointStatus,
        Coverage,
        Finding,
        FindingKind,
        ReadingCheckpoint,
        SourceRange,
    )
    from frontier_agent.core.runtime.reading.store import JsonCheckpointStore

    monkeypatch.setenv("CORPUS_TOOL_REF_ROOT", str(tmp_path))
    directory = tmp_path / "reading"

    checkpoint = ReadingCheckpoint(
        checkpoint_id="ck:run/001",
        task_id="run",
        question="营收口径",
        findings=(
            Finding(
                finding_id="f1",
                kind=FindingKind.NUMBER,
                statement="2025 财年营收 123 百万美元",
                evidence_refs=(REF,),
                source_id=DOC,
                value="123",
                unit="百万美元",
                period="FY2025",
            ),
        ),
        sources=(SourceRange(DOC, DOC[4:], 1000, 1000 + len(QUOTE), LOCATOR),),
        coverage=Coverage(read_ranges=(SourceRange(DOC, DOC[4:], 1000, 1033),)),
        status=CheckpointStatus.INSTALLED,
    )
    JsonCheckpointStore(directory).put(checkpoint)

    # A different object, as a restarted worker would build it.
    reopened = JsonCheckpointStore(directory).get("ck:run/001")

    assert reopened is not None
    assert reopened.findings[0].evidence_refs == (REF,)
    assert reopened.sources[0].locator == LOCATOR
    assert reopened.sources[0].version == DOC[4:]
    # And the ref in it still names the exact fragment, with no in-memory index.
    assert reopened.findings[0].unit == "百万美元"
