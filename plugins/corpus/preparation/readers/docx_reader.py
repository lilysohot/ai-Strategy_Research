"""DOCX 读取 Adapter（架构 v1.1 §5.3）。

按正文 XML 元素顺序（不假设 ``document.paragraphs`` 已覆盖全文）读取段落、
标题、列表与表格，记录 element/paragraph/cell 坐标。重复标题不影响唯一
ordinal；图片、文本框等未可靠读取内容记录为缺口（``unreadable_element``），
不假定其已被覆盖。嵌套表格递归提取（嵌套行在所属行后发射，全局表序保证
``tbl[k]`` 唯一），不静默丢失（复核 F4）。
"""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from plugins.corpus.preparation.contract import UnitLocation, UnitStatus
from plugins.corpus.preparation.readers.base import (
    CandidateUnit,
    ReaderIssue,
    ReaderResult,
    detect_format,
)

READER_DOCX_REV = "reader-docx-2"

_SKIP_TAGS = frozenset({qn("w:sectPr")})


def _extractor_rev() -> str:
    try:
        version = importlib.metadata.version("python-docx")
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover
        version = "unknown"
    return f"{READER_DOCX_REV}+python-docx-{version}"


def _is_heading(style_name: str) -> bool:
    return style_name.startswith("Heading") or style_name.startswith("标题")


def read_docx(path: str | Path) -> ReaderResult:
    """读取 DOCX 正文元素序为候选单元；表格逐行输出并携带 cell 坐标。"""
    fmt, file_path = detect_format(path)
    document = Document(str(file_path))
    units: list[CandidateUnit] = []
    issues: list[ReaderIssue] = []
    ordinal = 0
    element_index = 0
    table_index = 0

    def emit_table_rows(table: Table, path_prefix: str) -> None:
        """按行发射表格行单元；嵌套表格递归提取，全局表序保证 ``tbl[k]`` 唯一。"""
        nonlocal ordinal, table_index
        tbl_no = table_index
        table_index += 1
        for row_index, row in enumerate(table.rows):
            cell_texts: list[str] = []
            cell_coords: list[tuple[int, int]] = []
            seen_tc: set[int] = set()
            nested: list[tuple[Table, str]] = []
            for col_index, cell in enumerate(row.cells):
                if id(cell._tc) in seen_tc:  # 合并单元格重复引用只计一次
                    continue
                seen_tc.add(id(cell._tc))
                cell_texts.append(cell.text)
                cell_coords.append((row_index, col_index))
                # 单元格内图片/文本框/OLE 记账（复核 R3）：嵌套表递归提取之外，
                # drawing/pict/object 不静默消失，逐 cell 立缺口（与正文段落同规则）。
                cell_unreadable = sum(
                    len(cell._tc.findall(f".//{qn(tag_name)}"))
                    for tag_name in ("w:drawing", "w:pict", "w:object", "w:txbxContent")
                )
                if cell_unreadable:
                    issues.append(
                        ReaderIssue(
                            code="unreadable_element",
                            location=f"{path_prefix}:tbl[{tbl_no}]/row[{row_index}]/cell[{col_index}]",
                            detail=f"单元格含 {cell_unreadable} 个图片/文本框/OLE 元素，未读取（列缺口）",
                        )
                    )
                for nested_tbl in cell._tc.findall(qn("w:tbl")):
                    # 嵌套表在所属行之后发射；路径带父链，坐标可回溯。
                    nested.append(
                        (
                            Table(nested_tbl, document),
                            f"{path_prefix}:tbl[{tbl_no}]/row[{row_index}]",
                        )
                    )
            if not cell_texts:
                continue
            ordinal += 1
            units.append(
                CandidateUnit(
                    ordinal=ordinal,
                    kind="table_row",
                    status=UnitStatus.KEPT,
                    reasons=(f"tbl[{tbl_no}]",),
                    raw_text=" | ".join(cell_texts),
                    location=UnitLocation(
                        element=f"{path_prefix}:tbl[{tbl_no}]/row[{row_index}]",
                        cells=tuple(cell_coords),
                    ),
                )
            )
            for nested_table, nested_prefix in nested:
                emit_table_rows(nested_table, nested_prefix)

    for child in document.element.body.iterchildren():
        tag = child.tag
        if tag in _SKIP_TAGS:
            continue
        location_id = f"body[{element_index}]"
        element_index += 1

        if tag == qn("w:p"):
            paragraph = Paragraph(child, document)
            unreadable = sum(
                len(child.findall(f".//{qn(tag_name)}"))
                for tag_name in ("w:drawing", "w:pict", "w:object", "w:txbxContent")
            )
            if unreadable:
                issues.append(
                    ReaderIssue(
                        code="unreadable_element",
                        location=location_id,
                        detail=f"段落含 {unreadable} 个图片/文本框/OLE 元素，未读取（列缺口）",
                    )
                )
            text = paragraph.text
            if not text.strip():
                continue
            style_name = ""
            try:
                style = paragraph.style
                style_name = style.name if style is not None and style.name else ""
            except AttributeError:  # 样式表缺失等；按普通段落处理
                style_name = ""
            p_pr = child.find(qn("w:pPr"))
            is_list = p_pr is not None and p_pr.find(qn("w:numPr")) is not None
            if is_list:
                kind, reasons = "list_item", ("style:list",)
            elif _is_heading(style_name):
                kind, reasons = "heading", (f"style:{style_name}",)
            elif style_name in {"Title", "标题"}:
                kind, reasons = "title", (f"style:{style_name}",)
            else:
                kind, reasons = "paragraph", ()
            ordinal += 1
            units.append(
                CandidateUnit(
                    ordinal=ordinal,
                    kind=kind,
                    status=UnitStatus.KEPT,
                    reasons=reasons,
                    raw_text=text,
                    location=UnitLocation(element=location_id),
                )
            )
            continue

        if tag == qn("w:tbl"):
            emit_table_rows(Table(child, document), location_id)
            continue

        issues.append(
            ReaderIssue(
                code="unknown_body_element",
                location=location_id,
                detail=f"未处理的正文元素 {tag}，保留缺口记录",
            )
        )

    return ReaderResult(
        format=fmt,
        extractor_rev=_extractor_rev(),
        source_path=str(file_path),
        page_count=None,
        units=tuple(units),
        issues=tuple(issues),
    )
