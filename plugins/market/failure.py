"""失败分类与转译（§6：任何时候都不拖垮主流程）。

transport 已保证「不把 `httpx` 异常往外传」，本层负责把它变成 **Agent 能读懂、
能照着做** 的失败：`reason` + `request_id` + `next`。

两条纪律：
1. **不落库 ⇒ 没有「退而求其次」**：失败就是失败，绝不返回旧值 / 近似值冒充新值；
2. 失败必须**可执行**：每条 `next` 都指向具体下一步（对齐 `corpus_fetch` 找不到时
   引导下一步的风格）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from plugins.market.ports import FailureKind, MarketUnavailable

#: 每类失败给 Agent 的下一步建议（§6.3）
NEXT_ACTIONS: dict[FailureKind, str] = {
    "credentials": "检查 .env 的 THS_API_KEY 与该 capability 权限（§7）；"
    "也可设 MARKET_ENABLED=false 让流程退化为未接入的形态继续跑",
    "bad_request": "修正参数后重试：批量端点用 `thscodes`、单标的端点用 `thscode`；"
    "`financials` 的 period 只能是 `annual` / `quarterly`（§2.1.1）",
    "not_found": "先用 `market_resolve` 消歧拿到正确的 `thscode`（接口不接受纯代码）",
    "rate_limited": "稍后重试即可；本模块**绝不返回旧值冒充新值**",
    "unavailable": "供应商侧异常，稍后重试；期间可先用研报证据出卡（§6.4）",
    "network": "检查网络与超时设置；取不到数时可用研报证据出卡（§6.4），不要卡死流程",
}


def translate(exc: MarketUnavailable, *, tool: str = "") -> dict[str, Any]:
    """把领域异常转译成 Agent 可读的失败结果。

    返回体恒定含 `ok=False`、`reason`、`kind`、`request_id`（对账唯一凭证）、`next`。
    """
    reason = exc.message
    if tool:
        reason = f"{tool}: {reason}"
    return {
        "ok": False,
        "kind": exc.kind,
        "reason": reason,
        "request_id": exc.request_id,
        "next": NEXT_ACTIONS.get(exc.kind, ""),
        "retryable": exc.retryable,
    }


def build_partial(
    items: list[Any],
    failures: list[dict[str, Any]],
    *,
    tool: str = "",
) -> dict[str, Any]:
    """多标的 / 多端点调用时的**部分成功**（§6.5：一个失败不影响其他）。

    只在 `items` 非空时算 partial；全失败时仍返回 `ok=False`。
    """
    payload: dict[str, Any] = {
        "ok": bool(items),
        "items": items,
        "failures": failures,
    }
    if items and failures:
        payload["partial"] = True
        payload["note"] = f"部分标的取数失败（{len(failures)} 项），已返回成功部分"
    if tool:
        payload["tool"] = tool
    return payload


def call_or_fail[T](fn: Callable[[], T], *, tool: str = "") -> T | dict[str, Any]:
    """执行 `fn`，把任何失败转成 `translate` 结果，**不让异常冒泡拖垮主流程**。

    用于工具层最后一道防线（§6.2 第四道）。成功时原样返回 `T`。
    """
    try:
        return fn()
    except MarketUnavailable as exc:
        return translate(exc, tool=tool)
    except Exception as exc:  # 最后一道防线，必须兜住
        return translate(
            MarketUnavailable("network", f"未预期的失败：{type(exc).__name__}: {exc}"),
            tool=tool,
        )
