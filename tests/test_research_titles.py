"""Research labels follow submitted messages, including legacy blank titles."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from server import store
from server.session_titles import research_title


@pytest.fixture
async def research_client():
    await store.init_db()
    from server.app import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/auth/register", json={
            "username": "research_titles", "password": "Str0ngPass1",
        })
        assert response.status_code == 201
        user_id = uuid.UUID(response.json()["id"])
        login = await client.post("/api/auth/login", json={
            "username": "research_titles", "password": "Str0ngPass1",
        })
        client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        yield client, user_id


@pytest.mark.parametrize("atomic", [False, True])
async def test_blank_research_gets_topic_after_greeting(research_client, atomic):
    client, user_id = research_client
    created = (await client.post("/api/sessions", json={})).json()
    sid = uuid.UUID(created["id"])
    assert created["title"] == "新对话"
    assert created["turn_count"] == 0
    await store.append_turn(session_id=sid, role="user", content="你好")
    await store.append_turn(session_id=sid, role="assistant", content="欢迎，请问研究什么？")
    greeting = (await client.get(f"/api/sessions/{sid}")).json()
    assert greeting["title"] == "问候与交流"
    prompt = "请帮我分析贵州茅台的估值和现金流"
    if atomic:
        async with store.get_sessionmaker()() as db:
            await store.ensure_session_in(db, session_id=sid, user_id=user_id, title=prompt)
            await store.append_turn_in(db, session_id=sid, role="user", content=prompt)
            await db.commit()
    else:
        await store.append_turn(session_id=sid, role="user", content=prompt)
    detail = (await client.get(f"/api/sessions/{sid}")).json()
    assert detail["title"] == "分析贵州茅台的估值和现金流"
    assert detail["turn_count"] == 3
    assert detail["updated_at"] >= created["updated_at"]
    assert (await client.get("/api/sessions")).json()["sessions"][0] == detail
    persisted = await store.get_session(session_id=sid, user_id=user_id)
    assert persisted.title == detail["title"]


async def test_manual_name_preserved_and_seeded_counts(research_client):
    client, _ = research_client
    created = (await client.post("/api/sessions", json={
        "title": "我的长期持仓研究", "first_message": "分析贵州茅台",
    })).json()
    assert created["title"] == "我的长期持仓研究"
    assert created["turn_count"] == 1
    await store.append_turn(session_id=uuid.UUID(created["id"]), role="user", content="研究腾讯")
    assert (await client.get(f"/api/sessions/{created['id']}")).json()["title"] == created["title"]


async def test_history_titles_are_scoped_and_do_not_rewrite_storage(research_client):
    client, user_id = research_client
    legacy = await store.create_session(user_id=user_id)
    # Direct legacy rows reproduce data written before automatic naming existed.
    async with store.get_sessionmaker()() as db:
        db.add_all([
            store.Turn(session_id=legacy.id, seq=1, role="user", content="你好"),
            store.Turn(session_id=legacy.id, seq=2, role="assistant", content="不要使用助手思考作标题"),
            store.Turn(session_id=legacy.id, seq=3, role="user", content="比较宁德时代和比亚迪的盈利能力"),
        ])
        other = store.User(username="other_titles", password_hash="unused")
        db.add(other)
        await db.flush()
        foreign = store.Session(user_id=other.id, title="新对话")
        db.add(foreign)
        await db.flush()
        db.add(store.Turn(session_id=foreign.id, seq=1, role="user", content="其他用户的私密研究"))
        await db.commit()
    listing = (await client.get("/api/sessions?limit=1")).json()
    assert listing["total"] == 1
    assert listing["sessions"][0]["title"] == "比较宁德时代和比亚迪的盈利能力"
    assert listing["sessions"][0]["turn_count"] == 3
    assert (await client.get(f"/api/sessions/{foreign.id}")).status_code == 404
    stored = await store.get_session(session_id=legacy.id, user_id=user_id)
    assert stored.title == "新对话"


async def test_rolled_back_submission_does_not_rename_research(research_client):
    client, _ = research_client
    created = (await client.post("/api/sessions", json={})).json()
    sid = uuid.UUID(created["id"])
    async with store.get_sessionmaker()() as db:
        # Force a real outer write transaction for SQLite before its savepoint.
        await db.execute(store.update(store.Session).where(store.Session.id == sid).values(title="新对话"))
        await store.append_turn_in(db, session_id=sid, role="user", content="分析腾讯财报")
        await db.rollback()
    detail = (await client.get(f"/api/sessions/{sid}")).json()
    assert detail["title"] == "新对话"
    assert detail["turn_count"] == 0


def test_excerpt_is_single_line_and_bounded():
    assert research_title("你好， 请帮我分析腾讯\n  财报") == "分析腾讯 财报"
    assert research_title("你好！") is None
    title = research_title("分析" + "非常长的研究主题" * 30)
    assert len(title) == 60
    assert title.endswith("…")
