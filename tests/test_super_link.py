"""Public foundation behavior, with no model, monitor or live service access."""

import hashlib
import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from server import store
from server.super_link import models as sl
from server.super_link import service
from server.super_link.contracts import CollaborationError, DeliveryContent, SenderBinding


async def seed_pair(sessions):
    async with sessions.begin() as session:
        owner = store.User(username=uuid.uuid4().hex, password_hash="unused")
        session.add(owner)
        await session.flush()
        pair = await service.create_pair(
            session, user_id=owner.id, creation_key=uuid.uuid4(), goal="Find research candidates"
        )
        return owner.id, pair


async def make_run(sessions, user_id, pair, *, role="team", status="completed", archive=True):
    session_id = pair.team_session_id if role == "team" else pair.single_session_id
    participant_id = pair.team_id if role == "team" else pair.single_id
    async with sessions.begin() as session:
        run = store.Run(
            session_id=session_id,
            user_id=user_id,
            status=status,
            pipeline_id="agent_team" if role == "team" else "stateful-react-agent",
            prompt="Test execution stand-in",
            run_dir="unused-test-directory",
            finished_at=datetime.now(UTC) if status != "running" else None,
        )
        session.add(run)
        await session.flush()
        if archive:
            payload = '{"private":"must not reach the peer"}'
            session.add(
                store.RunContextSource(
                    run_id=run.id,
                    session_id=session_id,
                    pipeline_id=run.pipeline_id,
                    native_payload=payload,
                    native_sha256=hashlib.sha256(payload.encode()).hexdigest(),
                )
            )
        return SenderBinding(user_id, pair.space_id, participant_id, run.id)


async def registered(sessions, binding, recipient_id, **kwargs):
    async with sessions.begin() as session:
        row = await service.register(
            session,
            binding=binding,
            recipient_id=recipient_id,
            registration_key=kwargs.pop("registration_key", uuid.uuid4()),
            content=kwargs.pop("content", DeliveryContent(body="Research with explicit evidence")),
            **kwargs,
        )
        return row.id


async def published(sessions, binding, recipient_id, **kwargs):
    mid = await registered(sessions, binding, recipient_id, **kwargs)
    async with sessions.begin() as session:
        await service.publish(session, binding=binding, message_id=mid)
    return mid


@pytest.fixture
async def case():
    await store.init_db()
    async with store.get_engine().begin() as connection:
        await connection.run_sync(sl.Base.metadata.create_all)
    sessions = store.get_sessionmaker()
    uid, pair = await seed_pair(sessions)
    binding = await make_run(sessions, uid, pair)
    return sessions, uid, pair, binding


async def test_round_trip_preserves_private_history_and_does_not_dispatch(case):
    sessions, uid, pair, binding = case
    first = await published(sessions, binding, pair.single_id)
    async with sessions.begin() as session:
        await service.receive(session, first)
        await service.receive(session, first)
        messages = await service.inbox(session, user_id=uid, participant_id=pair.single_id)
        assert [m.id for m in messages] == [first]
        assert "private" not in str(messages[0].content_json)
        assert (await session.get(sl.SuperLinkReceipt, first)).state == "awaiting_check"
    # The receiving agent is a test stand-in; the foundation never starts it.
    reply_binding = await make_run(sessions, uid, pair, role="single")
    reply = await published(sessions, reply_binding, pair.team_id, in_reply_to=first)
    async with sessions.begin() as session:
        await service.receive(session, reply)
        messages = await service.inbox(session, user_id=uid, participant_id=pair.team_id)
        assert [m.id for m in messages] == [reply]
        assert messages[0].request_id == first and messages[0].in_reply_to == first
        assert await session.scalar(select(func.count()).select_from(store.Run)) == 2
        for model in (store.RunDispatch, store.Turn, store.SessionConversation):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize("status", ["running", "queued", "failed", "stopped"])
async def test_unfinished_or_failed_run_cannot_publish(case, status):
    sessions, uid, pair, _ = case
    binding = await make_run(sessions, uid, pair, status=status)
    mid = await registered(sessions, binding, pair.single_id)
    with pytest.raises(CollaborationError, match="source_run_not_complete"):
        async with sessions.begin() as session:
            await service.publish(session, binding=binding, message_id=mid)
    async with sessions.begin() as session:
        assert (await session.get(sl.SuperLinkMessage, mid)).state == "registered"
        assert await session.get(sl.SuperLinkOutbox, mid) is None
        await service.receive(session, mid)
        assert await session.get(sl.SuperLinkReceipt, mid) is None


async def test_missing_continuity_can_retry_publication_after_repair(case):
    sessions, uid, pair, _ = case
    binding = await make_run(sessions, uid, pair, archive=False)
    mid = await registered(sessions, binding, pair.single_id)
    with pytest.raises(CollaborationError, match="continuity_not_saved"):
        async with sessions.begin() as session:
            await service.publish(session, binding=binding, message_id=mid)
    async with sessions.begin() as session:
        session.add(
            store.RunContextSource(
                run_id=binding.run_id,
                session_id=pair.team_session_id,
                pipeline_id="agent_team",
                native_payload="saved",
                native_sha256=hashlib.sha256(b"saved").hexdigest(),
            )
        )
    async with sessions.begin() as session:
        await service.publish(session, binding=binding, message_id=mid)
        await service.publish(session, binding=binding, message_id=mid)
        assert await session.scalar(select(func.count()).select_from(sl.SuperLinkOutbox)) == 1


async def test_duplicate_registration_is_stable_but_conflicting_payload_rejected(case):
    sessions, _, pair, binding = case
    key = uuid.uuid4()
    first = await registered(sessions, binding, pair.single_id, registration_key=key)
    assert await registered(sessions, binding, pair.single_id, registration_key=key) == first
    with pytest.raises(CollaborationError, match="registration_key_conflict"):
        await registered(
            sessions,
            binding,
            pair.single_id,
            registration_key=key,
            content=DeliveryContent(body="Changed content under same identity"),
        )


async def test_publish_and_outbox_rollback_together(case):
    sessions, _, pair, binding = case
    mid = await registered(sessions, binding, pair.single_id)
    with pytest.raises(RuntimeError, match="crash"):
        async with sessions.begin() as session:
            await service.publish(session, binding=binding, message_id=mid)
            raise RuntimeError("crash")
    async with sessions.begin() as session:
        assert (await session.get(sl.SuperLinkMessage, mid)).state == "registered"
        assert await session.get(sl.SuperLinkOutbox, mid) is None


async def test_other_space_owner_run_and_forged_reply_rejected(case):
    sessions, uid, pair, binding = case
    other_uid, other = await seed_pair(sessions)
    with pytest.raises(CollaborationError, match="invalid_recipient"):
        await registered(sessions, binding, other.single_id)
    with pytest.raises(CollaborationError, match="space_not_found"):
        await registered(sessions, replace(binding, user_id=other_uid), pair.single_id)
    with pytest.raises(CollaborationError, match="invalid_sender_binding"):
        await registered(sessions, replace(binding, participant_id=pair.single_id), pair.team_id)
    with pytest.raises(CollaborationError, match="invalid_reply"):
        await registered(sessions, binding, pair.single_id, in_reply_to=uuid.uuid4())
    async with sessions.begin() as session:
        with pytest.raises(CollaborationError, match="space_not_found"):
            await service.inbox(session, user_id=uid, participant_id=other.single_id)


async def test_create_pair_idempotency_and_exclusive_new_sessions(case):
    sessions, uid, pair, _ = case
    key = uuid.uuid4()
    async with sessions.begin() as session:
        args = {"user_id": uid, "creation_key": key, "goal": "A second independent collaboration"}
        second = await service.create_pair(session, **args)
        assert second == await service.create_pair(session, **args)
        assert {pair.team_session_id, pair.single_session_id}.isdisjoint(
            {second.team_session_id, second.single_session_id}
        )
        with pytest.raises(CollaborationError, match="creation_key_conflict"):
            await service.create_pair(session, **{**args, "goal": "Different"})


@pytest.mark.parametrize("damage", [{"schema_version": 2, "body": "future"}, {"body": "changed"}])
async def test_bad_message_is_quarantined_without_blocking_other_delivery(case, damage):
    sessions, _, pair, binding = case
    bad = await published(sessions, binding, pair.single_id)
    good = await published(sessions, binding, pair.single_id)
    async with sessions.begin() as session:
        (await session.get(sl.SuperLinkMessage, bad)).content_json = damage
    async with sessions.begin() as session:
        await service.receive(session, bad)
        await service.receive(session, good)
    async with sessions.begin() as session:
        assert (await session.get(sl.SuperLinkOutbox, bad)).state == "quarantined"
        assert await session.get(sl.SuperLinkReceipt, bad) is None
        assert await session.get(sl.SuperLinkReceipt, good) is not None


@pytest.mark.parametrize(
    "content",
    [
        {"body": " "},
        {"body": "x", "schema_version": 2},
        {"body": "x", "user_id": "forged"},
        {"body": "x", "artifacts": ["/private"]},
        {"body": "x", "requests_execution": "true"},
    ],
)
def test_unsupported_contract_rejected(content):
    with pytest.raises(ValidationError):
        DeliveryContent.model_validate(content)


async def test_optional_schema_does_not_change_legacy_readiness_metadata(tmp_path):
    await store.init_db()
    from sqlalchemy import inspect

    from server.readiness import storage_readiness

    assert not any(name.startswith("super_link_") for name in store.Base.metadata.tables)
    async with store.get_engine().connect() as connection:
        tables = await connection.run_sync(lambda conn: inspect(conn).get_table_names())
    assert not any(name.startswith("super_link_") for name in tables)
    assert (await storage_readiness(data_root=tmp_path)).ok
