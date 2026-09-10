"""确定性渲染：`quote_text` 与 `as_of` 可读化（§5.4）。

两条硬要求：
1. **确定性**：同一次响应渲染两次必须完全一致，否则留痕比对会随机误判（§5.5）；
2. **时点可读**：价格是实时时变的，毫秒戳让模型换算必错 ⇒ 同时给
   `as_of_ms` / `as_of`（ISO）/ `age`（"同日" / "N 天前"）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

TZ_SHANGHAI = timezone(timedelta(hours=8))


def to_iso(as_of_ms: int) -> str:
    """毫秒时间戳 → ISO 8601（Asia/Shanghai）。"""
    return datetime.fromtimestamp(as_of_ms / 1000, TZ_SHANGHAI).isoformat()


def age_label(as_of_ms: int, *, now_ms: int | None = None) -> str:
    """距现在多久（按**自然日粗判**，无日历表时如此，§5.5）。"""
    now = datetime.fromtimestamp((now_ms or as_of_ms) / 1000, TZ_SHANGHAI)
    then = datetime.fromtimestamp(as_of_ms / 1000, TZ_SHANGHAI)
    days = (now.date() - then.date()).days
    if days <= 0:
        return "同日"
    if days == 1:
        return "1 天前"
    return f"{days} 天前"


def format_as_of(as_of_ms: int, *, now_ms: int | None = None) -> dict[str, object]:
    """同时给机器可读（毫秒）与人类可读（ISO / age）三种时点表达。"""
    return {
        "as_of_ms": as_of_ms,
        "as_of": to_iso(as_of_ms),
        "age": age_label(as_of_ms, now_ms=now_ms),
    }


def _fmt(value: float | None) -> str:
    if value is None:
        return "null"  # 未披露，明确标注而不是写 0（§9 风险表）
    return f"{value}"


def render_quote_text(
    quote_last_price: float | None,
    *,
    pe_ttm: float | None = None,
    as_of_ms: int = 0,
    adjust: str = "none",
) -> str:
    """渲染规范 `quote_text`（字段与顺序固定，供硬闸①逐字比对）。

    形如：`last_price=1290.88; pe_ttm=19.816116; as_of=1788938632000`
    """
    parts = [f"last_price={_fmt(quote_last_price)}"]
    if pe_ttm is not None:
        parts.append(f"pe_ttm={_fmt(pe_ttm)}")
    parts.append(f"as_of={as_of_ms}")
    if adjust and adjust != "none":
        parts.append(f"adjust={adjust}")  # 前复权随基准变化，必须标注口径（§9 坑 1）
    return "; ".join(parts)
