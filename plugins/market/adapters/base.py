"""adapter 公共解析工具（L3，§5.0）。

只做**信封解析与契约防御**，不含业务判断。所有解析都以 §2.1.1 实测结论为准：
响应信封**不统一**（有的 `data` 有 `timestamp`，有的没有），因此每一项都要能容忍缺失。
"""

from __future__ import annotations

import time
from typing import Any

from plugins.market.ports import MarketUnavailable


def extract_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """取 `data.item`，统一成 dict 列表（容忍单 dict / 缺失 / None）。"""
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    item = data.get("item")
    if item is None:
        return []
    if isinstance(item, list):
        return [row for row in item if isinstance(row, dict)]
    if isinstance(item, dict):
        return [item]
    return []


def as_of_ms(payload: dict[str, Any]) -> int | None:
    """取 `data.timestamp`（毫秒）。`corporate-actions` 等端点**没有**它（§2.1.1 #4）。"""
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    timestamp = data.get("timestamp")
    if isinstance(timestamp, bool):
        return None
    if isinstance(timestamp, (int, float)):
        return int(timestamp)
    return None


def now_ms() -> int:
    """兜底时点：仅在供应商未提供 `timestamp` 时使用（会在 caveat 中标注）。"""
    return int(time.time() * 1000)


def num(value: Any) -> float | None:
    """数值归一：`null` 表示未披露，**禁止当成 0**（§2 / §9 风险表）。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def text(value: Any) -> str:
    return "" if value is None else str(value)


def guard_batch(item_count: int, requested: int, *, endpoint: str) -> None:
    """**契约防御（§2.1.1 #1）**：批量端点参数名写错会被静默忽略并返回全市场。

    例如 `prices/snapshot` 误传 `thscode` 会返回 5569 条而不报错。此处一旦
    「返回条数 > 请求条数」立即判定为契约错误并失败，**绝不把全市场数据当结果返回**。
    """
    if item_count > requested:
        raise MarketUnavailable(
            "unavailable",
            f"{endpoint} 返回 {item_count} 条，但只请求了 {requested} 条："
            "疑似参数名错误（批量端点必须用 `thscodes`）导致返回全市场数据",
            retryable=False,
        )
