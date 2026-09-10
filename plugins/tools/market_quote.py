"""market_quote — 最新行情 + 估值快照。

**价格是实时时变的**：每次调用取的是当下最新快照，数据时点由 `as_of` 标注。
返回体同时给出 `as_of_ms` / `as_of`（ISO）/ `age`（"同日"/"N 天前"），
以及可直接写进 evidence 的规范 `quote_text`（硬闸①的比对对象）。
"""

from __future__ import annotations

import json

from frontier_agent.core.tool import tool
from plugins.market.factory import build_service, resolve_or_error, unavailability
from plugins.market.failure import translate
from plugins.market.ports import MarketUnavailable


@tool
async def market_quote(query: str) -> str:
    """取某只标的的**最新**行情与估值（价格实时变化，以返回的 `as_of` 为准）。

    用于「现在什么价 / 现在多少倍 PE」这类**实时**问题。历史序列请用
    ``market_history``。价格随时变化，引用数字时**必须带上 `as_of` 时点**。

    Args:
        query: 标的名称 / 代码 / thscode（内部会自动消歧）。

    Returns:
        JSON 字符串：``{"ok": true, "items": [{"thscode", "name", "last_price",
        "pe_ttm", "as_of_ms", "as_of", "age", "quote_text", ...}]}``。
        ``quote_text`` 是**规范引用串**，写进 evidence 的 ``quote`` 字段，
        不要改写其中的数字。估值失败不影响行情返回（见 ``caveats``）。
    """
    if not isinstance(query, str) or not query.strip():
        return json.dumps(
            {"ok": False, "reason": "query 必须是非空字符串", "next": "传入股票名称或代码"},
            ensure_ascii=False,
        )

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

    try:
        result = service.quote([str(thscode)])
    except MarketUnavailable as exc:
        return json.dumps(translate(exc, tool="market_quote"), ensure_ascii=False)

    return json.dumps({**result, "query": query, "thscode": thscode}, ensure_ascii=False)
