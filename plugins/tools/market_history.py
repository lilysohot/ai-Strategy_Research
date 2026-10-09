"""market_history — 历史日 K 线。

默认 `adjust=none`（不复权）：前复权序列会以「最新」为基准重算，**跨次调用不可比**
（§9 坑 1）。确需前复权时，返回的 `adjust` 字段会标注口径，引用时必须一并说明。

**回溯天数上限（试验阶段筛选）**：10 年日线约 2400 条 / 13 万字符，会触发工具结果的
overflow 落盘，模型只能靠 `recover_result` 逐页翻读（每次上限 2 万字符），实测一次任务
为此多花约 6 轮 LLM 往返。这里把回溯上限压到 90 天，请求超过上限时在返回体里以
`requested_days` / `capped` 标注，避免被误读成「更早区间不存在」。
"""

from __future__ import annotations

import json
import time
from typing import Any, Literal

from frontier_agent.core.tool import tool
from plugins.market.factory import build_service, resolve_or_error, unavailability
from plugins.market.failure import translate
from plugins.market.ports import MarketUnavailable

#: 试验阶段的回溯硬上限。10 年日线约 2400 条 / 13 万字符，会触发工具结果的 overflow
#: 落盘，模型只能靠 ``recover_result`` 逐页翻读（每次 2 万字符），实测一次任务为此多花
#: 约 6 轮 LLM 往返。只取最近 90 天（约 60 个交易日）后体积降到千字符级。
MAX_DAYS = 90
#: 未显式指定时的回溯天数。
DEFAULT_DAYS = 90

_NOTE = "默认不复权；前复权随基准变化，跨次调用不可比（§9 坑 1）"


@tool
async def market_history(
    query: str,
    days: int = DEFAULT_DAYS,
    adjust: Literal["none", "forward", "backward"] = "none",
) -> str:
    """取历史日 K 线（OHLC + 成交量额）。

    用于区间涨跌幅、波动、回撤等**需要时间序列**的问题；只看当前价请用
    ``market_quote``。

    Args:
        query: 标的名称 / 代码 / thscode（内部会自动消歧）。
        days: 回溯天数，默认 90，**上限 90**（试验阶段筛选）。超过上限的值会被截到
            90，并在返回体里以 ``requested_days`` / ``capped`` 标注。
        adjust: 复权方式。`none`（默认，不复权）/ `forward`（前复权，
            **随基准变化、跨次调用不可比**）/ `backward`（后复权）。

    Returns:
        JSON 字符串：``{"ok": true, "thscode", "interval", "adjust", "count",
        "items": [{"date_ms", "open_price", "high_price", "low_price",
        "close_price", "volume", "turnover"}]}``。
        请求超过上限时另带 ``requested_days`` 与 ``capped: true``——不要据此认为更早的
        区间不存在。
    """
    if not isinstance(query, str) or not query.strip():
        return json.dumps(
            {"ok": False, "reason": "query 必须是非空字符串", "next": "传入股票名称或代码"},
            ensure_ascii=False,
        )
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        days = DEFAULT_DAYS
    requested_days = days
    days = min(days, MAX_DAYS)

    denied = unavailability()
    if denied is not None:
        return json.dumps(denied, ensure_ascii=False)

    service = build_service()
    if service is None:
        return json.dumps(
            {"ok": False, "reason": "market 服务不可用", "next": "检查 .env 的 THS_API_KEY"},
            ensure_ascii=False,
        )

    thscode, error = resolve_or_error(service, query)
    if error is not None:
        return json.dumps(error, ensure_ascii=False)

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 24 * 60 * 60 * 1000

    try:
        result = service.history(
            str(thscode), start_ms=start_ms, end_ms=end_ms, adjust=adjust
        )
    except MarketUnavailable as exc:
        return json.dumps(translate(exc, tool="market_history"), ensure_ascii=False)

    payload: dict[str, Any] = {
        **result,
        "query": query,
        "days": days,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "note": _NOTE,
    }
    if requested_days != days:
        payload["requested_days"] = requested_days
        payload["capped"] = True
        payload["note"] = (
            f"{_NOTE}；试验阶段回溯上限 {MAX_DAYS} 天，本次请求 {requested_days} 天"
            f"已按上限截断为 {days} 天"
        )

    return json.dumps(payload, ensure_ascii=False)
