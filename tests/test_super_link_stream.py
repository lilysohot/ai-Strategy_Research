"""SSE-T03: consistent snapshots, cursor catch-up and bounded space streams."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.exc import OperationalError, ProgrammingError

from server import store
from server.config import get_config
from server.deps import get_current_user
from server.routes import super_link as routes
from server.super_link import events, management, service, stream
from server.super_link import models as sl
from tests.test_super_link import make_run, published
from tests.test_super_link_runtime import case as case


@pytest.fixture
async def client(case, monkeypatch):
    sessions, uid, _pair = case
    monkeypatch.setattr(get_config(), "super_link_sse_auth_recheck_seconds", 60.0)
    async with sessions() as session:
        user = await session.get(store.User, uid)
    holder = {"user": user}
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_current_user] = lambda: holder["user"]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", timeout=10
    ) as http:
        yield http, holder


@pytest.fixture
async def seeded(case):
    sessions, uid, pair = case
    running = await make_run(sessions, uid, pair, status="running", archive=False)
    completed = await make_run(sessions, uid, pair, status="completed")
    message_id = await published(sessions, completed, pair.single_id)
    async with sessions.begin() as session:
        await service.receive(session, message_id)
        session.add(
            store.ControlRecord(
                run_id=running.run_id,
                session_id=pair.team_session_id,
                user_id=uid,
                kind="approval",
                status="pending",
                request_json={"tool": "demo"},
            )
        )
        session.add(
            sl.SuperLinkRecoveryAction(
                space_id=pair.space_id,
                user_id=uid,
                idempotency_key=uuid.uuid4(),
                request_json={"action": "retry"},
                result_json={"ok": True},
            )
        )
        await events.seal_changes(session)
    return sessions, uid, pair, running, message_id


@dataclass
class Head:
    stream_epoch: uuid.UUID
    last_seq: int


async def _head(sessions, space_id):
    async with sessions() as session:
        row = await session.get(sl.SuperLinkEventHead, space_id)
        if row is None:
            return None
        return Head(stream_epoch=row.stream_epoch, last_seq=row.last_seq)


async def _append_event(
    sessions, space_id, *, change_key, kind="sl.space.control_changed", **kwargs
):
    async with sessions.begin() as session:
        await events.stage_for_space(
            session,
            space_id,
            type=kind,
            change_key=change_key,
            data=kwargs.pop("data", {"value": change_key}),
            **kwargs,
        )
        await events.seal_changes(session)
    head = await _head(sessions, space_id)
    return head


def _frames(text: str) -> list[str]:
    return [block for block in text.split("\n\n") if block.strip()]


def _parse(block: str) -> tuple[str | None, str | None, dict | None]:
    event = frame_id = None
    data = None
    for line in block.splitlines():
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("id: "):
            frame_id = line[4:]
        elif line.startswith("data: "):
            data = json.loads(line[6:])
    return event, frame_id, data


async def test_snapshot_returns_cursor_lists_and_exact_totals(client, seeded):
    http, _holder = client
    sessions, _uid, pair, running, _message = seeded
    head = await _head(sessions, pair.space_id)

    response = await http.get(
        f"/api/super-link/spaces/{pair.space_id}/snapshot", params={"limit": 1}
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["schema_version"] == 1
    assert body["cursor"] == events.format_cursor(
        pair.space_id, head.stream_epoch, head.last_seq
    )
    assert body["durability_scope"] == "committed_records"
    assert body["space"]["space_id"] == str(pair.space_id)
    assert body["space"]["automatic_budget"]["used"] == 0
    assert body["capabilities"] == {
        "replay": True,
        "live_output": "local_owner_only",
    }
    assert {row["role"] for row in body["participants"]} == {"team", "single"}
    assert all(row["available"] for row in body["participants"])

    assert body["runs"]["total"] == 2
    assert len(body["runs"]["items"]) == 1
    assert body["runs"]["next_after"]
    assert body["deliveries"]["total"] == 1
    assert body["deliveries"]["items"][0]["phase"]
    assert body["pending_interventions"]["total"] == 1
    assert body["pending_interventions"]["items"][0]["kind"] == "approval"
    assert body["actions"]["total"] == 1
    assert body["active_run_ids"] == [str(running.run_id)]


async def test_snapshot_and_interventions_continue_all_lists(client, seeded):
    http, _holder = client
    sessions, uid, pair, running, _message = seeded
    base = datetime.now(UTC).replace(microsecond=0)
    async with sessions.begin() as session:
        for index in range(3):
            session.add(
                store.ControlRecord(
                    run_id=running.run_id,
                    session_id=pair.team_session_id,
                    user_id=uid,
                    kind="approval",
                    external_id=f"page-{index}",
                    status="pending",
                    request_json={"index": index},
                )
            )
        for index in range(2):
            session.add(
                store.Run(
                    id=uuid.uuid4(),
                    session_id=pair.team_session_id,
                    user_id=uid,
                    status="completed",
                    pipeline_id="stateful-react-agent",
                    prompt="pagination stand-in",
                    run_dir=f"runs/page-{index}",
                    created_at=base + timedelta(microseconds=10 + index),
                )
            )

    snapshot_url = f"/api/super-link/spaces/{pair.space_id}/snapshot"
    first = (await http.get(snapshot_url, params={"limit": 1})).json()
    assert first["pending_interventions"]["total"] == 4
    pending_ids = [
        item["control_id"] for item in first["pending_interventions"]["items"]
    ]
    cursor = first["pending_interventions"]["next_after"]
    for _ in range(10):
        if not cursor:
            break
        page = (
            await http.get(
                snapshot_url, params={"limit": 1, "pending_after": cursor}
            )
        ).json()
        assert page["pending_interventions"]["total"] == 4
        pending_ids += [
            item["control_id"] for item in page["pending_interventions"]["items"]
        ]
        cursor = page["pending_interventions"]["next_after"]
    assert len(pending_ids) == 4
    assert len(set(pending_ids)) == 4

    first = (await http.get(snapshot_url, params={"limit": 1})).json()
    assert first["runs"]["total"] == 4
    run_ids = [item["run_id"] for item in first["runs"]["items"]]
    cursor = first["runs"]["next_after"]
    for _ in range(10):
        if not cursor:
            break
        page = (
            await http.get(snapshot_url, params={"limit": 1, "runs_after": cursor})
        ).json()
        assert page["runs"]["total"] == 4
        run_ids += [item["run_id"] for item in page["runs"]["items"]]
        cursor = page["runs"]["next_after"]
    assert len(run_ids) == 4
    assert len(set(run_ids)) == 4

    interventions_url = f"/api/super-link/spaces/{pair.space_id}/interventions"
    first = (await http.get(interventions_url, params={"limit": 1})).json()
    assert first["pending_total"] == 4
    assert first["cursor"].startswith(f"sl1:{pair.space_id}:")
    ids = [item["control_id"] for item in first["pending"]]
    cursor = first["pending_next_after"]
    for _ in range(10):
        if not cursor:
            break
        page = (
            await http.get(
                interventions_url, params={"limit": 1, "pending_after": cursor}
            )
        ).json()
        ids += [item["control_id"] for item in page["pending"]]
        cursor = page["pending_next_after"]
    assert len(ids) == 4
    assert len(set(ids)) == 4


async def test_snapshot_cursor_then_events_has_no_gap(client, seeded):
    http, _holder = client
    sessions, uid, pair, _running, _message = seeded
    snapshot = (
        await http.get(f"/api/super-link/spaces/{pair.space_id}/snapshot")
    ).json()

    head = await _append_event(
        sessions,
        pair.space_id,
        change_key=f"gap:{uuid.uuid4()}",
        kind="sl.space.control_changed",
    )
    page = await events.read_events(
        user_id=uid, space_id=pair.space_id, after=snapshot["cursor"], limit=10
    )
    assert [item["type"] for item in page.events] == ["sl.space.control_changed"]
    assert page.events[0]["seq"] == str(head.last_seq)


async def test_snapshot_min_cursor_rules(client, seeded):
    http, _holder = client
    sessions, _uid, pair, _running, _message = seeded
    snapshot = (
        await http.get(f"/api/super-link/spaces/{pair.space_id}/snapshot")
    ).json()
    head = await _head(sessions, pair.space_id)
    root = f"/api/super-link/spaces/{pair.space_id}/snapshot"

    assert (await http.get(root, params={"min_cursor": snapshot["cursor"]})).status_code == 200

    cross = events.format_cursor(uuid.uuid4(), head.stream_epoch, 0)
    assert (await http.get(root, params={"min_cursor": cross})).status_code == 400

    future = events.format_cursor(
        pair.space_id, head.stream_epoch, head.last_seq + 10
    )
    assert (await http.get(root, params={"min_cursor": future})).status_code == 400

    stale_epoch = events.format_cursor(pair.space_id, uuid.uuid4(), 0)
    assert (
        await http.get(root, params={"min_cursor": stale_epoch})
    ).status_code == 410

    assert (
        await http.get(root, params={"min_cursor": "not-a-cursor"})
    ).status_code == 400


async def test_snapshot_rejects_foreign_user_and_missing_head(client, seeded):
    http, holder = client
    sessions, _uid, pair, _running, _message = seeded
    root = f"/api/super-link/spaces/{pair.space_id}/snapshot"

    other = await store.create_user(username=uuid.uuid4().hex, password_hash="unused")
    holder["user"] = other
    assert (await http.get(root)).status_code == 404

    async with sessions.begin() as session:
        await session.execute(
            delete(sl.SuperLinkEvent).where(sl.SuperLinkEvent.space_id == pair.space_id)
        )
        await session.execute(
            delete(sl.SuperLinkEventHead).where(
                sl.SuperLinkEventHead.space_id == pair.space_id
            )
        )
    # Restore the owner through a fresh query rather than reusing a detached row.
    async with sessions() as session:
        holder["user"] = await session.get(store.User, _uid)
    assert (await http.get(root)).status_code == 503


async def test_stream_http_error_matrix(client, seeded):
    http, holder = client
    sessions, _uid, pair, _running, _message = seeded
    head = await _head(sessions, pair.space_id)
    root = f"/api/super-link/spaces/{pair.space_id}/events"

    assert (await http.get(root)).status_code == 400
    assert (
        await http.get(root, params={"after": "not-a-cursor"})
    ).status_code == 400

    cross = events.format_cursor(uuid.uuid4(), head.stream_epoch, 0)
    assert (await http.get(root, params={"after": cross})).status_code == 400

    future = events.format_cursor(
        pair.space_id, head.stream_epoch, head.last_seq + 5
    )
    assert (await http.get(root, params={"after": future})).status_code == 400

    stale_epoch = events.format_cursor(pair.space_id, uuid.uuid4(), 0)
    assert (
        await http.get(root, params={"after": stale_epoch})
    ).status_code == 410

    valid = events.format_cursor(pair.space_id, head.stream_epoch, head.last_seq)
    async with sessions.begin() as session:
        (await session.get(store.User, _uid)).status = "disabled"
    assert (await http.get(root, params={"after": valid})).status_code == 404

    other = await store.create_user(username=uuid.uuid4().hex, password_hash="unused")
    holder["user"] = other
    assert (await http.get(root, params={"after": valid})).status_code == 404


async def test_stream_missing_head_is_503(client, seeded):
    http, _holder = client
    sessions, _uid, pair, _running, _message = seeded
    head = await _head(sessions, pair.space_id)
    valid = events.format_cursor(pair.space_id, head.stream_epoch, head.last_seq)
    async with sessions.begin() as session:
        await session.execute(
            delete(sl.SuperLinkEvent).where(sl.SuperLinkEvent.space_id == pair.space_id)
        )
        row = await session.get(sl.SuperLinkEventHead, pair.space_id)
        await session.delete(row)
    response = await http.get(
        f"/api/super-link/spaces/{pair.space_id}/events", params={"after": valid}
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "event_chain_unavailable"


@pytest.mark.parametrize("error", [OperationalError, ProgrammingError])
async def test_database_errors_map_to_503(client, seeded, monkeypatch, error):
    http, _holder = client
    sessions, _uid, pair, _running, _message = seeded
    head = await _head(sessions, pair.space_id)
    valid = events.format_cursor(pair.space_id, head.stream_epoch, head.last_seq)

    async def broken(*args, **kwargs):
        raise error("SELECT 1", {}, RuntimeError("db unavailable"))

    monkeypatch.setattr(stream, "read_snapshot", broken)
    monkeypatch.setattr(events, "read_events", broken)

    snapshot = await http.get(f"/api/super-link/spaces/{pair.space_id}/snapshot")
    assert snapshot.status_code == 503
    assert snapshot.json()["detail"] == "event_chain_unavailable"

    streamed = await http.get(
        f"/api/super-link/spaces/{pair.space_id}/events", params={"after": valid}
    )
    assert streamed.status_code == 503
    assert streamed.json()["detail"] == "event_chain_unavailable"


async def test_stream_quota_returns_429_without_entering_the_stream(
    client, seeded, monkeypatch
):
    http, _holder = client
    sessions, uid, pair, _running, _message = seeded
    monkeypatch.setattr(get_config(), "super_link_sse_max_connections", 1)
    head = await _head(sessions, pair.space_id)
    valid = events.format_cursor(pair.space_id, head.stream_epoch, head.last_seq)

    lease = await stream.acquire_connection(uid)
    assert lease is not None
    try:
        response = await http.get(
            f"/api/super-link/spaces/{pair.space_id}/events", params={"after": valid}
        )
        assert response.status_code == 429
        assert response.headers["retry-after"] == "5"
        assert response.json()["detail"] == "too_many_connections"
    finally:
        await lease.release()
    assert await stream.LIMITER.count(uid) == 0


async def test_stream_catch_up_and_max_age_close(client, seeded, monkeypatch):
    http, _holder = client
    sessions, _uid, pair, _running, _message = seeded
    head = await _head(sessions, pair.space_id)
    hub = stream.SpaceHintHub(listen=False, poll=False)
    monkeypatch.setattr(stream, "HUB", hub)
    cfg = get_config()
    monkeypatch.setattr(cfg, "super_link_sse_max_age_seconds", 0.08)
    monkeypatch.setattr(cfg, "super_link_sse_heartbeat_seconds", 0.02)
    monkeypatch.setattr(cfg, "super_link_sse_poll_seconds", 0.02)

    after = events.format_cursor(pair.space_id, head.stream_epoch, 0)
    response = await http.get(
        f"/api/super-link/spaces/{pair.space_id}/events", params={"after": after}
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"

    facts = []
    for block in _frames(response.text):
        event, frame_id, data = _parse(block)
        if event == stream.FACT_EVENT:
            facts.append((frame_id, data))
    assert facts, response.text
    assert [int(data["seq"]) for _fid, data in facts] == list(
        range(1, len(facts) + 1)
    )
    for frame_id, data in facts:
        assert frame_id == data["cursor"]


async def test_stream_live_after_run_terminal_keeps_space_open(case, seeded, monkeypatch):
    sessions, uid, pair, running, _message = seeded
    hub = stream.SpaceHintHub(listen=False, poll=False)
    monkeypatch.setattr(stream, "HUB", hub)
    cfg = get_config()
    monkeypatch.setattr(cfg, "super_link_sse_max_age_seconds", 10.0)
    monkeypatch.setattr(cfg, "super_link_sse_heartbeat_seconds", 10.0)
    monkeypatch.setattr(cfg, "super_link_sse_poll_seconds", 0.05)
    monkeypatch.setattr(cfg, "super_link_sse_auth_recheck_seconds", 60.0)

    head = await _head(sessions, pair.space_id)
    lease = await stream.acquire_connection(uid)
    assert lease is not None
    generator = stream.event_stream(
        user_id=uid,
        space_id=pair.space_id,
        after=events.format_cursor(pair.space_id, head.stream_epoch, head.last_seq),
        lease=lease,
    )
    pending = asyncio.create_task(anext(generator))
    await asyncio.sleep(0.08)

    head = await _append_event(
        sessions,
        pair.space_id,
        change_key=f"terminal:{uuid.uuid4()}",
        kind="sl.run.changed",
        run_id=running.run_id,
        source_kind="run",
        source_id=str(running.run_id),
        invalidate=("runs",),
        data={"status": "completed"},
    )
    await hub.dispatch(pair.space_id, head.stream_epoch, head.last_seq)
    first = await asyncio.wait_for(pending, 2)
    event, _frame_id, data = _parse(first)
    assert event == stream.FACT_EVENT
    assert data["type"] == "sl.run.changed"
    assert data["data"]["status"] == "completed"

    async with sessions.begin() as session:
        space = await session.get(sl.SuperLinkSpace, pair.space_id)
        space.control_state = "stopped"
        space.control_version += 1
    head = await _append_event(
        sessions,
        pair.space_id,
        change_key=f"stop:{uuid.uuid4()}",
        kind="sl.space.control_changed",
        data={"control_state": "stopped", "control_version": 1},
        invalidate=("space",),
        source_kind="space",
        source_id=str(pair.space_id),
    )
    await hub.dispatch(pair.space_id, head.stream_epoch, head.last_seq)
    second = await asyncio.wait_for(anext(generator), 2)
    event, _frame_id, data = _parse(second)
    assert event == stream.FACT_EVENT
    assert data["type"] == "sl.space.control_changed"
    assert data["data"]["control_state"] == "stopped"
    assert int(data["seq"]) == head.last_seq

    await generator.aclose()
    assert await stream.LIMITER.count(uid) == 0


async def test_stream_rechecks_head_after_catch_up(seeded, monkeypatch):
    """An event committed during catch-up is read before the stream waits."""
    sessions, uid, pair, _running, _message = seeded
    hub = stream.SpaceHintHub(listen=False, poll=False)
    monkeypatch.setattr(stream, "HUB", hub)
    cfg = get_config()
    monkeypatch.setattr(cfg, "super_link_sse_max_age_seconds", 10.0)
    monkeypatch.setattr(cfg, "super_link_sse_heartbeat_seconds", 10.0)
    monkeypatch.setattr(cfg, "super_link_sse_poll_seconds", 0.05)
    monkeypatch.setattr(cfg, "super_link_sse_auth_recheck_seconds", 60.0)

    original = events.read_events
    late = {"seq": None, "injected": False}

    async def read_then_commit(**kwargs):
        page = await original(**kwargs)
        if not late["injected"] and page.events:
            late["injected"] = True
            head = await _append_event(
                sessions,
                pair.space_id,
                change_key=f"during-catch-up:{uuid.uuid4()}",
                data={"late": True},
            )
            late["seq"] = head.last_seq
        return page

    monkeypatch.setattr(events, "read_events", read_then_commit)

    head = await _head(sessions, pair.space_id)
    lease = await stream.acquire_connection(uid)
    generator = stream.event_stream(
        user_id=uid,
        space_id=pair.space_id,
        after=events.format_cursor(pair.space_id, head.stream_epoch, 0),
        lease=lease,
    )
    seqs = []
    try:
        for _ in range(20):
            frame = await asyncio.wait_for(anext(generator), 2)
            event, _frame_id, data = _parse(frame)
            if event == stream.FACT_EVENT:
                seqs.append(int(data["seq"]))
            if late["seq"] is not None and late["seq"] in seqs:
                break
    finally:
        await generator.aclose()
        assert await stream.LIMITER.count(uid) == 0

    assert late["injected"]
    assert late["seq"] in seqs, seqs


async def test_large_backlog_advances_with_a_consuming_client(seeded, monkeypatch):
    """A 1.2 MiB catch-up cannot overflow the 1 MiB buffer out from under a reader."""
    sessions, uid, pair, _running, _message = seeded
    async with sessions.begin() as session:
        for index in range(100):
            await events.stage_for_space(
                session,
                pair.space_id,
                type="sl.action.recorded",
                change_key=f"bulk:{index}",
                data={"blob": "x" * 12_000},
            )
        await events.seal_changes(session)

    hub = stream.SpaceHintHub(listen=False, poll=False)
    monkeypatch.setattr(stream, "HUB", hub)
    cfg = get_config()
    monkeypatch.setattr(cfg, "super_link_sse_buffer_bytes", 64 * 1024)
    monkeypatch.setattr(cfg, "super_link_sse_buffer_frames", 512)
    monkeypatch.setattr(cfg, "super_link_sse_send_timeout_seconds", 5.0)
    monkeypatch.setattr(cfg, "super_link_sse_max_age_seconds", 20.0)
    monkeypatch.setattr(cfg, "super_link_sse_poll_seconds", 0.05)
    monkeypatch.setattr(cfg, "super_link_sse_heartbeat_seconds", 10.0)
    monkeypatch.setattr(cfg, "super_link_sse_auth_recheck_seconds", 60.0)

    head = await _head(sessions, pair.space_id)
    lease = await stream.acquire_connection(uid)
    generator = stream.event_stream(
        user_id=uid,
        space_id=pair.space_id,
        after=events.format_cursor(pair.space_id, head.stream_epoch, 0),
        lease=lease,
    )
    seqs = []
    try:
        while len(seqs) < head.last_seq:
            frame = await asyncio.wait_for(anext(generator), 5)
            event, _frame_id, data = _parse(frame)
            if event == stream.FACT_EVENT:
                seqs.append(int(data["seq"]))
    finally:
        await generator.aclose()
        assert await stream.LIMITER.count(uid) == 0

    assert seqs == list(range(1, head.last_seq + 1))


async def test_stream_resync_when_epoch_changes(seeded, monkeypatch):
    sessions, uid, pair, _running, _message = seeded
    hub = stream.SpaceHintHub(listen=False, poll=False)
    monkeypatch.setattr(stream, "HUB", hub)
    cfg = get_config()
    monkeypatch.setattr(cfg, "super_link_sse_max_age_seconds", 10.0)
    monkeypatch.setattr(cfg, "super_link_sse_heartbeat_seconds", 10.0)
    monkeypatch.setattr(cfg, "super_link_sse_poll_seconds", 0.05)
    monkeypatch.setattr(cfg, "super_link_sse_auth_recheck_seconds", 60.0)

    head = await _head(sessions, pair.space_id)
    cursor = events.format_cursor(pair.space_id, head.stream_epoch, head.last_seq)
    lease = await stream.acquire_connection(uid)
    generator = stream.event_stream(
        user_id=uid, space_id=pair.space_id, after=cursor, lease=lease
    )
    pending = asyncio.create_task(anext(generator))
    await asyncio.sleep(0.08)

    new_epoch = uuid.uuid4()
    async with sessions.begin() as session:
        row = await session.get(sl.SuperLinkEventHead, pair.space_id)
        row.stream_epoch = new_epoch
    await hub.dispatch(pair.space_id, new_epoch, head.last_seq)

    frame = await asyncio.wait_for(pending, 2)
    event, frame_id, data = _parse(frame)
    assert event == stream.RESYNC_REQUIRED_EVENT
    assert frame_id is None
    assert data["reason"] == "cursor_expired"
    await generator.aclose()
    assert await stream.LIMITER.count(uid) == 0


async def test_stream_auth_required_after_user_disabled(seeded, monkeypatch):
    sessions, uid, pair, _running, _message = seeded
    hub = stream.SpaceHintHub(listen=False, poll=False)
    monkeypatch.setattr(stream, "HUB", hub)
    cfg = get_config()
    monkeypatch.setattr(cfg, "super_link_sse_max_age_seconds", 10.0)
    monkeypatch.setattr(cfg, "super_link_sse_heartbeat_seconds", 10.0)
    monkeypatch.setattr(cfg, "super_link_sse_poll_seconds", 0.05)
    monkeypatch.setattr(cfg, "super_link_sse_auth_recheck_seconds", 0.01)

    head = await _head(sessions, pair.space_id)
    cursor = events.format_cursor(pair.space_id, head.stream_epoch, head.last_seq)
    lease = await stream.acquire_connection(uid)
    generator = stream.event_stream(
        user_id=uid, space_id=pair.space_id, after=cursor, lease=lease
    )
    pending = asyncio.create_task(anext(generator))
    await asyncio.sleep(0.08)

    async with sessions.begin() as session:
        (await session.get(store.User, uid)).status = "disabled"

    frame = await asyncio.wait_for(pending, 2)
    event, frame_id, data = _parse(frame)
    assert event == stream.AUTH_REQUIRED_EVENT
    assert frame_id is None
    assert data["reason"] == "auth_lost"


async def test_stream_unavailable_when_ledger_read_fails(seeded, monkeypatch):
    _sessions, uid, pair, _running, _message = seeded
    hub = stream.SpaceHintHub(listen=False, poll=False)
    monkeypatch.setattr(stream, "HUB", hub)
    monkeypatch.setattr(get_config(), "super_link_sse_max_age_seconds", 10.0)

    async def broken(*args, **kwargs):
        raise RuntimeError("simulated ledger failure")

    monkeypatch.setattr(events, "read_events", broken)
    lease = await stream.acquire_connection(uid)
    generator = stream.event_stream(
        user_id=uid,
        space_id=pair.space_id,
        after=events.format_cursor(pair.space_id, uuid.uuid4(), 0),
        lease=lease,
    )
    frame = await anext(generator)
    event, _frame_id, data = _parse(frame)
    assert event == stream.UNAVAILABLE_EVENT
    assert data["reason"] == "event_chain_unavailable"


async def test_frame_buffer_waits_for_the_consumer_then_times_out():
    buffer = stream.FrameBuffer(max_frames=1, max_bytes=1024)
    assert await buffer.put("one", timeout=1)
    waiting = asyncio.create_task(buffer.put("two", timeout=1))
    await asyncio.sleep(0.02)
    assert not waiting.done(), "a full buffer must apply backpressure"
    assert await buffer.get() == "one"
    assert await waiting
    assert await buffer.get() == "two"

    slow = stream.FrameBuffer(max_frames=1, max_bytes=1024)
    assert await slow.put("one", timeout=1)
    started = time.monotonic()
    assert not await slow.put("two", timeout=0.05)
    assert time.monotonic() - started >= 0.04
    assert slow.closed
    assert await slow.get() is None

    final = stream.FrameBuffer(max_frames=2, max_bytes=1024)
    assert await final.put("one", timeout=1)
    await final.terminate("control")
    assert await final.get() == "control"
    assert await final.get() is None


async def test_connection_limiter_counts_and_releases(monkeypatch):
    limiter = stream.ConnectionLimiter()
    monkeypatch.setattr(get_config(), "super_link_sse_max_connections", 1)
    lease = await limiter.acquire(uuid.uuid4())
    assert lease is not None
    assert await limiter.acquire(lease.user_id) is None
    await lease.release()
    assert await limiter.count(lease.user_id) == 0
    assert await limiter.acquire(lease.user_id) is not None


async def test_hub_notifies_only_on_head_change(case, monkeypatch):
    sessions, _uid, pair = case
    hub = stream.SpaceHintHub(listen=False, poll=False)
    first = await hub.subscribe(pair.space_id)
    second = await hub.subscribe(pair.space_id)
    head = await _head(sessions, pair.space_id)
    await hub.mark_synced(pair.space_id, head.stream_epoch, head.last_seq)

    assert not await hub.dispatch(pair.space_id, head.stream_epoch, head.last_seq)
    assert not await first.wait(0.01)

    head = await _append_event(
        sessions, pair.space_id, change_key=f"hub:{uuid.uuid4()}"
    )
    waiter = asyncio.create_task(first.wait(1.0))
    other = asyncio.create_task(second.wait(1.0))
    await asyncio.sleep(0.02)
    assert await hub.poll_once() == 1
    assert await waiter
    assert await other
    await first.consume()
    await second.consume()

    # An unchanged head must not wake anyone on the next poll.
    assert await hub.poll_once() == 1
    assert not await first.wait(0.02)

    # A failed shared poll wakes subscribers to re-confirm from the ledger; it
    # must not close the subscription or fabricate an unavailable frame.
    def broken_sessionmaker():
        raise RuntimeError("simulated poll failure")

    monkeypatch.setattr(store, "get_sessionmaker", broken_sessionmaker)
    waiter = asyncio.create_task(first.wait(1.0))
    await asyncio.sleep(0.02)
    assert await hub.poll_once() == 0
    assert await waiter
    await first.consume()
    assert not first.closed

    await hub.mark_synced(pair.space_id, head.stream_epoch, head.last_seq - 1)
    assert not await hub.dispatch(pair.space_id, head.stream_epoch, head.last_seq)
    await hub.unsubscribe(first)
    await hub.unsubscribe(second)
    assert hub._tasks == []


async def test_hub_does_not_cache_unsubscribed_spaces(case):
    sessions, _uid, pair = case
    hub = stream.SpaceHintHub(listen=False, poll=False)
    subscription = await hub.subscribe(pair.space_id)
    try:
        for _ in range(100):
            assert not await hub.dispatch(uuid.uuid4(), uuid.uuid4(), 1)
        assert pair.space_id not in hub._known

        head = await _head(sessions, pair.space_id)
        assert await hub.dispatch(pair.space_id, head.stream_epoch, head.last_seq)
        assert set(hub._known) == {pair.space_id}
    finally:
        await hub.unsubscribe(subscription)
    assert pair.space_id not in hub._known


async def test_sse_response_releases_when_send_blocks(seeded, monkeypatch):
    sessions, uid, pair, _running, _message = seeded
    hub = stream.SpaceHintHub(listen=False, poll=False)
    monkeypatch.setattr(stream, "HUB", hub)
    cfg = get_config()
    monkeypatch.setattr(cfg, "super_link_sse_max_age_seconds", 0.1)
    monkeypatch.setattr(cfg, "super_link_sse_send_timeout_seconds", 5.0)
    monkeypatch.setattr(cfg, "super_link_sse_heartbeat_seconds", 10.0)
    monkeypatch.setattr(cfg, "super_link_sse_poll_seconds", 0.05)
    monkeypatch.setattr(cfg, "super_link_sse_auth_recheck_seconds", 60.0)

    head = await _head(sessions, pair.space_id)
    lease = await stream.acquire_connection(uid)
    body = stream.event_stream(
        user_id=uid,
        space_id=pair.space_id,
        after=events.format_cursor(pair.space_id, head.stream_epoch, 0),
        lease=lease,
    )
    response = routes.SSEStreamingResponse(
        body, media_type="text/event-stream", send_timeout=5.0, max_age=0.1
    )
    blocked = asyncio.Event()

    async def send(message):
        if message["type"] == "http.response.start":
            return
        # The client stopped reading: every body send stays suspended.
        await blocked.wait()

    started = time.monotonic()
    await asyncio.wait_for(response.stream_response(send), 2)
    assert time.monotonic() - started < 1.5
    assert await stream.LIMITER.count(uid) == 0
    assert not hub._subs


async def test_runs_page_continues_with_default_timestamps(client, seeded):
    http, _holder = client
    _sessions, _uid, pair, _running, _message = seeded

    seen: list[str] = []
    page = (
        await http.get(
            f"/api/super-link/spaces/{pair.space_id}/runs",
            params={"limit": 1, "newest_first": True},
        )
    ).json()
    seen += [item["run_id"] for item in page["items"]]
    cursor = page["next_after"]
    for _ in range(10):
        if not cursor:
            break
        page = (
            await http.get(
                f"/api/super-link/spaces/{pair.space_id}/runs",
                params={"limit": 1, "newest_first": True, "after": cursor},
            )
        ).json()
        seen += [item["run_id"] for item in page["items"]]
        cursor = page["next_after"]
    assert len(seen) == 2
    assert len(set(seen)) == 2


async def test_list_cursor_precedes_the_page(client, seeded, monkeypatch):
    http, _holder = client
    sessions, _uid, pair, _running, _message = seeded
    before = await _head(sessions, pair.space_id)
    injected = {"done": False}
    original = management.run_status

    async def run_status_with_commit(session, run_id):
        if not injected["done"]:
            injected["done"] = True
            async with sessions.begin() as other:
                await events.stage_for_space(
                    other,
                    pair.space_id,
                    type="sl.space.control_changed",
                    change_key=f"boundary:{uuid.uuid4()}",
                    data={"value": "committed-during-page"},
                )
                await events.seal_changes(other)
        return await original(session, run_id)

    monkeypatch.setattr(management, "run_status", run_status_with_commit)
    response = await http.get(
        f"/api/super-link/spaces/{pair.space_id}/runs", params={"limit": 5}
    )
    assert response.status_code == 200, response.text
    assert injected["done"]
    # The cursor must describe the same boundary as the content, so a commit
    # during item projection cannot make it newer than the page.
    assert response.json()["cursor"] == events.format_cursor(
        pair.space_id, before.stream_epoch, before.last_seq
    )


async def test_sse_response_releases_when_read_hangs(seeded, monkeypatch):
    sessions, uid, pair, _running, _message = seeded
    hub = stream.SpaceHintHub(listen=False, poll=False)
    monkeypatch.setattr(stream, "HUB", hub)
    cfg = get_config()
    monkeypatch.setattr(cfg, "super_link_sse_max_age_seconds", 0.1)
    monkeypatch.setattr(cfg, "super_link_sse_send_timeout_seconds", 5.0)
    monkeypatch.setattr(cfg, "super_link_sse_heartbeat_seconds", 10.0)
    monkeypatch.setattr(cfg, "super_link_sse_poll_seconds", 0.05)
    monkeypatch.setattr(cfg, "super_link_sse_auth_recheck_seconds", 60.0)

    async def hanging_read(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(events, "read_events", hanging_read)
    head = await _head(sessions, pair.space_id)
    lease = await stream.acquire_connection(uid)
    body = stream.event_stream(
        user_id=uid,
        space_id=pair.space_id,
        after=events.format_cursor(pair.space_id, head.stream_epoch, 0),
        lease=lease,
    )
    response = routes.SSEStreamingResponse(
        body, media_type="text/event-stream", send_timeout=5.0, max_age=0.1
    )

    async def send(message):
        return

    started = time.monotonic()
    await asyncio.wait_for(response.stream_response(send), 2)
    assert time.monotonic() - started < 1.5
    assert await stream.LIMITER.count(uid) == 0
    assert not hub._subs


async def test_disabled_feature_returns_404_without_starting_hub(
    client, seeded, monkeypatch
):
    http, _holder = client
    hub = stream.SpaceHintHub(listen=False, poll=False)
    monkeypatch.setattr(stream, "HUB", hub)
    monkeypatch.setattr(get_config(), "super_link_enabled", False)
    _sessions, _uid, pair, _running, _message = seeded
    valid = events.format_cursor(pair.space_id, uuid.uuid4(), 0)

    async def forbidden(*args, **kwargs):
        raise AssertionError("disabled feature must not query events")

    monkeypatch.setattr(events, "read_events", forbidden)
    monkeypatch.setattr(stream, "read_snapshot", forbidden)
    assert (
        await http.get(f"/api/super-link/spaces/{pair.space_id}/snapshot")
    ).status_code == 404
    assert (
        await http.get(
            f"/api/super-link/spaces/{pair.space_id}/events",
            params={"after": valid},
        )
    ).status_code == 404
    assert hub._tasks == []
