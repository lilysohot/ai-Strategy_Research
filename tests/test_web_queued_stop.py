"""Stopping an outbox run must work before a worker exists (zero model calls)."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from server import dispatch_outbox, store
from server.app import app
from server.config import run_dir_for
from server.orchestrator import Orchestrator
from server.security import create_access_token


@pytest.mark.parametrize(
    "dispatch_status", ["pending", "retryable_failed", "abandoned", "claimed", "dispatched"]
)
async def test_stop_queued_outbox_run(dispatch_status, monkeypatch):
    await store.init_db()
    user = await store.create_user(username="queued-stop", password_hash="unused")
    session_id, run_id = uuid.uuid4(), uuid.uuid4()
    await store.ensure_session(session_id=session_id, user_id=user.id, title="queued")
    await store.create_run(
        run_id=run_id,
        session_id=session_id,
        user_id=user.id,
        prompt="watch trigger",
        pipeline_id="stateful-react-agent",
        run_dir=str(run_dir_for(run_id.hex)),
        status="queued",
    )
    async with store.get_sessionmaker()() as session, session.begin():
        row = await dispatch_outbox.enqueue(
            session,
            run_id=run_id,
            user_id=user.id,
            research_id=session_id,
            session_key=str(session_id),
            prompt="watch trigger",
        )
        row.status = dispatch_status
    orch = Orchestrator()
    monkeypatch.setattr("server.orchestrator._orchestrator", orch)
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        outsider = await store.create_user(username="outsider", password_hash="unused")
        denied = await client.post(
            f"/api/runs/{run_id}/control",
            json={"action": "stop"},
            headers={"Authorization": f"Bearer {create_access_token(outsider.id)}"},
        )
        assert denied.status_code == 404
        response = await client.post(
            f"/api/runs/{run_id}/control",
            json={"action": "stop"},
            headers=headers,
        )
        if dispatch_status in ("claimed", "dispatched"):
            assert response.status_code == 409
            run = await store.get_run(run_id=run_id, user_id=user.id)
            assert run.status == "queued"
            async with store.get_sessionmaker()() as session:
                row = await dispatch_outbox.get_for_run(session, run_id=run_id)
                assert row.status == dispatch_status
            return
        # Reconnecting a cancelled run has no trajectory or summary on disk.
        # Its SSE must finish from the durable status rather than wait forever.
        replay = await asyncio.wait_for(
            client.get(f"/api/runs/{run_id}/events", headers=headers),
            timeout=1,
        )
        assert replay.status_code == 200
        repeated = await client.post(
            f"/api/runs/{run_id}/control",
            json={"action": "stop"},
            headers=headers,
        )
        assert repeated.status_code == 200
    assert response.status_code == 200, response.text
    run = await store.get_run(run_id=run_id, user_id=user.id)
    assert run.status == "stopped"
    assert run.stopped_by == "user_stop"
    assert run.finished_at is not None
    async with store.get_sessionmaker()() as session:
        row = await dispatch_outbox.get_for_run(session, run_id=run_id)
        assert row.status == dispatch_outbox.ABANDONED
        assert await dispatch_outbox.claim_due(session) == []
