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

from frontier_agent.core.tool import tool
from plugins.corpus.service import get_service

MAX_LIMIT = 20

#: 无研报覆盖时的**流程级指令**（不是建议，是要求）。
#:
#: 关键点：语料里没有相关研报时，必须让模型**立刻停下「继续找研报」这条路**
#: （否则它会反复检索，或去够一篇沾边但不相关的研报凑 evidence），
#: 转而走市场数据 + 技术面。同时钉住纪律：禁止编造研报、指标数值不得由模型自算。
NO_COVERAGE_HINT = (
    "当前已发布范围内没有与该查询匹配的研报（query_status=no_match；"
    "availability=unknown——只说明该范围无匹配，不等于资料不存在）。"
    "**请立即停止继续检索研报，不要反复重试本工具**，切换到市场数据路径："
    "① 用 market_resolve 把标的消歧成 thscode（数据端点不接受纯代码）；"
    "② 用 market_quote 取实时行情与估值（价格实时变化，务必带 as_of 时点）；"
    "③ 用 market_history 取历史序列，做区间 / 均线 / 波动等技术面分析。"
    "纪律：禁止编造或引用不存在的研报；"
    "技术指标的**数值**必须来自确定性工具并带 computed_by，不得由你自行计算（硬闸②）；"
    "最终结论请明确标注『无研报覆盖，结论基于市场数据与技术面』，"
    "并在 evidence 中如实反映数据来源（市场接口而非研报）。"
)


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
        JSON 字符串：``{"ok": true, "hits": [{"doc_id", "locator", "source_id",
        "build_id", "chunk_id", "title", "published", "snippet"}],
        "coverage": {...}, "hint": ...}``（I2-8：``doc_id`` 为 ``cv2:<build_id>``、
        ``locator`` 为 ``chunk:<chunk_id>``；``coverage`` 为 §7.3 三轴对象）；
        语料库不存在时返回 ``ok=false``。
    """
    if not isinstance(query, str) or not query.strip():
        return json.dumps(
            {"ok": False, "error": "query 必须是非空字符串", "hits": []},
            ensure_ascii=False,
        )
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        limit = 10
    limit = min(limit, MAX_LIMIT)

    coverage: dict | None = None
    try:
        svc = get_service()
        # §7.3：命中与覆盖元数据必须取自同一数据库快照（RM-I28-3）；
        # Service 提供组合读取时一次取回，避免拼接两个时刻的状态。
        if hasattr(svc, "search_with_coverage"):
            hits, coverage = svc.search_with_coverage(query, limit=limit)
        else:
            hits = svc.search(query, limit=limit)
    except Exception as exc:  # 库不可用 / 连接失败 / 检索异常统一归到 ok=false
        return json.dumps(
            {
                "ok": False,
                "error": f"检索失败（语料库可能未就绪）：{exc}",
                "hits": [],
            },
            ensure_ascii=False,
        )

    status = "matched" if hits else "no_match"
    if coverage is None:
        try:
            coverage = svc.coverage(query_status=status)
        except Exception:  # 覆盖统计不可读不影响主流程，但必须显式为 unknown
            coverage = {
                "processing": "unknown",
                "query_status": status,
                "availability": "unknown",
                "reason_codes": ("coverage_unavailable",),
            }

    if not hits:
        # 「没有相关研报」与「检索成功但为空」此前长得一样（ok=true + 空 hits），
        # 模型无法区分，容易硬凑。这里给出**显式覆盖度信号 + 明确的下一步**。
        # I2-8：空命中按 §7.3 表述为"该已查询范围无匹配"，不给 availability=absent。
        return json.dumps(
            {
                "ok": True,
                "query": query,
                "count": 0,
                "hits": [],
                "coverage": coverage,
                "hint": NO_COVERAGE_HINT,
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "ok": True,
            "query": query,
            "count": len(hits),
            "hits": [
                {
                    # I2-8 §7.2 版本句柄：doc_id=cv2:<build_id>、locator=chunk:<chunk_id>
                    "doc_id": hit.doc_id,
                    "locator": hit.locator,
                    "source_id": hit.source_id,
                    "build_id": hit.build_id,
                    "chunk_id": hit.chunk_id,
                    "title": hit.title,
                    "published": hit.published,
                    "snippet": hit.snippet,
                }
                for hit in hits
            ],
            "coverage": coverage,
            # hint 显式告诉模型下一步该做什么，而不是让它自己领会
            "hint": (
                "snippet 已截断，仅用于定位，禁止直接引用。"
                "写 evidence 前请用 corpus_fetch(doc_id, locator) 取回逐字原文，"
                "并把 locator 原样填进 evidence.page。"
            ),
        },
        ensure_ascii=False,
    )
