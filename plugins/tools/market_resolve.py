"""market_resolve — 标的消歧。**一切取数的前置步骤**。

同花顺的数据端点**不接受纯代码**（`600519` 不行，必须 `600519.SH`），
所以任何取数前都要先过这一关（§2.1）。实测 `meta/search` 对名称子串与纯代码
都能命中；但像 `000001` 会同时命中场外基金与 A 股 ⇒ 多义时必须把候选交给模型选，
工具绝不替它"猜一个"。
"""

from __future__ import annotations

import json

from frontier_agent.core.tool import tool
from plugins.market.factory import build_service, unavailability
from plugins.market.failure import translate
from plugins.market.ports import MarketUnavailable

MAX_LIMIT = 20


@tool
async def market_resolve(query: str, limit: int = 10) -> str:
    """把名称 / 代码解析成唯一的 `thscode`（同花顺唯一标的代码）。

    **取数前必先调用本工具**：同花顺数据端点不接受纯代码（``600519`` 不行，
    必须是 ``600519.SH``）。「茅台」「600519」「600519.SH」会得到同一结果。

    Args:
        query: 标的关键字。支持中文名称（``茅台``）、纯代码（``600519``）
            或完整代码（``600519.SH``）。
        limit: 候选返回上限，默认 10。

    Returns:
        JSON 字符串：``{"ok": true, "thscode", "name"}``；
        多义时 ``{"ok": true, "ambiguous": true, "candidates": [...]}``——
        此时**必须**挑一个 thscode 再取数，不要自行猜测；
        找不到时 ``ok=false`` 并给出 ``next``。
    """
    if not isinstance(query, str) or not query.strip():
        return json.dumps(
            {"ok": False, "reason": "query 必须是非空字符串", "next": "传入股票名称或代码"},
            ensure_ascii=False,
        )
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        limit = 10
    limit = min(limit, MAX_LIMIT)

    denied = unavailability()
    if denied is not None:
        return json.dumps(denied, ensure_ascii=False)

    service = build_service()
    if service is None:
        return json.dumps(
            {"ok": False, "reason": "market 服务不可用", "next": "检查 .env 的 THS_API_KEY"},
            ensure_ascii=False,
        )

    try:
        resolved = service.resolve(query)
    except MarketUnavailable as exc:
        return json.dumps(translate(exc, tool="market_resolve"), ensure_ascii=False)

    payload = resolved.to_dict()
    for key in ("candidates", "other_candidates"):
        if key in payload:
            payload[key] = payload[key][:limit]
    return json.dumps(payload, ensure_ascii=False)
