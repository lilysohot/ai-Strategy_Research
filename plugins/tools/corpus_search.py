"""corpus_search — 语料检索。**只定位，不取证。**

与 ``corpus_fetch`` 的分工是整个硬闸①的机制核心：

- 本工具返回**截断的** snippet（两端带省略号）+ 取证句柄（``doc_id`` + ``locator``）
- 要逐字原文，必须再调 ``corpus_fetch``

snippet 故意给不全，不是偷懒：如果这里就把整段原文吐出来，Agent 没有任何
理由再去调 fetch，于是「引用必须逐字来自原文」就退化成一句提示词，
而提示词是最容易被绕过的一层。把原文锁在另一个工具里，
溯源就从「叮嘱」变成了「路径」。

返回体里带 ``hint`` 字段而不是只在文档串里写：Agent 读到工具输出时，
``hint`` 就在眼前；文档串里的说明它未必看得到。
"""

from __future__ import annotations

import json
import sqlite3

from frontier_agent.core.tool import tool
from plugins.corpus.index import search
from plugins.corpus.ingest import DEFAULT_DB_PATH, connect

MAX_LIMIT = 20


@tool
async def corpus_search(query: str, limit: int = 10) -> str:
    """在研报语料库里检索，返回命中的文档与定位句柄（**不含**完整原文）。

    用于**定位**：找到哪些研报的哪些页/章节在谈这个话题。
    拿到句柄后，必须调用 ``corpus_fetch`` 取回逐字原文才能写入 evidence——
    本工具返回的 snippet 是**截断**的，禁止直接引用。

    Args:
        query: 检索词。可以是关键词、数字（如 ``47.3亿``、``30%``）
            或一句话；数字与其单位会被整体匹配。
        limit: 返回条数上限，默认 10。

    Returns:
        JSON 字符串：``{"ok": true, "hits": [{"doc_id", "locator", "title",
        "snippet"}], "hint": ...}``；语料库不存在时返回 ``ok=false``。
    """
    if not isinstance(query, str) or not query.strip():
        return json.dumps(
            {"ok": False, "error": "query 必须是非空字符串", "hits": []},
            ensure_ascii=False,
        )
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        limit = 10
    limit = min(limit, MAX_LIMIT)

    try:
        conn = connect(DEFAULT_DB_PATH)
    except sqlite3.Error as exc:
        return json.dumps(
            {"ok": False, "error": f"语料库不可用：{exc}", "hits": []},
            ensure_ascii=False,
        )

    try:
        hits = search(conn, query, limit=limit)
    except sqlite3.Error as exc:
        # 索引未建是最常见的失败原因，单独说清楚，否则 Agent 会以为「资料里没有」
        return json.dumps(
            {
                "ok": False,
                "error": f"检索失败（语料索引可能尚未建立）：{exc}",
                "hits": [],
            },
            ensure_ascii=False,
        )
    finally:
        conn.close()

    return json.dumps(
        {
            "ok": True,
            "query": query,
            "count": len(hits),
            "hits": [
                {
                    "doc_id": hit.doc_id,
                    "locator": hit.locator,
                    "title": hit.title,
                    "published": hit.published,
                    "snippet": hit.snippet,
                }
                for hit in hits
            ],
            # hint 显式告诉模型下一步该做什么，而不是让它自己领会
            "hint": (
                "snippet 已截断，仅用于定位，禁止直接引用。"
                "写 evidence 前请用 corpus_fetch(doc_id, locator) 取回逐字原文，"
                "并把 locator 原样填进 evidence.page。"
            ),
        },
        ensure_ascii=False,
    )
