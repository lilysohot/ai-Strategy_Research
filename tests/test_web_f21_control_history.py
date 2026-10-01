"""F21: user directions and approval verdicts must be durable facts.

Before this, ``steer_queued`` / ``approval_requested`` / ``approval_resolved``
existed only as live SSE frames: "received", "queued" and "actually took effect"
could not be told apart afterwards, a refresh lost a parked approval, and a
mid-run correction never reached the next run's history (history is rendered
from ``turns``).

The contract under test (``.scratch/web-runtime-trace-hardening/
f21-control-history-contract.md``):

* steer:    ``queued`` → ``adopted`` (injected at a turn boundary) | ``dropped``,
            with ``undelivered`` for the 409 case;
* approval: ``pending`` → ``adopted`` | ``rejected`` | ``expired`` | ``abandoned``
            — a timeout must never be recorded as the user declining;
* adoption is written twice on purpose: the record says it took effect, the
  ``turns`` row is what the *next* run sees.

Run with::

    uv run pytest tests/test_web_f21_control_history.py -q
"""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest

from server.config import get_config, run_dir_for
from server.history import STEER_TURN_PREFIX
from server.store import (
    APPROVAL_ABANDONED,
    APPROVAL_ADOPTED,
    APPROVAL_EXPIRED,
    APPROVAL_PENDING,
    APPROVAL_REJECTED,
    CONTROL_KIND_APPROVAL,
    CONTROL_KIND_STEER,
    STEER_ADOPTED,
    STEER_DROPPED,
    STEER_QUEUED,
    STEER_UNDELIVERED,
    create_control,
    create_run,
    ensure_session,
    get_control,
    init_db,
    list_controls,
    list_turns,
)


@pytest.fixture
async def app_client():
    from httpx import ASGITransport, AsyncClient

    from server.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _register(app_client, username: str) -> dict[str, str]:
    await init_db()
    pwd = "Str0ngPass1"
    reg = await app_client.post(
        "/api/auth/register", json={"username": username, "password": pwd}
    )
    assert reg.status_code in (201, 409), reg.text
    login = await app_client.post(
        "/api/auth/login", json={"username": username, "password": pwd}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
async def auth_headers(app_client):
    return await _register(app_client, "f21-user-a")


@pytest.fixture
async def other_user_headers(app_client):
    return await _register(app_client, "f21-user-b")


@pytest.fixture
def isolated_orchestrator(monkeypatch):
    """Private orchestrator: no handle for anything this test did not create."""
    import server.orchestrator as orch_mod

    orch = orch_mod.Orchestrator()
    monkeypatch.setattr(orch_mod, "_orchestrator", orch)
    return orch


@pytest.fixture
def runs_root(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    monkeypatch.setattr(get_config(), "runs_root", root)
    return root


class _FakeStdin:
    """Minimal ``proc.stdin`` stand-in capturing written JSONL lines."""

    def __init__(self) -> None:
        self.data = b""

    def write(self, data: bytes) -> int:
        self.data += data
        return len(data)

    async def drain(self) -> None:
        return None


def _user_id_from(headers: dict[str, str]) -> uuid.UUID:
    from server.security import decode_access_token

    token = headers["Authorization"].removeprefix("Bearer ").strip()
    return decode_access_token(token)


async def _owned_run(headers: dict[str, str], *, status: str = "running") -> tuple[uuid.UUID, uuid.UUID]:
    """Create a session + run owned by the caller (sessions first: F16 FKs)."""
    user_id = _user_id_from(headers)
    session_id = uuid.uuid4()
    run_id = uuid.uuid4()
    await ensure_session(session_id=session_id, user_id=user_id, title="f21")
    await create_run(
        run_id=run_id,
        session_id=session_id,
        user_id=user_id,
        prompt="p",
        pipeline_id="stateful-react-agent",
        run_dir=str(run_dir_for(run_id.hex)),
        status=status,
    )
    return run_id, session_id


def _live_handle(orch, run_id: uuid.UUID, session_id: uuid.UUID, user_id: uuid.UUID):
    """Register a handle whose worker is alive, with the spawn params F21 needs."""
    from server.orchestrator import RunHandle

    proc = SimpleNamespace(returncode=None, stdin=_FakeStdin())
    handle = RunHandle(run_id=run_id.hex, session_id=session_id.hex, proc=proc)
    handle._params = {
        "session_uuid": session_id,
        "user_id": user_id,
        "run_id": run_id.hex,
    }
    orch._handles[run_id.hex] = handle
    return handle


async def _steer(app_client, headers, run_id: uuid.UUID, message: str):
    return await app_client.post(
        f"/api/runs/{run_id.hex}/steer",
        json={"message": message},
        headers=headers,
    )


async def _controls(app_client, headers, run_id: uuid.UUID, **params):
    return await app_client.get(f"/api/runs/{run_id.hex}/controls", headers=headers, params=params)


def _only(records) -> object:
    assert len(records) == 1, f"expected exactly one control record, got {len(records)}"
    return records[0]


# — A1: the record exists and is queryable after the fact ————————————————


async def test_f21_steer_is_recorded_queued_with_its_control_id(
    app_client, auth_headers, isolated_orchestrator
) -> None:
    run_id, session_id = await _owned_run(auth_headers)
    user_id = _user_id_from(auth_headers)
    handle = _live_handle(isolated_orchestrator, run_id, session_id, user_id)
    queue = isolated_orchestrator.subscribe(run_id.hex)

    resp = await _steer(app_client, auth_headers, run_id, "use the 2024 numbers")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["queued"] is True
    assert body["control_id"]

    # The worker got the id: that is what its adoption report will name.
    line = json.loads(handle.proc.stdin.data.decode().strip())
    assert line["action"] == "steer"
    assert line["message"] == "use the 2024 numbers"
    assert line["control_id"] == body["control_id"]

    event = await asyncio.wait_for(queue.get(), timeout=1)
    assert event["type"] == "steer_queued"
    assert event["control_id"] == body["control_id"]

    # A1 (断线前后): a *fresh* read rebuilds the fact the live frame carried.
    listed = await _controls(app_client, auth_headers, run_id)
    assert listed.status_code == 200, listed.text
    payload = listed.json()["controls"]
    assert len(payload) == 1
    assert payload[0]["control_id"] == body["control_id"]
    assert payload[0]["kind"] == CONTROL_KIND_STEER
    assert payload[0]["status"] == STEER_QUEUED
    assert payload[0]["request"]["message"] == "use the 2024 numbers"


# — A3: received but never delivered must still leave a trace ———————————


async def test_f21_steer_without_a_worker_is_recorded_undelivered(
    app_client, auth_headers, isolated_orchestrator
) -> None:
    run_id, _ = await _owned_run(auth_headers)

    resp = await _steer(app_client, auth_headers, run_id, "late direction")
    assert resp.status_code == 409, resp.text
    control_id = resp.json()["detail"]["control_id"]
    assert control_id

    record = await get_control(control_id=uuid.UUID(control_id))
    assert record is not None
    assert record.status == STEER_UNDELIVERED
    assert (record.detail_json or {}).get("http") == 409
    assert record.resolved_at is not None


# — A2 / A6: adopted vs dropped, and only adopted reaches the transcript ——


async def test_f21_adopted_steer_marks_the_record_and_writes_the_turn(
    app_client, auth_headers, isolated_orchestrator
) -> None:
    run_id, session_id = await _owned_run(auth_headers)
    user_id = _user_id_from(auth_headers)
    handle = _live_handle(isolated_orchestrator, run_id, session_id, user_id)
    queue = isolated_orchestrator.subscribe(run_id.hex)
    resp = await _steer(app_client, auth_headers, run_id, "买入价为 12.34 元")
    control_id = resp.json()["control_id"]
    queued = await asyncio.wait_for(queue.get(), timeout=1)
    assert queued["type"] == "steer_queued"

    # The worker confirms the direction was injected at a turn boundary.
    await isolated_orchestrator._record_steer_adopted(
        handle, {"type": "control_applied", "kind": "steer", "control_id": control_id}
    )

    record = await get_control(control_id=uuid.UUID(control_id))
    assert record is not None
    assert record.status == STEER_ADOPTED
    assert record.adopted_turn_seq is not None

    turns = await list_turns(session_id=session_id)
    steer_turns = [t for t in turns if t.content.startswith(STEER_TURN_PREFIX)]
    assert len(steer_turns) == 1
    assert steer_turns[0].content == f"{STEER_TURN_PREFIX}买入价为 12.34 元"
    assert steer_turns[0].seq == record.adopted_turn_seq
    assert steer_turns[0].run_id == run_id

    applied = await asyncio.wait_for(queue.get(), timeout=1)
    assert applied["type"] == "steer_applied"
    assert applied["control_id"] == control_id
    assert applied["turn_index"] == record.adopted_turn_seq

    # Idempotent: a re-delivered frame must not produce a second message.
    await isolated_orchestrator._record_steer_adopted(
        handle, {"type": "control_applied", "kind": "steer", "control_id": control_id}
    )
    turns_after = await list_turns(session_id=session_id)
    assert len([t for t in turns_after if t.content.startswith(STEER_TURN_PREFIX)]) == 1


async def test_f21_steer_still_parked_when_the_run_ends_is_dropped(
    app_client, auth_headers, isolated_orchestrator
) -> None:
    run_id, session_id = await _owned_run(auth_headers)
    user_id = _user_id_from(auth_headers)
    _live_handle(isolated_orchestrator, run_id, session_id, user_id)
    resp = await _steer(app_client, auth_headers, run_id, "never injected")
    control_id = uuid.UUID(resp.json()["control_id"])

    # Negative control for the closure itself: without it the record reads
    # "queued" forever, which is the pre-fix ambiguity.
    assert (await get_control(control_id=control_id)).status == STEER_QUEUED

    await isolated_orchestrator._close_control_records(
        run_id.hex, closed_by="run_finished"
    )

    record = await get_control(control_id=control_id)
    assert record is not None
    assert record.status == STEER_DROPPED
    assert (record.detail_json or {}).get("closed_by") == "run_finished"
    # A direction that never took effect must not enter the transcript — the
    # next run would then treat what the user said as something that happened.
    turns = await list_turns(session_id=session_id)
    assert [t for t in turns if t.content.startswith(STEER_TURN_PREFIX)] == []


async def test_f21_next_run_history_carries_the_adopted_correction(
    app_client, auth_headers, isolated_orchestrator
) -> None:
    """A6: history is rendered from ``turns``, so the correction must be one."""
    from server.history import render_session_history
    from server.orchestrator import _turns_as_of_submission

    run_id, session_id = await _owned_run(auth_headers)

    user_id = _user_id_from(auth_headers)
    handle = _live_handle(isolated_orchestrator, run_id, session_id, user_id)
    resp = await _steer(app_client, auth_headers, run_id, "资金是 50 万，不是 5 万")
    await isolated_orchestrator._record_steer_adopted(
        handle, {"control_id": resp.json()["control_id"]}
    )

    # A later run of the same session renders what the user corrected. Its own
    # question sits after the steer turn, so the F14 submission cutoff must
    # exclude that question while keeping the correction.
    from server.store import append_turn

    later_run = uuid.uuid4()
    await create_run(
        run_id=later_run,
        session_id=session_id,
        user_id=user_id,
        prompt="继续",
        pipeline_id="stateful-react-agent",
        run_dir=str(run_dir_for(later_run.hex)),
        status="running",
    )
    await append_turn(
        session_id=session_id, role="user", content="继续", run_id=later_run
    )
    turns = await list_turns(session_id=session_id)
    history = render_session_history(
        _turns_as_of_submission(turns, current_run_id=later_run)
    )
    assert "资金是 50 万，不是 5 万" in history
    assert "继续" not in history


# — A4 / A5 / A7: the approval state machine ————————————————————————


async def _request_approval(orch, handle, approval_id: str = "appr-1") -> None:
    await orch._persist_control_event(
        handle,
        {
            "type": "approval_requested",
            "approval_id": approval_id,
            "tool_name": "bash",
            "target": "rm -rf /tmp/x",
            "reason": "high risk",
            "preview": "rm -rf /tmp/x",
            "risk": "high",
        },
    )


async def _resolve_approval(orch, handle, decision: str, source: str, approval_id: str = "appr-1") -> None:
    await orch._persist_control_event(
        handle,
        {
            "type": "approval_resolved",
            "approval_id": approval_id,
            "decision": decision,
            "source": source,
            "replacement_command": None,
        },
    )


@pytest.mark.parametrize(
    ("decision", "source", "expected"),
    [
        ("once", "user", APPROVAL_ADOPTED),
        ("reject", "user", APPROVAL_REJECTED),
        # The gate fails closed with decision="reject" for both of these; the
        # record must not attribute them to the user (A4/A5).
        ("reject", "timeout", APPROVAL_EXPIRED),
        ("reject", "stopped", APPROVAL_ABANDONED),
    ],
)
async def test_f21_approval_states_keep_user_timeout_and_stop_apart(
    app_client, auth_headers, isolated_orchestrator, decision, source, expected
) -> None:
    run_id, session_id = await _owned_run(auth_headers)
    user_id = _user_id_from(auth_headers)
    handle = _live_handle(isolated_orchestrator, run_id, session_id, user_id)

    await _request_approval(isolated_orchestrator, handle)
    record = _only(await list_controls(run_id=run_id, kind=CONTROL_KIND_APPROVAL))
    assert record.status == APPROVAL_PENDING
    assert record.request_json["tool_name"] == "bash"
    assert record.resolved_at is None

    await _resolve_approval(isolated_orchestrator, handle, decision, source)
    record = await get_control(control_id=record.id)
    assert record is not None
    assert record.status == expected
    assert record.decision == decision
    assert (record.detail_json or {}).get("source") == source
    assert record.resolved_at is not None


async def test_f21_approval_request_and_verdict_are_idempotent(
    app_client, auth_headers, isolated_orchestrator
) -> None:
    run_id, session_id = await _owned_run(auth_headers)
    user_id = _user_id_from(auth_headers)
    handle = _live_handle(isolated_orchestrator, run_id, session_id, user_id)

    # A re-delivered request frame must not open a second approval.
    await _request_approval(isolated_orchestrator, handle)
    await _request_approval(isolated_orchestrator, handle)
    assert len(await list_controls(run_id=run_id)) == 1

    await _resolve_approval(isolated_orchestrator, handle, "once", "user")
    # A re-delivered verdict must not rewrite the decision that landed.
    await _resolve_approval(isolated_orchestrator, handle, "reject", "timeout")
    record = _only(await list_controls(run_id=run_id))
    assert record.status == APPROVAL_ADOPTED
    assert record.decision == "once"


async def test_f21_pending_approval_is_abandoned_by_the_orphan_sweep(
    app_client, auth_headers, isolated_orchestrator, runs_root
) -> None:
    """A5: after a restart nobody can decide, so it is not "still pending"."""
    run_id, session_id = await _owned_run(auth_headers, status="running")
    user_id = _user_id_from(auth_headers)
    record = await create_control(
        run_id=run_id,
        session_id=session_id,
        user_id=user_id,
        kind=CONTROL_KIND_APPROVAL,
        status=APPROVAL_PENDING,
        external_id="appr-orphan",
        request_payload={"tool_name": "bash"},
    )

    closed = await isolated_orchestrator.reconcile_orphan_runs()
    assert closed == 1

    row = await get_control(control_id=record.id)
    assert row is not None
    assert row.status == APPROVAL_ABANDONED
    assert (row.detail_json or {}).get("closed_by") == "server_restart"


# — A8 / A9: ownership and redaction —————————————————————————————


async def test_f21_controls_route_hides_another_users_records(
    app_client, auth_headers, other_user_headers, isolated_orchestrator
) -> None:
    run_id, session_id = await _owned_run(auth_headers)
    user_id = _user_id_from(auth_headers)
    handle = _live_handle(isolated_orchestrator, run_id, session_id, user_id)
    await _steer(app_client, auth_headers, run_id, "secret plan")
    await isolated_orchestrator._record_steer_adopted(
        handle, {"control_id": (await list_controls(run_id=run_id))[0].id.hex}
    )

    mine = await _controls(app_client, auth_headers, run_id)
    assert mine.status_code == 200
    assert len(mine.json()["controls"]) == 1

    theirs = await _controls(app_client, other_user_headers, run_id)
    assert theirs.status_code == 404
    assert "secret plan" not in theirs.text


async def test_f21_steer_message_is_redacted_before_it_is_stored(
    app_client, auth_headers, isolated_orchestrator
) -> None:
    run_id, session_id = await _owned_run(auth_headers)
    user_id = _user_id_from(auth_headers)
    _live_handle(isolated_orchestrator, run_id, session_id, user_id)

    secret = "sk-abcdef123456"
    resp = await _steer(app_client, auth_headers, run_id, f"key {secret} rotate it")
    control_id = uuid.UUID(resp.json()["control_id"])

    record = await get_control(control_id=control_id)
    assert record is not None
    assert secret not in json.dumps(record.request_json)
    assert "(redacted)" in record.request_json["message"]

    listed = await _controls(app_client, auth_headers, run_id)
    assert secret not in listed.text
    assert "(redacted)" in listed.text


async def test_f21_controls_route_rejects_an_unknown_kind(
    app_client, auth_headers, isolated_orchestrator
) -> None:
    run_id, _ = await _owned_run(auth_headers)
    resp = await _controls(app_client, auth_headers, run_id, kind="nonsense")
    assert resp.status_code == 422
