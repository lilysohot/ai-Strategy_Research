"""议题 B 结构召回与排序：选择策略（I-B3）+ 结构重叠信号（I-B2）常驻测试。

对应票 01（selection.py）与票 02/03 的 rank 信号（search_pg.rank_hits）。
合成命中驱动，不构造真实 PG/模型客户端。

最终形态（i42 回测裁决）：**perdoc**——`selection.select_structural` 为产品落点
（文档序=词法，文档内按 (结构重叠, score) 重排）；`rank_hits` 的 structural
模式是 global 全池重排原语，仅在 i42 审计回测对照中使用，不作为产品选择路径。

band 区间（§10.5 选项 A 落产品）：`selection.select_band` 在**选择层**承载
"连续区间"（原票 03 `chunk.cover` 落点作废）；band_cap=8 是 I-B3 的带语义。
"""

from __future__ import annotations

import pytest

from plugins.corpus.preparation.contract import sha256_of_bytes
from plugins.corpus.preparation.cross_boundary import _merge_chunk
from plugins.corpus.preparation.read_pg import ChunkEvidence, UnitEvidence
from plugins.corpus.preparation.search_pg import SearchHit, rank_hits
from plugins.corpus.preparation.selection import (
    BandPolicy,
    SelectedBand,
    SelectionError,
    SelectionPolicy,
    select,
    select_band,
    select_structural,
)


def _ws_norm(s: str) -> str:
    """剥离全部空白，做引文包含判定（与 scorer 空白规约一致）。"""
    return "".join(ch for ch in s if not ch.isspace())


def _hit(
    source_id: str,
    build_id: str,
    score: float,
    *,
    chunk_id: str | None = None,
    label_path: tuple[str, ...] = (),
    page: int | None = None,
) -> SearchHit:
    return SearchHit(
        source_id=source_id,
        build_id=build_id,
        chunk_id=chunk_id or f"chunk-{source_id}-{score}",
        kind="table",
        title_text=None,
        section_path=(),
        unit_refs=("u1",),
        score=score,
        label_path=label_path,
        page=page,
    )


# --- I-B3：不调 cap ---


def test_cap_unchanged_by_this_work() -> None:
    """I-B3：max_chunks_per_document 保持 8（r39 预声明边界），显式断言。"""
    policy = SelectionPolicy()
    assert policy.top_k == 5
    assert policy.max_chunks_per_document == 8


def test_selection_policy_rejects_invalid_bounds() -> None:
    with pytest.raises(SelectionError):
        SelectionPolicy(top_k=0)
    with pytest.raises(SelectionError):
        SelectionPolicy(max_chunks_per_document=0)


def test_select_first_occurrence_top_k_and_per_document_caps() -> None:
    """前 top_k 来源各取 per_document 块；首个出现即确定来源排名。"""
    # 12 个 A 块 + 12 个 B 块 + 1 个 C 块（score 严格降序）
    ordered = (
        [_hit("A", "b1", 10.0 - i * 0.1, chunk_id=f"A{i}") for i in range(12)]
        + [_hit("B", "b1", 8.0 - i * 0.1, chunk_id=f"B{i}") for i in range(12)]
        + [_hit("C", "b1", 5.0, chunk_id="C0")]
    )
    selected = select(tuple(ordered), SelectionPolicy())
    # 来源数 = min(top_k=5, 实际来源 3) = 3；每来源 8 块
    from collections import Counter

    counts = Counter(hit.source_id for hit in selected)
    assert counts == {"A": 8, "B": 8, "C": 1}
    assert len(selected) == 17
    # 相对顺序保持 score 降序
    assert [hit.score for hit in selected] == sorted((hit.score for hit in selected), reverse=True)


def test_select_rejects_multiple_active_builds_per_source() -> None:
    hits = (
        _hit("A", "b1", 10.0, chunk_id="a0"),
        _hit("A", "b2", 9.0, chunk_id="a1"),
    )
    with pytest.raises(SelectionError):
        select(hits, SelectionPolicy())


# --- I-B2：结构重叠为主键的排序信号 ---


def test_structural_match_enters_selection() -> None:
    """I-B2：查询含行/列标签词时，对应 cell 块经结构信号进入选择范围。

    词法高分（score 8.5）的正文块无结构重叠；表格 cell 块结构重叠 ≥1 但词法
    score 低——结构信号下排序键 = (结构重叠数, score)，cell 块整体优先。
    """
    lexemes = ("尿素", "开工率", "89.9")
    hits = (
        _hit("A", "b1", 8.5, chunk_id="prose", label_path=()),
        _hit("A", "b1", 1.2, chunk_id="cell", label_path=("尿素 开工率",)),
    )
    ranked = rank_hits(hits, lexemes=lexemes, signals=("lexical", "structural"))
    assert ranked[0].chunk_id == "cell"  # 结构命中进入首位
    # 经选择策略后仍在选择范围内
    selected = select(ranked, SelectionPolicy())
    assert "cell" in {hit.chunk_id for hit in selected}


def test_rank_hits_default_signal_is_byte_identical() -> None:
    """默认 signals=("lexical",) 与现状逐字节一致：原序原样返回。"""
    hits = (
        _hit("A", "b1", 3.0, chunk_id="a"),
        _hit("A", "b1", 9.0, chunk_id="b"),
    )
    assert rank_hits(hits) == hits


def test_structural_overlap_dedup_does_not_magnify_repeats() -> None:
    """结构重叠数 = 去重命中数：重复词元/重复标签不放大。"""
    lexemes = ("尿素", "开工率")
    dup = _hit("A", "b1", 1.0, chunk_id="dup", label_path=("尿素 开工率", "尿素 开工率"))
    single = _hit("A", "b1", 1.0, chunk_id="single", label_path=("尿素 开工率",))
    other = _hit("B", "b1", 2.0, chunk_id="other")  # 词法分更高但无结构标签
    ranked = rank_hits((dup, single, other), lexemes=lexemes, signals=("structural",))
    # dup 与 single 去重后结构重叠数相同 → 保持稳定原序；other 无结构命中排后
    assert [hit.chunk_id for hit in ranked] == ["dup", "single", "other"]


def test_rank_hits_structural_tie_breaks_by_score() -> None:
    """同结构重叠数时按 score 降序（稳定、可预期）。"""
    lexemes = ("纯碱",)
    hits = (
        _hit("A", "b1", 4.0, chunk_id="low", label_path=("纯碱",)),
        _hit("A", "b1", 9.0, chunk_id="high", label_path=("纯碱",)),
    )
    ranked = rank_hits(hits, lexemes=lexemes, signals=("structural",))
    assert [hit.chunk_id for hit in ranked] == ["high", "low"]


# --- I-B2 产品落点：perdoc（i42 裁决） ---


def test_select_structural_promotes_cell_within_doc() -> None:
    """I-B2（perdoc 形态）：同一文档内，结构命中的 cell 块进入该文档前 N 块。

    词法高分（score 8.5）的正文块无结构重叠；表格 cell 块结构重叠 ≥1 但词法
    score 低——文档内按 (结构重叠数, score) 重排后 cell 块整体优先。
    """
    lexemes = ("尿素", "开工率", "89.9")
    hits = (
        _hit("A", "b1", 8.5, chunk_id="prose", label_path=()),
        _hit("A", "b1", 1.2, chunk_id="cell", label_path=("尿素 开工率",)),
    )
    selected = select_structural(hits, SelectionPolicy(), lexemes=lexemes)
    chunks = [hit.chunk_id for hit in selected]
    assert chunks.index("cell") < chunks.index("prose")


def test_select_structural_keeps_lexical_doc_order() -> None:
    """perdoc 不跨文档重排：文档序 = 词法首次出现（与 select 一致）。

    B 文档（词法首次出现靠前）不得被 A 文档的结构命中块挤到后面——
    这是 global 全池重排的缺陷（company-008 茅台落出 top-5），perdoc 规避。
    """
    lexemes = ("尿素", "开工率")
    hits = (
        _hit("B", "b1", 9.0, chunk_id="b_prose", label_path=()),  # 词法先行文档
        _hit("B", "b1", 8.0, chunk_id="b_more", label_path=()),
        _hit("A", "b1", 1.0, chunk_id="a_cell", label_path=("尿素 开工率",)),
        _hit("A", "b1", 0.9, chunk_id="a_cell2", label_path=("尿素 开工率",)),
    )
    selected = select_structural(hits, SelectionPolicy(), lexemes=lexemes)
    order = [hit.source_id for hit in selected]
    # 文档序 B 在前（词法首次出现）；A 的结构命中块只在 A 内部优先
    assert order.index("B") < order.index("A")
    assert [hit.chunk_id for hit in selected][:2] == ["b_prose", "b_more"]


def test_select_structural_empty_lexemes_falls_back_to_select() -> None:
    """lexemes 为空退化为纯词法 select（行为逐字节一致）。"""
    hits = (
        _hit("A", "b1", 3.0, chunk_id="a"),
        _hit("B", "b1", 9.0, chunk_id="b"),
    )
    assert select_structural(hits, SelectionPolicy(), lexemes=()) == select(hits, SelectionPolicy())


def test_select_structural_rejects_multiple_active_builds() -> None:
    """同源多 build 混用 fail-closed（与 select 同判据）。"""
    hits = (
        _hit("A", "b1", 10.0, chunk_id="a0"),
        _hit("A", "b2", 9.0, chunk_id="a1"),
    )
    with pytest.raises(SelectionError):
        select_structural(hits, SelectionPolicy(), lexemes=("尿素",))


# --- band 区间落产品（§10.5 选项 A，原票 03 chunk.cover 落点作废） ---


def test_band_policy_defaults_preserve_cap_eight() -> None:
    """I-B3（band 语义）：band_cap 默认 8（不调 cap 值，8 从块数改为带数）。"""
    band = BandPolicy()
    assert band.gap == 1
    assert band.expand == 1
    assert band.band_cap == 8
    assert band.pool_cap == 24
    assert band.provable_width_bound == 49  # (24-1)*(1+1)+1+2*1


def test_band_policy_rejects_invalid_bounds() -> None:
    with pytest.raises(SelectionError):
        BandPolicy(gap=-1)
    with pytest.raises(SelectionError):
        BandPolicy(expand=-1)
    with pytest.raises(SelectionError):
        BandPolicy(band_cap=0)
    with pytest.raises(SelectionError):
        BandPolicy(pool_cap=0)


def test_select_band_covers_consecutive_interval() -> None:
    """I-A2（band 语义）：命中块聚簇成带，带覆盖原文序连续闭区间 [start, end]。

    池块位置 [4, 5] 相邻（gap=1），expand=1 → 带 [3, 6]；带内全部块 id
    由调用方按原文序装配（本模块不做 IO，只返回区间）。
    """
    chunk_order = ("c0", "c1", "c2", "c3", "c4", "c5", "c6", "c7")
    hits = (
        _hit("A", "b1", 1.0, chunk_id="c4"),
        _hit("A", "b1", 2.0, chunk_id="c5"),
    )
    bands = select_band(
        hits, SelectionPolicy(), BandPolicy(), chunk_order_by_source={"A": chunk_order}
    )
    assert len(bands) == 1
    band = bands[0]
    assert isinstance(band, SelectedBand)
    assert (band.start, band.end) == (3, 6)  # expand=1 两端各扩展一块
    assert band.width == 4
    assert band.pool == (4, 5)
    assert band.score == 2.0  # 带分 = 簇内最大 ts_rank


def test_select_band_gap_splits_clusters() -> None:
    """间隔 > gap 的命中块分属不同带（gap=1：间隔 2 块即断簇）。"""
    chunk_order = tuple(f"c{i}" for i in range(10))
    hits = (
        _hit("A", "b1", 1.0, chunk_id="c1"),
        _hit("A", "b1", 2.0, chunk_id="c4"),  # 4-1-1 = 2 > gap=1 → 断簇
    )
    bands = select_band(
        hits, SelectionPolicy(), BandPolicy(), chunk_order_by_source={"A": chunk_order}
    )
    # 带序 = (带分降序, 带起点升序)：c4 分更高排前
    assert [b.pool for b in bands] == [(4,), (1,)]


def test_select_band_dedup_repeat_hits_per_position() -> None:
    """多个命中投影到同一原文位置时去重（不放大带内池块数）。"""
    chunk_order = tuple(f"c{i}" for i in range(8))
    hits = (
        _hit("A", "b1", 1.0, chunk_id="c3"),
        _hit("A", "b1", 0.5, chunk_id="c3"),
    )
    bands = select_band(
        hits, SelectionPolicy(), BandPolicy(), chunk_order_by_source={"A": chunk_order}
    )
    assert len(bands) == 1
    assert bands[0].pool == (3,)


def test_select_band_cap_split_exceeds_pool_cap() -> None:
    """带内池块数 > pool_cap 时按池块锚拆子带（方案 C）。"""
    pool_cap = 3
    n = 30
    chunk_order = tuple(f"c{i}" for i in range(n))
    pool_positions = [2, 3, 4, 10, 11, 12, 13]  # 两簇，第二簇 4 块 > pool_cap=3
    hits = tuple(_hit("A", "b1", float(p), chunk_id=f"c{p}") for p in pool_positions)
    bands = select_band(
        hits,
        SelectionPolicy(),
        BandPolicy(gap=1, expand=1, pool_cap=pool_cap),
        chunk_order_by_source={"A": chunk_order},
    )
    # 带序 = (带分降序, 带起点升序)：第二簇拆带 (13,)/(10,11,12) 分高在前，第一簇 (2,3,4) 最后
    assert len(bands) == 3
    assert bands[0].pool == (13,)
    assert bands[1].pool == (10, 11, 12)
    assert bands[2].pool == (2, 3, 4)
    # 拆带后每个子带宽度仍 ≤ 可证带宽上界
    bound = (pool_cap - 1) * (1 + 1) + 1 + 2 * 1
    for band in bands:
        assert band.width <= bound


def test_select_band_width_within_provable_bound() -> None:
    """I-A3（band 语义）：任一选中带宽度 ≤ 可证带宽上界。"""
    band = BandPolicy(gap=2, expand=1, pool_cap=5)
    n = 60
    chunk_order = tuple(f"c{i}" for i in range(n))
    hits = tuple(_hit("A", "b1", float(i), chunk_id=f"c{i}") for i in range(0, n, 2))
    bands = select_band(hits, SelectionPolicy(), band, chunk_order_by_source={"A": chunk_order})
    assert bands
    for b in bands:
        assert b.width <= band.provable_width_bound


def test_select_band_doc_order_first_occurrence_and_band_cap() -> None:
    """文档序 = 词法首次出现（与 select 一致）；每文档取前 band_cap 个带。"""
    chunk_order_a = tuple(f"a{i}" for i in range(12))
    chunk_order_b = tuple(f"b{i}" for i in range(12))
    hits = (
        _hit("B", "b1", 9.0, chunk_id="b5"),
        _hit("B", "b1", 8.0, chunk_id="b6"),
        _hit("A", "b1", 1.0, chunk_id="a5"),
        _hit("A", "b1", 0.9, chunk_id="a6"),
    )
    bands = select_band(
        hits,
        SelectionPolicy(),
        BandPolicy(),
        chunk_order_by_source={"A": chunk_order_a, "B": chunk_order_b},
    )
    sources = [b.source_id for b in bands]
    assert sources.index("B") < sources.index("A")  # B 词法先行
    # 每文档单簇单带；band_cap=8 不截断此处（簇数 < 8）
    assert len(bands) == 2


def test_select_band_missing_chunk_order_fails_closed() -> None:
    """缺来源原文序清单 → fail-closed。"""
    hits = (_hit("A", "b1", 1.0, chunk_id="c0"),)
    with pytest.raises(SelectionError):
        select_band(hits, SelectionPolicy(), BandPolicy(), chunk_order_by_source={})


def test_select_band_hit_outside_order_fails_closed() -> None:
    """命中块不在原文序清单 → fail-closed（不静默丢块）。"""
    chunk_order = ("c0", "c1")
    hits = (_hit("A", "b1", 1.0, chunk_id="ghost"),)
    with pytest.raises(SelectionError):
        select_band(hits, SelectionPolicy(), BandPolicy(), chunk_order_by_source={"A": chunk_order})


def test_select_band_rejects_multiple_active_builds() -> None:
    """同源多 build 混用 fail-closed（与 select 同判据）。"""
    hits = (
        _hit("A", "b1", 10.0, chunk_id="c0"),
        _hit("A", "b2", 9.0, chunk_id="c1"),
    )
    with pytest.raises(SelectionError):
        select_band(
            hits, SelectionPolicy(), BandPolicy(), chunk_order_by_source={"A": ("c0", "c1")}
        )


def test_select_band_deterministic_and_stable_order() -> None:
    """确定性：同输入两次运行逐字段一致；带序按 (带分降序, 带起点升序)。"""
    chunk_order = tuple(f"c{i}" for i in range(20))
    hits = (
        _hit("A", "b1", 1.0, chunk_id="c3"),
        _hit("A", "b1", 9.0, chunk_id="c10"),
        _hit("A", "b1", 5.0, chunk_id="c16"),
    )
    first = select_band(
        hits, SelectionPolicy(), BandPolicy(), chunk_order_by_source={"A": chunk_order}
    )
    second = select_band(
        hits, SelectionPolicy(), BandPolicy(), chunk_order_by_source={"A": chunk_order}
    )
    assert first == second
    assert [b.score for b in first] == [9.0, 5.0, 1.0]


# --- band 落产品读取路径（F2）：同快照带宽不变式 + cell 派生只读 ---


def test_band_doc_set_matches_select_same_snapshot() -> None:
    """I-BAND-1：同一快照下 select_band 与 select 选中文档集一致。

    band 仅改变块/带的选择形态与排序，不得新增或丢失来源文档——文档序=词法首次
    出现，``band_cap=8`` 高于任何单源簇数，故来源集合与 perdoc ``select`` 逐字节
    一致。``chunk_order_by_source`` 为同快照原文序（按每 chunk 引用单元最小 ordinal
    升序），两端可证带宽上界一致。
    """
    chunk_order_a = tuple(f"a{i}" for i in range(24))
    chunk_order_b = tuple(f"b{i}" for i in range(24))
    hits = (
        _hit("B", "b1", 9.0, chunk_id="b5"),  # B 词法先行
        _hit("B", "b1", 8.0, chunk_id="b6"),
        _hit("A", "b1", 1.0, chunk_id="a15"),
        _hit("A", "b1", 0.9, chunk_id="a16"),
    )
    selected_docs = {h.source_id for h in select(hits, SelectionPolicy())}
    bands = select_band(
        hits,
        SelectionPolicy(),
        BandPolicy(),
        chunk_order_by_source={"A": chunk_order_a, "B": chunk_order_b},
    )
    band_docs = {b.source_id for b in bands}
    assert band_docs == selected_docs == {"A", "B"}
    # 来源序 = 词法首次出现（B 先行）；文档内带按 (带分降序) 排列
    assert [b.source_id for b in bands] == ["B", "A"]
    # 同快照原文序全量覆盖：每来源命中块位都在其原文序清单内且解析为真实命中块
    hit_chunks = {h.chunk_id for h in hits}
    for b in bands:
        order = {"A": chunk_order_a, "B": chunk_order_b}[b.source_id]
        for pos in b.pool:
            assert order[pos] in hit_chunks  # 原文序位置落到命中块 id


def test_band_every_band_width_within_provable_bound_49() -> None:
    """I-BAND-2：默认参数下任一选中带宽 ≤ 可证带宽上界 49。

    ``provable_width_bound=(pool_cap-1)*(gap+1)+1+2*expand = 49``，是 §10.5 选项 A
    的硬上界（回测实测最大带宽 33）；带宽既有下限保护（+expand 两头）又不会越界。
    """
    band = BandPolicy()
    n = 120
    chunk_order = tuple(f"c{i}" for i in range(n))
    hits = tuple(_hit("A", "b1", float(i), chunk_id=f"c{i}") for i in range(0, n, 2))
    bands = select_band(hits, SelectionPolicy(), band, chunk_order_by_source={"A": chunk_order})
    assert bands
    for b in bands:
        assert b.width <= band.provable_width_bound
        assert b.width <= 49
    assert max(b.width for b in bands) <= 49


def test_band_merges_sparse_hits_on_same_page_within_width_bound() -> None:
    """A PDF page is one evidence region even when several nonmatching chunks separate its hits."""
    order = tuple(f"c{i}" for i in range(20))
    hits = (
        _hit("A", "b1", 2.0, chunk_id="c2", page=7),
        _hit("A", "b1", 1.0, chunk_id="c12", page=7),
    )
    bands = select_band(hits, SelectionPolicy(), BandPolicy(), chunk_order_by_source={"A": order})
    assert len(bands) == 1
    assert bands[0].start == 1
    assert bands[0].end == 13


def test_band_does_not_merge_sparse_hits_from_different_pages() -> None:
    order = tuple(f"c{i}" for i in range(20))
    hits = (
        _hit("A", "b1", 2.0, chunk_id="c2", page=7),
        _hit("A", "b1", 1.0, chunk_id="c12", page=8),
    )
    bands = select_band(hits, SelectionPolicy(), BandPolicy(), chunk_order_by_source={"A": order})
    assert len(bands) == 2


def test_product_context_selection_returns_one_bounded_anchor_per_source() -> None:
    from plugins.corpus.service import CorpusService

    svc = CorpusService("dummy")
    hits = (
        _hit("A", "ba", 5.0, chunk_id="a2", page=1),
        _hit("B", "bb", 4.0, chunk_id="b1", page=3),
        _hit("A", "ba", 3.0, chunk_id="a5", page=1),
    )
    selected = svc._selected_context_hits(
        hits,
        {"A": tuple(f"a{i}" for i in range(8)), "B": tuple(f"b{i}" for i in range(4))},
        10,
    )
    assert [hit.source_id for hit in selected] == ["A", "B"]
    assert selected[0].chunk_id == "a2"
    assert selected[0].context_chunk_ids == tuple(f"a{i}" for i in range(1, 7))
    assert selected[1].context_chunk_ids == ("b0", "b1", "b2")


def test_emit_cells_derives_row_col_on_aligned_grid_only() -> None:
    """I-CELL-1：cell 证据只对选中带内对齐表单元派生，不改变块选择。

    网格行/列标签派生规则：``raw_text.split("\\n")`` 长度 == ``cells`` 数才入格；
    row = 同行左侧最近含字母单元、col = 同列上方最近含字母单元，二者都派生成功才发射。
    数字格子无这两种标签之一即诚实失败；切分不对齐的单元整块不入格。派生是纯函数，
    不改动输入块（冻结 dataclass），也不触及任何选择路径。
    """
    from plugins.corpus.preparation.read_pg import ChunkEvidence, UnitEvidence
    from plugins.corpus.service import CorpusService

    svc = CorpusService("dummy")  # 不触 DB：_emit_cells 只对传入 chunk 派生

    def unit(
        uid: str, text: str, cells: tuple[tuple[int, ...], ...], *, page: int | None = 1
    ) -> UnitEvidence:
        return UnitEvidence(unit_id=uid, raw_text=text, page=page, element="table", cells=cells)

    # 对齐 2x2 网格 + 一个切分不对齐的单元 + 一个纯数字但缺行标签的单元
    u_header = unit("u-h", "每股收益\n2025E", ((0, 0), (0, 1)))
    u_row = unit("u-r", "营业总收入\n84,679", ((1, 0), (1, 1)))
    u_unaligned = unit("u-ua", "甲\n乙\n丙", ((0, 2), (0, 3)))  # 3 行 vs 2 cells → 不入格
    u_pagenone = unit("u-pg", "营业收入\n12.5", ((2, 0), (2, 1)), page=None)  # 无 page → 跳过

    chunk = ChunkEvidence(
        source_id="S1",
        build_id="b1",
        chunk_id="c0",
        kind="table",
        title_text=None,
        section_path=(),
        units=(u_header, u_row, u_unaligned, u_pagenone),
        text="每股收益\n2025E\n营业总收入\n84,679",
        source_ranges=((0, 40),),
        spans=(("u-h", 0, 6), ("u-r", 7, 20)),
        active=True,
    )
    emitted = svc._emit_cells(chunk)

    # 唯一可发射格：(1,1)= "84,679"（row=营业总收入 / col=2025E）
    assert len(emitted) == 1
    cell = emitted[0]
    assert cell.unit_id == "u-r"
    assert cell.page == 1
    assert cell.row == "营业总收入"
    assert cell.col == "2025E"
    assert cell.text == "84,679"
    # 派生不改写输入块（冻结 dataclass，字段仍为原值）
    assert chunk.units == (u_header, u_row, u_unaligned, u_pagenone)


# --- F4：跨 NOISE/kept 边界联合取证（I-ATT-1 反例） ---


def _chunk_with_rating() -> ChunkEvidence:
    """伪单元对：kept 评级行 u-rating（ord6）+ NOISE 表头 u-title（ord5），同页同水平带。"""
    rating = UnitEvidence(
        unit_id="u-rating", raw_text="强推（维持）", page=1, element="paragraph", cells=()
    )
    return ChunkEvidence(
        source_id="S1",
        build_id="b1",
        chunk_id="c0",
        kind="paragraph",
        title_text=None,
        section_path=(),
        units=(rating,),
        text="强推（维持）",
        source_ranges=((0, 10),),
        spans=(("u-rating", 0, 6)),
        active=True,
    )


def test_cross_boundary_aggregates_noise_header_into_full_quote() -> None:
    """I-ATT-1：引文横跨 NOISE/kept 时，联合取证取到完整引文且标题序在评级前。

    a-1 反例：前半「贵州茅台（600519）2026 年中报点评」在 NOISE 表头（ord5），
    后半「强推（维持）」在 kept 评级单元（ord6）。同页 + bbox 垂直重叠 ⇒ 表头按
    ordinal 保序聚合进块证据，取证路径不静默丢半条。
    """
    kept = {
        "u-rating": (
            6,
            "强推（维持）",
            {"page": 1, "bbox": (0, 80, 500, 120)},
            sha256_of_bytes(("强推（维持）").encode()),
            ("heading_by_font_size",),
        ),
    }
    noise = {
        "u-title": (
            5,
            "贵州茅台（600519）2026 年中报点评",
            {"page": 1, "bbox": (0, 40, 500, 110)},
            sha256_of_bytes(("贵州茅台（600519）2026 年中报点评").encode()),
            ("header_repeated_geometric", "heading_by_font_size"),
        ),
    }
    merged = _merge_chunk(_chunk_with_rating(), kept, noise)
    full = _ws_norm(merged.text)
    assert "贵州茅台（600519）2026年中报点评" in full
    assert "强推（维持）" in full
    # 序正确：标题（ord5）位于评级（ord6）之前
    assert full.index("贵州茅台（600519）") < full.index("强推（维持）")

    # spans 自洽：按 (uid, start, end) 重建（单元间 "\n" 分隔）逐字节还原 text
    rebuilt = ""
    for i, (_uid, start, end) in enumerate(merged.spans):
        if i:
            rebuilt += "\n"
        rebuilt += merged.text[start:end]
    assert rebuilt == merged.text


def test_cross_boundary_ignores_different_page_and_no_y_overlap() -> None:
    """I-ATT-1 反向：不同页或 y 不重叠的 NOISE 不聚合，保持逐字块。"""
    ev = _chunk_with_rating()
    kept = {
        "u-rating": (
            6,
            "强推（维持）",
            {"page": 1, "bbox": (0, 80, 500, 120)},
            sha256_of_bytes(("强推（维持）").encode()),
            (),
        )
    }
    noise_other_page = {
        "u-title": (
            5,
            "贵州茅台（600519）2026 年中报点评",
            {"page": 2, "bbox": (0, 40, 500, 110)},
            sha256_of_bytes(("贵州茅台（600519）2026 年中报点评").encode()),
            ("header_repeated_geometric",),
        ),
    }
    assert _merge_chunk(ev, kept, noise_other_page) is ev  # 不同页 → 原样

    noise_no_overlap = {
        "u-title": (
            5,
            "贵州茅台（600519）2026 年中报点评",
            {"page": 1, "bbox": (0, 300, 500, 340)},
            sha256_of_bytes(("贵州茅台（600519）2026 年中报点评").encode()),
            ("header_repeated_geometric",),
        ),
    }
    assert _merge_chunk(ev, kept, noise_no_overlap) is ev  # y 不重叠 → 原样


def test_cross_boundary_do_not_repeat_existing_unit() -> None:
    """I-ATT-1：块内已有 NOISE 单元不重复聚合（保幂等）。"""
    kept = {
        "u-title": (
            5,
            "贵州茅台（600519）2026 年中报点评",
            {"page": 1, "bbox": (0, 40, 500, 110)},
            sha256_of_bytes(("贵州茅台（600519）2026 年中报点评").encode()),
            ("header_repeated_geometric",),
        ),
        "u-rating": (
            6,
            "强推（维持）",
            {"page": 1, "bbox": (0, 80, 500, 120)},
            sha256_of_bytes(("强推（维持）").encode()),
            (),
        ),
    }
    noise = dict(kept)  # 全部视为 NOISE 候选
    merged = _merge_chunk(_chunk_with_rating(), kept, noise)
    # 标题已出现在块内（kept 侧），不得重复插入
    assert merged.units[0].unit_id == "u-title"
    assert merged.units[1].unit_id == "u-rating"
    assert len([u for u in merged.units if u.unit_id == "u-title"]) == 1


# --- F3-B：读取侧续接片段聚合（I-CONT-1 反例，i0c-r4u） ---


def _chunk_cut_mid_sentence() -> ChunkEvidence:
    """company-007/e1 同构：kept 单元 u-fact（ord717）句中截断，止于『…4.06%的股』。"""
    fact = UnitEvidence(
        unit_id="u-fact",
        raw_text="贵州茅台的控股股东华创云信4.06%的股",
        page=7,
        element="paragraph",
        cells=(),
    )
    return ChunkEvidence(
        source_id="S1",
        build_id="b1",
        chunk_id="c0",
        kind="paragraph",
        title_text=None,
        section_path=(),
        units=(fact,),
        text="贵州茅台的控股股东华创云信4.06%的股",
        source_ranges=((0, 40),),
        spans=(("u-fact", 0, 17),),
        active=True,
    )


_E1_KEPT_HEAD = "贵州茅台的控股股东华创云信4.06%的股"


def test_continuation_stitch_merges_sentence_final_noise_fragment() -> None:
    """I-CONT-1：紧邻下一 ordinal 的 NOISE 尾片段以句末标点收尾（拼接即补全句子）
    且同页 ⇒ 按 ordinal 保序聚合，引文『…4.06%的股份。』逐字可承载。"""
    kept = {
        "u-fact": (717, _E1_KEPT_HEAD, {"page": 7}, sha256_of_bytes((_E1_KEPT_HEAD).encode()), ())
    }
    fragments = {
        "u-tail": (
            718,
            "份。",
            {"page": 7},
            sha256_of_bytes(("份。").encode()),
            ("disclaimer_section",),
        )
    }
    merged = _merge_chunk(_chunk_cut_mid_sentence(), kept, {}, fragments=fragments)
    full = _ws_norm(merged.text)
    # 引文逐字可承载（句中不再断开），且前半（ord717）在尾片段（ord718）之前
    assert "华创云信4.06%的股份。" in full
    assert full.index("4.06%的股") < full.index("份。")
    assert [u.unit_id for u in merged.units] == ["u-fact", "u-tail"]
    # spans 自洽：按 (uid, start, end) 重建（单元间 "\n" 分隔）逐字节还原 text
    rebuilt = ""
    for i, (_uid, start, end) in enumerate(merged.spans):
        if i:
            rebuilt += "\n"
        rebuilt += merged.text[start:end]
    assert rebuilt == merged.text


def test_continuation_stitch_ignores_non_sentence_final_fragment() -> None:
    """I-CONT-1 反向：尾片段不以句末标点收尾（如页脚『请务必阅读…』）不聚合。"""
    ev = _chunk_cut_mid_sentence()
    kept = {
        "u-fact": (717, _E1_KEPT_HEAD, {"page": 7}, sha256_of_bytes((_E1_KEPT_HEAD).encode()), ())
    }
    fragments = {
        "u-tail": (
            718,
            "请务必阅读报告末页的声明",
            {"page": 7},
            sha256_of_bytes(("请务必阅读报告末页的声明").encode()),
            ("footer_repeated_geometric",),
        )
    }
    assert _merge_chunk(ev, kept, {}, fragments=fragments) is ev  # 原样返回


def test_continuation_stitch_requires_cut_head_adjacency_and_same_page() -> None:
    """I-CONT-1 反向：kept 已句末收尾 / 不同页 / ordinal 不相邻 ⇒ 均不聚合。"""
    ev = _chunk_cut_mid_sentence()
    kept = {
        "u-fact": (717, _E1_KEPT_HEAD, {"page": 7}, sha256_of_bytes((_E1_KEPT_HEAD).encode()), ())
    }
    tail = {
        "u-tail": (
            718,
            "份。",
            {"page": 7},
            sha256_of_bytes(("份。").encode()),
            ("disclaimer_section",),
        )
    }
    kept_full = {
        "u-fact": (
            717,
            "增持至5.02%的股份。",
            {"page": 7},
            sha256_of_bytes(("增持至5.02%的股份。").encode()),
            (),
        )
    }
    assert _merge_chunk(ev, kept_full, {}, fragments=tail) is ev  # kept 已句末收尾
    tail_page8 = {
        "u-tail": (
            718,
            "份。",
            {"page": 8},
            sha256_of_bytes(("份。").encode()),
            ("disclaimer_section",),
        )
    }
    assert _merge_chunk(ev, kept, {}, fragments=tail_page8) is ev  # 不同页
    tail_gap = {
        "u-tail": (
            720,
            "份。",
            {"page": 7},
            sha256_of_bytes(("份。").encode()),
            ("disclaimer_section",),
        )
    }
    assert _merge_chunk(ev, kept, {}, fragments=tail_gap) is ev  # ordinal 不相邻（717→720）


def test_continuation_stitch_do_not_repeat_existing_unit() -> None:
    """I-CONT-1：尾片段已在块内（如已按 kept 入块）不重复聚合（保幂等）。"""
    ev = ChunkEvidence(
        source_id="S1",
        build_id="b1",
        chunk_id="c0",
        kind="paragraph",
        title_text=None,
        section_path=(),
        units=(
            UnitEvidence(
                unit_id="u-fact",
                raw_text=_E1_KEPT_HEAD,
                page=7,
                element="paragraph",
                cells=(),
            ),
            UnitEvidence(unit_id="u-tail", raw_text="份。", page=7, element="paragraph", cells=()),
        ),
        text=_E1_KEPT_HEAD + "\n份。",
        source_ranges=((0, 40),),
        spans=(("u-fact", 0, 17), ("u-tail", 18, 20)),
        active=True,
    )
    kept = {
        "u-fact": (717, _E1_KEPT_HEAD, {"page": 7}, sha256_of_bytes((_E1_KEPT_HEAD).encode()), ()),
        "u-tail": (718, "份。", {"page": 7}, sha256_of_bytes(("份。").encode()), ()),
    }
    merged = _merge_chunk(ev, kept, {}, fragments=dict(kept))
    assert merged is ev  # 尾片段已在块内，谓词命中也不重复插入


# --- D2：表格来源注聚合（I-NOTE-1，i0c-r4y） ---


def _chunk_table_row(
    cells: tuple[tuple[int, int], ...] = ((70, 6), (70, 7), (70, 8)),
) -> ChunkEvidence:
    """industry-008 同构：块内 kept **表格行**（cells 非空），版面 y 到 704.2。"""

    row = UnitEvidence(
        unit_id="u-row",
        raw_text="0.0%\n4.5%\n0.0%",
        page=10,
        element="table_row",
        cells=cells,
    )
    return ChunkEvidence(
        source_id="S1",
        build_id="b1",
        chunk_id="c0",
        kind="table",
        title_text=None,
        section_path=(),
        units=(row,),
        text="0.0%\n4.5%\n0.0%",
        source_ranges=((0, 14),),
        spans=(("u-row", 0, 14),),
        active=True,
    )


_TABLE_ROW_LOC = {"page": 10, "bbox": (42.6, 112.0, 553.1, 704.2)}
_NOTE_TEXT = (
    "资料来源：百川盈孚，卓创资讯，化纤信息网，Wind，长江证券研究所\n"
    "注1：价格、价差分位为2016 年1 月1 日至2026 年7 月27 日"
)
#: 版面上沿 709.7 = 表格行下沿 704.2 + 5.45pt（实测 ord518/ord582）
_NOTE_LOC_OK = {"page": 10, "bbox": (42.6, 709.7, 380.6, 764.4)}
_NOTE_LOC_FAR = {"page": 10, "bbox": (42.6, 720.0, 380.6, 780.0)}  # Δ15.8 ≥ 12
_NOTE_LOC_ABOVE = {"page": 10, "bbox": (42.6, 100.0, 380.6, 110.0)}  # 版面在表格之上
_PURE_SOURCE = "资料来源：WIND，光大证券研究所"  # 无说明性分句 ⇒ 不聚合


def test_source_note_attached_below_table_row() -> None:
    """I-NOTE-1：注段在块内表格行**下方**且 Δ<12pt ⇒ 保序聚合，引文逐字可承载。"""

    kept = {
        "u-row": (582, "0.0%\n4.5%\n0.0%", _TABLE_ROW_LOC, sha256_of_bytes(b"0.0%\n4.5%\n0.0%"), ())
    }
    notes = {"u-note": (518, _NOTE_TEXT, _NOTE_LOC_OK, sha256_of_bytes((_NOTE_TEXT).encode()), ())}
    merged = _merge_chunk(_chunk_table_row(), kept, {}, notes=notes)
    assert [u.unit_id for u in merged.units] == ["u-note", "u-row"]  # ordinal 518 < 582
    assert "注1：价格、价差分位为2016年1月1日至2026年7月27日" in _ws_norm(merged.text)
    # spans 自洽
    rebuilt = ""
    for i, (_uid, start, end) in enumerate(merged.spans):
        if i:
            rebuilt += "\n"
        rebuilt += merged.text[start:end]
    assert rebuilt == merged.text


def test_source_note_ignores_pure_source_label() -> None:
    """I-NOTE-1 反向：纯「资料来源：WIND，光大证券研究所」（无口径说明）不聚合。"""

    kept = {
        "u-row": (582, "0.0%\n4.5%\n0.0%", _TABLE_ROW_LOC, sha256_of_bytes(b"0.0%\n4.5%\n0.0%"), ())
    }
    notes = {
        "u-note": (518, _PURE_SOURCE, _NOTE_LOC_OK, sha256_of_bytes((_PURE_SOURCE).encode()), ())
    }
    ev = _chunk_table_row()
    assert _merge_chunk(ev, kept, {}, notes=notes) is ev


def test_source_note_requires_below_adjacent_and_same_page() -> None:
    """I-NOTE-1 反向：版面在表格之上 / 间距 ≥12pt / 不同页 ⇒ 均不聚合。"""

    kept = {
        "u-row": (582, "0.0%\n4.5%\n0.0%", _TABLE_ROW_LOC, sha256_of_bytes(b"0.0%\n4.5%\n0.0%"), ())
    }
    for loc in (_NOTE_LOC_ABOVE, _NOTE_LOC_FAR, {"page": 11, "bbox": (42.6, 709.7, 380.6, 764.4)}):
        ev = _chunk_table_row()
        assert (
            _merge_chunk(
                ev,
                kept,
                {},
                notes={
                    "u-note": (518, _NOTE_TEXT, loc, sha256_of_bytes((_NOTE_TEXT).encode()), ())
                },
            )
            is ev
        )


def test_source_note_requires_table_row_anchor() -> None:
    """I-NOTE-1 反向：块内 kept 单元不是表格行（cells 为空）⇒ 不作为锚，不聚合。"""

    kept = {
        "u-row": (582, "0.0%\n4.5%\n0.0%", _TABLE_ROW_LOC, sha256_of_bytes(b"0.0%\n4.5%\n0.0%"), ())
    }
    notes = {"u-note": (518, _NOTE_TEXT, _NOTE_LOC_OK, sha256_of_bytes((_NOTE_TEXT).encode()), ())}
    ev = _chunk_table_row(cells=())
    assert _merge_chunk(ev, kept, {}, notes=notes) is ev
