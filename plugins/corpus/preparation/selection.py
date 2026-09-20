"""I3-3 校准选择语义落产品（票 01：选择策略，I-B3 的常驻落点）+ 议题 B 结构排序最终形态。

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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class SelectionError(ValueError):
    """选择策略输入非法或同源多 build 混用（fail-closed，不静默降级）。"""


class _RankedHit(Protocol):
    """选择策略只依赖的来源身份、排名字段与结构标签（鸭子类型，避免耦合 SearchHit）。"""

    source_id: str
    build_id: str
    score: float
    label_path: tuple[str, ...]


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
