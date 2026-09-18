"""PDF 读取 Adapter（架构 v1.1 §5.3）。

读取页、文本行/块坐标与字号，按确定性规则装配段落与标题；表格读取作为受控
Adapter：表格区域内文字从正文剔除并计入表格行单元（不静默拼接两份重复正文），
提取失败、或存在成网状制表线却提取不到表格，均记录冲突信号进入复核。空文字页、
疑似图片页、乱码页与多栏页分别标记，不按全文平均字符数放行。
"""

from __future__ import annotations

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

READER_PDF_REV = "reader-pdf-2"

_GARBLED_MAX_RATIO = 0.05
_HEADING_SIZE_FACTOR = 1.15
_HEADING_MAX_CHARS = 80
_COLUMN_GAP_RATIO = 0.12
_MIN_GRID_LINES = 6
_IMAGE_REGION_RATIO = 0.25  # 混合页大图缺口阈值（占页面积比例）

BBox = tuple[float, float, float, float]


@dataclass
class _Line:
    """单文本行：span 文本、几何 bbox 与最大字号。"""

    text: str
    bbox: BBox
    size: float


@dataclass
class _Table:
    """一次表格提取结果：bbox 与逐行文本。"""

    index: int
    bbox: BBox
    rows: list[str]


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
    """几何装配段落：纵向间隙小于行高 0.8 倍且横向有交叠的行并入同段。"""
    ordered = sorted(lines, key=lambda item: (item.bbox[1], item.bbox[0]))
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


def _extract_tables(page: pymupdf.Page) -> tuple[list[_Table], list[ReaderIssue]]:
    """受控表格读取（单次 find_tables 调用）；失败/冲突全部显式记账。"""
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
        rows = [" | ".join("" if cell is None else str(cell) for cell in row) for row in grid]
        bbox: BBox = (
            float(table.bbox[0]),
            float(table.bbox[1]),
            float(table.bbox[2]),
            float(table.bbox[3]),
        )
        tables.append(_Table(index=index, bbox=bbox, rows=rows))
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
    for row_text in table.rows:
        if not row_text.strip(" |"):
            continue
        ordinal += 1
        units.append(
            CandidateUnit(
                ordinal=ordinal,
                kind="table_row",
                status=UnitStatus.KEPT,
                reasons=(f"tbl[{table.index}]",),
                raw_text=row_text,
                location=UnitLocation(page=page_no, bbox=table.bbox),
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
            tables, table_issues = _extract_tables(page)
            issues.extend(table_issues)
            lines = _page_lines(page)
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
                        detail="检测到左右分栏并排文本；阅读次序已按先左栏后右栏重建，保留复核标记",
                    )
                )
                ordered_columns = [columns[0], columns[1]]
            else:
                ordered_columns = [lines]

            median_size = statistics.median([line.size for line in lines])
            page_reasons: tuple[str, ...] = (
                ("multi_column_order_reconstructed",) if columns is not None else ()
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
                for line in sorted(column_lines, key=lambda item: (item.bbox[1], item.bbox[0])):
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
