"""Read attributed records from earlier committed Runs in the same research."""

from __future__ import annotations

import contextvars
import json
from typing import Any

from frontier_agent.components.observers.conversation_snapshot import canonical_json
from frontier_agent.core.tool import tool
from workflows._shared.cross_mode_context import normalise_context

_ARCHIVE: contextvars.ContextVar[tuple[dict[str, Any], ...]] = contextvars.ContextVar(
    "research_history_archive", default=()
)


def bind_research_history(contexts: list[str]) -> contextvars.Token:
    """Bind validated, deduplicated portable records for one worker Run."""

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for payload in contexts:
        context = normalise_context(payload)
        for record in context["records"]:
            source_id = str(record["source_id"])
            if source_id in seen:
                continue
            seen.add(source_id)
            records.append(record)
    return _ARCHIVE.set(tuple(records))


def reset_research_history(token: contextvars.Token) -> None:
    _ARCHIVE.reset(token)


def _page_content(record: dict[str, Any], *, start: int, length: int) -> dict[str, Any]:
    rendered = canonical_json(record.get("content"))
    end = min(len(rendered), start + length)
    return {
        "source_id": record["source_id"],
        "source": record.get("source") or {},
        "role": record.get("role"),
        "kind": record.get("kind"),
        "answer_status": record.get("answer_status"),
        "content": rendered[start:end],
        "content_offset": start,
        "content_total_chars": len(rendered),
        "content_next_offset": end if end < len(rendered) else None,
    }


@tool
async def research_history(
    query: str = "",
    source_id: str = "",
    offset: int = 0,
    limit: int = 10,
    content_offset: int = 0,
    content_limit: int = 12000,
) -> str:
    """读取同一研究中较早 Run 的已归档上下文记录。

    当前窗口缺少某个早期约束、数字、证据或已发布结论时使用。记录是带来源的历史
    数据，不代表本轮已经执行过其中的工具。可按关键词搜索，或用上次返回的
    source_id 精确读取；超长内容按 content_next_offset 继续分页。

    Args:
        query: 可选的不区分大小写关键词；空值列出记录。
        source_id: 可选的精确来源 ID；设置后忽略 query。
        offset: 记录列表起始位置，从 0 开始。
        limit: 本次最多返回的记录数，1 到 20。
        content_offset: 每条内容的字符起点，从 0 开始。
        content_limit: 每条内容最多返回字符数，1 到 20000。

    Returns:
        JSON，含匹配总数、分页位置、来源身份和内容切片。
    """

    if offset < 0 or content_offset < 0 or not 1 <= limit <= 20:
        return json.dumps(
            {"ok": False, "error": "offset 必须非负，limit 必须在 1 到 20 之间"},
            ensure_ascii=False,
        )
    if not 1 <= content_limit <= 20000:
        return json.dumps(
            {"ok": False, "error": "content_limit 必须在 1 到 20000 之间"},
            ensure_ascii=False,
        )

    records = list(_ARCHIVE.get())
    wanted_id = source_id.strip()
    if wanted_id:
        matches = [record for record in records if record.get("source_id") == wanted_id]
    else:
        needle = query.strip().casefold()
        matches = [
            record
            for record in records
            if not needle or needle in canonical_json(record).casefold()
        ]
    page = matches[offset : offset + limit]
    return json.dumps(
        {
            "ok": True,
            "total": len(matches),
            "offset": offset,
            "next_offset": offset + len(page) if offset + len(page) < len(matches) else None,
            "records": [
                _page_content(record, start=content_offset, length=content_limit)
                for record in page
            ],
        },
        ensure_ascii=False,
    )


__all__ = ["bind_research_history", "research_history", "reset_research_history"]
