"""DATA-13 验收：归档、删除与取消联动在真实 PostgreSQL 上的契约行为。

覆盖：账户/计划归档幂等且暂停相关监控规则；归档对象不能成为新分析有效选择；删除研究级联
（规则取消、事件过期、补数取消、outbox 作废、计划归档、会话软删除）；共享账户不随单一研究
删除（AC-17）；重复删除幂等；通知/快照/已建 Run 引用已删除对象不崩溃且可定位。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from server import business_service as biz
from server import (
    dispatch_outbox,
    input_requests,
    investment_snapshot,
    store,
    watch_eval,
    watch_rules,
    watch_scheduler,
)
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
    uid, rid_a, rid_b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with biz.business_transaction() as session:
        session.add(store.User(id=uid, username=f"arc-{uid.hex}", password_hash="x"))
        await session.flush()
        session.add(store.Session(id=rid_a, user_id=uid, title="研究A"))
        session.add(store.Session(id=rid_b, user_id=uid, title="研究B"))
        await session.flush()
        account = await biz.create_account(
            session,
            user_id=uid,
            name="共享账户",
            base_currency="CNY",
            declared={
                "total_capital": "100000",
                "capital_basis": "total",
                "currency": "CNY",
                "as_of": "2026-10-03T00:00:00Z",
            },
            idempotency_key=uuid.uuid4().hex,
        )
        plan_a = await biz.create_plan(
            session,
            user_id=uid,
            research_id=rid_a,
            name="计划A",
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
        plan_b = await biz.create_plan(
            session,
            user_id=uid,
            research_id=rid_b,
            name="计划B",
            declared={
                "symbol": "600519.SH",
                "market": "CN",
                "direction": "buy",
                "allocated_capital": "10000",
                "target_price": "25.00",
                "currency": "CNY",
            },
            idempotency_key=uuid.uuid4().hex,
        )
        await biz.set_research_link(
            session,
            user_id=uid,
            research_id=rid_a,
            account_id=uuid.UUID(account.result["account_id"]),
            primary_plan_id=uuid.UUID(plan_a.result["plan_id"]),
            idempotency_key=uuid.uuid4().hex,
        )
        await biz.set_research_link(
            session,
            user_id=uid,
            research_id=rid_b,
            account_id=uuid.UUID(account.result["account_id"]),
            primary_plan_id=uuid.UUID(plan_b.result["plan_id"]),
            idempotency_key=uuid.uuid4().hex,
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://arc.test"
    ) as client:
        yield SimpleNamespace(
            uid=uid,
            rid_a=rid_a,
            rid_b=rid_b,
            aid=uuid.UUID(account.result["account_id"]),
            pid_a=uuid.UUID(plan_a.result["plan_id"]),
            pid_b=uuid.UUID(plan_b.result["plan_id"]),
            client=client,
            headers={"Authorization": f"Bearer {create_access_token(uid)}"},
        )


def headers(case, key: str | None = None) -> dict[str, str]:
    return {**case.headers, "Idempotency-Key": key or uuid.uuid4().hex}


async def create_rule(case, *, research_id, plan_id=None) -> uuid.UUID:
    async with biz.business_transaction() as session:
        outcome = await watch_rules.create_rule(
            session,
            user_id=case.uid,
            research_id=research_id,
            plan_id=plan_id,
            name="监控规则",
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


async def rule_status(case, rule_id) -> str:
    async with biz.business_transaction() as session:
        rule = (
            await session.execute(select(store.WatchRule).where(store.WatchRule.id == rule_id))
        ).scalar_one()
        return rule.status


async def test_archive_account_idempotent_and_pauses_rules(case) -> None:
    rule_id = await create_rule(case, research_id=case.rid_a)
    response = await case.client.post(
        f"/api/business/accounts/{case.aid}/archive", headers=headers(case)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["archived"] is True
    assert body["paused_rules"] == [str(rule_id)]
    assert await rule_status(case, rule_id) == "paused"
    # 幂等：重复归档返回已归档回执，不再重复影响。
    again = await case.client.post(
        f"/api/business/accounts/{case.aid}/archive", headers=headers(case)
    )
    assert again.json()["already_archived"] is True
    assert again.json()["paused_rules"] == []


async def test_archive_plan_idempotent_and_pauses_rules(case) -> None:
    # 规则未直接绑定计划，但研究主计划为该计划 → 归档计划应暂停该规则。
    rule_id = await create_rule(case, research_id=case.rid_a)
    response = await case.client.post(
        f"/api/business/plans/{case.pid_a}/archive", headers=headers(case)
    )
    assert response.status_code == 200, response.text
    assert response.json()["archived"] is True
    assert str(rule_id) in response.json()["paused_rules"]
    again = await case.client.post(
        f"/api/business/plans/{case.pid_a}/archive", headers=headers(case)
    )
    assert again.json()["already_archived"] is True


async def test_archived_plan_stops_auto_analysis(case) -> None:
    rule_id = await create_rule(case, research_id=case.rid_a)
    event_id = await trigger(case, rule_id)
    await case.client.post(f"/api/business/plans/{case.pid_a}/archive", headers=headers(case))
    async with biz.business_transaction() as session:
        outcome = await watch_scheduler.schedule_event(session, event_id=event_id, now=_dt(2))
    assert outcome["status"] == "expired"
    # 归档计划会先暂停引用它的规则，调度侧先命中 rule_inactive（契约：归档停止新采用）。
    assert outcome["reason"] == "rule_inactive"
    # 归档对象不能成为新分析有效选择：直接解析也拒绝。
    async with biz.business_transaction() as session:
        spec = investment_snapshot.InvestmentInputSpec(
            use_case="plan_analysis",
            account=investment_snapshot.ObjectRef(id=case.aid),
            plan=investment_snapshot.ObjectRef(id=case.pid_a),
        )
        with pytest.raises(biz.ObjectArchivedError):
            await investment_snapshot.resolve_for_run(
                session, user_id=case.uid, research_id=case.rid_a, spec=spec
            )


async def test_delete_research_cascades(case) -> None:
    rule_id = await create_rule(case, research_id=case.rid_a)
    event_id = await trigger(case, rule_id)
    # 一条待补数请求。
    async with biz.business_transaction() as session:
        await input_requests.create_request(
            session,
            user_id=case.uid,
            research_id=case.rid_a,
            use_case="general_reading",
            fields=[{"name": "account.currency", "reason": "补全账户币种"}],
            idempotency_key=uuid.uuid4().hex,
            source_run_id=None,
            continuation={
                "message": "x",
                "investment_input": {"use_case": "general_reading"},
            },
        )
    # 一条待派发 outbox（研究 A 的直接 Run 派发意图）。
    async with biz.business_transaction() as session:
        run_id = uuid.uuid4()
        store.add_run(
            session,
            run_id=run_id,
            session_id=case.rid_a,
            user_id=case.uid,
            prompt="手动任务",
            pipeline_id="test",
            run_dir="/tmp/arc-run",
            status="queued",
        )
        await dispatch_outbox.enqueue(
            session,
            run_id=run_id,
            user_id=case.uid,
            research_id=case.rid_a,
            session_key=str(case.rid_a),
            prompt="手动任务",
        )

    response = await case.client.delete(
        f"/api/business/sessions/{case.rid_a}", headers=headers(case)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deleted"] is True
    assert body["cancelled_rules"] == 1
    assert body["expired_events"] == 1
    assert body["archived_plans"] == 1

    async with biz.business_transaction() as session:
        rule = (
            await session.execute(select(store.WatchRule).where(store.WatchRule.id == rule_id))
        ).scalar_one()
        event = (
            await session.execute(select(store.WatchEvent).where(store.WatchEvent.id == event_id))
        ).scalar_one()
        session_row = await session.get(store.Session, case.rid_a)
        plan_a = (
            await session.execute(
                select(store.InvestmentPlan).where(store.InvestmentPlan.id == case.pid_a)
            )
        ).scalar_one()
        account = (
            await session.execute(
                select(store.InvestmentAccount).where(store.InvestmentAccount.id == case.aid)
            )
        ).scalar_one()
        requests = (
            (
                await session.execute(
                    select(store.InputRequest).where(store.InputRequest.research_id == case.rid_a)
                )
            )
            .scalars()
            .all()
        )
        dispatch = (
            await session.execute(
                select(store.RunDispatch).where(store.RunDispatch.run_id == run_id)
            )
        ).scalar_one()
        link_b = (
            await session.execute(
                select(store.ResearchInvestmentLink).where(
                    store.ResearchInvestmentLink.research_id == case.rid_b
                )
            )
        ).scalar_one()
    assert rule.status == "cancelled"
    assert event.status == "expired"
    assert event.detail_json.get("expire_reason") == "research_deleted"
    assert session_row.deleted_at is not None
    assert plan_a.archived is True
    assert account.archived is False  # 共享账户不随研究删除（AC-17）
    assert all(request.status == "cancelled" for request in requests)
    assert dispatch.status == "abandoned"
    assert link_b.account_id == case.aid  # 研究 B 的绑定不受影响


async def test_delete_research_idempotent(case) -> None:
    rule_id = await create_rule(case, research_id=case.rid_a)
    first = await case.client.delete(f"/api/business/sessions/{case.rid_a}", headers=headers(case))
    assert first.json()["cancelled_rules"] == 1
    again = await case.client.delete(f"/api/business/sessions/{case.rid_a}", headers=headers(case))
    assert again.status_code == 200, again.text
    assert again.json()["already_deleted"] is True
    # 重试不复活已取消任务：规则仍是 cancelled。
    assert await rule_status(case, rule_id) == "cancelled"


async def test_queued_run_facts_preserved_after_delete(case) -> None:
    rule_id = await create_rule(case, research_id=case.rid_a)
    event_id = await trigger(case, rule_id)
    async with biz.business_transaction() as session:
        outcome = await watch_scheduler.schedule_event(session, event_id=event_id, now=_dt(2))
    run_id = uuid.UUID(outcome["run_id"])
    await case.client.delete(f"/api/business/sessions/{case.rid_a}", headers=headers(case))
    async with biz.business_transaction() as session:
        run = (await session.execute(select(store.Run).where(store.Run.id == run_id))).scalar_one()
        snap = (
            await session.execute(
                select(store.RunInvestmentSnapshot).where(
                    store.RunInvestmentSnapshot.run_id == run_id
                )
            )
        ).scalar_one()
        dispatch = (
            await session.execute(
                select(store.RunDispatch).where(store.RunDispatch.run_id == run_id)
            )
        ).scalar_one()
    # 事实保留：Run、快照仍在；待派发作废，不再启动。
    assert run is not None
    assert snap is not None and snap.source == "watch_event"
    assert dispatch.status == "abandoned"


async def test_notifications_reference_deleted_objects(case) -> None:
    rule_id = await create_rule(case, research_id=case.rid_a)
    await trigger(case, rule_id)
    listed = await case.client.get("/api/business/notifications", headers=case.headers)
    assert listed.json()["total"] == 1
    await case.client.delete(f"/api/business/sessions/{case.rid_a}", headers=headers(case))
    # 通知引用已删除研究/规则：不崩溃、仍可定位。
    after = await case.client.get("/api/business/notifications", headers=case.headers)
    assert after.status_code == 200, after.text
    assert after.json()["total"] == 1
    item = after.json()["items"][0]
    assert item["research_id"] == str(case.rid_a)
    assert item["detail"]["rule_id"] == str(rule_id)


async def test_other_user_cannot_archive_or_delete(case) -> None:
    other = uuid.uuid4()
    async with biz.business_transaction() as session:
        session.add(store.User(id=other, username=f"arc-other-{other.hex}", password_hash="x"))
        await session.flush()
    other_headers = {
        "Authorization": f"Bearer {create_access_token(other)}",
        "Idempotency-Key": uuid.uuid4().hex,
    }
    archive = await case.client.post(
        f"/api/business/accounts/{case.aid}/archive", headers=other_headers
    )
    assert archive.status_code == 404
    delete = await case.client.delete(f"/api/business/sessions/{case.rid_a}", headers=other_headers)
    assert delete.status_code == 404
