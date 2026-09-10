"""内存 adapter（测试 / 离线兜底用，不发网络、不连数据库）。

用于 M3 / M5 的单元测试：注入 `MarketService(adapter=MockAdapter())` 即可
**不发网络请求、不连数据库**（§8 M3 验收）。
"""

from __future__ import annotations

from plugins.market.adapters.base import now_ms
from plugins.market.ports import (
    Adjust,
    Bar,
    CorporateAction,
    FinancialRow,
    Interval,
    Period,
    Quote,
    Statement,
    TickerMatch,
    Valuation,
)

#: 固定样本（**不可用于演示 / 文档引用真实行情数字**，§7 纪律）
SAMPLE_TICKERS = [
    TickerMatch(
        thscode="600519.SH",
        ticker="600519",
        name="贵州茅台",
        exchange="SH",
        asset_type="a-share",
        currency="CNY",
    ),
    TickerMatch(
        thscode="000001.SZ",
        ticker="000001",
        name="平安银行",
        exchange="SZ",
        asset_type="a-share",
        currency="CNY",
    ),
]

SAMPLE_AS_OF_MS = 1788938632000
SAMPLE_QUOTES = {
    "600519.SH": Quote(
        thscode="600519.SH",
        as_of_ms=SAMPLE_AS_OF_MS,
        last_price=1290.88,
        open_price=1305.01,
        high_price=1309.3,
        low_price=1286.68,
        prev_price=1309.3,
        price_change=-18.42,
        price_change_ratio_pct=-1.406859,
        volume=3222611.0,
        turnover=4168500500.0,
        name="贵州茅台",
    ),
}

SAMPLE_VALUATIONS = {
    "600519.SH": Valuation(
        thscode="600519.SH",
        as_of_ms=SAMPLE_AS_OF_MS,
        pe_ttm=19.816116,
        pe_mrq=18.124645,
        pb_mrq=6.422616,
        ps_ttm=9.314936,
        pcf_ttm=13.549858,
        name="贵州茅台",
    ),
}

SAMPLE_BARS = [
    Bar(
        date_ms=1735747200000,
        open_price=1444.34577,
        high_price=1444.83577,
        low_price=1400.34577,
        close_price=1408.34577,
        volume=5002870.0,
        turnover=7490883773.19,
    ),
]

SAMPLE_FINANCIALS = [
    FinancialRow(
        thscode="600519.SH",
        period="annual",
        fiscal_year=2025,
        fiscal_period="FY",
        report_date_ms=1776355200000,
        period_end_ms=1767110400000,
        currency="CNY",
        values={"operating_income": 168838102514.79},
    ),
]

SAMPLE_ACTIONS = [
    CorporateAction(ex_date_ms=1782403200000, dividend_per_share=28.02423, per_share_bonus=0.0),
]


class MockAdapter:
    """固定样本 adapter：按 thscode 返回内置数据，未命中则返回空列表。"""

    def search_tickers(self, query: str, *, limit: int = 10) -> list[TickerMatch]:
        matched = [
            ticker
            for ticker in SAMPLE_TICKERS
            if query in (ticker.name, ticker.ticker, ticker.thscode) or query in ticker.name
        ]
        return (matched or SAMPLE_TICKERS)[:limit]

    def snapshot(self, thscodes: list[str]) -> list[Quote]:
        return [SAMPLE_QUOTES[code] for code in thscodes if code in SAMPLE_QUOTES]

    def valuations(self, thscodes: list[str]) -> list[Valuation]:
        return [SAMPLE_VALUATIONS[code] for code in thscodes if code in SAMPLE_VALUATIONS]

    def history(
        self,
        thscode: str,
        *,
        start_ms: int,
        end_ms: int,
        interval: Interval = "1d",
        adjust: Adjust = "none",
    ) -> list[Bar]:
        _ = (thscode, start_ms, end_ms, interval, adjust)
        return list(SAMPLE_BARS)

    def financials(
        self,
        thscode: str,
        *,
        period: Period,
        statement: Statement = "income",
    ) -> list[FinancialRow]:
        _ = (thscode, statement)
        return [row for row in SAMPLE_FINANCIALS if row.period == period]

    def corporate_actions(self, thscode: str) -> list[CorporateAction]:
        _ = thscode
        return list(SAMPLE_ACTIONS)

    @property
    def as_of_ms(self) -> int:
        return now_ms()
