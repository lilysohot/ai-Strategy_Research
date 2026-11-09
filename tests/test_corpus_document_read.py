"""A known document can be read completely without another search or chunk inventory."""

from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from plugins.corpus.context_reuse import CorpusContextReuseObserver
from plugins.corpus.cursor import decode_cursor, encode_cursor
from plugins.corpus.ledger import ConsumptionLedger, verify_manifest
from plugins.corpus.preparation import document_read, read_pg
from plugins.corpus.tool_refs import resolve_cursor_reference, resolve_evidence_reference

fetch = importlib.import_module("plugins.tools.corpus_fetch")
DOC = "cv2:" + "a" * 64


def entry(uid, text, *, kind="body", status="kept", page=1):
    return document_read.DocumentUnit(read_pg.UnitEvidence(uid, text, page, None, ()), kind, status)


class Service:
    def __init__(self, units):
        self.document = document_read.DocumentUnits("source", DOC[4:], True, tuple(units))
        self.withdrawn = False
        self.reads = 0

    def document_units(self, doc_id):
        assert doc_id == DOC
        self.reads += 1
        if self.withdrawn:
            raise read_pg.WithdrawnError("document_source_withdrawn")
        return self.document


@pytest.fixture
def install(monkeypatch, tmp_path):
    monkeypatch.setenv("CORPUS_TOOL_REF_ROOT", str(tmp_path))

    def build(units):
        service = Service(units)
        monkeypatch.setattr(fetch, "get_service", lambda: service)
        return service

    return build


async def call(**kwargs):
    raw = await fetch.corpus_fetch.func(doc_id=DOC, **kwargs)
    return raw, json.loads(raw)


async def test_read_all_units_once_in_source_order_with_receipts(install):
    units = [
        entry("unit:z", "文档标题", kind="heading"),
        entry("unit:empty", ""),
        entry("unit:a", '正文\\"\n含中文和😀。' * 900),
        entry("unit:table", "年份\t收入\n2026\t100", kind="table"),
        entry("unit:filtered", "未被检索投影采用的原文", status="dropped"),
    ]
    service = install(units)
    ledger = ConsumptionLedger()
    messages, fragments, ids = [], {}, []
    args = {"scope": "document", "max_chars": 4000}
    pages = 0
    while True:
        raw, page = await call(**args)
        pages += 1
        assert pages < 100
        assert page["ok"] and len(raw) <= 4000
        assert page["total_units"] == len(units)
        ledger.record_fetch_result(raw)
        messages.append({"role": "tool", "content": raw})
        for item in page["items"]:
            uid = item["unit_id"]
            if uid not in fragments:
                ids.append(uid)
                fragments[uid] = ""
            start = (item.get("fragment") or {}).get("start", 0)
            assert start == len(fragments[uid])
            fragments[uid] += item["text"]
            if item["text"]:
                receipt = resolve_evidence_reference(item["evidence_ref"])
                assert receipt["quote"] == item["text"]
                assert receipt["source_start"] == start
        if page["next_cursor"] is None:
            assert page["exhausted"] and page["fetch_complete"]
            break
        assert not page["fetch_complete"]
        args = {"cursor": page["next_cursor"], "max_chars": 4000}
    assert ids == [e.unit.unit_id for e in units]
    assert fragments == {e.unit.unit_id: e.unit.raw_text for e in units}
    assert service.reads == pages > 1
    ledger.finalize(messages)
    assert all(ledger.delivered_status(ref.identity) == "delivered" for ref in ledger.fetched)
    # Full-document citations participate in the existing manifest verification.
    manifest = {
        "conclusions": [
            {
                "id": "c1",
                "report_quote": "文档标题",
                "evidence": [
                    {
                        "doc_id": DOC,
                        "locator": document_read.unit_locator("unit:z"),
                        "quote": "文档标题",
                    }
                ],
            }
        ]
    }
    result = verify_manifest(manifest, ledger=ledger, resolver=lambda doc, loc: "文档标题")
    assert result["counts"]["supported"] == 1


async def test_replay_and_budget_clamp(install):
    install([entry("u1", "长文。" * 6000)])
    raw, page = await call(scope="document", max_chars=50000)
    assert len(raw) <= 6000
    assert page["next_cursor"]
    first, _ = await call(cursor=page["next_cursor"], max_chars=3500)
    replay, _ = await call(cursor=page["next_cursor"], max_chars=3500)
    assert first == replay
    # If an outer budget drops a page, its next-page cursor must not escape.
    shaped = json.loads(fetch.fit_structured_payload(raw, 2000))
    assert not shaped["ok"] and not shaped["fetch_complete"]
    assert shaped["next_cursor"] is None
    _, retried = await call(cursor=shaped["retry_cursor"], max_chars=3000)
    assert retried["items"][0]["fragment"]["start"] == 0


async def test_withdrawal_and_document_change_fail_on_continuation(install):
    service = install([entry("u1", "正文" * 5000)])
    _, first = await call(scope="document")
    service.withdrawn = True
    _, denied = await call(cursor=first["next_cursor"])
    assert not denied["ok"] and "withdrawn" in denied["error"]
    service.withdrawn = False
    service.document = replace(service.document, units=(entry("u1", "changed"),))
    _, changed = await call(cursor=first["next_cursor"])
    assert not changed["ok"] and "document_changed" in changed["error"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"scope": "document", "locator": "chunk:c1"},
        {"scope": "document", "locators": ["chunk:c1"]},
        {"scope": "unsupported"},
        {"scope": "document", "cursor": ""},
        {"scope": "document", "cursor": "damaged"},
        {"scope": "document", "max_chars": 200},
    ],
)
async def test_invalid_requests_fail_without_reading(install, kwargs):
    service = install([])
    _, out = await call(**kwargs)
    assert not out["ok"] and service.reads == 0


async def test_foreign_cursor_and_bad_offset_are_rejected(install):
    service = install([entry("u1", "正文" * 5000)])
    _, first = await call(scope="document")
    payload = decode_cursor(resolve_cursor_reference(first["next_cursor"]))
    for changes in (
        {"doc_id": "cv2:" + "b" * 64},
        {"mi": -1},
        {"off": 100000},
        {"mi": True},
        {"type": "inventory"},
    ):
        _, out = await call(scope="document", cursor=encode_cursor(payload | changes))
        assert not out["ok"]
    # A document cursor cannot be combined with block selectors.
    _, out = await call(cursor=first["next_cursor"], locator="chunk:c1")
    assert not out["ok"]
    assert service.reads > 0


@pytest.mark.parametrize("units", [[], [entry("empty", "")]])
async def test_empty_stored_text_has_explicit_end(install, units):
    install(units)
    _, out = await call(scope="document")
    assert out["ok"] and out["exhausted"] and out["fetch_complete"]
    assert out["total_units"] == len(units)
    assert out["source_coverage"] == "unknown"


async def test_document_result_rechecks_backend_instead_of_context_reuse(install):
    install([entry("u1", "全文")])
    raw, _ = await call(scope="document")
    args = {"doc_id": DOC, "scope": "document"}
    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "old", "function": {"name": "corpus_fetch", "arguments": json.dumps(args)}}
            ],
        },
        {"role": "tool", "tool_call_id": "old", "content": raw},
    ]
    result = await CorpusContextReuseObserver().on_tool_call(
        SimpleNamespace(messages=messages), {"name": "corpus_fetch", "args": args}
    )
    assert result is None


def test_authoritative_reader_snapshot_hashes_and_unit_resolution(monkeypatch):
    from contextlib import nullcontext

    calls = []
    rows = [
        ("u2", "标题", {"page": 1}, hashlib.sha256("标题".encode()).hexdigest(), "heading", "kept"),
        (
            "u1",
            "表格原文",
            {"page": 2},
            hashlib.sha256("表格原文".encode()).hexdigest(),
            "table",
            "dropped",
        ),
    ]

    class Cursor:
        requested_unit = None
        decision = "in_scope"

        def execute(self, sql, params=None):
            calls.append((sql, params))
            if "FROM corpus.corpus_units" in sql:
                self.requested_unit = params[1] if len(params) > 1 else None

        def fetchone(self):
            # Current publication differs, but the requested build is still readable.
            return ("source", "b" * 64, self.decision, self.decision, ["登记名.pdf"])

        def fetchall(self):
            return [row for row in rows if self.requested_unit in (None, row[0])]

    cursor = Cursor()
    connection = SimpleNamespace(
        transaction=lambda: nullcontext(), cursor=lambda: nullcontext(cursor)
    )
    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda *a, **kw: nullcontext(connection))
    monkeypatch.setattr(read_pg, "_check_target", lambda *a: None)
    document = document_read.read_units("dsn", DOC)
    assert document.build_id == DOC[4:] and not document.active
    assert document.original_names == ("登记名.pdf",)
    assert [item.unit.unit_id for item in document.units] == ["u2", "u1"]
    assert any("ORDER BY ordinal NULLS LAST, unit_id" in sql for sql, _ in calls)
    assert all(params is None or params[0] == DOC[4:] for _, params in calls)
    evidence = read_pg.fetch_verbatim("dsn", DOC, document_read.unit_locator("u1"))
    assert evidence.text == "表格原文" and evidence.units[0].page == 2
    with pytest.raises(read_pg.UnknownHandleError):
        read_pg.fetch_verbatim("dsn", DOC, document_read.unit_locator("absent"))
    cursor.decision = "excluded"
    with pytest.raises(read_pg.WithdrawnError):
        document_read.read_units("dsn", DOC)
    cursor.decision = "in_scope"
    rows[0] = (*rows[0][:3], "bad-hash", *rows[0][4:])
    with pytest.raises(read_pg.IntegrityError):
        document_read.read_units("dsn", DOC)


@pytest.mark.parametrize("names", [["原始 名称_v2.pdf", "原始_别名.PDF"], [], None])
async def test_source_names_reach_public_document_pages_from_reader(monkeypatch, tmp_path, names):
    """Exercise SQL selection -> read model -> service -> public pagination, not an injected name."""
    from contextlib import nullcontext

    import psycopg

    from plugins.corpus.service import CorpusService

    queries = []
    text = "标题不等于原始文件名。" * 700

    class Cursor:
        def execute(self, sql, params=None):
            queries.append((sql, params))
            self.sql = sql

        def fetchone(self):
            # Like SQL, only return names if the production reader selects them.
            row = ("source", "b" * 64, "in_scope", "in_scope")
            return (*row, names) if "s.original_names" in self.sql else row

        def fetchall(self):
            return [
                ("u1", text, {"page": 1}, hashlib.sha256(text.encode()).hexdigest(), "body", "kept")
            ]

    connection = SimpleNamespace(
        transaction=lambda: nullcontext(), cursor=lambda: nullcontext(Cursor())
    )
    monkeypatch.setattr(psycopg, "connect", lambda *a, **kw: nullcontext(connection))
    monkeypatch.setattr(read_pg, "_check_target", lambda *a: None)
    service = CorpusService("dsn")
    monkeypatch.setattr(service, "read_chain", lambda: "new")
    monkeypatch.setattr(fetch, "get_service", lambda: service)
    monkeypatch.setenv("CORPUS_TOOL_REF_ROOT", str(tmp_path))

    args = {"scope": "document", "max_chars": 3000}
    delivered, pages = "", 0
    while True:
        raw, page = await call(**args)
        pages += 1
        assert pages < 30
        assert page["ok"] and len(raw) <= 3000
        assert page["original_names"] == (names or [])
        assert (page["doc_id"], page["build_id"], page["source_id"]) == (DOC, DOC[4:], "source")
        delivered += "".join(item["text"] for item in page["items"])
        if page["fetch_complete"]:
            break
        args = {"cursor": page["next_cursor"], "max_chars": 3000}
    assert pages > 1 and delivered == text
    identity_queries = [(sql, params) for sql, params in queries if "FROM corpus.corpus_builds" in sql]
    assert identity_queries and all("s.original_names" in sql for sql, _ in identity_queries)
    assert all(params == (DOC[4:],) for _, params in identity_queries)


async def test_source_names_are_not_silently_truncated_to_fit_page(install):
    service = install([entry("u1", "正文")])
    names = tuple(f"原始名称_{i:03d}_" + "长" * 100 + ".pdf" for i in range(60))
    service.document = replace(service.document, original_names=names)
    raw, page = await call(scope="document", max_chars=3000)
    assert len(raw) <= 3000
    assert not page["ok"] and "budget_exceeded" in page["error"]
    assert not page["fetch_complete"]
    assert "next_cursor" not in page
    assert service.document.original_names == names
