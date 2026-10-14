"""Market-local dates and conservative finality labels for price evidence."""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


def local_date(timestamp_ms: Any, thscode: str) -> str | None:
    """Translate supported exchange timestamps without shifting China dates to UTC."""
    if not thscode.upper().endswith((".SH", ".SZ", ".BJ")):
        return None
    if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, (int, float)):
        return None
    try:
        return (
            datetime.fromtimestamp(timestamp_ms / 1000, ZoneInfo("Asia/Shanghai"))
            .date()
            .isoformat()
        )
    except (ValueError, OverflowError, OSError):
        return None


def annotate_history(result: dict[str, Any], thscode: str, now_ms: int) -> dict[str, Any]:
    """Keep incomplete daily bars outside the closed series used for comparisons."""
    today = local_date(now_ms, thscode)
    items: list[dict[str, Any]] = []
    provisional_items: list[dict[str, Any]] = []
    raw_items = list(result.get("items", []))
    for row in raw_items:
        date = local_date(row.get("date_ms"), thscode)
        status = "closed" if date and today and date < today else "provisional"
        if not date:
            status = "unverified"
        annotated = {
            **row,
            "trade_date": date,
            "bar_status": status,
            "comparison_eligible": status == "closed",
        }
        if status == "provisional":
            provisional_items.append(annotated)
        else:
            items.append(annotated)
    closed_dates = [row["trade_date"] for row in items if row["bar_status"] == "closed"]
    timezone = ZoneInfo("Asia/Shanghai") if today else None
    retrieved_at = (
        datetime.fromtimestamp(now_ms / 1000, timezone).isoformat(timespec="seconds")
        if timezone
        else None
    )
    return {
        **result,
        "raw_count": len(raw_items),
        "count": len(items),
        "items": items,
        "provisional_items": provisional_items,
        "latest_closed_trade_date": max(closed_dates) if closed_dates else None,
        "market_timezone": "Asia/Shanghai" if today else None,
        "retrieved_at": retrieved_at,
        "price_time_note": "items 只含可用于完整日比较的已收盘日线；盘中临时柱单列在 provisional_items。",
        "provisional_policy": (
            "provisional_items 仅是 retrieved_at 时刻的盘中快照：不能称为收盘价，"
            "不能纳入日均量、均线或完整日涨跌比较，也不能确认支撑守住或日K形态完成。"
        ),
    }
