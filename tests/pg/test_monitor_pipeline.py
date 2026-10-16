"""Real PostgreSQL + Redis, isolated test services; never start a model worker."""

import asyncio
import uuid
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select

from server import business_service as biz
from server import monitor_pipeline as pipeline
from server import store, watch_eval, watch_rules
from server.config import get_config
from tests.pg.test_watch_scheduler import case as scheduler_case
from tests.pg.test_watch_scheduler import create_rule

case = scheduler_case


@pytest.fixture
async def delivery(monkeypatch):
    cfg = get_config()
    monkeypatch.setattr(cfg, "monitor_streams_enabled", True)
    monkeypatch.setattr(cfg, "monitor_session_limit", 1)
    monkeypatch.setattr(cfg, "monitor_stream_prefix", f"test:monitor:{uuid.uuid4()}")
    client = Redis.from_url("redis://127.0.0.1:56379/0", decode_responses=True)
    await client.ping()
    yield pipeline.Delivery(client)
    await client.delete(
        f"{cfg.monitor_stream_prefix}:quotes", f"{cfg.monitor_stream_prefix}:triggers"
    )
    await client.aclose()


class Source:
    def __init__(self, price="21", **overrides):
        self.price = price
        self.overrides = overrides
        self.calls = []

    async def fetch(self, symbol, market, currency, basis):
        self.calls.append(symbol)
        ts = int(pipeline.utcnow().timestamp() * 1000)
        return replace(
            watch_eval.MonitoringObservation(
                thscode=symbol,
                market=market,
                currency=currency,
                quote_basis=basis,
                price=Decimal(self.price),
                received_at_ms=ts,
                observed_at_ms=ts,
            ),
            **self.overrides,
        )


async def enter(case):
    async with biz.business_transaction() as session:
        await pipeline.heartbeat(session, case.uid)


async def counts():
    async with biz.business_transaction() as session:
        return tuple(
            [
                await session.scalar(select(func.count()).select_from(model))
                for model in (store.WatchEvent, store.Run, store.RunDispatch)
            ]
        )


async def pump(delivery):
    await delivery.relay("quotes")
    await delivery.consume("quotes")
    await delivery.relay("triggers")
    await delivery.consume("triggers")


async def test_real_streams_commit_before_ack_and_redis_loss_create_one_run(case, delivery):
    await create_rule(case)
    await enter(case)
    assert await pipeline.collect_once(Source()) == 1
    await delivery.relay("quotes")
    async with biz.business_transaction() as session:
        quote_id = await session.scalar(
            select(store.MonitorMessage.id).where(store.MonitorMessage.channel == "quotes")
        )
    # Simulate crash after the DB commit but before the Redis acknowledgement.
    await pipeline.process_message(quote_id, channel="quotes")
    await delivery.consume("quotes")
    assert (await counts())[:2] == (1, 0)
    await delivery.relay("triggers")
    await delivery.redis.delete(delivery.stream("triggers"))
    async with biz.business_transaction() as session:
        row = await session.scalar(
            select(store.MonitorMessage).where(store.MonitorMessage.channel == "triggers")
        )
        row.published_at = pipeline.utcnow() - timedelta(minutes=5)
    assert await delivery.relay("triggers") == 1
    await delivery.consume("triggers")
    async with biz.business_transaction() as session:
        assert (
            await session.scalar(
                select(store.MonitorMessage.state).where(store.MonitorMessage.channel == "triggers")
            )
            == "accepted"
        )
    assert (await counts())[:2] == (1, 0)  # ACK does not wait for a long Run.
    await pipeline.schedule_received()
    await pipeline.schedule_received()
    assert (await counts())[:2] == (1, 1)
    async with biz.business_transaction() as session:
        event = await session.scalar(select(store.WatchEvent))
        run = await session.get(store.Run, event.run_id)
        assert run.status == "queued"
        assert "600519.SH" in run.prompt and "价格监控触发" in run.prompt
        assert (
            await session.scalar(select(func.count()).select_from(store.SessionConversation)) == 0
        )


async def test_offline_no_collection_and_pending_trigger_expires(case, delivery):
    await create_rule(case)
    source = Source()
    assert await pipeline.collect_once(source) == 0
    assert not source.calls
    await enter(case)
    assert await pipeline.collect_once(source) == 1
    await pump(delivery)
    async with biz.business_transaction() as session:
        presence = await session.get(store.MonitorPresence, case.uid)
        presence.expires_at = pipeline.utcnow() - timedelta(seconds=1)
    await pipeline.schedule_received()
    assert (await counts())[:2] == (1, 0)
    async with biz.business_transaction() as session:
        event = await session.scalar(select(store.WatchEvent))
        assert event.status == "expired"
        assert event.detail_json["expire_reason"] == "browser_offline"


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"time_source": "unknown"}, "unverified_quote_time"),
        ({"observed_at_ms": 1}, "stale_quote"),
        ({"precision_limited": True}, "imprecise_price"),
    ],
)
async def test_invalid_quotes_persist_decision_without_trigger(case, delivery, overrides, reason):
    rule_id = await create_rule(case)
    await enter(case)
    await pipeline.collect_once(Source(**overrides))
    await pump(delivery)
    assert (await counts())[:2] == (0, 0)
    async with biz.business_transaction() as session:
        rule = await session.get(store.WatchRule, rule_id)
        assert rule.armed and rule.last_valid_quote_at is None
        assert rule.last_suppressed_reason == reason
        message = await session.scalar(select(store.MonitorMessage))
        assert message.state == "completed"
        assert message.result["decisions"][0]["reason"] == reason


async def test_concurrent_creation_has_one_current_slot(case, delivery):
    outcomes = await asyncio.gather(create_rule(case), create_rule(case), return_exceptions=True)
    assert sum(isinstance(x, uuid.UUID) for x in outcomes) == 1
    assert sum(isinstance(x, biz.ValidationError) for x in outcomes) == 1


async def test_obsolete_queued_quote_cannot_trigger_edited_rule(case, delivery):
    rule_id = await create_rule(case)
    await enter(case)
    await pipeline.collect_once(Source())
    async with biz.business_transaction() as session:
        await watch_rules.update_rule(
            session,
            user_id=case.uid,
            rule_id=rule_id,
            expected_version=1,
            patch={"threshold": "19"},
            idempotency_key=uuid.uuid4().hex,
        )
    await pump(delivery)
    assert (await counts())[:2] == (0, 0)


async def test_poison_message_quarantined_and_other_session_keeps_consuming(case, delivery):
    await create_rule(case)
    await enter(case)
    async with biz.business_transaction() as session:
        poisoned = store.MonitorMessage(
            channel="quotes",
            payload={"broken": True},
            state="pending",
            available_at=pipeline.utcnow(),
        )
        session.add(poisoned)
        await session.flush()
        mid = poisoned.id
    for _ in range(get_config().monitor_max_attempts):
        await delivery.relay("quotes")
        await delivery.consume("quotes")
        async with biz.business_transaction() as session:
            row = await session.get(store.MonitorMessage, mid)
            row.available_at = pipeline.utcnow()
    async with biz.business_transaction() as session:
        assert (await session.get(store.MonitorMessage, mid)).state == "quarantined"
    await pipeline.collect_once(Source())
    await pump(delivery)
    await pipeline.schedule_received()
    assert (await counts())[:2] == (1, 1)


async def test_authenticated_status_scoped_to_research(case, delivery):
    heartbeat = await case.client.post("/api/business/monitor/heartbeat", headers=case.headers)
    assert heartbeat.status_code == 200
    status = await case.client.get(
        f"/api/business/monitor/sessions/{case.rid}", headers=case.headers
    )
    assert status.status_code == 200 and status.json()["online"]
    denied = await case.client.get(
        f"/api/business/monitor/sessions/{uuid.uuid4()}", headers=case.headers
    )
    assert denied.status_code == 404


async def test_same_instrument_in_two_sessions_shares_http_not_events(case, delivery):
    await create_rule(case)
    await enter(case)
    rid = uuid.uuid4()
    async with biz.business_transaction() as session:
        session.add(store.Session(id=rid, user_id=case.uid, title="second monitor"))
        await session.flush()
        await watch_rules.create_rule(
            session,
            user_id=case.uid,
            research_id=rid,
            plan_id=None,
            name="shared quote",
            spec={
                "symbol": "600519.SH",
                "market": "CN",
                "currency": "CNY",
                "direction": "up",
                "threshold": "20",
                "action": "notify",
                "on_create_already_met": "trigger_now",
            },
            idempotency_key=uuid.uuid4().hex,
        )
    source = Source()
    assert await pipeline.collect_once(source) == 1
    assert source.calls == ["600519.SH"]
    await pump(delivery)
    await pipeline.schedule_received()
    assert (await counts())[:2] == (2, 1)
    async with biz.business_transaction() as session:
        event = await session.scalar(
            select(store.WatchEvent).where(store.WatchEvent.research_id == rid)
        )
        assert event.status == "completed" and event.run_id is None


async def test_pause_resume_invalidates_queued_quote_and_trigger(case, delivery):
    rule_id = await create_rule(case)
    await enter(case)
    await pipeline.collect_once(Source())
    await pump(delivery)
    for action in ("pause", "resume"):
        response = await case.client.post(
            f"/api/business/watch-rules/{rule_id}/{action}",
            json={"expected_version": 1},
            headers={**case.headers, "Idempotency-Key": uuid.uuid4().hex},
        )
        assert response.status_code == 200
    await pipeline.schedule_received()
    assert (await counts())[:2] == (1, 0)
    async with biz.business_transaction() as session:
        event = await session.scalar(select(store.WatchEvent))
        assert event.status == "expired"
        assert event.detail_json["expire_reason"] == "rule_lifecycle_changed"
    # Paused/resumed still occupies the single current configuration slot.
    with pytest.raises(biz.ValidationError):
        await create_rule(case)
    response = await case.client.post(
        f"/api/business/watch-rules/{rule_id}/cancel",
        json={"expected_version": 1},
        headers={**case.headers, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert response.status_code == 200
    assert await create_rule(case) != rule_id


async def test_browser_reconnect_does_not_replay_prior_online_trigger(case, delivery):
    await create_rule(case)
    await enter(case)
    await pipeline.collect_once(Source())
    await pump(delivery)
    async with biz.business_transaction() as session:
        row = await session.get(store.MonitorPresence, case.uid)
        row.expires_at = pipeline.utcnow() - timedelta(seconds=1)
    await enter(case)
    await pipeline.schedule_received()
    async with biz.business_transaction() as session:
        event = await session.scalar(select(store.WatchEvent))
        assert event.status == "expired"
        assert event.detail_json["expire_reason"] == "prior_online_period"
    assert (await counts())[:2] == (1, 0)


async def test_busy_run_does_not_block_quote_consumption_and_requires_revalidation(case, delivery):
    await create_rule(case)
    await enter(case)
    busy_id = uuid.uuid4()
    async with biz.business_transaction() as session:
        store.add_run(
            session,
            run_id=busy_id,
            session_id=case.rid,
            user_id=case.uid,
            prompt="slow existing research",
            pipeline_id="stateful-react-agent",
            run_dir="unused-test-only",
            status="running",
        )
    await pipeline.collect_once(Source())
    await pump(delivery)
    await pipeline.schedule_received()
    async with biz.business_transaction() as session:
        receipt = await session.scalar(
            select(store.MonitorMessage).where(store.MonitorMessage.channel == "triggers")
        )
        assert receipt.state == "accepted" and receipt.result["reason"] == "research_busy"
        receipt.available_at = pipeline.utcnow()
        target = await session.scalar(select(store.MonitorTarget))
        target.next_poll_at = pipeline.utcnow()
        (await session.get(store.Run, busy_id)).status = "completed"
    # Price has fallen below the threshold while the first Run was busy.
    assert await pipeline.collect_once(Source("19")) == 1
    await pump(delivery)
    await pipeline.schedule_received()
    async with biz.business_transaction() as session:
        event = await session.scalar(select(store.WatchEvent))
        assert event.status == "expired" and event.run_id is None
        assert event.detail_json["expire_reason"] == "condition_no_longer_met"
    assert (await counts())[:2] == (1, 1)  # Only the original manual Run.


async def test_final_launch_gate_rejects_stale_quote_and_changed_snapshot(case, delivery):
    from server.watch_scheduler import assert_watch_launch_ready

    rule_id = await create_rule(case)
    await enter(case)
    await pipeline.collect_once(Source())
    await pump(delivery)
    await pipeline.schedule_received()
    async with biz.business_transaction() as session:
        run_id = await session.scalar(select(store.WatchEvent.run_id))
    await assert_watch_launch_ready(run_id)
    async with biz.business_transaction() as session:
        rule = await session.get(store.WatchRule, rule_id)
        rule.last_valid_quote_at = pipeline.utcnow() - timedelta(minutes=10)
    with pytest.raises(RuntimeError, match="monitor_quote_expired_before_launch"):
        await assert_watch_launch_ready(run_id)
    async with biz.business_transaction() as session:
        rule = await session.get(store.WatchRule, rule_id)
        rule.last_valid_quote_at = pipeline.utcnow()
        (await session.get(store.InvestmentPlan, case.pid)).archived = True
    with pytest.raises(RuntimeError, match="monitor_business_snapshot_changed"):
        await assert_watch_launch_ready(run_id)
