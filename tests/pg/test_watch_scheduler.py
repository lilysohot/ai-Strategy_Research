"""DATA-11 验收：事件→自动 Run 调度、合并与预算在真实 PostgreSQL 上的契约行为。

验证：触发后无需再点确认即可建自动 Run（快照按执行时最新版本冻结、source=watch_event，
与手动提交同 outbox 派发）；事件→Run 幂等（每事件每代次唯一）；缺业务字段转 DATA-07 补数
（needs_input）；预算 max_runs 达限 blocked_budget 且不建 Run；规则改版/暂停使旧版未启动事件
失效（expired）；同研究同标的同意图待派发事件合并；Run 终态对账 completed/failed；事件查询
所有者隔离。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select

from server import business_service as biz
from server import store, watch_eval, watch_rules, watch_scheduler
from server.app import app
from server.security import create_access_token

pytestmark = pytest.mark.pg

BASE_MS = 1730000000000
STEP_MS = 60_000


def _ms(step: int) -> int:
    return BASE_MS + step * STEP_MS


def _dt(step: int) -> datetime:
    return datetime.fromtimestamp(_ms(step) / 1000, UTC)


def make_obs(price, *, step: int) -> watch_eval.MonitoringObservation:
    return watch_eval.MonitoringObservation(
        thscode="600519.SH",
        market="CN",
        currency="CNY",
        price=Decimal(str(price)),
        received_at_ms=_ms(step),
        observed_at_ms=_ms(step),
    )


@pytest.fixture
async def case(pg_clean):
    uid, rid = uuid.uuid4(), uuid.uuid4()
    async with biz.business_transaction() as session:
        session.add(store.User(id=uid, username=f"sched-{uid.hex}", password_hash="x"))
        await session.flush()
        session.add(store.Session(id=rid, user_id=uid, title="sched research"))
        await session.flush()
        account = await biz.create_account(
            session,
            user_id=uid,
            name="主账户",
            base_currency="CNY",
            declared={
                "total_capital": "100000",
                "capital_basis": "total",
                "currency": "CNY",
                "as_of": "2026-10-03T00:00:00Z",
            },
            idempotency_key=uuid.uuid4().hex,
        )
        plan = await biz.create_plan(
            session,
            user_id=uid,
            research_id=rid,
            name="计划",
            declared={
                "symbol": "600519.SH",
                "market": "CN",
                "direction": "buy",
                "allocated_capital": "10000",
                "target_price": "24.00",
                "currency": "CNY",
            },
            idempotency_key=uuid.uuid4().hex,
        )
        await biz.set_research_link(
            session,
            user_id=uid,
            research_id=rid,
            account_id=uuid.UUID(account.result["account_id"]),
            primary_plan_id=uuid.UUID(plan.result["plan_id"]),
            idempotency_key=uuid.uuid4().hex,
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://sched.test"
    ) as client:
        yield SimpleNamespace(
            uid=uid,
            rid=rid,
            aid=uuid.UUID(account.result["account_id"]),
            pid=uuid.UUID(plan.result["plan_id"]),
            client=client,
            headers={"Authorization": f"Bearer {create_access_token(uid)}"},
        )


async def create_rule(case, *, spec=None) -> uuid.UUID:
    body = (
        spec
        if spec is not None
        else {
            "symbol": "600519.SH",
            "market": "CN",
            "currency": "CNY",
            "direction": "up",
            "threshold": "20",
            "action": "auto_analyze",
            "task": "触发后按当前计划给出仓位建议",
            "budget": {"max_runs": 5},
            "on_create_already_met": "trigger_now",
            "disconnect_recovery": "trigger_once",
        }
    )
    async with biz.business_transaction() as session:
        outcome = await watch_rules.create_rule(
            session,
            user_id=case.uid,
            research_id=case.rid,
            plan_id=None,
            name="监控规则",
            spec=body,
            idempotency_key=uuid.uuid4().hex,
        )
    return uuid.UUID(outcome.result["rule_id"])


async def trigger_event(case, rule_id: uuid.UUID) -> uuid.UUID:
    """19.99 → 20.02 上穿触发，返回事件 id。"""
    async with biz.business_transaction() as session:
        await watch_eval.evaluate(
            session, rule_id=rule_id, obs=make_obs("19.99", step=0), now=_dt(0)
        )
    async with biz.business_transaction() as session:
        outcome = await watch_eval.evaluate(
            session, rule_id=rule_id, obs=make_obs("20.02", step=1), now=_dt(1)
        )
    assert outcome["status"] == "triggered"
    return uuid.UUID(outcome["event_id"])


async def run_count(case, research_id=None) -> int:
    async with biz.business_transaction() as session:
        stmt = select(func.count()).select_from(store.Run)
        if research_id is not None:
            stmt = stmt.where(store.Run.session_id == research_id)
        return (await session.execute(stmt)).scalar_one()


async def schedule(case, event_id) -> dict:
    async with biz.business_transaction() as session:
        return await watch_scheduler.schedule_event(session, event_id=event_id, now=_dt(2))


async def get_event(case, event_id) -> store.WatchEvent:
    async with biz.business_transaction() as session:
        return (
            await session.execute(select(store.WatchEvent).where(store.WatchEvent.id == event_id))
        ).scalar_one()


async def test_trigger_schedules_auto_run(case) -> None:
    rule_id = await create_rule(case)
    event_id = await trigger_event(case, rule_id)
    assert await run_count(case) == 0

    outcome = await schedule(case, event_id)
    assert outcome["status"] == "dispatching"
    assert outcome["run_id"]
    assert await run_count(case) == 1

    async with biz.business_transaction() as session:
        event = (
            await session.execute(select(store.WatchEvent).where(store.WatchEvent.id == event_id))
        ).scalar_one()
        snap = (
            await session.execute(
                select(store.RunInvestmentSnapshot).where(
                    store.RunInvestmentSnapshot.run_id == uuid.UUID(outcome["run_id"])
                )
            )
        ).scalar_one()
        dispatch = (
            await session.execute(
                select(store.RunDispatch).where(
                    store.RunDispatch.run_id == uuid.UUID(outcome["run_id"])
                )
            )
        ).scalar_one()
        usage = (
            await session.execute(
                select(store.WatchBudgetUsage).where(
                    store.WatchBudgetUsage.rule_id == rule_id,
                    store.WatchBudgetUsage.rule_version == 1,
                )
            )
        ).scalar_one()
    assert event.status == "dispatching"
    assert event.run_id == uuid.UUID(outcome["run_id"])
    # 快照按执行时最新版本冻结，来源 watch_event（与手动提交 source=manual 分开）。
    assert snap.source == "watch_event"
    assert snap.account_id == case.aid
    assert snap.plan_id == case.pid
    assert Decimal(str(snap.resolved_json["account.total_capital"]["value"])) == Decimal("100000")
    assert Decimal(str(snap.resolved_json["total_capital"]["value"])) == Decimal("100000")
    assert dispatch.status == "pending"
    assert usage.runs_created == 1
    assert usage.runs_attempted == 1


async def test_schedule_is_idempotent_per_event(case) -> None:
    rule_id = await create_rule(case)
    event_id = await trigger_event(case, rule_id)
    first = await schedule(case, event_id)
    second = await schedule(case, event_id)
    assert second["status"] == "dispatching"
    assert second["replayed"] is True
    assert second["run_id"] == first["run_id"]
    assert await run_count(case) == 1


async def test_missing_fields_route_to_input_request(case) -> None:
    # 不绑定完整账户/计划：主计划账户缺资金时自动事件转补数。
    uid2, rid2 = uuid.uuid4(), uuid.uuid4()
    async with biz.business_transaction() as session:
        session.add(store.User(id=uid2, username=f"sched2-{uid2.hex}", password_hash="x"))
        await session.flush()
        session.add(store.Session(id=rid2, user_id=uid2, title="sched2 research"))
        await session.flush()
        account = await biz.create_account(
            session,
            user_id=uid2,
            name="空账户",
            base_currency="CNY",
            declared={"currency": "CNY"},
            allow_incomplete=True,
            idempotency_key=uuid.uuid4().hex,
        )
        plan = await biz.create_plan(
            session,
            user_id=uid2,
            research_id=rid2,
            name="计划",
            declared={
                "symbol": "600519.SH",
                "market": "CN",
                "direction": "buy",
                "allocated_capital": "10000",
                "target_price": "24.00",
                "currency": "CNY",
            },
            idempotency_key=uuid.uuid4().hex,
        )
        await biz.set_research_link(
            session,
            user_id=uid2,
            research_id=rid2,
            account_id=uuid.UUID(account.result["account_id"]),
            primary_plan_id=uuid.UUID(plan.result["plan_id"]),
            idempotency_key=uuid.uuid4().hex,
        )
        rule = await watch_rules.create_rule(
            session,
            user_id=uid2,
            research_id=rid2,
            plan_id=None,
            name="规则",
            spec={
                "symbol": "600519.SH",
                "market": "CN",
                "currency": "CNY",
                "direction": "up",
                "threshold": "20",
                "action": "auto_analyze",
                "task": "分析",
                "on_create_already_met": "trigger_now",
                "disconnect_recovery": "trigger_once",
            },
            idempotency_key=uuid.uuid4().hex,
        )
    rule_id = uuid.UUID(rule.result["rule_id"])
    async with biz.business_transaction() as session:
        await watch_eval.evaluate(
            session, rule_id=rule_id, obs=make_obs("19.99", step=0), now=_dt(0)
        )
    async with biz.business_transaction() as session:
        outcome = await watch_eval.evaluate(
            session, rule_id=rule_id, obs=make_obs("20.02", step=1), now=_dt(1)
        )
    event_id = uuid.UUID(outcome["event_id"])
    async with biz.business_transaction() as session:
        result = await watch_scheduler.schedule_event(session, event_id=event_id, now=_dt(2))
    assert result["status"] == "needs_input"
    assert any("account.total_capital" in key for key in result["fields"])
    async with biz.business_transaction() as session:
        event = (
            await session.execute(select(store.WatchEvent).where(store.WatchEvent.id == event_id))
        ).scalar_one()
        request = (
            await session.execute(
                select(store.InputRequest).where(store.InputRequest.watch_event_id == event_id)
            )
        ).scalar_one_or_none()
    assert event.status == "needs_input"
    assert request is not None
    assert request.source_run_id is None
    names = {field["name"] for field in request.fields_json}
    assert "account.total_capital" in names


async def test_budget_max_runs_blocks_event(case) -> None:
    rule_id = await create_rule(
        case,
        spec={
            "symbol": "600519.SH",
            "market": "CN",
            "currency": "CNY",
            "direction": "up",
            "threshold": "20",
            "action": "auto_analyze",
            "task": "分析",
            "budget": {"max_runs": 1},
            "on_create_already_met": "trigger_now",
            "disconnect_recovery": "trigger_once",
        },
    )
    event_id = await trigger_event(case, rule_id)
    # 模拟预算已被占用：同一规则版本已有一次分析（repeat 模式或历史）。
    async with biz.business_transaction() as session:
        usage = store.WatchBudgetUsage(
            rule_id=rule_id,
            rule_version=1,
            user_id=case.uid,
            runs_created=1,
            runs_attempted=1,
        )
        session.add(usage)
        await session.flush()
    outcome = await schedule(case, event_id)
    assert outcome["status"] == "blocked_budget"
    assert outcome["reason"] == "max_runs_exceeded"
    assert await run_count(case) == 0
    async with biz.business_transaction() as session:
        event = (
            await session.execute(select(store.WatchEvent).where(store.WatchEvent.id == event_id))
        ).scalar_one()
    assert event.status == "blocked_budget"
    assert event.budget_reason == "max_runs_exceeded"


async def test_rule_edit_invalidates_pending_event(case) -> None:
    rule_id = await create_rule(case)
    event_id = await trigger_event(case, rule_id)
    async with biz.business_transaction() as session:
        await watch_rules.update_rule(
            session,
            user_id=case.uid,
            rule_id=rule_id,
            expected_version=1,
            patch={"threshold": "22"},
            idempotency_key=uuid.uuid4().hex,
        )
    outcome = await schedule(case, event_id)
    assert outcome["status"] == "expired"
    assert outcome["reason"] == "rule_obsoleted"
    assert await run_count(case) == 0
    async with biz.business_transaction() as session:
        event = (
            await session.execute(select(store.WatchEvent).where(store.WatchEvent.id == event_id))
        ).scalar_one()
    assert event.status == "expired"
    assert event.detail_json.get("expire_reason") == "rule_obsoleted"


async def test_rule_pause_invalidates_pending_event(case) -> None:
    rule_id = await create_rule(case)
    event_id = await trigger_event(case, rule_id)
    async with biz.business_transaction() as session:
        rule = (
            await session.execute(select(store.WatchRule).where(store.WatchRule.id == rule_id))
        ).scalar_one()
        rule.status = watch_rules.PAUSED
        await session.flush()
    outcome = await schedule(case, event_id)
    assert outcome["status"] == "expired"
    assert outcome["reason"] == "rule_inactive"


async def test_pending_events_merge(case) -> None:
    rule_a = await create_rule(
        case,
        spec={
            "symbol": "600519.SH",
            "market": "CN",
            "currency": "CNY",
            "direction": "up",
            "threshold": "20",
            "action": "auto_analyze",
            "task": "任务A",
            "on_create_already_met": "trigger_now",
            "disconnect_recovery": "trigger_once",
        },
    )
    rule_b = await create_rule(
        case,
        spec={
            "symbol": "600519.SH",
            "market": "CN",
            "currency": "CNY",
            "direction": "up",
            "threshold": "25",
            "action": "auto_analyze",
            "task": "任务B",
            "on_create_already_met": "trigger_now",
            "disconnect_recovery": "trigger_once",
        },
    )
    event_a = await trigger_event(case, rule_a)
    # 规则 B 用不同时序触发（避免与 A 同观测去重）。
    async with biz.business_transaction() as session:
        await watch_eval.evaluate(
            session,
            rule_id=rule_b,
            obs=watch_eval.MonitoringObservation(
                thscode="600519.SH",
                market="CN",
                currency="CNY",
                price=Decimal("24.90"),
                received_at_ms=_ms(3),
                observed_at_ms=_ms(3),
            ),
            now=_dt(3),
        )
    async with biz.business_transaction() as session:
        out = await watch_eval.evaluate(
            session,
            rule_id=rule_b,
            obs=watch_eval.MonitoringObservation(
                thscode="600519.SH",
                market="CN",
                currency="CNY",
                price=Decimal("25.02"),
                received_at_ms=_ms(4),
                observed_at_ms=_ms(4),
            ),
            now=_dt(4),
        )
    event_b = uuid.UUID(out["event_id"])

    async with biz.business_transaction() as session:
        counters = await watch_scheduler.schedule_cycle(session, limit=10, now=_dt(5))
    assert counters["merged"] == 1
    assert await run_count(case) == 1

    async with biz.business_transaction() as session:
        lead = (
            await session.execute(select(store.WatchEvent).where(store.WatchEvent.id == event_a))
        ).scalar_one()
        merged = (
            await session.execute(select(store.WatchEvent).where(store.WatchEvent.id == event_b))
        ).scalar_one()
    assert lead.status == "dispatching"
    assert lead.run_id is not None
    assert merged.status == "merged"
    assert merged.merged_into_id == event_a
    assert merged.detail_json.get("merged_into") == str(event_a)


async def test_run_terminal_reconciles_event(case) -> None:
    rule_id = await create_rule(case)
    event_id = await trigger_event(case, rule_id)
    outcome = await schedule(case, event_id)
    run_id = uuid.UUID(outcome["run_id"])
    async with biz.business_transaction() as session:
        run = (await session.execute(select(store.Run).where(store.Run.id == run_id))).scalar_one()
        run.status = "completed"
        await session.flush()
    async with biz.business_transaction() as session:
        changed = await watch_scheduler.reconcile_event_runs(session, limit=10, now=_dt(6))
    assert changed == 1
    async with biz.business_transaction() as session:
        event = (
            await session.execute(select(store.WatchEvent).where(store.WatchEvent.id == event_id))
        ).scalar_one()
    assert event.status == "completed"
    assert event.completed_at is not None


async def test_notify_rule_does_not_create_run(case) -> None:
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
        },
    )
    event_id = await trigger_event(case, rule_id)
    outcome = await schedule(case, event_id)
    assert outcome["status"] == "completed"
    assert outcome["notify_only"] is True
    assert await run_count(case) == 0
    async with biz.business_transaction() as session:
        event = (
            await session.execute(select(store.WatchEvent).where(store.WatchEvent.id == event_id))
        ).scalar_one()
    assert event.status == "completed"
    assert event.detail_json.get("notify_only") is True
    assert event.run_id is None


async def test_events_owner_isolation(case) -> None:
    rule_id = await create_rule(case)
    event_id = await trigger_event(case, rule_id)
    other = uuid.uuid4()
    async with biz.business_transaction() as session:
        session.add(store.User(id=other, username=f"sched-other-{other.hex}", password_hash="x"))
        await session.flush()
    other_headers = {"Authorization": f"Bearer {create_access_token(other)}"}
    response = await case.client.get("/api/business/watch-events", headers=other_headers)
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 0
    mine = await case.client.get("/api/business/watch-events", headers=case.headers)
    assert mine.json()["total"] == 1
    assert mine.json()["events"][0]["id"] == str(event_id)
    by_status = await case.client.get(
        "/api/business/watch-events?status=pending", headers=case.headers
    )
    assert by_status.json()["total"] == 1
