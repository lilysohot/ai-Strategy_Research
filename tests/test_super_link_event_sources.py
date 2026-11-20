"""Business-side event sources (SSE-T02 T2.4).

Each source must stage exactly one draft per real mutation, in the same
transaction as its business write, and seal before that transaction commits.
Ordinary (non-collaborative) sessions must emit nothing at all.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from server import business_service as biz
from server import dispatch_outbox, store
from server.config import get_config
from server.super_link import events
from server.super_link import models as sl

PROMPT = "Seed prompt that must stay private"
ANSWER = "Answer that must stay private"


async def seed(sessions):
    async with sessions.begin() as session:
        owner = store.User(username=uuid.uuid4().hex, password_hash="unused")
        session.add(owner)
        await session.flush()
        space = sl.SuperLinkSpace(user_id=owner.id, creation_key=uuid.uuid4(), goal="Sources")
        session.add(space)
        await session.flush()
        research = {}
        for role in ("team", "single"):
            row = store.Session(user_id=owner.id, title=f"{role}: sources")
            session.add(row)
            await session.flush()
            session.add(
                sl.SuperLinkParticipant(space_id=space.id, session_id=row.id, role=role)
            )
            research[role] = row.id
        session.add(sl.SuperLinkEventHead(space_id=space.id, stream_epoch=uuid.uuid4()))
        await session.flush()
        return owner.id, space.id, research["team"], research["single"]


@pytest.fixture
async def case(monkeypatch):
    await store.init_db()
    async with store.get_engine().begin() as connection:
        await connection.run_sync(sl.Base.metadata.create_all)
    monkeypatch.setattr(get_config(), "super_link_enabled", True)
    sessions = store.get_sessionmaker()
    uid, space_id, team, single = await seed(sessions)
    return sessions, uid, space_id, team, single


async def rows(sessions, space_id):
    async with sessions() as session:
        return (
            await session.scalars(
                select(sl.SuperLinkEvent)
                .where(sl.SuperLinkEvent.space_id == space_id)
                .order_by(sl.SuperLinkEvent.seq)
            )
        ).all()


def keys(items):
    return [item.change_key for item in items]


async def make_run(sessions, uid, session_id, *, status="queued", pipeline_id="stateful-react-agent"):
    run_id = uuid.uuid4()
    await store.create_run(
        run_id=run_id,
        session_id=session_id,
        user_id=uid,
        prompt=PROMPT,
        pipeline_id=pipeline_id,
        run_dir=f"runs/{run_id}",
        status=status,
    )
    return run_id


async def test_run_lifecycle_is_staged_once_per_real_state(case):
    sessions, uid, space_id, team, _ = case
    run_id = await make_run(sessions, uid, team)
    await store.mark_run_started(run_id=run_id)
    await store.mark_run_started(run_id=run_id)
    await store.update_run_result(run_id=run_id, status="completed", final_answer=ANSWER)
    await store.update_run_result(run_id=run_id, status="completed", final_answer=ANSWER)
    assert await store.mark_run_failed_if_active(run_id=run_id, error="late") is False

    items = await rows(sessions, space_id)
    assert keys(items) == [
        f"run:{run_id}:created",
        f"run:{run_id}:running",
        f"run:{run_id}:terminal:completed",
    ]
    assert {item.type for item in items} == {"sl.run.changed"}
    terminal = items[-1].data_json
    assert terminal["status"] == "completed"
    assert terminal["finished"] is True
    assert PROMPT not in str(terminal) and ANSWER not in str(terminal)
    assert items[0].data_json["started"] is False
    assert items[1].data_json["started"] is True


async def test_artifact_keys_survive_a_to_b_to_a(case):
    sessions, uid, space_id, team, _ = case
    run_id = await make_run(sessions, uid, team)
    version_a = [{"rel_path": "a.md", "size": 1, "sha256": "aa"}]
    version_b = [{"rel_path": "a.md", "size": 1, "sha256": "bb"}]
    for artifacts in (version_a, version_b, version_a, version_a):
        await store.record_artifacts(run_id=run_id, artifacts=artifacts)
    await store.sync_run_artifacts(run_id=run_id, artifacts=[])

    items = [item for item in await rows(sessions, space_id) if item.type == "sl.artifacts.changed"]
    assert len(items) == 4
    assert len({item.change_key for item in items}) == 4
    assert all(item.change_key.startswith(f"artifacts:{run_id}:") for item in items)
    assert items[0].data_json["count"] == 1
    assert len(items[0].data_json["index_sha256"]) == 64


async def test_controls_and_session_deletion_are_staged(case):
    sessions, uid, space_id, team, _ = case
    run_id = await make_run(sessions, uid, team)
    control = await store.create_control(
        run_id=run_id,
        session_id=team,
        user_id=uid,
        kind="approval",
        status="pending",
        external_id="ext-1",
    )
    again = await store.create_control(
        run_id=run_id,
        session_id=team,
        user_id=uid,
        kind="approval",
        status="pending",
        external_id="ext-1",
    )
    assert again.id == control.id
    await store.resolve_control(control_id=control.id, status="approved")
    await store.delete_session(session_id=team, user_id=uid)

    items = await rows(sessions, space_id)
    interventions = [item for item in items if item.type == "sl.intervention.changed"]
    assert keys(interventions) == [
        f"intervention:{control.id}:pending",
        f"intervention:{control.id}:approved",
    ]
    participant = [item for item in items if item.type == "sl.participant.availability_changed"]
    assert len(participant) == 1
    assert participant[0].data_json == {
        "participant_id": str(participant[0].participant_id),
        "role": "team",
        "available": False,
        "reason": "session_deleted",
    }


async def test_failed_approval_persist_leaves_no_intervention_fact(case, monkeypatch):
    """A failed approval write must not leak a phantom approve entry."""
    sessions, uid, space_id, team, _ = case
    run_id = await make_run(sessions, uid, team)

    def boom(*args, **kwargs):
        raise RuntimeError("persist failed")

    monkeypatch.setattr(store, "_stage_intervention", boom)
    with pytest.raises(RuntimeError, match="persist failed"):
        await store.create_control(
            run_id=run_id,
            session_id=team,
            user_id=uid,
            kind="approval",
            status="pending",
            external_id="ext-failed",
        )
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(store.ControlRecord)) == 0
    items = await rows(sessions, space_id)
    assert not [item for item in items if item.type == "sl.intervention.changed"]


async def test_dispatch_outbox_transitions_and_stop(case):
    sessions, uid, space_id, team, _ = case
    first = await make_run(sessions, uid, team, pipeline_id="agent_team")
    second = await make_run(sessions, uid, team, pipeline_id="agent_team")
    async with sessions.begin() as session:
        # SQLite timestamps have second resolution; make FIFO order explicit.
        (await session.get(store.Run, first)).created_at = datetime.now(UTC) - timedelta(
            seconds=2
        )

    async with sessions.begin() as session:
        for run_id in (first, second):
            await dispatch_outbox.enqueue(
                session,
                run_id=run_id,
                user_id=uid,
                research_id=team,
                session_key=str(team),
                prompt="Research",
            )
        await events.seal_changes(session)
    async with sessions.begin() as session:
        # FIFO keeps the later same-session run unclaimed; only the head claims.
        assert [row.run_id for row in await dispatch_outbox.claim_due(session)] == [first]
    async with sessions.begin() as session:
        row = await dispatch_outbox.get_for_run(session, run_id=first)
        await dispatch_outbox.mark_dispatched(
            session, row.id, claim_version=row.claim_version
        )
        await events.seal_changes(session)
    assert await dispatch_outbox.stop_queued_run(run_id=second) is True

    items = await rows(sessions, space_id)
    dispatch_rows = [item for item in items if item.type == "sl.dispatch.changed"]
    assert len(dispatch_rows) == 5, keys(dispatch_rows)
    assert len({item.change_key for item in dispatch_rows}) == 5
    assert f"run:{second}:terminal:stopped" in keys(items)


async def test_continuity_sources_commit_archive_and_conflict(case):
    sessions, uid, space_id, team, _ = case
    first = await make_run(sessions, uid, team, status="completed")
    second = await make_run(sessions, uid, team, status="completed")
    third = await make_run(sessions, uid, team, status="completed")

    await store.upsert_session_conversation(session_id=team, run_id=first, payload="{}")
    await store.upsert_session_conversation(session_id=team, run_id=first, payload="{}")
    await store.upsert_session_conversation(
        session_id=team,
        run_id=second,
        payload="{}",
        expected_head_run_id=first,
        enforce_expected_head=True,
    )
    with pytest.raises(store.ContextHeadConflictError):
        await store.upsert_session_conversation(
            session_id=team,
            run_id=third,
            payload="{}",
            expected_head_run_id=first,
            enforce_expected_head=True,
        )

    items = [item for item in await rows(sessions, space_id) if item.type == "sl.continuity.changed"]
    assert keys(items) == [
        f"continuity:{first}:archived",
        f"continuity:{first}:committed",
        f"continuity:{second}:archived",
        f"continuity:{second}:committed",
        f"continuity:{third}:archived",
    ]
    assert items[1].data_json["outcome"] == "committed"
    assert items[1].data_json["source_run_id"] is None
    assert items[3].data_json["source_run_id"] == str(first)
    assert items[-1].data_json["source_run_id"] == str(second)


async def test_business_transaction_owns_the_seal(case):
    sessions, uid, space_id, team, _ = case
    run_id = uuid.uuid4()
    async with biz.business_transaction() as session:
        await store.add_run(
            session,
            run_id=run_id,
            session_id=team,
            user_id=uid,
            prompt=PROMPT,
            pipeline_id="stateful-react-agent",
            run_dir=f"runs/{run_id}",
        )
    assert keys(await rows(sessions, space_id)) == [f"run:{run_id}:created"]


async def test_ordinary_sessions_emit_nothing(case):
    sessions, uid, space_id, _, _ = case
    async with sessions.begin() as session:
        ordinary = store.Session(user_id=uid, title="ordinary")
        session.add(ordinary)
        await session.flush()
        session_id = ordinary.id
    run_id = await make_run(sessions, uid, session_id)
    await store.record_artifacts(
        run_id=run_id, artifacts=[{"rel_path": "a.md", "size": 1, "sha256": "aa"}]
    )
    await store.create_control(
        run_id=run_id,
        session_id=session_id,
        user_id=uid,
        kind="approval",
        status="pending",
    )
    await store.delete_session(session_id=session_id, user_id=uid)
    assert await rows(sessions, space_id) == []
