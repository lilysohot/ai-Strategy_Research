"""M2a 验收：transport HTTP 治理（不需要 API Key，用 httpx.MockTransport）。

覆盖 §5.2 与 M2a 验收项：超时 / 429 / 500 三类均有正确行为、
**无 `httpx` 异常外泄**、并发上限 + 单飞去重、熔断快速失败、参数错误不重试。
"""

from __future__ import annotations

import threading
import time

import httpx
import pytest

from plugins.market.ports import MarketUnavailable
from plugins.market.transport import CircuitBreaker, MarketTransport
from plugins.market.transport.client import map_response_code

NO_SLEEP = lambda _seconds: None  # noqa: E731 - 注入以跳过真实等待


def make_transport(handler, *, attempts: int = 3, **kwargs) -> MarketTransport:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return MarketTransport(
        base_url="https://example.test",
        api_key="test-key",
        client=client,
        attempts=attempts,
        sleep=NO_SLEEP,
        **kwargs,
    )


def test_success_returns_payload_and_counts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "message": "success", "data": {"item": []}})

    with make_transport(handler) as transport:
        payload = transport.get("/api/a-share/prices/snapshot", {"thscodes": "600519.SH"})

    assert payload["code"] == 0
    assert transport.counters["success"] == 1


@pytest.mark.parametrize(
    ("status", "body", "expected_kind"),
    [
        (429, {"code": 429, "message": "request limit exceeded"}, "rate_limited"),
        (500, {"code": 5001, "message": "upstream error"}, "unavailable"),
        (503, {"code": 5002, "message": "service unavailable"}, "unavailable"),
    ],
)
def test_retryable_failures_map_to_domain_errors(
    status: int, body: dict, expected_kind: str
) -> None:
    """429 / 5xx 必须转成领域异常，且**绝不是 httpx 异常**。"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(status, json=body)

    with (
        make_transport(handler, attempts=2) as transport,
        pytest.raises(MarketUnavailable) as excinfo,
    ):
        transport.get("/api/x")

    error = excinfo.value
    assert error.kind == expected_kind
    assert not isinstance(error, httpx.HTTPError)
    assert error.retryable is True
    assert calls["n"] == 2  # 可重试失败：按 attempts 重试


def test_timeout_maps_to_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    with (
        make_transport(handler, attempts=2) as transport,
        pytest.raises(MarketUnavailable) as excinfo,
    ):
        transport.get("/api/x")

    assert excinfo.value.kind == "network"
    assert not isinstance(excinfo.value, httpx.HTTPError)


def test_bad_request_is_not_retried() -> None:
    """参数错误重试多少次都一样 ⇒ 只发一次（§6：不拖慢主流程）。"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200, json={"code": 1001, "message": "Missing required parameter: thscodes"}
        )

    with (
        make_transport(handler, attempts=3) as transport,
        pytest.raises(MarketUnavailable) as excinfo,
    ):
        transport.get("/api/x")

    assert excinfo.value.kind == "bad_request"
    assert calls["n"] == 1


def test_singleflight_dedupes_concurrent_identical_requests() -> None:
    """并发相同请求只发一次真实请求（单飞去重）。"""
    lock = threading.Lock()
    calls = {"n": 0}
    barrier = threading.Barrier(5)

    def handler(request: httpx.Request) -> httpx.Response:
        with lock:
            calls["n"] += 1
        time.sleep(0.05)
        return httpx.Response(200, json={"code": 0, "data": {"item": []}})

    results: list[dict] = []
    results_lock = threading.Lock()

    def worker() -> None:
        barrier.wait()
        payload = transport.get("/api/x", {"thscodes": "600519.SH"})
        with results_lock:
            results.append(payload)

    with make_transport(handler) as transport:
        threads = [threading.Thread(target=worker) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert len(results) == 5
    assert calls["n"] == 1, "并发相同请求应只发一次真实请求"
    assert transport.counters["deduped"] == 4


def test_circuit_breaker_opens_and_fails_fast() -> None:
    """连续失败达阈值后熔断：后续请求不再发往网络。"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, json={"code": 5001, "message": "boom"})

    breaker = CircuitBreaker(threshold=2, reset_after=60.0)
    with make_transport(handler, attempts=1, breaker=breaker) as transport:
        for _ in range(2):
            with pytest.raises(MarketUnavailable):
                transport.get("/api/x")

        assert breaker.is_open is True

        with pytest.raises(MarketUnavailable) as excinfo:
            transport.get("/api/x")

    assert "熔断" in excinfo.value.message
    assert calls["n"] == 2, "熔断打开后不应再发请求"


def test_circuit_breaker_recovers_after_cooldown() -> None:
    clock = {"t": 0.0}
    breaker = CircuitBreaker(threshold=1, reset_after=10.0, clock=lambda: clock["t"])
    breaker.record_failure()
    assert breaker.is_open is True

    clock["t"] = 11.0
    assert breaker.is_open is False
    breaker.check()  # 冷却后可以再次尝试（不应抛）
    breaker.record_success()
    assert breaker.failures == 0


@pytest.mark.parametrize(
    ("code", "expected_kind"),
    [
        (2001, "credentials"),
        (2003, "credentials"),
        (1002, "bad_request"),
        (3001, "not_found"),
        (4001, "rate_limited"),
        (5001, "unavailable"),
        (9999, "unavailable"),
    ],
)
def test_map_response_code_covers_all_families(code: int, expected_kind: str) -> None:
    error = map_response_code(code, "msg", request_id="rid-1")
    assert error.kind == expected_kind
    assert error.request_id == "rid-1"


def test_non_json_response_is_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    with (
        make_transport(handler, attempts=1) as transport,
        pytest.raises(MarketUnavailable) as excinfo,
    ):
        transport.get("/api/x")

    assert excinfo.value.kind == "network"
