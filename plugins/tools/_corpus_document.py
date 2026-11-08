"""Document pagination for corpus_fetch; search candidates never define its scope."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from plugins.corpus.cursor import CONTENT, encode_cursor
from plugins.corpus.preparation.document_read import DocumentUnit, DocumentUnits, unit_locator
from plugins.corpus.read_errors import read_failure
from plugins.corpus.tool_refs import fetch_evidence_ref

if TYPE_CHECKING:
    from plugins.corpus.service import CorpusService

# Match the default ReAct/Agent Team result budget before constructing a page.
DOCUMENT_PAGE_BUDGET = 6000
_HINT = (
    "已知文档的原文顺序阅读，无需再次搜索。续读只传 doc_id 和 next_cursor；"
    "items 的 evidence_ref 可直接引用，fragment 为单元内码点区间。"
    "fetch_complete 仅表示本版本入库文本遍历结束，不证明源 PDF 图像、表格提取完整，"
    "也不证明结论已核实。"
)


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
    if (unit.element or "").startswith("local_ocr:"):
        item.update(text_origin="ocr", ocr_unverified=True)
    if item["text"]:
        item["evidence_ref"] = fetch_evidence_ref(doc_id, item)
    return item


def document_page(
    service: CorpusService, doc_id: str, max_chars: int, cursor: dict[str, Any] | None = None
) -> str:
    """Page authoritative units without changing their text, membership or order."""
    budget = min(max_chars, DOCUMENT_PAGE_BUDGET)
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
        return _json({
            "ok": False, "error": f"document_read_failed：{exc}",
            "doc_id": doc_id, "scope": "document", "fetch_complete": False,
            **read_failure(exc),
        })
    digest = _identity(document)
    if cursor is not None and cursor.get("document_sha256") != digest:
        return _error("document_changed：原文单元集合或内容已变更，不能接续旧游标")
    index = cursor.get("mi", 0) if cursor else 0
    offset = cursor.get("off", 0) if cursor else 0
    units = document.units
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
                "document_sha256": digest,
                "source_coverage": "unknown",
                "total_units": len(units),
                "position": {"unit_index": mi, "offset": off},
                "items": items,
                "item_errors": [],
                "unresolved": [],
                "next_cursor": None if exhausted else token(mi, off),
                "retry_cursor": token(start_index, start_offset),
                "exhausted": exhausted,
                "fetch_complete": exhausted,
                "page_id": "docpage:"
                + hashlib.sha256(
                    f"{doc_id}|{digest}|{start_index}|{start_offset}|{budget}".encode()
                ).hexdigest()[:16],
                "hint": _HINT,
            }
        )

    items: list[dict[str, Any]] = []
    while index < len(units):
        entry = units[index]
        text = entry.unit.raw_text
        whole = _item(doc_id, entry, offset, len(text))
        if len(render([*items, whole], index + 1, 0)) <= budget:
            items.append(whole)
            index, offset = index + 1, 0
            continue
        if items:
            break
        # A long unit is split by code-point offsets only at delivery time.
        lo, hi, end = offset + 1, len(text) - 1, offset
        while lo <= hi:
            mid = (lo + hi) // 2
            if len(render([_item(doc_id, entry, offset, mid)], index, mid)) <= budget:
                end, lo = mid, mid + 1
            else:
                hi = mid - 1
        if end == offset:
            return _error("budget_exceeded：分页信封与最小片段装不下，请提高 max_chars")
        items.append(_item(doc_id, entry, offset, end))
        offset = end
        break
    body = render(items, index, offset)
    if len(body) > budget:
        return _error("budget_exceeded：全文分页信封装不下，请提高 max_chars")
    return body


def fit_document_payload(payload: dict[str, Any], budget: int) -> str:
    """Never advance past a page that was discarded by a smaller outer budget."""
    error = {
        "ok": False,
        "scope": "document",
        "doc_id": payload["doc_id"],
        "fetch_complete": False,
        "next_cursor": None,
        "retry_cursor": payload["retry_cursor"],
        "error": "budget_exceeded：本页未送达；使用 retry_cursor 并降低 max_chars 重取本页",
    }
    body = _json(error)
    if len(body) > budget:
        return _error("budget_exceeded：本页未送达；以原请求和更小 max_chars 重试，勿前移游标")
    return body
