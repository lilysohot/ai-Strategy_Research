"""DATA-07: durable input requests, partial answers, conflicts, and one continuation Run."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select

from server import business_events, input_requests, investment_snapshot, store
from server import business_service as biz
from server.app import app
from server.security import create_access_token

pytestmark = pytest.mark.pg


@pytest.fixture
async def case(pg_clean):
    uid, rid = uuid.uuid4(), uuid.uuid4()
    async with biz.business_transaction() as session:
        session.add(store.User(id=uid, username=f"input-{uid.hex}", password_hash="unused"))
        await session.flush()
        session.add(store.Session(id=rid, user_id=uid, title="input research"))
        await session.flush()
        account = await biz.create_account(
            session,
            user_id=uid,
            name="account",
            base_currency="CNY",
            declared={
                "total_capital": "100000",
                "capital_basis": "total",
                "currency": "CNY",
                "as_of": "2026-10-03T00:00:00Z",
            },
            idempotency_key=uuid.uuid4().hex,
        )
        plan = await biz.create_plan(
            session,
            user_id=uid,
            research_id=rid,
            name="plan",
            declared={
                "symbol": "600519.SH",
                "market": "CN",
                "direction": "buy",
                "plan_price": "20",
                "target_price": "25",
                "currency": "CNY",
            },
            idempotency_key=uuid.uuid4().hex,
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://input.test"
    ) as client:
        yield SimpleNamespace(
            uid=uid,
            rid=rid,
            aid=uuid.UUID(account.result["account_id"]),
            pid=uuid.UUID(plan.result["plan_id"]),
            client=client,
            headers={"Authorization": f"Bearer {create_access_token(uid)}"},
        )


def investment(case):
    return {
        "use_case": "plan_analysis",
        "account": {"id": str(case.aid)},
        "plan": {"id": str(case.pid)},
        "idempotency_key": uuid.uuid4().hex,
    }


async def submit_run(case):
    response = await case.client.post(
        "/api/runs",
        json={
            "message": "analyze",
            "session_id": str(case.rid),
            "investment_input": investment(case),
        },
        headers=case.headers,
    )
    assert response.status_code == 202, response.text
    return response.json()


async def create_request(case, source_run_id=None, **extra):
    body = {
        "use_case": "plan_analysis",
        "source_run_id": source_run_id,
        "fields": [
            {"name": "account.total_capital", "unit": "currency", "reason": "confirm"},
            {"name": "plan.target_price", "unit": "currency", "reason": "confirm"},
        ],
        **extra,
    }
    return await case.client.post(
        f"/api/business/sessions/{case.rid}/input-requests",
        json=body,
        headers={**case.headers, "Idempotency-Key": uuid.uuid4().hex},
    )


async def answer(case, request_id, declared, key=None, **extra):
    return await case.client.post(
        f"/api/business/input-requests/{request_id}/answers",
        json={"answer": "明确回答", "declared": declared, **extra},
        headers={**case.headers, "Idempotency-Key": key or uuid.uuid4().hex},
    )


async def test_request_is_durable_and_stops_source_with_input_required(case):
    source = await submit_run(case)
    created = await create_request(case, source["run_id"])
    assert created.status_code == 201, created.text
    request_id = created.json()["request_id"]

    listed = await case.client.get("/api/business/input-requests", headers=case.headers)
    assert listed.status_code == 200
    assert listed.json()["requests"][0]["id"] == request_id
    detail = await case.client.get(
        f"/api/business/input-requests/{request_id}", headers=case.headers
    )
    assert detail.json()["source_run_id"] == source["run_id"]
    assert detail.json()["known_versions"] == {"account": 1, "plan": 1}
    events = await case.client.get("/api/business/events", headers=case.headers)
    assert events.status_code == 200
    assert events.json()["items"][0]["kind"] == "input_required"
    assert events.json()["items"][0]["request_id"] == request_id
    async with biz.business_transaction() as session:
        run = await session.get(store.Run, uuid.UUID(source["run_id"]))
        outbox = (
            await session.execute(
                select(store.RunDispatch).where(store.RunDispatch.run_id == run.id)
            )
        ).scalar_one()
        assert (run.status, run.stopped_by, outbox.status) == (
            "stopped",
            "input_required",
            "abandoned",
        )


async def test_partial_answers_persist_then_create_exactly_one_follow_up(case):
    source = await submit_run(case)
    request_id = (await create_request(case, source["run_id"])).json()["request_id"]
    partial = await answer(case, request_id, {"account": {"total_capital": "80000"}})
    assert partial.status_code == 200, partial.text
    assert partial.json()["status"] == "pending"
    assert partial.json()["remaining_fields"] == ["plan.target_price"]
    assert partial.json()["follow_up_run_id"] is None

    key = uuid.uuid4().hex
    completed = await answer(case, request_id, {"plan": {"target_price": "28"}}, key=key)
    assert completed.status_code == 200, completed.text
    replay = await answer(case, request_id, {"plan": {"target_price": "28"}}, key=key)
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["follow_up_run_id"] == completed.json()["follow_up_run_id"]

    async with biz.business_transaction() as session:
        row = await session.get(store.InputRequest, uuid.UUID(request_id))
        answers = (
            (
                await session.execute(
                    select(store.InputRequestAnswer)
                    .where(store.InputRequestAnswer.request_id == row.id)
                    .order_by(store.InputRequestAnswer.revision)
                )
            )
            .scalars()
            .all()
        )
        follow_up = await session.get(store.Run, row.follow_up_run_id)
        snapshot = (
            await session.execute(
                select(store.RunInvestmentSnapshot).where(
                    store.RunInvestmentSnapshot.run_id == row.follow_up_run_id
                )
            )
        ).scalar_one()
        assert row.status == "answered"
        assert [item.outcome for item in answers] == ["pending_clarification", "answered"]
        assert follow_up.status == "queued"
        assert snapshot.rerun_of_run_id == uuid.UUID(source["run_id"])
        assert snapshot.account_revision == 2
        assert snapshot.plan_revision == 2
        count = (
            await session.execute(
                select(func.count()).select_from(store.Run).where(store.Run.session_id == case.rid)
            )
        ).scalar_one()
        assert count == 2
    events = (await case.client.get("/api/business/events", headers=case.headers)).json()
    assert [item["kind"] for item in events["items"]] == ["input_required", "input_answered"]


@pytest.mark.parametrize("status", ["assumed", "estimated", "pending_clarification"])
async def test_ambiguous_answer_is_recorded_without_changing_business_data(case, status):
    source = await submit_run(case)
    request_id = (await create_request(case, source["run_id"])).json()["request_id"]
    response = await answer(
        case,
        request_id,
        {"account": {"total_capital": {"value": "80000", "status": status}}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending"
    detail = await case.client.get(
        f"/api/business/input-requests/{request_id}", headers=case.headers
    )
    assert detail.json()["answers"][0]["outcome"] == "pending_clarification"
    async with biz.business_transaction() as session:
        account = await session.get(store.InvestmentAccount, case.aid)
        assert account.current_revision == 1


async def test_clear_fields_survive_an_ambiguous_field_in_the_same_answer(case):
    source = await submit_run(case)
    request_id = (await create_request(case, source["run_id"])).json()["request_id"]
    partial = await answer(
        case,
        request_id,
        {
            "account": {"total_capital": "80000"},
            "plan": {"target_price": {"value": "28", "status": "estimated"}},
        },
    )
    assert partial.status_code == 200, partial.text
    assert partial.json()["status"] == "pending"
    assert partial.json()["remaining_fields"] == ["plan.target_price"]

    detail = await case.client.get(
        f"/api/business/input-requests/{request_id}", headers=case.headers
    )
    assert detail.json()["collected"] == {"account": {"total_capital": "80000"}}

    completed = await answer(case, request_id, {"plan": {"target_price": "28"}})
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "answered"


async def test_retracting_a_collected_fact_keeps_request_pending(case):
    source = await submit_run(case)
    request_id = (await create_request(case, source["run_id"])).json()["request_id"]
    first = await answer(case, request_id, {"account": {"total_capital": "80000"}})
    assert first.json()["remaining_fields"] == ["plan.target_price"]

    retracted = await answer(
        case,
        request_id,
        {"account": {"total_capital": {"value": "80000", "status": "pending_clarification"}}},
    )
    assert retracted.json()["remaining_fields"] == [
        "account.total_capital",
        "plan.target_price",
    ]

    later = await answer(case, request_id, {"plan": {"target_price": "28"}})
    assert later.status_code == 200, later.text
    assert later.json()["status"] == "pending"
    assert later.json()["remaining_fields"] == ["account.total_capital"]
    detail = await case.client.get(
        f"/api/business/input-requests/{request_id}", headers=case.headers
    )
    assert detail.json()["collected"] == {"plan": {"target_price": "28"}}
    assert detail.json()["follow_up_run_id"] is None


async def test_concurrent_business_edit_causes_revision_conflict_and_no_answer(case):
    source = await submit_run(case)
    request_id = (await create_request(case, source["run_id"])).json()["request_id"]
    async with biz.business_transaction() as session:
        await biz.update_account(
            session,
            user_id=case.uid,
            account_id=case.aid,
            expected_revision=1,
            declared={"total_capital": "90000"},
            idempotency_key=uuid.uuid4().hex,
        )
    response = await answer(
        case,
        request_id,
        {"account": {"total_capital": "80000"}, "plan": {"target_price": "28"}},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "revision_conflict"
    detail = await case.client.get(
        f"/api/business/input-requests/{request_id}", headers=case.headers
    )
    assert detail.json()["status"] == "pending"
    assert detail.json()["answers"] == []


async def test_user_can_acknowledge_current_revision_after_conflict(case):
    source = await submit_run(case)
    request_id = (await create_request(case, source["run_id"])).json()["request_id"]
    async with biz.business_transaction() as session:
        await biz.update_account(
            session,
            user_id=case.uid,
            account_id=case.aid,
            expected_revision=1,
            declared={"total_capital": "90000"},
            idempotency_key=uuid.uuid4().hex,
        )
    detail = await case.client.get(
        f"/api/business/input-requests/{request_id}", headers=case.headers
    )
    assert detail.status_code == 200
    assert detail.json()["known_versions"] == {"account": 1, "plan": 1}
    assert detail.json()["current_versions"] == {"account": 2, "plan": 1}
    response = await answer(
        case,
        request_id,
        {"account": {"total_capital": "80000"}, "plan": {"target_price": "28"}},
        expected_versions={"account": 2, "plan": 1},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "answered"


@pytest.mark.parametrize("terminal", ["cancelled", "expired"])
async def test_terminal_request_rejects_answer(case, terminal):
    source = await submit_run(case)
    extra = (
        {"expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()}
        if terminal == "expired"
        else {}
    )
    request_id = (await create_request(case, source["run_id"], **extra)).json()["request_id"]
    if terminal == "cancelled":
        cancelled = await case.client.post(
            f"/api/business/input-requests/{request_id}/cancel",
            headers={**case.headers, "Idempotency-Key": uuid.uuid4().hex},
        )
        assert cancelled.status_code == 200
    response = await answer(case, request_id, {"account": {"total_capital": "80000"}})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == f"request_{terminal}"


async def test_foreign_user_cannot_see_or_answer_request(case):
    source = await submit_run(case)
    request_id = (await create_request(case, source["run_id"])).json()["request_id"]
    other_id = uuid.uuid4()
    async with biz.business_transaction() as session:
        session.add(store.User(id=other_id, username=f"other-{other_id.hex}", password_hash="x"))
    headers = {"Authorization": f"Bearer {create_access_token(other_id)}"}
    assert (
        await case.client.get(f"/api/business/input-requests/{request_id}", headers=headers)
    ).status_code == 404
    response = await case.client.post(
        f"/api/business/input-requests/{request_id}/answers",
        json={"answer": "x", "declared": {"account": {"total_capital": "1"}}},
        headers={**headers, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert response.status_code == 404


async def test_notification_cursor_and_read_state_are_owner_scoped(case):
    source = await submit_run(case)
    await create_request(case, source["run_id"])
    first = (await case.client.get("/api/business/events", headers=case.headers)).json()
    event = first["items"][0]
    replay = await case.client.get(
        "/api/business/events", params={"after": event["cursor"]}, headers=case.headers
    )
    assert replay.json()["items"] == []
    assert replay.json()["cursor"] == event["cursor"]
    marked = await case.client.post(
        f"/api/business/events/{event['id']}/read", headers=case.headers
    )
    assert marked.status_code == 204
    refreshed = (await case.client.get("/api/business/events", headers=case.headers)).json()
    assert refreshed["items"][0]["read"] is True

    other_id = uuid.uuid4()
    async with biz.business_transaction() as session:
        session.add(store.User(id=other_id, username=f"notice-{other_id.hex}", password_hash="x"))
    other_headers = {"Authorization": f"Bearer {create_access_token(other_id)}"}
    assert (await case.client.get("/api/business/events", headers=other_headers)).json()[
        "items"
    ] == []
    assert (
        await case.client.post(f"/api/business/events/{event['id']}/read", headers=other_headers)
    ).status_code == 404


async def test_event_cursor_allocation_is_serialized_by_user(case):
    maker = store.get_sessionmaker()
    first_session = maker()
    await first_session.begin()
    first = await business_events.add_event(
        first_session,
        user_id=case.uid,
        research_id=case.rid,
        kind="input_required",
        title="first",
        summary="first",
    )

    second_started = asyncio.Event()

    async def write_second():
        async with maker() as session, session.begin():
            second_started.set()
            return await business_events.add_event(
                session,
                user_id=case.uid,
                research_id=case.rid,
                kind="input_required",
                title="second",
                summary="second",
            )

    second_task = asyncio.create_task(write_second())
    await second_started.wait()
    await asyncio.sleep(0.05)
    assert not second_task.done(), "same-user event writer must wait for commit-order lock"
    await first_session.commit()
    second = await asyncio.wait_for(second_task, timeout=2)
    await first_session.close()

    async with biz.business_transaction() as session:
        rows, cursor = await business_events.list_events(
            session, user_id=case.uid, after=0, limit=100
        )
    assert [row.cursor for row in rows] == [first.cursor, second.cursor]
    assert cursor == second.cursor


async def test_expiry_scan_cannot_overwrite_answer_that_commits_first(case, monkeypatch):
    source = await submit_run(case)
    expires_at = datetime.now(UTC) + timedelta(milliseconds=300)
    request_id = (
        await create_request(case, source["run_id"], expires_at=expires_at.isoformat())
    ).json()["request_id"]

    entered = asyncio.Event()
    release = asyncio.Event()
    real_persist = investment_snapshot.persist_declared

    async def paused_persist(*args, **kwargs):
        entered.set()
        await release.wait()
        return await real_persist(*args, **kwargs)

    monkeypatch.setattr(input_requests.snapshots, "persist_declared", paused_persist)
    answer_task = asyncio.create_task(
        answer(
            case,
            request_id,
            {"account": {"total_capital": "80000"}, "plan": {"target_price": "28"}},
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=2)
    await asyncio.sleep(0.35)
    expiry_task = asyncio.create_task(
        case.client.get(f"/api/business/input-requests/{request_id}", headers=case.headers)
    )
    await asyncio.sleep(0.05)
    release.set()
    answered = await asyncio.wait_for(answer_task, timeout=3)
    detail = await asyncio.wait_for(expiry_task, timeout=3)
    assert answered.status_code == 200, answered.text
    assert detail.status_code == 200
    assert detail.json()["status"] == "answered"


async def test_running_source_is_stopped_and_late_completion_cannot_overwrite(
    case, stub_orchestrator
):
    source = await submit_run(case)
    run_id = uuid.UUID(source["run_id"])
    async with biz.business_transaction() as session:
        run = await session.get(store.Run, run_id, with_for_update=True)
        run.status = "running"
        run.started_at = datetime.now(UTC)
        dispatch = (
            await session.execute(
                select(store.RunDispatch).where(store.RunDispatch.run_id == run_id)
            )
        ).scalar_one()
        dispatch.status = "dispatched"

    created = await create_request(case, source["run_id"])
    assert created.status_code == 201, created.text
    assert created.json()["source_stop_requested"] is True
    assert created.json()["source_stop_confirmed"] is True
    assert stub_orchestrator.stopped == [source["run_id"]]
    assert stub_orchestrator.stop_reasons == ["input_required"]

    await store.update_run_result(run_id=run_id, status="completed", final_answer="late")
    async with biz.business_transaction() as session:
        run = await session.get(store.Run, run_id)
        assert (run.status, run.stopped_by) == ("stopped", "input_required")


async def test_event_origin_without_source_run_uses_explicit_continuation(case):
    continuation = {
        "message": "event analysis",
        "investment_input": {
            "use_case": "plan_analysis",
            "account": {"id": str(case.aid), "expected_revision": 1},
            "plan": {"id": str(case.pid), "expected_revision": 1},
            "idempotency_key": uuid.uuid4().hex,
        },
    }
    created = await create_request(
        case, None, watch_event_id=str(uuid.uuid4()), continuation=continuation
    )
    assert created.status_code == 201, created.text
    completed = await answer(
        case,
        created.json()["request_id"],
        {"account": {"total_capital": "80000"}, "plan": {"target_price": "28"}},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["follow_up_run_id"]
