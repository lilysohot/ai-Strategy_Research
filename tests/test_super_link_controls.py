"""Lifecycle fencing, stop persistence, human authorization and continuation."""

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from server import dispatch_outbox, store
from server.config import get_config
from server.super_link import controls, coordination, events, management, runtime
from server.super_link import models as sl
from server.super_link.contracts import CollaborationError
from tests.test_super_link import make_run, published
from tests.test_super_link_entry import client as client
from tests.test_super_link_runtime import case as case


def command(action, version=0, **kwargs):
    return controls.ControlRequest(
        action=action,
        expected_version=version,
        idempotency_key=uuid.uuid4(),
        reason="Owner decision",
        **kwargs,
    )


async def queue(case):
    sessions, uid, pair = case
    binding = await make_run(sessions, uid, pair, status="queued", archive=False)
    async with sessions.begin() as session:
        await dispatch_outbox.enqueue(
            session,
            run_id=binding.run_id,
            user_id=uid,
            research_id=pair.team_session_id,
            session_key=str(pair.team_session_id),
            prompt="Research",
        )
        await events.seal_changes(session)
    return binding.run_id


async def test_pause_keeps_queue_and_resume_preserves_fifo(case):
    sessions, uid, pair = case
    rid = await queue(case)
    req = command("pause")
    result = await controls.control(uid, pair.space_id, req)
    assert result["control_state"] == "paused"
    assert await controls.control(uid, pair.space_id, req) == result
    async with sessions.begin() as session:
        assert not await dispatch_outbox.claim_due(session)
        assert (await session.get(store.Run, rid)).status == "queued"
    with pytest.raises(CollaborationError, match="control_version_conflict"):
        await controls.control(uid, pair.space_id, command("resume", 0))
    await controls.control(uid, pair.space_id, command("resume", 1))
    async with sessions() as session:
        assert not await coordination.fifo_blocked(session, await session.get(store.Run, rid))


async def test_pause_does_not_close_running_delivery_registration(case):
    sessions, uid, pair = case
    binding = await make_run(sessions, uid, pair, status="running", archive=False)
    await runtime.prepare(binding.run_id, None)
    await controls.control(uid, pair.space_id, command("pause"))
    payload = {
        "recipient_id": str(pair.single_id),
        "registration_key": str(uuid.uuid4()),
        "content": {"body": "Research completed"},
    }
    assert (await runtime.register_from_worker(binding.run_id, payload))["ok"]
    await controls.control(uid, pair.space_id, command("stop", 1))
    with pytest.raises(CollaborationError, match="registration_closed"):
        await runtime.register_from_worker(binding.run_id, payload)


async def test_stop_cancels_queue_survives_reconcile_and_never_revives_delivery(case):
    sessions, uid, pair = case
    binding = await make_run(sessions, uid, pair)
    mid = await published(sessions, binding, pair.single_id)
    rid = await queue(case)
    await controls.control(uid, pair.space_id, command("stop"))
    orch = AsyncMock()
    await controls.reconcile_stops(orch)
    async with sessions() as session:
        space = await session.get(sl.SuperLinkSpace, pair.space_id)
        assert space.control_state == "stopped"
        assert (await session.get(store.Run, rid)).status == "stopped"
        version = space.control_version
    await controls.control(uid, pair.space_id, command("resume", version))
    inspector = AsyncMock()
    # Receipt may arrive after stop; old content still cannot start a review.
    from server.super_link.service import receive

    async with sessions.begin() as session:
        await receive(session, message_id=mid)
        await events.seal_changes(session)
    await coordination.inspect_delivery(mid, inspector, reviewer="test")
    inspector.assert_not_called()
    assert await coordination.accept_delivery(mid) is None
    assert await coordination.accept_feedback(mid) is None
    async with sessions() as session:
        assert (
            await management.delivery_status(session, await session.get(sl.SuperLinkMessage, mid))
        )["phase"] == "cancelled_by_stop"
        assert (await session.get(store.Run, rid)).status == "stopped"


async def test_stop_waits_for_real_exit_and_finalization(case):
    sessions, uid, pair = case
    binding = await make_run(sessions, uid, pair, status="running", archive=False)
    await runtime.prepare(binding.run_id, None)
    await controls.control(uid, pair.space_id, command("stop"))
    orch = AsyncMock()
    orch.stop.return_value = False  # Another process owns it: no fabricated terminal state.
    await controls.reconcile_stops(orch)
    orch.stop.assert_awaited_once_with(binding.run_id.hex)
    async with sessions.begin() as session:
        assert (await session.get(sl.SuperLinkSpace, pair.space_id)).control_state == "stopping"
        (await session.get(store.Run, binding.run_id)).status = "stopped"
    await controls.reconcile_stops(orch)
    async with sessions() as session:
        assert (await session.get(sl.SuperLinkSpace, pair.space_id)).control_state == "stopping"
    await runtime.witness_exit(binding.run_id, -15)
    await runtime.finalize(binding.run_id)
    await controls.reconcile_stops(orch)
    async with sessions() as session:
        assert (await session.get(sl.SuperLinkSpace, pair.space_id)).control_state == "stopped"


async def test_stopped_space_cancels_new_monitor_dispatch(case):
    sessions, uid, pair = case
    await controls.control(uid, pair.space_id, command("stop"))
    await controls.reconcile_stops(AsyncMock())
    rid = await queue(case)
    async with sessions() as session:
        assert (await session.get(store.Run, rid)).status == "stopped"
        assert (await dispatch_outbox.get_for_run(session, run_id=rid)).status == "abandoned"


async def test_human_continuation_is_atomic_idempotent_and_role_bound(case, client):
    sessions, _uid, pair = case
    req = command("continue", participant_id=pair.single_id, message="New evidence")
    root = f"/api/super-link/spaces/{pair.space_id}/control"
    first = await client.post(root, json=req.model_dump(mode="json"))
    assert first.status_code == 200, first.text
    assert (await client.post(root, json=req.model_dump(mode="json"))).json() == first.json()
    async with sessions() as session:
        run = await session.get(store.Run, uuid.UUID(first.json()["run_id"]))
        assert (
            run.session_id == pair.single_session_id and run.pipeline_id == "stateful-react-agent"
        )
        assert await session.scalar(select(func.count()).select_from(store.Turn)) == 1
        assert await session.scalar(select(func.count()).select_from(store.RunDispatch)) == 1
        assert (
            await coordination.automatic_budget(
                session, await session.get(sl.SuperLinkSpace, pair.space_id)
            )
        )[0] == 0
    changed = req.model_copy(update={"message": "Different"})
    assert (await client.post(root, json=changed.model_dump(mode="json"))).status_code == 409
    bad = command("continue", 1, participant_id=uuid.uuid4(), message="Foreign")
    assert (await client.post(root, json=bad.model_dump(mode="json"))).status_code == 404


async def test_controls_restore_and_owner_boundaries(case, client, monkeypatch):
    sessions, _uid, pair = case
    root = f"/api/super-link/spaces/{pair.space_id}"
    req = command("pause").model_dump(mode="json")
    assert (
        await client.post(f"/api/super-link/spaces/{uuid.uuid4()}/control", json=req)
    ).status_code == 404
    monkeypatch.setattr(get_config(), "restore_mode", True)
    assert (await client.post(root + "/control", json=req)).status_code == 409
    assert (await client.get(root)).json()["can_control"] is False
    async with sessions() as session:
        assert (await session.get(sl.SuperLinkSpace, pair.space_id)).control_version == 0


async def test_approval_projection_and_stale_or_wrong_run_rejected(case, client, monkeypatch):
    sessions, uid, pair = case
    binding = await make_run(sessions, uid, pair, status="running")
    record = await store.create_control(
        run_id=binding.run_id,
        session_id=pair.team_session_id,
        user_id=uid,
        kind="approval",
        status="pending",
        external_id="pending-tool",
        request_payload={"tool_name": "bash", "risk": "high", "preview": "delete"},
    )
    root = f"/api/super-link/spaces/{pair.space_id}"
    result = (await client.get(root + "/interventions")).json()
    assert result["pending"][0]["external_id"] == "pending-tool"
    from server.routes import super_link as routes

    approved = AsyncMock(return_value={"approved": True})
    monkeypatch.setattr(routes, "run_approve", approved)
    endpoint = root + f"/runs/{binding.run_id}/approve"
    body = {"approval_id": "pending-tool", "decision": "once"}
    assert (await client.post(endpoint, json=body)).status_code == 200
    async with sessions() as session:
        assert (
            await session.get(store.ControlRecord, record.id)
        ).status == "pending"  # HTTP is not adoption.
    assert (await client.post(endpoint, json={**body, "approval_id": "wrong"})).status_code == 409
    await store.resolve_control(control_id=record.id, status="expired")
    assert (await client.post(endpoint, json=body)).status_code == 409
    assert (await client.get(root + "/interventions")).json()["pending"] == []
    approved.assert_awaited_once()


async def test_pause_between_claim_and_submit_holds_dispatch(case, monkeypatch):
    sessions, uid, pair = case
    rid = await queue(case)

    async def pause_after_claim(_rid):
        await controls.control(uid, pair.space_id, command("pause"))

    monkeypatch.setattr(dispatch_outbox.uploads, "publish_for_run", pause_after_claim)
    orch = AsyncMock()
    assert await dispatch_outbox.dispatch_once(orch) == 0
    orch.submit.assert_not_called()
    async with sessions() as session:
        assert (await dispatch_outbox.get_for_run(session, run_id=rid)).status == "pending"
        assert (await session.get(store.Run, rid)).status == "queued"


async def test_continuation_enqueue_failure_rolls_back_command_and_turn(case, monkeypatch):
    sessions, uid, pair = case
    monkeypatch.setattr(
        dispatch_outbox, "enqueue", AsyncMock(side_effect=RuntimeError("outbox down"))
    )
    with pytest.raises(RuntimeError, match="outbox down"):
        await controls.control(
            uid,
            pair.space_id,
            command(
                "continue",
                participant_id=pair.team_id,
                message="Additional evidence",
            ),
        )
    async with sessions() as session:
        assert (await session.get(sl.SuperLinkSpace, pair.space_id)).control_version == 0
        for model in (store.Run, store.Turn, sl.SuperLinkRecoveryAction):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_foreign_space_owner_cannot_control_or_read_approvals(case, client):
    from tests.test_super_link import seed_pair

    sessions, _uid, _ = case
    _, other = await seed_pair(sessions)
    root = f"/api/super-link/spaces/{other.space_id}"
    assert (await client.get(root + "/interventions")).status_code == 404
    assert (
        await client.post(root + "/control", json=command("stop").model_dump(mode="json"))
    ).status_code == 404
    async with sessions() as session:
        assert (await session.get(sl.SuperLinkSpace, other.space_id)).control_state == "active"


async def test_stop_failure_in_one_run_does_not_block_other_space(case):
    from tests.test_super_link import seed_pair

    sessions, uid, pair = case
    running = await make_run(sessions, uid, pair, status="running")
    await controls.control(uid, pair.space_id, command("stop"))
    other_uid, other = await seed_pair(sessions)
    rid = await queue((sessions, other_uid, other))
    await controls.control(other_uid, other.space_id, command("stop"))
    orch = AsyncMock()
    orch.stop.side_effect = RuntimeError("worker pipe unavailable")
    await controls.reconcile_stops(orch)
    async with sessions() as session:
        assert (await session.get(store.Run, running.run_id)).status == "running"
        assert (await session.get(store.Run, rid)).status == "stopped"
