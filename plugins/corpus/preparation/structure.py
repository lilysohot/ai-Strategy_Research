"""跨格式的确定性文档结构契约。

本模块只表达读取阶段已经观察到的节点、阅读顺序和结构关系。它不清洗文本、
不切块，也不根据相邻位置补造关系。reader 可以逐步增加有来源依据的关系；旧
消费者继续通过 ``CandidateUnit`` 兼容投影工作。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from plugins.corpus.preparation.contract import UnitLocation, UnitStatus


class StructureError(ValueError):
    """结构契约非法。"""


class TextOrigin(StrEnum):
    """节点文本的取得方式。"""

    NATIVE = "native_text"
    OCR = "ocr"


class RelationKind(StrEnum):
    """准备链允许传递的结构关系。"""

    CONTAINS = "contains"
    NEXT_IN_READING_ORDER = "next_in_reading_order"
    HEADER_FOR = "header_for"
    ROW_LABEL_FOR = "row_label_for"
    CONTINUATION_OF = "continuation_of"
    CAPTION_OF = "caption_of"
    FOOTNOTE_OF = "footnote_of"


class RelationCertainty(StrEnum):
    """关系的证据强度；无法判断时不创建关系并保留 issue。"""

    CONFIRMED = "confirmed"
    CANDIDATE = "candidate"


@dataclass(frozen=True)
class StructureNode:
    """可追溯到来源坐标的最小结构节点。"""

    node_id: str
    # 只有兼容投影节点拥有 ordinal；table/cell 等结构节点不进入 CandidateUnit
    # 视图，因此必须显式使用 None，不能借用或伪造正文顺序号。
    ordinal: int | None
    kind: str
    status: UnitStatus
    reasons: tuple[str, ...]
    raw_text: str
    location: UnitLocation
    text_origin: TextOrigin = TextOrigin.NATIVE

    def __post_init__(self) -> None:
        if not self.node_id:
            raise StructureError("node_id 不能为空")
        if self.ordinal is not None and self.ordinal < 0:
            raise StructureError(f"ordinal 不能为负数: {self.ordinal}")
        if not self.kind:
            raise StructureError(f"节点 {self.node_id} 的 kind 不能为空")


@dataclass(frozen=True)
class StructureRelation:
    """两个已知节点之间、带证据说明的有向关系。"""

    source_id: str
    target_id: str
    kind: RelationKind
    certainty: RelationCertainty
    evidence: str

    def __post_init__(self) -> None:
        if not self.source_id or not self.target_id:
            raise StructureError("关系端点不能为空")
        if self.source_id == self.target_id:
            raise StructureError(f"关系不能自指: {self.source_id}")
        if not self.evidence:
            raise StructureError(f"关系 {self.source_id}->{self.target_id} 缺少 evidence")


@dataclass(frozen=True)
class StructuredDocument:
    """reader 输出的节点与关系；节点顺序不承担隐式阅读顺序语义。"""

    nodes: tuple[StructureNode, ...]
    relations: tuple[StructureRelation, ...]

    def __post_init__(self) -> None:
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise StructureError("node_id 必须在文档内唯一")
        ordinals = [node.ordinal for node in self.nodes if node.ordinal is not None]
        if len(ordinals) != len(set(ordinals)):
            raise StructureError("ordinal 必须在文档内唯一")
        known = set(node_ids)
        for relation in self.relations:
            if relation.source_id not in known or relation.target_id not in known:
                raise StructureError(
                    f"关系端点必须引用本文档节点: {relation.source_id}->{relation.target_id}"
                )


def shadow_node_id(ordinal: int) -> str:
    """为兼容单元生成确定、可排序且不依赖文本内容的节点 ID。"""

    if ordinal < 0:
        raise StructureError(f"ordinal 不能为负数: {ordinal}")
    return f"unit:{ordinal:06d}"
