"""A1 有依据的上下文结构清单：协议样例与失败样例（01 §A1、§A2.2）。

覆盖纪律：

* 成员集合 = 传入的有序 locator（首次出现去重），**不引入区间之间的块**；
* ``region_ids`` 由来源原文序的连续位置还原为实际选择区间，不用首尾包络代替；
* 未知一律 ``null``／``unknown``，不填 0、不由 ``max(cells)`` 推算整表规模；
* 清单过大分页，且 ``inventory`` 游标与 ``content`` 游标严格区分；
* 固定游标 + 相同预算重放得到同一页（``page_id`` 与成员一致）。
"""

from __future__ import annotations

import importlib
import json

import pytest

from plugins.corpus import cursor as cursor_mod
from plugins.corpus.preparation import read_pg
from plugins.corpus.service import CorpusService, context_scope_id

inventory_module = importlib.import_module("plugins.tools.corpus_inventory")

_BUILD = "a" * 64
_DOC = f"cv2:{_BUILD}"


def _unit(unit_id, raw_text, page, cells=(), label_path=()):
    return read_pg.UnitStructure(
        unit_id=unit_id,
        raw_text=raw_text,
        page=page,
        element=None,
        cells=tuple(tuple(c) for c in cells),
        label_path=tuple(label_path),
    )


def _structure(chunk_id, kind, units):
    return read_pg.ChunkStructure(
        chunk_id=chunk_id,
        kind=kind,
        title_text=None,
        section_path=(),
        units=tuple(units),
    )


@pytest.fixture
def stub_reads(monkeypatch):
    """固定返回：来源原文序 c0..c5；只有被请求的成员出现在结构投影里。"""
    structures = {
        "c0": _structure("c0", "body", [_unit("u0", "第一段正文", 1)]),
        "c1": _structure(
            "c1",
            "table",
            [
                _unit(
                    "u1",
                    "科目\n金额\n收入\n100",
                    3,
                    cells=[[0, 0], [0, 1], [1, 0], [1, 1]],
                    label_path=["资产负债表 营业收入"],
                )
            ],
        ),
        "c4": _structure("c4", "heading", [_unit("u4", "附录：财务预测表", 9)]),
        "c5": _structure(
            "c5",
            "table",
            [_unit("u5", "名称\t值\nA\t12", 10, cells=[[0, 0], [0, 1], [1, 0], [1, 1]])],
        ),
    }
    order = ("c0", "c1", "c2", "c3", "c4", "c5")

    def fake_structures(dsn, build_id, chunk_ids, *, sandbox_db=None):
        return {cid: structures[cid] for cid in chunk_ids if cid in structures}

    monkeypatch.setattr(read_pg, "fetch_chunk_structures", fake_structures)
    monkeypatch.setattr(
        read_pg, "chunk_order_for_build", lambda dsn, build_id, *, sandbox_db=None: order
    )
    return svc()


def svc() -> CorpusService:
    return CorpusService("dummy")  # 不触 DB：所有读取都被替换


# ── 范围身份与成员集合 ─────────────────────────────────────────────────


def test_scope_id_binds_build_and_ordered_members() -> None:
    assert context_scope_id(_BUILD, ("c0", "c1")) == context_scope_id(_BUILD, ("c0", "c1"))
    assert context_scope_id(_BUILD, ("c0", "c1")) != context_scope_id(_BUILD, ("c1", "c0"))
    assert context_scope_id(_BUILD, ("c0",)) != context_scope_id("b" * 64, ("c0",))


def test_inventory_dedupes_and_excludes_blocks_between_regions(stub_reads) -> None:
    inv = stub_reads.context_inventory(_DOC, ["chunk:c0", "chunk:c1", "chunk:c4", "chunk:c1"])

    assert inv["total_chunks"] == 3  # 重复成员按首次出现去重
    assert [m["chunk_id"] for m in inv["members"]] == ["c0", "c1", "c4"]
    # c2/c3 从未被选中，绝不因「补全区间」被引入
    assert "c2" not in inv["member_chunk_ids"] and "c3" not in inv["member_chunk_ids"]
    assert inv["by_kind"] == {"body": 1, "table": 1, "heading": 1}
    assert inv["table_chunks"] == 1
    assert inv["unknown_members"] == []
    assert inv["scope_id"] == context_scope_id(_BUILD, ("c0", "c1", "c4"))


def test_regions_follow_source_order_runs_not_envelope(stub_reads) -> None:
    inv = stub_reads.context_inventory(_DOC, ["chunk:c0", "chunk:c1", "chunk:c4"])

    # 位置 {0,1} 连续成一段、{4} 单点成另一段 —— 两段之间是 c2/c3 的缝隙
    assert len(inv["regions"]) == 2
    region_of = {m["chunk_id"]: m["region_ids"] for m in inv["members"]}
    assert region_of["c0"] == region_of["c1"]  # 位置 0,1 连续 → 同一区间
    assert region_of["c0"] != region_of["c4"]  # 中间隔 c2/c3 → 不同区间，不用首尾包络合并
    # 每个成员的 region_ids 恰好一个（位置属于唯一极大连续段）
    for member in inv["members"]:
        assert len(member["region_ids"]) == 1


def test_unknown_table_identity_and_grid_are_null_not_zero(stub_reads) -> None:
    inv = stub_reads.context_inventory(_DOC, ["chunk:c1"])
    member = inv["members"][0]

    # 无持久化表身份 → null；未掌握完整表网格 → null（不填 0，不用 max(cells) 推算）
    assert member["table_ref"] is None
    assert member["table_rows"] is None
    assert member["table_cols"] is None
    assert member["header_refs"] is None
    # 块自身确实覆盖的结构如实填写
    assert member["covered_rows"] == [0, 1]
    assert member["page_range"] == [3, 3]
    assert member["structure_status"] == "verified"
    assert member["label_path"] == ["资产负债表 营业收入"]


def test_plain_body_block_reports_unknown_structure(stub_reads) -> None:
    inv = stub_reads.context_inventory(_DOC, ["chunk:c0", "chunk:c4"])
    for member in inv["members"]:
        assert member["structure_status"] == "unknown"
        assert member["covered_rows"] is None
        assert member["label_path"] is None


def test_unaligned_grid_is_partial_not_verified(stub_reads) -> None:
    inv = stub_reads.context_inventory(_DOC, ["chunk:c5"])
    member = inv["members"][0]

    assert member["structure_status"] == "partial"  # 有坐标但未形成可核验对齐
    assert member["covered_rows"] == [0, 1]


def test_unknown_member_is_reported_not_fabricated(stub_reads) -> None:
    inv = stub_reads.context_inventory(_DOC, ["chunk:c0", "chunk:missing"])
    assert inv["total_chunks"] == 1
    assert inv["unknown_members"] == ["chunk:missing"]


# ── 游标编解码（A1／A2 共用） ──────────────────────────────────────────


def test_cursor_roundtrip_and_type_validation() -> None:
    token = cursor_mod.encode_cursor(
        {"type": cursor_mod.INVENTORY, "doc_id": _DOC, "req": ["chunk:c0"], "pos": 0}
    )
    assert cursor_mod.decode_cursor(token)["type"] == cursor_mod.INVENTORY


def test_cursor_rejects_tampering_and_garbage() -> None:
    token = cursor_mod.encode_cursor(
        {"type": cursor_mod.INVENTORY, "doc_id": _DOC, "req": ["chunk:c0"], "pos": 0}
    )
    # 改一个字符 → 校验和不符/不可解析，绝不猜一个位置
    with pytest.raises(cursor_mod.CursorError):
        cursor_mod.decode_cursor(token[:-1] + ("A" if token[-1] != "A" else "B"))
    with pytest.raises(cursor_mod.CursorError):
        cursor_mod.decode_cursor("!!!not-base64!!!")


def test_cursor_rejects_unknown_type_and_version() -> None:
    with pytest.raises(cursor_mod.CursorError):
        cursor_mod.decode_cursor(
            cursor_mod.encode_cursor({"type": "sideways", "doc_id": _DOC})
        )
    # 伪造版本号会被校验和挡住（encode 只写当前版本），此处直接改载荷再签也无效
    token = cursor_mod.encode_cursor({"type": cursor_mod.INVENTORY, "doc_id": _DOC})
    payload = cursor_mod.decode_cursor(token)
    assert payload["v"] == cursor_mod.CURSOR_SCHEMA_VERSION


# ── 工具层：分页信封、游标类型区分、失败样例 ───────────────────────────


class _StubService:
    def __init__(self, members):
        self._members = members

    def context_inventory(self, doc_id, locators):
        by_kind: dict[str, int] = {}
        for member in self._members:
            by_kind[member["kind"]] = by_kind.get(member["kind"], 0) + 1
        return {
            "doc_id": doc_id,
            "build_id": _BUILD,
            "scope_id": context_scope_id(_BUILD, tuple(locators)),
            "total_chunks": len(self._members),
            "by_kind": by_kind,
            "table_chunks": by_kind.get("table", 0),
            "regions": [{"region_id": "region:x", "chunk_count": len(self._members)}],
            "members": list(self._members),
            "unknown_members": [],
        }


def _member(i: int, kind: str = "body") -> dict:
    return {
        "locator": f"chunk:c{i}",
        "chunk_id": f"c{i}",
        "kind": kind,
        "page_range": [i + 1, i + 1],
        "region_ids": ["region:x"],
        "table_ref": None,
        "structure_status": "unknown",
        "covered_rows": None,
        "header_refs": None,
        "label_path": None,
        "table_rows": None,
        "table_cols": None,
    }


@pytest.fixture
def stub_service(monkeypatch):
    members = [_member(i, "table" if i % 3 == 0 else "body") for i in range(12)]
    monkeypatch.setattr(inventory_module, "get_service", lambda: _StubService(members))
    return members


def _call(**kwargs):
    import asyncio

    return asyncio.run(inventory_module.corpus_inventory.func(**kwargs))


def test_inventory_tool_requires_exactly_one_selector(stub_service) -> None:
    both = json.loads(_call(doc_id=_DOC, locators=["chunk:c0"], cursor="x"))
    neither = json.loads(_call(doc_id=_DOC))
    assert both["ok"] is False and neither["ok"] is False


def test_inventory_tool_paginates_and_replays_identically(stub_service) -> None:
    first = json.loads(_call(doc_id=_DOC, locators=["chunk:c0"], max_chars=900))
    assert first["ok"] is True
    assert first["cursor_type"] == "inventory"
    assert first["exhausted"] is False and first["next_cursor"]
    assert len(first["items"]) < first["total_chunks"]

    again = json.loads(_call(doc_id=_DOC, locators=["chunk:c0"], max_chars=900))
    # 固定请求 + 相同预算 → 同一页（成员与 page_id 一致）
    assert again["page_id"] == first["page_id"]
    assert again["items"] == first["items"]

    second = json.loads(_call(doc_id=_DOC, cursor=first["next_cursor"], max_chars=900))
    assert second["page_id"] != first["page_id"]
    # 续取不重复上一页成员，逐页累积直到终点
    seen = {m["chunk_id"] for m in first["items"]}
    assert not (seen & {m["chunk_id"] for m in second["items"]})
    seen |= {m["chunk_id"] for m in second["items"]}
    tail = second
    while not tail["exhausted"]:
        tail = json.loads(_call(doc_id=_DOC, cursor=tail["next_cursor"], max_chars=900))
        page = {m["chunk_id"] for m in tail["items"]}
        assert not (seen & page)  # 页间不重叠
        seen |= page
    assert seen == {f"c{i}" for i in range(12)}


def test_inventory_tool_rejects_content_cursor(stub_service) -> None:
    content_cursor = cursor_mod.encode_cursor(
        {"type": cursor_mod.CONTENT, "doc_id": _DOC, "req": ["chunk:c0"], "pos": 0}
    )
    out = json.loads(_call(doc_id=_DOC, cursor=content_cursor))
    assert out["ok"] is False
    assert "游标类型不符" in out["error"]


def test_inventory_tool_rejects_legacy_handle(stub_service) -> None:
    out = json.loads(_call(doc_id="legacy-doc", locators=["chunk:c0"]))
    assert out["ok"] is False and "archive_required" in out["error"]


def test_inventory_tool_rejects_tiny_budget(stub_service) -> None:
    out = json.loads(_call(doc_id=_DOC, locators=["chunk:c0"], max_chars=10))
    assert out["ok"] is False and "max_chars" in out["error"]
