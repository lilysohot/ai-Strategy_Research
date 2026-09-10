"""market_financials — 财务报表（已披露）。

**前视偏差防线**：返回体同时带 `report_date_ms`（披露日）与 `period_end_ms`（报告期末）。
做历史判断时只能用**披露日**——用报告期会「用未来数据解释过去」（§9 坑 2）。
"""

from __future__ import annotations

import json
from typing import Literal

from frontier_agent.core.tool import tool
from plugins.market.factory import build_service, resolve_or_error, unavailability
from plugins.market.failure import translate
from plugins.market.ports import MarketUnavailable


@tool
async def market_financials(
    query: str,
    period: Literal["annual", "quarterly"] = "annual",
    statement: Literal["income", "balance", "cashflow"] = "income",
) -> str:
    """取已披露的财务报表（利润表 / 资产负债表 / 现金流量表）。

    Args:
        query: 标的名称 / 代码 / thscode（内部会自动消歧）。
        period: 报告频率字面量。`annual`（年报）/ `quarterly`（季报）。
        statement: 报表类型。`income`（利润表）/ `balance`（资产负债表）/
            `cashflow`（现金流量表）。

    Returns:
        JSON 字符串：``{"ok": true, "items": [{"fiscal_year", "fiscal_period",
        "report_date_ms", "period_end_ms", "currency", "values": {...}}]}``。
        `report_date_ms` 是**披露日**，`period_end_ms` 是报告期末；
        判断「当时是否已知道」一律用披露日。
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
        result = service.financials(str(thscode), period=period, statement=statement)
    except MarketUnavailable as exc:
        return json.dumps(translate(exc, tool="market_financials"), ensure_ascii=False)

    return json.dumps(
        {
            **result,
            "query": query,
            "note": "report_date_ms=披露日，period_end_ms=报告期末；防前视偏差请用披露日（§9 坑 2）",
        },
        ensure_ascii=False,
    )
