"""market 模块的端口层：领域对象、协议与异常。

**零依赖、零 IO** —— 本模块不 import httpx、不做网络请求、不连数据库，
只定义类型与契约，便于 service / 工具 / 测试只依赖抽象（§5.0 分层：L2 端口）。

字段契约以 **§2.1.1 实测结论** 为准，不以官方文档的模糊描述为准。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Period = Literal["annual", "quarterly"]
Adjust = Literal["none", "forward", "backward"]
Interval = Literal["1d"]
Statement = Literal["income", "balance", "cashflow"]

FailureKind = Literal[
    "credentials",  # 无 key / 2001 未认证 / 2003 无权限
    "bad_request",  # 1001-1004 参数缺失 / 格式错 / 越界 / 冲突
    "not_found",  # 3001 标的不存在 / 3002 数据未就绪 / 3004 类型不支持
    "rate_limited",  # HTTP 429 / code=4001
    "unavailable",  # 5001-5003 服务或上游异常、熔断打开
    "network",  # 超时 / 连接失败 / 解析失败
]

#: 可重试的失败类型（transport 内退避重试，其余直接失败）
RETRYABLE_KINDS: frozenset[str] = frozenset({"network", "rate_limited", "unavailable"})

#: 单次批量请求上限（估值快照实测「单次最多 100 个 token」）
MAX_BATCH = 100


class MarketUnavailable(Exception):
    """市场数据不可用——**唯一的对外领域异常**。

    transport 层不得把 `httpx` / 网络异常往外传，一律转成此异常，
    由上层按 §6 转译为 Agent 可读的 `reason` + `next`。
    """

    def __init__(
        self,
        kind: FailureKind,
        message: str,
        *,
        request_id: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.request_id = request_id
        self.retryable = retryable if retryable is not None else kind in RETRYABLE_KINDS

    def __repr__(self) -> str:
        return (
            f"MarketUnavailable(kind={self.kind!r}, message={self.message!r}, "
            f"request_id={self.request_id!r})"
        )


@dataclass(frozen=True, slots=True)
class TickerMatch:
    """标的检索（消歧）结果——一切取数的前置步骤。"""

    thscode: str
    ticker: str
    name: str
    exchange: str = ""
    asset_type: str = ""
    currency: str = ""


@dataclass(frozen=True, slots=True)
class Quote:
    """行情快照。价格**实时时变**，`as_of_ms` 是唯一的时点锚。"""

    thscode: str
    as_of_ms: int
    last_price: float | None = None
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    prev_price: float | None = None
    price_change: float | None = None
    price_change_ratio_pct: float | None = None
    volume: float | None = None
    turnover: float | None = None
    #: 行情快照端点**不返回 name**（§2.1），通常由估值快照或 meta 补齐
    name: str | None = None


@dataclass(frozen=True, slots=True)
class Valuation:
    """估值快照（含 `name`，可用来补 Quote 缺失的中文名）。"""

    thscode: str
    as_of_ms: int
    pe_ttm: float | None = None
    pe_mrq: float | None = None
    pb_mrq: float | None = None
    ps_ttm: float | None = None
    pcf_ttm: float | None = None
    name: str | None = None


@dataclass(frozen=True, slots=True)
class Bar:
    """日 K 线。价格为**复权口径**，`adjust` 决定口径（默认 forward，随基准漂移）。"""

    date_ms: int
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    close_price: float | None = None
    volume: float | None = None
    turnover: float | None = None


@dataclass(frozen=True, slots=True)
class FinancialRow:
    """财务报表一行。`report_date_ms` 是**披露日**，防前视偏差的关键（§9 坑 2）。"""

    thscode: str
    period: str
    fiscal_year: int
    fiscal_period: str
    report_date_ms: int
    period_end_ms: int
    currency: str = ""
    values: dict[str, float | None] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CorporateAction:
    """复权因子事件（官方只给原始事件，复权需自行推导）。"""

    ex_date_ms: int
    dividend_per_share: float | None = None
    per_share_bonus: float | None = None
    allotment_ratio: float | None = None
    allotment_price: float | None = None


class MarketAdapter(Protocol):
    """数据适配器协议（L3）。换供应商时只换实现，工具与硬闸不动（§3.2）。"""

    def search_tickers(self, query: str, *, limit: int = 10) -> list[TickerMatch]:
        """按名称 / 代码检索标的，返回候选（消歧）。"""
        ...

    def snapshot(self, thscodes: list[str]) -> list[Quote]:
        """行情快照。参数名必须是 `thscodes`（传错会被静默忽略并返回全市场）。"""
        ...

    def valuations(self, thscodes: list[str]) -> list[Valuation]:
        """估值快照。"""
        ...

    def history(
        self,
        thscode: str,
        *,
        start_ms: int,
        end_ms: int,
        interval: Interval = "1d",
        adjust: Adjust = "none",
    ) -> list[Bar]:
        """历史 K 线，窗口 ≤ 10 年。"""
        ...

    def financials(
        self,
        thscode: str,
        *,
        period: Period,
        statement: Statement = "income",
    ) -> list[FinancialRow]:
        """财务报表。`period` 是字面量 `annual` / `quarterly`。"""
        ...

    def corporate_actions(self, thscode: str) -> list[CorporateAction]:
        """复权因子事件流。该端点响应**没有 `data.timestamp`**（§2.1.1 #4）。"""
        ...


class TraceSink(Protocol):
    """留痕接缝（L2）。默认 `NullSink`，可选 `FileSink`（run 目录）。"""

    def write(self, record: dict[str, Any]) -> None:
        """写入一条调用留痕。必须幂等、不得抛异常拖垮主流程。"""
        ...
