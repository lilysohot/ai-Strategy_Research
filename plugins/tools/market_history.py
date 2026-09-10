"""market_history — 历史日 K 线。

默认 `adjust=none`（不复权）：前复权序列会以「最新」为基准重算，**跨次调用不可比**
（§9 坑 1）。确需前复权时，返回的 `adjust` 字段会标注口径，引用时必须一并说明。
"""

from __future__ import annotations

import json
import time
from typing import Literal

from frontier_agent.core.tool import tool
from plugins.market.factory import build_service, resolve_or_error, unavailability
from plugins.market.failure import translate
from plugins.market.ports import MarketUnavailable

MAX_DAYS = 3650  # 窗口 ≤ 10 年（§2.1）


@tool
async def market_history(
    query: str,
    days: int = 365,
    adjust: Literal["none", "forward", "backward"] = "none",
) -> str:
    """取历史日 K 线（OHLC + 成交量额）。

    用于区间涨跌幅、波动、回撤等**需要时间序列**的问题；只看当前价请用
    ``market_quote``。

    Args:
        query: 标的名称 / 代码 / thscode（内部会自动消歧）。
        days: 回溯天数，默认 365（上限 3650，即 10 年）。
        adjust: 复权方式。`none`（默认，不复权）/ `forward`（前复权，
            **随基准变化、跨次调用不可比**）/ `backward`（后复权）。

    Returns:
        JSON 字符串：``{"ok": true, "thscode", "interval", "adjust", "count",
        "items": [{"date_ms", "open_price", "high_price", "low_price",
        "close_price", "volume", "turnover"}]}``。
    """
    if not isinstance(query, str) or not query.strip():
        return json.dumps(
            {"ok": False, "reason": "query 必须是非空字符串", "next": "传入股票名称或代码"},
            ensure_ascii=False,
        )
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        days = 365
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

    return json.dumps(
        {
            **result,
            "query": query,
            "days": days,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "note": "默认不复权；前复权随基准变化，跨次调用不可比（§9 坑 1）",
        },
        ensure_ascii=False,
    )
