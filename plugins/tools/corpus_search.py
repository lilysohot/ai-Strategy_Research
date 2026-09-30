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
from typing import Any

from frontier_agent.core.tool import tool
from plugins.corpus.service import get_service

MAX_LIMIT = 20

#: 超预算压缩时逐命中保留的核心字段（模型据此定位并复取，缺一不可）。
_HIT_CORE_KEYS = (
    "doc_id",
    "locator",
    "source_id",
    "build_id",
    "chunk_id",
    "scope_id",
    "context_locators",
    "fetch_plan",
)
#: 核心字段之外按预算余量保留的可选字段（顺序即保留优先级）。
_HIT_OPTIONAL_KEYS = ("title", "published", "snippet", "by_kind")

#: 命中被按预算整条舍弃时替换的提示（明确后续动作，不让模型以为检索已取全）。
_ELIDED_HINT = (
    "本次命中数超过工具结果预算，已按相关度**整条**舍弃尾部命中"
    "（舍弃条数见 hits_elided，最相关的若干条仍完整保留）。"
    "snippet 已截断，仅用于定位，禁止直接引用；"
    "写 evidence 前请用 corpus_fetch(doc_id, locator) 取回逐字原文，"
    "并依次取回 context_locators。需要看全被舍弃的命中时，"
    "请用更具体的 query 或更小的 limit 重新检索。"
)

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


#: B2 abstain 拒检的分流提示：有检索候选但判定为无实质答案而过拒检（与
#: ``no_match``「无研报覆盖」机器可区分）。同样是流程级指令：不许编造研报、不重试。
ABSTAIN_HINT = (
    "查询命中候选，但判定为**无实质答案**（query_status=abstain；availability=unknown"
    "——只说明判为拒检，不等于资料不存在）。**请立即停止继续检索研报，不要反复重试本工具**，"
    "切换市场数据路径并明确标注『无研报覆盖，结论基于市场数据与技术面』："
    "① 用 market_resolve 消歧；② 用 market_quote 取实时行情；③ 用 market_history 取历史序列。"
    "纪律：禁止编造或引用不存在的研报；最终结论不得凭空给出研报级数字。"
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
        "build_id", "chunk_id", "context_locators", "fetch_plan", "title",
        "published", "snippet"}],
        "coverage": {...}, "hint": ...}``（I2-8：``doc_id`` 为 ``cv2:<build_id>``、
        ``locator`` 为 ``chunk:<chunk_id>``；``coverage`` 为 §7.3 三轴对象）；
        语料库不存在时返回 ``ok=false``。结果超过本轮工具结果预算时不会按字符硬切
        （那样会破坏 JSON 与句柄），而是整条舍弃尾部命中并标 ``hits_elided``、
        去掉可推导字段并标 ``diagnostics_elided``；连一条都装不下时返回
        ``ok=false`` 的预算错误，提示缩小 query 或 limit。
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
        # B2：被 abstain 拒检（有检索候选但无实质答案）与 no_match（无研报覆盖）
        # 机器可区分——coverage["abstain"] 为真时走 ABSTAIN_HINT 并置顶层 abstain。
        if coverage.get("abstain"):
            return json.dumps(
                {
                    "ok": True,
                    "query": query,
                    "count": 0,
                    "hits": [],
                    "coverage": coverage,
                    "abstain": True,
                    "hint": ABSTAIN_HINT,
                },
                ensure_ascii=False,
            )
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
                    "context_locators": list(hit.context_locators),
                    # 把文档句柄与上下文范围组成一个不可拆的复取计划。
                    # 这避免调用方从不同命中拼接 doc_id 与 locator。
                    "fetch_plan": {
                        "doc_id": hit.doc_id,
                        "locator": hit.locator,
                        "locators": list(hit.context_locators),
                        "scope_id": hit.scope_id,
                        "view": "compact",
                    },
                    # A1 内联 scope 摘要：成员范围身份 + 按 kind 计数 + 表块数。
                    # 只报告**块**统计，不声称「共有几张表」（表身份未知时为 null）。
                    "scope_id": hit.scope_id,
                    "total_chunks": len(hit.context_locators),
                    "by_kind": dict(hit.context_by_kind),
                    "table_chunks": dict(hit.context_by_kind).get("table", 0),
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
                "写 evidence 前请严格使用同一命中的 fetch_plan.doc_id 与"
                "fetch_plan.locators 和 fetch_plan.view 调用 corpus_fetch；不得把不同命中的 doc_id、"
                "locator 或 context_locators 混在一起。这些句柄共同构成有界的文档证据区。"
                "需要先看清这批上下文候选的结构（哪些是标题、哪些是表格块、"
                "各自覆盖哪些页与区间）时，用 corpus_inventory(doc_id, locators=context_locators)。"
            ),
        },
        ensure_ascii=False,
    )


def _compact_hit(hit: dict[str, Any]) -> dict[str, Any]:
    """逐命中只保留定位与复取必需字段（其余为可推导／诊断字段）。"""
    out = {key: hit[key] for key in _HIT_CORE_KEYS if key in hit}
    for key in _HIT_OPTIONAL_KEYS:
        if key in hit:
            out[key] = hit[key]
    return out


def fit_search_payload(body: str, budget: int) -> str | None:
    """A0.3：把 ``corpus_search`` 的结构化 JSON 结果压进 ``budget``，始终返回**合法 JSON**。

    与 ``corpus_fetch.fit_structured_payload`` 同一契约，策略按搜索结果的语义定：
    命中按相关度排序，**整条命中**才是「一篇可去读的文档」这一原子单位，所以逐级
    降级但绝不切开单条命中的 ``context_locators``——那是本次请求的取证范围，切开会让
    「有界证据区」的承诺与账本的 offered 集合同时失真；也不按字符硬切（会同时破坏
    JSON 与句柄）。降级阶梯：

    1. ≤ ``budget``：原样返回，不改任何字段；
    2. 超预算：逐命中只保留定位与复取必需字段（其余可推导／诊断字段去掉），装下即返回，
       并标 ``diagnostics_elided``；
    3. 仍超：按相关度从**尾部整条**舍弃命中（至少保留 1 条），标 ``hits_elided``；
    4. 连 1 条都装不下：返回可识别的**预算错误**（仍为合法 JSON），不返回残缺正文。

    非成功结果或不可解析时返回 ``None``（交回调用方按原策略处理）。
    """
    if budget <= 0 or not isinstance(body, str):
        return None
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return None
    if len(body) <= budget:
        return body

    hits = [hit for hit in (payload.get("hits") or []) if isinstance(hit, dict)]
    if not hits:
        return None

    compact_hits = [_compact_hit(hit) for hit in hits]

    def render(keep: list[dict[str, Any]]) -> str:
        out: dict[str, Any] = {
            "ok": True,
            "query": payload.get("query"),
            "count": payload.get("count", len(hits)),
            "hits": keep,
            "coverage": payload.get("coverage"),
            "hint": payload.get("hint"),
            "diagnostics_elided": True,
        }
        if len(keep) < len(hits):
            out["hits_elided"] = len(hits) - len(keep)
            out["hint"] = _ELIDED_HINT
        return json.dumps(out, ensure_ascii=False)

    candidate = render(compact_hits)
    if len(candidate) <= budget:
        return candidate

    for keep in range(len(compact_hits) - 1, 0, -1):
        candidate = render(compact_hits[:keep])
        if len(candidate) <= budget:
            return candidate

    return json.dumps(
        {
            "ok": False,
            "error": (
                "budget_exceeded：本次检索命中的定位句柄超过本轮工具结果预算；"
                "为避免截断出非法 JSON 或丢掉取证范围，未返回命中。"
                "请用更具体的 query 或更小的 limit 重新检索。"
            ),
            "query": payload.get("query"),
            "hits_total": len(hits),
            "budget": budget,
        },
        ensure_ascii=False,
    )
