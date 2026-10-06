"""DATA-10 验收：监控行情判定与防重复唤醒在真实 PostgreSQL 上的契约行为。

固定时钟 + 脚本化行情序列，直接驱动 ``watch_eval.evaluate``（不经真实行情源/模型）：
上穿/下穿/区间、阈值附近往返只触发一次、一直越线不反复、重启不重复、乱序/重复报价忽略、
暂停/取消不判定、并发只消耗一次资格、断线恢复策略、改版重新布防。监控链模型调用数为零。
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from server import business_service as biz
from server import store, watch_eval, watch_rules

pytestmark = pytest.mark.pg

#: 固定时钟锚点（毫秒）。
BASE_MS = 1730000000000
STEP_MS = 60_000


def _ms(step: int) -> int:
    return BASE_MS + step * STEP_MS


def _dt(step: int) -> datetime:
    return datetime.fromtimestamp(_ms(step) / 1000, UTC)


def make_obs(
    price,
    *,
    step: int,
    symbol="600519.SH",
    market="CN",
    currency="CNY",
    time_source="vendor",
    precision_limited=False,
) -> watch_eval.MonitoringObservation:
    return watch_eval.MonitoringObservation(
        thscode=symbol,
        market=market,
        currency=currency,
        price=Decimal(str(price)),
        received_at_ms=_ms(step),
        observed_at_ms=_ms(step) if time_source == "vendor" else None,
        time_source=time_source,
        precision_limited=precision_limited,
    )


@pytest.fixture
async def case(pg_clean):
    uid, rid = uuid.uuid4(), uuid.uuid4()
    async with biz.business_transaction() as session:
        session.add(store.User(id=uid, username=f"eval-{uid.hex}", password_hash="x"))
        await session.flush()
        session.add(store.Session(id=rid, user_id=uid, title="eval research"))
        await session.flush()
    yield SimpleNamespace(uid=uid, rid=rid)


async def create_rule(case, *, spec=None, **extra) -> uuid.UUID:
    body = {
        "research_id": case.rid,
        "name": "监控规则",
        "spec": spec
        if spec is not None
        else {
            "symbol": "600519.SH",
            "market": "CN",
            "currency": "CNY",
            "direction": "up",
            "threshold": "20",
            "action": "auto_analyze",
            "on_create_already_met": "trigger_now",
            "disconnect_recovery": "trigger_once",
        },
    }
    async with biz.business_transaction() as session:
        outcome = await watch_rules.create_rule(
            session,
            user_id=case.uid,
            research_id=case.rid,
            plan_id=None,
            name=body["name"],
            spec=body["spec"],
            idempotency_key=uuid.uuid4().hex,
        )
    return uuid.UUID(outcome.result["rule_id"])


async def evaluate(case, rule_id, obs, *, step_now=None, max_gap_seconds=None) -> dict:
    now = _dt(step_now) if step_now is not None else _dt(0)
    max_gap = timedelta(seconds=max_gap_seconds) if max_gap_seconds else None
    async with biz.business_transaction() as session:
        return await watch_eval.evaluate(
            session, rule_id=rule_id, obs=obs, now=now, max_gap=max_gap
        )


async def event_count(case, rule_id) -> int:
    async with biz.business_transaction() as session:
        return (
            await session.execute(
                select(func.count())
                .select_from(store.WatchEvent)
                .where(store.WatchEvent.rule_id == rule_id)
            )
        ).scalar_one()


async def observation_count(case, rule_id) -> int:
    async with biz.business_transaction() as session:
        return (
            await session.execute(
                select(func.count())
                .select_from(store.WatchObservation)
                .where(store.WatchObservation.rule_id == rule_id)
            )
        ).scalar_one()


async def test_up_cross_triggers_once(case) -> None:
    rule_id = await create_rule(case)
    assert (await evaluate(case, rule_id, make_obs("19.99", step=0)))["status"] == "watched"
    triggered = await evaluate(case, rule_id, make_obs("20.02", step=1))
    assert triggered["status"] == "triggered"
    assert triggered["reason"] == "up_cross"
    assert triggered["event_id"]
    suppressed = await evaluate(case, rule_id, make_obs("20.05", step=2))
    assert suppressed["status"] == "suppressed"
    assert suppressed["reason"] == "single_trigger_consumed"

    assert await event_count(case, rule_id) == 1
    async with biz.business_transaction() as session:
        event = (
            await session.execute(
                select(store.WatchEvent).where(store.WatchEvent.rule_id == rule_id)
            )
        ).scalar_one()
        rule = (
            await session.execute(select(store.WatchRule).where(store.WatchRule.id == rule_id))
        ).scalar_one()
    assert event.rule_version == 1
    assert event.prev_price == Decimal("19.99")
    assert event.price == Decimal("20.02")
    assert event.trigger_reason == "up_cross"
    assert event.status == "pending"
    assert rule.armed is False
    assert rule.baseline_price == Decimal("20.05")


async def test_oscillation_near_threshold_triggers_once(case) -> None:
    rule_id = await create_rule(case)
    for price, step, expect in [
        ("19.98", 0, "watched"),
        ("19.99", 1, "watched"),
        ("20.01", 2, "triggered"),  # 上穿
        ("19.99", 3, "suppressed"),
        ("20.02", 4, "suppressed"),
    ]:
        outcome = await evaluate(case, rule_id, make_obs(price, step=step))
        assert outcome["status"] == expect, (price, outcome)
    assert await event_count(case, rule_id) == 1


async def test_persistent_above_initial_met(case) -> None:
    rule_id = await create_rule(case)  # trigger_now
    first = await evaluate(case, rule_id, make_obs("21.00", step=0))
    assert first["status"] == "triggered"
    assert first["reason"] == "initial_met"
    second = await evaluate(case, rule_id, make_obs("22.00", step=1))
    assert second["status"] == "suppressed"
    assert await event_count(case, rule_id) == 1


async def test_wait_requalify_triggers_after_recross(case) -> None:
    rule_id = await create_rule(
        case,
        spec={
            "symbol": "600519.SH",
            "market": "CN",
            "currency": "CNY",
            "direction": "up",
            "threshold": "20",
            "action": "notify",
            "on_create_already_met": "wait_requalify",
            "disconnect_recovery": "wait_requalify",
        },
    )
    first = await evaluate(case, rule_id, make_obs("21.00", step=0))
    assert first["status"] == "watched"  # 已达标但等待重新穿越，不触发
    dip = await evaluate(case, rule_id, make_obs("19.00", step=1))
    assert dip["status"] == "watched"
    recross = await evaluate(case, rule_id, make_obs("21.00", step=2))
    assert recross["status"] == "triggered"
    assert recross["reason"] == "up_cross"
    assert await event_count(case, rule_id) == 1


async def test_restart_does_not_retrigger(case) -> None:
    rule_id = await create_rule(case)
    await evaluate(case, rule_id, make_obs("19.99", step=0))
    await evaluate(case, rule_id, make_obs("20.02", step=1))
    assert await event_count(case, rule_id) == 1
    # 模拟进程重启：全新会话/事务重新读取，资格已消耗，不重复触发。
    again = await evaluate(case, rule_id, make_obs("20.10", step=2))
    assert again["status"] == "suppressed"
    assert await event_count(case, rule_id) == 1


async def test_out_of_order_observation_ignored(case) -> None:
    rule_id = await create_rule(case)
    await evaluate(case, rule_id, make_obs("19.99", step=0))
    stale = await evaluate(case, rule_id, make_obs("19.90", step=-1))
    assert stale["status"] == "stale"
    assert await observation_count(case, rule_id) == 1


async def test_duplicate_observation_deduped(case) -> None:
    rule_id = await create_rule(case)
    obs = make_obs("19.99", step=0)
    assert (await evaluate(case, rule_id, obs))["status"] == "watched"
    assert (await evaluate(case, rule_id, obs))["status"] == "duplicate"
    assert await observation_count(case, rule_id) == 1


async def test_paused_and_cancelled_do_not_evaluate(case) -> None:
    rule_id = await create_rule(case)
    async with biz.business_transaction() as session:
        rule = (
            await session.execute(select(store.WatchRule).where(store.WatchRule.id == rule_id))
        ).scalar_one()
        rule.status = watch_rules.PAUSED
        await session.flush()
    outcome = await evaluate(case, rule_id, make_obs("20.50", step=0))
    assert outcome["status"] == "inactive"
    assert await observation_count(case, rule_id) == 0
    assert await event_count(case, rule_id) == 0

    async with biz.business_transaction() as session:
        rule = (
            await session.execute(select(store.WatchRule).where(store.WatchRule.id == rule_id))
        ).scalar_one()
        rule.status = watch_rules.CANCELLED
        await session.flush()
    assert (await evaluate(case, rule_id, make_obs("20.50", step=1)))["status"] == "inactive"


async def test_symbol_mismatch_not_evaluated(case) -> None:
    rule_id = await create_rule(case)
    outcome = await evaluate(
        case, rule_id, make_obs("21.00", step=0, symbol="000001.SZ", market="CN")
    )
    assert outcome["status"] == "mismatch"
    assert await observation_count(case, rule_id) == 0


async def test_recovered_met_after_gap(case) -> None:
    rule_id = await create_rule(case)  # disconnect_recovery=trigger_once
    await evaluate(case, rule_id, make_obs("19.00", step=0), step_now=0)
    # 断线缺口：下次观测已超过 max_gap，恢复后首个报价已达标。
    outcome = await evaluate(
        case, rule_id, make_obs("21.00", step=20), step_now=20, max_gap_seconds=300
    )
    assert outcome["status"] == "triggered"
    assert outcome["reason"] == "recovered_met"
    assert await event_count(case, rule_id) == 1
    async with biz.business_transaction() as session:
        event = (
            await session.execute(
                select(store.WatchEvent).where(store.WatchEvent.rule_id == rule_id)
            )
        ).scalar_one()
    assert event.detail_json.get("gap") is True


async def test_recovered_wait_requalify_no_gap_retrigger(case) -> None:
    rule_id = await create_rule(
        case,
        spec={
            "symbol": "600519.SH",
            "market": "CN",
            "currency": "CNY",
            "direction": "up",
            "threshold": "20",
            "action": "notify",
            "on_create_already_met": "trigger_now",
            "disconnect_recovery": "wait_requalify",
        },
    )
    await evaluate(case, rule_id, make_obs("19.00", step=0), step_now=0)
    outcome = await evaluate(
        case, rule_id, make_obs("21.00", step=20), step_now=20, max_gap_seconds=300
    )
    assert outcome["status"] == "watched"  # 不补发，等待新的有效穿越
    assert await event_count(case, rule_id) == 0
    dip = await evaluate(case, rule_id, make_obs("19.00", step=21), step_now=21)
    assert dip["status"] == "watched"
    recross = await evaluate(case, rule_id, make_obs("21.00", step=22), step_now=22)
    assert recross["status"] == "triggered"
    assert recross["reason"] == "up_cross"


async def test_edit_resets_qualification(case) -> None:
    rule_id = await create_rule(case)
    await evaluate(case, rule_id, make_obs("19.99", step=0))
    await evaluate(case, rule_id, make_obs("20.02", step=1))
    assert await event_count(case, rule_id) == 1
    # 改版（新版本）重新布防：阈值改为 22，资格复位。
    async with biz.business_transaction() as session:
        await watch_rules.update_rule(
            session,
            user_id=case.uid,
            rule_id=rule_id,
            expected_version=1,
            patch={"threshold": "22"},
            idempotency_key=uuid.uuid4().hex,
        )
    below = await evaluate(case, rule_id, make_obs("21.00", step=2))
    assert below["status"] == "watched"
    crossed = await evaluate(case, rule_id, make_obs("22.50", step=3))
    assert crossed["status"] == "triggered"
    assert crossed["reason"] == "up_cross"
    # 一个规则两个版本各一次触发：事件唯一约束按 (rule_id, rule_version)。
    assert await event_count(case, rule_id) == 2


async def test_concurrent_evaluation_consumes_once(case) -> None:
    rule_id = await create_rule(case)
    await evaluate(case, rule_id, make_obs("19.99", step=0))
    obs = make_obs("20.02", step=1)

    async def run() -> str:
        async with biz.business_transaction() as session:
            return (
                await watch_eval.evaluate(
                    session, rule_id=rule_id, obs=obs, now=_dt(1), max_gap=None
                )
            )["status"]

    results = await asyncio.gather(run(), run(), run())
    # 并发判定只消耗一次资格：唯一触发者建事件；其余为 duplicate（同观测已入库）
    # 或 suppressed（资格已被消耗），均不重复建事件。
    assert results.count("triggered") == 1
    assert all(status in {"suppressed", "duplicate"} for status in results[1:])
    assert await event_count(case, rule_id) == 1


async def test_observation_preserves_precision_and_time_source(case) -> None:
    rule_id = await create_rule(case)
    obs = make_obs("19.99", step=0, time_source="unknown", precision_limited=True)
    await evaluate(case, rule_id, obs)
    async with biz.business_transaction() as session:
        row = (
            await session.execute(
                select(store.WatchObservation).where(store.WatchObservation.rule_id == rule_id)
            )
        ).scalar_one()
    assert row.price == Decimal("19.99")
    assert row.observed_at_ms is None
    assert row.time_source == "unknown"
    assert row.precision_limited is True
    assert row.received_at_ms == _ms(0)


async def test_expired_rule_does_not_trigger(case) -> None:
    rule_id = await create_rule(
        case,
        spec={
            "symbol": "600519.SH",
            "market": "CN",
            "currency": "CNY",
            "direction": "up",
            "threshold": "20",
            "action": "notify",
            "on_create_already_met": "trigger_now",
            "disconnect_recovery": "trigger_once",
            "expires_at": "2020-01-01T00:00:00Z",
        },
    )
    outcome = await evaluate(case, rule_id, make_obs("21.00", step=0))
    assert outcome["status"] == "expired"
    assert await observation_count(case, rule_id) == 0
    assert await event_count(case, rule_id) == 0


async def test_down_cross(case) -> None:
    rule_id = await create_rule(
        case,
        spec={
            "symbol": "600519.SH",
            "market": "CN",
            "currency": "CNY",
            "direction": "down",
            "threshold": "18",
            "action": "notify",
            "on_create_already_met": "trigger_now",
            "disconnect_recovery": "trigger_once",
        },
    )
    await evaluate(case, rule_id, make_obs("18.50", step=0))
    crossed = await evaluate(case, rule_id, make_obs("17.90", step=1))
    assert crossed["status"] == "triggered"
    assert crossed["reason"] == "down_cross"


async def test_enter_range(case) -> None:
    rule_id = await create_rule(
        case,
        spec={
            "symbol": "600519.SH",
            "market": "CN",
            "currency": "CNY",
            "direction": "range",
            "threshold": {"low": "18", "high": "20"},
            "action": "notify",
            "on_create_already_met": "trigger_now",
            "disconnect_recovery": "trigger_once",
        },
    )
    await evaluate(case, rule_id, make_obs("17.00", step=0))
    entered = await evaluate(case, rule_id, make_obs("19.00", step=1))
    assert entered["status"] == "triggered"
    assert entered["reason"] == "enter_range"


def test_monitor_chain_has_no_llm_import() -> None:
    # 监控链（判定 + 轮询）不 import 框架内核 / LLM 客户端：监控本身零模型调用。
    for module in (watch_eval, __import__("server.monitor", fromlist=["monitor"])):
        source = inspect.getsource(module)
        lowered = source.lower()
        assert "frontier_agent" not in lowered
        assert "openai" not in lowered
        assert "anthropic" not in lowered
