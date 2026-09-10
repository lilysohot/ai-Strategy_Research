"""M2c 验收：adapter 契约测试（固定响应样本，**不需要 API Key**）。

验证 §2.1.1 实测契约被正确固化在代码里：
参数名（`thscodes` vs `thscode`）、`period` 字面量、毫秒时间窗口、
响应信封差异、以及**「返回条数 > 请求条数 ⇒ 判定返回全市场」**的硬防御。
"""

from __future__ import annotations

import httpx
import pytest

from plugins.market.adapters.fuyao_rest import FuyaoRestAdapter, chunked
from plugins.market.ports import MarketUnavailable
from plugins.market.transport import MarketTransport

NO_SLEEP = lambda _seconds: None  # noqa: E731

SNAPSHOT_ROW = {
    "thscode": "600519.SH",
    "ticker": "600519",
    "volume": 3222611,
    "turnover": 4168500500,
    "last_price": 1290.88,
    "price_change": -18.42,
    "price_change_ratio_pct": -1.406859,
    "open_price": 1305.01,
    "high_price": 1309.3,
    "low_price": 1286.68,
    "prev_price": 1309.3,
}


def make_adapter(handler) -> FuyaoRestAdapter:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    transport = MarketTransport(
        base_url="https://example.test", api_key="test-key", client=client, sleep=NO_SLEEP
    )
    return FuyaoRestAdapter(transport)


def test_search_tickers_maps_all_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "timestamp": 1788937212509,
                    "item": [
                        {
                            "thscode": "600519.SH",
                            "ticker": "600519",
                            "name": "贵州茅台",
                            "exchange": "SH",
                            "asset_type": "a-share",
                            "currency": "CNY",
                        }
                    ],
                },
            },
        )

    matches = make_adapter(handler).search_tickers("茅台")

    assert len(matches) == 1
    assert matches[0].thscode == "600519.SH"
    assert matches[0].name == "贵州茅台"
    assert matches[0].asset_type == "a-share"


def test_snapshot_uses_plural_thscodes_and_maps_quote() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["query"] = str(request.url.query)
        return httpx.Response(
            200, json={"code": 0, "data": {"timestamp": 1788938632000, "item": [SNAPSHOT_ROW]}}
        )

    quotes = make_adapter(handler).snapshot(["600519.SH"])

    assert "thscodes=600519.SH" in seen["query"], "批量端点必须用复数 thscodes"
    assert len(quotes) == 1
    assert quotes[0].last_price == 1290.88
    assert quotes[0].as_of_ms == 1788938632000


def test_batch_guard_rejects_market_wide_response() -> None:
    """传错参数名会静默返回全市场 —— 必须被挡住而不是当成结果返回（§2.1.1 #1）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "timestamp": 1,
                    "item": [
                        {"thscode": "000001.SZ", "last_price": 11.7},
                        {"thscode": "000002.SZ", "last_price": 10.1},
                        {"thscode": "600519.SH", "last_price": 1290.88},
                    ],
                },
            },
        )

    with pytest.raises(MarketUnavailable) as excinfo:
        make_adapter(handler).snapshot(["600519.SH"])

    assert "全市场" in excinfo.value.message
    assert excinfo.value.retryable is False


def test_history_uses_singular_thscode_and_ms_window() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["query"] = str(request.url.query)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "timestamp": 1,
                    "item": [
                        {
                            "date_ms": 1735747200000,
                            "open_price": 1444.34577,
                            "close_price": 1408.34577,
                            "volume": 5002870.0,
                        }
                    ],
                },
            },
        )

    bars = make_adapter(handler).history(
        "600519.SH", start_ms=1735660800000, end_ms=1767196800000
    )

    query = seen["query"]
    assert "thscode=600519.SH" in query, "单标的端点必须用单数 thscode"
    assert "start=1735660800000" in query
    assert "end=1767196800000" in query
    assert "interval=1d" in query
    assert len(bars) == 1
    assert bars[0].close_price == 1408.34577


def test_financials_uses_period_literal_and_collects_extra_values() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["query"] = str(request.url.query)
        seen["path"] = request.url.path
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "timestamp": 1,
                    "item": [
                        {
                            "thscode": "600519.SH",
                            "period": "annual",
                            "fiscal_year": 2025,
                            "fiscal_period": "FY",
                            "report_date_ms": 1776355200000,
                            "period_end_ms": 1767110400000,
                            "currency": "CNY",
                            "operating_income": 168838102514.79,
                        }
                    ],
                },
            },
        )

    rows = make_adapter(handler).financials("600519.SH", period="annual")

    assert "period=annual" in seen["query"]
    assert "income-statements" in seen["path"]
    assert rows[0].report_date_ms == 1776355200000
    assert rows[0].values["operating_income"] == 168838102514.79
    assert "fiscal_year" not in rows[0].values, "已单独成列的字段不应重复进 values"


def test_corporate_actions_parses_envelope_without_timestamp() -> None:
    """该端点 `data` 没有 `timestamp`（§2.1.1 #4）——不能统一假设。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "thscode": "600519.SH",
                    "ticker": "600519",
                    "item": [
                        {
                            "ex_date_ms": 1782403200000,
                            "dividend_per_share": 28.02423,
                            "per_share_bonus": 0,
                        }
                    ],
                },
            },
        )

    actions = make_adapter(handler).corporate_actions("600519.SH")

    assert len(actions) == 1
    assert actions[0].ex_date_ms == 1782403200000
    assert actions[0].dividend_per_share == 28.02423


def test_null_is_not_coerced_to_zero() -> None:
    """`null` 表示未披露，**禁止当成 0**（§9 风险表）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "timestamp": 1,
                    "item": [{"thscode": "600519.SH", "pe_ttm": None, "pb_mrq": 6.42}],
                },
            },
        )

    valuations = make_adapter(handler).valuations(["600519.SH"])

    assert valuations[0].pe_ttm is None
    assert valuations[0].pb_mrq == 6.42


def test_batch_is_chunked_over_limit() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        codes = request.url.params.get("thscodes", "").split(",")
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "timestamp": 1,
                    "item": [{"thscode": code, "last_price": 1.0} for code in codes],
                },
            },
        )

    codes = [f"{600000 + index}.SH" for index in range(150)]
    quotes = make_adapter(handler).snapshot(codes)

    assert calls["n"] == 2, "超过 100 应分片请求"
    assert len(quotes) == 150


def test_chunked_partitions_codes() -> None:
    assert chunked(list(range(5)), size=2) == [[0, 1], [2, 3], [4]]
