"""覆盖映射：把「送达区间」与「文档版本原始区间」放在同一把尺子上量。

两条口径严格分开，互不推断：

* **入库文本覆盖**（:func:`coverage_report`）：分母是目标文档版本的原始单元／字符
  范围，分子是实际送达区间的**并集**。已提取的 OCR 文本计入这一项，不能因为
  "是 OCR"就把图像／表格内容笼统排除。
* **原 PDF 提取完整性**（:data:`SOURCE_EXTRACTION_UNKNOWN`）：没有独立的提取证据就
  一律 ``unknown``，绝不从入库文本覆盖反推。

另外三条约束：

* 页数只是效率指标，单独放在 ``efficiency`` 里，**不参与覆盖率计算**；
* ``native1``（检索）与 ``document1``（分页）通过后台映射关联，不强行归一成一种
  locator；查不到就报 ``unmapped``，不猜；
* 同一单元的多次送达／跨页分片按字符区间合并，长单元跨页不会被 ``unit_id`` 去重
  误删。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: 原 PDF 提取完整性在无独立证据时的唯一合法取值。
SOURCE_EXTRACTION_UNKNOWN: dict[str, str] = {
    "status": "unknown",
    "note": "入库文本覆盖不证明原 PDF 图像、表格或未被检索到的页面已提取。",
}


@dataclass(frozen=True)
class UnitRange:
    """目标文档版本里的一个原始单元。"""

    locator: str
    unit_id: str
    chars: int


@dataclass(frozen=True)
class Delivery:
    """一次实际送达的码点区间 ``[start, end)``。"""

    doc_id: str
    locator: str
    start: int
    end: int


def merge_intervals(intervals: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """合并重叠或首尾相接的区间；非法／空区间丢弃，不补造范围。"""
    cleaned = sorted(
        (int(start), int(end))
        for start, end in intervals
        if int(end) > int(start) and int(start) >= 0
    )
    merged: list[tuple[int, int]] = []
    for start, end in cleaned:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def delivered_union(
    deliveries: Sequence[Delivery], *, doc_id: str
) -> dict[str, list[tuple[int, int]]]:
    """按 ``doc_id + locator`` 聚合送达区间并集；跨 agent／跨轮重复只算一次。"""
    grouped: dict[str, list[tuple[int, int]]] = {}
    for item in deliveries:
        if item.doc_id != doc_id:
            continue
        grouped.setdefault(item.locator, []).append((item.start, item.end))
    return {locator: merge_intervals(ranges) for locator, ranges in grouped.items()}


def _interval_chars(intervals: Sequence[tuple[int, int]]) -> int:
    return sum(end - start for start, end in intervals)


def coverage_report(
    *,
    doc_id: str,
    units: Sequence[UnitRange],
    deliveries: Sequence[Delivery],
    page_count: int = 0,
    source_extraction: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """入库文本覆盖：分母固定为文档版本原始范围，分子为送达区间并集。

    ``page_count`` 只写进 ``efficiency``，绝不进分母或分子。
    """
    union = delivered_union(deliveries, doc_id=doc_id)
    total_chars = sum(max(0, int(unit.chars)) for unit in units)
    delivered_chars = 0
    covered_units = 0
    missing: list[dict[str, Any]] = []
    for unit in units:
        intervals = union.get(unit.locator, [])
        clipped = merge_intervals(
            (max(0, start), min(int(unit.chars), end)) for start, end in intervals
        )
        covered = _interval_chars(clipped)
        delivered_chars += covered
        if unit.chars <= 0 or covered >= unit.chars:
            covered_units += 1
        else:
            missing.append(
                {
                    "locator": unit.locator,
                    "chars": int(unit.chars),
                    "delivered_chars": covered,
                    "missing": interval_gaps(clipped, int(unit.chars)),
                }
            )
    return {
        "doc_id": doc_id,
        "scope": "ingested_text",
        "denominator": {"unit_count": len(units), "total_chars": total_chars},
        "numerator": {
            "delivered_chars": delivered_chars,
            "covered_units": covered_units,
            "interval_count": sum(len(rows) for rows in union.values()),
        },
        "ratio": (delivered_chars / total_chars) if total_chars else None,
        "complete": not missing and total_chars > 0,
        "missing": missing,
        # 效率指标与覆盖率正交，单独放。
        "efficiency": {"page_count": int(page_count)},
        "source_extraction_completeness": dict(
            source_extraction if source_extraction is not None else SOURCE_EXTRACTION_UNKNOWN
        ),
    }


def interval_gaps(intervals: Sequence[tuple[int, int]], total: int) -> list[tuple[int, int]]:
    """返回 ``[0, total)`` 中未被区间覆盖的部分，用于定位缺口而不是猜。"""
    gaps: list[tuple[int, int]] = []
    cursor = 0
    for start, end in intervals:
        if start > cursor:
            gaps.append((cursor, min(start, total)))
        cursor = max(cursor, end)
    if cursor < total:
        gaps.append((cursor, total))
    return gaps


def map_native_to_document(
    native_locators: Sequence[str],
    *,
    native_to_units: Mapping[str, Sequence[str]],
    known_units: Mapping[str, UnitRange],
) -> dict[str, Any]:
    """后台映射 ``native1`` 检索块 → ``document1`` 单元区间。

    只做查表，绝不按名称相似度或相邻顺序推断。查不到的块显式列入 ``unmapped``，
    调用方必须能看到"哪些检索范围还没有后台对应关系"。
    """
    mapped: dict[str, list[str]] = {}
    unmapped: list[str] = []
    for locator in native_locators:
        unit_ids = list(native_to_units.get(locator) or ())
        resolved = [unit_id for unit_id in unit_ids if unit_id in known_units]
        if not resolved or len(resolved) != len(unit_ids):
            unmapped.append(locator)
            continue
        mapped[locator] = [known_units[unit_id].locator for unit_id in resolved]
    return {
        "mapped": mapped,
        "unmapped": unmapped,
        "mapped_count": len(mapped),
        "unmapped_count": len(unmapped),
    }


# ── 后台映射表：native1 检索块 → document1 权威单元 ────────────────────
#
# 唯一权威来源是检索后端取证时生成的 ``native_slices``（``NativeSpan`` 的落盘形态）：
# 每项含 ``unit_id``、该单元原文内的 ``[start, end)`` 码点区间与 ``raw_sha256``。
# 这里只做校验与查表，**绝不**按 chunk 序号、名称相似度或相邻顺序推断对应关系；
# 任何字段缺失／越界的块整条拒绝，调用方必须仍能看见它是 ``unmapped``。

NATIVE_PREFIX = "chunk:native1/"
MAPPING_CONTRACT = "native-document-map-v2"
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class NativeUnitSlice:
    """一个 native 块绑定的权威单元原文区间 ``[start, end)``（code point）。"""

    unit_id: str
    start: int
    end: int
    raw_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "start": self.start,
            "end": self.end,
            "raw_sha256": self.raw_sha256,
        }


@dataclass(frozen=True)
class NativeMapping:
    """一条后台映射：检索块 locator → 版本钉死的权威单元区间列表。"""

    doc_id: str
    build_id: str
    locator: str
    slices: tuple[NativeUnitSlice, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": MAPPING_CONTRACT,
            "doc_id": self.doc_id,
            "build_id": self.build_id,
            "locator": self.locator,
            "slices": [item.to_dict() for item in self.slices],
        }


def _valid_slice(row: Any) -> NativeUnitSlice | None:
    if not isinstance(row, dict):
        return None
    unit_id = row.get("unit_id")
    start, end = row.get("start"), row.get("end")
    if not isinstance(unit_id, str) or not unit_id.strip():
        return None
    if type(start) is not int or type(end) is not int or start < 0 or end <= start:
        return None
    digest = row.get("raw_sha256") or ""
    if digest and (not isinstance(digest, str) or not _SHA256.fullmatch(digest)):
        return None
    return NativeUnitSlice(unit_id, start, end, digest)


def build_native_mapping(
    *,
    locator: str,
    doc_id: str,
    build_id: str,
    rows: Sequence[Any],
) -> NativeMapping | None:
    """只接受后端给出的 ``native_slices``；任一非法行整条拒绝，不猜、不补造。"""
    if not isinstance(locator, str) or not locator.startswith(NATIVE_PREFIX):
        return None
    if not build_id or doc_id != "cv2:" + build_id:
        return None
    if not isinstance(rows, (list, tuple)) or not rows:
        return None
    parsed = [_valid_slice(row) for row in rows]
    if any(item is None for item in parsed):
        return None
    slices = tuple(item for item in parsed if item is not None)
    return NativeMapping(
        doc_id=str(doc_id),
        build_id=str(build_id),
        locator=locator,
        slices=slices,
    )


def mappings_from_fetch(payload: Any) -> list[NativeMapping]:
    """从 ``corpus_fetch`` 的单块／分页信封提取映射（须是未经投影的原始结果）。"""
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return []
    doc_id = str(payload.get("doc_id") or "")
    build_id = str(payload.get("build_id") or "")
    out: list[NativeMapping] = []
    single = build_native_mapping(
        locator=str(payload.get("locator") or ""),
        doc_id=doc_id,
        build_id=build_id,
        rows=payload.get("native_target_slices") or (
            payload.get("native_slices") if not payload.get("fragment") else ()
        ) or (),
    )
    if single is not None:
        out.append(single)
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        entry = build_native_mapping(
            locator=str(item.get("locator") or ""),
            doc_id=doc_id,
            build_id=build_id,
            rows=item.get("native_target_slices") or (
                item.get("native_slices") if not item.get("fragment") else ()
            ) or (),
        )
        if entry is not None:
            out.append(entry)
    return merge_native_mappings(out)


def mapping_from_dict(row: Any) -> NativeMapping | None:
    """反序列化一条落盘映射；契约不符或切片损坏一律返回 ``None``。"""
    if not isinstance(row, dict) or row.get("contract") != MAPPING_CONTRACT:
        return None
    return build_native_mapping(
        locator=str(row.get("locator") or ""),
        doc_id=str(row.get("doc_id") or ""),
        build_id=str(row.get("build_id") or ""),
        rows=row.get("slices") or (),
    )


def mappings_from_dict(rows: Any) -> list[NativeMapping]:
    if not isinstance(rows, (list, tuple)):
        return []
    parsed = [mapping_from_dict(row) for row in rows]
    return merge_native_mappings([item for item in parsed if item is not None])


def merge_native_mappings(mappings: Iterable[NativeMapping]) -> list[NativeMapping]:
    """同一 locator 的切片取并集；按 locator 排序，保证落盘可复现。"""
    grouped: dict[tuple[str, str, str], dict[tuple[str, int, int, str], NativeUnitSlice]] = {}
    for mapping in mappings:
        key = (mapping.doc_id, mapping.build_id, mapping.locator)
        bucket = grouped.setdefault(key, {})
        for item in mapping.slices:
            bucket[(item.unit_id, item.start, item.end, item.raw_sha256)] = item
    return [
        NativeMapping(
            doc_id=key[0],
            build_id=key[1],
            locator=key[2],
            slices=tuple(sorted(bucket.values(), key=lambda s: (s.unit_id, s.start, s.end))),
        )
        for key, bucket in sorted(grouped.items())
    ]


def native_to_units(mappings: Sequence[NativeMapping]) -> dict[str, tuple[str, ...]]:
    """喂给 :func:`map_native_to_document` 的 ``native_to_units`` 查表输入。"""
    return {
        mapping.locator: tuple(dict.fromkeys(item.unit_id for item in mapping.slices))
        for mapping in mappings
    }


def native_unit_intervals(
    mappings: Sequence[NativeMapping],
) -> dict[str, tuple[NativeUnitSlice, ...]]:
    """按 native locator 给出权威单元原文区间，供范围完整性折算。"""
    return {mapping.locator: mapping.slices for mapping in mappings}
