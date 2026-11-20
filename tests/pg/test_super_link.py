"""Real PG/Redis recovery tests. Uses a dedicated registered DB and stream only."""

import asyncio
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from server import store
from server.super_link import models as sl
from server.super_link import service, transport
from server.super_link.contracts import DeliveryContent
from tests.test_super_link import make_run, published, registered, seed_pair

pytestmark = pytest.mark.pg


async def test_concurrent_space_control_and_continuation(case, monkeypatch):
    from server.config import get_config
    from server.super_link import controls

    monkeypatch.setattr(get_config(), "super_link_enabled", True)
    sessions, uid, pair, _ = case
    request = controls.ControlRequest(
        action="pause", idempotency_key=uuid.uuid4(), expected_version=0, reason="Pause once",
    )
    results = await asyncio.gather(*(controls.control(uid, pair.space_id, request) for _ in range(5)))
    assert all(r == results[0] for r in results)
    async with sessions() as session:
        assert (await session.get(sl.SuperLinkSpace, pair.space_id)).control_version == 1
        assert await session.scalar(select(func.count()).select_from(sl.SuperLinkRecoveryAction)) == 1
    await controls.control(uid, pair.space_id, controls.ControlRequest(
        action="resume", idempotency_key=uuid.uuid4(), expected_version=1, reason="Resume",
    ))
    continuation = controls.ControlRequest(
        action="continue", idempotency_key=uuid.uuid4(), expected_version=2,
        reason="New evidence", message="Research the new evidence", participant_id=pair.single_id,
    )
    results = await asyncio.gather(*(controls.control(uid, pair.space_id, continuation) for _ in range(5)))
    assert all(r == results[0] for r in results)
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(store.RunDispatch)) == 1
        assert await session.scalar(select(func.count()).select_from(store.Turn)) == 1


async def test_space_control_migration_preserves_pause_and_records(case):
    sessions, _uid, pair, binding = case
    mid = await published(sessions, binding, pair.single_id)
    async with sessions.begin() as session:
        (await session.get(sl.SuperLinkSpace, pair.space_id)).paused = True
    migrate_optional("downgrade", "sl_0004_recovery")
    migrate_optional("upgrade", "head")
    async with sessions() as session:
        space = await session.get(sl.SuperLinkSpace, pair.space_id)
        assert space.paused and space.control_state == "paused" and space.control_version == 0
        assert (await session.get(sl.SuperLinkMessage, mid)).state == "published"


async def test_pause_fences_claimed_dispatch_on_postgres(case, monkeypatch):
    from server.config import get_config
    from tests.test_super_link_controls import test_pause_between_claim_and_submit_holds_dispatch

    monkeypatch.setattr(get_config(), "super_link_enabled", True)
    sessions, uid, pair, _ = case
    await test_pause_between_claim_and_submit_holds_dispatch((sessions, uid, pair), monkeypatch)


def migrate_optional(*args):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "server/super_link/alembic.ini", *args],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(scope="session")
def sl_migrated(pg_migrated):
    migrate_optional("upgrade", "head")


@pytest.fixture
async def case(sl_migrated, pg_clean):
    sessions = store.get_sessionmaker()
    uid, pair = await seed_pair(sessions)
    binding = await make_run(sessions, uid, pair)
    return sessions, uid, pair, binding


@pytest.fixture
async def delivery(case):
    url = os.environ.get("SUPER_LINK_TEST_REDIS_URL")
    if not url:
        pytest.skip("Set SUPER_LINK_TEST_REDIS_URL to an isolated test Redis")
    # A fresh namespace is mandatory even on a dedicated test instance.
    client = Redis.from_url(url, decode_responses=False)
    await client.ping()
    worker = transport.Delivery(
        client, case[0], namespace=f"test:super-link:{uuid.uuid4().hex}", reclaim_ms=1
    )
    yield worker
    await client.delete(worker.stream)
    await client.aclose()


async def test_concurrent_create_register_publish_receive_is_idempotent(case):
    sessions, uid, pair, binding = case
    key = uuid.uuid4()

    async def create():
        async with sessions.begin() as session:
            return await service.create_pair(
                session, user_id=uid, creation_key=key, goal="Parallel"
            )

    pairs = await asyncio.gather(*[create() for _ in range(4)])
    assert all(p == pairs[0] for p in pairs)

    async def send():
        return await published(sessions, binding, pair.single_id, registration_key=key)

    ids = await asyncio.gather(*[send() for _ in range(4)])
    assert len(set(ids)) == 1

    async def accept():
        async with sessions.begin() as session:
            await service.receive(session, ids[0])

    await asyncio.gather(*[accept() for _ in range(4)])
    async with sessions() as session:
        for model in (sl.SuperLinkMessage, sl.SuperLinkOutbox, sl.SuperLinkReceipt):
            assert await session.scalar(select(func.count()).select_from(model)) == 1


async def test_redis_roundtrip_after_restart_and_no_auto_run(case, delivery):
    sessions, uid, pair, binding = case
    first = await published(sessions, binding, pair.single_id)
    assert await delivery.relay() == 1
    # Restart consumer and database connections, keeping only persistent state.
    await store.reset_engine()
    sessions = store.get_sessionmaker()
    worker = transport.Delivery(
        delivery.redis, sessions, namespace=delivery.stream.rsplit(":", 1)[0]
    )
    assert await worker.consume() == 1
    async with sessions.begin() as session:
        messages = await service.inbox(session, user_id=uid, participant_id=pair.single_id)
        assert [row.id for row in messages] == [first]
        assert messages[0].content_json["requests_execution"] is False
    reply_binding = await make_run(sessions, uid, pair, role="single")
    reply = await published(
        sessions,
        reply_binding,
        pair.team_id,
        in_reply_to=first,
        content=DeliveryContent(body="Please supplement macro evidence", requests_execution=True),
    )
    assert await worker.relay() == 1
    assert await worker.consume() == 1
    async with sessions.begin() as session:
        messages = await service.inbox(session, user_id=uid, participant_id=pair.team_id)
        assert messages[0].request_id == first and messages[0].id == reply
        assert await session.scalar(select(func.count()).select_from(store.Run)) == 2
        assert await session.scalar(select(func.count()).select_from(store.RunDispatch)) == 0


async def test_redis_loss_replays_only_unreceived_records(case, delivery):
    sessions, _, pair, binding = case
    received = await published(sessions, binding, pair.single_id)
    await delivery.relay()
    await delivery.consume()
    pending = await published(sessions, binding, pair.single_id)
    await delivery.relay()
    await delivery.redis.delete(delivery.stream)
    async with sessions.begin() as session:
        (await session.get(sl.SuperLinkOutbox, pending)).notified_at = datetime.now(
            UTC
        ) - timedelta(minutes=5)
    assert await delivery.relay() == 1
    assert await delivery.consume() == 1
    async with sessions() as session:
        assert await session.get(sl.SuperLinkReceipt, received) is not None
        assert await session.get(sl.SuperLinkReceipt, pending) is not None
        assert await session.scalar(select(func.count()).select_from(sl.SuperLinkReceipt)) == 2


async def test_ack_loss_reclaims_receipt_without_duplicate(case, delivery, monkeypatch):
    sessions, _, pair, binding = case
    mid = await published(sessions, binding, pair.single_id)
    await delivery.relay()
    original_ack = delivery.redis.xack

    async def lost_ack(*args, **kwargs):
        raise RedisConnectionError("simulated ACK loss")

    monkeypatch.setattr(delivery.redis, "xack", lost_ack)
    with pytest.raises(RedisConnectionError):
        await delivery.consume()
    async with sessions() as session:
        assert await session.get(sl.SuperLinkReceipt, mid) is not None
    monkeypatch.setattr(delivery.redis, "xack", original_ack)
    await asyncio.sleep(0.01)
    worker = transport.Delivery(
        delivery.redis, sessions, namespace=delivery.stream.rsplit(":", 1)[0], reclaim_ms=1
    )
    assert await worker.consume() == 1
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(sl.SuperLinkReceipt)) == 1


async def test_database_failure_does_not_ack_and_recovers(case, delivery, monkeypatch):
    sessions, _, pair, binding = case
    mid = await published(sessions, binding, pair.single_id)
    await delivery.relay()
    original = transport.receive

    async def failed_commit(session, message_id):
        await original(session, message_id)
        raise RuntimeError("simulated transaction abort")

    monkeypatch.setattr(transport, "receive", failed_commit)
    with pytest.raises(RuntimeError):
        await delivery.consume()
    async with sessions() as session:
        assert await session.get(sl.SuperLinkReceipt, mid) is None
        assert (await session.get(sl.SuperLinkOutbox, mid)).state == "pending"
    monkeypatch.setattr(transport, "receive", original)
    await asyncio.sleep(0.01)
    assert await delivery.consume() == 1
    async with sessions() as session:
        assert await session.get(sl.SuperLinkReceipt, mid) is not None


async def test_redis_unavailable_keeps_durable_publication(case, delivery, monkeypatch):
    sessions, _, pair, binding = case
    mid = await published(sessions, binding, pair.single_id)
    original = delivery.redis.xadd

    async def unavailable(*args, **kwargs):
        raise RedisConnectionError("simulated Redis outage")

    monkeypatch.setattr(delivery.redis, "xadd", unavailable)
    with pytest.raises(RedisConnectionError):
        await delivery.relay()
    async with sessions() as session:
        assert (await session.get(sl.SuperLinkMessage, mid)).state == "published"
        assert (await session.get(sl.SuperLinkOutbox, mid)).notified_at is None
        assert (await session.get(store.Run, binding.run_id)).status == "completed"
    monkeypatch.setattr(delivery.redis, "xadd", original)
    assert await delivery.relay() == 1
    assert await delivery.consume() == 1


async def test_unknown_transport_and_poison_do_not_execute_or_block_peer(case, delivery):
    sessions, _, pair, binding = case
    draft = await registered(sessions, binding, pair.single_id)
    poisoned = await published(sessions, binding, pair.single_id)
    good = await published(sessions, binding, pair.single_id)
    async with sessions.begin() as session:
        (await session.get(sl.SuperLinkMessage, poisoned)).content_json = {"schema_version": 999}
    await delivery.ensure()
    await delivery.redis.xadd(delivery.stream, {"id": "not-a-uuid", "body": "run this"})
    await delivery.redis.xadd(delivery.stream, {"id": str(draft)})
    await delivery.redis.xadd(delivery.stream, {"id": str(uuid.uuid4())})
    await delivery.relay()
    await delivery.consume()
    async with sessions() as session:
        assert await session.get(sl.SuperLinkReceipt, draft) is None
        assert (await session.get(sl.SuperLinkOutbox, poisoned)).state == "quarantined"
        assert await session.get(sl.SuperLinkReceipt, good) is not None
        assert await session.scalar(select(func.count()).select_from(store.Run)) == 1


async def test_database_rejects_cross_space_relationship_even_without_service(case):
    sessions, _, pair, binding = case
    _, other = await seed_pair(sessions)
    mid = await registered(sessions, binding, pair.single_id)
    with pytest.raises(IntegrityError):
        async with sessions.begin() as session:
            (await session.get(sl.SuperLinkMessage, mid)).recipient_id = other.single_id
            await session.flush()


async def test_optional_migration_roundtrip_preserves_legacy_data_and_readiness(case, tmp_path):
    from server.readiness import storage_readiness

    sessions, uid, pair, binding = case
    async with sessions() as session:
        legacy_head = await session.scalar(text("SELECT version_num FROM alembic_version"))
    # The test database is guarded by tests/pg/conftest.py, never the business DB.
    migrate_optional("downgrade", "base")
    try:
        assert (await storage_readiness(data_root=tmp_path)).ok
        async with sessions() as session:
            assert await session.get(store.User, uid) is not None
            assert await session.get(store.Session, pair.team_session_id) is not None
            assert (await session.get(store.Run, binding.run_id)).status == "completed"
            assert (
                await session.scalar(text("SELECT version_num FROM alembic_version")) == legacy_head
            )
    finally:
        migrate_optional("upgrade", "head")
    assert (await storage_readiness(data_root=tmp_path)).ok
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(sl.SuperLinkSpace)) == 0
        assert await session.get(store.RunContextSource, binding.run_id) is not None


async def test_inspection_claim_and_execution_acceptance_are_concurrent_safe(
    case, delivery, monkeypatch
):
    from server.config import get_config
    from server.super_link.coordination import Inspection, accept_delivery, inspect_delivery

    monkeypatch.setattr(get_config(), "super_link_enabled", True)
    sessions, _, pair, binding = case
    mid = await published(
        sessions,
        binding,
        pair.single_id,
        content=DeliveryContent(body="Research", requests_execution=True),
    )
    await delivery.relay()
    await delivery.consume()
    calls = 0

    async def inspector(envelope):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return Inspection(verdict="pass", explanation="Independent test result")

    await asyncio.gather(*[inspect_delivery(mid, inspector, reviewer="pg-test") for _ in range(4)])
    assert calls == 1
    ids = await asyncio.gather(*[accept_delivery(mid) for _ in range(4)])
    assert ids[0] is not None and len(set(ids)) == 1
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(sl.SuperLinkExecution)) == 1
        assert await session.scalar(select(func.count()).select_from(store.RunDispatch)) == 1
        assert await session.scalar(select(func.count()).select_from(store.Turn)) == 0


async def test_fifo_concurrent_claims_select_only_oldest(case, monkeypatch):
    from server import dispatch_outbox
    from server.config import get_config

    sessions, uid, pair, _ = case
    monkeypatch.setattr(get_config(), "super_link_enabled", True)
    first = await make_run(sessions, uid, pair, role="single", status="queued", archive=False)
    second = await make_run(sessions, uid, pair, role="single", status="queued", archive=False)
    async with sessions.begin() as session:
        for index, binding in enumerate((first, second)):
            row = await session.get(store.Run, binding.run_id)
            row.created_at = datetime.now(UTC) + timedelta(seconds=index)
            await dispatch_outbox.enqueue(
                session,
                run_id=row.id,
                user_id=uid,
                research_id=row.session_id,
                session_key=str(row.session_id),
                prompt="queued task",
            )

    async def claim():
        async with sessions.begin() as session:
            return [row.run_id for row in await dispatch_outbox.claim_due(session)]

    batches = await asyncio.gather(*[claim() for _ in range(4)])
    assert [rid for batch in batches for rid in batch] == [first.run_id]


@pytest.mark.parametrize(
    "scenario",
    [
        "preinspection_poison_batch_does_not_starve_other_space",
        "fifty_held_admissions_cannot_starve_another_space",
        "archive_surviving_cas_conflict_cannot_publish_or_release_fifo",
        "informational_inbox_is_reviewed_private_and_frozen_per_run",
    ],
)
async def test_reliability_boundaries_on_postgres(case, monkeypatch, scenario):
    from server.config import get_config
    from tests import test_super_link_reliability as regression

    monkeypatch.setattr(get_config(), "super_link_enabled", True)
    sessions, uid, pair, _ = case
    check = getattr(regression, "test_" + scenario)
    kwargs = {"monkeypatch": monkeypatch} if scenario.startswith("preinspection") else {}
    await check((sessions, uid, pair), **kwargs)


async def test_reliability_migration_preserves_existing_deliveries(case):
    sessions, _, pair, binding = case
    mid = await published(sessions, binding, pair.single_id)
    migrate_optional("downgrade", "sl_0002_runtime")
    try:
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(sl.SuperLinkMessage.state).where(sl.SuperLinkMessage.id == mid)
                )
                == "published"
            )
            assert await session.get(store.RunContextSource, binding.run_id) is not None
    finally:
        migrate_optional("upgrade", "head")
    async with sessions() as session:
        assert (await session.get(sl.SuperLinkMessage, mid)).state == "published"
        assert await session.scalar(select(func.count()).select_from(sl.SuperLinkInboxAccess)) == 0


async def test_concurrent_correction_and_budget_recovery_are_exactly_once(case, monkeypatch):
    from server.config import get_config
    from server.super_link import coordination, management

    monkeypatch.setattr(get_config(), "super_link_enabled", True)
    sessions, uid, pair, binding = case
    mid = await published(sessions, binding, pair.single_id)
    async with sessions.begin() as session:
        await service.receive(session, mid)

    async def inspector(envelope):
        return coordination.Inspection(verdict="block", explanation="Evidence missing")

    await coordination.inspect_delivery(mid, inspector, reviewer="pg-test")
    ids = await asyncio.gather(*[coordination.accept_feedback(mid) for _ in range(4)])
    assert ids[0] is not None and len(set(ids)) == 1
    command = management.RecoveryRequest(
        action="extend_budget",
        idempotency_key=uuid.uuid4(),
        reason="Reviewed capacity",
        additional_runs=2,
    )
    results = await asyncio.gather(
        *[management.recover(uid, pair.space_id, command) for _ in range(4)]
    )
    assert all(result == results[0] for result in results)
    assert results[0]["limit"] == get_config().super_link_max_automatic_runs + 2
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(sl.SuperLinkFeedback)) == 1
        assert await session.scalar(select(func.count()).select_from(store.RunDispatch)) == 1
        assert (
            await session.scalar(select(func.count()).select_from(sl.SuperLinkRecoveryAction)) == 1
        )


async def test_recovery_migration_preserves_old_inspection_without_inventing_inputs(case):
    sessions, _, pair, binding = case
    mid = await published(sessions, binding, pair.single_id)
    async with sessions.begin() as session:
        message = await session.get(sl.SuperLinkMessage, mid)
        session.add(
            sl.SuperLinkReview(
                message_id=mid,
                content_sha256=message.content_sha256,
                goal_version=message.goal_version,
                verdict="block",
                explanation="Original missing evidence",
                reviewer="legacy-reviewer",
            )
        )
    migrate_optional("downgrade", "sl_0003_reliability")
    migrate_optional("upgrade", "head")
    async with sessions() as session:
        review = await session.get(sl.SuperLinkReview, mid)
        attempt = await session.get(sl.SuperLinkReviewAttempt, (mid, 1))
        assert review.verdict == attempt.verdict == "block"
        assert review.failure_kind == "business" and review.attempt_count == 1
        assert attempt.explanation == "Original missing evidence"
        assert attempt.input_json == {} and attempt.model_snapshot is None
        assert (await session.get(sl.SuperLinkMessage, mid)).state == "published"


async def test_expired_inspection_reply_is_fenced_on_postgres(case, monkeypatch):
    from server.config import get_config
    from tests.test_super_link_recovery import test_expired_inspection_lease_fences_late_model_reply

    monkeypatch.setattr(get_config(), "super_link_enabled", True)
    sessions, uid, pair, _ = case
    await test_expired_inspection_lease_fences_late_model_reply((sessions, uid, pair))


async def test_abandonment_serializes_with_native_ingestion(case, monkeypatch):
    from server.config import get_config
    from server.super_link import management, runtime

    monkeypatch.setattr(get_config(), "super_link_enabled", True)
    sessions, uid, pair, _ = case
    bound = await make_run(sessions, uid, pair, status="running", archive=False)
    await runtime.prepare(bound.run_id, None)
    async with sessions.begin() as session:
        (await session.get(store.Run, bound.run_id)).status = "completed"
    await runtime.witness_exit(bound.run_id, 0)
    command = management.RecoveryRequest(
        action="abandon_finalization",
        target_id=bound.run_id,
        idempotency_key=uuid.uuid4(),
        reason="Abandon incomplete source",
    )
    async with runtime.continuity_guard(bound.run_id) as writable:
        assert writable
        abandoning = asyncio.create_task(management.recover(uid, pair.space_id, command))
        await asyncio.sleep(0.05)
        assert not abandoning.done()
        await store.upsert_session_conversation(
            session_id=pair.team_session_id,
            run_id=bound.run_id,
            payload="Original native memory",
            pipeline_id="agent_team",
        )
    result = await asyncio.wait_for(abandoning, 3)
    assert result["outcome"] == "abandoned_not_published"
    async with runtime.continuity_guard(bound.run_id) as writable:
        assert not writable


async def test_concurrent_web_creation_starts_exactly_one_initial_run(case, monkeypatch):
    from server.config import get_config
    from server.routes import super_link as routes

    sessions, uid, _, _ = case
    monkeypatch.setattr(get_config(), "super_link_enabled", True)
    monkeypatch.setattr(get_config(), "agent_team_enabled", True)
    monkeypatch.setattr(get_config(), "sandbox_backend", "bwrap")
    monkeypatch.setattr(routes, "probe_data_root", lambda: None)
    async with sessions() as session:
        user = await session.get(store.User, uid)
    request = routes.CreateSpaceRequest(creation_key=uuid.uuid4(), goal="Latest reports")
    results = await asyncio.gather(*[routes.create_space(request, user) for _ in range(4)])
    assert all(r == results[0] for r in results)
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(store.RunDispatch)) == 1
        assert await session.scalar(select(func.count()).select_from(store.Turn)) == 1
        assert len(await store.list_sessions(user_id=uid, ordinary_only=True)) == 0
