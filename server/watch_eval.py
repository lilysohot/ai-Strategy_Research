"""监控行情判定与防重复唤醒（DATA-10 / PR-WATCH-01/04）。

本模块是监控链的"判定真源"，与 ``plugins.market.Quote``（float + 适配器可回退本地时间）
**分开**：观测以精确 ``Decimal`` 价格 + 供应商观测时间/本地接收时间 + 时间来源可信度进入，
不把 ``now()`` 冒充实时新行情（契约 §9 / DATA-10）。

状态机（C 阶段单次模式）：
- ``armed``（一次触发资格）+ ``baseline_price``（最近已核验价）在 ``watch_rules`` 指针行；
  编辑（新版本）复位两者，改版不复用旧版报价基线与触发资格。
- 有效观测 → 去重 / 乱序过滤 → 基线判定（上穿/下穿/区间，精确比较、不用浮点相等）→
  满足且 armed → 同一事务内消耗资格 + 建事件（唯一身份 = 规则版本 + 一次触发资格）。
- 触发后 armed=False，分析失败不恢复成未触发；后续穿越只记抑制原因，不反复建分析。
- 创建时已达标（``on_create_already_met``）与断线恢复（``disconnect_recovery``）分别执行。

监控链全程不调用 LLM：判定只用行情与状态。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server import store
from server.config import get_config

ACTIVE = "active"

TRIGGER_REASONS = frozenset(
    {"initial_met", "recovered_met", "up_cross", "down_cross", "enter_range"}
)


@dataclass(frozen=True, slots=True)
class MonitoringObservation:
    """一次用于判定的行情观测（DATA-10 判定真源，独立于 Quote 的 float/回退时间）。"""

    thscode: str
    market: str
    currency: str
    price: Decimal
    received_at_ms: int
    observed_at_ms: int | None = None
    #: vendor=供应商观测时间可用；unknown=缺可靠观测时间（不得以本地 now 冒充实时）。
    time_source: str = "vendor"
    #: 值已经过 float 往返（真实适配器），精度受限但判定仍可用。
    precision_limited: bool = False
    source_ref: str | None = None
    quote_basis: str = "last"


class QuoteSource(Protocol):
    """监控轮询的行情源端口：按 thscode 拉取一批观测。"""

    def fetch(self, thscodes: list[str]) -> dict[str, list[MonitoringObservation]]: ...


class FuyaoQuoteSource:
    """把现有市场服务包装成监控观测（保守契约，DATA-10 §需求）。

    现有适配器只暴露 ``Quote``（float、且 as_of 可能回退本地时间），无法可靠辨别观测时间
    来源，因此统一标 ``time_source=unknown`` + ``precision_limited=True``：值可用但**不宣称**
    实时新行情；真实时点/时效验证属 DATA-10 供应商核验，未核验前保持待核定。
    """

    def __init__(self, service: Any) -> None:
        self._service = service

    def fetch(self, thscodes: list[str]) -> dict[str, list[MonitoringObservation]]:
        result = self._service.quote(list(thscodes), with_valuation=False)
        out: dict[str, list[MonitoringObservation]] = {}
        for item in result.get("items", []):
            thscode = str(item.get("thscode") or "")
            raw_price = item.get("last_price")
            if not thscode or raw_price is None:
                continue
            out.setdefault(thscode, []).append(
                MonitoringObservation(
                    thscode=thscode,
                    market="",
                    currency="",
                    price=Decimal(str(raw_price)),
                    observed_at_ms=None,
                    received_at_ms=int(datetime.now(UTC).timestamp() * 1000),
                    time_source="unknown",
                    precision_limited=True,
                    source_ref=f"fuyao:as_of={item.get('as_of_ms')}",
                )
            )
        return out


def condition_met(
    price: Decimal, direction: str, low: Decimal | None, high: Decimal | None
) -> bool:
    """当前价是否已满足触发条件（上穿/下穿/区间）。精确比较，不用浮点相等。"""
    if direction == "up":
        return low is not None and price >= low
    if direction == "down":
        return low is not None and price <= low
    return low is not None and high is not None and low <= price <= high


def classify_cross(
    prev: Decimal | None,
    cur: Decimal,
    direction: str,
    low: Decimal | None,
    high: Decimal | None,
) -> str | None:
    """判定穿越。``prev`` 为上次已核验价（基线），无基线不判定穿越。

    - up：``prev < threshold <= cur``（上穿）
    - down：``prev > threshold >= cur``（下穿）
    - range：从带外进入带内（``prev < low`` 或 ``prev > high``，且 ``low <= cur <= high``）
    """
    if prev is None:
        return None
    if direction == "up":
        return "up_cross" if low is not None and prev < low and cur >= low else None
    if direction == "down":
        return "down_cross" if low is not None and prev > low and cur <= low else None
    if low is not None and high is not None and (prev < low or prev > high) and low <= cur <= high:
        return "enter_range"
    return None


def _dedup_hash(rule_id: Any, obs: MonitoringObservation) -> str:
    ts_ms = obs.observed_at_ms if obs.observed_at_ms is not None else obs.received_at_ms
    raw = f"{rule_id}:{ts_ms}:{obs.price}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _analysis_deadline(obs: MonitoringObservation) -> datetime | None:
    """事件的分析截止 = 接收时间 + 最大排队延迟；配置为 0 表示发布前未冻结（不强制）。"""
    max_delay = get_config().auto_max_delay_seconds
    if max_delay and max_delay > 0:
        return datetime.fromtimestamp(obs.received_at_ms / 1000, UTC) + timedelta(seconds=max_delay)
    return None


def event_view(row: store.WatchEvent) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "rule_id": str(row.rule_id),
        "rule_version": row.rule_version,
        "research_id": str(row.research_id),
        "symbol": row.symbol,
        "market": row.market,
        "currency": row.currency,
        "direction": row.direction,
        "threshold": _threshold_view(row),
        "prev_price": _decimal_text(row.prev_price),
        "price": _decimal_text(row.price),
        "observed_at_ms": row.observed_at_ms,
        "received_at_ms": row.received_at_ms,
        "time_source": row.time_source,
        "trigger_reason": row.trigger_reason,
        "status": row.status,
        "run_id": str(row.run_id) if row.run_id else None,
        "generation": row.generation,
        "merged_into_id": str(row.merged_into_id) if row.merged_into_id else None,
        "budget_reason": row.budget_reason,
        "analysis_expires_at": _iso(row.analysis_expires_at),
        "scheduled_at": _iso(row.scheduled_at),
        "attempted_at": _iso(row.attempted_at),
        "completed_at": _iso(row.completed_at),
        "detail": dict(row.detail_json or {}),
        "created_at": _iso(row.created_at),
    }


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _threshold_view(row: store.WatchEvent) -> Any:
    if row.direction == "range":
        return {"low": _decimal_text(row.threshold_low), "high": _decimal_text(row.threshold_high)}
    return _decimal_text(row.threshold_low)


def observation_view(row: store.WatchObservation) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "rule_id": str(row.rule_id),
        "rule_version": row.rule_version,
        "symbol": row.symbol,
        "price": _decimal_text(row.price),
        "observed_at_ms": row.observed_at_ms,
        "received_at_ms": row.received_at_ms,
        "time_source": row.time_source,
        "precision_limited": row.precision_limited,
        "source_ref": row.source_ref,
        "created_at": _iso(row.created_at),
    }


async def _latest_revision(
    session: AsyncSession, rule_id: Any, version: int
) -> store.WatchRuleRevision | None:
    return (
        await session.execute(
            select(store.WatchRuleRevision).where(
                store.WatchRuleRevision.rule_id == rule_id,
                store.WatchRuleRevision.version == version,
            )
        )
    ).scalar_one_or_none()


async def _last_observed_ms(session: AsyncSession, *, rule_id: Any) -> int | None:
    """该规则最近一条带供应商观测时间的观测（乱序/重放过滤的锚点）。"""
    return (
        await session.execute(
            select(func.max(store.WatchObservation.observed_at_ms)).where(
                store.WatchObservation.rule_id == rule_id,
                store.WatchObservation.observed_at_ms.is_not(None),
            )
        )
    ).scalar_one_or_none()


async def list_events(
    session: AsyncSession,
    *,
    user_id: Any,
    research_id: Any | None = None,
    status: str | None = None,
    limit: int,
    offset: int,
) -> tuple[list[store.WatchEvent], int]:
    """按所有者列出监控事件（DATA-11 追溯 / UI-09）。"""
    stmt = select(store.WatchEvent).where(store.WatchEvent.user_id == user_id)
    if research_id is not None:
        stmt = stmt.where(store.WatchEvent.research_id == research_id)
    if status is not None:
        stmt = stmt.where(store.WatchEvent.status == status)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(store.WatchEvent.received_at_ms.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total


def _decide_trigger(
    *,
    armed: bool,
    first_ever: bool,
    gap: bool,
    prev_baseline: Decimal | None,
    price: Decimal,
    direction: str,
    low: Decimal | None,
    high: Decimal | None,
    on_create: str,
    disconnect: str,
) -> tuple[str, Decimal | None] | None:
    """单次模式触发决策：返回 ``(trigger_reason, prev_price)`` 或 ``None``（不触发）。

    - 首次观测已达标 → 按 ``on_create_already_met``（trigger_now 触发 / wait_requalify 等待重新穿越）
    - 断线缺口后恢复且已达标 → 按 ``disconnect_recovery``（trigger_once 触发 / wait_requalify 不补发）
    - 常规穿越（上穿/下穿/进入区间）→ 触发
    """
    if not armed:
        return None
    if first_ever:
        if condition_met(price, direction, low, high) and on_create == "trigger_now":
            return ("initial_met", None)
        return None
    if gap and condition_met(price, direction, low, high):
        if disconnect == "trigger_once":
            return ("recovered_met", prev_baseline)
        return None
    cross = classify_cross(prev_baseline, price, direction, low, high)
    return (cross, prev_baseline) if cross is not None else None


async def evaluate(
    session: AsyncSession,
    *,
    rule_id: Any,
    obs: MonitoringObservation,
    now: datetime | None = None,
    max_gap: timedelta | None = None,
) -> dict[str, Any]:
    """对一条观测做一次判定，并与规则状态/事件**同一事务**原子保存。

    返回状态：``triggered`` / ``watched``（已核验未触发）/ ``suppressed``（已消耗等）/
    ``duplicate``（重复投递）/ ``stale``（乱序/重放）/ ``mismatch``（标的/币种不符）/
    ``inactive``（暂停/取消，不判定）/ ``not_found``。
    """
    now = now or datetime.now(UTC)
    rule = (
        await session.execute(
            select(store.WatchRule).where(store.WatchRule.id == rule_id).with_for_update()
        )
    ).scalar_one_or_none()
    if rule is None:
        return {"status": "not_found"}
    if rule.status != ACTIVE:
        return {"status": "inactive"}
    rev = await _latest_revision(session, rule.id, rule.current_version)
    if rev is None:
        return {"status": "inactive"}
    if rev.symbol != obs.thscode or rev.market != obs.market or rev.currency != obs.currency:
        return {"status": "mismatch"}
    if rev.expires_at is not None and now > rev.expires_at:
        # 有效期已过：不再判定/记录观测，保持待核定（规则本身未取消，UI 可续期改版）。
        return {"status": "expired"}

    dedup = _dedup_hash(rule.id, obs)
    existing = (
        await session.execute(
            select(store.WatchObservation).where(store.WatchObservation.dedup_hash == dedup)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {"status": "duplicate"}
    if obs.observed_at_ms is not None:
        last_ms = await _last_observed_ms(session, rule_id=rule.id)
        if last_ms is not None and obs.observed_at_ms < last_ms:
            return {"status": "stale"}

    prev_baseline = rule.baseline_price
    prev_last_valid_at = rule.last_valid_quote_at
    first_ever = prev_baseline is None
    gap = (
        max_gap is not None
        and prev_last_valid_at is not None
        and (now - prev_last_valid_at) > max_gap
    )

    direction = rev.direction
    low, high = rev.threshold_low, rev.threshold_high
    price = obs.price

    trigger = _decide_trigger(
        armed=rule.armed,
        first_ever=first_ever,
        gap=gap,
        prev_baseline=prev_baseline,
        price=price,
        direction=direction,
        low=low,
        high=high,
        on_create=rev.on_create_already_met,
        disconnect=rev.disconnect_recovery,
    )

    # 观测（audit）先落，同一事务后续状态/事件与之一起提交/回滚。
    session.add(
        store.WatchObservation(
            rule_id=rule.id,
            rule_version=rule.current_version,
            user_id=rule.user_id,
            research_id=rule.research_id,
            symbol=obs.thscode,
            market=obs.market,
            currency=obs.currency,
            quote_basis=obs.quote_basis or "last",
            price=price,
            observed_at_ms=obs.observed_at_ms,
            received_at_ms=obs.received_at_ms,
            time_source=obs.time_source,
            precision_limited=obs.precision_limited,
            source_ref=obs.source_ref,
            dedup_hash=dedup,
        )
    )
    await session.flush()

    event_id: str | None = None
    if trigger is not None:
        # 事件唯一约束（rule_id, rule_version）是并发判定的库级兜底：真并发时只有一方
        # 能插入成功，另一方拿到 IntegrityError 整体回滚（fail closed），不重复消耗资格。
        event = store.WatchEvent(
            rule_id=rule.id,
            rule_version=rule.current_version,
            user_id=rule.user_id,
            research_id=rule.research_id,
            symbol=obs.thscode,
            market=obs.market,
            currency=obs.currency,
            quote_basis=obs.quote_basis or "last",
            direction=direction,
            threshold_low=low,
            threshold_high=high,
            prev_price=trigger[1],
            price=price,
            observed_at_ms=obs.observed_at_ms,
            received_at_ms=obs.received_at_ms,
            time_source=obs.time_source,
            trigger_reason=trigger[0],
            status="pending",
            analysis_expires_at=_analysis_deadline(obs),
            detail_json={
                "gap": gap,
                "first_observation": first_ever,
                "precision_limited": obs.precision_limited,
            },
        )
        session.add(event)
        await session.flush()
        event_id = str(event.id)
        rule.armed = False
        rule.last_triggered_at = now
        rule.last_suppressed_reason = None
        status = "triggered"
        reason = trigger[0]
    else:
        if not rule.armed:
            rule.last_suppressed_reason = "single_trigger_consumed"
            status = "suppressed"
            reason = "single_trigger_consumed"
        else:
            rule.last_suppressed_reason = None
            status = "watched"
            reason = None

    rule.baseline_price = price
    rule.last_check_at = now
    rule.last_valid_quote_at = datetime.fromtimestamp(obs.received_at_ms / 1000, UTC)
    rule.last_valid_quote_price = price
    await session.flush()

    outcome: dict[str, Any] = {"status": status, "reason": reason}
    if event_id is not None:
        outcome["event_id"] = event_id
    return outcome
