from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from server import store
from server.config import get_config
from server.deps import get_current_user
from server.routes import super_link as routes
from server.super_link import events, observability
from tests.test_super_link_notifier import FakeRedis, seed_events
from tests.test_super_link_runtime import case as case


@pytest.fixture
async def client(case):
    sessions, uid, _pair = case
    async with sessions() as session:
        user = await session.get(store.User, uid)
    holder = {"user": user}
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_current_user] = lambda: holder["user"]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", timeout=10
    ) as http:
        yield http, holder, sessions


async def test_owner_reads_process_and_event_diagnostics(client):
    http, _holder, _sessions = client
    observability.reset()
    observability.inc("sse.opened")
    observability.inc("preview.frames", 2)
    observability.inc("preview.dropped")
    # The space id comes from the seeded pair via the authenticated user's spaces.
    spaces = (await http.get("/api/super-link/spaces")).json()["items"]
    space_id = spaces[0]["space_id"]

    response = await http.get(f"/api/super-link/spaces/{space_id}/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == 1
    assert body["scope"] == "process"
    assert body["process"]["sse"]["opened"] == 1
    assert body["process"]["sse"]["active_for_user"] == 0
    assert body["process"]["sse"]["limit"] == get_config().super_link_sse_max_connections
    assert body["process"]["preview"] == {"frames": 2, "resets": 0, "dropped": 1}
    assert body["events"]["head_seq"] >= 0
    assert body["events"]["unnotified_count"] >= 0
    assert body["events"]["oldest_unnotified_age_seconds"] >= 0


async def test_foreign_user_gets_404_without_existence_leak(client):
    http, holder, sessions = client
    spaces = (await http.get("/api/super-link/spaces")).json()["items"]
    space_id = spaces[0]["space_id"]
    async with sessions.begin() as session:
        outsider = store.User(username=uuid.uuid4().hex, password_hash="unused")
        session.add(outsider)
        await session.flush()
        await session.refresh(outsider)
    holder["user"] = outsider

    response = await http.get(f"/api/super-link/spaces/{space_id}/diagnostics")

    assert response.status_code == 404


async def test_disabled_mode_hides_diagnostics(client, monkeypatch):
    http, _holder, _sessions = client
    spaces = (await http.get("/api/super-link/spaces")).json()["items"]
    space_id = spaces[0]["space_id"]
    monkeypatch.setattr(get_config(), "super_link_enabled", False)

    response = await http.get(f"/api/super-link/spaces/{space_id}/diagnostics")

    assert response.status_code == 404


async def test_database_failure_is_503_not_zeroed(client, monkeypatch):
    http, _holder, _sessions = client
    spaces = (await http.get("/api/super-link/spaces")).json()["items"]
    space_id = spaces[0]["space_id"]

    class BrokenFactory:
        def __call__(self):
            raise SQLAlchemyError("catalog unavailable")

    monkeypatch.setattr(
        "server.routes.super_link.store.get_sessionmaker", lambda: BrokenFactory()
    )
    response = await http.get(f"/api/super-link/spaces/{space_id}/diagnostics")

    assert response.status_code == 503
    assert response.json()["detail"] == "event_chain_unavailable"


async def test_notifier_counters_track_success_and_failure(case):
    sessions, _uid, _pair = case
    observability.reset()
    (space_id,) = await seed_events(sessions, keys=("diag-1",))
    redis = FakeRedis()
    notifier = events.EventNotifier(sessions, redis, channel="test:diagnostics")
    first = await notifier.publish_once()
    assert first >= 1
    assert observability.snapshot()["notifier"]["published"] == first

    (second_space,) = await seed_events(sessions, keys=("diag-2",))
    assert second_space != space_id
    redis.fail = True
    assert await notifier.publish_once() == 0
    assert observability.snapshot()["notifier"]["failed"] == 1
