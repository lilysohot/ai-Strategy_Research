"""读取 Adapter 共享模型与格式识别（架构 v1.1 §5.3/§9）。

读取器输出候选结构单元（单元/坐标/状态）与缺口台账（issues），不判噪声、
不决定 scope（那是 I1-3 清洗与 I1-5 准入的职责）。全部判定为本地确定性
代码：给定同一文件字节与同一 extractor_rev，输出必须一致。

缺口码词表（issue codes，跨格式统一）：
- ``empty_page``：PDF 页无文字层且无图片。
- ``image_only_page``：PDF 页无文字层但有图片（OCR 缺口，needs_ocr 语义）。
- ``image_region_unreadable``：PDF 页有文字层但存在大面积图片区域（≥25% 页
  面积），文字层未覆盖该区域（混合页 OCR 缺口，needs_ocr 语义）。
- ``garbled_text``：提取文本乱码比例超阈值（U+FFFD/控制字符）。
- ``multi_column_order_unreliable``：检测到左右分栏并排文本；阅读次序保留
  pymupdf 原生序（不再强制按「先左栏后右栏」重建），但保留该标记供复核。
- ``table_text_overlap``：表格区域内命中的正文文字已从正文单元剔除并计入
  表格行单元，不静默拼接两份重复正文。
- ``table_extraction_failed``：表格提取器异常（失败 ≠ 原文没有表格）。
- ``table_lines_without_extraction``：页面存在成网状制表线但表格提取结果
  为空——冲突信号，进入复核而非静默放行。
- ``unterminated_code_fence``：Markdown 围栏代码块未闭合。
- ``unreadable_element``：DOCX 段落内图片/文本框/OLE 对象未读取（列缺口）。
- ``unknown_body_element``：DOCX 正文出现未处理元素类型（不无记录消失）。
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import cast

from plugins.corpus.preparation.contract import (
    DocumentFormat,
    UnitLocation,
    UnitStatus,
    sha256_of_bytes,
)
from plugins.corpus.preparation.structure import (
    RelationCertainty,
    RelationKind,
    StructuredDocument,
    StructureNode,
    StructureRelation,
    shadow_node_id,
)

_FORMAT_SIGNATURES: dict[str, tuple[DocumentFormat, bytes | None]] = {
    ".pdf": (DocumentFormat.PDF, b"%PDF-"),
    ".docx": (DocumentFormat.DOCX, b"PK\x03\x04"),
    ".md": (DocumentFormat.MARKDOWN, None),
    ".markdown": (DocumentFormat.MARKDOWN, None),
}


class ReaderError(ValueError):
    """格式识别或读取失败（fail-closed：不猜测、不降级为空结果）。"""


@dataclass(frozen=True)
class ReaderIssue:
    """读取缺口/降级记录：位置用人类可读坐标（``page:N``/``body:p[i]``/``char:a-b``）。"""

    code: str
    location: str
    detail: str


@dataclass(frozen=True)
class CandidateUnit:
    """读取器输出的候选结构单元；``build_id``/``unit_id`` 由 engine（I1-7）指派。

    ``raw_text`` 是该格式的权威提取文本：MD 逐字符对应原文件（char_span 可验），
    PDF 是文字层提取结果（不承诺等于页面全部视觉内容），DOCX 按正文元素顺序。
    """

    ordinal: int
    kind: str
    status: UnitStatus
    reasons: tuple[str, ...]
    raw_text: str
    location: UnitLocation

    @property
    def content_hash(self) -> str:
        return sha256_of_bytes(self.raw_text.encode("utf-8"))


@dataclass(frozen=True)
class ReaderResult:
    """一次确定性读取的结果：结构文档、兼容单元与缺口台账。

    S0 shadow 阶段允许现有 reader 只传 ``units``；此时自动建立一对一结构节点和
    显式阅读顺序关系。reader 后续传入更深的 ``structure`` 时，其兼容投影必须与
    ``units`` 逐字段一致，避免 clean/chunk 在迁移期间观察到两套内容。
    """

    format: DocumentFormat
    extractor_rev: str
    source_path: str
    page_count: int | None
    units: tuple[CandidateUnit, ...]
    issues: tuple[ReaderIssue, ...]
    structure: StructuredDocument | None = None

    def __post_init__(self) -> None:
        structure = self.structure
        if structure is None:
            structure = structure_from_units(self.units)
            object.__setattr__(self, "structure", structure)
        if project_candidate_units(structure) != self.units:
            raise ReaderError("structure 的 CandidateUnit 兼容投影与 units 不一致")


def structure_from_units(units: tuple[CandidateUnit, ...]) -> StructuredDocument:
    """把现有扁平 reader 输出提升为零行为变化的 shadow 结构。"""

    ordered = tuple(sorted(units, key=lambda unit: unit.ordinal))
    nodes = tuple(
        StructureNode(
            node_id=shadow_node_id(unit.ordinal),
            ordinal=unit.ordinal,
            kind=unit.kind,
            status=unit.status,
            reasons=unit.reasons,
            raw_text=unit.raw_text,
            location=unit.location,
        )
        for unit in ordered
    )
    relations = tuple(
        StructureRelation(
            source_id=shadow_node_id(previous.ordinal),
            target_id=shadow_node_id(current.ordinal),
            kind=RelationKind.NEXT_IN_READING_ORDER,
            certainty=RelationCertainty.CONFIRMED,
            evidence="reader_unit_ordinal",
        )
        for previous, current in pairwise(ordered)
    )
    return StructuredDocument(nodes=nodes, relations=relations)


def project_candidate_units(structure: StructuredDocument) -> tuple[CandidateUnit, ...]:
    """生成旧 clean/chunk 消费的逐字段兼容视图。"""

    return tuple(
        CandidateUnit(
            ordinal=cast(int, node.ordinal),
            kind=node.kind,
            status=node.status,
            reasons=node.reasons,
            raw_text=node.raw_text,
            location=node.location,
        )
        for node in sorted(
            (item for item in structure.nodes if item.ordinal is not None),
            key=lambda item: item.ordinal if item.ordinal is not None else -1,
        )
    )


def detect_format(path: str | Path) -> tuple[DocumentFormat, Path]:
    """扩展名 + 文件签名识别；不支持/不一致/不可读一律 :class:`ReaderError`。"""
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix not in _FORMAT_SIGNATURES:
        raise ReaderError(f"不支持的来源格式: {suffix!r}（{file_path.name}）")
    fmt, magic = _FORMAT_SIGNATURES[suffix]
    if magic is not None:
        try:
            with file_path.open("rb") as handle:
                head = handle.read(len(magic))
        except OSError as exc:
            raise ReaderError(f"来源文件不可读: {file_path} ({exc})") from exc
        if not head.startswith(magic):
            raise ReaderError(f"文件签名与扩展名 {suffix} 不符（{file_path.name}）")
    return fmt, file_path
