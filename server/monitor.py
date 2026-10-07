"""监控常驻轮询（DATA-10；DATA-00 §5 后台进程登记）。

判定与状态机在 :mod:`server.watch_eval`；本模块只负责：定期取活跃规则 → 经行情源拉观测 →
逐规则调用 ``watch_eval.evaluate``（各自独立事务原子保存）。**监控链不调用 LLM**。

行情源不可用（未配置 THS 凭据等）时 ``build_quote_source`` 返回 ``None``，调用方保持
"监控未启用/待核定"，不伪装实时；真实供应商时效/容量验证属 DATA-10 供应商核验项。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from server import business_service as biz
from server import restore_check, store, watch_eval, watch_rules

logger = logging.getLogger(__name__)


def build_quote_source() -> watch_eval.QuoteSource | None:
    """构造真实行情源；缺凭据/未启用时返回 ``None``（不拖垮主流程）。"""
    try:
        from plugins.market.factory import build_service

        service = build_service()
    except Exception:  # pragma: no cover - 配置异常不应阻断启动判定
        logger.exception("build market service failed")
        service = None
    if service is None:
        return None
    return watch_eval.FuyaoQuoteSource(service)


async def _active_rules(
    session: Any, *, max_rules: int
) -> list[tuple[store.WatchRule, store.WatchRuleRevision | None]]:
    rows = (
        (
            await session.execute(
                select(store.WatchRule)
                .where(store.WatchRule.status == watch_rules.ACTIVE)
                .order_by(store.WatchRule.updated_at.asc())
                .limit(max_rules)
            )
        )
        .scalars()
        .all()
    )
    items: list[tuple[store.WatchRule, store.WatchRuleRevision | None]] = []
    for rule in rows:
        rev = await watch_eval._latest_revision(session, rule.id, rule.current_version)
        items.append((rule, rev))
    return items


async def monitor_tick(
    quote_source: watch_eval.QuoteSource,
    *,
    max_rules: int,
    max_symbols: int,
    max_gap: timedelta,
    now: datetime | None = None,
) -> dict[str, int]:
    """一轮采样：取活跃规则 → 拉观测 → 逐规则判定。返回计数。"""
    now = now or datetime.now(UTC)
    counters = {"evaluated": 0, "triggered": 0, "skipped": 0, "no_quote": 0}
    async with biz.business_transaction() as session:
        rules = await _active_rules(session, max_rules=max_rules)
    by_symbol: dict[str, list[tuple[store.WatchRule, store.WatchRuleRevision]]] = {}
    for rule, rev in rules:
        if rev is None:
            continue
        by_symbol.setdefault(rev.symbol, []).append((rule, rev))
    symbols = list(by_symbol)[:max_symbols]
    if not symbols:
        return counters
    obs_by_symbol = quote_source.fetch(symbols)
    for symbol in symbols:
        for rule, rev in by_symbol.get(symbol, []):
            observations = obs_by_symbol.get(symbol)
            if not observations:
                counters["no_quote"] += 1
                continue
            for obs in observations:
                # 观测只携带价格/时间；市场与币种从规则版本补充，供 evaluate 校验匹配。
                enriched = replace(obs, market=rev.market, currency=rev.currency)
                try:
                    async with biz.business_transaction() as session:
                        outcome = await watch_eval.evaluate(
                            session,
                            rule_id=rule.id,
                            obs=enriched,
                            now=now,
                            max_gap=max_gap,
                        )
                except Exception:
                    logger.exception("watch evaluate failed rule=%s", rule.id)
                    counters["skipped"] += 1
                    continue
                counters["evaluated"] += 1
                if outcome.get("status") == "triggered":
                    counters["triggered"] += 1
    return counters


async def monitor_loop(
    quote_source: watch_eval.QuoteSource,
    *,
    poll_seconds: float,
    max_rules: int,
    max_symbols: int,
    max_gap: timedelta,
) -> None:
    """常驻轮询主循环；异常不退出，记录后等待下一轮。"""
    while True:
        # 恢复/迁移模式：禁止行情消费（DATA-14）。配置按 mtime 热加载，切换即停。
        if not restore_check.background_tasks_allowed():
            await asyncio.sleep(poll_seconds)
            continue
        try:
            await monitor_tick(
                quote_source,
                max_rules=max_rules,
                max_symbols=max_symbols,
                max_gap=max_gap,
                now=datetime.now(UTC),
            )
        except Exception:
            logger.exception("monitor tick failed")
        await asyncio.sleep(poll_seconds)
