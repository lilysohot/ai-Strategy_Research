"""结构优先切块（任务 I1-4，架构 v1.1 §6.2）。

输入 I1-3 的 :class:`~plugins.corpus.preparation.clean.CleanResult`（配对
``ReaderResult`` 取页码/元素坐标），输出检索块候选 :class:`ChunkResult`。
纯标准库；同输入同 ``CHUNK_REV`` 输出逐字段一致。

首版参数作为开发起点（架构 §6.2：I3 只在开发集校准后才冻结）：正文目标
``TARGET_MIN``—``TARGET_MAX`` Unicode 字符，常规块上限 ``HARD_LIMIT``；标题/
短评级/短尾块可远小于目标，不按最小长度删除有效信号。检索块 ≠ R2 原子义务。

规则（开发起点冻结于代码）：

- 正文：先章节、再完整段落、再安全句界；段落跨上限时只在句界切分（句点仅取
  中日韩终止符与分号，不含英文句点，避免切断小数）；不默认一页一块、不跨报告
  拼接；默认核心区域不重叠。
- 标题/短评级：与所属后文关联（``title_text`` + ``section_path``）；无后文时
  独立保留为 heading 块，不删除。
- 列表：条目为原子（不切断条目），超上限按完整条目分块；单条超上限标
  ``oversized_unsplittable`` 显式复核。
- 问答：问与答建立结构组（kind ``qa``）；答案长时分段，但每段显式关联同一
  问题（title 与引用式 context 携带问题原文），不把问题改写成陈述。
- 表格：以行为原子，按（页码/元素, 表序）分组——跨页不靠位置猜接，页界即分组
  边界（延续关系未验证前不连接，保守分开）；同组超上限按完整行分块，续块以
  首行（列头）作引用式 context 携带；单元格永不切断。
- 超长不可安全拆分单元：保留原文独立成块并标 ``oversized_unsplittable`` 复核，
  不截断后宣称完整，不自动当常规块发布。
- 噪声/待复核/需 OCR 区域不进入任何检索块（其状态已由清洗台账承载）。

``ChunkCandidate`` 是引擎侧契约 ``Chunk`` 的前置投影：``unit_ordinals`` 指回
读取单元 ordinal，``chunk_id``/``build_id``/``unit_refs`` 由 I1-7 引擎装配。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from plugins.corpus.preparation.clean import CleanRegion, CleanResult
from plugins.corpus.preparation.contract import CHUNK_KINDS, UnitStatus
from plugins.corpus.preparation.readers.base import CandidateUnit, ReaderResult

CHUNK_REV = "chunk-3"


def normalize_search_text(text: str) -> str:
    """索引与查询共用的搜索文本规范化（R5）。

    ``%``/``％`` 会粘连进数字 token（SCWS："23.5%" 整体成词，裸数字查询不命中），
    归一化为空格保证 "23.5" 可查；百分比符号不承载检索语义，权威文本仍是
    ``unit.raw_text``（不修改 units）。**写侧（chunk.search_text）与查询侧
    （search_pg.search_chunks）必须使用同一规则**，否则双方 token 不一致——
    这是 R5 修复的关键：查询侧须对 ``%`` 做同样归一化，而非只改写侧。

    本函数属**索引文本规则**：其变更只影响 token 形态、不改变块边界，因此只升
    ``index_rev``，不升 ``CHUNK_REV``（RM-10；见 engine.INDEX_REV_V3 注释）。
    """
    return text.replace("%", " ").replace("％", " ")


# --- 开发起点参数（架构 §6.2；I3 校准前不外置） ---
TARGET_MIN = 800
TARGET_MAX = 1200
HARD_LIMIT = 1800

_REVIEW_OVERSIZED = "oversized_unsplittable"

_HEADING_KINDS = frozenset({"heading", "title"})
_BODY_KINDS = frozenset({"paragraph", "quote", "unknown"})
_TABLE_KIND = "table_row"
_LIST_KIND = "list_item"

_QUESTION_TURN = re.compile(r"^(?:问|提问者|提问|投资者)\s*[：:]")
_SENTENCE_END = re.compile(r"[。！？!?；;…]")


class ChunkError(ValueError):
    """切块不变式被破坏（构造/校验即失败，不静默降级）。"""


@dataclass(frozen=True)
class ChunkCandidate:
    """一个检索块候选（契约 ``Chunk`` 的前置投影，id 由引擎装配）。

    ``context_refs`` 是引用式关联（复核 R4）：文本放不进本块、但解释本块所必需
    的来源单元 ordinal（如被正文预算挤出的表头行）——不复制文本，但保留引用与
    表归属，引用内容不因此从台账消失。
    """

    key: str
    kind: str
    unit_ordinals: tuple[int, ...]
    search_text: str
    title_text: str | None
    section_path: tuple[str, ...]
    review_reasons: tuple[str, ...] = ()
    context_refs: tuple[int, ...] = ()


@dataclass(frozen=True)
class ChunkResult:
    """一次确定性结构切块的结果：候选块 + 超长不可分单元清单。"""

    chunk_rev: str
    chunks: tuple[ChunkCandidate, ...]
    oversized_ordinals: tuple[int, ...]


@dataclass(frozen=True)
class _Piece:
    """块内最小装配片：一段不可再切的文本及其来源单元。"""

    ordinals: tuple[int, ...]
    text: str
    oversized: bool = False


def _split_sentences(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        end = match.end()
        parts.append(text[start:end])
        start = end
    if start < len(text):
        parts.append(text[start:])
    return parts


def _sentence_pieces(text: str) -> list[tuple[str, bool]]:
    """把超长段落按安全句界聚成 ≤``HARD_LIMIT`` 片；单句超上限标 oversized。"""
    pieces: list[tuple[str, bool]] = []
    current = ""
    for sentence in _split_sentences(text):
        if len(sentence) > HARD_LIMIT:
            if current:
                pieces.append((current, False))
            pieces.append((sentence, True))
            current = ""
        elif len(current) + len(sentence) > HARD_LIMIT:
            pieces.append((current, False))
            current = sentence
        else:
            current += sentence
    if current:
        pieces.append((current, False))
    return pieces


def _region_pieces(ordinal: int, text: str, *, splittable: bool) -> list[_Piece]:
    if len(text) <= HARD_LIMIT:
        return [_Piece((ordinal,), text)]
    if not splittable:  # 表格行/列表条目不可切分：保留原单元，显式复核
        return [_Piece((ordinal,), text, True)]
    return [_Piece((ordinal,), piece, flag) for piece, flag in _sentence_pieces(text)]


def _kept_regions(reader_result: ReaderResult, clean: CleanResult) -> list[tuple[int, CleanRegion]]:
    region_by_ordinal = {
        region.ordinal: region for region in clean.regions if region.ordinal is not None
    }
    kept: list[tuple[int, CleanRegion]] = []
    for unit in sorted(reader_result.units, key=lambda item: item.ordinal):
        region = region_by_ordinal.get(unit.ordinal)
        if region is not None and region.status is UnitStatus.KEPT and region.clean_view:
            kept.append((unit.ordinal, region))
    return kept


def _table_row_label_prefix(unit: CandidateUnit | None) -> str:
    """表格行的结构标签前缀（票 04 I-B1）：与 cells 对齐的 label_path 去重合并。

    仅注入索引文本（search_text），不触碰 ``unit.raw_text``——引用取证仍逐字
    来自原文；``label_path`` 为空的合成单元返回空串，行为与旧版逐字节一致。
    """
    if unit is None:
        return ""
    parts: list[str] = []
    seen: set[str] = set()
    for label in unit.location.label_path:
        if label and label not in seen:
            seen.add(label)
            parts.append(label)
    return " ".join(parts)


def _table_row_pieces(ordinal: int, text: str, prefix: str) -> list[_Piece]:
    """表格行 piece：结构标签前缀 + 行文本；单元格永不切断。

    前缀推超上限的行显式标 ``oversized_unsplittable`` 复核，不静默越过
    ``HARD_LIMIT``。
    """
    pieces = _region_pieces(ordinal, text, splittable=False)
    if not prefix:
        return pieces
    out: list[_Piece] = []
    for piece in pieces:
        prefixed = f"{prefix}\n{piece.text}"
        out.append(_Piece(piece.ordinals, prefixed, piece.oversized or len(prefixed) > HARD_LIMIT))
    return out


def _table_group_key(
    unit_by_ordinal: dict[int, CandidateUnit], ordinal: int, region: CleanRegion
) -> tuple[str, str]:
    """表格行分组键（页码/元素, 表序）：页界即分组边界，跨页不猜接。"""
    unit = unit_by_ordinal.get(ordinal)
    page = ""
    element = ""
    if unit is not None:
        page = str(unit.location.page) if unit.location.page is not None else ""
        element = unit.location.element or ""
    tbl = next((reason for reason in region.reasons if reason.startswith("tbl[")), "")
    return (page or element.split(":")[0], tbl)


def verify_chunk_result(clean: CleanResult, result: ChunkResult) -> None:
    """校验切块不变式；任何破坏抛 :class:`ChunkError`。

    - 覆盖：每个保留区进入 ≥1 个块；噪声/待复核/需 OCR 区域不进入任何块。
    - 完整：块文本 ≤ 上限，超限块必须带 ``oversized_unsplittable`` 复核标记；
      ``oversized_ordinals`` 与标记块引用一致；块 kind ∈ ``CHUNK_KINDS``。
    """
    kept = {
        region.ordinal
        for region in clean.regions
        if region.ordinal is not None and region.status is UnitStatus.KEPT and region.clean_view
    }
    used: set[int] = set()
    keys: set[str] = set()
    oversized_from_chunks: set[int] = set()
    for chunk in result.chunks:
        if chunk.kind not in CHUNK_KINDS:
            raise ChunkError(f"块 {chunk.key} kind 非法: {chunk.kind}")
        if chunk.key in keys:
            raise ChunkError(f"块 key 重复: {chunk.key}")
        keys.add(chunk.key)
        if not chunk.unit_ordinals or not chunk.search_text:
            raise ChunkError(f"块 {chunk.key} 缺少单元引用或检索文本")
        for ordinal in chunk.unit_ordinals:
            if ordinal not in kept:
                raise ChunkError(f"块 {chunk.key} 引用非保留区单元 {ordinal}")
            used.add(ordinal)
        for ref in chunk.context_refs:
            # 引用式关联（R4）必须指向真实保留区，且不得与自身单元引用重复。
            if ref not in kept:
                raise ChunkError(f"块 {chunk.key} context 引用非保留区单元 {ref}")
            if ref in chunk.unit_ordinals:
                raise ChunkError(f"块 {chunk.key} context 引用与自身单元引用重复: {ref}")
        if len(chunk.search_text) > HARD_LIMIT and _REVIEW_OVERSIZED not in chunk.review_reasons:
            raise ChunkError(f"块 {chunk.key} 超上限却无复核标记")
        if _REVIEW_OVERSIZED in chunk.review_reasons:
            oversized_from_chunks.update(chunk.unit_ordinals)
    missing = kept - used
    if missing:
        raise ChunkError(f"保留区未进入任何检索块: {sorted(missing)}")
    if set(result.oversized_ordinals) != oversized_from_chunks:
        raise ChunkError("oversized_ordinals 与复核标记块引用不一致")


def chunk_clean_result(reader_result: ReaderResult, clean: CleanResult) -> ChunkResult:
    """对保留区做结构优先切块：章节/段落/句界 + 问答/表格/列表分组 + 超长复核。"""
    kept = _kept_regions(reader_result, clean)
    unit_by_ordinal: dict[int, CandidateUnit] = {unit.ordinal: unit for unit in reader_result.units}
    chunks: list[ChunkCandidate] = []
    oversized: list[int] = []
    counters: dict[str, int] = {}
    section_path: list[str] = []
    pending_title: str | None = None
    pending_title_ordinal: int | None = None

    def next_key(kind: str) -> str:
        counters[kind] = counters.get(kind, 0) + 1
        return f"{kind}:{counters[kind] - 1:04d}"

    def emit(
        pieces: list[_Piece],
        *,
        kind: str,
        title: str | None,
        path: tuple[str, ...],
        context: _Piece | None = None,
        title_ordinal: int | None = None,
        context_refs: tuple[int, ...] = (),
    ) -> None:
        ordinals: list[int] = []
        texts: list[str] = []
        if title_ordinal is not None:
            ordinals.append(title_ordinal)  # 标题作引用式 context，单元随首块携带
        if context is not None:
            ordinals.extend(context.ordinals)
            texts.append(context.text)
        for piece in pieces:
            ordinals.extend(piece.ordinals)
            texts.append(piece.text)
        review = (_REVIEW_OVERSIZED,) if any(piece.oversized for piece in pieces) else ()
        chunk = ChunkCandidate(
            key=next_key(kind),
            kind=kind,
            unit_ordinals=tuple(ordinals),
            # %/％ 会粘连进数字 token（SCWS："23.5%" 整体成词，裸数字查询不命中），
            # 归一化为空格保证 "23.5" 可查；% 不承载语义，权威文本仍是 unit.raw_text。
            search_text=normalize_search_text("\n".join(texts)),
            title_text=title,
            section_path=path,
            review_reasons=review,
            context_refs=context_refs,
        )
        chunks.append(chunk)
        for piece in pieces:
            if piece.oversized:
                oversized.extend(piece.ordinals)

    def emit_run(
        pieces: list[_Piece],
        *,
        kind: str,
        title: str | None,
        path: tuple[str, ...],
        context: _Piece | None = None,
        title_ordinal: int | None = None,
    ) -> None:
        if context is not None and context.oversized:
            context = None  # 超长 context 会使一切块超限，退化为仅 title 关联
        current: list[_Piece] = []
        first = True

        def size(parts: list[_Piece], ctx: _Piece | None) -> int:
            total = len(ctx.text) + 1 if ctx is not None else 0
            return total + sum(len(piece.text) for piece in parts) + max(0, len(parts) - 1)

        def flush() -> None:
            nonlocal current, first
            if not current:
                return
            ctx = context
            dropped_refs: tuple[int, ...] = ()
            if ctx is not None and size(current, ctx) > HARD_LIMIT:
                # 复核 R4：context 文本超出正文预算时不再静默丢弃关联——文本
                # 退场、引用保留（context_refs 指向表头/问题来源单元），表归属
                # 不因此消失，也不得挤爆常规块上限。
                dropped_refs = ctx.ordinals
                ctx = None
            emit(
                current,
                kind=kind,
                title=title,
                path=path,
                context=None if first else ctx,
                context_refs=() if first else dropped_refs,
                title_ordinal=title_ordinal if first else None,
            )
            first = False
            current = []

        for piece in pieces:
            if piece.oversized:
                flush()
                # 复核 C7：已消费的 pending 标题不得随超长分支丢失。标题不能挂进
                # 超长复核块——verify 要求复核标记块的 unit_ordinals 与
                # oversized_ordinals 严格一致（标题属引用而非超长内容），覆盖检查
                # 又只认 unit_ordinals；故标题先独立成 heading 块发布（文本与单元
                # 都不退场），超长内容随后独立成块显式复核，二者均不丢失。
                if first and title_ordinal is not None and title is not None:
                    emit(
                        [_Piece((title_ordinal,), title)],
                        kind="heading",
                        title=None,
                        path=path,
                    )
                emit([piece], kind=kind, title=title, path=path)
                first = False
                continue
            if not current:
                current.append(piece)
                continue
            ctx = None if first else context
            if size([*current, piece], ctx) <= HARD_LIMIT and (
                size(current, ctx) < TARGET_MIN or size([*current, piece], ctx) <= TARGET_MAX
            ):
                current.append(piece)
            else:
                flush()
                current = [piece]
        flush()

    index = 0
    while index < len(kept):
        ordinal, region = kept[index]
        kind = region.kind
        text = region.clean_view or ""
        if kind in _HEADING_KINDS:
            section_path.append(text)
            del section_path[:-3]
            if index + 1 < len(kept) and kept[index + 1][1].kind in _HEADING_KINDS:
                # 无后文的标题独立保留，不按最小长度删除有效信号。
                emit(
                    [_Piece((ordinal,), text)], kind="heading", title=None, path=tuple(section_path)
                )
            else:
                pending_title, pending_title_ordinal = text, ordinal
            index += 1
            continue
        if kind == _LIST_KIND:
            run: list[tuple[int, CleanRegion]] = []
            while index < len(kept) and kept[index][1].kind == _LIST_KIND:
                run.append(kept[index])
                index += 1
            pieces = [
                piece
                for item_ordinal, item_region in run
                for piece in _region_pieces(
                    item_ordinal, item_region.clean_view or "", splittable=False
                )
            ]
            title, pending_title = pending_title, None
            title_ordinal, pending_title_ordinal = pending_title_ordinal, None
            emit_run(
                pieces,
                kind="list",
                title=title,
                path=tuple(section_path),
                title_ordinal=title_ordinal,
            )
            continue
        if kind == _TABLE_KIND:
            run = []
            while index < len(kept) and kept[index][1].kind == _TABLE_KIND:
                run.append(kept[index])
                index += 1
            title, pending_title = pending_title, None
            title_ordinal, pending_title_ordinal = pending_title_ordinal, None
            groups: list[list[tuple[int, CleanRegion]]] = []
            group_keys: list[tuple[str, str]] = []
            for row_ordinal, row_region in run:
                key = _table_group_key(unit_by_ordinal, row_ordinal, row_region)
                if groups and key == group_keys[-1]:
                    groups[-1].append((row_ordinal, row_region))
                else:
                    groups.append([(row_ordinal, row_region)])
                    group_keys.append(key)
            for group in groups:
                pieces: list[_Piece] = []
                for row_ordinal, row_region in group:
                    prefix = _table_row_label_prefix(unit_by_ordinal.get(row_ordinal))
                    pieces.extend(
                        _table_row_pieces(row_ordinal, row_region.clean_view or "", prefix)
                    )
                context = pieces[0] if len(pieces) > 1 else None
                emit_run(
                    pieces,
                    kind="table",
                    title=title,
                    path=tuple(section_path),
                    context=context,
                    title_ordinal=title_ordinal,
                )
            continue
        if kind == "paragraph" and _QUESTION_TURN.match(text):
            group = [(ordinal, region)]
            index += 1
            while index < len(kept):
                next_ordinal, next_region = kept[index]
                if next_region.kind != "paragraph":
                    break
                next_text = next_region.clean_view or ""
                if _QUESTION_TURN.match(next_text):
                    break
                group.append((next_ordinal, next_region))
                index += 1
            question_ordinal, question_region = group[0]
            question_text = question_region.clean_view or ""
            question_piece = _Piece(
                (question_ordinal,), question_text, oversized=len(question_text) > HARD_LIMIT
            )
            answer_pieces: list[_Piece] = []
            for answer_ordinal, answer_region in group[1:]:
                answer_pieces.extend(
                    _region_pieces(answer_ordinal, answer_region.clean_view or "", splittable=True)
                )
            title, pending_title = pending_title, None
            title_ordinal, pending_title_ordinal = pending_title_ordinal, None
            emit_run(
                [question_piece, *answer_pieces],
                kind="qa",
                title=title or question_text,  # 答案分段仍显式关联同一问题
                path=tuple(section_path),
                context=None if question_piece.oversized else question_piece,
                title_ordinal=title_ordinal,
            )
            continue
        # 正文：先章节（标题已断组），再完整段落，再安全句界；默认核心区域不重叠。
        run = []
        while index < len(kept):
            run_ordinal, run_region = kept[index]
            if run_region.kind in _HEADING_KINDS or run_region.kind in (_LIST_KIND, _TABLE_KIND):
                break
            if run_region.kind == "paragraph" and _QUESTION_TURN.match(run_region.clean_view or ""):
                break
            run.append((run_ordinal, run_region))
            index += 1
        pieces = [
            piece
            for body_ordinal, body_region in run
            for piece in _region_pieces(body_ordinal, body_region.clean_view or "", splittable=True)
        ]
        title, pending_title = pending_title, None
        title_ordinal, pending_title_ordinal = pending_title_ordinal, None
        emit_run(
            pieces, kind="body", title=title, path=tuple(section_path), title_ordinal=title_ordinal
        )

    if pending_title is not None and pending_title_ordinal is not None:
        # 末尾 pending 标题 flush（F7）：文档以标题收尾时独立保留为 heading 块，
        # 不删除，也不得因「保留区未进入任何检索块」而整体失败。
        emit(
            [_Piece((pending_title_ordinal,), pending_title)],
            kind="heading",
            title=None,
            path=tuple(section_path),
        )

    result = ChunkResult(
        chunk_rev=CHUNK_REV,
        chunks=tuple(chunks),
        oversized_ordinals=tuple(dict.fromkeys(oversized)),
    )
    verify_chunk_result(clean, result)
    return result
