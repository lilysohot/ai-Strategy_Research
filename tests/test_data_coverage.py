"""data_coverage 验收：开局一次性探测数据源覆盖度 + 全空时的正确出口。

四种结论都要验到，尤其后两种是**行为要求**而非提示：
- ``partial``（无研报有行情）⇒ 要求停止检索研报、转市场数据；
- ``none``（全空）⇒ 要求直接输出「数据不足，不做判断」，且明确这是唯一正确产出。
"""

from __future__ import annotations

import asyncio
import importlib
import json

import pytest

from plugins.market.service import ResolveResult

data_coverage_module = importlib.import_module("plugins.tools.data_coverage")


class _FakeCorpus:
    def __init__(self, hits: list) -> None:
        self._hits = hits

    def search(self, query: str, limit: int = 10) -> list:
        return self._hits[:limit]


class _FakeMarket:
    def __init__(self, *, quotes: list | None = None, financials: list | None = None) -> None:
        self._quotes = quotes if quotes is not None else []
        self._financials = financials if financials is not None else []

    def resolve(self, query: str, *, prefer_asset_type: str = "a-share") -> ResolveResult:
        return ResolveResult(query=query, ok=True, thscode="600519.SH", name="测试标的")

    def quote(self, thscodes: list[str], **kwargs) -> dict:
        return {"ok": bool(self._quotes), "items": self._quotes, "caveats": []}

    def financials(self, thscode: str, **kwargs) -> dict:
        return {"ok": bool(self._financials), "items": self._financials, "period": "annual"}


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    research_hits: list | None = None,
    market: _FakeMarket | None = None,
    denied: dict | None = None,
) -> None:
    from plugins.corpus import service as corpus_service_module

    monkeypatch.setattr(
        corpus_service_module, "get_service", lambda: _FakeCorpus(research_hits or [])
    )
    if denied is not None:
        monkeypatch.setattr(data_coverage_module, "unavailability", lambda *a, **k: denied)
    else:
        monkeypatch.setattr(data_coverage_module, "unavailability", lambda *a, **k: None)
        monkeypatch.setattr(data_coverage_module, "build_service", lambda *a, **k: market)


def _probe(query: str = "茅台", **kwargs) -> dict:
    raw = asyncio.run(data_coverage_module.data_coverage.func(query, **kwargs))
    return json.loads(raw)


def test_full_when_research_and_market_both_available(monkeypatch) -> None:
    _install(
        monkeypatch,
        research_hits=[{"doc_id": "a", "locator": "1", "title": "研报"}],
        market=_FakeMarket(quotes=[{"thscode": "600519.SH", "as_of_ms": 1788938632000}]),
    )

    payload = _probe()

    assert payload["verdict"] == "full"
    assert payload["coverage"]["research"]["count"] == 1
    assert payload["coverage"]["quote"]["available"] is True
    assert payload["thscode"] == "600519.SH"


def test_partial_without_research_requires_switching_to_market(monkeypatch) -> None:
    _install(
        monkeypatch,
        research_hits=[],
        market=_FakeMarket(quotes=[{"thscode": "600519.SH", "as_of_ms": 1788938632000}]),
    )

    payload = _probe()

    assert payload["verdict"] == "partial"
    assert payload["coverage"]["research"]["count"] == 0
    assert "停止" in payload["guidance"], "无研报时必须要求停止检索研报"
    assert "market_history" in payload["guidance"], "必须指明转市场数据做技术面"


def test_none_gives_the_correct_exit(monkeypatch) -> None:
    """全空：唯一正确产出是「数据不足，不做判断」，且要明确这不是失败。"""
    _install(monkeypatch, research_hits=[], market=_FakeMarket())

    payload = _probe()

    assert payload["verdict"] == "none"
    assert payload["coverage"]["quote"]["available"] is False
    assert "数据不足，不做判断" in payload["guidance"]
    assert "不是失败" in payload["guidance"], "必须让模型知道这是正确产出，而非任务失败"
    assert "严禁编造" in payload["guidance"]


def test_research_only_forbids_inventing_prices(monkeypatch) -> None:
    """有研报但无行情：只能定性，禁止给具体价格数字。"""
    _install(
        monkeypatch,
        research_hits=[{"doc_id": "a", "locator": "1", "title": "研报"}],
        market=_FakeMarket(),  # 行情与财报都空
    )

    payload = _probe()

    assert payload["verdict"] == "research_only"
    assert "禁止给出任何具体价格" in payload["guidance"]


def test_market_unavailable_is_reported_not_crashed(monkeypatch) -> None:
    """市场不可用（缺凭据）要如实标记，不能崩，也不能假装"有数据"。"""
    _install(monkeypatch, research_hits=[], denied={"ok": False, "reason": "THS_API_KEY 未配置"})

    payload = _probe()

    assert payload["ok"] is True
    assert payload["coverage"]["quote"]["available"] is False
    assert "THS_API_KEY" in (payload["coverage"]["quote"]["error"] or "")


def test_corpus_outage_is_distinguished_from_no_research(monkeypatch) -> None:
    """语料库故障 ≠ 没有研报：两者要分开记，否则会把故障误判成"无覆盖"。"""

    def _boom():
        raise RuntimeError("connection refused")

    from plugins.corpus import service as corpus_service_module

    monkeypatch.setattr(corpus_service_module, "get_service", _boom)
    monkeypatch.setattr(data_coverage_module, "unavailability", lambda *a, **k: None)
    monkeypatch.setattr(
        data_coverage_module,
        "build_service",
        lambda *a, **k: _FakeMarket(quotes=[{"thscode": "600519.SH", "as_of_ms": 1}]),
    )

    payload = _probe()

    assert payload["coverage"]["research"]["count"] == 0
    assert payload["coverage"]["research"]["error"], "语料库故障必须单独记录"


def test_empty_query_is_rejected() -> None:
    payload = asyncio.run(data_coverage_module.data_coverage.func("   "))
    assert json.loads(payload)["ok"] is False
