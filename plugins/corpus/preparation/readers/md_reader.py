"""Markdown 读取 Adapter（架构 v1.1 §5.3）。

保留原始换行/偏移（每个单元 ``char_span`` 逐字符对应原文件），识别 ATX 标题、
段落、列表、表格与引用块；围栏代码块按原样保留并记录原因。短小可读文字正常
处理；重复标题使用不同 ordinal（候选 ID 唯一），不标 needs_ocr。
"""

from __future__ import annotations

import re
from pathlib import Path

from plugins.corpus.preparation.contract import CharSpan, UnitLocation, UnitStatus
from plugins.corpus.preparation.readers.base import (
    CandidateUnit,
    ReaderError,
    ReaderIssue,
    ReaderResult,
    detect_format,
)

READER_MD_REV = "reader-md-2"

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST_MARKER = re.compile(r"^(?:[-*+]|\d{1,3}[.、)])\s+")
_FENCE = re.compile(r"^(```|~~~)")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?[\s:|-]*-{3,}[\s:|-]*(\|[\s:|-]*)+$")


def read_markdown(path: str | Path) -> ReaderResult:
    """读取 Markdown 文件为候选单元；全部 raw_text 为原文精确切片。"""
    fmt, file_path = detect_format(path)
    raw_bytes = file_path.read_bytes()
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReaderError(f"Markdown 非 UTF-8 文本，拒绝猜测解码: {file_path}") from exc

    units: list[CandidateUnit] = []
    issues: list[ReaderIssue] = []
    ordinal = 0
    table_count = 0  # 表序计数：相邻两表以 tbl[k] 区分，切块不融合（复核 F7）
    lines = text.splitlines(keepends=True)
    offset = 0

    def _emit(kind: str, start: int, end: int, reasons: tuple[str, ...]) -> None:
        nonlocal ordinal
        raw_text = text[start:end].rstrip("\n")
        ordinal += 1
        units.append(
            CandidateUnit(
                ordinal=ordinal,
                kind=kind,
                status=UnitStatus.KEPT,
                reasons=reasons,
                raw_text=raw_text,
                location=UnitLocation(char_span=CharSpan(start=start, end=start + len(raw_text))),
            )
        )

    index = 0
    while index < len(lines):
        line = lines[index]
        line_start = offset
        if not line.strip():
            offset += len(line)
            index += 1
            continue

        fence = _FENCE.match(line)
        if fence is not None:
            marker = fence.group(1)
            block_start = line_start
            offset += len(line)
            index += 1
            closed = False
            while index < len(lines):
                if lines[index].startswith(marker):
                    offset += len(lines[index])
                    index += 1
                    closed = True
                    break
                offset += len(lines[index])
                index += 1
            if not closed:
                issues.append(
                    ReaderIssue(
                        code="unterminated_code_fence",
                        location=f"char:{block_start}-",
                        detail="围栏代码块未闭合，已消费到文件尾",
                    )
                )
            _emit("paragraph", block_start, offset, ("code_fence",))
            continue

        if _HEADING.match(line):
            _emit("heading", line_start, line_start + len(line), ("atx_heading",))
            offset += len(line)
            index += 1
            continue

        if line.lstrip().startswith(">"):
            block_start = line_start
            while index < len(lines) and lines[index].lstrip().startswith(">"):
                offset += len(lines[index])
                index += 1
            _emit("quote", block_start, offset, ("blockquote",))
            continue

        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if "|" in line and _TABLE_SEPARATOR.match(next_line):
            table_index = table_count
            table_count += 1
            while index < len(lines) and "|" in lines[index]:
                row_start = offset
                offset += len(lines[index])
                index += 1
                _emit("table_row", row_start, offset, (f"tbl[{table_index}]",))
            continue

        if _LIST_MARKER.match(line):
            while index < len(lines):
                current = lines[index]
                if not _LIST_MARKER.match(current):
                    break
                item_start = offset
                offset += len(current)
                index += 1
                while index < len(lines):
                    cont = lines[index]
                    if (
                        not cont.strip()
                        or _LIST_MARKER.match(cont)
                        or not cont.startswith((" ", "\t"))
                    ):
                        break
                    offset += len(cont)
                    index += 1
                _emit("list_item", item_start, offset, ())
            continue

        # 普通段落：合并连续非空行，保留内部换行。
        block_start = line_start
        while (
            index < len(lines)
            and lines[index].strip()
            and not _is_structural(lines[index], lines[index + 1] if index + 1 < len(lines) else "")
        ):
            offset += len(lines[index])
            index += 1
        _emit("paragraph", block_start, offset, ())

    return ReaderResult(
        format=fmt,
        extractor_rev=READER_MD_REV,
        source_path=str(file_path),
        page_count=None,
        units=tuple(units),
        issues=tuple(issues),
    )


def _is_structural(line: str, next_line: str) -> bool:
    """段落合并的终止条件：标题/列表/引用/表格/围栏都另起新单元。"""
    return bool(
        _HEADING.match(line)
        or _LIST_MARKER.match(line)
        or line.lstrip().startswith(">")
        or _FENCE.match(line)
        or ("|" in line and _TABLE_SEPARATOR.match(next_line))
    )
