"""Tool adapter regressions: explicit scope, paging, cursors and unchanged off path."""

import asyncio
import base64
import importlib
import json
import zlib
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from plugins.corpus.cursor import CursorError, decode_cursor, encode_cursor
from plugins.corpus.preparation.read_pg import (
    ChunkEvidence,
    IntegrityError,
    UnitEvidence,
    UnknownHandleError,
)
from plugins.corpus.retrieval import native_live
from plugins.corpus.retrieval.embedding import text_hash


@pytest.mark.parametrize("mode", ["off", "pilot", "invalid"])
def test_trial_explicit_target_guard(monkeypatch, mode):
    monkeypatch.setenv("CORPUS_NATIVE_RETRIEVAL", mode)
    monkeypatch.setenv("CORPUS_NATIVE_TARGET_DB", "vector_pilot_test")
    if mode == "invalid":
        with pytest.raises(ValueError):
            native_live.enabled("vector_pilot_test")
    else:
        assert native_live.enabled("vector_pilot_test") == (mode == "pilot")
    if mode == "pilot":
        with pytest.raises(ValueError):
            native_live.enabled("production")
        with pytest.raises(ValueError):
            native_live.enabled("vector_pilot_other")


def test_source_bundle_required_and_target_bound(monkeypatch):
    monkeypatch.delenv("CORPUS_NATIVE_INDEX", raising=False)
    with pytest.raises(ValueError, match="required"):
        native_live.configured_seed("vector_pilot_test")


def test_release_requires_explicit_production_binding(monkeypatch):
    monkeypatch.setenv("CORPUS_NATIVE_RETRIEVAL", "release")
    monkeypatch.setenv("CORPUS_NATIVE_TARGET_DB", "postgres")
    monkeypatch.delenv("CORPUS_TARGET_DB", raising=False)
    with pytest.raises(ValueError, match="explicitly_bound"):
        native_live.enabled("postgres")
    monkeypatch.setenv("CORPUS_TARGET_DB", "postgres")
    assert native_live.enabled("postgres")
    with pytest.raises(ValueError):
        native_live.enabled("different_database")
    monkeypatch.setenv("CORPUS_NATIVE_RETRIEVAL", "pilot")
    with pytest.raises(ValueError, match="pilot_target"):
        native_live.enabled("postgres")


def test_release_read_binding_survives_switch_off(monkeypatch):
    from plugins.corpus.retrieval.native_target import check_native_target

    monkeypatch.setenv("CORPUS_NATIVE_RETRIEVAL", "off")
    monkeypatch.setenv("CORPUS_NATIVE_TARGET_DB", "postgres")
    monkeypatch.setenv("CORPUS_TARGET_DB", "postgres")
    assert not native_live.enabled("postgres")
    check_native_target("postgres")
    monkeypatch.setenv("CORPUS_TARGET_DB", "apodex")
    monkeypatch.setenv("CORPUS_NATIVE_TARGET_DB", "apodex")
    with pytest.raises(ValueError):
        check_native_target("apodex")


def test_http_source_limit_does_not_expand_native_block_budget(monkeypatch):
    index = SimpleNamespace(dates=[], chunks=[], vectors={})
    result = SimpleNamespace(
        blocks=[],
        retrieval_mode="hybrid",
        fallback_reason=None,
        index_id="test",
        char_budget=16000,
        block_limit=20,
        cutoff="2026-10-22",
        unknown_date_sources=[],
        query_terms=(),
    )
    monkeypatch.setattr(native_live, "configured_seed", lambda target: index)
    monkeypatch.setattr(native_live, "refresh", lambda *args: index)
    search = Mock(return_value=result)
    monkeypatch.setattr(native_live, "search_native", search)
    hits, coverage = native_live.search("", "postgres", "query", 50)
    assert hits == [] and coverage["native"]["hit_limit"] == 50
    assert search.call_args.kwargs["limit"] == 20
    assert coverage["native"]["block_limit"] == 20


def _unit(text, eligible=True):
    return {
        "unit_id": "u",
        "kind": "paragraph",
        "status": "kept",
        "raw_text": text,
        "clean_view": None,
        "content_hash": text_hash(text),
        "location": {"page": 1},
        "eligible": eligible,
    }


def test_projection_excludes_caption_and_context_without_expanding_body():
    units = {
        "u": _unit("很长的前文。目标原文。很长的后文。"),
        "caption": _unit("图1 图片", False),
        "context": _unit("另一段上下文。"),
    }
    chunk = {
        "kind": "body",
        "unit_refs": list(units),
        "context_refs": ["context"],
        "search_text": "目标原文。图1 图片",
    }
    projected = native_live.project(chunk, units)
    assert projected["unit_refs"] == ["u"]
    assert projected["search_text"] == "目标原文。"


def test_split_unsafe_unit_is_not_admitted():
    assert (
        native_live.project(
            {
                "kind": "body",
                "unit_refs": ["u", "bad"],
                "context_refs": [],
                "search_text": "正文。图中的半句",
            },
            {"u": _unit("正文。"), "bad": _unit("完整图中的半句内容", False)},
        )
        is None
    )


def test_missing_projection_unit_is_an_integrity_failure():
    with pytest.raises(IntegrityError):
        native_live.project(
            {"kind": "body", "unit_refs": ["missing"], "context_refs": [], "search_text": "正文"},
            {},
        )


def test_locator_identity_binds_original_hash_page_and_offsets():
    span = {"unit_id": "u", "page": 1, "start": 3, "end": 5, "raw_sha256": "hash"}
    original = native_live.locator_for("b:body:0001", "正文", [span])
    for key, value in [("page", 2), ("start", 4), ("raw_sha256", "other")]:
        assert native_live.locator_for("b:body:0001", "正文", [{**span, key: value}]) != original


@pytest.mark.parametrize("compressed", [False, True])
def test_cursor_roundtrip_and_corruption(compressed):
    payload = {"type": "content", "req": ["chunk:native1/test/" + "a" * 64] * 20, "off": 21}
    token = encode_cursor(payload, compressed=compressed)
    assert decode_cursor(token)["req"] == payload["req"]
    if compressed:
        assert len(token) < len(encode_cursor(payload)) / 2
    with pytest.raises(CursorError):
        decode_cursor(token[:8] + "!" + token[9:])


def test_compressed_cursor_bounded_inflation():
    token = "z1_" + base64.urlsafe_b64encode(zlib.compress(b"x" * 1000000)).decode()
    with pytest.raises(CursorError):
        decode_cursor(token)


@pytest.mark.parametrize("view,budget", [("compact", 3000), ("compact", 6000), ("full", 6000)])
def test_native_tool_paging_preserves_exact_text_and_fragment_coordinates(
    monkeypatch, view, budget
):
    fetch = importlib.import_module("plugins.tools.corpus_fetch")
    text = "收入增长12.5%。\n" * 250
    original = "前言" + text + "后记"
    native = {
        "unit_id": "u",
        "page": 1,
        "start": 2,
        "end": 2 + len(text),
        "raw_sha256": text_hash(original),
    }
    bid = "b" * 64
    ev = ChunkEvidence(
        "s",
        bid,
        "c",
        "body",
        None,
        (),
        (UnitEvidence("u", original, 1, None, ()),),
        text,
        (),
        (("u", 0, len(text)),),
        True,
        native_slices=(native,),
    )
    svc = Mock()
    svc.fetch_verbatim.return_value = ev
    svc.emit_cells.return_value = ()
    svc.context_relations.return_value = {}
    monkeypatch.setattr(fetch, "get_service", lambda: svc)
    locator = native_live.locator_for("c", text, [native])
    kwargs = {"doc_id": "cv2:" + bid, "locators": [locator], "view": view, "max_chars": budget}
    collected = ""
    for _ in range(30):
        raw = asyncio.run(fetch.corpus_fetch.ainvoke(kwargs))
        page = json.loads(raw)
        assert page["ok"] and len(raw) <= budget, page
        for item in page["items"]:
            collected += item["text"]
            for s in item["native_slices"]:
                assert (
                    original[s["start"] : s["end"]] == item["text"][s["text_start"] : s["text_end"]]
                )
        if page["exhausted"]:
            assert page["fetch_complete"]
            break
        kwargs = {"doc_id": "cv2:" + bid, "cursor": page["next_cursor"], "max_chars": budget}
        assert (
            json.loads(asyncio.run(fetch.corpus_fetch.ainvoke(kwargs)))["page_id"]
            == json.loads(asyncio.run(fetch.corpus_fetch.ainvoke(kwargs)))["page_id"]
        )
    else:
        pytest.fail("pagination did not terminate")
    assert collected == text


def test_date_refresh_does_not_keep_frozen_date_after_metadata_update():
    assert native_live._date(["report_20261020.pdf"], "2026-10-22", None)[0] == "2026-10-22"
    assert native_live._date(["report_20261020.pdf"], None, None)[0] == "2026-10-20"
    assert native_live._date(["unknown.pdf"], None, None)[0] is None


def test_trial_does_not_silently_run_legacy_read_chain(monkeypatch):
    from plugins.corpus.preparation.repository import StoreError
    from plugins.corpus.service import CorpusService

    service = object.__new__(CorpusService)
    service._target_db = "vector_pilot_test"
    monkeypatch.setattr(service, "read_chain", lambda: "legacy")
    monkeypatch.setenv("CORPUS_NATIVE_RETRIEVAL", "pilot")
    monkeypatch.setenv("CORPUS_NATIVE_TARGET_DB", "vector_pilot_test")
    with pytest.raises(StoreError, match="native_tools_require_new_read_chain"):
        service.search_with_coverage("query")


@pytest.mark.parametrize("uncertain", [False, True])
def test_sync_provider_failure_is_recorded_and_not_blindly_retried(monkeypatch, uncertain):
    from plugins.corpus.retrieval import native_sync
    from plugins.corpus.retrieval.embedding import EmbeddingError

    target = "vector_pilot_test"
    config = SimpleNamespace(target_db=target, profile="p", dimensions=2)
    index = SimpleNamespace(
        manifest={"profile": "p"},
        vectors={},
        chunks=[{"input_hash": "h", "search_text": "原文"}],
        index_id="i",
    )
    monkeypatch.setattr(native_sync, "refresh", lambda *args: index)
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.execute.return_value.fetchone.return_value = ("h",)
    monkeypatch.setattr(native_sync.psycopg, "connect", lambda *args, **kwargs: conn)
    monkeypatch.setattr(native_sync.read_pg, "_check_target", lambda *args: None)
    embed = Mock(side_effect=EmbeddingError("provider_failure", uncertain=uncertain))
    result = native_sync.sync("", target, index, config, embed, max_requests=10)
    assert result["requests_this_run"] == 1 and result["pending_chunks"] == 1
    assert embed.call_count == 1
    update = conn.execute.call_args_list[-1]
    assert update.args[1][0] == ("uncertain" if uncertain else "failed")


def test_native_search_message_compaction_keeps_all_scope_members():
    search = importlib.import_module("plugins.tools.corpus_search")
    hits = []
    for i in range(10):
        locators = [native_live.locator_for(f"b:body:{i}-{j}", "原文", []) for j in range(2)]
        hits.append(
            {
                "doc_id": "cv2:" + str(i) * 64,
                "locator": locators[0],
                "context_locators": locators,
                "scope_id": str(i),
                "fetch_plan": {"doc_id": "cv2:" + str(i) * 64, "locators": locators},
                "snippet": "检索预览" * 60,
            }
        )
    body = json.dumps(
        {"ok": True, "hits": hits, "coverage": {"native": {}}, "hint": "提示"}, ensure_ascii=False
    )
    # A nonempty diagnostic object matches the service contract.
    payload = json.loads(body)
    payload["coverage"]["native"] = {"policy": "native1"}
    fitted = json.loads(search.fit_search_payload(json.dumps(payload, ensure_ascii=False), 8000))
    assert fitted["ok"] and not fitted.get("hits_elided")
    assert [h["context_locators"] for h in fitted["hits"]] == [h["context_locators"] for h in hits]


def test_native_over_budget_drops_whole_hits_and_keeps_snippet_intact():
    """约束区不再把正文统一截到 120 字，而是整条命中让位并显式计数。"""
    search = importlib.import_module("plugins.tools.corpus_search")
    hits = []
    for i in range(8):
        locators = [native_live.locator_for(f"b:body:{i}-{j}", "原文", []) for j in range(6)]
        hits.append(
            {
                "doc_id": "cv2:" + str(i) * 64,
                "locator": locators[0],
                "source_id": str(i) * 64,
                "build_id": str(i) * 64,
                "chunk_id": f"b:body:{i}",
                "context_locators": locators,
                "scope_id": f"scope:{i}",
                "title": "光力科技：煤矿检测转型半导体划片机龙头",
                "published": "2026-09-06",
                "fetch_plan": {"doc_id": "cv2:" + str(i) * 64, "locators": locators},
                "snippet": "正" * 240,
            }
        )
    body = json.dumps(
        {"ok": True, "hits": hits, "coverage": {"native": {"policy": "native1"}}, "hint": "提示"},
        ensure_ascii=False,
    )

    fitted = json.loads(search.fit_search_payload(body, 6_000))

    assert fitted["ok"] is True
    assert fitted["hits_elided"] >= 1
    assert fitted["plans_compacted"] is True
    for hit in fitted["hits"]:
        assert len(hit["snippet"]) == 240  # 不再被截成 120 字残句
        assert hit["title"]  # 主体留在这条命中里
        assert "fetch_plan" not in hit  # locator 只保留一份
        assert len(hit["context_locators"]) == 6


def test_locator_carries_short_digest_and_old_handles_still_parse():
    span = {"unit_id": "u", "page": 1, "start": 3, "end": 5, "raw_sha256": "hash"}
    locator = native_live.locator_for("b:body:0001", "正文", [span])
    cid, expected = native_live.parse_locator(locator)
    assert cid == "b:body:0001"
    assert len(expected) == native_live.DIGEST_CHARS == 16

    # 已经发出的 64 位句柄必须继续可读（会话里可能仍持有旧值）。
    old_cid, old_expected = native_live.parse_locator("chunk:native1/b%3Abody%3A0001/" + "a" * 64)
    assert old_cid == "b:body:0001" and len(old_expected) == 64

    with pytest.raises(UnknownHandleError):
        native_live.parse_locator("chunk:native1/b%3Abody%3A0001/not-a-digest")


def test_digest_matches_accepts_prefix_only():
    full = "abcdef0123456789" + "f" * 48
    assert native_live.digest_matches(full[:16], full)
    assert native_live.digest_matches(full, full)
    assert not native_live.digest_matches("0" * 16, full)
    assert not native_live.digest_matches("", full)


def test_compose_snippet_labels_blocks_and_counts_hidden():
    from types import SimpleNamespace

    repeats = native_live.SNIPPET_BLOCK_CHARS // len("第一块正文 ") + 40
    blocks = [
        SimpleNamespace(text="第一块正文 " * repeats, slices=[SimpleNamespace(page=6)]),
        SimpleNamespace(text="第二块正文 " * repeats, slices=[SimpleNamespace(page=13)]),
        SimpleNamespace(text="第三块正文", slices=[SimpleNamespace(page=19)]),
    ]
    snippet = native_live.compose_snippet(blocks, 2)

    assert snippet.startswith("【1/3｜p6】")
    assert "【2/3｜p13】" in snippet
    assert "【3/3" not in snippet  # 只展示前两块
    assert "同源另有1块未展示" in snippet
    # 每段是独立前缀，不应把两块拼成一句连续正文
    assert snippet.count("句内节选，上下文不完整") == 2
    assert len(snippet) < 2 * native_live.SNIPPET_BLOCK_CHARS + 200


def test_compose_snippet_single_block_has_no_hidden_note():
    from types import SimpleNamespace

    snippet = native_live.compose_snippet(
        [SimpleNamespace(text="只有一个块", slices=[SimpleNamespace(page=1)])]
    )
    assert "未展示" not in snippet


def test_choose_snippet_blocks_uses_remaining_budget(monkeypatch):
    monkeypatch.setenv("CORPUS_NATIVE_SNIPPET_BLOCKS", "auto")
    # 单条命中、20 个块：正文预算充足 → 展示 3 块
    assert native_live.choose_snippet_blocks([20], 20 * 64) == 3
    # 更完整的段落预算下，5 条命中、昂贵句柄只能展示 1 块。
    assert native_live.choose_snippet_blocks([20] * 5, 7_000) == 1
    # 10 条命中×20 块：句柄已吃掉目标预算 → 至少保留 1 块
    assert native_live.choose_snippet_blocks([20] * 10, 200 * 64) == 1
    assert native_live.choose_snippet_blocks([], 0) == native_live.SNIPPET_BLOCKS


def test_compose_snippet_respects_explicit_limit():
    from types import SimpleNamespace

    blocks = [
        SimpleNamespace(text=f"第{i}块正文", slices=[SimpleNamespace(page=i)]) for i in range(1, 6)
    ]
    snippet = native_live.compose_snippet(blocks, 3)
    assert "【3/5｜p3】" in snippet
    assert "【4/5" not in snippet
    assert "同源另有2块未展示" in snippet


def test_choose_snippet_blocks_defaults_to_two(monkeypatch):
    monkeypatch.delenv("CORPUS_NATIVE_SNIPPET_BLOCKS", raising=False)
    assert native_live.choose_snippet_blocks([20], 1_280) == 2
    assert native_live.SNIPPET_BLOCKS == 2


def test_choose_snippet_blocks_env_override(monkeypatch):
    monkeypatch.setenv("CORPUS_NATIVE_SNIPPET_BLOCKS", "1")
    assert native_live.choose_snippet_blocks([20], 20 * 64) == 1
    monkeypatch.setenv("CORPUS_NATIVE_SNIPPET_BLOCKS", "3")
    assert native_live.choose_snippet_blocks([20] * 10, 200 * 64) == 3
    monkeypatch.setenv("CORPUS_NATIVE_SNIPPET_BLOCKS", "auto")
    assert native_live.choose_snippet_blocks([20], 1_280) == 3
    monkeypatch.setenv("CORPUS_NATIVE_SNIPPET_BLOCKS", "4")
    with pytest.raises(ValueError):
        native_live.choose_snippet_blocks([20], 0)


def test_compose_snippet_keeps_raw_whitespace_for_verbatim_copy():
    """展示文本里的空白必须与原文一致，否则复制出的引文无法逐字命中。"""
    from types import SimpleNamespace

    raw = "第一行数据\n  第二行缩进　全角空格"
    snippet = native_live.compose_snippet(
        [SimpleNamespace(text=raw, slices=[SimpleNamespace(page=1)])]
    )
    assert "\n" in snippet
    assert "　" in snippet
    assert raw.split("。")[0] in snippet


def test_search_forwards_pg_terms_without_reordering_handles(monkeypatch):
    from plugins.corpus.retrieval.native import NativeBlock, NativeResult, NativeSpan

    span = NativeSpan("unit:0001", 1, 0, 10, "hash")
    blocks = (
        NativeBlock("source", "b" * 64, "b:body:0001", None, "其他公司收入增长。", (span,)),
        NativeBlock("source", "b" * 64, "b:body:0002", None, "光力科技收入增长。", (span,)),
    )
    result = NativeResult(
        "光力科技收入",
        "index",
        blocks,
        20,
        16000,
        20,
        "2026-10-23",
        (),
        True,
        query_terms=("光力科技", "收入"),
    )
    index = SimpleNamespace(
        dates=[],
        vectors={},
        chunks=[
            {
                "build_id": b.build_id,
                "chunk_id": b.chunk_id,
                "kind": "body",
                "title_text": "公司材料",
                "input_hash": "",
            }
            for b in blocks
        ],
    )
    monkeypatch.setattr(native_live, "configured_seed", lambda _: index)
    monkeypatch.setattr(native_live, "refresh", lambda *_: index)
    monkeypatch.setattr(native_live, "search_native", lambda *_, **__: result)
    hits, _ = native_live.search("", "postgres", "光力科技收入", 10)
    expected = tuple(
        native_live.locator_for(
            b.chunk_id,
            b.text,
            [
                {
                    "unit_id": span.unit_id,
                    "page": span.page,
                    "start": span.start,
                    "end": span.end,
                    "raw_sha256": span.raw_sha256,
                }
            ],
        )
        for b in blocks
    )
    assert hits[0].context_locators == expected
    assert hits[0].locator == expected[0]
    assert hits[0].snippet.startswith("【2/2")
    assert "光力科技收入增长" in hits[0].snippet
