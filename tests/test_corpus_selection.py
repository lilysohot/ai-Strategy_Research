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


def _hit(
    source_id: str,
    build_id: str,
    score: float,
    *,
    chunk_id: str | None = None,
    label_path: tuple[str, ...] = (),
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
        _hit("B", "b1", 9.0, chunk_id="b_prose", label_path=()),          # 词法先行文档
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
    assert select_structural(hits, SelectionPolicy(), lexemes=()) == select(
        hits, SelectionPolicy()
    )


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
    bands = select_band(hits, SelectionPolicy(), BandPolicy(),
                        chunk_order_by_source={"A": chunk_order})
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
    bands = select_band(hits, SelectionPolicy(), BandPolicy(),
                        chunk_order_by_source={"A": chunk_order})
    # 带序 = (带分降序, 带起点升序)：c4 分更高排前
    assert [b.pool for b in bands] == [(4,), (1,)]


def test_select_band_dedup_repeat_hits_per_position() -> None:
    """多个命中投影到同一原文位置时去重（不放大带内池块数）。"""
    chunk_order = tuple(f"c{i}" for i in range(8))
    hits = (
        _hit("A", "b1", 1.0, chunk_id="c3"),
        _hit("A", "b1", 0.5, chunk_id="c3"),
    )
    bands = select_band(hits, SelectionPolicy(), BandPolicy(),
                        chunk_order_by_source={"A": chunk_order})
    assert len(bands) == 1
    assert bands[0].pool == (3,)


def test_select_band_cap_split_exceeds_pool_cap() -> None:
    """带内池块数 > pool_cap 时按池块锚拆子带（方案 C）。"""
    pool_cap = 3
    n = 30
    chunk_order = tuple(f"c{i}" for i in range(n))
    pool_positions = [2, 3, 4, 10, 11, 12, 13]  # 两簇，第二簇 4 块 > pool_cap=3
    hits = tuple(_hit("A", "b1", float(p), chunk_id=f"c{p}") for p in pool_positions)
    bands = select_band(hits, SelectionPolicy(),
                        BandPolicy(gap=1, expand=1, pool_cap=pool_cap),
                        chunk_order_by_source={"A": chunk_order})
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
    bands = select_band(hits, SelectionPolicy(), band,
                        chunk_order_by_source={"A": chunk_order})
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
        hits, SelectionPolicy(), BandPolicy(),
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
        select_band(hits, SelectionPolicy(), BandPolicy(),
                    chunk_order_by_source={})


def test_select_band_hit_outside_order_fails_closed() -> None:
    """命中块不在原文序清单 → fail-closed（不静默丢块）。"""
    chunk_order = ("c0", "c1")
    hits = (_hit("A", "b1", 1.0, chunk_id="ghost"),)
    with pytest.raises(SelectionError):
        select_band(hits, SelectionPolicy(), BandPolicy(),
                    chunk_order_by_source={"A": chunk_order})


def test_select_band_rejects_multiple_active_builds() -> None:
    """同源多 build 混用 fail-closed（与 select 同判据）。"""
    hits = (
        _hit("A", "b1", 10.0, chunk_id="c0"),
        _hit("A", "b2", 9.0, chunk_id="c1"),
    )
    with pytest.raises(SelectionError):
        select_band(hits, SelectionPolicy(), BandPolicy(),
                    chunk_order_by_source={"A": ("c0", "c1")})


def test_select_band_deterministic_and_stable_order() -> None:
    """确定性：同输入两次运行逐字段一致；带序按 (带分降序, 带起点升序)。"""
    chunk_order = tuple(f"c{i}" for i in range(20))
    hits = (
        _hit("A", "b1", 1.0, chunk_id="c3"),
        _hit("A", "b1", 9.0, chunk_id="c10"),
        _hit("A", "b1", 5.0, chunk_id="c16"),
    )
    first = select_band(hits, SelectionPolicy(), BandPolicy(),
                        chunk_order_by_source={"A": chunk_order})
    second = select_band(hits, SelectionPolicy(), BandPolicy(),
                         chunk_order_by_source={"A": chunk_order})
    assert first == second
    assert [b.score for b in first] == [9.0, 5.0, 1.0]
