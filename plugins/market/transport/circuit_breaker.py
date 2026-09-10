"""熔断器（transport 层，§5.2）。

连续失败达到阈值后**快速失败**，避免在供应商故障期间把每次工具调用都拖满超时，
进而拖垮整个策略流程（§6：任何时候都不拖垮主流程）。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from plugins.market.ports import MarketUnavailable

DEFAULT_THRESHOLD = 5
DEFAULT_RESET_AFTER = 60.0


class CircuitBreaker:
    """连续失败计数 + 冷却窗口。线程安全。

    状态机：closed →（连续失败达阈值）→ open →（冷却结束）→ half-open
    → 成功则 closed，失败则重新 open。
    """

    def __init__(
        self,
        *,
        threshold: int = DEFAULT_THRESHOLD,
        reset_after: float = DEFAULT_RESET_AFTER,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = max(1, threshold)
        self._reset_after = reset_after
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._opened_at is not None and not self._cooled_down()

    @property
    def failures(self) -> int:
        with self._lock:
            return self._failures

    def _cooled_down(self) -> bool:
        assert self._opened_at is not None
        return (self._clock() - self._opened_at) >= self._reset_after

    def check(self) -> None:
        """熔断打开且未冷却 ⇒ 快速失败，不发请求。"""
        with self._lock:
            if self._opened_at is not None and not self._cooled_down():
                raise MarketUnavailable(
                    "unavailable",
                    f"熔断打开：连续 {self._failures} 次失败，{self._reset_after:.0f}s 内快速失败",
                    retryable=True,
                )

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._threshold:
                self._opened_at = self._clock()
