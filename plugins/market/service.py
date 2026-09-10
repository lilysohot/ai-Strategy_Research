"""MarketService（L1 服务层，§5.0）：本模块的**唯一收口**。

- **消歧**（M1）：名称 / 纯代码 / 完整 `thscode` → 同一结果；多义时列候选让模型选；
  进程内短 TTL 缓存，**不落库**；
- **取数**（M3）：行情 + 估值合并（估值补中文名与 PE），渲染规范 `quote_text`；
- 依赖注入：`MarketService(adapter=..., sink=...)`，测试可用 `MockAdapter` 完全
  **不发网络请求、不连数据库**（§8 M3 验收）。
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from plugins.market.ports import (
    Adjust,
    Bar,
    CorporateAction,
    FinancialRow,
    Interval,
    MarketAdapter,
    MarketUnavailable,
    Period,
    Quote,
    Statement,
    TickerMatch,
    TraceSink,
    Valuation,
)
from plugins.market.render import format_as_of, render_quote_text
from plugins.market.sink import NullSink

#: 完整 thscode：`600519.SH`。数据端点**不接受纯代码**，所以消歧不可省（§2.1）
THSCODE_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ|OF|HK)$")

DEFAULT_CACHE_TTL = 300.0
DEFAULT_PREFER_ASSET_TYPE = "a-share"


@dataclass
class ResolveResult:
    """消歧结果：唯一 / 多义 / 未找到。"""

    query: str
    ok: bool
    thscode: str | None = None
    name: str | None = None
    matches: list[TickerMatch] = field(default_factory=list)
    ambiguous: bool = False
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "query": self.query,
            "thscode": self.thscode,
            "name": self.name,
            "ambiguous": self.ambiguous,
        }
        if self.reason:
            payload["reason"] = self.reason
        if self.ambiguous:
            payload["candidates"] = [self._candidate(match) for match in self.matches]
        elif len(self.matches) > 1:
            # 已按资产类型优先选中一个，但**必须让模型看见被丢弃的候选**
            # （实测 `000001` 同时命中场外基金与 A 股，静默丢弃会拿错标的）
            payload["other_candidates"] = [
                self._candidate(match) for match in self.matches if match.thscode != self.thscode
            ]
        return payload

    @staticmethod
    def _candidate(match: TickerMatch) -> dict[str, Any]:
        return {
            "thscode": match.thscode,
            "ticker": match.ticker,
            "name": match.name,
            "asset_type": match.asset_type,
        }


class MarketService:
    """行情取数服务（无存储，取回即用）。"""

    def __init__(
        self,
        *,
        adapter: MarketAdapter,
        sink: TraceSink | None = None,
        cache_ttl: float = DEFAULT_CACHE_TTL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._adapter = adapter
        self._sink = sink if sink is not None else NullSink()
        self._cache_ttl = cache_ttl
        self._clock = clock
        self._cache: dict[str, tuple[float, ResolveResult]] = {}

    # ------------------------------------------------------------------ 消歧
    def resolve(
        self, query: str, *, prefer_asset_type: str = DEFAULT_PREFER_ASSET_TYPE
    ) -> ResolveResult:
        """名称 / 代码 / thscode → 唯一 `thscode`（M1）。

        验收要点：「茅台」「600519」「600519.SH」得到**同一结果**。
        """
        raw = (query or "").strip()
        if not raw:
            return ResolveResult(query=query or "", ok=False, reason="查询为空")

        # 1) 已是完整 thscode ⇒ 直接短路（省一次搜索，也避免 search 的限流风险）
        if THSCODE_RE.match(raw.upper()):
            return ResolveResult(query=raw, ok=True, thscode=raw.upper())

        # 2) 进程内短 TTL 缓存（不落库）
        cached = self._cache_get(raw)
        if cached is not None:
            return cached

        # 3) 检索（实测：名称子串与**纯代码**都能命中，§2.1.1）
        matches = self._adapter.search_tickers(raw)
        if not matches:
            result = ResolveResult(
                query=raw,
                ok=False,
                reason=f"未找到匹配「{raw}」的标的，可换用更完整的名称或代码",
            )
        else:
            preferred = [m for m in matches if m.asset_type == prefer_asset_type]
            unique = preferred[0] if len(preferred) == 1 else (matches[0] if len(matches) == 1 else None)
            if unique is not None:
                result = ResolveResult(
                    query=raw, ok=True, thscode=unique.thscode, name=unique.name, matches=matches
                )
            else:
                candidates = preferred or matches
                result = ResolveResult(
                    query=raw,
                    ok=True,
                    ambiguous=True,
                    matches=candidates,
                    reason=f"「{raw}」有 {len(candidates)} 个候选，请指定其中一个 thscode",
                )

        self._cache_put(raw, result)
        return result

    def _cache_get(self, key: str) -> ResolveResult | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._clock() >= expires_at:
            self._cache.pop(key, None)
            return None
        return value

    def _cache_put(self, key: str, value: ResolveResult) -> None:
        self._cache[key] = (self._clock() + self._cache_ttl, value)

    # ------------------------------------------------------------------ 取数
    def quote(self, thscodes: list[str], *, with_valuation: bool = True) -> dict[str, Any]:
        """行情快照 + 估值（估值失败**不影响**行情，§6.5 隔离）。"""
        codes = [code for code in thscodes if code]
        if not codes:
            return {"ok": False, "items": [], "caveats": ["未提供 thscode"]}

        quotes = self._adapter.snapshot(codes)
        valuations: dict[str, Valuation] = {}
        caveats: list[str] = []

        if with_valuation:
            try:
                valuations = {item.thscode: item for item in self._adapter.valuations(codes)}
            except MarketUnavailable as exc:
                caveats.append(f"估值取数失败（不影响行情）：{exc.message}")

        items = [self._render_quote(quote, valuations.get(quote.thscode)) for quote in quotes]
        self._trace_quote(codes, items)
        return {"ok": bool(items), "items": items, "caveats": caveats}

    def _trace_quote(self, thscodes: list[str], items: list[dict[str, Any]]) -> None:
        """写一条**聚合留痕**：把本次 quote 的最终 `quote_text` 落痕（§5.3）。

        transport 留的是各端点原始响应；硬闸①比对的是「模型引用的 `quote_text`」，
        而它跨了行情与估值两次调用 ⇒ 这里聚合出一份**可直接逐字比对**的文本，
        并保留 `request_ids` 以便回溯到原始响应留痕。
        """
        if not items:
            return
        self._sink.write(
            {
                "type": "market_quote",
                "thscodes": list(thscodes),
                "as_of_ms": items[0].get("as_of_ms"),
                "received_at_ms": int(time.time() * 1000),
                "quote_texts": [str(item.get("quote_text", "")) for item in items],
            }
        )

    def _render_quote(self, quote: Quote, valuation: Valuation | None) -> dict[str, Any]:
        as_of_ms = quote.as_of_ms
        pe_ttm = valuation.pe_ttm if valuation else None
        name = quote.name or (valuation.name if valuation else None)
        item: dict[str, Any] = {
            "thscode": quote.thscode,
            "name": name,
            "last_price": quote.last_price,
            "open_price": quote.open_price,
            "high_price": quote.high_price,
            "low_price": quote.low_price,
            "prev_price": quote.prev_price,
            "price_change": quote.price_change,
            "price_change_ratio_pct": quote.price_change_ratio_pct,
            "volume": quote.volume,
            "turnover": quote.turnover,
            **format_as_of(as_of_ms),
        }
        if valuation is not None:
            item.update(
                {
                    "pe_ttm": valuation.pe_ttm,
                    "pe_mrq": valuation.pe_mrq,
                    "pb_mrq": valuation.pb_mrq,
                    "ps_ttm": valuation.ps_ttm,
                    "pcf_ttm": valuation.pcf_ttm,
                }
            )
        item["quote_text"] = render_quote_text(quote.last_price, pe_ttm=pe_ttm, as_of_ms=as_of_ms)
        if name is None:
            item.setdefault("caveats", []).append("行情快照不返回 name，name 来自估值快照")
        return item

    def history(
        self,
        thscode: str,
        *,
        start_ms: int,
        end_ms: int,
        interval: Interval = "1d",
        adjust: Adjust = "none",
    ) -> dict[str, Any]:
        """历史 K 线。默认 `adjust=none`（前复权随基准漂移，§9 坑 1）。"""
        bars: list[Bar] = self._adapter.history(
            thscode, start_ms=start_ms, end_ms=end_ms, interval=interval, adjust=adjust
        )
        return {
            "ok": bool(bars),
            "thscode": thscode,
            "interval": interval,
            "adjust": adjust,
            "count": len(bars),
            "items": [
                {
                    "date_ms": bar.date_ms,
                    "open_price": bar.open_price,
                    "high_price": bar.high_price,
                    "low_price": bar.low_price,
                    "close_price": bar.close_price,
                    "volume": bar.volume,
                    "turnover": bar.turnover,
                }
                for bar in bars
            ],
        }

    def financials(
        self, thscode: str, *, period: Period, statement: Statement = "income"
    ) -> dict[str, Any]:
        """财务报表。`report_date_ms` 是**披露日**（防前视偏差，§9 坑 2）。"""
        rows: list[FinancialRow] = self._adapter.financials(
            thscode, period=period, statement=statement
        )
        return {
            "ok": bool(rows),
            "thscode": thscode,
            "period": period,
            "statement": statement,
            "items": [
                {
                    "fiscal_year": row.fiscal_year,
                    "fiscal_period": row.fiscal_period,
                    "report_date_ms": row.report_date_ms,
                    "period_end_ms": row.period_end_ms,
                    "currency": row.currency,
                    "values": row.values,
                }
                for row in rows
            ],
        }

    def corporate_actions(self, thscode: str) -> dict[str, Any]:
        """复权因子事件流（官方只给原始事件，复权需自行推导）。"""
        actions: list[CorporateAction] = self._adapter.corporate_actions(thscode)
        return {
            "ok": bool(actions),
            "thscode": thscode,
            "count": len(actions),
            "items": [
                {
                    "ex_date_ms": action.ex_date_ms,
                    "dividend_per_share": action.dividend_per_share,
                    "per_share_bonus": action.per_share_bonus,
                    "allotment_ratio": action.allotment_ratio,
                    "allotment_price": action.allotment_price,
                }
                for action in actions
            ],
        }

    def health(self) -> dict[str, Any]:
        """健康检查（**不发起网络请求**）。"""
        return {
            "ok": True,
            "adapter": type(self._adapter).__name__,
            "trace_enabled": not isinstance(self._sink, NullSink),
        }
