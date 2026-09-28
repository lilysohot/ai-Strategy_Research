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
    stub({f"chunk:c0": _evidence("c0", "body", [("u0", "正文", 1, ())])})
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
    assert _ENVELOPE_KEYS <= set(out)
    assert out["cursor_type"] == "content"
    assert [it["chunk_id"] for it in out["items"]] == ["c0", "c1"]  # 首次出现去重
    assert all(it["fragment"] is None for it in out["items"])
    assert out["exhausted"] is True and out["fetch_complete"] is True
    assert out["unresolved"] == [] and out["item_errors"] == []
    assert out["next_cursor"] is None


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
    for (_, prev_end), (next_start, _) in zip(frags, frags[1:]):
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
    assert out["ok"] is True
    errors = {e["code"] for e in out["item_errors"]}
    assert "unit_too_large" in errors
    assert out["unresolved"] == ["chunk:t0"]
    # 遍历到终点但未取全 → exhausted True / fetch_complete False
    assert out["exhausted"] is True and out["fetch_complete"] is False


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
    assert "units" not in item             # 正是被省去的固定字段


def test_fixed_fields_over_budget_error_names_an_executable_fallback(stub) -> None:
    """连 compact 都装不下时才报错，且提示必须是真能执行的退路。"""
    stub({"chunk:c0": _unit_heavy_evidence()})

    out = json.loads(_call(doc_id=_DOC, locator="chunk:c0", max_chars=1000))
    (err,) = out["item_errors"]
    assert err["code"] == "budget_exceeded"
    assert err["views_tried"] == ["full", "compact"]  # 回退已尝试过
    assert "提高 max_chars" in err["error"]           # 退路真的可执行
    assert "更小范围" not in err["error"]             # 不再给不可执行的建议
    assert out["unresolved"] == ["chunk:c0"]
    assert out["fetch_complete"] is False


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


def test_unresolved_carries_across_pages(stub) -> None:
    blocks = {
        f"chunk:c{i}": _evidence(
            f"c{i}", "body", [("u" + str(i), "正文" * 40, i + 1, ())]
        )
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
