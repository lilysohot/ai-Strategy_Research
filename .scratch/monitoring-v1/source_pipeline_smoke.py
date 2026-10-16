"""Live read-only provider call, durable processing only in the isolated UI test DB."""
import asyncio
import uuid
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from redis.asyncio import Redis
from sqlalchemy import select

from plugins.market.factory import get_api_key, get_base_url
from server import business_service as biz
from server import monitor_pipeline as pipeline
from server import store, watch_rules
from server.config import get_config
from server.monitor_source import HttpPriceSource


async def main():
    load_dotenv(override=False)
    cfg = get_config()
    assert urlparse(cfg.database_url).path == '/frontier_monitor_ui_test'
    cfg.monitor_stream_prefix = 'test:live-source:' + uuid.uuid4().hex
    uid, rid = uuid.uuid4(), uuid.uuid4()
    async with biz.business_transaction() as session:
        session.add(store.User(id=uid, username='source-smoke-' + uid.hex, password_hash='unused'))
        await session.flush()
        session.add(store.Session(id=rid, user_id=uid, title='Isolated live quote smoke'))
        await session.flush()
        result = await watch_rules.create_rule(session, user_id=uid, research_id=rid, plan_id=None,
            name='Source smoke (notify only)', spec={'symbol': '601138.SH', 'market': 'CN', 'currency': 'CNY',
            'direction': 'up', 'threshold': '999999', 'action': 'notify'}, idempotency_key=uuid.uuid4().hex)
        await pipeline.heartbeat(session, uid)
    redis = Redis.from_url('redis://127.0.0.1:56379/0', decode_responses=True)
    delivery = pipeline.Delivery(redis)
    async with httpx.AsyncClient(base_url=get_base_url(), headers={'X-api-key': get_api_key()}, timeout=10) as client:
        await pipeline.collect_once(HttpPriceSource(client, timestamp_verified=True))
    await delivery.relay('quotes')
    await delivery.consume('quotes')
    async with biz.business_transaction() as session:
        rule = await session.get(store.WatchRule, uuid.UUID(result.result['rule_id']))
        print('live_source_decision', rule.last_suppressed_reason or 'valid_quote_below_threshold')
        print('last_valid_quote', rule.last_valid_quote_price, rule.last_valid_quote_at)
        message = await session.scalar(select(store.MonitorMessage).order_by(store.MonitorMessage.created_at.desc()).limit(1))
        print('durable_receipt', message.state, message.result)
        assert rule.armed
        assert message.state == 'completed'
        rule.status = 'cancelled'
    await redis.delete(delivery.stream('quotes'), delivery.stream('triggers'))
    await redis.aclose()
    await store.get_engine().dispose()


asyncio.run(main())
