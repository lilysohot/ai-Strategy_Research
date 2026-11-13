"""Document pagination for corpus_fetch; search candidates never define its scope."""

from __future__ import annotations

import hashlib
import json
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Any

from plugins.corpus.cursor import CONTENT, encode_cursor
from plugins.corpus.pagination_policy import (
    DOCUMENT_MIN_TEXT_BUDGET,
    DOCUMENT_VISIBLE_CAP,
    PAGINATION_POLICY_VERSION,
    POLICY_VERSION_KEY,
    document_page_id,
    policy_version,
)
from plugins.corpus.preparation.document_read import DocumentUnit, DocumentUnits, unit_locator
from plugins.corpus.projection import navigation_enabled, render_fetch_view
from plugins.corpus.read_errors import read_failure
from plugins.corpus.tool_refs import fetch_evidence_ref

if TYPE_CHECKING:
    from plugins.corpus.service import CorpusService

# Per-job dispatched unit range (1-based inclusive). When a coordinator splits a
# numbered document across members, the range is enforced here — members page
# only their slice instead of each reading the whole document (run c010c5e1:
# three agents each fetched all 299 units although the plan split 0-99/100-199/
# 200-298). Ranges bound units by their 1-based source position, whatever the
# unit id format — F27-r1 failed because the first implementation accepted only
# digit-only ids ("u21".isdigit() is False) and every member saw an empty page.
_unit_range_scope: ContextVar[tuple[int, int] | None] = ContextVar(
    "corpus_unit_range",
    default=None,
)


def set_unit_range_scope(lo: int, hi: int) -> Token:
    return _unit_range_scope.set((int(lo), int(hi)))


def reset_unit_range_scope(token: Token) -> None:
    _unit_range_scope.reset(token)


def current_unit_range() -> tuple[int, int] | None:
    return _unit_range_scope.get()


def unit_positions(document: DocumentUnits) -> dict[str, int]:
    """unit_id → 1-based source position, for range checks on explicit handles."""
    return {entry.unit.unit_id: pos for pos, entry in enumerate(document.units, start=1)}


_HINT = (
    "已知文档的原文顺序阅读，无需再次搜索。续读只传 doc_id 和 next_cursor；"
    "items 的 evidence_ref 可直接引用，fragment 为单元内码点区间。"
    "fetch_complete 仅表示本版本入库文本遍历结束，不证明源 PDF 图像、表格提取完整，"
    "也不证明结论已核实。"
    "缺结构与缺内容分开看：有 OCR 文本只说明该处有入库文本，不等于目标表格内容已取得；"
    "structure_status=partial 仅表示存在单元几何坐标、未做网格语义核验，"
    "不得按相邻顺序还原表格行列关系；display_groups 只在有可靠 row 坐标时给出，"
    "并保留原始 unit 与字符区间映射。"
    "search 的 table_chunks 只统计检索范围内被分类为 table 的块，不等于原 PDF 无表格。"
)

# 与 corpus_fetch A1 词汇一致：verified 需要网格投影成功，全文路径不做该投影，
# 因此这里最多给出 partial（有几何坐标），绝不自行宣称 verified。
_STRUCTURE_PARTIAL = "partial"
_STRUCTURE_UNKNOWN = "unknown"


def _ocr_unit(entry: DocumentUnit) -> bool:
    return (entry.unit.element or "").startswith("local_ocr:")


def _row_cells(entry: DocumentUnit) -> tuple[tuple[int, ...], ...]:
    """只取非 OCR、且每个坐标至少含 (页, 行, 列) 的单元几何。"""
    if _ocr_unit(entry) or not entry.unit.cells:
        return ()
    cells = tuple(cell for cell in entry.unit.cells if len(cell) >= 3)
    return cells if cells and len(cells) == len(entry.unit.cells) else ()


def _display_groups(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按可靠 row 坐标组合展示；**不**改变 items、也不改动引用与覆盖所用的区间。

    只有 ``table_row`` 明确且非 OCR 的连续单元才成组；OCR 文本一律单列，绝不靠
    相邻顺序推断表格关系。组内存的是原始 unit_id + 该 item 的码点区间。
    """
    groups: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None
    for item in items:
        row = item.get("table_row")
        if not row or item.get("ocr_unverified"):
            active = None
            continue
        if active is None or active["row"] != row:
            active = {
                "kind": "table_row",
                "row": row,
                "relation_status": "unverified",
                "unit_ranges": [],
            }
            groups.append(active)
        fragment = item.get("fragment") or {}
        active["unit_ranges"].append(
            {
                "unit_id": item.get("unit_id"),
                "start": int(fragment.get("start", 0)),
                "end": int(fragment.get("end", len(item.get("text") or ""))),
                "evidence_ref": item.get("evidence_ref"),
            }
        )
    # 单个单元的"组"没有展示价值，也会给覆盖统计制造假区间。
    return [group for group in groups if len(group["unit_ranges"]) > 1]


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


def _error(message: str) -> str:
    return _json({"ok": False, "error": message, "fetch_complete": False})


def _identity(document: DocumentUnits) -> str:
    members = [
        (
            entry.unit.unit_id,
            hashlib.sha256(entry.unit.raw_text.encode()).hexdigest(),
            entry.kind,
            entry.status,
        )
        for entry in document.units
    ]
    return hashlib.sha256(json.dumps(members, ensure_ascii=False).encode()).hexdigest()


def _item(doc_id: str, entry: DocumentUnit, start: int, end: int) -> dict[str, Any]:
    unit = entry.unit
    text = unit.raw_text
    item: dict[str, Any] = {
        "locator": unit_locator(unit.unit_id),
        "unit_id": unit.unit_id,
        "kind": entry.kind,
        "page": unit.page,
        "text": text[start:end],
    }
    # Whole units already carry their complete text and a version-bound handle;
    # repeat whole-unit identity metadata only when reconstructing a split unit.
    if start != 0 or end != len(text):
        item.update(
            fragment={"start": start, "end": end},
            text_chars=len(text),
            text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        )
    if entry.status != "kept":
        item["status"] = entry.status
    # 缺结构 ≠ 缺内容：content_status 只说"入库文本在不在"，
    # structure_status 只说"有没有可核验的行列结构"。两者都不描述原 PDF 是否完整。
    item["content_status"] = "ingested_text" if item["text"] else "empty"
    cells = _row_cells(entry)
    item["structure_status"] = _STRUCTURE_PARTIAL if cells else _STRUCTURE_UNKNOWN
    if cells:
        rows = {f"{cell[0]}:{cell[1]}" for cell in cells}
        if len(rows) == 1:
            item["table_row"] = next(iter(rows))
    if _ocr_unit(entry):
        item.update(text_origin="ocr", ocr_unverified=True)
    if item["text"]:
        item["evidence_ref"] = fetch_evidence_ref(doc_id, item)
    return item


def document_page(
    service: CorpusService,
    doc_id: str,
    max_chars: int,
    cursor: dict[str, Any] | None = None,
    unit_range: tuple[int, int] | None = None,
) -> str:
    """Page authoritative units without changing their text, membership or order.

    v2 双预算：``max_chars`` 是**原文**字符预算，可见回执另有硬上限
    （:data:`DOCUMENT_VISIBLE_CAP`），任一先达到即止。游标绑定策略版本、读取范围与
    ``mi``／``off``；缺少策略字段的旧游标沿用 v1 信封计量。
    """
    if type(max_chars) is not int or max_chars < DOCUMENT_MIN_TEXT_BUDGET:
        return _error(
            f"budget_exceeded：max_chars 至少为 {DOCUMENT_MIN_TEXT_BUDGET}"
            "（v2 按原文字符计量），本次未读取任何内容"
        )
    version = policy_version(cursor) if cursor is not None else PAGINATION_POLICY_VERSION
    if cursor is not None and (version not in (1, 2) or (
        POLICY_VERSION_KEY in cursor and type(cursor[POLICY_VERSION_KEY]) is not int
    )):
        return _error("pagination_policy_unsupported：请使用受支持的游标版本")
    text_budget = min(max_chars, 6000) if version == 1 else int(max_chars)
    if unit_range is None:
        unit_range = current_unit_range()
    if cursor is not None and version == 2:
        bound = cursor.get("unit_range")
        if bound is not None and (
            not isinstance(bound, list) or len(bound) != 2
            or any(type(n) is not int for n in bound) or bound[0] < 1 or bound[1] < bound[0]
        ):
            return _error("document_cursor_mismatch：读取范围无效")
        bound_range = tuple(bound) if bound is not None else None
        if unit_range is not None and unit_range != bound_range:
            return _error("document_cursor_mismatch：读取范围已变更，请从本范围重新开始")
        unit_range = bound_range
    if cursor is not None and (
        cursor.get("type") != CONTENT
        or cursor.get("scope") != "document"
        or cursor.get("doc_id") != doc_id
        or cursor.get("build_id") != doc_id.removeprefix("cv2:")
    ):
        return _error("document_cursor_mismatch：游标类型或绑定文档版本不符")
    try:
        document = service.document_units(doc_id)
    except Exception as exc:
        return _json(
            {
                "ok": False,
                "error": f"document_read_failed：{exc}",
                "doc_id": doc_id,
                "scope": "document",
                "fetch_complete": False,
                **read_failure(exc),
            }
        )
    digest = _identity(document)
    if cursor is not None and cursor.get("document_sha256") != digest:
        return _error("document_changed：原文单元集合或内容已变更，不能接续旧游标")
    index = cursor.get("mi", 0) if cursor else 0
    offset = cursor.get("off", 0) if cursor else 0
    units = document.units
    if unit_range is not None:
        lo, hi = unit_range
        units = [entry for pos, entry in enumerate(document.units, start=1) if lo <= pos <= hi]
    if (
        type(index) is not int
        or type(offset) is not int
        or not 0 <= index <= len(units)
        or offset < 0
        or (index == len(units) and offset != 0)
        or (index < len(units) and offset > len(units[index].unit.raw_text))
    ):
        return _error("document_cursor_invalid：单元位置或字符偏移无效")
    start_index, start_offset = index, offset

    def token(mi: int, off: int) -> str:
        return encode_cursor(
            {
                "type": CONTENT,
                "scope": "document",
                "doc_id": doc_id,
                "build_id": document.build_id,
                "document_sha256": digest,
                "mi": mi,
                "off": off,
                # 策略版本随游标旅行：旧游标缺该键即按 v1 续读。
                POLICY_VERSION_KEY: version,
                **({"unit_range": list(unit_range)} if unit_range is not None else {}),
            },
            compressed=True,
        )

    def render(items: list[dict[str, Any]], mi: int, off: int) -> str:
        exhausted = mi == len(units)
        return _json(
            {
                "ok": True,
                "schema_version": 1,
                "cursor_type": CONTENT,
                "scope": "document",
                "coverage_scope": "document_units",
                "doc_id": doc_id,
                "build_id": document.build_id,
                "source_id": document.source_id,
                "original_names": list(document.original_names),
                "document_sha256": digest,
                "source_coverage": "unknown",
                "total_units": len(units),
                **({"unit_range": list(unit_range)} if unit_range is not None else {}),
                "position": {"unit_index": mi, "offset": off},
                # 只承诺入库文本；原 PDF 的图像／表格提取完整性仍是 source_coverage。
                "content_scope": "ingested_text_only",
                "items": items,
                # 展示组合是附加视图：items 与其 fragment/evidence_ref 原封不动，
                # 引用与覆盖统计仍以 items 为准。
                "display_groups": _display_groups(items),
                "item_errors": [],
                "unresolved": [],
                "next_cursor": None if exhausted else token(mi, off),
                "retry_cursor": token(start_index, start_offset),
                "exhausted": exhausted,
                "fetch_complete": exhausted,
                # 策略版本独立成字段：审计可直接读，不必从 page_id 反推。
                "pagination_policy_version": version,
                # 生效预算（原文字符）随页回显，请求预算与生效预算才能对账。
                "max_chars": text_budget,
                "page_id": document_page_id(
                    doc_id=doc_id,
                    build_id=document.build_id,
                    start_index=start_index,
                    start_offset=start_offset,
                    effective_budget=text_budget,
                    version=version,
                    unit_range=unit_range,
                    document_sha256=digest,
                    view="navigation" if navigation_enabled() else "compatible",
                ),
                "hint": _HINT,
            }
        )

    def fits(items: list[dict[str, Any]], mi: int, off: int) -> bool:
        body = render(items, mi, off)
        if version == 1:
            return len(body) <= text_budget
        return len(render_fetch_view(json.loads(body))) <= DOCUMENT_VISIBLE_CAP

    items: list[dict[str, Any]] = []
    text_used = 0
    while index < len(units):
        entry = units[index]
        text = entry.unit.raw_text
        whole = _item(doc_id, entry, offset, len(text))
        text_chars = text_used + (len(text) - offset)
        if (
            text_chars <= text_budget
            and fits([*items, whole], index + 1, 0)
        ):
            items.append(whole)
            text_used = text_chars
            index, offset = index + 1, 0
            continue
        if items:
            break
        # A long unit is split by code-point offsets only at delivery time.
        # 两个预算都要满足：正文切片不超过 text_budget，信封序列化不超过可见上限。
        lo, hi, end = offset + 1, len(text) - 1, offset
        while lo <= hi:
            mid = (lo + hi) // 2
            if (
                mid - offset <= text_budget
                and fits([_item(doc_id, entry, offset, mid)], index, mid)
            ):
                end, lo = mid, mid + 1
            else:
                hi = mid - 1
        if end == offset:
            return _error("budget_exceeded：分页信封与最小片段装不下，请提高 max_chars")
        items.append(_item(doc_id, entry, offset, end))
        text_used += end - offset
        offset = end
        break
    body = render(items, index, offset)
    if not fits(items, index, offset):
        return _error("budget_exceeded：全文分页信封装不下，请提高 max_chars")
    return body


def fit_document_payload(payload: dict[str, Any], budget: int) -> str:
    """Never advance past a page that was discarded by a smaller outer budget."""
    error = {
        "ok": False,
        "code": "budget_exceeded",
        "scope": "document",
        "doc_id": payload["doc_id"],
        "fetch_complete": False,
        "next_cursor": None,
        "retry_cursor": payload["retry_cursor"],
        "error": "budget_exceeded：本页未送达；使用 retry_cursor 并降低 max_chars 重取本页",
    }
    body = _json(error)
    from plugins.corpus.projection import navigation_enabled, project_tool_result
    from plugins.corpus.tool_refs import publish_fetch_references

    if navigation_enabled():
        body = project_tool_result("corpus_fetch", publish_fetch_references(body), error_budget=budget)
    if len(body) > budget:
        return _error("budget_exceeded：本页未送达；以原请求和更小 max_chars 重试，勿前移游标")
    return body
