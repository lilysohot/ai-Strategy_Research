"""A3 标题身份与可信内容关联：协议样例与失败样例（01 §A3）。

覆盖纪律：

* ``kind=heading`` → ``content_role="heading_only"``（只证明标题被取回，不含表体）；
* 关联是**列表**（允许一对多），每项含目标 locator／种类、关系类型、``verified``／
  ``candidate`` 状态与依据；候选与已确认严格分开；
* **不得**把「后面的第一张表」固定为 ``points_to``——标题对外关系一律 ``candidate``；
* 跨章节不越界；表题归属不唯一时降级为候选；无法判定 → ``relations=[]`` 且 ``unknown``；
* 同一套关联字段同时落到 ``corpus_inventory`` 成员与 ``corpus_fetch`` item。
"""

from __future__ import annotations

import asyncio
import importlib
import json

import pytest

from plugins.corpus.preparation import read_pg
from plugins.corpus.service import (
    CorpusService,
    StructuralMember,
    context_scope_id,
    structural_relation_fields,
)

fetch_module = importlib.import_module("plugins.tools.corpus_fetch")

_BUILD = "a" * 64
_DOC = f"cv2:{_BUILD}"


def _member(locator, kind, title_text=None, section_path=()):
    return StructuralMember(
        locator=locator,
        kind=kind,
        title_text=title_text,
        section_path=tuple(section_path),
    )


def _relations(fields, locator):
    return fields[locator]["relations"]


# ── 标题身份与同章节候选 ───────────────────────────────────────────────


def test_heading_is_heading_only_and_links_are_candidates_only() -> None:
    fields = structural_relation_fields(
        [
            _member("chunk:h1", "heading", None, ("附录：财务预测表",)),
            _member("chunk:t1", "table", "附录：财务预测表", ("附录：财务预测表",)),
        ]
    )

    head = fields["chunk:h1"]
    assert head["content_role"] == "heading_only"
    # 标题对外只有同章节候选，绝不出现 points_to 这类确定归属
    assert [r["relation"] for r in head["relations"]] == ["section_candidate"]
    assert head["relations"][0]["target_locator"] == "chunk:t1"
    assert head["relations"][0]["status"] == "candidate"
    assert head["relations"][0]["basis"] == "same_section"
    assert head["relation_status"] == "candidate"


def test_heading_without_same_section_member_is_unknown() -> None:
    fields = structural_relation_fields([_member("chunk:h1", "heading", None, ("X",))])
    assert fields["chunk:h1"]["content_role"] == "heading_only"
    assert fields["chunk:h1"]["relations"] == []
    assert fields["chunk:h1"]["relation_status"] == "unknown"


def test_heading_does_not_leak_across_sections() -> None:
    fields = structural_relation_fields(
        [
            _member("chunk:h1", "heading", None, ("研报",)),
            _member("chunk:h2", "heading", None, ("研报", "财务")),
            _member("chunk:t1", "table", "财务", ("研报", "财务")),
        ]
    )
    # 上层标题不能把子章节的表算成自己的候选
    assert fields["chunk:h1"]["relations"] == []
    assert fields["chunk:h1"]["relation_status"] == "unknown"
    assert [r["target_locator"] for r in fields["chunk:h2"]["relations"]] == ["chunk:t1"]


# ── 非标题成员：持久化结构树／表题归属（可核验） ───────────────────────


def test_table_links_owner_heading_and_caption_as_verified() -> None:
    fields = structural_relation_fields(
        [
            _member("chunk:h1", "heading", None, ("资产负债表",)),
            _member("chunk:t1", "table", "资产负债表", ("资产负债表",)),
        ]
    )
    table = fields["chunk:t1"]
    assert table["content_role"] == "content"
    kinds = {r["relation"]: r for r in table["relations"]}
    assert kinds["section_member"]["status"] == "verified"
    assert kinds["section_member"]["basis"] == "persisted_section_path"
    assert kinds["caption_of"]["status"] == "verified"
    assert kinds["caption_of"]["basis"] == "persisted_title_text"
    assert table["relation_status"] == "verified"


def test_ambiguous_caption_is_candidate_not_verified() -> None:
    fields = structural_relation_fields(
        [
            _member("chunk:h1", "heading", None, ("A",)),
            _member("chunk:h2", "heading", None, ("B", "A")),
            _member("chunk:t1", "table", "A", ("A",)),
        ]
    )
    captions = [r for r in _relations(fields, "chunk:t1") if r["relation"] == "caption_of"]
    assert len(captions) == 2  # 一对多：两个同名标题都列，但不冒充确定归属
    assert all(r["status"] == "candidate" for r in captions)
    assert all(r["basis"] == "persisted_title_text_ambiguous" for r in captions)


def test_caption_without_member_heading_is_candidate_without_target() -> None:
    fields = structural_relation_fields(
        [_member("chunk:t1", "table", "孤立表题", ("S",))]
    )
    table = fields["chunk:t1"]
    assert table["relations"][0]["target_locator"] is None  # 不猜目标块
    assert table["relations"][0]["target_heading"] == "孤立表题"
    assert table["relations"][0]["status"] == "candidate"
    assert table["relations"][0]["basis"] == "title_text_without_member_heading"


def test_body_without_any_basis_is_unknown() -> None:
    fields = structural_relation_fields([_member("chunk:b1", "body", None, ())])
    assert fields["chunk:b1"]["relations"] == []
    assert fields["chunk:b1"]["relation_status"] == "unknown"


# ── 服务层：context_relations 读结构范围 ────────────────────────────────


def _structure(chunk_id, kind, title_text=None, section_path=(), units=()):
    return read_pg.ChunkStructure(
        chunk_id=chunk_id,
        kind=kind,
        title_text=title_text,
        section_path=tuple(section_path),
        units=tuple(units),
    )


def test_context_relations_uses_scope_structures(monkeypatch) -> None:
    structures = {
        "h1": _structure("h1", "heading", section_path=("A",)),
        "t1": _structure("t1", "table", title_text="A", section_path=("A",)),
    }
    monkeypatch.setattr(
        read_pg,
        "fetch_chunk_structures",
        lambda dsn, build, cids, *, sandbox_db=None: {
            c: structures[c] for c in cids if c in structures
        },
    )
    svc = CorpusService("dummy")
    out = svc.context_relations(_DOC, ["chunk:h1", "chunk:t1"])
    assert out["chunk:h1"]["content_role"] == "heading_only"
    assert out["chunk:t1"]["relation_status"] == "verified"


def test_context_relations_degrades_to_empty_on_read_failure(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise read_pg.WithdrawnError("来源已撤销")

    monkeypatch.setattr(read_pg, "fetch_chunk_structures", boom)
    svc = CorpusService("dummy")
    # 关联是辅助信息：读失败不伪造，也绝不阻断正文取回
    assert svc.context_relations(_DOC, ["chunk:h1"]) == {}


# ── corpus_inventory 成员携带关联字段 ──────────────────────────────────


@pytest.fixture
def inventory_service(monkeypatch):
    structures = {
        "h1": _structure("h1", "heading", section_path=("资产负债表",)),
        "t1": _structure("t1", "table", title_text="资产负债表", section_path=("资产负债表",)),
        "b1": _structure("b1", "body", section_path=("资产负债表",)),
    }
    monkeypatch.setattr(
        read_pg,
        "fetch_chunk_structures",
        lambda dsn, build, cids, *, sandbox_db=None: {
            c: structures[c] for c in cids if c in structures
        },
    )
    monkeypatch.setattr(
        read_pg,
        "chunk_order_for_build",
        lambda dsn, build, *, sandbox_db=None: ("h1", "t1", "b1"),
    )
    return CorpusService("dummy")


def test_inventory_members_carry_content_role_and_relations(inventory_service) -> None:
    inv = inventory_service.context_inventory(
        _DOC, ["chunk:h1", "chunk:t1", "chunk:b1"]
    )
    by_id = {m["chunk_id"]: m for m in inv["members"]}

    assert by_id["h1"]["content_role"] == "heading_only"
    assert {r["target_locator"] for r in by_id["h1"]["relations"]} == {
        "chunk:t1",
        "chunk:b1",
    }
    assert all(r["relation"] == "section_candidate" for r in by_id["h1"]["relations"])
    assert by_id["t1"]["relation_status"] == "verified"
    assert by_id["b1"]["content_role"] == "content"


# ── corpus_fetch item 携带关联字段 ─────────────────────────────────────


def _evidence(chunk_id, kind, unit_specs):
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


class _FetchStub:
    def __init__(self, blocks, relations=None):
        self._blocks = blocks
        self._relations = relations or {}

    def fetch_verbatim(self, doc_id, locator):
        if locator not in self._blocks:
            raise read_pg.UnknownHandleError(f"句柄不存在: {locator}")
        return self._blocks[locator]

    def emit_cells(self, evidence):
        from plugins.corpus.service import emit_cells_from_units

        return emit_cells_from_units(evidence.units)

    def context_relations(self, doc_id, locators):
        return self._relations


def _call(**kwargs):
    return asyncio.run(fetch_module.corpus_fetch.func(**kwargs))


def test_fetch_single_heading_reports_heading_only(monkeypatch) -> None:
    blocks = {"chunk:h1": _evidence("h1", "heading", [("u1", "资产负债表", 1, ())])}
    monkeypatch.setattr(fetch_module, "get_service", lambda: _FetchStub(blocks))
    out = json.loads(_call(doc_id=_DOC, locator="chunk:h1"))
    assert out["content_role"] == "heading_only"
    assert out["relations"] == []
    assert out["relation_status"] == "unknown"


def test_fetch_batch_items_carry_scope_relations(monkeypatch) -> None:
    blocks = {
        "chunk:h1": _evidence("h1", "heading", [("u1", "资产负债表", 1, ())]),
        "chunk:t1": _evidence("t1", "table", [("u2", "科目\t金额", 2, ())]),
    }
    relations = {
        "chunk:h1": {
            "content_role": "heading_only",
            "relations": [
                {
                    "target_locator": "chunk:t1",
                    "target_kind": "table",
                    "relation": "section_candidate",
                    "status": "candidate",
                    "basis": "same_section",
                }
            ],
            "relation_status": "candidate",
        }
    }
    monkeypatch.setattr(
        fetch_module, "get_service", lambda: _FetchStub(blocks, relations)
    )
    out = json.loads(
        _call(doc_id=_DOC, locators=["chunk:h1", "chunk:t1"], max_chars=4000)
    )
    by_id = {it["chunk_id"]: it for it in out["items"]}
    assert by_id["h1"]["content_role"] == "heading_only"
    assert by_id["h1"]["relations"][0]["relation"] == "section_candidate"
    assert by_id["h1"]["relations"][0]["status"] == "candidate"
    # 范围外无关联的成员按「仅角色」兜底，不臆造关系
    assert by_id["t1"]["content_role"] == "content"
    assert by_id["t1"]["relation_status"] == "unknown"
    assert out["scope_id"] == context_scope_id(_BUILD, ("chunk:h1", "chunk:t1"))
