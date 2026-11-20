"""Redis head hints: durable watermark, retry after failure and startup gating."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select

from server import store
from server.config import get_config
from server.super_link import events
from server.super_link import models as sl


class FakeRedis:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.fail = False

    async def publish(self, channel, message):
        if self.fail:
            raise ConnectionError("redis unavailable")
        self.messages.append((channel, message))
        return len(self.messages)


async def seed_events(sessions, *, keys=("a1",), spaces=1):
    spaces_out = []
    async with sessions.begin() as session:
        owner = store.User(username=uuid.uuid4().hex, password_hash="unused")
        session.add(owner)
        await session.flush()
        for _ in range(spaces):
            space = sl.SuperLinkSpace(
                user_id=owner.id, creation_key=uuid.uuid4(), goal="Notify"
            )
            session.add(space)
            await session.flush()
            session.add(sl.SuperLinkEventHead(space_id=space.id, stream_epoch=uuid.uuid4()))
            spaces_out.append(space.id)
        for space_id in spaces_out:
            for index, key in enumerate(keys, start=1):
                await events.stage_for_space(
                    session,
                    space_id,
                    type="sl.action.recorded",
                    change_key=key,
                    data={"action": f"step-{index}"},
                )
        await events.seal_changes(session)
    return spaces_out


async def notified(sessions, space_id):
    async with sessions.begin() as session:
        return (
            await session.scalars(
                select(sl.SuperLinkEvent.notified_at).where(
                    sl.SuperLinkEvent.space_id == space_id
                )
            )
        ).all()


@pytest.fixture
async def case(monkeypatch):
    await store.init_db()
    async with store.get_engine().begin() as connection:
        await connection.run_sync(sl.Base.metadata.create_all)
    monkeypatch.setattr(get_config(), "super_link_enabled", True)
    sessions = store.get_sessionmaker()
    (space_id,) = await seed_events(sessions, keys=("a1", "a2"))
    return sessions, space_id


async def test_publish_once_marks_watermark_and_is_idempotent(case):
    sessions, space_id = case
    redis = FakeRedis()
    notifier = events.EventNotifier(sessions, redis, channel="test:ui-events")
    assert await notifier.publish_once() == 1
    assert len(redis.messages) == 1
    channel, payload = redis.messages[0]
    assert channel == "test:ui-events"
    body = json.loads(payload)
    assert body == {
        "schema_version": 1,
        "space_id": str(space_id),
        "stream_epoch": body["stream_epoch"],
        "head_seq": 2,
    }
    uuid.UUID(body["stream_epoch"])
    assert all(value is not None for value in await notified(sessions, space_id))

    assert await notifier.publish_once() == 0
    assert len(redis.messages) == 1


async def test_redis_failure_keeps_watermark_for_retry(case):
    sessions, space_id = case
    redis = FakeRedis()
    redis.fail = True
    notifier = events.EventNotifier(sessions, redis, channel="test:ui-events")
    assert await notifier.publish_once() == 0
    assert all(value is None for value in await notified(sessions, space_id))

    redis.fail = False
    assert await notifier.publish_once() == 1
    assert all(value is not None for value in await notified(sessions, space_id))


async def test_batch_limit_publishes_one_group_per_call(monkeypatch):
    await store.init_db()
    async with store.get_engine().begin() as connection:
        await connection.run_sync(sl.Base.metadata.create_all)
    monkeypatch.setattr(get_config(), "super_link_enabled", True)
    sessions = store.get_sessionmaker()
    first, second = await seed_events(sessions, keys=("a1",), spaces=2)
    redis = FakeRedis()
    notifier = events.EventNotifier(sessions, redis, channel="test:ui-events", batch=1)
    assert await notifier.publish_once() == 1
    assert await notifier.publish_once() == 1
    assert await notifier.publish_once() == 0
    published = {json.loads(payload)["space_id"] for _, payload in redis.messages}
    assert published == {str(first), str(second)}


async def test_channel_and_startup_predicate(monkeypatch):
    cfg = get_config()
    monkeypatch.setattr(cfg, "super_link_event_env", "test-env")
    monkeypatch.setattr(cfg, "super_link_namespace", "super-link:v1")
    assert events.event_channel(cfg) == "test-env:super-link:v1:ui-events:v1"

    monkeypatch.setattr(cfg, "super_link_enabled", True)
    monkeypatch.setattr(cfg, "restore_mode", False)
    assert events.notifier_should_start(ready=True) is True
    assert events.notifier_should_start(ready=False) is False
    monkeypatch.setattr(cfg, "restore_mode", True)
    assert events.notifier_should_start(ready=True) is False
    monkeypatch.setattr(cfg, "restore_mode", False)
    monkeypatch.setattr(cfg, "super_link_enabled", False)
    assert events.notifier_should_start(ready=True) is False
