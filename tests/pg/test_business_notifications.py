"""DATA-12 验收：业务事件与通知在真实 PostgreSQL 上的契约行为。

覆盖：触发/排队/结果/错误/预算/规则失效通知完整且去重；最近未读优先视图；按等级/类型/已读
过滤；已读与隐藏幂等且不改变业务事实（游标重放仍可见）；阅读进度；通知设置读写；所有者隔离；
SSE 游标重放 + 长期存活（live tail）。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from server import business_events, store, watch_eval, watch_rules, watch_scheduler
from server import business_service as biz
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
        session.add(store.User(id=uid, username=f"ntf-{uid.hex}", password_hash="x"))
        await session.flush()
        session.add(store.Session(id=rid, user_id=uid, title="ntf research"))
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
                "plan_price": "19.90",
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
        transport=httpx.ASGITransport(app=app), base_url="http://ntf.test"
    ) as client:
        yield SimpleNamespace(
            uid=uid,
            rid=rid,
            client=client,
            headers={"Authorization": f"Bearer {create_access_token(uid)}"},
        )


async def create_rule(case, *, action="auto_analyze", **extra) -> uuid.UUID:
    spec = {
        "symbol": "600519.SH",
        "market": "CN",
        "currency": "CNY",
        "direction": "up",
        "threshold": "20",
        "action": action,
        "task": "触发后分析",
        "on_create_already_met": "trigger_now",
        "disconnect_recovery": "trigger_once",
        **extra,
    }
    async with biz.business_transaction() as session:
        outcome = await watch_rules.create_rule(
            session,
            user_id=case.uid,
            research_id=case.rid,
            plan_id=None,
            name="监控规则",
            spec=spec,
            idempotency_key=uuid.uuid4().hex,
        )
    return uuid.UUID(outcome.result["rule_id"])


async def trigger(case, rule_id) -> uuid.UUID:
    async with biz.business_transaction() as session:
        await watch_eval.evaluate(
            session, rule_id=rule_id, obs=make_obs("19.99", step=0), now=_dt(0)
        )
    async with biz.business_transaction() as session:
        outcome = await watch_eval.evaluate(
            session, rule_id=rule_id, obs=make_obs("20.02", step=1), now=_dt(1)
        )
    return uuid.UUID(outcome["event_id"])


async def notify_count(case, kind: str) -> int:
    async with biz.business_transaction() as session:
        rows = (
            (
                await session.execute(
                    select(store.BusinessEvent).where(
                        store.BusinessEvent.user_id == case.uid,
                        store.BusinessEvent.kind == kind,
                    )
                )
            )
            .scalars()
            .all()
        )
        return len(list(rows))


async def test_trigger_and_analysis_lifecycle_notifications(case) -> None:
    rule_id = await create_rule(case)
    event_id = await trigger(case, rule_id)
    # 触发通知（DATA-10 侧，dedup by 事件身份）。
    assert await notify_count(case, "watch_triggered") == 1
    # 排队通知（DATA-11 侧）。
    async with biz.business_transaction() as session:
        await watch_scheduler.schedule_event(session, event_id=event_id, now=_dt(2))
    assert await notify_count(case, "auto_analysis_queued") == 1
    # 结果通知（终态对账，完成/失败共用终态去重键）。
    async with biz.business_transaction() as session:
        run = (
            await session.execute(select(store.Run).where(store.Run.session_id == case.rid))
        ).scalar_one()
        run.status = "completed"
        await session.flush()
        await watch_scheduler.reconcile_event_runs(session, limit=10, now=_dt(3))
    assert await notify_count(case, "watch_analysis_completed") == 1
    assert await notify_count(case, "watch_analysis_failed") == 0


async def test_analysis_failure_notification(case) -> None:
    rule_id = await create_rule(case)
    event_id = await trigger(case, rule_id)
    async with biz.business_transaction() as session:
        await watch_scheduler.schedule_event(session, event_id=event_id, now=_dt(2))
    async with biz.business_transaction() as session:
        run = (
            await session.execute(select(store.Run).where(store.Run.session_id == case.rid))
        ).scalar_one()
        run.status = "failed"
        await session.flush()
        await watch_scheduler.reconcile_event_runs(session, limit=10, now=_dt(3))
    assert await notify_count(case, "watch_analysis_failed") == 1
    # 终态去重：重复对账不重复通知。
    async with biz.business_transaction() as session:
        await watch_scheduler.reconcile_event_runs(session, limit=10, now=_dt(4))
    assert await notify_count(case, "watch_analysis_failed") == 1


async def test_notify_rule_only_trigger_notification(case) -> None:
    rule_id = await create_rule(case, action="notify")
    event_id = await trigger(case, rule_id)
    assert await notify_count(case, "watch_triggered") == 1
    async with biz.business_transaction() as session:
        await watch_scheduler.schedule_event(session, event_id=event_id, now=_dt(2))
    assert await notify_count(case, "auto_analysis_queued") == 0


async def test_budget_blocked_notification(case) -> None:
    rule_id = await create_rule(case, budget={"max_runs": 1})
    event_id = await trigger(case, rule_id)
    async with biz.business_transaction() as session:
        session.add(
            store.WatchBudgetUsage(
                rule_id=rule_id,
                rule_version=1,
                user_id=case.uid,
                runs_created=1,
                runs_attempted=1,
            )
        )
        await session.flush()
    async with biz.business_transaction() as session:
        outcome = await watch_scheduler.schedule_event(session, event_id=event_id, now=_dt(2))
    assert outcome["status"] == "blocked_budget"
    assert await notify_count(case, "watch_budget_blocked") == 1


async def test_rule_inactive_notification(case) -> None:
    rule_id = await create_rule(case)
    event_id = await trigger(case, rule_id)
    async with biz.business_transaction() as session:
        await watch_rules.update_rule(
            session,
            user_id=case.uid,
            rule_id=rule_id,
            expected_version=1,
            patch={"threshold": "22"},
            idempotency_key=uuid.uuid4().hex,
        )
    async with biz.business_transaction() as session:
        outcome = await watch_scheduler.schedule_event(session, event_id=event_id, now=_dt(2))
    assert outcome["status"] == "expired"
    assert await notify_count(case, "watch_rule_inactive") == 1


async def test_dedup_same_trigger_once(case) -> None:
    async with biz.business_transaction() as session:
        first = await business_events.add_event(
            session,
            user_id=case.uid,
            research_id=case.rid,
            kind="watch_triggered",
            title="t",
            summary="s",
            dedup_key="watch_trigger:dup-1",
        )
        second = await business_events.add_event(
            session,
            user_id=case.uid,
            research_id=case.rid,
            kind="watch_triggered",
            title="t2",
            summary="s2",
            dedup_key="watch_trigger:dup-1",
        )
    assert second.id == first.id
    assert await notify_count(case, "watch_triggered") == 1


async def test_recent_unread_first_view(case) -> None:
    kinds = ["watch_triggered", "watch_budget_blocked", "watch_rule_inactive"]
    async with biz.business_transaction() as session:
        for i, kind in enumerate(kinds):
            await business_events.add_event(
                session,
                user_id=case.uid,
                research_id=case.rid,
                kind=kind,
                title=f"t{i}",
                summary="s",
                level="high" if kind == "watch_budget_blocked" else "low",
            )
    # 标记第一条已读：未读优先应排在最前。
    async with biz.business_transaction() as session:
        rows = (
            (
                await session.execute(
                    select(store.BusinessEvent).where(store.BusinessEvent.user_id == case.uid)
                )
            )
            .scalars()
            .all()
        )
        await business_events.mark_read(session, user_id=case.uid, event_id=rows[0].id)
    response = await case.client.get("/api/business/notifications", headers=case.headers)
    body = response.json()
    assert response.status_code == 200, response.text
    assert body["total"] == 3
    assert body["unread_count"] == 2
    assert body["read_progress"] == rows[0].cursor
    # 未读优先：前两条未读（cursor 降序），已读的最后。
    assert body["items"][0]["read"] is False
    assert body["items"][1]["read"] is False
    assert body["items"][2]["read"] is True
    # 排序：未读在前且按 cursor 降序，已读殿后。
    cursors = [item["cursor"] for item in body["items"]]
    assert cursors == sorted(cursors, reverse=True)


async def test_notification_filters(case) -> None:
    async with biz.business_transaction() as session:
        await business_events.add_event(
            session,
            user_id=case.uid,
            research_id=case.rid,
            kind="watch_triggered",
            title="t",
            summary="s",
            level="medium",
        )
        await business_events.add_event(
            session,
            user_id=case.uid,
            research_id=case.rid,
            kind="watch_budget_blocked",
            title="b",
            summary="s",
            level="high",
        )
    by_level = await case.client.get(
        "/api/business/notifications", params={"level": ["high"]}, headers=case.headers
    )
    assert by_level.json()["total"] == 1
    assert by_level.json()["items"][0]["kind"] == "watch_budget_blocked"
    by_kind = await case.client.get(
        "/api/business/notifications", params={"kind": ["watch_triggered"]}, headers=case.headers
    )
    assert by_kind.json()["total"] == 1
    by_read = await case.client.get(
        "/api/business/notifications", params={"read": "false"}, headers=case.headers
    )
    assert by_read.json()["total"] == 2
    bad_level = await case.client.get(
        "/api/business/notifications", params={"level": ["urgent", "bogus"]}, headers=case.headers
    )
    assert bad_level.status_code == 400
    assert bad_level.json()["error"]["code"] == "validation_error"


async def test_hide_is_view_only(case) -> None:
    async with biz.business_transaction() as session:
        row = await business_events.add_event(
            session,
            user_id=case.uid,
            research_id=case.rid,
            kind="watch_triggered",
            title="t",
            summary="s",
        )
        event_id = row.id
    listed = await case.client.get("/api/business/notifications", headers=case.headers)
    assert listed.json()["total"] == 1
    hidden = await case.client.post(
        f"/api/business/notifications/{event_id}/hide", headers=case.headers
    )
    assert hidden.status_code == 204
    after = await case.client.get("/api/business/notifications", headers=case.headers)
    assert after.json()["total"] == 0
    # 业务事实仍在：游标重放仍可见。
    replayed = await case.client.get("/api/business/events", headers=case.headers)
    assert replayed.json()["items"][0]["id"] == str(event_id)


async def test_read_idempotent_and_progress(case) -> None:
    async with biz.business_transaction() as session:
        first = await business_events.add_event(
            session,
            user_id=case.uid,
            research_id=case.rid,
            kind="watch_triggered",
            title="a",
            summary="s",
        )
        second = await business_events.add_event(
            session,
            user_id=case.uid,
            research_id=case.rid,
            kind="watch_triggered",
            title="b",
            summary="s",
        )
    one = await case.client.post(f"/api/business/events/{first.id}/read", headers=case.headers)
    assert one.status_code == 204
    again = await case.client.post(f"/api/business/events/{first.id}/read", headers=case.headers)
    assert again.status_code == 204
    progress = await case.client.get("/api/business/events/read-progress", headers=case.headers)
    assert progress.json()["read_progress"] == first.cursor
    all_read = await case.client.post(
        "/api/business/events/read-all", json={"through": second.cursor}, headers=case.headers
    )
    assert all_read.status_code == 204
    progress = await case.client.get("/api/business/events/read-progress", headers=case.headers)
    assert progress.json()["read_progress"] == second.cursor


async def test_settings_roundtrip(case) -> None:
    default = await case.client.get("/api/business/notifications/settings", headers=case.headers)
    assert default.json() == {"muted_kinds": [], "muted_levels": []}
    updated = await case.client.put(
        "/api/business/notifications/settings",
        json={"muted_kinds": ["watch_rule_inactive"], "muted_levels": ["low"]},
        headers=case.headers,
    )
    assert updated.status_code == 200
    assert updated.json() == {"muted_kinds": ["watch_rule_inactive"], "muted_levels": ["low"]}
    bad = await case.client.put(
        "/api/business/notifications/settings",
        json={"muted_kinds": [], "muted_levels": ["critical"]},
        headers=case.headers,
    )
    assert bad.status_code == 400
    refetched = await case.client.get("/api/business/notifications/settings", headers=case.headers)
    assert refetched.json() == {"muted_kinds": ["watch_rule_inactive"], "muted_levels": ["low"]}


async def test_notifications_owner_isolation(case) -> None:
    async with biz.business_transaction() as session:
        await business_events.add_event(
            session,
            user_id=case.uid,
            research_id=case.rid,
            kind="watch_triggered",
            title="t",
            summary="s",
        )
    other = uuid.uuid4()
    async with biz.business_transaction() as session:
        session.add(store.User(id=other, username=f"ntf-other-{other.hex}", password_hash="x"))
        await session.flush()
    other_headers = {"Authorization": f"Bearer {create_access_token(other)}"}
    response = await case.client.get("/api/business/notifications", headers=other_headers)
    assert response.json()["total"] == 0
    hidden = await case.client.post(
        "/api/business/notifications/00000000-0000-0000-0000-000000000000/hide",
        headers=other_headers,
    )
    assert hidden.status_code == 404


async def test_events_stream_replays_then_tails(case) -> None:
    # SSE 生成器（长期存活进程）：游标重放已提交事件，之后轮询等待新事件，可取消。
    # 注：httpx ASGITransport 会缓冲完整响应，无法对无限流做 HTTP 端到端断言；
    # 因此直接消费生成器验证语义（路由仅做 request.is_disconnected 的薄包装）。
    async with biz.business_transaction() as session:
        await business_events.add_event(
            session,
            user_id=case.uid,
            research_id=case.rid,
            kind="watch_triggered",
            title="seed",
            summary="seed",
        )
    stream = business_events.stream_events(case.uid, 0, poll_seconds=0.05)
    seed_chunk = await asyncio.wait_for(stream.__anext__(), timeout=5)
    assert "event: business_event" in seed_chunk
    assert '"kind":"watch_triggered"' in seed_chunk

    # 流保持打开期间插入第二条事件：live tail 应投递，且不重复。
    async with biz.business_transaction() as session:
        await business_events.add_event(
            session,
            user_id=case.uid,
            research_id=case.rid,
            kind="watch_budget_blocked",
            title="tail",
            summary="tail",
        )
    tail_chunk = await asyncio.wait_for(stream.__anext__(), timeout=5)
    assert '"kind":"watch_budget_blocked"' in tail_chunk
    # 可取消：aclose 终止长期存活生成器。
    await stream.aclose()
