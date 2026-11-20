"""Independent web entry: atomic creation, admission gates and session isolation."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from server import dispatch_outbox, store
from server.config import get_config
from server.deps import get_current_user
from server.routes import super_link as routes
from server.routes.sessions import router as session_router
from tests.test_super_link import make_run
from tests.test_super_link_runtime import case as case


@pytest.fixture
async def client(case, monkeypatch):
    sessions, uid, _ = case
    monkeypatch.setattr(get_config(), "agent_team_enabled", True)
    monkeypatch.setattr(get_config(), "sandbox_backend", "bwrap")
    monkeypatch.setattr(routes, "probe_data_root", lambda: None)
    async with sessions() as session:
        user = await session.get(store.User, uid)
    app = FastAPI()
    app.include_router(routes.router)
    app.include_router(session_router)
    app.dependency_overrides[get_current_user] = lambda: user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_create_starts_one_team_run_atomically_and_replays(case, client):
    sessions, _, _ = case
    body = {"creation_key": str(uuid.uuid4()), "goal": "Research the latest reports"}
    first = await client.post("/api/super-link/spaces", json=body)
    assert first.status_code == 201, first.text
    second = await client.post("/api/super-link/spaces", json=body)
    assert second.json() == first.json()
    conflict = await client.post("/api/super-link/spaces", json=body | {"goal": "changed"})
    assert conflict.status_code == 409
    async with sessions() as session:
        rid = uuid.UUID(first.json()["initial_run_id"])
        run = await session.get(store.Run, rid)
        assert run.pipeline_id == "agent_team" and run.status == "queued"
        assert body["goal"] in run.prompt
        assert await session.scalar(select(func.count()).select_from(store.RunDispatch)) == 1
        assert await session.scalar(select(func.count()).select_from(store.Turn)) == 1
        dispatch = await dispatch_outbox.get_for_run(session, run_id=rid)
        assert (
            dispatch.prompt_addendum.startswith("[super-link")
            or "super-link" in dispatch.prompt_addendum
        )
    detail = (await client.get(f"/api/super-link/spaces/{first.json()['space_id']}")).json()
    assert (
        detail["automatic_budget"]["used"] == 0
    )  # Initial user request is not an automatic follow-up.


async def test_create_dispatch_failure_rolls_back_both_sessions_and_space(
    case, client, monkeypatch
):
    sessions, _, _ = case

    async def unavailable(*args, **kwargs):
        raise RuntimeError("simulated outbox failure")

    monkeypatch.setattr(dispatch_outbox, "enqueue", unavailable)
    async with sessions() as session:
        before = await session.scalar(select(func.count()).select_from(store.Session))
    with pytest.raises(RuntimeError):
        await client.post(
            "/api/super-link/spaces", json={"creation_key": str(uuid.uuid4()), "goal": "Goal"}
        )
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(store.Session)) == before
        assert await session.scalar(select(func.count()).select_from(store.Run)) == 0


@pytest.mark.parametrize(
    "gate", ["super_link_enabled", "agent_team_enabled", "dispatch_enabled", "restore_mode"]
)
async def test_creation_respects_service_gates(case, client, monkeypatch, gate):
    monkeypatch.setattr(get_config(), gate, gate == "restore_mode")
    response = await client.post(
        "/api/super-link/spaces", json={"creation_key": str(uuid.uuid4()), "goal": "Goal"}
    )
    assert response.status_code == (404 if gate == "super_link_enabled" else 503)
    async with case[0]() as session:
        assert await session.scalar(select(func.count()).select_from(store.Run)) == 0


async def test_collaboration_sessions_stay_separate_even_when_disabled(case, client, monkeypatch):
    _sessions, uid, _ = case
    ordinary = await store.create_session(user_id=uid, title="ordinary research")
    for enabled in (True, False):
        monkeypatch.setattr(get_config(), "super_link_enabled", enabled)
        result = (await client.get("/api/sessions?limit=1")).json()
        assert result["total"] == 1 and result["has_more"] is False
        assert [row["id"] for row in result["sessions"]] == [str(ordinary.id)]


async def test_newest_run_pagination_and_foreign_cursor(case, client):
    sessions, uid, pair = case
    ids = []
    for i in range(3):
        bound = await make_run(sessions, uid, pair)
        ids.append(bound.run_id)
        async with sessions.begin() as session:
            (await session.get(store.Run, bound.run_id)).created_at = datetime.now(UTC) + timedelta(
                seconds=i
            )
    root = f"/api/super-link/spaces/{pair.space_id}/runs"
    first = (await client.get(root, params={"newest_first": "true", "limit": 2})).json()
    assert [r["run_id"] for r in first["items"]] == [str(ids[2]), str(ids[1])]
    second = (
        await client.get(root, params={"newest_first": "true", "after": first["next_after"]})
    ).json()
    assert [r["run_id"] for r in second["items"]] == [str(ids[0])]
    assert (await client.get(root, params={"after": str(uuid.uuid4())})).status_code == 404
