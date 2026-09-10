"""退避重试（transport 层，§5.2）。

只对 **可重试** 失败重试（网络 / 限流 / 上游异常），参数错误与凭据错误直接失败——
这类错误重试多少次都是同样结果，只会拖慢主流程。
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable

from plugins.market.ports import MarketUnavailable

DEFAULT_ATTEMPTS = 3
DEFAULT_BASE_DELAY = 0.5
DEFAULT_MAX_DELAY = 8.0


def is_retryable(exc: MarketUnavailable) -> bool:
    """是否值得重试：可重试类型且未被显式标记为不可重试。"""
    return exc.retryable and exc.kind != "bad_request"


def compute_delay(
    attempt: int,
    *,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    jitter: float | None = None,
) -> float:
    """指数退避 + 抖动（避免同一时刻重试形成尖峰）。"""
    delay = min(max_delay, base_delay * (2**attempt))
    if jitter:
        delay *= jitter
    return delay


def retry_with_backoff[T](
    fn: Callable[[], T],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    sleep: Callable[[float], None] = time.sleep,
    rng: Callable[[], float] = random.random,
    jitter: bool = True,
) -> T:
    """执行 `fn`，可重试失败时退避重试，重试耗尽后抛出最后一次异常。

    `sleep` / `rng` 可注入，测试无需真实等待。
    """
    last: MarketUnavailable | None = None
    for attempt in range(max(1, attempts)):
        try:
            return fn()
        except MarketUnavailable as exc:
            last = exc
            if attempt == max(1, attempts) - 1 or not is_retryable(exc):
                raise
            factor = (0.5 + rng() * 0.5) if jitter else None
            sleep(compute_delay(attempt, base_delay=base_delay, max_delay=max_delay, jitter=factor))
    assert last is not None  # 循环内必然赋值或已 return / raise
    raise last
