"""I3-3 校准选择语义落产品（票 01：选择策略，I-B3 的常驻落点）+ 议题 B 结构排序最终形态
+ band 区间落产品（§10.5 选项 A）。

:func:`group_hits`（calibrate.py）的语义在此固化：候选按 score 降序流入，
**首个命中即确定来源出现**（first occurrence），前 ``top_k`` 个来源各取
``max_chunks_per_document`` 块；同一来源不得混用多个活动 build。

``max_chunks_per_document`` 默认锁死 8（r39 预声明的实验边界，I-B3）——调参
即违反「scores 后不调参」纪律，本模块不提供覆盖路径，只提供显式断言点。

议题 B（i42 回测裁决）最终形态：**perdoc** —— 文档序保持词法首次出现
（与 :func:`select` 逐字节一致），仅**文档内**前 ``max_chunks_per_document``
块按 (结构重叠数, score) 重排后取。结构重叠数 = 查询词元在 ``label_path``
token 中的去重命中数（词元重复不放大，非表格块得 0）。global 全池重排变体
（``search_pg.rank_hits`` 的 structural 模式）已在 i42 回测中对照并弃用——
它会把无关文档的结构命中块整体提前，扰动文档级召回（company-008 茅台落出
top-5）。

band 区间（i41 已验证 19/24，S2 判定后改道落产品）：:func:`select_band` 在
**选择层**承载"连续区间"（原票 03 ``chunk.cover`` 落点作废），chunk 层不动。
语义：文档内把命中块按原文位置聚簇成带（gap/expand），按带分取前 ``band_cap``
个带；``band_cap=8`` 是 I-B3 的带语义（不调 cap 值，8 从"块数"改为"带数"）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


class SelectionError(ValueError):
    """选择策略输入非法或同源多 build 混用（fail-closed，不静默降级）。"""


class _RankedHit(Protocol):
    """选择策略只依赖的来源身份、排名字段与结构标签（鸭子类型，避免耦合 SearchHit）。

    只读 property 声明：对 frozen dataclass（SearchHit）与可变实现均兼容，
    且不要求实现者暴露可写字段（协议只读 = 消费者只读）。
    """

    @property
    def source_id(self) -> str: ...

    @property
    def build_id(self) -> str: ...

    @property
    def chunk_id(self) -> str: ...

    @property
    def score(self) -> float: ...

    @property
    def label_path(self) -> tuple[str, ...]: ...

    @property
    def page(self) -> int | None: ...


@dataclass(frozen=True)
class SelectionPolicy:
    """选择策略：来源数与每来源块数上限（票 01 / I-B3）。"""

    top_k: int = 5
    max_chunks_per_document: int = 8  # I-B3：保持 8，调参即违反 r39 纪律

    def __post_init__(self) -> None:
        if self.top_k < 1:
            raise SelectionError(f"top_k 必须 >= 1: {self.top_k}")
        if self.max_chunks_per_document < 1:
            raise SelectionError(
                f"max_chunks_per_document 必须 >= 1: {self.max_chunks_per_document}"
            )


def select(hits: tuple[_RankedHit, ...], policy: SelectionPolicy) -> tuple[_RankedHit, ...]:
    """按 score 降序选择：前 ``top_k`` 个来源各取 ``max_chunks_per_document`` 块。

    - 第一个出现即确定来源排名（first occurrence follows maximum chunk score）；
    - 同一来源若混用多个 build（`group_hits` 同判据），抛 :class:`SelectionError`；
    - 返回块在输入序（score 降序）中保持相对顺序。
    """
    grouped: dict[str, list[_RankedHit]] = {}
    selected: list[_RankedHit] = []
    for hit in hits:
        if hit.source_id not in grouped:
            if len(grouped) >= policy.top_k:
                continue
            grouped[hit.source_id] = []
        bucket = grouped[hit.source_id]
        if bucket and hit.build_id != bucket[0].build_id:
            raise SelectionError(f"同一来源多个活动 build: {hit.source_id}")
        if len(bucket) < policy.max_chunks_per_document:
            bucket.append(hit)
            selected.append(hit)
    return tuple(selected)


def _label_tokens(hit: _RankedHit) -> set[str]:
    """hit 结构标签的 token 集合（结构重叠信号的比对侧，与 search_pg._label_tokens 同规则）。"""
    tokens: set[str] = set()
    for label in hit.label_path:
        tokens.update(label.split())
    return tokens


def select_structural(
    hits: tuple[_RankedHit, ...],
    policy: SelectionPolicy,
    *,
    lexemes: tuple[str, ...],
) -> tuple[_RankedHit, ...]:
    """议题 B 最终形态（perdoc）：文档序=词法首次出现，文档内按 (结构重叠数, score) 重排。

    - 文档序与 :func:`select` 逐字节一致（首个命中即确定来源排名，前 ``top_k`` 来源）；
    - 每个文档的桶先按 (结构重叠数, score) 降序重排，再取前 ``max_chunks_per_document`` 块
      （I-B2：问题含行/列标签词时，对应 cell 块进入该文档前 N 块）；
    - ``lexemes`` 为空时退化为纯词法 :func:`select`（与现状一致）；
    - 同一来源混用多个 build 抛 :class:`SelectionError`（同 :func:`select` 判据）。
    """
    if not lexemes:
        return select(hits, policy)
    lexeme_set = set(lexemes)
    grouped: dict[str, list[_RankedHit]] = {}
    order: list[str] = []
    for hit in hits:
        if hit.source_id not in grouped:
            if len(grouped) >= policy.top_k:
                continue
            grouped[hit.source_id] = []
            order.append(hit.source_id)
        bucket = grouped[hit.source_id]
        if bucket and hit.build_id != bucket[0].build_id:
            raise SelectionError(f"同一来源多个活动 build: {hit.source_id}")
        bucket.append(hit)

    def key(hit: _RankedHit) -> tuple[int, float]:
        return (len(lexeme_set & _label_tokens(hit)), hit.score)

    selected: list[_RankedHit] = []
    for sid in order:
        bucket = sorted(grouped[sid], key=key, reverse=True)
        selected.extend(bucket[: policy.max_chunks_per_document])
    return tuple(selected)


@dataclass(frozen=True)
class BandPolicy:
    """带区间选择策略（§10.5 选项 A 落产品，i40/i41 已验证语义）。

    - ``gap``：相邻池块间允许的最大非池块数（空隙容忍）；
    - ``expand``：带两端各扩展的块数；
    - ``band_cap``：每文档选带数上限（I-B3：cap=8 的带语义——不调 cap 值，
      ``max_chunks_per_document=8`` 语义改为"每文档选带数 8"）；
    - ``pool_cap``：带内池块数上限（span cap mode = "pool"；超限簇按池块锚拆子带）。
    """

    gap: int = 1
    expand: int = 1
    band_cap: int = 8
    pool_cap: int = 24

    def __post_init__(self) -> None:
        if self.gap < 0 or self.expand < 0:
            raise SelectionError(f"gap/expand 必须 >= 0: {self.gap}/{self.expand}")
        if self.band_cap < 1 or self.pool_cap < 1:
            raise SelectionError(f"band_cap/pool_cap 必须 >= 1: {self.band_cap}/{self.pool_cap}")

    @property
    def provable_width_bound(self) -> int:
        """可证带宽上界（块）：W_max = (pool_cap-1)*(gap+1)+1+2*expand。"""
        return (self.pool_cap - 1) * (self.gap + 1) + 1 + 2 * self.expand


@dataclass(frozen=True)
class SelectedBand:
    """一个选中带区间：原文序闭区间 [start, end] + 带分 + 池块位置。

    ``chunk_ids`` 是原文序带内全部块 id（含扩展的非池块），由调用方按需装配
    （本模块不做 IO）。``pool`` 是带内池块（查询命中块）的原文序位置。
    """

    source_id: str
    build_id: str
    start: int
    end: int
    score: float
    pool: tuple[int, ...]

    @property
    def width(self) -> int:
        return self.end - self.start + 1


def _form_bands(
    pool_positions: list[int],
    score_by_pos: dict[int, float],
    n: int,
    gap: int,
    expand: int,
) -> list[dict]:
    """池内位置聚簇 → 带区间（原文序闭区间），带分 = 簇内最大 ts_rank。

    ``pool_positions`` 已按原文序排序。相邻池位置间隔（非池块数）≤ gap 视为同簇；
    每簇两端各扩展 expand 块。返回按位置排序的带 [{start, end, score, pool}]。
    """
    clusters: list[list[int]] = []
    for p in pool_positions:
        if clusters and p - clusters[-1][-1] - 1 <= gap:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    bands = []
    for cl in clusters:
        bands.append(
            {
                "start": max(0, cl[0] - expand),
                "end": min(n - 1, cl[-1] + expand),
                "score": max(score_by_pos[p] for p in cl),
                "pool": list(cl),
            }
        )
    return bands


def _cap_split(
    bands: list[dict],
    score_by_pos: dict[int, float],
    n: int,
    pool_cap: int,
    expand: int,
) -> list[dict]:
    """方案 C：带内池块数上限。簇内池块 > pool_cap 时按池块锚顺序拆为子带。

    每子带 = 连续 ≤pool_cap 个池块 ± expand 扩展；子带分 = 子带内最大 ts_rank。
    """
    out = []
    for band in bands:
        bp = band["pool"]
        if len(bp) <= pool_cap:
            out.append(band)
            continue
        for i in range(0, len(bp), pool_cap):
            group = bp[i : i + pool_cap]
            out.append(
                {
                    "start": max(0, group[0] - expand),
                    "end": min(n - 1, group[-1] + expand),
                    "score": max(score_by_pos[p] for p in group),
                    "pool": list(group),
                }
            )
    return out


def _merge_same_page_bands(
    bands: list[dict],
    page_by_pos: Mapping[int, int | None],
    *,
    max_width: int,
    pool_cap: int,
) -> list[dict]:
    """Merge sparse PDF hits on one page without weakening the global width bound."""
    merged: list[dict] = []
    for original in bands:
        band = dict(original)
        pages = {page_by_pos.get(position) for position in band["pool"]}
        page = next(iter(pages)) if len(pages) == 1 else None
        if (
            page is not None
            and merged
            and merged[-1].get("page") == page
            and band["end"] - merged[-1]["start"] + 1 <= max_width
            and len(merged[-1]["pool"]) + len(band["pool"]) <= pool_cap
        ):
            previous = merged[-1]
            previous["end"] = band["end"]
            previous["score"] = max(previous["score"], band["score"])
            previous["pool"] = sorted({*previous["pool"], *band["pool"]})
            continue
        band["page"] = page
        merged.append(band)
    return merged


def _rank_bands(bands: list[dict]) -> dict[int, int]:
    """带分降序排名（并列按带起点）；返回 {带在 bands 中的索引: 排名(1-based)}。"""
    order = sorted(range(len(bands)), key=lambda i: (-bands[i]["score"], bands[i]["start"]))
    return {idx: rank + 1 for rank, idx in enumerate(order)}


def select_band(
    hits: tuple[_RankedHit, ...],
    policy: SelectionPolicy,
    band: BandPolicy,
    *,
    chunk_order_by_source: Mapping[str, tuple[str, ...]],
) -> tuple[SelectedBand, ...]:
    """带区间选择（§10.5 选项 A 落产品）：文档选择同 :func:`select`，
    文档内把命中块聚簇成带（gap/expand），按带分取前 ``band_cap`` 个带。

    - 文档序与 :func:`select` 逐字节一致（首个命中即确定来源排名，前 ``top_k`` 来源）；
    - 每个文档：命中块位置 → :func:`_form_bands` 聚簇 → :func:`_cap_split` 拆超限簇
      → :func:`_rank_bands` 排名 → 取前 ``band.band_cap`` 个带（并列按带起点）；
    - ``chunk_order_by_source``：{source_id: 原文序全部块 id}，把命中块投影到原文位置
      （本模块不做 IO，由调用方按 build 全量块装配）；
    - 同一来源混用多个 build 抛 :class:`SelectionError`（同 :func:`select` 判据）；
    - 命中块不在原文序清单（chunk_order_by_source 缺项）时抛 :class:`SelectionError`
      （fail-closed，不静默丢块）。
    """
    if not hits:
        return ()
    grouped: dict[str, list[_RankedHit]] = {}
    order: list[str] = []
    for hit in hits:
        if hit.source_id not in grouped:
            if len(grouped) >= policy.top_k:
                continue
            grouped[hit.source_id] = []
            order.append(hit.source_id)
        bucket = grouped[hit.source_id]
        if bucket and hit.build_id != bucket[0].build_id:
            raise SelectionError(f"同一来源多个活动 build: {hit.source_id}")
        bucket.append(hit)

    selected: list[SelectedBand] = []
    for source_id in order:
        bucket = grouped[source_id]
        ordered = chunk_order_by_source.get(source_id)
        if ordered is None:
            raise SelectionError(f"缺少 {source_id} 的原文序块清单")
        pos_of = {chunk_id: i for i, chunk_id in enumerate(ordered)}
        missing = [h.chunk_id for h in bucket if h.chunk_id not in pos_of]
        if missing:
            raise SelectionError(f"{source_id} 命中块不在原文序清单: {missing[:3]}")
        pool_positions = sorted({pos_of[h.chunk_id] for h in bucket})
        score_by_pos = {pos_of[h.chunk_id]: h.score for h in bucket}
        page_by_pos = {pos_of[h.chunk_id]: getattr(h, "page", None) for h in bucket}
        bands = _form_bands(pool_positions, score_by_pos, len(ordered), band.gap, band.expand)
        bands = _cap_split(bands, score_by_pos, len(ordered), band.pool_cap, band.expand)
        bands = _merge_same_page_bands(
            bands,
            page_by_pos,
            max_width=band.provable_width_bound,
            pool_cap=band.pool_cap,
        )
        ranking = _rank_bands(bands)
        for index in sorted(
            (i for i, rank in ranking.items() if rank <= band.band_cap),
            key=lambda i: (-bands[i]["score"], bands[i]["start"]),
        ):
            b = bands[index]
            selected.append(
                SelectedBand(
                    source_id=source_id,
                    build_id=bucket[0].build_id,
                    start=b["start"],
                    end=b["end"],
                    score=b["score"],
                    pool=tuple(b["pool"]),
                )
            )
    return tuple(selected)
