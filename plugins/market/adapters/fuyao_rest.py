"""同花顺 fuyao REST adapter（L3，默认实现）。

**唯一依据 = §2.1.1 实测契约**，不以官方文档的模糊描述为准：

- 批量端点用 `thscodes`（逗号分隔，≤100），单标的端点用 `thscode`；
- `financials` 的 `period` 是字面量 `annual` / `quarterly`；
- `historical` 需要 `start` / `end`（毫秒）+ `interval`；
- `corporate-actions` 的 `data` **没有 `timestamp`**；
- 批量响应条数 > 请求条数 ⇒ 判定为参数名错误返回全市场，直接失败。
"""

from __future__ import annotations

from plugins.market.adapters.base import as_of_ms, extract_items, guard_batch, now_ms, num, text
from plugins.market.ports import (
    MAX_BATCH,
    Adjust,
    Bar,
    CorporateAction,
    FinancialRow,
    Interval,
    MarketUnavailable,
    Period,
    Quote,
    Statement,
    TickerMatch,
    Valuation,
)
from plugins.market.transport import MarketTransport

PATH_SEARCH = "/api/meta/tickers/search"
PATH_SNAPSHOT = "/api/a-share/prices/snapshot"
PATH_VALUATIONS = "/api/a-share/valuations/snapshot"
PATH_HISTORICAL = "/api/a-share/prices/historical"
PATH_ACTIONS = "/api/a-share/corporate-actions/adjustment-factors"

PATH_STATEMENTS: dict[Statement, str] = {
    "income": "/api/a-share/financials/income-statements",
    "balance": "/api/a-share/financials/balance-sheets",
    "cashflow": "/api/a-share/financials/cash-flow-statements",
}

#: 财报中已单独成列的字段，其余数值字段进 `values`
_FINANCIAL_META_KEYS = frozenset(
    {
        "thscode",
        "ticker",
        "period",
        "fiscal_year",
        "fiscal_period",
        "report_date_ms",
        "period_end_ms",
        "currency",
    }
)


def chunked(codes: list[str], size: int = MAX_BATCH) -> list[list[str]]:
    """批量分片：单次最多 `MAX_BATCH` 个（估值快照实测上限 100）。"""
    return [codes[index : index + size] for index in range(0, len(codes), size)] or [[]]


class FuyaoRestAdapter:
    """把 fuyao 端点响应解析成领域对象。"""

    def __init__(self, transport: MarketTransport) -> None:
        self._transport = transport

    # ------------------------------------------------------------------ 消歧
    def search_tickers(self, query: str, *, limit: int = 10) -> list[TickerMatch]:
        payload = self._transport.get(PATH_SEARCH, {"q": query})
        rows = extract_items(payload)
        matches = [
            TickerMatch(
                thscode=text(row.get("thscode")),
                ticker=text(row.get("ticker")),
                name=text(row.get("name")),
                exchange=text(row.get("exchange")),
                asset_type=text(row.get("asset_type")),
                currency=text(row.get("currency")),
            )
            for row in rows
            if row.get("thscode")
        ]
        return matches[:limit]

    # -------------------------------------------------------------- 行情快照
    def snapshot(self, thscodes: list[str]) -> list[Quote]:
        codes = [code for code in thscodes if code]
        if not codes:
            return []
        quotes: list[Quote] = []
        for batch in chunked(codes):
            payload = self._transport.get(PATH_SNAPSHOT, {"thscodes": ",".join(batch)})
            rows = extract_items(payload)
            guard_batch(len(rows), len(batch), endpoint="prices/snapshot")
            timestamp = as_of_ms(payload) or now_ms()
            quotes.extend(
                Quote(
                    thscode=text(row.get("thscode")),
                    as_of_ms=timestamp,
                    last_price=num(row.get("last_price")),
                    open_price=num(row.get("open_price")),
                    high_price=num(row.get("high_price")),
                    low_price=num(row.get("low_price")),
                    prev_price=num(row.get("prev_price")),
                    price_change=num(row.get("price_change")),
                    price_change_ratio_pct=num(row.get("price_change_ratio_pct")),
                    volume=num(row.get("volume")),
                    turnover=num(row.get("turnover")),
                )
                for row in rows
            )
        return quotes

    # -------------------------------------------------------------- 估值快照
    def valuations(self, thscodes: list[str]) -> list[Valuation]:
        codes = [code for code in thscodes if code]
        if not codes:
            return []
        valuations: list[Valuation] = []
        for batch in chunked(codes):
            payload = self._transport.get(PATH_VALUATIONS, {"thscodes": ",".join(batch)})
            rows = extract_items(payload)
            guard_batch(len(rows), len(batch), endpoint="valuations/snapshot")
            timestamp = as_of_ms(payload) or now_ms()
            valuations.extend(
                Valuation(
                    thscode=text(row.get("thscode")),
                    as_of_ms=timestamp,
                    pe_ttm=num(row.get("pe_ttm")),
                    pe_mrq=num(row.get("pe_mrq")),
                    pb_mrq=num(row.get("pb_mrq")),
                    ps_ttm=num(row.get("ps_ttm")),
                    pcf_ttm=num(row.get("pcf_ttm")),
                    name=text(row.get("name")) or None,
                )
                for row in rows
            )
        return valuations

    # -------------------------------------------------------------- 历史 K 线
    def history(
        self,
        thscode: str,
        *,
        start_ms: int,
        end_ms: int,
        interval: Interval = "1d",
        adjust: Adjust = "none",
    ) -> list[Bar]:
        payload = self._transport.get(
            PATH_HISTORICAL,
            {
                "thscode": thscode,
                "interval": interval,
                "start": str(start_ms),
                "end": str(end_ms),
                "adjust": adjust,
            },
        )
        rows = extract_items(payload)
        return [
            Bar(
                date_ms=int(num(row.get("date_ms")) or 0),
                open_price=num(row.get("open_price")),
                high_price=num(row.get("high_price")),
                low_price=num(row.get("low_price")),
                close_price=num(row.get("close_price")),
                volume=num(row.get("volume")),
                turnover=num(row.get("turnover")),
            )
            for row in rows
            if row.get("date_ms") is not None
        ]

    # ---------------------------------------------------------------- 财报
    def financials(
        self,
        thscode: str,
        *,
        period: Period,
        statement: Statement = "income",
    ) -> list[FinancialRow]:
        path = PATH_STATEMENTS.get(statement)
        if path is None:
            raise MarketUnavailable("bad_request", f"不支持的报表类型：{statement}")
        payload = self._transport.get(path, {"thscode": thscode, "period": period})
        rows = extract_items(payload)
        return [
            FinancialRow(
                thscode=text(row.get("thscode")) or thscode,
                period=text(row.get("period")) or period,
                fiscal_year=int(num(row.get("fiscal_year")) or 0),
                fiscal_period=text(row.get("fiscal_period")),
                report_date_ms=int(num(row.get("report_date_ms")) or 0),
                period_end_ms=int(num(row.get("period_end_ms")) or 0),
                currency=text(row.get("currency")),
                values={key: num(value) for key, value in row.items() if key not in _FINANCIAL_META_KEYS},
            )
            for row in rows
        ]

    # ------------------------------------------------------------ 复权因子
    def corporate_actions(self, thscode: str) -> list[CorporateAction]:
        payload = self._transport.get(PATH_ACTIONS, {"thscode": thscode})
        rows = extract_items(payload)  # 该端点 data 无 timestamp（§2.1.1 #4）
        actions = [
            CorporateAction(
                ex_date_ms=int(num(row.get("ex_date_ms")) or 0),
                dividend_per_share=num(row.get("dividend_per_share")),
                per_share_bonus=num(row.get("per_share_bonus")),
                allotment_ratio=num(row.get("allotment_ratio")),
                allotment_price=num(row.get("allotment_price")),
            )
            for row in rows
            if row.get("ex_date_ms") is not None
        ]
        return actions
