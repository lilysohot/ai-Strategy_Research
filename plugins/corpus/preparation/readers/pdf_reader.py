"""PDF 读取 Adapter（架构 v1.1 §5.3）。

读取页、文本行/块坐标与字号，按确定性规则装配段落与标题；表格读取作为受控
Adapter：表格区域内文字从正文剔除并计入表格行单元（不静默拼接两份重复正文），
提取失败、或存在成网状制表线却提取不到表格，均记录冲突信号进入复核。空文字页、
疑似图片页、乱码页与多栏页分别标记，不按全文平均字符数放行。
"""

from __future__ import annotations

import re
import statistics
import unicodedata
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

import pymupdf

from plugins.corpus.preparation.contract import UnitLocation, UnitStatus
from plugins.corpus.preparation.readers.base import (
    CandidateUnit,
    ReaderIssue,
    ReaderResult,
    detect_format,
)

READER_PDF_REV = "reader-pdf-6"

_GARBLED_MAX_RATIO = 0.05
_HEADING_SIZE_FACTOR = 1.15
_HEADING_MAX_CHARS = 80
_COLUMN_GAP_RATIO = 0.12
_MIN_GRID_LINES = 6
_IMAGE_REGION_RATIO = 0.25  # 混合页大图缺口阈值（占页面积比例）
_MAX_HEADER_ROWS = 2  # 表格结构模型：最多识别 2 行表头（多级表头按层级展开）

_YEAR_TOKEN_RE = re.compile(r"^\d{4}$")
_NUMERIC_TOKEN_RE = re.compile(r"^[+-]?\d[\d,]*(?:\.\d+)?%?$")

BBox = tuple[float, float, float, float]


@dataclass
class _Line:
    """单文本行：span 文本、几何 bbox 与最大字号。"""

    text: str
    bbox: BBox
    size: float


@dataclass(frozen=True)
class _TableCell:
    """表格单元格：文本、网格坐标、以及它在页面原生阅读序中的位置。"""

    text: str
    row: int
    col: int
    native_pos: int


@dataclass(frozen=True)
class _TableRow:
    """表格一行：按网格列序收下的单元格（文本形态由 ``_row_text`` 决定）。"""

    cells: tuple[_TableCell, ...]


@dataclass
class _Table:
    """一次表格提取结果：bbox、逐行单元格与结构模型（不含任何文本拼接决定）。"""

    index: int
    bbox: BBox
    rows: list[_TableRow]
    model: _TableModel | None = None


@dataclass(frozen=True)
class _TableModel:
    """表格结构模型（确定性表头识别 + 合并单元格几何，票 04 I-B1 落点）。

    为每个网格单元格提供行/列标签路径：
    - 行标签 = 数据行在首个数据形态单元格之前的文本（如产品名）；
    - 列标签 = 表头行链自下而上收集，合并单元格按 bbox 覆盖继承标签。

    只输出结构事实，不参与文本顺序——I1/I2（字符/顺序保真）仍由
    ``_row_text`` 决定，本模型绝不重排或改写单元格文本。
    """

    page: int
    table_index: int
    header_rows: tuple[int, ...]
    grid: tuple[tuple[str | None, ...], ...]
    anchored: tuple[tuple[tuple[int, tuple[float, float]], ...], ...]

    def ncols(self) -> int:
        return len(self.grid[0]) if self.grid else 0

    def cell_text(self, row: int, col: int) -> str:
        """网格单元格文本；越界/空位一律返回空串（不猜测内容）。"""
        if not (0 <= row < len(self.grid) and 0 <= col < len(self.grid[row])):
            return ""
        value = self.grid[row][col]
        return value if value is not None else ""

    def _column_center(self, col: int) -> float | None:
        """列 x 中心：由首个在该列锚定的单元格 bbox 决定（跨行一致）。"""
        for row_cells in self.anchored:
            for cell_col, (x0, x1) in row_cells:
                if cell_col == col:
                    return (x0 + x1) / 2.0
        return None

    def _row_label(self, row: int) -> str:
        """行标签：表头行无行标签；数据行取首个数据形态单元格之前的文本。"""
        if row in self.header_rows:
            return ""
        parts: list[str] = []
        for col in range(self.ncols()):
            text = self.cell_text(row, col)
            if not text:
                continue
            if _is_data_like(text):
                break
            parts.append(text)
        return " ".join(parts)

    def col_labels(self, col: int) -> tuple[str, ...]:
        """列标签链：自下而上遍历表头行，合并单元格按 bbox 覆盖继承。"""
        center = self._column_center(col)
        out: list[str] = []
        for header_row in reversed(self.header_rows):
            label: str | None = None
            if center is not None and header_row < len(self.anchored):
                for cell_col, (x0, x1) in self.anchored[header_row]:
                    if x0 <= center <= x1:
                        label = self.cell_text(header_row, cell_col)
                        break
            if label and label not in out:
                out.append(label)
        return tuple(out)

    def label_path(self, row: int, col: int) -> tuple[str, ...]:
        """(行标签, 列标签, 列标签父级, ...)——多级表头按层级展开。"""
        row_label = self._row_label(row)
        column_labels = self.col_labels(col)
        if row_label:
            return (row_label, *column_labels)
        return column_labels


def _is_data_like(text: str) -> bool:
    """数据形态文本：全部 token 为数字/百分比，且至少一个 token 非裸 4 位年份。

    裸 4 位年份（2023 等）视为期间标签而非数据值，避免把 ``2023 2024 2025``
    这类表头期间行误判成数据行。
    """
    tokens = text.split()
    if not tokens:
        return False
    for token in tokens:
        if not _NUMERIC_TOKEN_RE.match(token):
            return False
    return not all(_YEAR_TOKEN_RE.match(token) for token in tokens)


def _detect_header_rows(grid: list[list[str | None]]) -> tuple[int, ...]:
    """确定性表头识别：顶部连续的非数据形态行，最多 ``_MAX_HEADER_ROWS`` 行。

    - 非空单元格 <2 视为稀疏行（整行合并的标题等），跳过不计数、不打断扫描；
    - 数据形态单元格占比 ≥50% 判定为数据行，扫描终止；
    - 不使用模型/样式启发，只依赖网格文本形态。
    """
    header: list[int] = []
    for row_index, values in enumerate(grid):
        non_empty = [(col, value) for col, value in enumerate(values) if value and value.strip()]
        if len(non_empty) < 2:
            continue
        data_like = sum(1 for _, value in non_empty if _is_data_like(value))
        if data_like * 2 >= len(non_empty):
            break
        header.append(row_index)
        if len(header) >= _MAX_HEADER_ROWS:
            break
    return tuple(header)


def _anchored_cells(
    raw_rows: list[Any], nrows: int, ncols: int
) -> tuple[tuple[tuple[int, tuple[float, float]], ...], ...]:
    """每行锚定单元格（非合并覆盖位）的 (列号, (x0, x1))；与网格列对齐。

    ``table.rows[i].cells`` 在合并单元格的覆盖位上是 None，锚定位是 bbox 元组；
    此函数把「列 → x 区间」几何信息下沉进模型，供列标签合并继承使用。
    """
    out: list[tuple[tuple[int, tuple[float, float]], ...]] = []
    for row_index in range(nrows):
        if row_index >= len(raw_rows):
            out.append(())
            continue
        row_cells = tuple(raw_rows[row_index].cells)
        anchored: list[tuple[int, tuple[float, float]]] = []
        for col_index in range(min(len(row_cells), ncols)):
            bbox = row_cells[col_index]
            if bbox is not None:
                anchored.append((col_index, (float(bbox[0]), float(bbox[2]))))
        out.append(tuple(anchored))
    return tuple(out)


def _cell_native_pos(rect: tuple[float, float, float, float] | None, lines: list[_Line]) -> int:
    """单元格在页面原生阅读序中的位置：其矩形内第一条行的索引。

    用几何而非文本查找：子串查找会误命中（'21' 命中 '214' 内部），也会把同值
    单元格压到同一位置，从而打乱行内顺序。找不到行时排到最后（确定性）。
    """
    if rect is None:
        return len(lines)
    box: BBox = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
    for index, line in enumerate(lines):
        if _inside_any(line.bbox, [box]):
            return index
    return len(lines)


def _extractor_rev() -> str:
    return f"{READER_PDF_REV}+pymupdf-{pymupdf.__version__}"


def _garbled_ratio(text: str) -> float:
    """U+FFFD 与控制字符占比（换行/制表除外）；空文本为 0。"""
    if not text:
        return 0.0
    bad = sum(
        1
        for ch in text
        if ch == "\ufffd" or (unicodedata.category(ch) == "Cc" and ch not in "\n\t")
    )
    return bad / len(text)


def _join_spans(texts: list[str]) -> str:
    """行内 span 拼接：两侧均为 ASCII 字母数字时补空格，CJK 直接相连。"""
    out = ""
    for piece in texts:
        if (
            out
            and piece
            and out[-1].isascii()
            and out[-1].isalnum()
            and piece[0].isascii()
            and piece[0].isalnum()
        ):
            out += " "
        out += piece
    return out


def _page_lines(page: pymupdf.Page) -> list[_Line]:
    """从 dict 提取行级文本与坐标（保留提取次序）。"""
    payload = cast(dict[str, Any], page.get_text("dict"))
    lines: list[_Line] = []
    for block in payload.get("blocks", []):
        if block.get("type") != 0:
            continue  # 图片块由 get_images 单独记账
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if str(s.get("text", "")).strip()]
            if not spans:
                continue
            boxes: list[BBox] = [
                (float(s["bbox"][0]), float(s["bbox"][1]), float(s["bbox"][2]), float(s["bbox"][3]))
                for s in spans
            ]
            bbox = (
                min(b[0] for b in boxes),
                min(b[1] for b in boxes),
                max(b[2] for b in boxes),
                max(b[3] for b in boxes),
            )
            size = max(float(s.get("size", 0.0)) for s in spans)
            lines.append(
                _Line(text=_join_spans([str(s["text"]) for s in spans]), bbox=bbox, size=size)
            )
    return lines


def _split_columns(lines: list[_Line], page_width: float) -> tuple[list[_Line], list[_Line]] | None:
    """检测确定性左右分栏：存在超宽横向空隙且两侧行纵向并排。"""
    ordered = sorted(lines, key=lambda item: item.bbox[0])
    best_gap = 0.0
    split_x: float | None = None
    for left, right in pairwise(ordered):
        gap = right.bbox[0] - left.bbox[2]
        if gap > best_gap:
            best_gap = gap
            split_x = (left.bbox[2] + right.bbox[0]) / 2
    if split_x is None or best_gap <= page_width * _COLUMN_GAP_RATIO:
        return None
    left_lines = [item for item in lines if (item.bbox[0] + item.bbox[2]) / 2 < split_x]
    right_lines = [item for item in lines if (item.bbox[0] + item.bbox[2]) / 2 >= split_x]
    if not left_lines or not right_lines:
        return None
    for left in left_lines:
        for right in right_lines:
            overlap = min(left.bbox[3], right.bbox[3]) - max(left.bbox[1], right.bbox[1])
            shorter = min(left.bbox[3] - left.bbox[1], right.bbox[3] - right.bbox[1])
            if shorter > 0 and overlap > shorter * 0.5:
                return left_lines, right_lines
    return None


def _merge_lines(lines: list[_Line]) -> list[list[_Line]]:
    """几何装配段落：纵向间隙小于行高 0.8 倍且横向有交叠的行并入同段。

    保留传入行的原生阅读序（pymupdf 块→行序）；不再做全局 ``(y,x)`` 重排，
    否则会把跨块的正文连读性打散（I3-3 34 条逐字引文被重排破坏）。页内流已按
    原生序送入，单栏页原生序≈``(y,x)`` 序，分组结果不变。
    """
    ordered = list(lines)
    merged: list[list[_Line]] = []
    for line in ordered:
        if merged:
            prev = merged[-1][-1]
            prev_height = prev.bbox[3] - prev.bbox[1]
            gap = line.bbox[1] - prev.bbox[3]
            horizontal = min(prev.bbox[2], line.bbox[2]) - max(prev.bbox[0], line.bbox[0])
            if prev_height > 0 and gap < prev_height * 0.8 and horizontal > 0:
                merged[-1].append(line)
                continue
        merged.append([line])
    return merged


def _count_grid_lines(page: pymupdf.Page) -> int:
    """统计近似水平/垂直的制表线数量（用于“有线无表”冲突检测）。"""
    horizontal = vertical = 0
    for drawing in page.get_drawings():
        for item in drawing.get("items", []):
            if item[0] != "l":
                continue
            p1, p2 = item[1], item[2]
            if abs(p1.y - p2.y) < 0.5 and abs(p1.x - p2.x) > 20:
                horizontal += 1
            elif abs(p1.x - p2.x) < 0.5 and abs(p1.y - p2.y) > 20:
                vertical += 1
    return horizontal + vertical if (horizontal >= 3 and vertical >= 3) else 0


def _extract_tables(
    page: pymupdf.Page, lines: list[_Line]
) -> tuple[list[_Table], list[ReaderIssue]]:
    """受控表格读取（单次 find_tables 调用）；失败/冲突全部显式记账。

    只读取结构事实（单元格文本 + 网格坐标 + 原生序位置），**不决定文本形态**：
    拼接交给 ``_row_text``，以守住 I1（不插入原文没有的字符）与 I2（顺序服从
    页面原生阅读序）。
    """
    issues: list[ReaderIssue] = []
    assert page.number is not None
    where = f"page:{page.number + 1}"
    try:
        finder = page.find_tables()
        raw_tables: list[Any] = list(finder.tables)  # type: ignore[attr-defined]
    except Exception as exc:  # 提取失败 ≠ 原文没有表格
        return [], [
            ReaderIssue(
                code="table_extraction_failed",
                location=where,
                detail=f"表格提取器异常: {type(exc).__name__}: {exc}",
            )
        ]
    tables: list[_Table] = []
    for index, table in enumerate(raw_tables):
        grid: list[list[str | None]] = table.extract()
        raw_rows: list[Any] = list(table.rows)
        bbox: BBox = (
            float(table.bbox[0]),
            float(table.bbox[1]),
            float(table.bbox[2]),
            float(table.bbox[3]),
        )
        model = _TableModel(
            page=page.number + 1,
            table_index=index,
            header_rows=_detect_header_rows(grid),
            grid=tuple(tuple(values) for values in grid),
            anchored=_anchored_cells(raw_rows, len(grid), len(grid[0]) if grid else 0),
        )
        rows: list[_TableRow] = []
        for row_index, values in enumerate(grid):
            rects: tuple[Any, ...] = (
                tuple(raw_rows[row_index].cells) if row_index < len(raw_rows) else ()
            )
            rows.append(
                _TableRow(
                    cells=tuple(
                        _TableCell(
                            text=str(value),
                            row=row_index,
                            col=col_index,
                            native_pos=_cell_native_pos(
                                rects[col_index] if col_index < len(rects) else None, lines
                            ),
                        )
                        for col_index, value in enumerate(values)
                        if value is not None and str(value).strip()
                    )
                )
            )
        tables.append(_Table(index=index, bbox=bbox, rows=rows, model=model))
    if not tables:
        grid_lines = _count_grid_lines(page)
        if grid_lines >= _MIN_GRID_LINES:
            issues.append(
                ReaderIssue(
                    code="table_lines_without_extraction",
                    location=where,
                    detail=f"检测到 {grid_lines} 条制表线但表格提取为空，进入复核",
                )
            )
    return tables, issues


def _inside_any(bbox: BBox, boxes: list[BBox]) -> bool:
    x_center = (bbox[0] + bbox[2]) / 2
    y_center = (bbox[1] + bbox[3]) / 2
    return any(box[0] <= x_center <= box[2] and box[1] <= y_center <= box[3] for box in boxes)


def _union_bbox(boxes: list[BBox]) -> BBox:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _is_heading(line: _Line, median_size: float) -> bool:
    """字号显著大于页中位数且长度有限的行判为标题（确定性字号规则）。"""
    return (
        median_size > 0
        and line.size >= median_size * _HEADING_SIZE_FACTOR
        and len(line.text) <= _HEADING_MAX_CHARS
    )


def _emit_paragraphs(
    prose: list[_Line],
    ordinal: int,
    *,
    page_no: int,
    page_status: UnitStatus,
    page_reasons: tuple[str, ...],
    units: list[CandidateUnit],
) -> int:
    """装配并发射累积正文（随后清空 ``prose``）；返回新的 ordinal。"""
    for paragraph in _merge_lines(prose):
        ordinal += 1
        units.append(
            CandidateUnit(
                ordinal=ordinal,
                kind="paragraph",
                status=page_status,
                reasons=page_reasons,
                raw_text="\n".join(line.text for line in paragraph),
                location=UnitLocation(
                    page=page_no, bbox=_union_bbox([line.bbox for line in paragraph])
                ),
            )
        )
    prose.clear()
    return ordinal


def _row_text(row: _TableRow) -> tuple[str, tuple[tuple[int, int], ...]]:
    """行文本与结构定位（表格发射的两条不变量落点）。

    I1（字符保真）：单元格之间只用换行，不插入原文里不存在的字符（旧实现插入
    ``" | "``，破坏了"去空白连续"的口径）。
    I2（顺序保真）：文本顺序服从页面原生阅读序（``native_pos``）；网格行列只作为
    locator 元数据随单元下发，绝不用于重排文本。
    """
    ordered = sorted(row.cells, key=lambda cell: (cell.native_pos, cell.col))
    return (
        "\n".join(cell.text for cell in ordered),
        tuple((cell.row, cell.col) for cell in ordered),
    )


def _emit_table(
    table: _Table,
    ordinal: int,
    *,
    page_no: int,
    page_lines: list[_Line],
    units: list[CandidateUnit],
    issues: list[ReaderIssue],
) -> int:
    """发射一张表的行单元，并按页级行流记账 overlap；返回新的 ordinal。"""
    overlap = sum(1 for line in page_lines if _inside_any(line.bbox, [table.bbox]))
    if overlap:
        issues.append(
            ReaderIssue(
                code="table_text_overlap",
                location=f"page:{page_no}",
                detail=f"表格 tbl[{table.index}] 区域含 {overlap} 行正文文字，"
                "已从正文单元剔除并计入表格行",
            )
        )
    for row in table.rows:
        row_text, cells = _row_text(row)
        if not row_text.strip():
            continue
        ordinal += 1
        # 与 cells 对齐的结构标签路径（每格 = " ".join(label_path)）；无模型时为空。
        label_path: tuple[str, ...] = ()
        if table.model is not None:
            label_path = tuple(
                " ".join(table.model.label_path(cell_row, cell_col)) for cell_row, cell_col in cells
            )
        units.append(
            CandidateUnit(
                ordinal=ordinal,
                kind="table_row",
                status=UnitStatus.KEPT,
                reasons=(f"tbl[{table.index}]",),
                raw_text=row_text,
                location=UnitLocation(
                    page=page_no, bbox=table.bbox, cells=cells, label_path=label_path
                ),
            )
        )
    return ordinal


def read_pdf(path: str | Path) -> ReaderResult:
    """读取 PDF 为候选单元；失败与降级全部显式记账。"""
    fmt, file_path = detect_format(path)
    units: list[CandidateUnit] = []
    issues: list[ReaderIssue] = []
    ordinal = 0
    page_count = 0
    with pymupdf.open(str(file_path)) as document:
        page_count = int(document.page_count)
        for page in document:
            assert page.number is not None
            page_no = page.number + 1
            lines = _page_lines(page)
            tables, table_issues = _extract_tables(page, lines)
            issues.extend(table_issues)
            if not lines:
                if page.get_images(full=True):
                    issues.append(
                        ReaderIssue(
                            code="image_only_page",
                            location=f"page:{page_no}",
                            detail="无文字层且有图片，需 OCR（未自动执行）",
                        )
                    )
                else:
                    issues.append(
                        ReaderIssue(
                            code="empty_page",
                            location=f"page:{page_no}",
                            detail="无文字层且无图片",
                        )
                    )
                continue

            garbled = _garbled_ratio("\n".join(line.text for line in lines))
            garbled_page = garbled > _GARBLED_MAX_RATIO
            if garbled_page:
                issues.append(
                    ReaderIssue(
                        code="garbled_text",
                        location=f"page:{page_no}",
                        detail=f"乱码字符占比 {garbled:.2%} 超过阈值 {_GARBLED_MAX_RATIO:.0%}",
                    )
                )

            columns = _split_columns(lines, float(page.rect.width))
            if columns is not None:
                issues.append(
                    ReaderIssue(
                        code="multi_column_order_unreliable",
                        location=f"page:{page_no}",
                        detail="检测到左右分栏并排文本；阅读次序保留 pymupdf 原生序（强制"
                        "先左栏后右栏会在「单栏正文+浮动侧栏」版式上误判并撕断句子，I3-3 实测净 -5），"
                        "保留该标记供人工复核",
                    )
                )
            # 只标记、不重排：_split_columns 是全局 (y,x) 重排时代的补偿性补丁；
            # 重排移除后再强制左→右，等于把浮动侧栏当第二栏整块搬到页尾。
            ordered_columns = [lines]

            median_size = statistics.median([line.size for line in lines])
            page_reasons: tuple[str, ...] = (
                ("multi_column_order_flagged",) if columns is not None else ()
            )
            page_status = UnitStatus.REVIEW_REQUIRED if garbled_page else UnitStatus.KEPT

            # 混合页图片记账（F4 + 复核 R3）：有文字层的页面同样检查图片区域——
            # 文字层未覆盖的图片内容不静默消失。面积阈值只决定复核优先级，
            # 不决定区域是否进入台账：≥阈值记 OCR/人工复核缺口，小图按装饰
            # 噪声显式记账（不阻断整篇，也不无记录消失）。
            page_area = float(page.rect.width) * float(page.rect.height)
            for image in page.get_images(full=True):
                for rect in page.get_image_rects(image[0]):
                    area = (rect.x1 - rect.x0) * (rect.y1 - rect.y0)
                    if page_area <= 0:
                        continue
                    if area >= page_area * _IMAGE_REGION_RATIO:
                        issues.append(
                            ReaderIssue(
                                code="image_region_unreadable",
                                location=f"page:{page_no}",
                                detail=f"图片区域 ({rect.x0:.0f},{rect.y0:.0f},"
                                f"{rect.x1:.0f},{rect.y1:.0f}) 占页面 {area / page_area:.0%}，"
                                "文字层未覆盖，需 OCR/人工复核",
                            )
                        )
                    else:
                        issues.append(
                            ReaderIssue(
                                code="image_region_small",
                                location=f"page:{page_no}",
                                detail=f"图片区域 ({rect.x0:.0f},{rect.y0:.0f},"
                                f"{rect.x1:.0f},{rect.y1:.0f}) 占页面 {area / page_area:.0%}，"
                                "低于缺口阈值，按装饰噪声记账（文字层不覆盖其内容）",
                            )
                        )

            # 有序区域流（F3）：行按几何次序流经正文累积器，遇标题/表格边界即
            # flush，保持同页标题/正文/表格的交错阅读次序，不再整页分阶段发射。
            emitted_tables: set[int] = set()
            for column_lines in ordered_columns:
                prose: list[_Line] = []
                # 保留 pymupdf 原生块→行阅读序，不再做全局 (y,x) 重排：
                # 全局重排会把跨块正文连读性打散（I3-3 的 34 条逐字引文根因）。
                # column_lines 来自 _split_columns/页内流，本身已保持原生相对序。
                for line in column_lines:
                    hits = [table for table in tables if _inside_any(line.bbox, [table.bbox])]
                    if hits:
                        if _is_heading(line, median_size):
                            issues.append(
                                ReaderIssue(
                                    code="table_text_overlap",
                                    location=f"page:{page_no}",
                                    detail=f"标题文字 {line.text!r} 位于表格区域内，不重复计入正文",
                                )
                            )
                        ordinal = _emit_paragraphs(
                            prose,
                            ordinal,
                            page_no=page_no,
                            page_status=page_status,
                            page_reasons=page_reasons,
                            units=units,
                        )
                        for table in hits:
                            if table.index not in emitted_tables:
                                emitted_tables.add(table.index)
                                ordinal = _emit_table(
                                    table,
                                    ordinal,
                                    page_no=page_no,
                                    page_lines=lines,
                                    units=units,
                                    issues=issues,
                                )
                        continue
                    if _is_heading(line, median_size):
                        ordinal = _emit_paragraphs(
                            prose,
                            ordinal,
                            page_no=page_no,
                            page_status=page_status,
                            page_reasons=page_reasons,
                            units=units,
                        )
                        ordinal += 1
                        units.append(
                            CandidateUnit(
                                ordinal=ordinal,
                                kind="heading",
                                status=page_status,
                                reasons=(*page_reasons, "heading_by_font_size"),
                                raw_text=line.text,
                                location=UnitLocation(page=page_no, bbox=line.bbox),
                            )
                        )
                        continue
                    prose.append(line)
                ordinal = _emit_paragraphs(
                    prose,
                    ordinal,
                    page_no=page_no,
                    page_status=page_status,
                    page_reasons=page_reasons,
                    units=units,
                )

            # 未被任何行命中的表格（如纯矢量/空单元格表）按 bbox 次序补发，不静默丢失。
            for table in sorted(
                (table for table in tables if table.index not in emitted_tables),
                key=lambda table: table.bbox[1],
            ):
                ordinal = _emit_table(
                    table, ordinal, page_no=page_no, page_lines=lines, units=units, issues=issues
                )

    return ReaderResult(
        format=fmt,
        extractor_rev=_extractor_rev(),
        source_path=str(file_path),
        page_count=page_count,
        units=tuple(units),
        issues=tuple(issues),
    )
