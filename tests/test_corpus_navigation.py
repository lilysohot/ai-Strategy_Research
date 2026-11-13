"""§2 / §5 第二步：可选导航协议与 ref / 独立游标读取入口。

默认流程不变；导航模式显式开启且带独立版本标记。search 只负责选择，
fetch 从收据还原版本与范围并交付权威原文，预览不进入已读证据集合。
"""

from __future__ import annotations

import asyncio
import importlib
import json
from types import SimpleNamespace

import pytest

from frontier_agent.core.loop_types import ToolResult
from plugins.corpus import cursor as cursor_mod
from plugins.corpus import projection, search_refs, tool_refs
from plugins.corpus.ledger import ConsumptionLedger
from plugins.corpus.preparation import document_read, read_pg
from plugins.corpus.retrieval.embedding import text_hash
from workflows.stateful_react_agent._runtime import ReactToolResultPostProcessor

fetch_module = importlib.import_module("plugins.tools.corpus_fetch")
search_module = importlib.import_module("plugins.tools.corpus_search")

_BUILD = "a" * 64
_DOC = "cv2:" + _BUILD
_TEXT = "认证周期构成优势。"
_LOCATOR = f"chunk:native1/{_BUILD[:16]}%3Abody%3A0001/0123456789abcdef"
_LOCATOR_2 = _LOCATOR.replace("0001", "0002")
_LABEL = "【1/2】〔原文字符0:9〕"
_FILENAME = "2026-11-06_深度_太空算力：SPCX_有望在_2028_年实现_1_GW_在.pdf"
_SECTION_TITLE = "SpaceX：模型能力落后，但算力资源雄厚"


def _full_hit() -> dict:
    return {
        "doc_id": _DOC,
        "build_id": _BUILD,
        "source_id": _BUILD,
        "locator": _LOCATOR,
        "chunk_id": "body:0001",
        "scope_id": "scope:1",
        "context_locators": [_LOCATOR, _LOCATOR_2],
        "by_kind": {"body": 2},
        "total_chunks": 2,
        "title": "竞争优势",
        "published": "2026-10-24",
        "snippet": _LABEL + _TEXT,
        "evidence_contract": "native-search-evidence-v1",
        "evidence_spans": [
            {
                "member": 1,
                "start": 0,
                "end": len(_TEXT),
                "snippet_start": len(_LABEL),
                "snippet_end": len(_LABEL) + len(_TEXT),
                "text_chars": len(_TEXT),
                "text_sha256": text_hash(_TEXT),
                "quote_sha256": text_hash(_TEXT),
            }
        ],
    }


def _evidence(text: str = _TEXT, *, page: int = 3) -> read_pg.ChunkEvidence:
    unit = read_pg.UnitEvidence(unit_id="u1", raw_text=text, page=page, element=None, cells=())
    base = read_pg.ChunkEvidence(
        source_id="src",
        build_id=_BUILD,
        chunk_id="c1",
        kind="body",
        title_text=None,
        section_path=(),
        units=(),
        text="",
        source_ranges=(),
        spans=(),
        active=True,
    )
    return read_pg.with_units(base, (unit,))


class _StubService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.document_calls: list[str] = []

    def fetch_verbatim(self, doc_id: str, locator: str) -> read_pg.ChunkEvidence:
        self.calls.append((doc_id, locator))
        return _evidence()

    def emit_cells(self, evidence: read_pg.ChunkEvidence) -> list:
        return []

    def context_relations(self, doc_id: str, locators: list[str]) -> dict:
        return {}

    def document_units(self, doc_id: str) -> document_read.DocumentUnits:
        self.document_calls.append(doc_id)
        unit = read_pg.UnitEvidence(unit_id="u1", raw_text=_TEXT, page=3, element=None, cells=())
        return document_read.DocumentUnits(
            source_id="src",
            build_id=_BUILD,
            active=True,
            units=(document_read.DocumentUnit(unit, "body", "kept"),),
        )

    def search_with_coverage(self, query: str, limit: int | None = None, **kwargs):
        hit = _full_hit()
        hit["title"] = _SECTION_TITLE  # matched heading, not the source filename
        return (
            [
                SimpleNamespace(
                    **hit,
                    ingested_at=None,
                    publication_date_basis="unknown",
                    context_by_kind={"body": 2},
                )
            ],
            {
                "query_status": "matched",
                "availability": "unknown",
                "processing": "full",
                "native": {"policy": "native1"},
            },
        )


@pytest.fixture
def service(monkeypatch):
    svc = _StubService()
    monkeypatch.setattr(fetch_module, "get_service", lambda: svc)
    monkeypatch.setattr(search_module, "get_service", lambda: svc)
    identity = {_DOC: {"filename": _FILENAME, "document_title": _FILENAME}}

    def fake_titles(doc_ids):
        return {doc_id: identity[doc_id] for doc_id in doc_ids if doc_id in identity}

    monkeypatch.setattr(fetch_module, "document_titles", fake_titles)
    monkeypatch.setattr(search_module, "document_titles", fake_titles)
    return svc


@pytest.fixture(autouse=True)
def _isolated_index():
    projection.reset_snapshot_index()
    yield
    projection.reset_snapshot_index()


def _call(**kwargs):
    return json.loads(asyncio.run(fetch_module.corpus_fetch.func(**kwargs)))


# ── navigation search selects, never delivers ──────────────────────────


def test_navigation_search_returns_only_handles_and_short_preview(service, monkeypatch):
    monkeypatch.setenv("CORPUS_NAVIGATION_MODE", "on")
    payload = json.loads(asyncio.run(search_module.corpus_search.func(query="认证周期")))

    assert payload["protocol"] == projection.NAVIGATION_VERSION
    assert payload["count"] == 1
    hit = payload["hits"][0]
    assert set(hit) <= {
        "ref",
        "filename",
        "document_title",
        "section_title",
        "published",
        "published_basis",
        "preview", "table_chunks", "table_chunks_scope", "source_table_count",
    }
    assert hit["ref"].startswith("sref:") and len(hit["ref"]) == 5 + 64
    # Task information survives projection: the real filename is distinct from
    # the matched section heading, and the ambiguous bare "title" is gone.
    assert hit["filename"] == _FILENAME
    assert "document_title" not in hit
    assert hit["table_chunks_scope"] == "retrieved_chunks_classified_as_table"
    assert hit["source_table_count"] is None
    assert hit["section_title"] == _SECTION_TITLE
    assert hit["section_title"] != hit["filename"]
    assert "title" not in hit
    assert len(hit.get("preview", "")) <= 240
    assert "excerpts" not in hit and "doc_id" not in hit and "scope_ref" not in hit
    assert "preview 不可引用" in payload["hint"]
    assert "filename" in payload["hint"] and "section_title" in payload["hint"]
    # Compact coverage status remains for the existing scope guardrails, but the
    # complete diagnostics are not expanded in the model message.
    assert payload["coverage"]["query_status"] == "matched"
    assert "body_characters" not in payload["coverage"].get("native", {})

    ledger = ConsumptionLedger()
    ledger.record_search(json.dumps(payload, ensure_ascii=False))
    assert not ledger.fetched  # previews are not read evidence
    assert ledger.offered and ledger.offered[0]["locators"] == [_LOCATOR, _LOCATOR_2]


def test_explicit_off_keeps_legacy_search_originals(service, monkeypatch):
    monkeypatch.setenv("CORPUS_NAVIGATION_MODE", "off")
    payload = json.loads(asyncio.run(search_module.corpus_search.func(query="认证周期")))
    assert payload.get("protocol") is None
    assert payload["hits"][0]["excerpts"][0]["text"] == _TEXT
    assert payload["hits"][0]["scope_ref"].startswith("sref:")


def test_navigation_is_enabled_by_default(monkeypatch):
    """The product default is nav on; both the view and the prompt must agree."""
    monkeypatch.delenv("CORPUS_NAVIGATION_MODE", raising=False)
    from server.profile import NAVIGATION_READ_POLICY, build_prompt_addenda

    assert projection.navigation_enabled() is True
    addenda = build_prompt_addenda(pipeline_id="stateful-react-agent")
    assert NAVIGATION_READ_POLICY in addenda["_sys_prompt_addendum"]
    team = build_prompt_addenda(pipeline_id="agent_team")
    assert NAVIGATION_READ_POLICY in team["_sys_prompt_addendum"]
    assert NAVIGATION_READ_POLICY in team["_subagent_prompt_addendum"]


@pytest.mark.parametrize("value", ["off", "0", "false", "no", " OFF "])
def test_explicit_off_disables_navigation(monkeypatch, value):
    monkeypatch.setenv("CORPUS_NAVIGATION_MODE", value)
    from server.profile import NAVIGATION_READ_POLICY, build_prompt_addenda

    assert projection.navigation_enabled() is False
    assert (
        NAVIGATION_READ_POLICY
        not in build_prompt_addenda(pipeline_id="stateful-react-agent")["_sys_prompt_addendum"]
    )


@pytest.mark.parametrize("mode", ["on", "off"])
def test_team_citation_policy_matches_the_visible_protocol(monkeypatch, mode):
    from server.profile import (
        LEGACY_CITATION_POLICY,
        NAVIGATION_READ_POLICY,
        build_prompt_addenda,
    )

    monkeypatch.setenv("CORPUS_NAVIGATION_MODE", mode)
    prompts = build_prompt_addenda(pipeline_id="agent_team")
    for prompt in prompts.values():
        assert "carry its doc_id" not in prompt
        assert "cite doc_id + locator when found" not in prompt
        assert "cite every item with its doc_id" not in prompt
        assert (NAVIGATION_READ_POLICY in prompt) == (mode == "on")
        assert (LEGACY_CITATION_POLICY in prompt) == (mode == "off")
        assert "evidence_ref" in prompt


@pytest.mark.parametrize("mode", ["on", "off"])
def test_fetch_prefers_pinned_original_filename_without_catalog(monkeypatch, mode):
    monkeypatch.setenv("CORPUS_NAVIGATION_MODE", mode)

    def unavailable_catalog(_):
        pytest.fail("existing source names must not require the active catalog")

    monkeypatch.setattr(fetch_module, "document_titles", unavailable_catalog)
    body = fetch_module._attach_document_identity(json.dumps({
        "ok": True, "doc_id": _DOC, "original_names": [None, "", "原始文件.pdf"],
        "title": "正文中的小标题", "text": _TEXT,
    }, ensure_ascii=False))
    visible = json.loads(projection.project_tool_result("corpus_fetch", body))
    identity = visible["source"] if mode == "on" else visible
    assert identity["filename"] == "原始文件.pdf"
    if mode == "off":
        assert identity["document_title"] == "原始文件.pdf"
    else:
        assert "document_title" not in identity


def test_fetch_identity_never_substitutes_section_title(monkeypatch):
    monkeypatch.setattr(fetch_module, "document_titles", lambda _: {})
    result = json.loads(fetch_module._attach_document_identity(json.dumps({
        "ok": True, "doc_id": _DOC, "title": "小标题", "original_names": [],
    })))
    assert "filename" not in result and "document_title" not in result
    assert any("文件名不可用" in note for note in result["limitations"])


def test_fetch_preserves_explicit_document_title_and_filename(monkeypatch):
    monkeypatch.setattr(fetch_module, "document_titles", lambda _: pytest.fail("unneeded lookup"))
    result = json.loads(fetch_module._attach_document_identity(json.dumps({
        "ok": True, "filename": "实际文件.pdf", "document_title": "正式标题",
        "original_names": ["别名.pdf"],
    })))
    assert result["filename"] == "实际文件.pdf" and result["document_title"] == "正式标题"


# ── ref / cursor entries ────────────────────────────────────────────────


def test_fetch_by_ref_restores_version_and_candidate_scope(service):
    hit = search_refs.compact_hit(_full_hit())
    ref = hit["scope_ref"]
    payload = _call(ref=ref)

    assert payload["ok"] is True
    assert payload["ref"] == ref and payload["doc_id"] == _DOC
    assert [item["text"] for item in payload["items"]] == [_TEXT, _TEXT]
    assert all(item["evidence_ref"].startswith("ce:") for item in payload["items"])
    assert service.calls == [(_DOC, _LOCATOR), (_DOC, _LOCATOR_2)]
    assert not service.document_calls  # candidates != whole document
    assert payload["fetch_complete"] is True
    # The citation handle resolves back to the same verbatim text and position.
    resolved = tool_refs.resolve_evidence_reference(payload["items"][0]["evidence_ref"])
    assert resolved["quote"] == _TEXT and resolved["doc_id"] == _DOC
    assert resolved["locator"] == _LOCATOR


def test_fetch_ref_document_scope_reads_document_order(service):
    ref = search_refs.compact_hit(_full_hit())["scope_ref"]
    payload = _call(ref=ref, scope="document")
    assert payload["scope"] == "document" and payload["doc_id"] == _DOC
    assert payload["items"][0]["text"] == _TEXT
    assert service.document_calls == [_DOC] and not service.calls


def test_cursor_only_continues_without_model_supplied_doc_id(service):
    encoded = cursor_mod.encode_cursor(
        {
            "type": cursor_mod.CONTENT,
            "doc_id": _DOC,
            "build_id": _BUILD,
            "req": [_LOCATOR],
            "view": "compact",
            "mi": 0,
            "off": 0,
            "unresolved": [],
        },
        compressed=True,
    )
    cursor_ref = tool_refs._store("cpage", encoded)
    payload = _call(cursor=cursor_ref)
    assert payload["ok"] is True and payload["doc_id"] == _DOC
    assert payload["items"][0]["text"] == _TEXT
    assert service.calls == [(_DOC, _LOCATOR)]


def test_ref_entry_fail_closed_on_mixed_or_invalid_handles(service):
    ref = search_refs.compact_hit(_full_hit())["scope_ref"]
    mixed = _call(ref=ref, doc_id=_DOC, locator=_LOCATOR)
    assert mixed["ok"] is False and "互斥" in mixed["error"]

    missing = _call(ref="sref:" + "f" * 64)
    assert missing["ok"] is False and "search_reference_unavailable" in missing["error"]

    wrong_kind = _call(ref="ce:" + "c" * 32)
    assert wrong_kind["ok"] is False

    no_selector = _call(ref=None, doc_id=None)
    assert no_selector["ok"] is False and "doc_id" in no_selector["error"]


def test_ref_candidate_scope_respects_dispatched_unit_range(service):
    from plugins.tools._corpus_document import reset_unit_range_scope, set_unit_range_scope

    hit = _full_hit()
    hit["context_locators"] = ["unit:0099"]
    ref = "sref:" + search_refs._store(hit)
    token = set_unit_range_scope(1, 1)
    try:
        payload = _call(ref=ref)
    finally:
        reset_unit_range_scope(token)
    assert payload["ok"] is False and "unit_range_violation" in payload["error"]
    assert not service.calls  # rejected before any authoritative read


# ── navigation fetch view ───────────────────────────────────────────────


def test_navigation_fetch_view_hides_internal_identities(service, monkeypatch):
    monkeypatch.setenv("CORPUS_NAVIGATION_MODE", "on")
    ref = search_refs.compact_hit(_full_hit())["scope_ref"]
    full = json.dumps(_call(ref=ref), ensure_ascii=False)
    out = ReactToolResultPostProcessor().process(
        ToolResult(
            name="corpus_fetch",
            args={},
            result=full,
            duration_ms=0,
            tool_call_id="nav-1",
            is_error=False,
        )
    )
    view = json.loads(out)

    assert view["protocol"] == projection.NAVIGATION_VERSION
    assert view["scope"] == "candidates" and view["fetch_complete"] is True
    assert "doc_id" not in view and "build_id" not in view and "cmeta" not in out
    assert view["source"]["ref"] == ref
    # The source identity is task information: hidden coordinates stay hidden,
    # but the real filename/title must survive the navigation projection.
    assert view["source"]["filename"] == _FILENAME
    assert "document_title" not in view["source"]
    for item in view["items"]:
        assert set(item) <= {"text", "evidence_ref", "location", "content_role",
                             "structure_status", "content_status", "text_origin", "ocr_unverified"}
        assert item["text"] == _TEXT
        assert item["location"] == "第 3 页"
        assert "locator" not in item and "fragment" not in item
    assert projection.materialize("corpus_fetch", out, tool_call_id="nav-1")["doc_id"] == _DOC


def test_legacy_fetch_view_keeps_source_identity(service, monkeypatch):
    """The first-step whitelist must not drop the document identity either."""
    monkeypatch.setenv("CORPUS_NAVIGATION_MODE", "off")
    ref = search_refs.compact_hit(_full_hit())["scope_ref"]
    full = json.dumps(_call(ref=ref), ensure_ascii=False)
    out = ReactToolResultPostProcessor().process(
        ToolResult(
            name="corpus_fetch",
            args={},
            result=full,
            duration_ms=0,
            tool_call_id="legacy-1",
            is_error=False,
        )
    )
    view = json.loads(out)
    assert view["protocol"] == projection.VISIBLE_VERSION
    assert view["filename"] == _FILENAME
    assert view["document_title"] == _FILENAME


def test_navigation_end_to_end_cites_only_fetched_text(service, monkeypatch):
    monkeypatch.setenv("CORPUS_NAVIGATION_MODE", "on")
    nav = json.loads(asyncio.run(search_module.corpus_search.func(query="认证周期")))
    ref = nav["hits"][0]["ref"]
    page = _call(ref=ref)

    ledger = ConsumptionLedger()
    ledger.record_search(json.dumps(nav, ensure_ascii=False))
    assert not ledger.fetched
    ledger.record_fetch_result(json.dumps(page, ensure_ascii=False))
    ledger.finalize(
        [
            {
                "role": "tool",
                "name": "corpus_fetch",
                "content": json.dumps(page, ensure_ascii=False),
                "tool_call_id": "nav-1",
            }
        ]
    )
    assert ledger.fetched
    assert all(
        ledger.delivered_status(fragment.identity) == "delivered" for fragment in ledger.fetched
    )
    citation = page["items"][0]["evidence_ref"]
    assert tool_refs.resolve_evidence_reference(citation)["quote"] == _TEXT
