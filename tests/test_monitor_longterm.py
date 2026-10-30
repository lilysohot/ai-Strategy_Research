"""Long-running monitor contract on isolated storage; no live quotes or model calls."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from server import business_service as biz
from server import monitor_longterm as monitor
from server import store, watch_agent, watch_rules, watch_scheduler
from server.config import get_config


@pytest.fixture
async def case(monkeypatch):
    async with store.get_engine().begin() as connection:
        await connection.run_sync(store.Base.metadata.create_all)
    now = datetime.now(UTC)
    clock = [now]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    monkeypatch.setattr(monitor, "datetime", Clock)
    monkeypatch.setattr(get_config(), "monitor_session_limit", 3)
    uid, rid, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with biz.business_transaction() as session:
        session.add(store.User(id=uid, username=uid.hex, password_hash="x"))
        await session.flush()
        session.add(store.Session(id=rid, user_id=uid, title="monitor"))
        await session.flush()
        session.add(
            store.MonitorPresence(
                user_id=uid,
                started_at=now - timedelta(seconds=1),
                expires_at=now + timedelta(days=2),
            )
        )
        session.add(store.MonitorSession(research_id=rid, auto_manage=True, sequence=0))
        store.add_run(
            session,
            run_id=run_id,
            session_id=rid,
            user_id=uid,
            prompt="research",
            pipeline_id="stateful-react-agent",
            status="running",
            run_dir="/tmp/test-monitor",
        )

    async def no_llm(**kwargs):
        return None

    monkeypatch.setattr(store, "get_default_llm_config", no_llm)
    monkeypatch.setattr(store, "build_llm_snapshot", no_llm)
    return SimpleNamespace(uid=uid, rid=rid, run_id=run_id, clock=clock)


def spec(price="20", symbol="600519.SH"):
    return dict(
        symbol=symbol,
        market="CN",
        currency="CNY",
        quote_basis="last",
        direction="up",
        threshold=price,
        trigger_mode="continuous",
        action="auto_analyze",
        task="核验价格",
    )


async def create(case, price="20", symbol="600519.SH", **overrides):
    async with biz.business_transaction() as session:
        out = await watch_rules.create_rule(
            session,
            user_id=case.uid,
            research_id=case.rid,
            plan_id=None,
            name="target",
            spec=spec(price, symbol) | overrides,
            idempotency_key=uuid.uuid4().hex,
        )
        return uuid.UUID(out.result["rule_id"])


class Source:
    def __init__(self, case, price="25"):
        self.case, self.price, self.calls = case, price, []

    async def fetch(self, symbol, market, currency, basis):
        from server.watch_eval import MonitoringObservation

        self.calls.append(symbol)
        ts = int(self.case.clock[0].timestamp() * 1000)
        return MonitoringObservation(
            thscode=symbol,
            market=market,
            currency=currency,
            quote_basis=basis,
            price=Decimal(self.price),
            observed_at_ms=ts,
            received_at_ms=ts,
        )


@pytest.mark.parametrize("direction,prices", [
    ("up", ["21", "22", "19", "20", "21"]),
    ("down", ["19", "18", "21", "20", "19"]),
    ("range", ["21", "22", "19", "20", "21"]),
])
async def test_crossing_first_hit_then_requires_reentry(case, direction, prices):
    threshold = {"low": "20", "high": "23"} if direction == "range" else "20"
    await create(case, direction=direction, threshold=threshold, trigger_mode="crossing")
    source = Source(case)
    for price, expected in zip(prices, [1, 1, 1, 2, 2], strict=True):
        source.price = price
        await monitor.collect_once(source, now=case.clock[0])
        assert len(await events()) == expected
        case.clock[0] += timedelta(minutes=15)


async def test_human_run_can_cancel_paused_agent_target_and_replace(case):
    out = await watch_agent.call(case.run_id, "submit", {"intents": [intent()]})
    rule_id = out["results"][0]["rule_id"]
    async with biz.business_transaction() as session:
        (await session.get(store.WatchRule, uuid.UUID(rule_id))).status = "paused"
    out = await watch_agent.call(case.run_id, "submit", {"intents": [
        {"operation": "cancel", "intent_key": "breakout", "rule_id": rule_id,
         "expected_version": 1, "reason": "按本轮用户要求替换旧目标"},
        intent("replacement", "21") | {"spec": spec("21") | {"trigger_mode": "crossing"}},
    ]})
    assert out["ok"]
    targets = (await watch_agent.call(case.run_id, "get", {}))["targets"]
    assert len(targets) == 1 and targets[0]["trigger_mode"] == "crossing"


async def test_agent_update_preserves_crossing_mode(case):
    payload = intent() | {"spec": spec() | {"trigger_mode": "crossing"}}
    out = await watch_agent.call(case.run_id, "submit", {"intents": [payload]})
    await watch_agent.call(case.run_id, "submit", {"intents": [{
        "operation": "update", "intent_key": "breakout", "reason": "调整关键价格",
        "rule_id": out["results"][0]["rule_id"], "expected_version": 1,
        "spec": {"threshold": "22"},
    }]})
    target = (await watch_agent.call(case.run_id, "get", {}))["targets"][0]
    assert target["trigger_mode"] == "crossing"
    assert target["threshold"] == "22"


async def test_crossing_rebases_after_offline_without_synthetic_cross(case):
    await create(case, trigger_mode="crossing")
    source = Source(case, "19")
    await monitor.collect_once(source, now=case.clock[0])
    assert not await events()
    case.clock[0] += timedelta(minutes=15)
    async with biz.business_transaction() as session:
        (await session.get(store.MonitorPresence, case.uid)).started_at = case.clock[0]
    source.price = "21"
    await monitor.collect_once(source, now=case.clock[0])
    assert not await events()  # no claim to have observed a crossing while offline
    for price in ("19", "20"):
        case.clock[0] += timedelta(minutes=15)
        source.price = price
        await monitor.collect_once(source, now=case.clock[0])
    assert len(await events()) == 1


async def events():
    async with biz.business_transaction() as session:
        return list(
            (
                await session.scalars(
                    select(store.WatchEvent).order_by(store.WatchEvent.queue_sequence)
                )
            ).all()
        )


async def finish(run_id):
    async with biz.business_transaction() as session:
        (await session.get(store.Run, run_id)).status = "completed"


async def schedule(event, case):
    async with biz.business_transaction() as session:
        return await watch_scheduler.schedule_event(session, event_id=event.id, now=case.clock[0])


async def test_three_targets_one_signal_and_no_same_round_replay(case):
    first = await create(case, "20")
    await create(case, "21")
    await create(case, "22", "000001.SZ")
    source = Source(case)
    assert await monitor.collect_once(source, now=case.clock[0]) == 1
    assert len(source.calls) == 2  # one quote per distinct instrument, shared across targets
    rows = await events()
    assert len(rows) == 1
    assert len(rows[0].detail_json["targets"]) == 3
    async with biz.business_transaction() as session:
        ordered = await monitor.targets(session, case.rid)
        assert rows[0].rule_id == ordered[0][0].id
        assert (await session.get(store.WatchRule, first)).armed
    assert await monitor.collect_once(source, now=case.clock[0]) == 0
    assert len(await events()) == 1


async def test_repeats_fifo_and_price_return_does_not_cancel(case):
    rule_id = await create(case)
    source = Source(case)
    await monitor.collect_once(source, now=case.clock[0])
    case.clock[0] += timedelta(minutes=15)
    await monitor.collect_once(source, now=case.clock[0])
    first, second = await events()
    assert (await schedule(first, case))["reason"] == "research_busy"
    assert (await schedule(second, case))["reason"] == "earlier_signal"
    await finish(case.run_id)
    async with biz.business_transaction() as session:
        rule = await session.get(store.WatchRule, rule_id)
        rule.last_valid_quote_price = Decimal("1")
        rule.last_valid_quote_at = case.clock[0] - timedelta(days=2)
    result = await schedule(first, case)
    assert result["status"] == "dispatching"  # no account, no trade, price now below threshold
    assert (await schedule(first, case))["run_id"] == result["run_id"]
    assert (await schedule(second, case))["reason"] == "research_busy"
    await finish(uuid.UUID(result["run_id"]))
    case.clock[0] += timedelta(hours=2)
    assert (await schedule(second, case))["status"] == "dispatching"


async def test_offline_preserves_queue_and_resumes(case):
    await create(case)
    await monitor.collect_once(Source(case), now=case.clock[0])
    event = (await events())[0]
    await finish(case.run_id)
    async with biz.business_transaction() as session:
        presence = await session.get(store.MonitorPresence, case.uid)
        presence.expires_at = case.clock[0] - timedelta(seconds=1)
    assert (await schedule(event, case))["reason"] == "browser_offline"
    case.clock[0] += timedelta(minutes=15)
    assert await monitor.collect_once(Source(case), now=case.clock[0]) == 0
    async with biz.business_transaction() as session:
        presence = await session.get(store.MonitorPresence, case.uid)
        presence.started_at = case.clock[0]
        presence.expires_at = case.clock[0] + timedelta(minutes=2)
    assert (await schedule(event, case))["status"] == "dispatching"


async def test_pause_during_acquisition_excludes_target(case):
    target = await create(case)
    other = await create(case, "21")

    class PausingSource(Source):
        async def fetch(self, *args):
            async with biz.business_transaction() as session:
                (await session.get(store.WatchRule, target)).status = "paused"
            return await super().fetch(*args)

    await monitor.collect_once(PausingSource(case), now=case.clock[0])
    rows = await events()
    assert len(rows) == 1
    assert [h["id"] for h in rows[0].detail_json["targets"]] == [str(other)]


async def test_expired_quote_and_source_errors_do_not_trigger(case):
    await create(case)

    class BadSource(Source):
        async def fetch(self, *args):
            raise TimeoutError("do not expose provider credentials")

    await monitor.collect_once(BadSource(case), now=case.clock[0])
    assert await events() == []


def intent(key="breakout", price="20"):
    return {
        "operation": "create",
        "intent_key": key,
        "reason": "研究依据价格复核",
        "evidence_refs": ["market_quote:observed"],
        "spec": spec(price),
    }


async def test_agent_authorization_atomic_capacity_and_idempotence(case):
    payload = {"intents": [intent("a", "20"), intent("b", "21"), intent("c", "22")]}
    result = await watch_agent.call(case.run_id, "submit", payload)
    assert result["ok"]
    assert (await watch_agent.call(case.run_id, "submit", payload))["results"] == result["results"]
    with pytest.raises(biz.ValidationError):
        await watch_agent.call(case.run_id, "submit", {"intents": [intent("d", "23")]})
    assert len((await watch_agent.call(case.run_id, "get", {}))["targets"]) == 3
    async with biz.business_transaction() as session:
        (await session.get(store.MonitorSession, case.rid)).auto_manage = False
    with pytest.raises(biz.ValidationError):
        await watch_agent.call(case.run_id, "submit", payload)


async def test_batch_invalid_rolls_back_and_paused_intent_cannot_reappear(case):
    with pytest.raises(biz.ValidationError):
        await watch_agent.call(case.run_id, "submit", {"intents": [intent(), intent("bad", "NaN")]})
    assert (await watch_agent.call(case.run_id, "get", {}))["targets"] == []
    result = await watch_agent.call(case.run_id, "submit", {"intents": [intent()]})
    target = uuid.UUID(result["results"][0]["rule_id"])
    async with biz.business_transaction() as session:
        (await session.get(store.WatchRule, target)).status = "paused"
    with pytest.raises(biz.ValidationError):
        await watch_agent.call(case.run_id, "submit", {"intents": [intent(price="21")]})


async def test_bridge_capability_and_live_pause_guard(case, monkeypatch):
    from plugins.tools.watch_targets import request
    from server.watch_bridge import WatchBridge

    await create(case)
    await monitor.collect_once(Source(case), now=case.clock[0])
    await finish(case.run_id)
    result = await schedule((await events())[0], case)
    bridge = WatchBridge(uuid.UUID(result["run_id"]))
    config = await bridge.start()
    monkeypatch.setenv("FRONTIER_WATCH_CHANNEL", config)
    try:
        assert (await request("guard"))["ok"]
        async with biz.business_transaction() as session:
            for rule, _ in await monitor.targets(session, case.rid):
                rule.status = "paused"
        assert not (await request("guard"))["ok"]
        wrong = json.loads(config) | {"token": "wrong"}
        monkeypatch.setenv("FRONTIER_WATCH_CHANNEL", json.dumps(wrong))
        assert not (await request("get"))["ok"]
    finally:
        await bridge.close()


async def test_agent_cancel_replace_and_human_takeover(case):
    result = await watch_agent.call(case.run_id, "submit", {"intents": [intent()]})
    target = result["results"][0]["rule_id"]
    cancel = dict(
        operation="cancel",
        intent_key="breakout",
        rule_id=target,
        expected_version=1,
        reason="原假设不成立",
    )
    result = await watch_agent.call(
        case.run_id, "submit", {"intents": [cancel, intent("new", "21")]}
    )
    assert result["ok"]
    rows = (await watch_agent.call(case.run_id, "get", {}))["targets"]
    assert len(rows) == 1
    async with biz.business_transaction() as session:
        await watch_rules.update_rule(
            session,
            user_id=case.uid,
            rule_id=uuid.UUID(rows[0]["id"]),
            expected_version=1,
            patch={"threshold": "22"},
            idempotency_key=uuid.uuid4().hex,
        )
    with pytest.raises(biz.ValidationError):
        await watch_agent.call(case.run_id, "submit", {"intents": [intent("new", "23")]})


async def test_launch_offline_is_deferred_not_failed(case):
    from server import dispatch_outbox

    await create(case)
    await monitor.collect_once(Source(case), now=case.clock[0])
    await finish(case.run_id)
    result = await schedule((await events())[0], case)
    run_id = uuid.UUID(result["run_id"])
    async with biz.business_transaction() as session:
        (await session.get(store.MonitorPresence, case.uid)).expires_at = case.clock[0] - timedelta(
            seconds=1
        )
        assert await dispatch_outbox.claim_due(session) == []
    with pytest.raises(monitor.MonitorLaunchDeferred):
        await watch_scheduler.assert_watch_launch_ready(run_id)
    await monitor.defer_launch(run_id)
    async with biz.business_transaction() as session:
        assert (await session.get(store.Run, run_id)).status == "queued"
        row = await session.scalar(
            select(store.RunDispatch).where(store.RunDispatch.run_id == run_id)
        )
        assert row.status == "pending"


async def test_agent_cannot_write_another_session(case):
    async with biz.business_transaction() as session:
        other = store.Session(user_id=case.uid, title="other")
        session.add(other)
        await session.flush()
        out = await watch_rules.create_rule(
            session,
            user_id=case.uid,
            research_id=other.id,
            plan_id=None,
            name="other",
            spec=spec(),
            idempotency_key=uuid.uuid4().hex,
        )
    change = dict(
        operation="update",
        intent_key="other",
        reason="update",
        rule_id=out.result["rule_id"],
        expected_version=1,
        spec={"threshold": "30"},
    )
    with pytest.raises(biz.NotFoundOrForbiddenError):
        await watch_agent.call(case.run_id, "submit", {"intents": [change]})


async def test_cancel_all_targets_releases_already_queued_run(case):
    from server import dispatch_outbox

    await create(case)
    await monitor.collect_once(Source(case), now=case.clock[0])
    await finish(case.run_id)
    result = await schedule((await events())[0], case)
    run_id = uuid.UUID(result["run_id"])
    async with biz.business_transaction() as session:
        for rule, _ in await monitor.targets(session, case.rid):
            rule.status = "cancelled"
    async with biz.business_transaction() as session:
        assert await dispatch_outbox.claim_due(session) == []
    async with biz.business_transaction() as session:
        assert (await session.get(store.Run, run_id)).status == "stopped"
        event = await session.scalar(
            select(store.WatchEvent).where(store.WatchEvent.run_id == run_id)
        )
        assert event.status == "expired"
        dispatch = await session.scalar(
            select(store.RunDispatch).where(store.RunDispatch.run_id == run_id)
        )
        assert dispatch.status == "abandoned"


async def test_monitor_settings_scope_and_queued_status(case):
    from server.routes.monitor import MonitorSettings, session_status, update_settings

    async with biz.business_transaction() as session:
        user = await session.get(store.User, case.uid)
    result = await update_settings(case.rid, MonitorSettings(auto_manage=False), user)
    assert result == {"auto_manage": False}
    with pytest.raises(biz.NotFoundOrForbiddenError):
        await update_settings(uuid.uuid4(), MonitorSettings(auto_manage=True), user)
    await create(case)
    await monitor.collect_once(Source(case), now=case.clock[0])
    assert (await session_status(case.rid, user))["queued_signals"] == 1
    await finish(case.run_id)
    result = await schedule((await events())[0], case)
    status = await session_status(case.rid, user)
    assert status["queued_signals"] == 1
    assert status["auto_manage"] is False
    await finish(uuid.UUID(result["run_id"]))
    assert (await session_status(case.rid, user))["queued_signals"] == 0


async def test_monitor_prompt_does_not_repeat_reports_or_target_views(case):
    await create(case)
    await finish(case.run_id)
    await monitor.collect_once(Source(case), now=case.clock[0])
    first = await schedule((await events())[0], case)
    async with biz.business_transaction() as session:
        run = await session.get(store.Run, uuid.UUID(first["run_id"]))
        run.status = "completed"
        run.final_answer = "OLD_FULL_REPORT_MUST_NOT_BE_INLINED" * 50
    case.clock[0] += timedelta(minutes=15)
    await monitor.collect_once(Source(case), now=case.clock[0])
    second = await schedule((await events())[-1], case)
    async with biz.business_transaction() as session:
        prompt = (await session.get(store.Run, uuid.UUID(second["run_id"]))).prompt
    assert "OLD_FULL_REPORT_MUST_NOT_BE_INLINED" not in prompt
    assert '"armed"' not in prompt
    assert '"last_suppressed_reason"' not in prompt
