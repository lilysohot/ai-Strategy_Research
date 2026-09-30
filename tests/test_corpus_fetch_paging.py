"""A2 单一批量分页接口：页信封、分片、失败前进与游标可重放（01 §A2）。

覆盖纪律：

* ``locator``／``locators``／``cursor`` 恰选其一；单块装得下时**维持既有形状**；
* 批量／游标返回一致分页信封，键齐备；
* 正文块超限按边界分片、片间无缝无叠，拼回即整块；表格块只按完整行切；
* 最小原子单元仍超限 → ``unit_too_large``，不空转、不宣称取全；
* 单成员失败进 ``item_errors``／``unresolved``，其余成员照常返回；
* ``exhausted`` 与 ``fetch_complete`` 分离；固定游标 + 相同预算重放同一 ``page_id``；
* ``content`` 游标与 ``inventory`` 游标严格区分。
"""

from __future__ import annotations

import asyncio
import importlib
import json
from itertools import pairwise

import pytest

from plugins.corpus import cursor as cursor_mod
from plugins.corpus.preparation import read_pg
from plugins.corpus.service import emit_cells_from_units

fetch_module = importlib.import_module("plugins.tools.corpus_fetch")

_BUILD = "a" * 64
_DOC = f"cv2:{_BUILD}"

#: 页信封必含键（A2.2）。
_ENVELOPE_KEYS = {
    "ok",
    "schema_version",
    "cursor_type",
    "doc_id",
    "build_id",
    "scope_id",
    "view",
    "items",
    "item_errors",
    "next_cursor",
    "exhausted",
    "fetch_complete",
    "unresolved",
    "page_id",
}


def _evidence(chunk_id, kind, unit_specs):
    """按 (unit_id, raw_text, page, cells) 造一个真实 ChunkEvidence（text/spans 由 with_units 复算）。"""
    units = tuple(
        read_pg.UnitEvidence(
            unit_id=uid,
            raw_text=raw,
            page=page,
            element=None,
            cells=tuple(tuple(cell) for cell in cells),
        )
        for uid, raw, page, cells in unit_specs
    )
    base = read_pg.ChunkEvidence(
        source_id="src",
        build_id=_BUILD,
        chunk_id=chunk_id,
        kind=kind,
        title_text=None,
        section_path=(),
        units=(),
        text="",
        source_ranges=(),
        spans=(),
        active=True,
    )
    return read_pg.with_units(base, units)


class _StubService:
    def __init__(self, blocks, fail=()):
        self._blocks = blocks
        self._fail = set(fail)

    def fetch_verbatim(self, doc_id, locator):
        if locator in self._fail or locator not in self._blocks:
            raise read_pg.UnknownHandleError(f"句柄不存在: {locator}")
        return self._blocks[locator]

    def emit_cells(self, evidence):
        return emit_cells_from_units(evidence.units)

    def context_relations(self, doc_id, locators):
        # A3：分页契约测试不构造结构关联；工具按「仅角色」兜底。
        return {}


@pytest.fixture
def stub(monkeypatch):
    def install(blocks, fail=()):
        svc = _StubService(blocks, fail)
        monkeypatch.setattr(fetch_module, "get_service", lambda: svc)
        return svc

    return install


def _call(**kwargs):
    return asyncio.run(fetch_module.corpus_fetch.func(**kwargs))


# ── 入口与兼容性 ───────────────────────────────────────────────────────


def test_schema_keeps_selectors_optional() -> None:
    schema = fetch_module.corpus_fetch.parameters
    props = schema["properties"]
    assert schema.get("required") == ["doc_id"]
    for name in ("locator", "locators", "cursor", "view", "max_chars"):
        assert name in props
    assert props["max_chars"]["default"] == 6000


def test_requires_exactly_one_selector(stub) -> None:
    stub({"chunk:c0": _evidence("c0", "body", [("u0", "正文", 1, ())])})
    both = json.loads(_call(doc_id=_DOC, locator="chunk:c0", locators=["chunk:c0"]))
    none = json.loads(_call(doc_id=_DOC))
    assert both["ok"] is False and none["ok"] is False
    assert "恰选其一" in both["error"] and "恰选其一" in none["error"]


def test_single_block_small_keeps_legacy_shape(stub) -> None:
    stub({"chunk:c0": _evidence("c0", "body", [("u0", "石英股份产能 100 万吨", 3, ())])})
    out = json.loads(_call(doc_id=_DOC, locator="chunk:c0"))
    # 既有字段语义不变；不因 A2 多出信封键
    assert out["ok"] is True and out["text"] == "石英股份产能 100 万吨"
    assert out["chunk_id"] == "c0" and out["build_id"] == _BUILD
    assert "items" not in out and "next_cursor" not in out


def test_legacy_handle_rejected(stub) -> None:
    out = json.loads(_call(doc_id="legacy-doc", locator="chunk:c0"))
    assert out["ok"] is False and "archive_required" in out["error"]


# ── 批量模式：一致分页信封 ─────────────────────────────────────────────


def test_batch_returns_envelope_with_whole_blocks(stub) -> None:
    stub(
        {
            "chunk:c0": _evidence("c0", "body", [("u0", "第一段", 1, ())]),
            "chunk:c1": _evidence("c1", "heading", [("u1", "标题", 2, ())]),
        }
    )
    out = json.loads(
        _call(doc_id=_DOC, locators=["chunk:c0", "chunk:c0", "chunk:c1"], max_chars=4000)
    )
    assert set(out) >= _ENVELOPE_KEYS
    assert out["cursor_type"] == "content"
    assert [it["chunk_id"] for it in out["items"]] == ["c0", "c1"]  # 首次出现去重
    assert all(it["fragment"] is None for it in out["items"])
    assert out["exhausted"] is True and out["fetch_complete"] is True
    assert out["unresolved"] == [] and out["item_errors"] == []
    assert out["next_cursor"] is None


def test_fetch_returns_persisted_label_path_for_table_value_binding(stub) -> None:
    svc = stub({"chunk:t0": _evidence("t0", "table", [("u0", "R32\n99.6%", 10, ())])})
    svc.context_relations = lambda _doc_id, _locators: {
        "chunk:t0": {
            "content_role": "content",
            "relations": [],
            "relation_status": "unknown",
            "label_path": ["R32 价格分位", "R32 价差分位", "R32 开工率"],
        }
    }

    batch = json.loads(
        _call(doc_id=_DOC, locators=["chunk:t0"], view="compact", max_chars=4000)
    )
    single = json.loads(_call(doc_id=_DOC, locator="chunk:t0", view="compact"))

    expected = ["R32 价格分位", "R32 价差分位", "R32 开工率"]
    assert batch["items"][0]["label_path"] == expected
    assert single["label_path"] == expected


def test_batch_empty_list_rejected(stub) -> None:
    stub({})
    out = json.loads(_call(doc_id=_DOC, locators=[]))
    assert out["ok"] is False and "locators" in out["error"]


# ── 分片：正文块超限 ───────────────────────────────────────────────────


def test_single_oversize_fragments_tile_the_block(stub) -> None:
    text = "\n".join(f"第{i}段：确定性正文内容，用于分片测试。" for i in range(150))
    stub({"chunk:c0": _evidence("c0", "body", [("u0", text, 1, ())])})

    first = json.loads(_call(doc_id=_DOC, locator="chunk:c0", max_chars=2000))
    # 单块超限 → 显式分片为信封，不悄悄改写为「已取得全文」
    assert first["ok"] is True and first["cursor_type"] == "content"
    assert first["exhausted"] is False and first["next_cursor"]
    assert all(it["fragment"] is not None for it in first["items"])

    collected: list[str] = []
    frags: list[tuple[int, int]] = []
    page = first
    while True:
        for it in page["items"]:
            collected.append(it["text"])
            frags.append((it["fragment"]["start"], it["fragment"]["end"]))
            assert it["text_sha256"] == first["items"][0]["text_sha256"]
            assert it["text_chars"] == len(text)
        if page["exhausted"]:
            break
        page = json.loads(_call(doc_id=_DOC, cursor=page["next_cursor"], max_chars=2000))

    # 片间无缝、无叠，拼回即整块
    assert "".join(collected) == text
    for (_, prev_end), (next_start, _) in pairwise(frags):
        assert prev_end == next_start
    assert page["exhausted"] is True and page["fetch_complete"] is True


def test_fragments_never_cut_a_table_row(stub) -> None:
    rows = [f"科目{i}\t金额{i}\t单位{i}" for i in range(80)]
    text = "\n".join(rows)
    stub({"chunk:t0": _evidence("t0", "table", [("u0", text, 5, [[0, 0]])])})

    page = json.loads(_call(doc_id=_DOC, locator="chunk:t0", max_chars=2000))
    assert page["ok"] is True and page["items"]
    fragments: list[str] = []
    while True:
        fragments.extend(it["text"] for it in page["items"])
        if page["exhausted"]:
            break
        page = json.loads(_call(doc_id=_DOC, cursor=page["next_cursor"], max_chars=2000))
    # 拼回即整块；且除末片外都收在换行处 —— 绝不硬切半个单元格
    assert "".join(fragments) == text
    for frag in fragments[:-1]:
        assert frag.endswith("\n")


def test_atom_too_large_reports_error_and_resolves(stub) -> None:
    huge_row = "甲" * 5000  # 单个表格行本身超过片段预算
    stub({"chunk:t0": _evidence("t0", "table", [("u0", huge_row, 1, [[0, 0]])])})

    out = json.loads(_call(doc_id=_DOC, locator="chunk:t0", max_chars=2000))
    assert out["ok"] is False
    errors = {e["code"] for e in out["item_errors"]}
    assert "unit_too_large" in errors
    assert out["unresolved"] == ["chunk:t0"]
    # 遍历到终点但未取全 → exhausted True / fetch_complete False
    assert out["exhausted"] is True and out["fetch_complete"] is False


# ── 评审 S1：full 装不下原子行时先试 compact 再终止 ─────────────────────


def _long_row_table(rows: int = 6, row_len: int = 600):
    """多行长表格：行是原子，full 的固定字段吃掉正文预算时行装不下。"""
    specs = [
        (f"u{i}", f"指标{i}：" + "甲" * (row_len - 10), 1, ((i, 0),)) for i in range(rows)
    ]
    return _evidence("t0", "table", specs)


def test_full_view_atom_too_large_falls_back_to_compact(stub) -> None:
    """full 剩余正文预算 >0 但装不下原子行时，compact 释放的预算可能容纳
    ——预期 compact 回退成功取回，而不是在 full 上直接 unit_too_large（评审 S1）。"""
    stub({"chunk:t0": _long_row_table()})

    out = json.loads(_call(doc_id=_DOC, locator="chunk:t0", max_chars=2500))
    assert out["ok"] is True
    assert out["item_errors"] == [] and out["unresolved"] == []
    (item,) = out["items"]
    assert "甲" * 100 in item["text"]  # 原子行真的取回了
    assert item["view_fallback"] == "compact"
    assert out["next_cursor"]  # 一页装不下整块，续取正常


def test_unit_too_large_reports_after_all_views_tried(stub) -> None:
    """各视图均有正文预算但都装不下原子行才报 unit_too_large，并如实报告已试视图。"""
    stub({"chunk:t0": _long_row_table()})

    out = json.loads(_call(doc_id=_DOC, locator="chunk:t0", max_chars=2000))
    assert out["ok"] is False
    (err,) = out["item_errors"]
    assert err["code"] == "unit_too_large"
    assert err["needed_chars"] == 595
    assert err["views_tried"] == ["full", "compact"]
    assert out["unresolved"] == ["chunk:t0"]
    assert out["fetch_complete"] is False


# ── D3：固定字段超预算时自动回退 compact ───────────────────────────────


def _unit_heavy_evidence(units: int = 250):
    """单元清单很大、正文很小的一块：full 视图的 units 会独占预算。"""
    return _evidence("c0", "body", [(f"u{i}", "字", 1, ()) for i in range(units)])


def test_fixed_fields_over_budget_falls_back_to_compact(stub) -> None:
    """清单撑爆预算时自动改用 compact 视图取回正文，而不是报错让调用方自己领会。"""
    stub({"chunk:c0": _unit_heavy_evidence()})

    out = json.loads(_call(doc_id=_DOC, locator="chunk:c0", max_chars=6000))
    assert out["ok"] is True
    assert out["item_errors"] == [] and out["unresolved"] == []
    assert out["fetch_complete"] is True
    (item,) = out["items"]
    # 单元间以换行分隔，去掉分隔符即原文（正文真的取回了）
    assert item["text"].replace("\n", "") == "字" * 250
    assert item["view_fallback"] == "compact"  # 回退透明，但如实标注
    assert "units" not in item  # 正是被省去的固定字段


def test_fixed_fields_over_budget_error_names_an_executable_fallback(stub) -> None:
    """连 compact 都装不下时才报错，且提示必须是真能执行的退路。"""
    stub({"chunk:c0": _unit_heavy_evidence()})

    out = json.loads(_call(doc_id=_DOC, locator="chunk:c0", max_chars=1000))
    (err,) = out["item_errors"]
    assert err["code"] == "budget_exceeded"
    assert err["views_tried"] == ["full", "compact"]  # 回退已尝试过
    assert "提高 max_chars" in err["error"]  # 退路真的可执行
    assert "更小范围" not in err["error"]  # 不再给不可执行的建议
    assert out["unresolved"] == ["chunk:c0"]
    assert out["fetch_complete"] is False


# ── D2：分页信封保留整块证据（source_id／units／spans／semantic_cells）──


def _cell_table_evidence(rows: int = 7, pad: int = 200):
    """两列表格（表头行+标签列+长数值列）：块超限进信封，且 full 视图恰好整体承载
    block_evidence（含行/列证据）。数值用纯数字——含字母的值会让下方单元格的 col
    标签级联取上一行全文，单元格证据体积翻倍，full 档就装不下整块证据了。
    """
    specs = [("uh0", "指标", 5, ((0, 0),)), ("uh1", "2026E", 5, ((0, 1),))]
    for i in range(rows):
        specs.append((f"u{i:02d}a", f"指标{i}", 5, ((i + 1, 0),)))
        specs.append((f"u{i:02d}b", f"{i}.36" + "8" * pad, 5, ((i + 1, 1),)))
    return _evidence("t0", "table", specs)


def _walk_pages(doc_id: str, first: dict, **call_kwargs) -> list[dict]:
    pages, page = [first], first
    while not page["exhausted"]:
        page = json.loads(_call(doc_id=doc_id, cursor=page["next_cursor"], **call_kwargs))
        pages.append(page)
    return pages


def test_single_oversize_envelope_carries_block_evidence(stub) -> None:
    """单块超限转分页后，整块证据（units／spans／语义单元格）随信封返回且可拼回校验。"""
    stub({"chunk:t0": _cell_table_evidence()})

    first = json.loads(_call(doc_id=_DOC, locator="chunk:t0", max_chars=6000))
    pages = _walk_pages(_DOC, first, max_chars=6000)
    assert first["ok"] is True
    assert first["cursor_type"] == "content" and first["items"]  # 走的是信封路径
    text = "".join(it["text"] for page in pages for it in page["items"])
    for page in pages:
        ev = page["block_evidence"]
        assert ev["source_id"] == "src" and ev["chunk_id"] == "t0"
        assert all(u["page"] == 5 and "unit_id" in u for u in ev["units"])
        assert ev["spans"]
        for cell in ev["semantic_cells"]:
            assert set(cell) == {"unit_id", "page", "row", "col", "text"}
            assert cell["text"] in text  # 行／列证据可回溯到拼回的整块原文
    assert all(it["source_id"] == "src" for page in pages for it in page["items"])


def test_block_evidence_survives_paging_and_reassembles(stub) -> None:
    text = "\n".join(f"第{i}行：多页分片时整块证据仍随页携带。" for i in range(120))
    stub({"chunk:c0": _evidence("c0", "body", [("u0", text, 1, ())])})

    first = json.loads(_call(doc_id=_DOC, locator="chunk:c0", max_chars=2000))
    pages = _walk_pages(_DOC, first, max_chars=2000)
    assert len(pages) > 1
    text_sha = first["items"][0]["text_sha256"]
    collected = []
    for page in pages:
        ev = page["block_evidence"]
        assert ev["source_id"] == "src" and ev["chunk_id"] == "c0"
        assert ev["semantic_cells"] == []
        assert all(it["source_id"] == "src" for it in page["items"])
        collected.extend(it["text"] for it in page["items"])
        for it in page["items"]:
            assert it["text_sha256"] == text_sha and it["text_chars"] == len(text)
    assert "".join(collected) == text


def test_batch_envelope_has_no_block_evidence_but_items_keep_source_id(stub) -> None:
    stub(
        {
            "chunk:c0": _evidence("c0", "body", [("u0", "第一段正文", 1, ())]),
            "chunk:c1": _evidence("c1", "body", [("u1", "第二段正文", 2, ())]),
        }
    )
    out = json.loads(_call(doc_id=_DOC, locators=["chunk:c0", "chunk:c1"], max_chars=4000))
    assert "block_evidence" not in out  # 批量请求不附整块证据（按 locator 单独复取）
    assert all(it["source_id"] == "src" for it in out["items"])


def test_paging_envelope_never_exceeds_max_chars_despite_escapes(stub) -> None:
    """转义记账：多换行正文分片后，每页序列化长度都不得超出自身 max_chars。"""
    text = "\n".join(f"第{i}行：换行密集的正文，转义后长度大于原始字符数。" for i in range(120))
    stub({"chunk:c0": _evidence("c0", "body", [("u0", text, 1, ())])})

    first = json.loads(_call(doc_id=_DOC, locator="chunk:c0", max_chars=2000))
    raw_pages = [_call(doc_id=_DOC, locator="chunk:c0", max_chars=2000)]
    page = first
    while not page["exhausted"]:
        raw = _call(doc_id=_DOC, cursor=page["next_cursor"], max_chars=2000)
        raw_pages.append(raw)
        page = json.loads(raw)

    assert all(len(raw) <= 2000 for raw in raw_pages)
    assert (
        "".join(it["text"] for p in (json.loads(r) for r in raw_pages) for it in p["items"]) == text
    )


def test_compact_envelope_drops_block_evidence() -> None:
    envelope = {
        "ok": True,
        "items": [{"locator": "chunk:c0", "text": "正文", "units": [{"unit_id": "u0"}]}],
        "next_cursor": None,
        "block_evidence": {"source_id": "src", "units": [], "spans": [], "semantic_cells": []},
    }
    out = json.loads(fetch_module._compact_envelope(envelope))
    assert "block_evidence" not in out
    assert out["items"][0]["text"] == "正文"  # 正文与游标绝不丢
    assert "units" not in out["items"][0]


# ── 失败与前进性 ───────────────────────────────────────────────────────


def test_member_failure_is_reported_and_others_proceed(stub) -> None:
    stub(
        {
            "chunk:c0": _evidence("c0", "body", [("u0", "好的正文", 1, ())]),
            "chunk:c2": _evidence("c2", "body", [("u2", "后面的正文", 3, ())]),
        },
        fail={"chunk:c1"},
    )
    out = json.loads(
        _call(doc_id=_DOC, locators=["chunk:c0", "chunk:c1", "chunk:c2"], max_chars=4000)
    )
    assert [it["chunk_id"] for it in out["items"]] == ["c0", "c2"]  # 失败不阻断其他成员
    assert [e["locator"] for e in out["item_errors"]] == ["chunk:c1"]
    assert out["unresolved"] == ["chunk:c1"]
    assert out["exhausted"] is True and out["fetch_complete"] is False


def test_all_member_failures_are_explicit_tool_failure(stub) -> None:
    """A wrong build/locator pair must never look like an empty successful fetch."""
    stub({}, fail={"chunk:wrong"})

    out = json.loads(_call(doc_id=_DOC, locators=["chunk:wrong"], max_chars=4000))

    assert out["ok"] is False
    assert "没有成功取回" in out["error"]
    assert out["items"] == []
    assert out["unresolved"] == ["chunk:wrong"]
    assert out["fetch_complete"] is False


def test_empty_authority_content_is_not_reported_as_success(stub) -> None:
    """An existing chunk with empty authoritative text still needs remediation."""
    stub({"chunk:empty": _evidence("empty", "body", [("u0", "", 1, ())])})

    out = json.loads(_call(doc_id=_DOC, locator="chunk:empty", max_chars=4000))

    assert out["ok"] is False, json.dumps(out, ensure_ascii=False)
    assert "empty_content" in out["error"]
    assert out["doc_id"] == _DOC and out["locator"] == "chunk:empty"


def test_unresolved_carries_across_pages(stub) -> None:
    blocks = {
        f"chunk:c{i}": _evidence(f"c{i}", "body", [("u" + str(i), "正文" * 40, i + 1, ())])
        for i in range(6)
    }
    stub(blocks, fail={"chunk:c3"})

    page = json.loads(
        _call(doc_id=_DOC, locators=[f"chunk:c{i}" for i in range(6)], max_chars=2000)
    )
    while not page["exhausted"]:
        page = json.loads(_call(doc_id=_DOC, cursor=page["next_cursor"], max_chars=2000))
    # 失败成员在遍历结束后仍在 unresolved，fetch_complete 保持 False
    assert page["unresolved"] == ["chunk:c3"]
    assert page["fetch_complete"] is False


# ── 游标契约 ───────────────────────────────────────────────────────────


def test_cursor_replay_is_identical(stub) -> None:
    text = "\n".join(f"第{i}行：这是一段用于分页重放测试的确定性正文内容。" for i in range(80))
    stub({"chunk:c0": _evidence("c0", "body", [("u0", text, 1, ())])})

    first = json.loads(_call(doc_id=_DOC, locator="chunk:c0", max_chars=2000))
    again = json.loads(_call(doc_id=_DOC, locator="chunk:c0", max_chars=2000))
    assert first["page_id"] == again["page_id"]
    assert first["items"] == again["items"]

    # 固定游标 + 相同预算重放 → 同一页
    second = json.loads(_call(doc_id=_DOC, cursor=first["next_cursor"], max_chars=2000))
    second_again = json.loads(_call(doc_id=_DOC, cursor=first["next_cursor"], max_chars=2000))
    assert second["page_id"] == second_again["page_id"]
    assert second["items"] == second_again["items"]
    assert second["page_id"] != first["page_id"]


def test_cursor_binds_view_and_doc(stub) -> None:
    stub({"chunk:c0": _evidence("c0", "body", [("u0", "正文段落" * 1000, 1, ())])})
    first = json.loads(_call(doc_id=_DOC, locator="chunk:c0", max_chars=2000))
    # 游标模式忽略调用方的 view（以绑定为准），不因换 view 而改变分片契约
    out = json.loads(
        _call(doc_id=_DOC, cursor=first["next_cursor"], view="compact", max_chars=2000)
    )
    assert out["ok"] is True and out["view"] == "full"

    other_doc = "cv2:" + "b" * 64
    bad = json.loads(_call(doc_id=other_doc, cursor=first["next_cursor"], max_chars=2000))
    assert bad["ok"] is False and "doc_id" in bad["error"]


def test_rejects_inventory_cursor(stub) -> None:
    stub({"chunk:c0": _evidence("c0", "body", [("u0", "正文", 1, ())])})
    inventory_cursor = cursor_mod.encode_cursor(
        {"type": cursor_mod.INVENTORY, "doc_id": _DOC, "req": ["chunk:c0"], "pos": 0}
    )
    out = json.loads(_call(doc_id=_DOC, cursor=inventory_cursor))
    assert out["ok"] is False and "游标类型不符" in out["error"]


def test_rejects_tiny_budget(stub) -> None:
    stub({"chunk:c0": _evidence("c0", "body", [("u0", "正文", 1, ())])})
    out = json.loads(_call(doc_id=_DOC, locator="chunk:c0", max_chars=10))
    assert out["ok"] is False and "max_chars" in out["error"]
