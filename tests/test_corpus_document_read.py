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
from plugins.corpus.pagination_policy import DOCUMENT_VISIBLE_CAP
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
        # v2 双预算：正文按原文字符、可见回执按独立硬上限。
        assert page["ok"] and len(raw) <= DOCUMENT_VISIBLE_CAP
        assert sum(len(item["text"]) for item in page["items"]) <= 4000
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


async def test_unit_range_clamps_document_pagination_to_the_assigned_slice(install):
    """c010c5e1: three extract agents each read all 299 units although the plan
    split 0-99/100-199/200-298 — the range lived only in free-text notes. A
    dispatched unit_range must mechanically bound pagination to the slice."""
    from plugins.tools import _corpus_document

    units = [entry(str(i).zfill(4), f"单元{i}正文。" * 5) for i in range(1, 301)]
    install(units)
    token = _corpus_document.set_unit_range_scope(100, 199)
    try:
        seen: list[int] = []
        pages = 0
        args: dict[str, object] = {"scope": "document", "max_chars": 4000}
        while True:
            _raw, page = await call(**args)
            pages += 1
            assert pages < 100
            assert page["ok"]
            assert page["total_units"] == 100
            assert page["unit_range"] == [100, 199]
            for item in page["items"]:
                seen.append(int(item["unit_id"]))
            if page["next_cursor"] is None:
                assert page["exhausted"] and page["fetch_complete"]
                break
            args = {"cursor": page["next_cursor"], "max_chars": 4000}
    finally:
        _corpus_document.reset_unit_range_scope(token)
    assert seen == list(range(100, 200)), "pagination must cover exactly the assigned slice"


async def test_unit_range_uses_source_position_not_id_format(install):
    """Regression for F27-r1: the longdoc fixture ids are u01…u60, not numeric
    strings — the first digit-only implementation filtered every unit out and
    members saw empty exhausted pages. A dispatched range bounds units by their
    1-based source position, whatever the id format."""
    from plugins.tools import _corpus_document

    units = [entry(f"u{i:02d}", f"单元{i}正文。" * 5) for i in range(1, 61)]
    install(units)
    token = _corpus_document.set_unit_range_scope(21, 40)
    try:
        _raw, page = await call(scope="document", max_chars=4000)
        assert page["ok"] and page["total_units"] == 20
        assert page["unit_range"] == [21, 40]
        seen: list[str] = [item["unit_id"] for item in page["items"]]
        # v2 下这 20 个短单元一页即可装完（可见上限 12000），不再必然分页。
        args: dict[str, object] = {"cursor": page["next_cursor"], "max_chars": 4000}
        while page["next_cursor"] is not None:
            _raw, page = await call(**args)
            assert page["ok"]
            seen.extend(item["unit_id"] for item in page["items"])
            assert page["next_cursor"] is not None or (page["exhausted"] and page["fetch_complete"])
            args = {"cursor": page["next_cursor"], "max_chars": 4000}
    finally:
        _corpus_document.reset_unit_range_scope(token)
    assert seen == [f"u{i:02d}" for i in range(21, 41)]


async def test_unit_locator_by_position_outside_range_is_rejected(install):
    from plugins.tools import _corpus_document

    units = [entry(f"u{i:02d}", "x" * 10) for i in range(1, 61)]
    install(units)
    token = _corpus_document.set_unit_range_scope(21, 40)
    try:
        raw, page = await call(locator="unit:u50", max_chars=4000)
    finally:
        _corpus_document.reset_unit_range_scope(token)
    assert not page["ok"]
    assert "21" in raw and "40" in raw


async def test_explicit_unit_locator_outside_assigned_range_is_rejected(install):
    from plugins.tools import _corpus_document

    units = [entry(str(i).zfill(4), "x" * 10) for i in (1, 50, 150)]
    install(units)
    token = _corpus_document.set_unit_range_scope(100, 199)
    try:
        raw, page = await call(locator="unit:0050", max_chars=4000)
    finally:
        _corpus_document.reset_unit_range_scope(token)
    assert not page["ok"]
    assert "100" in raw and "199" in raw


async def test_replay_and_budget_clamp(install):
    install([entry("u1", "长文。" * 6000)])
    raw, page = await call(scope="document", max_chars=50000)
    # v2 不再把 max_chars 当信封上限：可见回执由策略硬上限约束。
    assert len(fetch.projection.render_fetch_view(page)) <= DOCUMENT_VISIBLE_CAP
    assert page["pagination_policy_version"] == 2
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
        assert page["ok"] and len(raw) <= DOCUMENT_VISIBLE_CAP
        assert sum(len(item["text"]) for item in page["items"]) <= 3000
        assert page["original_names"] == (names or [])
        assert (page["doc_id"], page["build_id"], page["source_id"]) == (DOC, DOC[4:], "source")
        delivered += "".join(item["text"] for item in page["items"])
        if page["fetch_complete"]:
            break
        args = {"cursor": page["next_cursor"], "max_chars": 3000}
    assert pages > 1 and delivered == text
    identity_queries = [
        (sql, params) for sql, params in queries if "FROM corpus.corpus_builds" in sql
    ]
    assert identity_queries and all("s.original_names" in sql for sql, _ in identity_queries)
    assert all(params == (DOC[4:],) for _, params in identity_queries)


async def test_source_names_are_not_silently_truncated_to_fit_page(install):
    service = install([entry("u1", "正文")])
    # 让身份元数据本身就超过可见回执硬上限：60 个名字在 12000 上限下已装得下。
    names = tuple(f"原始名称_{i:03d}_" + "长" * 100 + ".pdf" for i in range(130))
    service.document = replace(service.document, original_names=names)
    _raw, page = await call(scope="document", max_chars=3000)
    assert page["ok"] and page["fetch_complete"]
    assert page["original_names"] == list(names)
    # All aliases stay in the receipt; only necessary identity enters context.
    assert len(fetch.projection.render_fetch_view(page)) <= DOCUMENT_VISIBLE_CAP
    assert service.document.original_names == names


def table_unit(uid, text, *, element=None, cells=()):
    return document_read.DocumentUnit(
        replace(entry(uid, text, kind="table").unit, element=element, cells=tuple(cells)),
        "table",
        "kept",
    )


async def test_ocr_text_is_never_read_as_verified_table_structure(install):
    # 缺结构（只有 OCR 文本）与缺内容（目标表格未取得）是两件事：
    # 有坐标也不能据相邻顺序还原行列，更不能声称表格内容已取得。
    install(
        [
            table_unit("unit:o1", "2028 1GW 145次", element="local_ocr:p11", cells=((11, 3, 1),)),
            table_unit("unit:o2", "2029 2GW 220次", element="local_ocr:p11", cells=((11, 3, 2),)),
        ]
    )
    _raw, page = await call(scope="document", max_chars=4000)
    assert page["ok"] and page["content_scope"] == "ingested_text_only"
    assert page["source_coverage"] == "unknown"
    assert page["display_groups"] == []
    assert [item["structure_status"] for item in page["items"]] == ["unknown", "unknown"]
    assert all(item["content_status"] == "ingested_text" for item in page["items"])
    assert all(item["ocr_unverified"] and item["text_origin"] == "ocr" for item in page["items"])
    assert all("table_row" not in item for item in page["items"])
    assert "不等于目标表格内容已取得" in page["hint"]
    assert "table_chunks" in page["hint"]


async def test_display_groups_keep_original_unit_and_char_ranges(install):
    install(
        [
            table_unit("unit:t1", "甲", cells=((11, 3, 1),)),
            table_unit("unit:t2", "乙", cells=((11, 3, 2),)),
            table_unit("unit:t3", "丙", cells=((11, 4, 1),)),
        ]
    )
    _raw, page = await call(scope="document", max_chars=4000)
    assert page["ok"]
    assert [item["structure_status"] for item in page["items"]] == ["partial"] * 3
    assert [group["row"] for group in page["display_groups"]] == ["11:3"]
    group = page["display_groups"][0]
    assert group["kind"] == "table_row" and group["relation_status"] == "unverified"
    assert [(r["unit_id"], r["start"], r["end"]) for r in group["unit_ranges"]] == [
        ("unit:t1", 0, 1),
        ("unit:t2", 0, 1),
    ]
    assert all(r["evidence_ref"] for r in group["unit_ranges"])
    # items 未被组合改写：逐字原文与引用仍是原始单元粒度。
    assert [item["text"] for item in page["items"]] == ["甲", "乙", "丙"]
