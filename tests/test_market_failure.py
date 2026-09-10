"""M2b 验收：失败分类与转译（§6）。

关注三点：失败**可分类**、**带 `request_id` 可对账**、**`next` 可执行**；
以及最后一道防线 `call_or_fail` 绝不让异常冒泡拖垮主流程。
"""

from __future__ import annotations

import pytest

from plugins.market.failure import NEXT_ACTIONS, build_partial, call_or_fail, translate
from plugins.market.ports import MarketUnavailable


def test_translate_includes_reason_request_id_and_next() -> None:
    error = MarketUnavailable("rate_limited", "触发限流（HTTP 429）", request_id="rid-42")
    result = translate(error, tool="market_quote")

    assert result["ok"] is False
    assert result["kind"] == "rate_limited"
    assert result["request_id"] == "rid-42"
    assert "market_quote" in result["reason"]
    assert result["next"]


@pytest.mark.parametrize("kind", sorted(NEXT_ACTIONS))
def test_every_failure_kind_has_actionable_next(kind: str) -> None:
    result = translate(MarketUnavailable(kind, "msg"))
    assert result["next"], f"{kind} 缺少可执行的下一步建议"


def test_not_found_next_points_to_resolve() -> None:
    """对齐 corpus_fetch 风格：找不到时引导下一步，而不是干巴巴报错。"""
    result = translate(MarketUnavailable("not_found", "标的不存在"))
    assert "market_resolve" in result["next"]


def test_bad_request_next_mentions_param_contract() -> None:
    """参数错误的提示要带上 §2.1.1 实测的参数名契约。"""
    result = translate(MarketUnavailable("bad_request", "Missing required parameter: thscodes"))
    assert "thscodes" in result["next"]
    assert "thscode" in result["next"]


def test_partial_success_keeps_ok_and_marks_partial() -> None:
    result = build_partial(
        [{"thscode": "600519.SH"}], [{"reason": "取数失败"}], tool="market_quote"
    )
    assert result["ok"] is True
    assert result["partial"] is True


def test_all_failed_is_not_ok() -> None:
    result = build_partial([], [{"reason": "取数失败"}])
    assert result["ok"] is False
    assert "partial" not in result


def test_call_or_fail_converts_market_error() -> None:
    def raise_market() -> None:
        raise MarketUnavailable("unavailable", "上游异常", request_id="rid-9")

    result = call_or_fail(raise_market, tool="market_quote")
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert result["kind"] == "unavailable"


def test_call_or_fail_catches_unexpected_exception() -> None:
    def boom() -> None:
        raise RuntimeError("boom")

    result = call_or_fail(boom, tool="market_quote")
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert result["kind"] == "network"


def test_call_or_fail_returns_value_on_success() -> None:
    assert call_or_fail(lambda: 42) == 42
