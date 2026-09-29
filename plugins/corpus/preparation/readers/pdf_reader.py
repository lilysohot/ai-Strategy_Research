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

READER_PDF_REV = "reader-pdf-9"

_GARBLED_MAX_RATIO = 0.05
_HEADING_SIZE_FACTOR = 1.15
_HEADING_MAX_CHARS = 80
_COLUMN_GAP_RATIO = 0.12
_MIN_GRID_LINES = 6
_IMAGE_REGION_RATIO = 0.25  # 混合页大图缺口阈值（占页面积比例）
_MAX_HEADER_ROWS = 2  # 表格结构模型：最多识别 2 行表头（多级表头按层级展开）

# R8（S1-S3）：无线表格 fallback——lines 策略 0 表时的确定性形态信号与提取参数。
_WIRELESS_MIN_ROWS = 5  # 表格化数据块最少连续数据视觉行
_WIRELESS_MIN_TOKENS = 3  # 数据视觉行最少数字 token 数
_WIRELESS_ROW_BREAK = 20.0  # 数据块纵向断裂间隔（pt）
_WIRELESS_MIN_COLS = 3  # 表格化判定：数字格 x0 对齐列数下限
_WIRELESS_COL_TOL = 3.0  # 数字格列对齐容差（pt）
_WIRELESS_SEAM_RATIO = 0.5  # 中缝判别：右栏视觉行起头于中缝右缘的最小占比
_WIRELESS_SEAM_TOL = 12.0  # 「起头于中缝右缘」的 x 容差（容纳二级科目缩进约一字宽）
_WIRELESS_HEADER_PAD = 30.0  # 数据块上方表头预留（pt）
_WIRELESS_FOOT_PAD = 15.0  # 数据块下方预留（pt）
# R8（S4）：相邻网格行 bbox 纵向重叠 → 行切分错乱，该行行内序改按网格列序。
_ROW_OVERLAP_MIN = 1.0
# R9：同一逻辑行的取值行与其「同比增长」续行被 find_tables 拆成相邻两网格行，且
# 取值格把多个子值并成单个单元、在 native 序中留下幻影空隙。行内按 native 分组的
# 容差放宽到 4：足以吞掉取值格折叠子行产生的空隙（≤3），又不会跨产品（产品由
# 网格行对隔开）。
_NATIVE_MERGE_GAP = 4
_WIRELESS_PLACEHOLDER = "·"  # text 策略空位占位符（清洗为空格）

_YEAR_TOKEN_RE = re.compile(r"^\d{4}$")
_NUMERIC_TOKEN_RE = re.compile(r"^[+-]?\d[\d,]*(?:\.\d+)?%?$")

BBox = tuple[float, float, float, float]


@dataclass
class _Line:
    """单文本行：文字、几何、字号，以及原生文本块的局部样式。"""

    text: str
    bbox: BBox
    size: float
    # PDF 原生文本块仅作为局部结构信号。缺省值保留给合成测试或没有块信息的调用方。
    block_index: int = -1
    block_line_count: int = 1
    block_min_size: float = 0.0
    block_max_size: float = 0.0


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
    # R8 S4：行网格错乱（相邻行 bbox 纵向重叠）的行号；发射时行内序改按网格列序。
    column_ordered_rows: frozenset[int] = frozenset()


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
    for block_index, block in enumerate(payload.get("blocks", [])):
        if block.get("type") != 0:
            continue  # 图片块由 get_images 单独记账
        block_lines: list[tuple[str, BBox, float]] = []
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
            block_lines.append((_join_spans([str(s["text"]) for s in spans]), bbox, size))
        if not block_lines:
            continue
        block_min_size = min(line[2] for line in block_lines)
        block_max_size = max(line[2] for line in block_lines)
        for text, bbox, size in block_lines:
            lines.append(
                _Line(
                    text=text,
                    bbox=bbox,
                    size=size,
                    block_index=block_index,
                    block_line_count=len(block_lines),
                    block_min_size=block_min_size,
                    block_max_size=block_max_size,
                )
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
            same_known_block = (
                prev.block_index >= 0
                and line.block_index >= 0
                and prev.block_index == line.block_index
            )
            crosses_multiline_blocks = (
                prev.block_index >= 0
                and line.block_index >= 0
                and not same_known_block
                and (prev.block_line_count > 1 or line.block_line_count > 1)
            )
            if (
                not crosses_multiline_blocks
                and prev_height > 0
                and gap < prev_height * 0.8
                and horizontal > 0
            ):
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


def _overlapping_row_indices(raw_rows: list[Any]) -> frozenset[int]:
    """相邻网格行 bbox 纵向重叠的行号集合（行切分错乱信号，R8 S4）。

    正常表格行边界链式相接；跨栏续表左右两侧行高不一致时，find_tables 的统一
    行网格互相咬合（重叠），重叠行的 ``native_pos`` 序会被跨栏内容流打乱。
    """
    out: set[int] = set()
    for index in range(len(raw_rows) - 1):
        upper = raw_rows[index].bbox
        lower = raw_rows[index + 1].bbox
        overlap = min(float(upper[3]), float(lower[3])) - max(float(upper[1]), float(lower[1]))
        if overlap > _ROW_OVERLAP_MIN:
            out.add(index)
            out.add(index + 1)
    return frozenset(out)


def _clean_grid(grid: list[list[str | None]]) -> list[list[str | None]]:
    """规整提取网格：text 策略的空位占位符 ``·`` 清洗为 None（不猜测内容）。"""
    return [
        [
            None if value is None or str(value).strip() == _WIRELESS_PLACEHOLDER else str(value)
            for value in row
        ]
        for row in grid
    ]


def _build_table(page_no: int, index: int, table: Any, lines: list[_Line]) -> _Table:
    """把一次 find_tables 的原始结果装配为 :class:`_Table`（结构事实，不做文本拼接）。"""
    grid = _clean_grid(table.extract())
    raw_rows: list[Any] = list(table.rows)
    bbox: BBox = (
        float(table.bbox[0]),
        float(table.bbox[1]),
        float(table.bbox[2]),
        float(table.bbox[3]),
    )
    model = _TableModel(
        page=page_no,
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
    return _Table(
        index=index,
        bbox=bbox,
        rows=rows,
        model=model,
        column_ordered_rows=_overlapping_row_indices(raw_rows),
    )


def _visual_rows(lines: list[_Line]) -> list[tuple[float, float, list[_Line]]]:
    """按 y 重叠把行级单元聚成视觉行（仅用于无线表格形态检测，不改发射顺序）。"""
    rows: list[tuple[float, float, list[_Line]]] = []
    for line in sorted(lines, key=lambda item: (item.bbox[1], item.bbox[0])):
        if rows:
            top, bottom, members = rows[-1]
            overlap = min(bottom, line.bbox[3]) - max(top, line.bbox[1])
            height = min(bottom - top, line.bbox[3] - line.bbox[1])
            if height > 0 and overlap > height * 0.5:
                rows[-1] = (min(top, line.bbox[1]), max(bottom, line.bbox[3]), [*members, line])
                continue
        rows.append((line.bbox[1], line.bbox[3], [line]))
    return rows


def _is_data_line(line: _Line) -> bool:
    """行级单元含至少一个数字 token（百分比/千分位/小数均算）。"""
    return any(_NUMERIC_TOKEN_RE.match(token) for token in line.text.split())


def _wireless_table_block(
    lines: list[_Line],
) -> tuple[float, float, float, float, list[_Line]] | None:
    """无线表格形态检测（确定性：连续数据视觉行 + 数字格列对齐，无样式启发）。

    返回 ``(x0, y_top, x1, y_bottom, 块内行级单元)``；无表格形态返回 None。
    条件足够严格：页脚散数字、纯正文段落不构成候选（行数/每行 token 数/列对齐
    三重门槛），因此 fallback 只在真正的无线预测表页触发。
    """
    runs: list[list[tuple[float, float, list[_Line]]]] = []
    run: list[tuple[float, float, list[_Line]]] = []
    for row in _visual_rows(lines):
        token_count = sum(
            1
            for member in row[2]
            for token in member.text.split()
            if _NUMERIC_TOKEN_RE.match(token)
        )
        if token_count >= _WIRELESS_MIN_TOKENS:
            if run and row[0] - run[-1][1] > _WIRELESS_ROW_BREAK:
                runs.append(run)
                run = []
            run.append(row)
        elif run:
            runs.append(run)
            run = []
    if run:
        runs.append(run)
    qualifying = [item for item in runs if len(item) >= _WIRELESS_MIN_ROWS]
    if not qualifying:
        return None
    data_lines = [
        line for item in qualifying for row in item for line in row[2] if _is_data_line(line)
    ]
    # 列对齐（锚点法）：数字格 x0 聚类数须 ≥ 下限，排除页脚/尾注散数字。
    anchors: list[float] = []
    for x in sorted(line.bbox[0] for line in data_lines):
        if not anchors or x - anchors[-1] > _WIRELESS_COL_TOL:
            anchors.append(x)
    if len(anchors) < _WIRELESS_MIN_COLS:
        return None
    y_top = min(row[0] for item in qualifying for row in item) - _WIRELESS_HEADER_PAD
    y_bottom = max(row[1] for item in qualifying for row in item) + _WIRELESS_FOOT_PAD
    x0 = min(line.bbox[0] for item in qualifying for row in item for line in row[2])
    x1 = max(line.bbox[2] for item in qualifying for row in item for line in row[2])
    # 分栏检测需要块内**全部**行级单元（含行标签列）：中缝判别依赖右栏首列
    # 的左对齐非数字形态，只有数字格 x 区间看不出对齐方式；且空白带由全部行级
    # 单元的 x 间隙构成，clip 边界才不会把右栏首列文字（如「EPS(摊薄)（元）」）撕开。
    block_lines = [line for item in qualifying for row in item for line in row[2]]
    return max(x0, 0.0), max(y_top, 0.0), x1, y_bottom, block_lines


def _wireless_split_x(lines: list[_Line], page_width: float) -> tuple[float, float] | None:
    """并排分栏中缝检测：返回零文本空白带 ``(left_edge, right_edge)``。

    中缝的判别特征不是「最宽间隙」（无线表内部列间隙常与中缝同量级），而是
    **右栏行首对齐**：中缝右侧是另一张表的首列（行标签，左对齐），其几乎每个
    视觉行都有一条**非数字**行级单元从中缝右缘起头；表内列间隙右侧是右对齐
    数字格，起头散布且均为数字，达不到占比。clip 边界落在空白带内，不会撕裂
    任何文本行。
    """
    min_gap = max(5.0, page_width * 0.008)
    ordered = sorted(lines, key=lambda line: (line.bbox[0], line.bbox[2]))
    best: tuple[float, float, float] | None = None  # (宽度, left_edge, right_edge)
    for left, right in pairwise(ordered):
        lo, hi = left.bbox[2], right.bbox[0]
        if hi - lo < min_gap:
            continue
        if not _seam_right_aligned(lines, lo, hi):
            continue
        if best is None or hi - lo > best[0]:
            best = (hi - lo, lo, hi)
    if best is None:
        return None
    return best[1], best[2]


def _seam_right_aligned(lines: list[_Line], lo: float, hi: float) -> bool:
    """候选空白带右缘是否呈「右栏行首对齐」形态（并排两表首列的确定性特征）。

    左右两侧各自聚成视觉行：任一侧行数不足（不成表）即否决；右栏视觉行中
    起头于右缘 ``hi`` 附近（容差内含二级科目缩进）的占比低于阈值即否决；
    起头单元以数字为主也否决（右对齐数字列即使等宽聚拢，起头单元仍是数字，
    不构成标签列形态）。
    """
    left_rows = _visual_rows([line for line in lines if line.bbox[2] <= lo + 0.5])
    right_rows = _visual_rows([line for line in lines if line.bbox[0] >= hi - 0.5])
    if len(left_rows) < _WIRELESS_MIN_ROWS or len(right_rows) < _WIRELESS_MIN_ROWS:
        return False
    aligned = [
        member
        for _, _, members in right_rows
        for member in members
        if member.bbox[0] <= hi + _WIRELESS_SEAM_TOL
    ]
    aligned_rows = sum(
        1
        for _, _, members in right_rows
        if any(member.bbox[0] <= hi + _WIRELESS_SEAM_TOL for member in members)
    )
    if aligned_rows / len(right_rows) < _WIRELESS_SEAM_RATIO:
        return False
    non_numeric = sum(1 for member in aligned if not _is_data_line(member))
    return non_numeric / len(aligned) >= _WIRELESS_SEAM_RATIO


def _extract_wireless_tables(page: pymupdf.Page, lines: list[_Line]) -> list[_Table]:
    """lines 策略 0 表时的无线表格 fallback：数据块 → 分栏 clip → text 策略。

    R8 S1-S3：财务预测表常无制表线（lines 策略检测不到），且资产负债表｜利润表
    双栏并排、左右行高不一致——整页单网格会把左右两栏揉成一张错乱大表。按数字
    格 x 空隙切分左右栏、各自 ``find_tables(clip, strategy="text")`` 独立成表，
    行/列网格与 cells 才能逐表正确。text 策略对无表格形态区域提取为空，即安全阀。
    """
    block = _wireless_table_block(lines)
    if block is None:
        return []
    x0, y_top, x1, y_bottom, block_lines = block
    page_width = float(page.rect.width)
    # 中缝是零文本空白带，clip 边界取带内中点，不会撕裂任何文本行。
    seam = _wireless_split_x(block_lines, page_width)
    if seam is not None:
        lo, hi = seam
        middle = (lo + hi) / 2.0
        clips = [
            pymupdf.Rect(max(x0, 0.0), y_top, middle, y_bottom),
            pymupdf.Rect(middle, y_top, x1, y_bottom),
        ]
    else:
        clips = [pymupdf.Rect(max(x0, 0.0), y_top, x1, y_bottom)]
    tables: list[_Table] = []
    assert page.number is not None
    for clip in clips:
        try:
            finder = page.find_tables(clip=clip, strategy="text")
        except Exception:  # fallback 失败不致命：保持 0 表现状，不猜测内容
            continue
        for raw in finder.tables:  # type: ignore[union-attr]
            tables.append(_build_table(page.number + 1, len(tables), raw, lines))
    return tables


def _extract_tables(
    page: pymupdf.Page, lines: list[_Line]
) -> tuple[list[_Table], list[ReaderIssue]]:
    """受控表格读取；失败/冲突全部显式记账。

    只读取结构事实（单元格文本 + 网格坐标 + 原生序位置），**不决定文本形态**：
    拼接交给 ``_row_text``，以守住 I1（不插入原文没有的字符）与 I2（顺序服从
    页面原生阅读序）。lines 策略 0 表且页面存在无线表格形态时，走
    ``_extract_wireless_tables`` fallback（R8 S1-S3）。
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
    tables = [
        _build_table(page.number + 1, index, table, lines) for index, table in enumerate(raw_tables)
    ]
    if not tables:
        tables = _extract_wireless_tables(page, lines)
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
    # 研报页常混排大量小字号表格／页脚，页中位数会被拉低。若一个原生多行文本块
    # 的字号基本一致，它更像同一段排版正文；不能因为每一行都高于页面中位数就把
    # 整段拆成 heading。块内存在明显字号层次时，仍由原有字号规则处理标题行。
    uniform_multiline_block = (
        line.block_line_count > 1
        and line.block_max_size - line.block_min_size <= max(0.5, line.block_max_size * 0.05)
    )
    if uniform_multiline_block:
        return False
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
    R9：双栏并存（跨栏续表/无线预测表）被 find_tables 揉成一张合并网格时，网格
    行 bbox 会与相邻行大量纵向重叠，把几乎整表误判为错乱行。universality 探针
    已证明页面原生流（``native_pos`` 次序）即为 gold 引文的地面真值阅读序，按
    网格列序强排反而会把左半列数值插进右半列标签与数值之间、打断引文连续
    （图6 续表「尿素/产能/价格分位」即此类）。故行内一律按 ``native_pos`` 原生
    阅读序发射。
    """
    ordered = sorted(row.cells, key=lambda cell: (cell.native_pos, cell.col))
    return (
        "\n".join(cell.text for cell in ordered),
        tuple((cell.row, cell.col) for cell in ordered),
    )


def _is_bare_data_row(row: _TableRow) -> bool:
    """纯数值续行判定：整行只有数据形态单元格、无行标签/表头。

    跨栏续表里，同一逻辑产品行的「产能值」与其「同比增长」续行会被 find_tables
    拆成相邻两行：续行不含产品名等标签，全是数值。它不属于独立逻辑行，应并入
    前一行，否则会把同一产品行的 e5 取值（24.0 28.5 28.5 - 18.8% 0.0%）切成个
    独立单元。
    """
    return bool(row.cells) and all(
        _is_data_like(cell.text) or cell.text.strip() in ("-", "–", "—", "/") for cell in row.cells
    )


def _native_groups(table: _Table) -> list[tuple[_TableCell, ...]]:
    """把整表单元格重排为发射单元（R9 核心：以页面原生阅读序为主键）。

    合并网格（跨栏续表/无线预测表被 find_tables 揉成一张）的 grid 行 bbox 互相
    咬合错乱：同一逻辑行（如 R32「24.0 28.5 28.5 - 18.8% 0.0%」）会被拆进相邻
    网格行，而相邻逻辑行的右半格又插进中间（第 10 页图6 续表 12 列）。per-grid
    row 发射无法同时守住 e3/e4 与 e5：先按行序再行内 native 序，等于仍以错乱
    的 grid 行作主键。universality 探针已证明页面原生流（``native_pos`` 次序）是
    gold 引文的地面真值阅读序。因此先做两层归并，再按 native 连续性切成组、随后
    跨组统一按 native 序发射：
    - 逻辑行归并：纯数值续行并入前一逻辑行（R9 续行修复）；
    - 组内归并：同一逻辑行内按 native 连续性切组，容差 ``_NATIVE_MERGE_GAP``
      吞掉取值格折叠子行留下的幻影空隙（R9），使 e5 六个取值归入一个单元。

    普通有线表每行自带标签、无续行、行内 native 连续，归并不触发、组 == 行，
    行为不变。
    """
    combined: list[list[_TableCell]] = []
    for row in table.rows:
        if combined and _is_bare_data_row(row):
            combined[-1].extend(row.cells)
        else:
            combined.append(list(row.cells))
    groups: list[tuple[_TableCell, ...]] = []
    for cells in combined:
        ordered = sorted(cells, key=lambda cell: (cell.native_pos, cell.col))
        segment: list[_TableCell] = []
        for cell in ordered:
            if segment and cell.native_pos - segment[-1].native_pos > _NATIVE_MERGE_GAP:
                groups.append(tuple(segment))
                segment = []
            segment.append(cell)
        if segment:
            groups.append(tuple(segment))
    # 跨行/跨组统一按原生阅读序发射：native 位最靠前的单元格所在组优先。
    groups.sort(
        key=lambda group: (min(cell.native_pos for cell in group), min(cell.col for cell in group))
    )
    return groups


def _emit_table(
    table: _Table,
    ordinal: int,
    *,
    page_no: int,
    page_lines: list[_Line],
    units: list[CandidateUnit],
    issues: list[ReaderIssue],
) -> int:
    """发射一张表的连续组单元，并按页级行流记账 overlap；返回新的 ordinal。"""
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
    for group in _native_groups(table):
        row_text, cells = _row_text(_TableRow(cells=group))
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
