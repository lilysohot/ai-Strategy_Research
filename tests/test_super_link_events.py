"""Durable event ledger: sequencing, idempotency, savepoints and commit guards."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from server import store
from server.config import get_config
from server.super_link import events
from server.super_link import models as sl
from server.super_link.contracts import CollaborationError


async def seed_space(sessions, *, owner_id=None, goal="Event ledger"):
    async with sessions.begin() as session:
        if owner_id is None:
            owner = store.User(username=uuid.uuid4().hex, password_hash="unused")
            session.add(owner)
            await session.flush()
            owner_id = owner.id
        space = sl.SuperLinkSpace(user_id=owner_id, creation_key=uuid.uuid4(), goal=goal)
        session.add(space)
        await session.flush()
        for role in ("team", "single"):
            research = store.Session(user_id=owner_id, title=f"{role}: {goal}")
            session.add(research)
            await session.flush()
            session.add(
                sl.SuperLinkParticipant(space_id=space.id, session_id=research.id, role=role)
            )
        session.add(
            sl.SuperLinkEventHead(space_id=space.id, stream_epoch=uuid.uuid4())
        )
        await session.flush()
        return owner_id, space.id


async def space_sessions(sessions, space_id):
    async with sessions.begin() as session:
        rows = (
            await session.scalars(
                select(sl.SuperLinkParticipant).where(
                    sl.SuperLinkParticipant.space_id == space_id
                )
            )
        ).all()
        return {row.role: row.session_id for row in rows}


async def head(sessions, space_id):
    async with sessions.begin() as session:
        row = await session.get(sl.SuperLinkEventHead, space_id)
        assert row is not None
        return row.stream_epoch, row.last_seq, row.min_after


async def event_rows(sessions, space_id):
    async with sessions.begin() as session:
        return (
            await session.scalars(
                select(sl.SuperLinkEvent)
                .where(sl.SuperLinkEvent.space_id == space_id)
                .order_by(sl.SuperLinkEvent.seq)
            )
        ).all()


async def stage(session, space_id, key, *, type="sl.action.recorded", **kwargs):
    return await events.stage_for_space(
        session,
        space_id,
        type=type,
        change_key=key,
        data=kwargs.pop("data", {"action": "note", "outcome": "ok"}),
        **kwargs,
    )


@pytest.fixture
async def case(monkeypatch):
    await store.init_db()
    async with store.get_engine().begin() as connection:
        await connection.run_sync(sl.Base.metadata.create_all)
    monkeypatch.setattr(get_config(), "super_link_enabled", True)
    sessions = store.get_sessionmaker()
    uid, space_id = await seed_space(sessions)
    _, other_space = await seed_space(sessions, owner_id=uid, goal="Isolated")
    return sessions, uid, space_id, uuid.uuid4(), other_space


async def test_sequences_are_per_space_and_envelopes_carry_cursors(case):
    sessions, uid, space_id, _, other_space = case
    async with sessions.begin() as session:
        await stage(session, space_id, "a1", data={"action": "one"}, invalidate=("runs",))
        await stage(session, space_id, "a2", data={"action": "two"})
        await stage(session, other_space, "b1")
        notifications = await events.seal_changes(session)
    assert {(n.space_id, n.head_seq) for n in notifications} == {
        (space_id, 2),
        (other_space, 1),
    }

    page = await events.read_events(user_id=uid, space_id=space_id, after=None, limit=200)
    assert [row["seq"] for row in page.events] == ["1", "2"]
    assert page.head_seq == 2
    first = page.events[0]
    assert first["type"] == "sl.action.recorded"
    assert first["data"] == {"action": "one"}
    assert first["invalidate"] == ["runs"]
    assert first["space_id"] == str(space_id)
    assert first["cursor"] == events.format_cursor(
        space_id, page.stream_epoch, 1
    )
    assert page.next_cursor == events.format_cursor(space_id, page.stream_epoch, 2)

    one = await events.read_events(user_id=uid, space_id=space_id, after=None, limit=1)
    assert [row["seq"] for row in one.events] == ["1"]
    assert one.next_cursor == events.format_cursor(space_id, page.stream_epoch, 1)
    rest = await events.read_events(
        user_id=uid, space_id=space_id, after=one.next_cursor, limit=200
    )
    assert [row["seq"] for row in rest.events] == ["2"]

    empty = await events.read_events(
        user_id=uid, space_id=space_id, after=page.next_cursor, limit=200
    )
    assert empty.events == [] and empty.next_cursor == page.next_cursor

    other_page = await events.read_events(
        user_id=uid, space_id=other_space, after=None, limit=200
    )
    assert [row["seq"] for row in other_page.events] == ["1"]


async def test_read_events_never_returns_events_beyond_reported_head(case):
    sessions, uid, space_id, _, _ = case
    async with sessions.begin() as session:
        await stage(session, space_id, "visible")
        await events.seal_changes(session)
    epoch, last_seq, _ = await head(sessions, space_id)
    assert last_seq == 1
    # Simulate a concurrent commit landing after this reader observed the head.
    async with sessions.begin() as session:
        session.add(
            sl.SuperLinkEvent(
                space_id=space_id,
                stream_epoch=epoch,
                seq=2,
                event_id=uuid.uuid4(),
                transaction_id=uuid.uuid4(),
                change_key="ahead-of-head",
                type="sl.action.recorded",
                schema_version=1,
                source_kind="space",
                source_id=str(space_id),
                data_json={"action": "late"},
                invalidate_json=[],
            )
        )
    page = await events.read_events(user_id=uid, space_id=space_id, after=None, limit=200)
    assert [row["seq"] for row in page.events] == ["1"]
    assert page.head_seq == 1


async def test_read_events_rejects_foreign_space_bad_cursor_and_limit(case):
    sessions, uid, space_id, other_uid, _ = case
    async with sessions.begin() as session:
        await stage(session, space_id, "a1")
        await events.seal_changes(session)
    epoch, _, _ = await head(sessions, space_id)

    with pytest.raises(CollaborationError, match="not_found"):
        await events.read_events(user_id=other_uid, space_id=space_id, after=None)
    with pytest.raises(CollaborationError, match="invalid_cursor"):
        await events.read_events(user_id=uid, space_id=space_id, after="sl1:bogus")
    with pytest.raises(CollaborationError, match="invalid_cursor"):
        await events.read_events(
            user_id=uid,
            space_id=space_id,
            after=events.format_cursor(uuid.uuid4(), epoch, 1),
        )
    with pytest.raises(CollaborationError, match="invalid_cursor"):
        await events.read_events(
            user_id=uid, space_id=space_id, after=events.format_cursor(space_id, epoch, 99)
        )
    with pytest.raises(CollaborationError, match="resync_required"):
        await events.read_events(
            user_id=uid,
            space_id=space_id,
            after=events.format_cursor(space_id, uuid.uuid4(), 1),
        )
    with pytest.raises(CollaborationError, match="invalid_limit"):
        await events.read_events(user_id=uid, space_id=space_id, after=None, limit=0)
    with pytest.raises(CollaborationError, match="invalid_limit"):
        await events.read_events(user_id=uid, space_id=space_id, after=None, limit=201)

    async with sessions.begin() as session:
        row = await session.get(sl.SuperLinkEventHead, space_id)
        assert row is not None
        row.min_after = 5
    with pytest.raises(CollaborationError, match="resync_required"):
        await events.read_events(
            user_id=uid,
            space_id=space_id,
            after=events.format_cursor(space_id, epoch, 1),
        )


async def test_retry_with_same_key_reuses_event_and_conflicts_on_change(case):
    sessions, _, space_id, _, _ = case
    data = {"status": "queued"}
    async with sessions.begin() as session:
        await stage(session, space_id, "run:1:created", type="sl.run.changed", data=data)
        notes = await events.seal_changes(session)
        assert notes[0].head_seq == 1
    async with sessions.begin() as session:
        await stage(session, space_id, "run:1:created", type="sl.run.changed", data=data)
        notes = await events.seal_changes(session)
        assert notes == []
    _epoch, last_seq, _ = await head(sessions, space_id)
    assert last_seq == 1
    assert len(await event_rows(sessions, space_id)) == 1

    with pytest.raises(CollaborationError, match="change_key_conflict"):
        async with sessions.begin() as session:
            await stage(session, space_id, "run:1:created", type="sl.run.changed", data={"status": "running"})
            await events.seal_changes(session)
            await stage(session, space_id, "another", data={})
    assert (await head(sessions, space_id))[1] == 1
    assert [row.change_key for row in await event_rows(sessions, space_id)] == ["run:1:created"]


async def test_same_key_twice_in_one_transaction_deduplicates_or_conflicts(case):
    sessions, _, space_id, _, _ = case
    async with sessions.begin() as session:
        await stage(session, space_id, "dup", data={"action": "same"})
        await stage(session, space_id, "dup", data={"action": "same"})
        notes = await events.seal_changes(session)
    assert notes[0].head_seq == 1
    assert len(await event_rows(sessions, space_id)) == 1

    with pytest.raises(CollaborationError, match="change_key_conflict"):
        async with sessions.begin() as session:
            await stage(session, space_id, "dup-2", data={"action": "same"})
            await stage(session, space_id, "dup-2", data={"action": "different"})
            await events.seal_changes(session)
    assert len(await event_rows(sessions, space_id)) == 1


async def test_unsealed_commit_rolls_back_business_and_events(case):
    sessions, uid, space_id, _, _ = case
    marker = f"unsealed-{uuid.uuid4().hex}"
    with pytest.raises(CollaborationError, match="unsealed_event_drafts"):
        async with sessions.begin() as session:
            await stage(session, space_id, "a1")
            session.add(store.Session(user_id=uid, title=marker))
    assert (await head(sessions, space_id))[1] == 0
    assert await event_rows(sessions, space_id) == []
    async with sessions.begin() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(store.Session)
                .where(store.Session.title == marker)
            )
            == 0
        )


async def test_missing_event_head_rolls_back_business_and_events(case):
    sessions, uid, _, _, _ = case
    async with sessions.begin() as session:
        orphan = sl.SuperLinkSpace(user_id=uid, creation_key=uuid.uuid4(), goal="No head")
        session.add(orphan)
        await session.flush()
        orphan_id = orphan.id
    marker = f"orphan-{uuid.uuid4().hex}"
    with pytest.raises(CollaborationError, match="event_head_missing"):
        async with sessions.begin() as session:
            session.add(store.Session(user_id=uid, title=marker))
            await stage(session, orphan_id, "orphan")
            await events.seal_changes(session)
    assert await event_rows(sessions, orphan_id) == []
    async with sessions.begin() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(store.Session)
                .where(store.Session.title == marker)
            )
            == 0
        )


async def test_stage_after_seal_is_rejected(case):
    sessions, _, space_id, _, _ = case
    with pytest.raises(CollaborationError, match="event_seal_closed"):
        async with sessions.begin() as session:
            await stage(session, space_id, "a1")
            await events.seal_changes(session)
            await stage(session, space_id, "a2")


async def test_orm_writes_after_seal_are_rejected(case):
    sessions, _, space_id, _, _ = case
    # A flush after sealing is rejected before SQL is emitted.
    with pytest.raises(CollaborationError, match="event_seal_business_writes"):
        async with sessions.begin() as session:
            space = await session.get(sl.SuperLinkSpace, space_id)
            assert space is not None
            await stage(session, space_id, "a1")
            await events.seal_changes(session)
            space.paused = True
            await session.flush()
    # A new ORM object after sealing is rejected on commit.
    with pytest.raises(CollaborationError, match="event_seal_business_writes"):
        async with sessions.begin() as session:
            await stage(session, space_id, "a2")
            await events.seal_changes(session)
            session.add(store.Session(user_id=(await session.get(sl.SuperLinkSpace, space_id)).user_id, title="late"))
    assert await event_rows(sessions, space_id) == []


async def test_managed_savepoint_rolls_back_or_merges_drafts(case):
    sessions, _, space_id, _, _ = case
    async with sessions.begin() as session:
        with pytest.raises(RuntimeError, match="discard"):
            async with events.savepoint(session):
                await stage(session, space_id, "discarded")
                raise RuntimeError("discard")
        async with events.savepoint(session):
            await stage(session, space_id, "kept")
        await stage(session, space_id, "outer")
        notes = await events.seal_changes(session)
    assert notes[0].head_seq == 2
    assert [row.change_key for row in await event_rows(sessions, space_id)] == ["kept", "outer"]


async def test_nested_managed_savepoints_discard_only_the_inner_scope(case):
    sessions, _, space_id, _, _ = case
    async with sessions.begin() as session:
        async with events.savepoint(session):
            await stage(session, space_id, "outer")
            with pytest.raises(RuntimeError, match="inner"):
                async with events.savepoint(session):
                    await stage(session, space_id, "inner")
                    raise RuntimeError("inner")
        await events.seal_changes(session)
    assert [row.change_key for row in await event_rows(sessions, space_id)] == ["outer"]


async def test_unmanaged_savepoint_cannot_stage(case):
    sessions, _, space_id, _, _ = case
    with pytest.raises(CollaborationError, match="event_unmanaged_savepoint"):
        async with sessions.begin() as session:
            async with session.begin_nested():
                await stage(session, space_id, "unmanaged")


async def test_seal_inside_savepoint_is_rejected(case):
    sessions, _, space_id, _, _ = case
    with pytest.raises(CollaborationError, match="event_seal_inside_savepoint"):
        async with sessions.begin() as session:
            async with events.savepoint(session):
                await stage(session, space_id, "a1")
                await events.seal_changes(session)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"type": "sl.unknown", "change_key": "k", "data": {}}, "invalid_event_type"),
        ({"type": "sl.action.recorded", "change_key": "", "data": {}}, "invalid_change_key"),
        (
            {"type": "sl.action.recorded", "change_key": "k" * 201, "data": {}},
            "invalid_change_key",
        ),
        (
            {"type": "sl.action.recorded", "change_key": "k", "data": {"bad": object()}},
            "invalid_event_payload",
        ),
        (
            {"type": "sl.action.recorded", "change_key": "k", "data": ["not", "a", "map"]},
            "invalid_event_payload",
        ),
        (
            {"type": "sl.action.recorded", "change_key": "k", "data": {"blob": "x" * 20000}},
            "event_payload_too_large",
        ),
        (
            {
                "type": "sl.action.recorded",
                "change_key": "k",
                "data": {},
                "invalidate": ("secret_view",),
            },
            "invalid_event_invalidate",
        ),
        (
            {
                "type": "sl.action.recorded",
                "change_key": "k",
                "data": {},
                "source_id": "s" * 65,
            },
            "invalid_event_source",
        ),
    ],
)
async def test_change_validation(case, change, code):
    sessions, _, space_id, _, _ = case
    kwargs = {
        "type": change["type"],
        "change_key": change["change_key"],
        "data": change["data"],
        "invalidate": change.get("invalidate", ()),
        "source_id": change.get("source_id"),
    }
    with pytest.raises(CollaborationError, match=code):
        async with sessions.begin() as session:
            await events.stage_for_space(session, space_id, **kwargs)


async def test_tracking_and_disabled_mode_have_no_side_effects(case, monkeypatch):
    sessions, _, space_id, _, _ = case
    by_role = await space_sessions(sessions, space_id)
    async with sessions.begin() as session:
        assert await events.tracking(session, session_id=by_role["team"]) is True
        assert await events.tracking(session, session_id=uuid.uuid4()) is False
        assert events._state(session.sync_session) is None

    monkeypatch.setattr(get_config(), "super_link_enabled", False)
    async with sessions.begin() as session:
        assert await events.tracking(session, session_id=by_role["team"]) is False
        assert (
            await events.stage_for_session(
                session, by_role["team"], type="sl.action.recorded", change_key="off", data={}
            )
            is False
        )
        assert events._state(session.sync_session) is None
        session.add(store.Session(user_id=(await session.get(sl.SuperLinkSpace, space_id)).user_id, title="plain"))
    assert await event_rows(sessions, space_id) == []


async def test_listener_installation_is_idempotent_and_plain_sessions_unaffected(case):
    events.install_listeners()
    events.install_listeners()
    assert events._INSTALLED is True
    sessions, uid, space_id, _, _ = case
    async with sessions.begin() as session:
        session.add(store.Session(user_id=uid, title="plain-transaction"))
    assert await event_rows(sessions, space_id) == []
