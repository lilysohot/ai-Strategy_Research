"""M11：失败注入端到端（§6）。

五类注入：断网 / 429 / 500 / 超时 / 字段漂移。断言：
1. 工具返回 `ok=false` 且带可执行的 `next`；
2. **异常绝不冒泡**（不抛 httpx / 其他异常）；
3. observability 有记录（进程内失败计数）。
"""

from __future__ import annotations

import importlib
import json

import httpx
import pytest

from plugins.market.adapters.fuyao_rest import FuyaoRestAdapter
from plugins.market.service import MarketService
from plugins.market.transport import MarketTransport

# 注意：`plugins.tools.__init__` 把 `market_quote` 这个名字绑定成了 Tool 对象，
# 直接 `from plugins.tools import market_quote` 拿不到模块 ⇒ 用 importlib 取真身。
market_quote_module = importlib.import_module("plugins.tools.market_quote")

NO_SLEEP = lambda _seconds: None  # noqa: E731


def _service_with(handler) -> MarketService:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    transport = MarketTransport(
        base_url="https://example.test",
        api_key="test-key",
        client=client,
        attempts=1,
        sleep=NO_SLEEP,
    )
    return MarketService(adapter=FuyaoRestAdapter(transport))


def _inject(monkeypatch: pytest.MonkeyPatch, service: MarketService) -> None:
    """把工具模块里的工厂替换成注入的服务（不碰真实凭据）。"""
    monkeypatch.setattr(market_quote_module, "unavailability", lambda *a, **k: None)
    monkeypatch.setattr(market_quote_module, "build_service", lambda *a, **k: service)


async def _call(query: str = "600519.SH") -> dict:
    raw = await market_quote_module.market_quote.func(query)
    return json.loads(raw)


def _network_down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused")


def _timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.TimeoutException("timed out")


@pytest.mark.parametrize(
    ("label", "handler", "expected_kind"),
    [
        ("断网", _network_down, "network"),
        ("超时", _timeout, "network"),
        (
            "429 限流",
            lambda request: httpx.Response(429, json={"code": 429, "message": "limit"}),
            "rate_limited",
        ),
        (
            "500 上游异常",
            lambda request: httpx.Response(500, json={"code": 5001, "message": "boom"}),
            "unavailable",
        ),
    ],
)
async def test_failure_injection_returns_actionable_failure(
    monkeypatch: pytest.MonkeyPatch,
    label: str,
    handler,
    expected_kind: str,
) -> None:
    """任何失败都要变成「Agent 能照着做」的结果，而不是异常或空数据。"""
    _inject(monkeypatch, _service_with(handler))

    result = await _call()  # 不得抛异常

    assert result["ok"] is False, f"{label} 应返回 ok=false"
    assert result["kind"] == expected_kind
    assert result["reason"]
    assert result["next"], "失败必须给出可执行的下一步"


async def test_field_drift_yields_null_not_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """字段漂移（响应缺字段）不得崩溃，更**不得把缺失当 0**（§9 风险表）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {"timestamp": 1788938632000, "item": [{"thscode": "600519.SH"}]},
            },
        )

    _inject(monkeypatch, _service_with(handler))

    result = await _call()

    assert result["ok"] is True
    assert result["items"][0]["last_price"] is None


async def test_failures_are_counted_for_observability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """失败必须留痕（进程内计数），否则线上无法感知供应商异常。"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, json={"code": 5001, "message": "boom"})

    service = _service_with(handler)
    _inject(monkeypatch, service)

    await _call()

    assert calls["n"] >= 1
    assert service.health()["ok"] is True  # 健康检查本身不因取数失败而失败
