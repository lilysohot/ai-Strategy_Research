"""market_financials — 财务报表（已披露）。

**前视偏差防线**：返回体同时带 `report_date_ms`（披露日）与 `period_end_ms`（报告期末）。
做历史判断时只能用**披露日**——用报告期会「用未来数据解释过去」（§9 坑 2）。

**内联期数上限（试验阶段筛选）**：整份历史报表可达 11 万字符，会触发工具结果的
overflow 落盘，模型只能用 `recover_result` 逐页翻读（每次上限 2 万字符），实测一次任务
为此多花约 6 轮 LLM 往返。这里只内联最新一期（「1 页」口径），并在返回体里给出
`total_items` 与 `truncated`，避免被误读成「该公司只披露过一期」。
"""

from __future__ import annotations

import json
from typing import Any, Literal

from frontier_agent.core.tool import tool
from plugins.market.factory import build_service, resolve_or_error, unavailability
from plugins.market.failure import translate
from plugins.market.ports import MarketUnavailable

#: 内联返回的最大期数。1 = 只给最新一期（试验阶段用于压缩执行时间）。
INLINE_PERIOD_LIMIT = 1

_NOTE = "report_date_ms=披露日，period_end_ms=报告期末；防前视偏差请用披露日（§9 坑 2）"


def _latest_first(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按报告期末降序；缺失时退回披露日，再缺失视为 0。"""

    def sort_key(item: dict[str, Any]) -> int:
        for field in ("period_end_ms", "report_date_ms"):
            value = item.get(field)
            if isinstance(value, int):
                return value
        return 0

    return sorted(items, key=sort_key, reverse=True)


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
        `items` 只含**最新一期**；被省略时返回体带 `total_items`（实际期数）与
        `truncated: true`——不要据此认为该公司只披露过一期。
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

    payload: dict[str, Any] = {**result, "query": query, "note": _NOTE}

    items = result.get("items")
    if isinstance(items, list):
        ordered = [item for item in items if isinstance(item, dict)]
        if len(ordered) > INLINE_PERIOD_LIMIT:
            kept = INLINE_PERIOD_LIMIT
            payload["items"] = _latest_first(ordered)[:kept]
            payload["total_items"] = len(ordered)
            payload["truncated"] = True
            payload["note"] = (
                f"{_NOTE}；本次只内联最新一期，其余 {len(ordered) - kept} 期未返回"
                "（实际期数见 total_items）"
            )

    return json.dumps(payload, ensure_ascii=False)
