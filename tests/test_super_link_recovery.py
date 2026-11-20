"""Bounded technical retries, immutable correction lineage and owner recovery APIs."""

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from server import store
from server.config import get_config
from server.deps import get_current_user
from server.routes.super_link import router
from server.super_link import (
    coordination,
    events,
    management,
    process_witness,
    runtime,
    service,
    worker,
)
from server.super_link import models as sl
from server.super_link.contracts import CollaborationError
from tests.test_super_link import make_run, seed_pair
from tests.test_super_link_reliability import deliver
from tests.test_super_link_runtime import case as case


async def inspection(mid, verdict="pass", explanation="checked"):
    async def evaluate(envelope):
        return coordination.Inspection(verdict=verdict, explanation=explanation)

    await coordination.inspect_delivery(mid, evaluate, reviewer="test-model")


async def due(sessions, mid):
    async with sessions.begin() as session:
        row = await session.get(sl.SuperLinkReview, mid)
        row.retry_at = datetime.now(UTC) - timedelta(seconds=1)


def command(action, target=None, **kwargs):
    return management.RecoveryRequest(
        action=action,
        target_id=target,
        idempotency_key=uuid.uuid4(),
        reason="Investigated the recorded failure",
        **kwargs,
    )


async def test_technical_retry_survives_restart_and_preserves_attempts(case, monkeypatch):
    sessions, uid, pair = case
    mid, _ = await deliver(sessions, uid, pair, execute=True)
    calls = 0

    async def provider(owner, envelope):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TimeoutError("provider-secret-must-not-leak")
        return coordination.Inspection(verdict="pass", explanation="Evidence checked")

    monkeypatch.setattr(worker, "model_inspection", provider)
    await worker.review_received()
    await store.reset_engine()
    sessions = store.get_sessionmaker()
    await worker.review_received()
    assert calls == 1  # Restart must not erase backoff.
    await due(sessions, mid)
    await worker.review_received()
    await due(sessions, mid)
    await worker.review_received()
    await worker.dispatch_feedback()
    async with sessions() as session:
        rows = list(
            await session.scalars(
                select(sl.SuperLinkReviewAttempt)
                .where(sl.SuperLinkReviewAttempt.message_id == mid)
                .order_by(sl.SuperLinkReviewAttempt.number)
            )
        )
        assert [r.verdict for r in rows] == ["incomplete", "incomplete", "pass"]
        assert [r.failure_kind for r in rows] == ["technical", "technical", None]
        assert all(r.finished_at and r.input_json["task_basis"] for r in rows)
        assert all("provider-secret" not in r.explanation for r in rows)
        assert await session.get(sl.SuperLinkFeedback, mid) is None
    await worker.admit_reviewed()
    await worker.admit_reviewed()
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(sl.SuperLinkExecution)) == 1


@pytest.mark.parametrize("origin", ["execution", "feedback"])
async def test_automatic_runs_cannot_impersonate_human_paused_monitor_cancellation(case, origin):
    from server import business_service as biz
    from server import watch_agent
    from tests.test_monitor_longterm import intent

    sessions, uid, pair = case
    mid, _ = await deliver(sessions, uid, pair, execute=True)
    await inspection(mid, "pass" if origin == "execution" else "block")
    rid = await (
        coordination.accept_delivery(mid)
        if origin == "execution"
        else coordination.accept_feedback(mid)
    )
    async with sessions.begin() as session:
        run = await session.get(store.Run, rid)
        session.add(store.MonitorSession(research_id=run.session_id, auto_manage=True, sequence=0))
    result = await watch_agent.call(rid, "submit", {"intents": [intent()]})
    rule_id = uuid.UUID(result["results"][0]["rule_id"])
    async with sessions.begin() as session:
        (await session.get(store.WatchRule, rule_id)).status = "paused"
    with pytest.raises(biz.ValidationError, match="暂停"):
        await watch_agent.call(
            rid,
            "submit",
            {
                "intents": [
                    {
                        "operation": "cancel",
                        "intent_key": "breakout",
                        "rule_id": str(rule_id),
                        "expected_version": 1,
                        "reason": "Automatic correction request",
                        "evidence_refs": ["watch:test"],
                    }
                ]
            },
        )
    async with sessions() as session:
        assert (await session.get(store.WatchRule, rule_id)).status == "paused"


async def test_exhausted_inspection_requires_audited_owner_retry(case, monkeypatch):
    sessions, uid, pair = case
    mid, _ = await deliver(sessions, uid, pair)
    calls = 0

    async def unavailable(owner, envelope):
        nonlocal calls
        calls += 1
        raise ConnectionError("outage")

    monkeypatch.setattr(worker, "model_inspection", unavailable)
    for _ in range(3):
        await worker.review_received()
        await due(sessions, mid)
    await worker.review_received()
    assert calls == 3
    async with sessions() as session:
        state = await management.delivery_status(
            session, await session.get(sl.SuperLinkMessage, mid)
        )
        assert state["phase"] == "inspection_exhausted"
    request = command("inspection_retry", mid)
    result = await management.recover(uid, pair.space_id, request)
    assert await management.recover(uid, pair.space_id, request) == result
    with pytest.raises(CollaborationError, match="idempotency_conflict"):
        await management.recover(
            uid, pair.space_id, request.model_copy(update={"reason": "different"})
        )
    await inspection(mid)
    async with sessions() as session:
        assert (await session.get(sl.SuperLinkReview, mid)).attempt_count == 4
        assert (
            await session.scalar(select(func.count()).select_from(sl.SuperLinkRecoveryAction)) == 1
        )
        assert (
            await session.scalar(select(func.count()).select_from(sl.SuperLinkReviewAttempt)) == 4
        )


async def test_expired_inspection_lease_fences_late_model_reply(case):
    sessions, uid, pair = case
    mid, _ = await deliver(sessions, uid, pair)
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(envelope):
        entered.set()
        await release.wait()
        return coordination.Inspection(verdict="pass", explanation="late stale answer")

    task = asyncio.create_task(coordination.inspect_delivery(mid, slow, reviewer="slow"))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        async with sessions.begin() as session:
            row = await session.get(sl.SuperLinkReview, mid)
            row.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        await inspection(mid, "block", "missing evidence")
    finally:
        release.set()
        await task
    async with sessions() as session:
        assert (await session.get(sl.SuperLinkReview, mid)).verdict == "block"
        expired = await session.get(sl.SuperLinkReviewAttempt, (mid, 1))
        assert expired.explanation == "inspection_lease_expired" and expired.finished_at
        assert (await session.get(sl.SuperLinkReviewAttempt, (mid, 2))).verdict == "block"


@pytest.mark.parametrize("verdict", ["block", "incomplete"])
async def test_business_feedback_is_queued_once_and_revision_is_independent(case, verdict):
    sessions, uid, pair = case
    original, _ = await deliver(sessions, uid, pair, execute=True, body="Needs dated sources")
    await inspection(original, verdict, "Provide dated source evidence")
    await due(sessions, original)
    # A business failure cannot be retried until the model happens to approve it.
    await inspection(original, "pass")
    with pytest.raises(CollaborationError, match="revision_required"):
        await management.recover(uid, pair.space_id, command("inspection_retry", original))
    earlier = await make_run(sessions, uid, pair, status="queued", archive=False)
    async with sessions.begin() as session:
        r = await session.get(store.Run, earlier.run_id)
        r.created_at = datetime.now(UTC) - timedelta(seconds=10)
    await worker.dispatch_feedback()
    await worker.dispatch_feedback()
    async with sessions() as session:
        feedback = await session.get(sl.SuperLinkFeedback, original)
        feedback_run = await session.get(store.Run, feedback.run_id)
        rid = feedback.run_id
        assert feedback_run.session_id == pair.team_session_id
        assert "Provide dated source evidence" in feedback_run.prompt
        assert await coordination.fifo_blocked(session, feedback_run)
        assert await session.scalar(select(func.count()).select_from(store.RunDispatch)) == 1
        assert await session.scalar(select(func.count()).select_from(store.Turn)) == 0
    async with sessions.begin() as session:
        (await session.get(store.Run, earlier.run_id)).status = "completed"
    await runtime.prepare(rid, None)
    new = await runtime.register_from_worker(
        rid,
        {
            "recipient_id": str(pair.single_id),
            "registration_key": str(uuid.uuid4()),
            "revises_message_id": str(original),
            "content": {"body": "Corrected: dated evidence and limits", "requests_execution": True},
        },
    )
    mid = uuid.UUID(new["message_id"])
    async with sessions() as session:
        assert (await session.get(sl.SuperLinkMessage, mid)).state == "registered"
        assert await session.get(sl.SuperLinkOutbox, mid) is None
    async with sessions.begin() as session:
        run = await session.get(store.Run, rid)
        run.status, run.finished_at = "completed", datetime.now(UTC)
    await store.upsert_session_conversation(
        session_id=pair.team_session_id,
        run_id=rid,
        pipeline_id="agent_team",
        payload="own correction memory",
    )
    await runtime.witness_exit(rid, 0)
    assert await runtime.finalize(rid)
    async with sessions.begin() as session:
        await service.receive(session, mid)
        await events.seal_changes(session)

    async def independent(envelope):
        assert envelope["revision_of"]["message_id"] == str(original)
        assert envelope["revision_of"]["inspection"]["verdict"] == verdict
        return coordination.Inspection(
            verdict="caveat", explanation="Corrected but retain limitations"
        )

    await coordination.inspect_delivery(mid, independent, reviewer="second-inspection")
    accepted = await coordination.accept_delivery(mid)
    assert accepted and await coordination.accept_delivery(mid) == accepted
    async with sessions() as session:
        old, revision = (
            await session.get(sl.SuperLinkMessage, original),
            await session.get(sl.SuperLinkMessage, mid),
        )
        assert old.content_json["body"] == "Needs dated sources"
        assert revision.revises_message_id == original and revision.request_id == original
        assert (await session.get(sl.SuperLinkReview, original)).verdict == verdict
        admitted = await session.scalar(
            select(sl.SuperLinkEvent)
            .where(
                sl.SuperLinkEvent.space_id == pair.space_id,
                sl.SuperLinkEvent.type == "sl.admission.changed",
                sl.SuperLinkEvent.source_id == str(mid),
            )
            .order_by(sl.SuperLinkEvent.seq.desc())
        )
        assert admitted is not None and "space" in admitted.invalidate_json
        used, _ = await coordination.automatic_budget(
            session, await session.get(sl.SuperLinkSpace, pair.space_id)
        )
        assert used == 2  # correction + receiver run share the same cap


async def test_feedback_retry_after_transient_failure_keeps_one_success_event(case, monkeypatch):
    sessions, uid, pair = case
    mid, _ = await deliver(sessions, uid, pair)
    await inspection(mid, "block", "Provide dated source evidence")
    original = coordination.enqueue_automatic
    calls = 0

    async def flaky(session, space, peer, prompt):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient coordinator failure")
        return await original(session, space, peer, prompt)

    monkeypatch.setattr(coordination, "enqueue_automatic", flaky)
    await worker.dispatch_feedback()
    async with sessions.begin() as session:
        row = await session.get(sl.SuperLinkFeedback, mid)
        assert row.attempts == 1 and row.run_id is None and not row.held
        row.retry_at = datetime.now(UTC) - timedelta(seconds=1)

    await worker.dispatch_feedback()
    async with sessions() as session:
        feedback = await session.get(sl.SuperLinkFeedback, mid)
        assert feedback.run_id is not None
        rows = list(
            await session.scalars(
                select(sl.SuperLinkEvent)
                .where(
                    sl.SuperLinkEvent.space_id == pair.space_id,
                    sl.SuperLinkEvent.type == "sl.feedback.changed",
                )
                .order_by(sl.SuperLinkEvent.seq)
            )
        )
        assert [row.change_key for row in rows] == [
            f"feedback:{mid}:1:admission_failed",
            f"feedback:{mid}:1:started",
        ]
        success = rows[-1]
        assert success.participant_id == pair.team_id
        assert success.session_id == pair.team_session_id
        assert success.run_id == feedback.run_id
        assert "space" in success.invalidate_json
        assert success.data_json["attempts"] == 1 and success.data_json["error_code"] is None


async def test_budget_extension_is_idempotent_and_releases_held_feedback(case, monkeypatch):
    sessions, uid, pair = case
    monkeypatch.setattr(get_config(), "super_link_max_automatic_runs", 1)
    first, _ = await deliver(sessions, uid, pair, verdict="pass", execute=True)
    assert await coordination.accept_delivery(first)
    blocked, _ = await deliver(sessions, uid, pair)
    await inspection(blocked, "block", "Evidence needed")
    await worker.dispatch_feedback()
    async with sessions() as session:
        row = await session.get(sl.SuperLinkFeedback, blocked)
        assert row.error_code == "automatic_run_limit" and row.held and row.run_id is None
    request = command("extend_budget", additional_runs=1)
    first_result = await management.recover(uid, pair.space_id, request)
    assert await management.recover(uid, pair.space_id, request) == first_result
    await worker.dispatch_feedback()
    await store.reset_engine()
    await worker.dispatch_feedback()
    async with store.get_sessionmaker()() as session:
        assert (await session.get(sl.SuperLinkFeedback, blocked)).run_id is not None
        assert (await session.get(sl.SuperLinkSpace, pair.space_id)).automatic_run_limit == 2
        assert await session.scalar(select(func.count()).select_from(store.RunDispatch)) == 2


async def test_finalization_retries_are_bounded_and_do_not_rewrite_head(case):
    sessions, uid, pair = case
    bound = await make_run(sessions, uid, pair, archive=False)
    async with sessions.begin() as session:
        session.add(
            sl.SuperLinkFinalization(
                run_id=bound.run_id,
                state="pending",
                worker_exited_at=datetime.now(UTC),
                exit_code=0,
            )
        )
    calls = 0

    async def ingest(*args, **kwargs):
        nonlocal calls
        calls += 1

    orch = SimpleNamespace(_ingest_conversation=ingest)
    for _ in range(5):
        await worker.recover_finalizations(orch)
        async with sessions.begin() as session:
            (await session.get(sl.SuperLinkFinalization, bound.run_id)).retry_at = None
    assert calls == 3
    await management.recover(uid, pair.space_id, command("finalization_retry", bound.run_id))
    await worker.recover_finalizations(orch)
    assert calls == 4
    async with sessions() as session:
        row = await session.get(sl.SuperLinkFinalization, bound.run_id)
        assert row.state == "pending" and row.error_code == "continuity_not_saved"
        assert (
            await session.scalar(select(func.count()).select_from(store.SessionConversation)) == 0
        )


async def test_orphan_abandonment_requires_host_process_evidence_and_never_publishes(case):
    sessions, uid, pair = case
    bound = await make_run(sessions, uid, pair, status="running", archive=False)
    await runtime.prepare(bound.run_id, None)
    registered = await runtime.register_from_worker(
        bound.run_id,
        {
            "recipient_id": str(pair.single_id),
            "registration_key": str(uuid.uuid4()),
            "content": {"body": "unwitnessed"},
        },
    )
    async with sessions.begin() as session:
        run = await session.get(store.Run, bound.run_id)
        run.status, run.finished_at = "failed", datetime.now(UTC)
    request = command("abandon_finalization", bound.run_id)
    with pytest.raises(CollaborationError, match="worker_exit_unverified"):
        await management.recover(uid, pair.space_id, request)
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import sys; print('ready', flush=True); sys.stdin.read()",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        await process.stdout.readline()
        identity = process_witness.capture(process.pid)
        assert identity is not None
        async with sessions.begin() as session:
            (await session.get(sl.SuperLinkFinalization, bound.run_id)).process_identity = identity
        with pytest.raises(CollaborationError, match="worker_exit_unverified"):
            await management.recover(uid, pair.space_id, request)
    finally:
        process.stdin.close()
        await process.wait()
    assert process_witness.group_is_gone(identity)
    result = await management.recover(uid, pair.space_id, request)
    assert result["outcome"] == "abandoned_not_published"
    await runtime.witness_exit(bound.run_id, 0)  # A late callback cannot resurrect abandonment.
    assert not await runtime.finalize(bound.run_id)
    async with runtime.continuity_guard(bound.run_id) as writable:
        assert not writable  # Late ingestion cannot replace memory after queue release.
    async with sessions() as session:
        assert (await session.get(sl.SuperLinkFinalization, bound.run_id)).state == "failed"
        assert (
            await session.get(sl.SuperLinkMessage, uuid.UUID(registered["message_id"]))
        ).state == "registered"
        assert await session.scalar(select(func.count()).select_from(sl.SuperLinkOutbox)) == 0


async def test_owner_api_status_privacy_recovery_and_disabled_isolation(case, monkeypatch):
    sessions, uid, pair = case
    mid, _ = await deliver(sessions, uid, pair)
    await inspection(mid, "block", "Missing evidence")
    await worker.dispatch_feedback()
    _other_uid, other = await seed_pair(sessions)
    app = FastAPI()
    app.include_router(router)
    async with sessions() as session:
        user = await session.get(store.User, uid)
    app.dependency_overrides[get_current_user] = lambda: user
    base = f"/api/super-link/spaces/{pair.space_id}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        overview = (await client.get(base)).json()
        assert overview["automatic_budget"]["used"] == 1
        response = await client.get(f"{base}/deliveries/{mid}")
        assert response.status_code == 200
        detail = response.json()
        assert detail["phase"] == "correction_required"
        assert detail["attempts"][0]["input"]["task_basis"]
        assert detail["feedback"]["run"]["status"] == "queued"
        assert "must not reach the peer" not in response.text
        assert (await client.get(f"{base}/runs")).status_code == 200
        assert (await client.get(f"/api/super-link/spaces/{other.space_id}")).status_code == 404
        request = command("extend_budget", additional_runs=2).model_dump(mode="json")
        assert (
            await client.post(f"/api/super-link/spaces/{other.space_id}/recovery", json=request)
        ).status_code == 404
        first = await client.post(f"{base}/recovery", json=request)
        assert first.status_code == 200
        assert (await client.post(f"{base}/recovery", json=request)).json() == first.json()
        assert len((await client.get(f"{base}/recovery-actions")).json()["items"]) == 1
        request["action"] = "force_pass"
        assert (await client.post(f"{base}/recovery", json=request)).status_code == 422
        monkeypatch.setattr(get_config(), "restore_mode", True)
        assert (await client.get(base)).status_code == 200
        assert (
            await client.post(
                f"{base}/recovery", json=command("extend_budget").model_dump(mode="json")
            )
        ).status_code == 409
        monkeypatch.setattr(get_config(), "super_link_enabled", False)
        monkeypatch.setattr(
            store, "get_sessionmaker", lambda: pytest.fail("disabled API touched optional storage")
        )
        assert (await client.get(base)).status_code == 404
