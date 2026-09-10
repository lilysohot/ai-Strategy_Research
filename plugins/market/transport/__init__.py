"""transport 层：HTTP 治理（超时 / 退避 / 并发上限 / 熔断 / 单飞去重）。

只负责「把请求发出去、把失败管住」，**不认识业务字段**（那是 adapter 的事）。
"""

from plugins.market.transport.circuit_breaker import CircuitBreaker
from plugins.market.transport.client import MarketTransport
from plugins.market.transport.retry import retry_with_backoff

__all__ = ["CircuitBreaker", "MarketTransport", "retry_with_backoff"]
