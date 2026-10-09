"""market_financials 只内联最新一期（试验阶段压缩执行时间）。

背景：整份历史报表可达 11 万字符，会触发工具结果的 overflow 落盘，模型只能用
``recover_result`` 逐页翻读（每次上限 2 万字符），实测一次任务为此多花约 6 轮 LLM 往返。

本测试锁住两条：
1. 多期时只返回最新一期（按报告期末取最新）；
2. 发生省略时**必须**带 ``total_items`` 与 ``truncated``，否则模型会把「只给一期」
   误读成「该公司只披露过一期」。
"""

from __future__ import annotations

import importlib
import json

import pytest

tool_module = importlib.import_module("plugins.tools.market_financials")
market_financials = tool_module.market_financials

_THSCode = "600519.SH"


class _FakeService:
    def __init__(self, items: list[dict]) -> None:
        self._items = items

    def financials(self, thscode: str, *, period: str, statement: str) -> dict:
        return {
            "ok": bool(self._items),
            "thscode": thscode,
            "period": period,
            "statement": statement,
            "items": self._items,
        }


def _row(period_end_ms: int, fiscal_year: str, *, fields: int = 1) -> dict:
    return {
        "fiscal_year": fiscal_year,
        "fiscal_period": "FY",
        "report_date_ms": period_end_ms + 86_400_000,
        "period_end_ms": period_end_ms,
        "currency": "CNY",
        "values": {f"item_{i}": 1 for i in range(fields)},
    }


@pytest.fixture(autouse=True)
def _stub_market(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool_module, "unavailability", lambda: None)
    monkeypatch.setattr(
        tool_module, "resolve_or_error", lambda service, query: (_THSCode, None)
    )


async def test_multi_period_returns_only_latest(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        _row(1_600_000_000_000, "2022"),
        _row(1_700_000_000_000, "2023"),
        _row(1_800_000_000_000, "2024"),
    ]
    monkeypatch.setattr(tool_module, "build_service", lambda: _FakeService(rows))

    payload = json.loads(await market_financials.func("600519.SH"))

    assert payload["ok"] is True
    assert len(payload["items"]) == 1
    assert payload["items"][0]["fiscal_year"] == "2024"
    assert payload["total_items"] == 3
    assert payload["truncated"] is True
    assert "total_items" in payload["note"]


async def test_single_period_is_not_marked_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tool_module, "build_service", lambda: _FakeService([_row(1_800_000_000_000, "2024")])
    )

    payload = json.loads(await market_financials.func("600519.SH"))

    assert len(payload["items"]) == 1
    assert "truncated" not in payload
    assert "total_items" not in payload
    assert payload["note"].startswith("report_date_ms=披露日")


async def test_empty_items_are_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool_module, "build_service", lambda: _FakeService([]))

    payload = json.loads(await market_financials.func("600519.SH"))

    assert payload["ok"] is False
    assert payload["items"] == []
    assert "truncated" not in payload


async def test_order_is_by_period_end_not_input_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        _row(1_700_000_000_000, "2023"),
        _row(1_800_000_000_000, "2024"),
        _row(1_600_000_000_000, "2022"),
    ]
    monkeypatch.setattr(tool_module, "build_service", lambda: _FakeService(rows))

    payload = json.loads(await market_financials.func("600519.SH"))

    assert payload["items"][0]["fiscal_year"] == "2024"


async def test_payload_fits_overflow_scale(monkeypatch: pytest.MonkeyPatch) -> None:
    """12 期 × 200 科目的场景必须被压到一页，否则又会溢出成可 recover 的大结果。"""
    rows = [
        _row(1_700_000_000_000 + i, f"20{10 + i:02d}", fields=200) for i in range(12)
    ]
    monkeypatch.setattr(tool_module, "build_service", lambda: _FakeService(rows))

    raw = await market_financials.func("600519.SH")

    assert len(json.loads(raw)["items"]) == 1
    assert len(raw) < 20_000
