"""corpus_inventory — 有来源依据的上下文结构清单（A1）。

与 ``corpus_search``／``corpus_fetch`` 的分工：

- ``corpus_search`` 定位并给出**有界上下文候选**（``context_locators``）与内联 scope
  摘要（``scope_id``、成员数与按 kind 计数）；
- 本工具把这些候选展开为**逐成员的结构清单**：每个成员自身的 ``kind``、``page_range``、
  所属**实际选择区间** ``region_ids``、``structure_status`` 及确有依据的结构字段；
- 要逐字原文仍必须走 ``corpus_fetch``——清单只描述结构，不给正文。

纪律（01 §A1）：

- **结构有依据才声明**：无持久化表身份 → ``table_ref`` 为 ``null``；未掌握完整表网格
  → ``table_rows``／``table_cols`` 为 ``null``（**不填 0**）；未知一律 ``null``／``unknown``，
  不补造行列、不用 ``max(cells)`` 推算整表规模；
- **不引入中间块**：成员集合就是传入的有序 locator 集合（按首次出现去重），
  ``region_ids`` 只表达成员自身所属区间，不把两个区间之间的块算进来；
- **清单过大时分页**：总数与当前页成员分别标识，游标类型为 ``inventory``，与正文
  分页的 ``content`` 游标严格区分、禁止混用（01 §A1.1、§A2.2）。

消费提示（01 §A1.2）：这些块是本次检索提供的上下文候选；标题不包含表体；按问题选择
证据范围，涉及表中结论时补齐必要表头、期间、单位及脚注——而不是无条件读取所有表。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from frontier_agent.core.tool import tool
from plugins.corpus.cursor import INVENTORY, CursorError, decode_cursor, encode_cursor
from plugins.corpus.service import get_service

#: 清单页信封 schema 版本（与游标绑定，变更即显式失效）。
_SCHEMA_VERSION = 1

#: 分页预算下限：低于此值连信封都装不下，直接返回可识别的预算错误。
_MIN_BUDGET = 400

#: 消费提示：不写成「无条件读取所有表」。
_HINT = (
    "这些块是本次检索提供的上下文候选，不是已读内容；content_role=heading_only 的"
    "标题块只证明标题被取回，不含表体。按问题选择证据范围：涉及表中的结论时，补齐"
    "必要表头、期间、单位及脚注。relations 是本次范围内的结构关联（verified=持久化"
    "结构树／表题证明，candidate=同章节邻接），候选不得当作已满足表体依赖。"
    "table_ref/table_rows/table_cols 为 null 表示**尚无依据**，不得据此推断整表规模。"
    "要逐字原文请用 corpus_fetch(doc_id, locator)。"
)


def _page_id(scope_id: str, start: int, end: int, budget: int) -> str:
    """页身份：由范围身份 + 本页覆盖的成员下标区间 + 有效预算决定。

    固定游标 + 相同有效预算重放 → 同一 ``page_id``（01 §A2.2 的可重放性要求）。
    """
    digest = hashlib.sha256(f"{scope_id}|{start}|{end}|{budget}".encode()).hexdigest()
    return f"invpage:{digest[:16]}"


def _error(message: str, **extra: Any) -> str:
    payload: dict[str, Any] = {"ok": False, "error": message}
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def _dedupe(locators: list[str]) -> list[str]:
    """按首次出现去重并固定顺序（01 §A2.1：批量输入去重规则确定）。"""
    seen: set[str] = set()
    out: list[str] = []
    for locator in locators:
        if not isinstance(locator, str) or not locator.strip():
            raise ValueError("locators 必须是非空字符串列表")
        if locator not in seen:
            seen.add(locator)
            out.append(locator)
    return out


@tool
async def corpus_inventory(
    doc_id: str,
    locators: list[str] | None = None,
    cursor: str | None = None,
    max_chars: int = 6000,
) -> str:
    """取回一组上下文候选 locator 的**有依据结构清单**（分页）。

    在 ``corpus_search`` 之后调用：把该次检索提供的上下文候选（``context_locators``，
    或续取用的 ``cursor``）展开为逐成员的结构清单。清单只描述结构，不含正文——
    逐字原文请用 ``corpus_fetch``。

    Args:
        doc_id: 版本句柄（来自 ``corpus_search`` 的 ``doc_id``，形如 ``cv2:<build_id>``）。
        locators: 本次清单的成员 locator（``chunk:<chunk_id>``），**有序**；按首次出现去重。
            与 ``cursor`` 恰选其一。
        cursor: 续取游标（上一页返回的 ``next_cursor``；类型必须为 ``inventory``）。
            与 ``locators`` 恰选其一；游标已绑定请求集合、顺序与视图，续取时不得改动。
        max_chars: 本页序列化 JSON 的字符上限（含信封与转义）；服务按实际路径预算收紧。

    Returns:
        JSON 字符串页信封：``{"ok": true, "schema_version", "cursor_type": "inventory",
        "doc_id", "build_id", "scope_id", "total_chunks", "by_kind", "table_chunks",
        "regions", "page_id", "items", "next_cursor", "exhausted", "hint"}``。
        每个 item（成员）另带 ``content_role``（标题块为 ``heading_only``）、``relations``
        （本次范围内的结构关联，``verified`` 与 ``candidate`` 严格分开）与
        ``relation_status``。参数非法、游标类型不符（如误传 ``content`` 游标）、句柄为
        旧句柄或预算不足时返回 ``ok=false`` 及原因，不返回残缺清单。
    """
    if not isinstance(doc_id, str) or not doc_id.strip():
        return _error("doc_id 必须是非空字符串")
    if not doc_id.startswith("cv2:"):
        return _error(
            "archive_required：该 doc_id 是旧句柄（非 cv2:<build_id>），新链不以其取清单",
            doc_id=doc_id,
        )
    if (locators is None) == (cursor is None):
        return _error("locators 与 cursor 恰选其一（不得同时给出或同时省略）")
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars < _MIN_BUDGET:
        return _error(
            f"max_chars 必须是 ≥ {_MIN_BUDGET} 的整数（收到 {max_chars!r}）；"
            "预算过小则连页信封都装不下",
        )

    # 解析请求集合与起始位置：游标模式绑定请求集合与顺序，调用方不得借参数改动。
    if cursor is not None:
        try:
            payload = decode_cursor(cursor)
        except CursorError as exc:
            return _error(f"游标不可用：{exc}", cursor_type=INVENTORY)
        if payload.get("type") != INVENTORY:
            return _error(
                f"游标类型不符：该游标是 {payload.get('type')!r}，本工具只接受 {INVENTORY!r}",
                cursor_type=INVENTORY,
            )
        if payload.get("doc_id") != doc_id:
            return _error(
                "游标绑定的 doc_id 与本次调用不一致；续取不得切换文档/版本",
                cursor_type=INVENTORY,
            )
        request = [str(item) for item in (payload.get("req") or [])]
        start = int(payload.get("pos") or 0)
        if not request:
            return _error("游标未绑定任何成员集合（损坏）", cursor_type=INVENTORY)
    else:
        try:
            request = _dedupe(list(locators or []))
        except ValueError as exc:
            return _error(str(exc))
        if not request:
            return _error("locators 不能为空列表")
        start = 0

    try:
        svc = get_service()
        inventory = svc.context_inventory(doc_id, request)
    except Exception as exc:  # 句柄不可解析 / 跨 build / 来源撤销 / 完整性不符 → fail-closed
        return _error(f"清单构建失败（句柄不可解析、跨 build 或来源已撤销）：{exc}")

    members: list[dict[str, object]] = list(inventory["members"])  # type: ignore[arg-type]
    if start >= len(members):
        start = len(members)

    envelope: dict[str, Any] = {
        "ok": True,
        "schema_version": _SCHEMA_VERSION,
        "cursor_type": INVENTORY,
        "doc_id": inventory["doc_id"],
        "build_id": inventory["build_id"],
        "scope_id": inventory["scope_id"],
        "total_chunks": inventory["total_chunks"],
        "by_kind": inventory["by_kind"],
        "table_chunks": inventory["table_chunks"],
        "regions": inventory["regions"],
        "unknown_members": inventory["unknown_members"],
        "hint": _HINT,
    }

    # 先量信封本身；装不下就返回可识别的预算错误，不返回残缺清单。
    empty_probe = json.dumps(
        {**envelope, "items": [], "next_cursor": None, "exhausted": False},
        ensure_ascii=False,
    )
    if len(empty_probe) > max_chars:
        return _error(
            "budget_exceeded：本次 max_chars 连清单页信封都装不下；请提高 max_chars 或缩小请求范围",
            doc_id=doc_id,
            scope_id=inventory["scope_id"],
        )

    page_items: list[dict[str, object]] = []
    index = start
    while index < len(members):
        candidate = [*page_items, members[index]]
        probe = json.dumps({**envelope, "items": candidate}, ensure_ascii=False)
        if len(probe) > max_chars and page_items:
            break
        page_items = candidate
        index += 1

    exhausted = index >= len(members)
    next_cursor = None
    if not exhausted:
        next_cursor = encode_cursor(
            {
                "type": INVENTORY,
                "doc_id": doc_id,
                "build_id": inventory["build_id"],
                "scope_id": inventory["scope_id"],
                "req": request,
                "pos": index,
            }
        )
    envelope["items"] = page_items
    envelope["next_cursor"] = next_cursor
    envelope["exhausted"] = exhausted
    envelope["page_id"] = _page_id(str(inventory["scope_id"]), start, index, max_chars)
    return json.dumps(envelope, ensure_ascii=False)
