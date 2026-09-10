"""M7 验收：市场类黄金题——留痕开启时，市场数字溯源命中率 **100%**。

与 corpus 黄金题（检索 Recall@5）不同，这里验的是**溯源闭环**：
Agent 引用的每个市场数字，都必须能在 run 目录留痕里逐字命中。

三类黄金场景（对齐 M7 定义「现价 / 区间 / 复权口径 / 财报对齐」）：
1. **现价**：`market_quote` 的规范 `quote_text`；
2. **历史区间**：`market_history` 返回体里的单字段键值（如 `close_price=...`）；
3. **财报**：`market_financials` 的科目值（如 `operating_income=...`）。

关键：走**真实的 transport 留痕路径**（httpx.MockTransport 模拟供应商，
但留痕写入、渲染、比对全部是生产代码），不是 mock 掉比对本身。
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from plugins.corpus.verify import _gate_market_traceability, check_market_consistency
from plugins.market.adapters.fuyao_rest import FuyaoRestAdapter
from plugins.market.service import MarketService
from plugins.market.sink import FileSink
from plugins.market.trace_store import resolve_market_source
from plugins.market.transport import MarketTransport

NO_SLEEP = lambda _seconds: None  # noqa: E731

SNAPSHOT_PAYLOAD = {
    "code": 0,
    "request_id": "rid-snap",
    "data": {
        "timestamp": 1788938632000,
        "item": [
            {
                "thscode": "600519.SH",
                "ticker": "600519",
                "last_price": 1290.88,
                "open_price": 1305.01,
                "high_price": 1309.3,
                "low_price": 1286.68,
                "prev_price": 1309.3,
                "price_change": -18.42,
                "price_change_ratio_pct": -1.406859,
                "volume": 3222611,
                "turnover": 4168500500,
            }
        ],
    },
}

VALUATION_PAYLOAD = {
    "code": 0,
    "request_id": "rid-val",
    "data": {
        "timestamp": 1788938632000,
        "item": [
            {
                "thscode": "600519.SH",
                "ticker": "600519",
                "name": "贵州茅台",
                "pe_ttm": 19.816116,
                "pb_mrq": 6.422616,
            }
        ],
    },
}

HISTORICAL_PAYLOAD = {
    "code": 0,
    "request_id": "rid-hist",
    "data": {
        "timestamp": 1788938632000,
        "thscode": "600519.SH",
        "interval": "1d",
        "adjust": "none",
        "item": [
            {
                "date_ms": 1735747200000,
                "open_price": 1444.34577,
                "high_price": 1444.83577,
                "low_price": 1400.34577,
                "close_price": 1408.34577,
                "volume": 5002870.0,
                "turnover": 7490883773.19,
            }
        ],
    },
}

FINANCIALS_PAYLOAD = {
    "code": 0,
    "request_id": "rid-fin",
    "data": {
        "timestamp": 1788938632000,
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
}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("prices/snapshot"):
        return httpx.Response(200, json=SNAPSHOT_PAYLOAD)
    if path.endswith("valuations/snapshot"):
        return httpx.Response(200, json=VALUATION_PAYLOAD)
    if path.endswith("prices/historical"):
        return httpx.Response(200, json=HISTORICAL_PAYLOAD)
    if path.endswith("income-statements"):
        return httpx.Response(200, json=FINANCIALS_PAYLOAD)
    return httpx.Response(200, json={"code": 3001, "message": f"unexpected path {path}"})


@pytest.fixture(scope="module")
def traced(tmp_path_factory):
    """走真实链路取数并留痕：quote / history / financials 各一次。"""
    directory = tmp_path_factory.mktemp("m7_trace")
    client = httpx.Client(transport=httpx.MockTransport(_handler))
    transport = MarketTransport(
        base_url="https://example.test",
        api_key="test-key",
        client=client,
        sleep=NO_SLEEP,
        sink=FileSink(directory),
    )
    # sink 必须同时给 service（聚合 quote_text 留痕）与 transport（raw 响应留痕）：
    # 少给任何一个，对应的引用就无法溯源——这正是本测试要验的东西。
    service = MarketService(adapter=FuyaoRestAdapter(transport), sink=FileSink(directory))

    quote_result = service.quote(["600519.SH"])
    history_result = service.history(
        "600519.SH", start_ms=1735660800000, end_ms=1767196800000
    )
    financials_result = service.financials("600519.SH", period="annual")
    return directory, quote_result, history_result, financials_result


def _resolver(directory: Path):
    def _resolve(ref: str) -> str | None:
        return resolve_market_source(ref, directory)

    return _resolve


def _evidence(ref: str, quote: str, *, page: str = "2026-09-09T15:00:00+08:00") -> dict:
    return {"source_ref": ref, "page": page, "quote": quote, "kind": "fact"}


def test_quote_golden_hits_trace(traced) -> None:
    """黄金题①：现价——规范 quote_text 必须逐字命中留痕。"""
    directory, quote_result, _, _ = traced
    quote_text = quote_result["items"][0]["quote_text"]

    status, problems, total, traced_count = _gate_market_traceability(
        {"position": {"evidence": [_evidence("ths:600519.SH:rid-snap", quote_text)]}},
        _resolver(directory),
    )

    assert status == "passed", problems
    assert total == 1 and traced_count == 1
    assert "last_price=1290.88" in quote_text


def test_history_golden_hits_trace(traced) -> None:
    """黄金题②：历史区间——返回体里的字段值必须能在留痕渲染中命中。"""
    directory, _, history_result, _ = traced
    bar = history_result["items"][0]
    close = bar["close_price"]

    status, problems, _, traced_count = _gate_market_traceability(
        {"position": {"evidence": [_evidence("ths:600519.SH:rid-hist", f"close_price={close}")]}},
        _resolver(directory),
    )

    assert status == "passed", problems
    assert traced_count == 1
    # 复权口径留痕可查（adjust=none 记录在原始响应里）
    rendered = resolve_market_source("ths:600519.SH:rid-hist", directory) or ""
    assert "adjust=none" in rendered


def test_financials_golden_hits_trace(traced) -> None:
    """黄金题③：财报——科目值必须命中，且披露日在留痕里可查。"""
    directory, _, _, financials_result = traced
    income = financials_result["items"][0]["values"]["operating_income"]

    status, problems, _, traced_count = _gate_market_traceability(
        {
            "position": {
                "evidence": [
                    _evidence("ths:600519.SH:rid-fin", f"operating_income={income}")
                ]
            }
        },
        _resolver(directory),
    )

    assert status == "passed", problems
    assert traced_count == 1


def test_fabricated_number_is_caught(traced) -> None:
    """反向黄金题：改写一个数字 ⇒ 必须被拦（这是命中率 100% 的另一面）。"""
    directory, quote_result, _, _ = traced
    bad = quote_result["items"][0]["quote_text"].replace("1290.88", "8888.88")

    status, problems, _, traced_count = _gate_market_traceability(
        {"position": {"evidence": [_evidence("ths:600519.SH:rid-snap", bad)]}},
        _resolver(directory),
    )

    assert status == "failed"
    assert any(p["code"] == "quote_not_found" for p in problems)
    assert traced_count == 0


def test_market_hit_rate_is_100_percent(traced) -> None:
    """**M7 核心验收**：三类黄金题合一，市场数字溯源命中率 == 100%。"""
    directory, quote_result, history_result, financials_result = traced
    quote_text = quote_result["items"][0]["quote_text"]
    close = history_result["items"][0]["close_price"]
    income = financials_result["items"][0]["values"]["operating_income"]

    card = {
        "position": {
            "evidence": [
                _evidence("ths:600519.SH:rid-snap", quote_text),
                _evidence("ths:600519.SH:rid-hist", f"close_price={close}"),
                _evidence("ths:600519.SH:rid-fin", f"operating_income={income}"),
            ]
        }
    }

    status, problems, total, traced_count = _gate_market_traceability(card, _resolver(directory))

    assert total == 3
    assert traced_count == 3, f"命中率不足：{traced_count}/{total}，问题：{problems}"
    assert status == "passed"
    assert traced_count / total == 1.0

    # 一致性：无 ERROR / 无 WARN（as_of 新鲜、口径一致）
    errors, warnings = check_market_consistency(card)
    assert errors == [], errors
    assert warnings == [], warnings


def test_fabricated_breaks_the_100_percent(traced) -> None:
    """命中率指标必须**对编造敏感**：混入一条编造 ⇒ 命中率立刻 < 100% 且 failed。"""
    directory, quote_result, _, _ = traced
    real = quote_result["items"][0]["quote_text"]
    card = {
        "position": {
            "evidence": [
                _evidence("ths:600519.SH:rid-snap", real),
                _evidence("ths:600519.SH:rid-snap", real.replace("1290.88", "7777.77")),
            ]
        }
    }

    status, _problems, total, traced_count = _gate_market_traceability(card, _resolver(directory))

    assert total == 2 and traced_count == 1
    assert traced_count / total < 1.0
    assert status == "failed"
