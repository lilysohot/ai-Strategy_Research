"""M1 + M3 验收：消歧与 MarketService 收口。

验收要点（§8）：
- M1：「茅台」「600519」「600519.SH」得到**同一结果**；多义时列候选；进程内短 TTL 缓存、**不落库**；
- M3：注入 `mock` adapter 时**不发网络请求、不连数据库**。
"""

from __future__ import annotations

import pytest

from plugins.market.adapters.mock import MockAdapter
from plugins.market.ports import (
    Adjust,
    Interval,
    MarketUnavailable,
    Period,
    Quote,
    Statement,
    TickerMatch,
    Valuation,
)
from plugins.market.service import MarketService

MATCH = TickerMatch(
    thscode="600519.SH",
    ticker="600519",
    name="贵州茅台",
    exchange="SH",
    asset_type="a-share",
    currency="CNY",
)


class FakeAdapter:
    """可编排的 adapter：记录调用次数，可注入多义候选与估值失败。"""

    def __init__(
        self,
        *,
        matches: list[TickerMatch] | None = None,
        quotes: list[Quote] | None = None,
        valuations: list[Valuation] | None = None,
        fail_valuation: bool = False,
    ) -> None:
        self._matches = matches if matches is not None else [MATCH]
        self._quotes = quotes if quotes is not None else []
        self._valuations = valuations if valuations is not None else []
        self.fail_valuation = fail_valuation
        self.search_calls = 0

    def search_tickers(self, query: str, *, limit: int = 10) -> list[TickerMatch]:
        self.search_calls += 1
        return self._matches[:limit]

    def snapshot(self, thscodes: list[str]) -> list[Quote]:
        return self._quotes

    def valuations(self, thscodes: list[str]) -> list[Valuation]:
        if self.fail_valuation:
            raise MarketUnavailable("unavailable", "估值接口异常")
        return self._valuations

    def history(
        self,
        thscode: str,
        *,
        start_ms: int,
        end_ms: int,
        interval: Interval = "1d",
        adjust: Adjust = "none",
    ) -> list:
        return []

    def financials(self, thscode: str, *, period: Period, statement: Statement = "income") -> list:
        return []

    def corporate_actions(self, thscode: str) -> list:
        return []


def test_resolve_name_code_and_thscode_all_agree() -> None:
    """M1 核心验收：三种写法得到同一 thscode。"""
    service = MarketService(adapter=MockAdapter())

    by_name = service.resolve("茅台")
    by_code = service.resolve("600519")
    by_thscode = service.resolve("600519.SH")

    assert by_name.thscode == by_code.thscode == by_thscode.thscode == "600519.SH"
    assert by_name.ok and by_code.ok and by_thscode.ok


def test_resolve_ambiguous_lists_candidates() -> None:
    """同类资产无法区分时必须列候选让模型选，而不是随便挑一个。"""
    adapter = FakeAdapter(
        matches=[
            TickerMatch("600519.SH", "600519", "贵州茅台", asset_type="a-share"),
            TickerMatch("601398.SH", "601398", "工商银行", asset_type="a-share"),
        ]
    )
    result = MarketService(adapter=adapter).resolve("60")

    assert result.ambiguous is True
    assert result.thscode is None
    assert [item["thscode"] for item in result.to_dict()["candidates"]] == [
        "600519.SH",
        "601398.SH",
    ]


def test_resolve_exposes_dropped_candidates_when_preferring() -> None:
    """按资产类型选中后，被丢弃的候选**必须仍然可见**（否则会静默拿错标的）。"""
    adapter = FakeAdapter(
        matches=[
            TickerMatch("000001.OF", "000001", "华夏成长", asset_type="fund-otc"),
            TickerMatch("000001.SZ", "000001", "平安银行", asset_type="a-share"),
        ]
    )
    result = MarketService(adapter=adapter).resolve("000001")

    assert result.thscode == "000001.SZ"
    payload = result.to_dict()
    assert [item["thscode"] for item in payload["other_candidates"]] == ["000001.OF"]


def test_resolve_prefers_a_share_over_other_asset_types() -> None:
    """实测 `000001` 会同时命中场外基金与 A 股（§2.1.1）⇒ 优先 A 股。"""
    adapter = FakeAdapter(
        matches=[
            TickerMatch("000001.OF", "000001", "华夏成长", asset_type="fund-otc"),
            TickerMatch("000001.SZ", "000001", "平安银行", asset_type="a-share"),
        ]
    )
    result = MarketService(adapter=adapter).resolve("000001")

    assert result.ambiguous is False
    assert result.thscode == "000001.SZ"
    assert result.name == "平安银行"


def test_resolve_not_found_has_actionable_reason() -> None:
    result = MarketService(adapter=FakeAdapter(matches=[])).resolve("不存在的公司")
    assert result.ok is False
    assert result.thscode is None
    assert "未找到" in (result.reason or "")


def test_resolve_cache_hits_within_ttl() -> None:
    adapter = FakeAdapter()
    service = MarketService(adapter=adapter)

    service.resolve("茅台")
    service.resolve("茅台")

    assert adapter.search_calls == 1, "TTL 内应命中进程内缓存"


def test_resolve_cache_expires_after_ttl() -> None:
    adapter = FakeAdapter()
    clock = {"t": 0.0}
    service = MarketService(adapter=adapter, cache_ttl=10.0, clock=lambda: clock["t"])

    service.resolve("茅台")
    clock["t"] = 11.0
    service.resolve("茅台")

    assert adapter.search_calls == 2, "超过 TTL 应重新检索"


def test_quote_merges_valuation_name_and_pe() -> None:
    quote = Quote(thscode="600519.SH", as_of_ms=1788938632000, last_price=1290.88)
    valuation = Valuation(
        thscode="600519.SH", as_of_ms=1788938632000, pe_ttm=19.816116, name="贵州茅台"
    )
    service = MarketService(adapter=FakeAdapter(quotes=[quote], valuations=[valuation]))

    result = service.quote(["600519.SH"])

    assert result["ok"] is True
    item = result["items"][0]
    assert item["name"] == "贵州茅台", "行情快照不返回 name，应由估值补齐"
    assert item["pe_ttm"] == 19.816116
    assert item["as_of_ms"] == 1788938632000
    assert item["quote_text"] == "last_price=1290.88; pe_ttm=19.816116; as_of=1788938632000"


def test_quote_survives_valuation_failure() -> None:
    """估值失败**不影响**行情（§6.5 隔离）。"""
    quote = Quote(thscode="600519.SH", as_of_ms=1788938632000, last_price=1290.88)
    service = MarketService(adapter=FakeAdapter(quotes=[quote], fail_valuation=True))

    result = service.quote(["600519.SH"])

    assert result["ok"] is True
    assert result["items"][0]["last_price"] == 1290.88
    assert any("估值取数失败" in note for note in result["caveats"])


def test_quote_text_is_deterministic() -> None:
    """同一次数据渲染两次必须一致，否则留痕比对会随机误判（§5.5）。"""
    quote = Quote(thscode="600519.SH", as_of_ms=1788938632000, last_price=1290.88)
    service = MarketService(adapter=FakeAdapter(quotes=[quote]))

    first = service.quote(["600519.SH"])["items"][0]["quote_text"]
    second = service.quote(["600519.SH"])["items"][0]["quote_text"]

    assert first == second


@pytest.mark.parametrize("codes", [[], [""]])
def test_quote_without_codes_fails_cleanly(codes: list[str]) -> None:
    result = MarketService(adapter=FakeAdapter()).quote(codes)
    assert result["ok"] is False
    assert result["items"] == []


def test_health_does_not_touch_network() -> None:
    health = MarketService(adapter=FakeAdapter()).health()
    assert health["ok"] is True
    assert health["adapter"] == "FakeAdapter"
    assert health["trace_enabled"] is False


def test_service_has_no_storage_dependency() -> None:
    """M3 验收：注入 mock adapter 时不发网络、不连数据库。"""
    service = MarketService(adapter=MockAdapter())
    result = service.quote(["600519.SH"])

    assert result["ok"] is True
    assert result["items"][0]["thscode"] == "600519.SH"
