"""M3b 验收：留痕接缝 + resolver（§5.3 / §5.5）。

硬闸①对行情的语义：证明「模型引用的数字出自标注 `as_of` 时点的真实调用」，
而不是「值等于冻结快照」（价格实时时变）。比对仍是 `quote in text`：
- 留痕开启 ⇒ `quote_text` 命中留痕文本（方案 A 通过）；
- 留痕关闭 ⇒ resolver 返回 `None`（降级方案 B，闸标 `partial`）；
- **模型改写数字 ⇒ 必然不命中**（这才是硬闸真正要挡的）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.market.ports import Adjust, Interval, Period, Quote, Statement, Valuation
from plugins.market.service import MarketService
from plugins.market.sink import FileSink, NullSink
from plugins.market.trace_store import (
    TraceStore,
    parse_source_ref,
    render_raw_record,
    resolve_market_source,
)


class _FakeAdapter:
    """最小 adapter：只服务 quote 流程。"""

    def __init__(self, quotes: list[Quote], valuations: list[Valuation]) -> None:
        self._quotes = quotes
        self._valuations = valuations

    def search_tickers(self, query: str, *, limit: int = 10) -> list:
        return []

    def snapshot(self, thscodes: list[str]) -> list[Quote]:
        return self._quotes

    def valuations(self, thscodes: list[str]) -> list[Valuation]:
        return self._valuations

    def history(
        self,
        thscode: str,
        *,
        start_ms: int,
        end_ms: int,
        interval: Interval = "1d",
        adjust: Adjust = "none",
    ) -> list:
        return []

    def financials(self, thscode: str, *, period: Period, statement: Statement = "income") -> list:
        return []

    def corporate_actions(self, thscode: str) -> list:
        return []


@pytest.fixture()
def quote_service(tmp_path: Path) -> tuple[MarketService, Path]:
    quote = Quote(thscode="600519.SH", as_of_ms=1788938632000, last_price=1290.88)
    valuation = Valuation(
        thscode="600519.SH", as_of_ms=1788938632000, pe_ttm=19.816116, name="贵州茅台"
    )
    service = MarketService(
        adapter=_FakeAdapter([quote], [valuation]), sink=FileSink(tmp_path)
    )
    return service, tmp_path


def test_quote_text_is_found_in_trace(quote_service: tuple[MarketService, Path]) -> None:
    """留痕开启 ⇒ 模型引用的 `quote_text` 能在留痕里逐字命中（方案 A）。"""
    service, directory = quote_service

    result = service.quote(["600519.SH"])
    quote_text = result["items"][0]["quote_text"]
    rendered = TraceStore(directory).render("600519.SH")

    assert quote_text in rendered


def test_tampered_number_does_not_match(quote_service: tuple[MarketService, Path]) -> None:
    """模型改写数字（"约 1291 元" / 换个数）⇒ **必然不命中**，这才叫硬闸。"""
    service, directory = quote_service

    service.quote(["600519.SH"])
    rendered = TraceStore(directory).render("600519.SH")

    assert "last_price=1290.88" in rendered
    assert "last_price=9999.99" not in rendered
    assert "as_of=1788938632000" in rendered


def test_trace_disabled_degrades_to_none(tmp_path: Path) -> None:
    """留痕关闭 ⇒ resolver 返回 `None`（硬闸①降级方案 B，闸标 `partial`）。"""
    quote = Quote(thscode="600519.SH", as_of_ms=1788938632000, last_price=1290.88)
    service = MarketService(adapter=_FakeAdapter([quote], []), sink=NullSink())

    service.quote(["600519.SH"])

    assert resolve_market_source("ths:600519.SH:rid", tmp_path) is None


def test_resolve_market_source_returns_rendered_text(
    quote_service: tuple[MarketService, Path],
) -> None:
    service, directory = quote_service
    service.quote(["600519.SH"])

    text = resolve_market_source("ths:600519.SH:rid-1", directory)

    assert text is not None
    assert "last_price=1290.88" in text


def test_resolve_market_source_ignores_non_market_ref(tmp_path: Path) -> None:
    assert resolve_market_source("corpus:doc-1", tmp_path) is None


def test_parse_source_ref() -> None:
    assert parse_source_ref("ths:600519.SH:abc123") == ("600519.SH", "abc123")
    assert parse_source_ref("ths:600519.SH") == ("600519.SH", None)
    assert parse_source_ref("corpus:other") == (None, None)


def test_render_raw_record_includes_sorted_fields_and_as_of() -> None:
    record = {
        "path": "/api/a-share/prices/snapshot",
        "raw": {
            "code": 0,
            "data": {
                "timestamp": 1788938632000,
                "item": [{"thscode": "600519.SH", "last_price": 1290.88}],
            },
        },
    }

    rendered = render_raw_record(record)

    assert "last_price=1290.88" in rendered
    assert "thscode=600519.SH" in rendered
    assert "as_of=1788938632000" in rendered


def test_missing_trace_file_is_tolerated(tmp_path: Path) -> None:
    """留痕文件缺失/损坏不得抛异常（留痕不可靠不影响取数主流程）。"""
    store = TraceStore(tmp_path)
    assert store.exists() is False
    assert store.records() == []
    assert store.render("600519.SH") == ""
