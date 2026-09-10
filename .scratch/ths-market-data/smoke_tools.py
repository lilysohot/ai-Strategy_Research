"""M5 smoke：用真实凭据端到端跑一遍四个 Agent 工具。

用法：
    set -a && . ./.env && set +a && uv run python .scratch/ths-market-data/smoke_tools.py

只打印工具返回体（**不打印 API Key**）。调用之间留间隔以避开动态 QPS 限流。
"""

from __future__ import annotations

import asyncio
import json

from plugins.tools.market_financials import market_financials
from plugins.tools.market_history import market_history
from plugins.tools.market_quote import market_quote
from plugins.tools.market_resolve import market_resolve


def show(label: str, raw: str, limit: int = 420) -> None:
    print(f"=== {label}")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print(raw[:limit])
        return
    print(json.dumps(payload, ensure_ascii=False, indent=2)[:limit])
    print()


async def main() -> None:
    show("market_resolve('茅台')", await market_resolve.func("茅台"))
    await asyncio.sleep(1.2)

    show("market_resolve('600519')  纯代码", await market_resolve.func("600519"))
    await asyncio.sleep(1.2)

    show("market_quote('茅台')  ← 实时价格", await market_quote.func("茅台"))
    await asyncio.sleep(1.2)

    show("market_history('600519.SH', days=5)", await market_history.func("600519.SH", days=5))
    await asyncio.sleep(1.2)

    show(
        "market_financials('600519.SH', period='annual')",
        await market_financials.func("600519.SH", period="annual"),
    )


if __name__ == "__main__":
    asyncio.run(main())
