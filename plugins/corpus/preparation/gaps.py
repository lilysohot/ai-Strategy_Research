"""缺口裁决（gap ledger）语义：码 → 状态/默认分级 → 生命周期 → 可执行恢复路径。

架构 §7.3（I2 全链路复核裁定 RM-FC-0）把「缺口可见性」与「发布阻断」分开：

- 缺口恒进台账（``quality_report.gap_regions``），任何路径都**不得静默丢弃**；
- 是否阻断发布由**默认分级表**（本模块 :data:`DEFAULT_GAP_DISPOSITION`，与架构 §7.3
  表同源）、**scope 归属**及 build 绑定的具名人工凭证共同决定：

  1. `out_of_scope`：缺口坐标可证落在获批 ``char:`` 区间之外（与任一区间无重叠）→
     该区域本就不在请求范围内，不阻断、不计入剩余范围；
  2. `blocking`：可能丢失获批正文（扫描页/表格抽取失败/未读取元素等）→ 拒绝发布；
  3. `acknowledged`：确知未丢失正文（空页/装饰图/未闭合围栏）→ 允许发布，但必须继续
     出现在 ``quality_report``、``check``/``status`` 的 ``gaps`` 与 ``coverage.reason_codes``。
     ``gap_review.py`` 还允许经完整人工签署及不相交校验的具体 build 缺口进入此生命周期，
     但原默认分级与台账保持不变（``engine.gap_records_of(..., store=...)`` 统一读取凭证）。

缺口身份沿用既有台账编码 ``issue:<code>:<location>``（``quality_report`` 形状不变，
仍为 ``gap_regions``/``oversized_chunks`` 两键）；编解码只在本模块
（:func:`gap_key` / :func:`parse_gap_key`），`clean.py` 是唯一生产者。

fail-closed：词表外的码、键不可解析、坐标不可判定，一律不乐观放行——词表外/不可解析按
``blocking`` 处理（看不见的缺口比误阻断更危险），坐标不可判定按**默认分级**回落（不因
「坐标缺失」而升级为放行）。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType

from plugins.corpus.preparation.contract import UnitStatus

#: 缺口裁决口径版本（默认分级表 + 判定顺序的版本身份；变更须同步架构 §7.3 表）。
GAP_POLICY_REV = "gap-policy-3"

_GAP_KEY_PREFIX = "issue"
_PAGE_RE = re.compile(r"^page:([0-9]+)$")
_CHAR_RE = re.compile(r"^char:([0-9]+)-([0-9]*)$")
_BODY_RE = re.compile(r"^body\[[0-9]+\]")

#: 缺口码 → 合成区域状态（``clean.py`` 立区时使用；本表为词表唯一来源）。
GAP_CODE_STATUS: Mapping[str, UnitStatus] = MappingProxyType(
    {
        "empty_page": UnitStatus.REVIEW_REQUIRED,
        "image_only_page": UnitStatus.NEEDS_OCR,
        "image_region_unreadable": UnitStatus.NEEDS_OCR,
        "image_region_small": UnitStatus.NOISE,
        "table_extraction_failed": UnitStatus.REVIEW_REQUIRED,
        "table_lines_without_extraction": UnitStatus.REVIEW_REQUIRED,
        "unreadable_element": UnitStatus.REVIEW_REQUIRED,
        "unknown_body_element": UnitStatus.REVIEW_REQUIRED,
        "unterminated_code_fence": UnitStatus.REVIEW_REQUIRED,
    }
)


class GapDisposition(StrEnum):
    """缺口默认分级：`blocking` 阻断发布，`acknowledged` 允许发布但保持可见。"""

    BLOCKING = "blocking"
    ACKNOWLEDGED = "acknowledged"


class GapLifecycle(StrEnum):
    """缺口在**具体 build + scope** 下的生命周期（默认分级经 scope 判定后的结果）。"""

    BLOCKING = "blocking"
    ACKNOWLEDGED = "acknowledged"
    OUT_OF_SCOPE = "out_of_scope"


#: 默认分级（架构 §7.3 表；**不得在别处复制**这份分级）。
DEFAULT_GAP_DISPOSITION: Mapping[str, GapDisposition] = MappingProxyType(
    {
        "empty_page": GapDisposition.ACKNOWLEDGED,
        "image_region_small": GapDisposition.ACKNOWLEDGED,
        "unterminated_code_fence": GapDisposition.ACKNOWLEDGED,
        "image_only_page": GapDisposition.BLOCKING,
        "image_region_unreadable": GapDisposition.BLOCKING,
        "table_extraction_failed": GapDisposition.BLOCKING,
        "table_lines_without_extraction": GapDisposition.BLOCKING,
        "unreadable_element": GapDisposition.BLOCKING,
        "unknown_body_element": GapDisposition.BLOCKING,
    }
)


class GapCoordinateKind(StrEnum):
    """缺口坐标种类；`unlocatable` = 无法给出可判定坐标（显式记账，不静默）。"""

    PAGE = "page"
    ELEMENT = "element"
    CHAR = "char"
    UNLOCATABLE = "unlocatable"


@dataclass(frozen=True)
class GapCoordinates:
    """缺口坐标（来自 reader ``location``；无坐标显式 ``unlocatable``）。"""

    kind: GapCoordinateKind
    page: int | None = None
    element: str | None = None
    char_start: int | None = None
    char_end: int | None = None

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"kind": self.kind.value}
        if self.page is not None:
            payload["page"] = self.page
        if self.element is not None:
            payload["element"] = self.element
        if self.char_start is not None:
            payload["char_start"] = self.char_start
        if self.char_end is not None:
            payload["char_end"] = self.char_end
        return payload


@dataclass(frozen=True)
class GapRecord:
    """一个缺口的裁决记录（码/坐标/状态/分级/生命周期/恢复路径）。"""

    key: str
    code: str
    location: str
    coordinates: GapCoordinates
    status: UnitStatus | None
    disposition: GapDisposition
    lifecycle: GapLifecycle
    basis: str
    remedy: str

    def as_payload(self) -> dict[str, object]:
        return {
            "key": self.key,
            "code": self.code,
            "location": self.location,
            "coordinates": self.coordinates.as_payload(),
            "status": self.status.value if self.status is not None else "unknown",
            "disposition": self.disposition.value,
            "lifecycle": self.lifecycle.value,
            "basis": self.basis,
            "remedy": self.remedy,
        }


_DEFAULT_BASIS = f"default_grading_table:{GAP_POLICY_REV}"
_UNCLASSIFIED_BASIS = f"unclassified_code:{GAP_POLICY_REV}"
_OPS_REBUILD = "uv run python -m plugins.corpus.cli build --manifest <manifest.json>（重跑该来源）"

#: 每个缺口码的可执行恢复路径（`status`/`check` 的 ``recovery`` 直接复用）。
GAP_CODE_REMEDY: Mapping[str, str] = MappingProxyType(
    {
        "empty_page": "空页未丢失正文：默认分级已放行（acknowledged），无需动作；仅记账与 coverage 反映",
        "image_region_small": "阈值内装饰图已按噪声记账：无需动作；阈值校准属 I3 校准范围",
        "unterminated_code_fence": "围栏未闭合但文本已读全：无需动作；如判定结构错误须升级 MD 规则后重建",
        "image_only_page": "扫描页无文字层：补 OCR 或改用带文字层的来源后重建；否则该来源转 review_required",
        "image_region_unreadable": "混合页大图区未覆盖：补 OCR（该区域）后重建；否则转 review_required",
        "table_extraction_failed": "表格提取失败：核对受控表格 Adapter 后重建，或人工复核该表格并转 review_required",
        "table_lines_without_extraction": "有成网制表线而提取为空：人工复核该页表格后重建；否则转 review_required",
        "unreadable_element": "段落/单元格内嵌对象未读取：改用可读导出稿，或人工复核后转 review_required",
        "unknown_body_element": "读取器未覆盖的正文元素：升级读取器（extractor_rev 变更）后重建",
    }
)


def gap_key(code: str, location: str) -> str:
    """缺口台账键的唯一构造点（``clean.py`` 立区时调用）。"""
    return f"{_GAP_KEY_PREFIX}:{code}:{location}"


def parse_gap_key(key: str) -> tuple[str, str] | None:
    """解析缺口键为 ``(code, location)``；不合法返回 ``None``（由调用方 fail-closed）。

    键格式：``issue:<code>:<location>``（location 自身可含 ``:``，如 ``page:3``）。
    """
    if not isinstance(key, str):
        return None
    parts = key.split(":", 2)
    if len(parts) != 3 or parts[0] != _GAP_KEY_PREFIX:
        return None
    code, location = parts[1].strip(), parts[2].strip()
    if not code or not location:
        return None
    return code, location


def parse_gap_location(location: str) -> GapCoordinates:
    """把 reader 的位置串解析为结构化坐标；不可判定即 ``unlocatable``（显式记账）。"""
    text = (location or "").strip()
    page = _PAGE_RE.match(text)
    if page is not None:
        return GapCoordinates(kind=GapCoordinateKind.PAGE, page=int(page.group(1)))
    char = _CHAR_RE.match(text)
    if char is not None:
        start = int(char.group(1))
        end_text = char.group(2)
        return GapCoordinates(
            kind=GapCoordinateKind.CHAR,
            char_start=start,
            char_end=int(end_text) if end_text else None,
        )
    if _BODY_RE.match(text):
        return GapCoordinates(kind=GapCoordinateKind.ELEMENT, element=text)
    return GapCoordinates(kind=GapCoordinateKind.UNLOCATABLE)


def gap_record(key: str) -> GapRecord:
    """把台账键裁决为 :class:`GapRecord`（词表外/键非法一律按 ``blocking``）。"""
    parsed = parse_gap_key(key)
    if parsed is None:
        return GapRecord(
            key=str(key),
            code="unparsable_key",
            location="",
            coordinates=GapCoordinates(kind=GapCoordinateKind.UNLOCATABLE),
            status=None,
            disposition=GapDisposition.BLOCKING,
            lifecycle=GapLifecycle.BLOCKING,
            basis=_UNCLASSIFIED_BASIS,
            remedy="缺口键不可解析：台账形状异常，须修复写入方（不得静默放行）",
        )
    code, location = parsed
    disposition = DEFAULT_GAP_DISPOSITION.get(code, GapDisposition.BLOCKING)
    status = GAP_CODE_STATUS.get(code)
    untabulated = code not in DEFAULT_GAP_DISPOSITION
    return GapRecord(
        key=key,
        code=code,
        location=location,
        coordinates=parse_gap_location(location),
        status=status,
        disposition=disposition,
        lifecycle=GapLifecycle(disposition.value),
        basis=_UNCLASSIFIED_BASIS if untabulated else _DEFAULT_BASIS,
        remedy=GAP_CODE_REMEDY.get(code, "词表外缺口码：升级裁决口径或转 review_required 后重建"),
    )


def gap_records(keys: Iterable[str]) -> tuple[GapRecord, ...]:
    """台账键 → 裁决记录（保持输入顺序，便于与 ``quality_report`` 对照）。"""
    return tuple(gap_record(key) for key in keys)


def _outside_scope(coordinates: GapCoordinates, scope_ranges: tuple[tuple[int, int], ...]) -> bool:
    """缺口坐标是否**可证**在获批 ``char:`` 区间之外（部分重叠/无坐标 → 不可证）。"""
    if coordinates.kind is not GapCoordinateKind.CHAR or coordinates.char_start is None:
        return False
    start = coordinates.char_start
    end = coordinates.char_end
    for low, high in scope_ranges:
        if end is None:
            if high > start:  # 开区间缺口与批准区间重叠 → 不可证范围外
                return False
            continue
        if start >= low and end <= high:
            return False  # 完全落在批准区间内
        if start < high and end > low:
            return False  # 部分重叠 → 不可证范围外（宁可少保留，不越权）
    return True


def evaluate_against_scope(
    records: Iterable[GapRecord],
    scope_ranges: tuple[tuple[int, int], ...],
) -> tuple[GapRecord, ...]:
    """按获批 scope 判定缺口生命周期：可证范围外 → ``out_of_scope``，其余保持默认分级。"""
    if not scope_ranges:
        return tuple(records)
    return tuple(
        replace(record, lifecycle=GapLifecycle.OUT_OF_SCOPE)
        if _outside_scope(record.coordinates, scope_ranges)
        else record
        for record in records
    )


def blocking_gaps(records: Iterable[GapRecord]) -> tuple[GapRecord, ...]:
    """仍阻断发布的缺口（发布门唯一判据）。"""
    return tuple(record for record in records if record.lifecycle is GapLifecycle.BLOCKING)


def acknowledged_gaps(records: Iterable[GapRecord]) -> tuple[GapRecord, ...]:
    """允许发布但必须保持可见的缺口（进 coverage/status，记录发布操作者）。"""
    return tuple(record for record in records if record.lifecycle is GapLifecycle.ACKNOWLEDGED)


def gap_summary(records: Iterable[GapRecord]) -> dict[str, object]:
    """缺口计数（status/check 的稳定机读摘要）。"""
    items = tuple(records)
    return {
        "total": len(items),
        "blocking": len(blocking_gaps(items)),
        "acknowledged": len(acknowledged_gaps(items)),
        "out_of_scope": sum(1 for r in items if r.lifecycle is GapLifecycle.OUT_OF_SCOPE),
        "policy_rev": GAP_POLICY_REV,
    }


def recovery_paths(records: Iterable[GapRecord]) -> list[dict[str, object]]:
    """缺口相关的可执行恢复路径（每个仍阻断的缺口一条；已放行的附说明）。"""
    paths: list[dict[str, object]] = []
    for record in records:
        if record.lifecycle is GapLifecycle.OUT_OF_SCOPE:
            continue
        entry: dict[str, object] = {
            "gap": record.key,
            "code": record.code,
            "lifecycle": record.lifecycle.value,
            "stage": "PARSED",
            "action": record.remedy,
        }
        if record.lifecycle is GapLifecycle.BLOCKING:
            entry["command"] = _OPS_REBUILD
        paths.append(entry)
    return paths
