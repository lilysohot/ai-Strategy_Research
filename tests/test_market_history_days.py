"""market_history 只回溯 90 天（试验阶段压缩执行时间）。

背景：模型传 ``days=3650`` 时，一次返回约 2400 条日线（13 万字符），触发工具结果的
overflow 落盘，模型只能靠 ``recover_result`` 逐页翻读（每次 2 万字符），实测一次任务
为此多花约 6 轮 LLM 往返。

本测试锁住三条：
1. 默认与上限都是 90 天；
2. 请求超过上限时截到 90，并带 ``requested_days`` / ``capped``，避免被误读成
   「更早区间不存在」；
3. 真正传给数据层的窗口也按截断后的天数计算（不能只改返回字段）。
"""

from __future__ import annotations

import importlib
import json

import pytest

tool_module = importlib.import_module("plugins.tools.market_history")
market_history = tool_module.market_history

_DAY_MS = 24 * 60 * 60 * 1000


class _FakeService:
    def __init__(self) -> None:
        self.windows: list[tuple[int, int]] = []

    def history(
        self,
        thscode: str,
        *,
        start_ms: int,
        end_ms: int,
        interval: str = "1d",
        adjust: str = "none",
    ) -> dict:
        self.windows.append((start_ms, end_ms))
        return {
            "ok": True,
            "thscode": thscode,
            "interval": interval,
            "adjust": adjust,
            "count": 0,
            "items": [],
        }


@pytest.fixture()
def service(monkeypatch: pytest.MonkeyPatch) -> _FakeService:
    fake = _FakeService()
    monkeypatch.setattr(tool_module, "unavailability", lambda: None)
    monkeypatch.setattr(tool_module, "build_service", lambda: fake)
    monkeypatch.setattr(
        tool_module, "resolve_or_error", lambda svc, query: ("600519.SH", None)
    )
    return fake


async def test_default_is_ninety_days(service: _FakeService) -> None:
    payload = json.loads(await market_history.func("600519.SH"))

    assert payload["days"] == 90
    assert "capped" not in payload
    start_ms, end_ms = service.windows[0]
    assert end_ms - start_ms == 90 * _DAY_MS


async def test_request_above_cap_is_clamped_and_labelled(service: _FakeService) -> None:
    payload = json.loads(await market_history.func("600519.SH", days=3650))

    assert payload["days"] == 90
    assert payload["requested_days"] == 3650
    assert payload["capped"] is True
    assert "90" in payload["note"]
    start_ms, end_ms = service.windows[0]
    assert end_ms - start_ms == 90 * _DAY_MS, "窗口必须按截断后的天数计算"


async def test_shorter_window_is_kept(service: _FakeService) -> None:
    payload = json.loads(await market_history.func("600519.SH", days=30))

    assert payload["days"] == 30
    assert "capped" not in payload
    start_ms, end_ms = service.windows[0]
    assert end_ms - start_ms == 30 * _DAY_MS


@pytest.mark.parametrize("bad", [0, -5, True, "60", None])
async def test_invalid_days_fall_back_to_default(
    service: _FakeService, bad: object
) -> None:
    payload = json.loads(await market_history.func("600519.SH", days=bad))

    assert payload["days"] == 90
    assert "capped" not in payload
