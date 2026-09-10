"""HTTP 客户端治理（§5.2：不是优化，是正确性）。

职责边界：**只管发请求与失败治理，不认识业务字段**（业务语义归 adapter）。
对外保证两条硬约束：

1. **绝不把 `httpx` 异常往外传** —— 一律转成 `MarketUnavailable`（领域异常）；
2. 失败要**可分类、可记账** —— 进程内计数 + `request_id` 随错误上抛，便于对账。

治理项：超时、退避重试（≤3）、并发上限、熔断、**单飞去重**、错误码映射。
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from plugins.market.ports import MarketUnavailable, TraceSink
from plugins.market.transport.circuit_breaker import CircuitBreaker
from plugins.market.transport.retry import retry_with_backoff

DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_CONCURRENCY = 4
DEFAULT_ATTEMPTS = 3

_Key = tuple[str, tuple[tuple[str, str], ...]]


@dataclass
class _Pending:
    """单飞去重：同一请求的并发等待者共享一次真实请求。"""

    event: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] | None = None
    error: BaseException | None = None


def map_response_code(code: int, message: str, request_id: str | None) -> MarketUnavailable:
    """按 §2.2 把供应商 `code` 映射为领域异常。"""
    if code in (2001, 2003):
        return MarketUnavailable(
            "credentials",
            f"{message}（检查 THS_API_KEY 与该 capability 权限）",
            request_id=request_id,
        )
    if code in (1001, 1002, 1003, 1004):
        return MarketUnavailable("bad_request", message, request_id=request_id)
    if code in (3001, 3002, 3004):
        return MarketUnavailable("not_found", message, request_id=request_id)
    if code in (4001, 429):
        return MarketUnavailable("rate_limited", message, request_id=request_id)
    if 5001 <= code <= 5003:
        return MarketUnavailable("unavailable", message, request_id=request_id)
    return MarketUnavailable("unavailable", f"未知响应 code={code}: {message}", request_id=request_id)


class MarketTransport:
    """带治理的 HTTP GET 客户端（同步）。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: float = DEFAULT_TIMEOUT,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        attempts: int = DEFAULT_ATTEMPTS,
        breaker: CircuitBreaker | None = None,
        client: httpx.Client | None = None,
        sink: TraceSink | None = None,
        sleep: Any = time.sleep,
        rng: Any = random.random,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._attempts = attempts
        self._breaker = breaker or CircuitBreaker()
        self._client = client if client is not None else httpx.Client(timeout=timeout)
        self._owns_client = client is None
        self._sink = sink
        self._semaphore = threading.Semaphore(max(1, max_concurrency))
        self._sleep = sleep
        self._rng = rng
        self._lock = threading.Lock()
        self._inflight: dict[_Key, _Pending] = {}
        self._counters: dict[str, int] = {"calls": 0, "success": 0, "failure": 0, "deduped": 0}

    @property
    def counters(self) -> dict[str, int]:
        """进程内 observability 计数（§6.6，无表）。"""
        with self._lock:
            return dict(self._counters)

    @property
    def breaker(self) -> CircuitBreaker:
        return self._breaker

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> MarketTransport:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---------------------------------------------------------------- 单飞去重
    def _begin(self, key: _Key) -> tuple[_Pending, bool]:
        with self._lock:
            pending = self._inflight.get(key)
            if pending is not None:
                self._counters["deduped"] += 1
                return pending, False
            pending = _Pending()
            self._inflight[key] = pending
            return pending, True

    def _finish(self, key: _Key, pending: _Pending, result: dict[str, Any] | None, error: BaseException | None) -> None:
        with self._lock:
            pending.result = result
            pending.error = error
            self._inflight.pop(key, None)
        pending.event.set()

    def _await(self, pending: _Pending) -> dict[str, Any]:
        pending.event.wait()
        if pending.error is not None:
            if isinstance(pending.error, MarketUnavailable):
                raise MarketUnavailable(
                    pending.error.kind,
                    pending.error.message,
                    request_id=pending.error.request_id,
                )
            raise pending.error
        assert pending.result is not None
        return pending.result

    # ------------------------------------------------------------------ 发请求
    def get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        """GET 一个端点，返回已解析的响应 dict（未判断业务 `code`）。"""
        params = dict(params or {})
        key: _Key = (path, tuple(sorted(params.items())))
        pending, is_owner = self._begin(key)
        if not is_owner:
            return self._await(pending)
        try:
            payload = self._request(path, params)
        except BaseException as exc:
            self._finish(key, pending, None, exc)
            raise
        self._finish(key, pending, payload, None)
        return payload

    def _request(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        self._breaker.check()

        def once() -> dict[str, Any]:
            with self._lock:
                self._counters["calls"] += 1
            try:
                with self._semaphore:
                    response = self._client.get(
                        f"{self._base_url}{path}",
                        params=params,
                        headers={"X-api-key": self._api_key, "Accept": "application/json"},
                    )
            except Exception as exc:
                self._record_failure("network")
                raise MarketUnavailable("network", f"网络请求失败：{type(exc).__name__}") from exc

            if response.status_code == 429:
                self._record_failure("rate_limited")
                raise MarketUnavailable("rate_limited", "触发限流（HTTP 429）")
            if response.status_code >= 500:
                self._record_failure("unavailable")
                raise MarketUnavailable("unavailable", f"服务异常 HTTP {response.status_code}")
            if response.status_code >= 400:
                self._record_failure("bad_request")
                raise MarketUnavailable("bad_request", f"请求被拒 HTTP {response.status_code}")

            try:
                payload = response.json()
            except ValueError as exc:
                self._record_failure("network")
                raise MarketUnavailable("network", "响应不是合法 JSON") from exc
            if not isinstance(payload, dict):
                self._record_failure("network")
                raise MarketUnavailable("network", "响应不是 JSON 对象")

            code = payload.get("code")
            if code not in (None, 0):
                error = map_response_code(
                    int(code),
                    str(payload.get("message") or "无错误信息"),
                    payload.get("request_id"),
                )
                self._record_failure(error.kind)
                raise error

            with self._lock:
                self._counters["success"] += 1
            self._breaker.record_success()
            self._trace(path, params, payload)
            return payload

        return retry_with_backoff(
            once,
            attempts=self._attempts,
            sleep=self._sleep,
            rng=self._rng,
        )

    def _trace(self, path: str, params: dict[str, str], payload: dict[str, Any]) -> None:
        """留痕：记下本次**真实响应**（§5.3），供硬闸①证伪来源与时点。

        注意留的是原始响应而不是解析后的对象——证伪要的是"供应商当时到底返回了什么"。
        """
        if self._sink is None:
            return
        data = payload.get("data")
        self._sink.write(
            {
                "path": path,
                "params": dict(params),
                "request_id": payload.get("request_id"),
                "as_of_ms": data.get("timestamp") if isinstance(data, dict) else None,
                "received_at_ms": int(time.time() * 1000),
                "code": payload.get("code"),
                "raw": payload,
            }
        )

    def _record_failure(self, kind: str) -> None:
        with self._lock:
            self._counters["failure"] += 1
        self._breaker.record_failure()
        _ = kind  # 计数细化留给 observability（§6.6）
