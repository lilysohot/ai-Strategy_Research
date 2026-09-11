"""Pagination for the session list and the turn list.

A conversation can hold thousands of turns; both endpoints used to return
everything in one response. Sessions page forward with limit/offset, turns page
*backwards* with ``before_seq`` because the interesting end of a conversation is
the most recent one.

Run with::
    uv run pytest tests/test_sessions_pagination.py -q
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from server.store import create_session, create_user, init_db, list_turns


@pytest.fixture
async def client(tmp_path):
    """App client backed by a throwaway SQLite database."""
    from server.config import get_config
    from server.store import reset_engine

    cfg = get_config()
    original_url = cfg.database_url
    original_key = cfg.master_key
    original_jwt = cfg.jwt_secret
    cfg.database_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    cfg.master_key = f"test-master-key-{uuid.uuid4().hex}"
    cfg.jwt_secret = ""
    await reset_engine()
    await init_db()

    from server.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    cfg.database_url = original_url
    cfg.master_key = original_key
    cfg.jwt_secret = original_jwt
    await reset_engine()


async def _login(client) -> dict[str, str]:
    await client.post(
        "/api/auth/register", json={"username": "pager", "password": "Str0ngPass1"}
    )
    resp = await client.post(
        "/api/auth/login", json={"username": "pager", "password": "Str0ngPass1"}
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_session_list_paginates(client):
    headers = await _login(client)
    for i in range(3):
        resp = await client.post("/api/sessions", json={"title": f"s{i}"}, headers=headers)
        assert resp.status_code == 201

    page = await client.get("/api/sessions?limit=1", headers=headers)
    assert page.status_code == 200
    body = page.json()
    assert len(body["sessions"]) == 1
    assert body["total"] == 3
    assert body["has_more"] is True

    last = await client.get("/api/sessions?limit=10&offset=2", headers=headers)
    assert len(last.json()["sessions"]) == 1
    assert last.json()["has_more"] is False


async def test_session_limit_is_bounded(client):
    """A caller must not be able to ask for an unbounded page."""
    headers = await _login(client)
    assert (await client.get("/api/sessions?limit=0", headers=headers)).status_code == 422
    assert (
        await client.get("/api/sessions?limit=9999", headers=headers)
    ).status_code == 422


async def test_turns_return_the_most_recent_page(client):
    headers = await _login(client)
    session = (
        await client.post("/api/sessions", json={"title": "t"}, headers=headers)
    ).json()
    sid = session["id"]

    user_row = await create_user(username="turn-seeder", password_hash="x")
    await create_session(user_id=user_row.id, title="seed")
    # Seed turns directly: the HTTP surface only appends one per run.
    from server.store import append_turn

    for i in range(1, 6):
        await append_turn(session_id=uuid.UUID(sid), role="user", content=f"m{i}")

    page = await client.get(f"/api/sessions/{sid}/turns?limit=2", headers=headers)
    assert page.status_code == 200
    body = page.json()
    assert [t["seq"] for t in body["turns"]] == [4, 5]
    assert body["has_more"] is True

    older = await client.get(
        f"/api/sessions/{sid}/turns?limit=2&before_seq=4", headers=headers
    )
    assert [t["seq"] for t in older.json()["turns"]] == [2, 3]


async def test_before_seq_walks_to_the_start_without_duplicates(client):
    """Paging backwards must never repeat or skip a turn."""
    headers = await _login(client)
    sid = (
        await client.post("/api/sessions", json={"title": "t"}, headers=headers)
    ).json()["id"]

    from server.store import append_turn

    for i in range(1, 8):
        await append_turn(session_id=uuid.UUID(sid), role="user", content=f"m{i}")

    seen: list[int] = []
    before_seq: int | None = None
    for _ in range(5):
        url = f"/api/sessions/{sid}/turns?limit=3"
        if before_seq is not None:
            url += f"&before_seq={before_seq}"
        page = (await client.get(url, headers=headers)).json()
        if not page["turns"]:
            break
        seen = [t["seq"] for t in page["turns"]] + seen
        before_seq = page["turns"][0]["seq"]
        if not page["has_more"]:
            break

    assert seen == [1, 2, 3, 4, 5, 6, 7]


async def test_store_list_turns_without_limit_is_unchanged():
    """No limit must still mean "everything", in ascending order."""
    # No client fixture here, so create the schema in the isolated database the
    # global conftest points at.
    await init_db()
    user = await create_user(username=f"u-{uuid.uuid4().hex[:8]}", password_hash="x")
    session = await create_session(user_id=user.id, title=None)

    from server.store import append_turn

    for i in range(3):
        await append_turn(session_id=session.id, role="assistant", content=f"m{i}")

    rows = await list_turns(session_id=session.id)
    assert len(rows) == 3
    assert [r.seq for r in rows] == [1, 2, 3]
