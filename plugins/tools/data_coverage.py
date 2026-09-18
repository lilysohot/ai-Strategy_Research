"""data_coverage —— **开局一次性**探测数据源覆盖度。

解决的问题：模型此前只能逐个工具试错——先 `corpus_search` 发现没研报，
再试 `market_quote` 才知道有没有行情，白费轮次，还容易在半途"以为没数据"
而放弃或硬凑。

本工具开局跑一次就给出全景：

    该标的：研报 0 篇 / 行情可用 / 财报可用 ⇒ verdict=partial

并对四种结论给出**明确指令**，其中两种是硬要求：

- ``partial``（无研报有行情）：**停止检索研报**，转市场数据 + 技术面；
- ``none``（全空）：**直接输出「数据不足，不做判断」**，禁止编造任何数字
  —— 这不是失败，而是唯一正确的产出。
"""

from __future__ import annotations

import json

from frontier_agent.core.tool import tool
from plugins.market.factory import build_service, resolve_or_error, unavailability
from plugins.market.ports import MarketUnavailable

#: 探测研报时最多取几条（只要判断"有没有"，不需要全部）
RESEARCH_PROBE_LIMIT = 5

GUIDANCE_FULL = (
    "研报与行情数据均可用：走完整流程。"
    "观点 / 逻辑 / 目标价用研报（corpus_fetch 取逐字原文），"
    "价格与财报用市场数据（引用必须带 as_of 时点）。"
)

GUIDANCE_PARTIAL = (
    "**无研报覆盖，但行情 / 财报可用**：请立即停止检索研报（不要反复重试 corpus_search），"
    "也不要拿不相关的研报凑 evidence。改走市场数据路径："
    "market_quote 取实时行情与估值 → market_history 取历史序列做技术面分析"
    "（区间 / 均线 / 波动 / 回撤）。"
    "你自主发挥的是**判断与观点**；技术指标的数值须来自确定性工具并带 computed_by，"
    "不得自行计算（硬闸②）。结论请标注『无研报覆盖，结论基于市场数据与技术面』。"
)

GUIDANCE_RESEARCH_ONLY = (
    "有研报但**行情数据不可用**（标的代码可能不被数据源覆盖，或接口暂不可用）。"
    "此时只能基于研报做定性分析，**禁止给出任何具体价格 / 涨跌幅 / 估值数字**"
    "（拿不到就写『数据未给出』）。不要为了补齐数字去猜价格。"
)

GUIDANCE_NONE = (
    "**三个数据源都没有该标的的可用数据**（无研报、无行情、无财报）。"
    "正确做法：直接给出结论『数据不足，不做判断』，并说明缺什么数据、"
    "以及需要补充什么才能分析。**这是本情形下的唯一正确产出，不是失败。**"
    "严禁编造任何数字、严禁引用不存在的研报或行情；"
    "也不要因为『总得说点什么』而给出无依据的倾向性意见。"
)


@tool
async def data_coverage(query: str, with_financials: bool = True) -> str:
    """开局探测某个标的的数据源覆盖度（研报 / 行情 / 财报），一次性给出全景与下一步。

    **建议在开始分析任何标的时先调用本工具**，据此决定走哪条路径，
    避免逐个工具试错。

    Args:
        query: 标的名称 / 代码 / thscode（如「茅台」「600519」「600519.SH」）。
        with_financials: 是否顺带探测财报（会多一次接口调用，默认 True）。

    Returns:
        JSON 字符串：``{"ok": true, "thscode", "coverage": {"research": {...},
        "quote": {...}, "financials": {...}, "web": {...}}, "verdict", "guidance"}``。
        ``verdict`` 取 ``full`` / ``partial`` / ``research_only`` / ``none``；
        ``guidance`` 是针对该结论的**明确指令**（``none`` 时要求输出「数据不足，不做判断」）。
    """
    if not isinstance(query, str) or not query.strip():
        return json.dumps(
            {"ok": False, "reason": "query 必须是非空字符串", "next": "传入标的名称或代码"},
            ensure_ascii=False,
        )

    # ① 研报：只要判断有没有，取少量即可；并透出 §7.3 三轴覆盖对象（RM-I28-4）
    research_count = 0
    research_error: str | None = None
    research_coverage: dict | None = None
    try:
        from plugins.corpus.service import get_service as corpus_service

        svc = corpus_service()
        # 命中与覆盖同快照取回（§7.3）；旧实现（无组合读取）退回两步并标注 query_status
        if hasattr(svc, "search_with_coverage"):
            hits, research_coverage = svc.search_with_coverage(query, limit=RESEARCH_PROBE_LIMIT)
            research_count = len(hits)
        else:
            research_count = len(svc.search(query, limit=RESEARCH_PROBE_LIMIT))
            # 覆盖对象可选：无该能力的旧替身（测试桩/旧 Service）只影响三轴透出，
            # 不影响「有没有研报」的计数语义。
            coverage_getter = getattr(svc, "coverage", None)
            if callable(coverage_getter):
                try:
                    candidate = coverage_getter(
                        query_status="matched" if research_count else "no_match"
                    )
                    research_coverage = dict(candidate) if isinstance(candidate, dict) else None
                except Exception:
                    research_coverage = None
    except Exception as exc:  # 语料库不可用 ≠ 没有研报，两者要分开记
        research_error = f"{type(exc).__name__}: {exc}"[:120]

    # ② 市场：行情与财报（凭据缺失 / 接口失败都要能区分）
    thscode: str | None = None
    quote_ok, fin_ok = False, False
    quote_as_of: int | None = None
    latest_report_ms: int | None = None
    market_error: str | None = None

    denied = unavailability()
    if denied is not None:
        market_error = denied.get("reason")
    else:
        service = build_service()
        if service is None:
            market_error = "market 服务不可用"
        else:
            resolved, error = resolve_or_error(service, query)
            if error is not None:
                market_error = str(error.get("reason") or error.get("next") or "消歧失败")[:160]
            else:
                thscode = str(resolved)
                try:
                    quote_result = service.quote([thscode])
                    items = quote_result.get("items") or []
                    quote_ok = bool(items)
                    if items:
                        quote_as_of = items[0].get("as_of_ms")
                except MarketUnavailable as exc:
                    market_error = f"{exc.kind}: {exc.message}"[:160]

                if with_financials:
                    try:
                        fin_result = service.financials(thscode, period="annual")
                        fin_items = fin_result.get("items") or []
                        fin_ok = bool(fin_items)
                        if fin_items:
                            latest_report_ms = fin_items[0].get("report_date_ms")
                    except MarketUnavailable:
                        fin_ok = False

    research_ok = research_count > 0
    market_ok = quote_ok or fin_ok

    if research_ok and market_ok:
        verdict, guidance = "full", GUIDANCE_FULL
    elif market_ok:
        verdict, guidance = "partial", GUIDANCE_PARTIAL
    elif research_ok:
        verdict, guidance = "research_only", GUIDANCE_RESEARCH_ONLY
    else:
        verdict, guidance = "none", GUIDANCE_NONE

    return json.dumps(
        {
            "ok": True,
            "query": query,
            "thscode": thscode,
            "coverage": {
                "research": {
                    "available": research_ok,
                    "count": research_count,
                    "error": research_error,
                },
                "quote": {
                    "available": quote_ok,
                    "as_of_ms": quote_as_of,
                    "error": None if quote_ok else market_error,
                },
                "financials": {
                    "available": fin_ok,
                    "latest_report_date_ms": latest_report_ms,
                    "error": None if fin_ok else market_error,
                },
                "web": {
                    "available": True,
                    "note": "公网检索兜底（web_search / web_fetch），须给可定位来源；不属于标的结构化数据",
                },
            },
            # 研报侧 §7.3 三轴（requested/effective/publication_snapshot/counts）：
            # 与市场侧字段**分层**——上面 coverage.* 是各数据源的可用性/计数，
            # 本键是语料新链的处理完整度与查询状态，两者不互相替代。
            "research_coverage": research_coverage,
            "verdict": verdict,
            "guidance": guidance,
        },
        ensure_ascii=False,
    )
