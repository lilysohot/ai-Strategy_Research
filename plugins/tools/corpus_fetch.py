"""corpus_fetch — 按取证句柄取回**逐字**原文。

硬闸①「数字可溯源」的在线落点：``evidence.quote`` 必须来自这里返回的文本，
而不是来自 ``corpus_search`` 的 snippet，更不是来自模型的记忆。

设计上刻意只做一件事——给 ``(doc_id, locator)`` 返回该块原文，
不做摘要、不做改写、不做拼接。**任何加工都会让「逐字」这一性质失效**，
而离线校验正是靠逐字比对来抓编造的。

定位符接受整数页码与字符串两种形式（``3`` 与 ``"3"``）：
模型从工具输出抄回时可能带类型变化，不归一化就会出现「明明有这页却取不到」，
那会诱导 Agent 得出「资料里没有」的错误结论。
"""

from __future__ import annotations

import json

from frontier_agent.core.tool import tool
from plugins.corpus.service import get_service


@tool
async def corpus_fetch(doc_id: str, locator: str) -> str:
    """取回语料中指定块的逐字原文，用于写入 ``evidence.quote``。

    在 ``corpus_search`` 之后调用：search 给句柄，本工具给原文。

    Args:
        doc_id: 文档标识（来自 ``corpus_search`` 的 ``doc_id``）。
        locator: 定位符（来自 ``corpus_search`` 的 ``locator``）。
            PDF 是页码（如 ``"3"``），DOCX/MD 是段落块或章节标题。

    Returns:
        JSON 字符串：``{"ok": true, "doc_id", "locator", "text"}``。
        找不到时返回 ``ok=false``——这是正常结果，换个定位符再试即可。
    """
    if not isinstance(doc_id, str) or not doc_id.strip():
        return json.dumps(
            {"ok": False, "error": "doc_id 必须是非空字符串"},
            ensure_ascii=False,
        )

    try:
        svc = get_service()
        block = svc.fetch(doc_id, locator)
    except Exception as exc:
        return json.dumps(
            {"ok": False, "error": f"语料库不可用：{exc}"},
            ensure_ascii=False,
        )

    if block is None:
        return json.dumps(
            {
                "ok": False,
                "error": f"找不到 {doc_id} 的定位符 {locator!r}；"
                "请先用 corpus_search 确认有效的 doc_id 与 locator",
            },
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "ok": True,
            "doc_id": block.doc_id,
            "locator": block.locator,
            "text": block.text,
            "hint": "evidence.quote 必须逐字取自本 text；evidence.page 填本 locator。",
        },
        ensure_ascii=False,
    )
