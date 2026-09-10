"""M6 验收：硬闸①扩展——市场数字可溯源（留痕比对）+ 一致性检查。

这是"市场数字能合法写进策略卡"的最后一块：此前 `verify` 只认语料库来源，
`ths:` 引用一律报「无法解析到原文」——**真的市场数字也进不了卡**。

验收要点：
1. 真实留痕 + 规范 quote_text ⇒ **通过**；
2. 编造的数字 ⇒ `quote_not_found`（精确指认编造，而不是笼统的"无法解析"）；
3. 没给 `--market-trace` ⇒ 该闸 `skipped`（验不了 = 没验过，strict 下不通过）；
4. 一致性 WARN 不阻断；口径混用 ERROR；
5. **纯语料卡的行为不变**（回归红线）。
"""

from __future__ import annotations

from plugins.corpus.verify import (
    GATE_MARKET,
    _gate_market_traceability,
    check_market_consistency,
    verify_card,
)
from plugins.market.ports import Adjust, Interval, Period, Quote, Statement, Valuation
from plugins.market.service import MarketService
from plugins.market.sink import FileSink
from plugins.market.trace_store import resolve_market_source


class _FakeAdapter:
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


AS_OF_MS = 1788938632000


def _make_traced_card(tmp_path, *, quote_text: str | None = None):
    """通过真实 service.quote 产出留痕 + 规范 quote_text，返回 (card, resolver)。"""
    quote = Quote(thscode="600519.SH", as_of_ms=AS_OF_MS, last_price=1290.88)
    valuation = Valuation(
        thscode="600519.SH", as_of_ms=AS_OF_MS, pe_ttm=19.816116, name="贵州茅台"
    )
    service = MarketService(adapter=_FakeAdapter([quote], [valuation]), sink=FileSink(tmp_path))
    result = service.quote(["600519.SH"])
    real_quote_text = result["items"][0]["quote_text"]

    card = {
        "position": {
            "evidence": [
                {
                    "source_ref": "ths:600519.SH:rid-1",
                    "page": "2026-09-09T15:00:00+08:00",
                    "quote": quote_text or real_quote_text,
                    "kind": "fact",
                }
            ]
        }
    }

    def resolver(ref: str) -> str | None:
        return resolve_market_source(ref, tmp_path)

    return card, resolver, real_quote_text


def test_real_trace_passes(tmp_path) -> None:
    """真实留痕 + 规范 quote_text ⇒ 通过（此前这会被判「无法解析」）。"""
    card, resolver, _ = _make_traced_card(tmp_path)

    status, problems, total, traced = _gate_market_traceability(card, resolver)

    assert status == "passed"
    assert problems == []
    assert total == 1 and traced == 1


def test_fabricated_quote_is_caught(tmp_path) -> None:
    """模型改写数字 ⇒ 精确指认编造（quote_not_found），而不是笼统报错。"""
    card, resolver, real = _make_traced_card(tmp_path)
    fabricated = real.replace("1290.88", "9999.99")
    card["position"]["evidence"][0]["quote"] = fabricated

    status, problems, _, traced = _gate_market_traceability(card, resolver)

    assert status == "failed"
    assert any(p["code"] == "quote_not_found" for p in problems)
    assert traced == 0


def test_missing_trace_degrades_to_skipped(tmp_path) -> None:
    """没给 --market-trace ⇒ 该闸 skipped（strict 下整卡不通过），不是误判通过。"""
    card, _resolver, _ = _make_traced_card(tmp_path)

    report = verify_card(card, market_resolver=None, strict=True)

    assert GATE_MARKET in report["skipped"]
    assert report["gates"][GATE_MARKET]["status"] == "skipped"
    assert report["passed"] is False


def test_malformed_ref_is_an_error(tmp_path) -> None:
    """缺 request_id 的引用 = 悬空引用，必须 ERROR。"""
    card, resolver, _ = _make_traced_card(tmp_path)
    card["position"]["evidence"][0]["source_ref"] = "ths:600519.SH"

    status, problems, _, _ = _gate_market_traceability(card, resolver)

    assert status == "failed"
    assert any(p["code"] == "market_ref_malformed" for p in problems)


def test_stale_quote_warns_but_does_not_block(tmp_path) -> None:
    """价格太旧是 WARN（提示复核），不是 ERROR（不阻断落卡）。"""
    card, _resolver, _ = _make_traced_card(tmp_path)
    ten_days_later = AS_OF_MS + 10 * 24 * 60 * 60 * 1000

    errors, warnings = check_market_consistency(card, now_ms=ten_days_later)

    assert errors == []
    assert any(w["code"] == "market_quote_stale" for w in warnings)


def test_adjust_mismatch_is_an_error(tmp_path) -> None:
    """同一张卡混用复权口径 ⇒ ERROR（口径混用必错）。"""
    card, _resolver, _ = _make_traced_card(tmp_path)
    card["position"]["evidence"] = [
        {"source_ref": "ths:600519.SH:r1", "page": "p", "quote": "a=1; adjust=none", "kind": "fact"},
        {"source_ref": "ths:600519.SH:r2", "page": "p", "quote": "a=2; adjust=forward", "kind": "fact"},
    ]

    errors, _ = check_market_consistency(card)

    assert any(e["code"] == "adjust_mismatch" for e in errors)


def test_financial_lookahead_is_an_error(tmp_path) -> None:
    """evidence 带 report_date_ms 且晚于当前 ⇒ 前视偏差 ERROR。"""
    card, _resolver, _ = _make_traced_card(tmp_path)
    future = AS_OF_MS + 30 * 24 * 60 * 60 * 1000
    card["position"]["evidence"][0]["report_date_ms"] = future

    errors, _ = check_market_consistency(card)

    assert any(e["code"] == "financial_lookahead" for e in errors)


def test_corpus_only_card_is_untouched() -> None:
    """回归红线：纯语料卡（无市场引用）⇒ 市场闸 passed 且 total=0，corpus 行为不变。"""
    card = {"position": {"evidence": []}}

    status, problems, total, traced = _gate_market_traceability(card, None)

    assert status == "passed" and total == 0 and traced == 0
    assert problems == []
    errors, warnings = check_market_consistency(card)
    assert errors == [] and warnings == []
