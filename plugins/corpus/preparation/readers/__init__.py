"""PDF/DOCX/MD 统一格式读取 Adapter（架构 v1.1 §5.3/§9 `preparation/readers/`）。

职责边界：输出候选结构单元（单元/坐标/状态）与缺口台账；不判噪声、不决定
scope、不执行 OCR。只使用本地确定性读取库（PyMuPDF/python-docx），零模型调用、
零网络；"库已安装"不构成支持声明——格式由扩展名 + 文件签名识别，不一致一律
fail-closed 拒绝。
"""

from __future__ import annotations

from pathlib import Path

from plugins.corpus.preparation.contract import DocumentFormat
from plugins.corpus.preparation.readers.base import (
    CandidateUnit,
    ReaderError,
    ReaderIssue,
    ReaderResult,
    detect_format,
)

__all__ = [
    "CandidateUnit",
    "DocumentFormat",
    "ReaderError",
    "ReaderIssue",
    "ReaderResult",
    "detect_format",
    "extractor_rev_for",
    "read_document",
]


def extractor_rev_for(fmt: DocumentFormat) -> str:
    """当前代码对指定格式的读取器版本（full-review C6：免解析查得）。

    引擎校验解析检查点时使用：检查点记录的 ``extractor_rev`` 必须等于当前代码
    对该格式会产出的版本，否则检查点不可复用（读取器升级 → 重算 → 新
    ``parse_rev``）。惰性导入与 :func:`read_document` 一致，不加重模块装载。
    """
    if fmt is DocumentFormat.PDF:
        from plugins.corpus.preparation.readers.pdf_reader import READER_PDF_REV

        return READER_PDF_REV
    if fmt is DocumentFormat.DOCX:
        from plugins.corpus.preparation.readers.docx_reader import READER_DOCX_REV

        return READER_DOCX_REV
    if fmt is DocumentFormat.MARKDOWN:
        from plugins.corpus.preparation.readers.md_reader import READER_MD_REV

        return READER_MD_REV
    raise ReaderError(f"不支持的来源格式: {fmt!r}")


def read_document(path: str | Path) -> ReaderResult:
    """按扩展名与文件签名分发到对应 Adapter；不支持/不一致一律 ReaderError。"""
    fmt, file_path = detect_format(path)
    if fmt is DocumentFormat.PDF:
        from plugins.corpus.preparation.readers.pdf_reader import read_pdf

        return read_pdf(file_path)
    if fmt is DocumentFormat.DOCX:
        from plugins.corpus.preparation.readers.docx_reader import read_docx

        return read_docx(file_path)
    from plugins.corpus.preparation.readers.md_reader import read_markdown

    return read_markdown(file_path)
