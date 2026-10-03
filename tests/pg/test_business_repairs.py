"""Regression cases from the 2026-10-03 business audit, on isolated PostgreSQL."""

import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError

from server import business_service as biz
from server import dispatch_outbox as dispatch
from server import investment_snapshot as snap
from server import store
from server.app import app
from server.config import get_config
from server.security import create_access_token

pytestmark = pytest.mark.pg


async def test_history_migration_round_trip_preserves_existing_rows(case, pg_dsn):
    assert (await submit(case)).status_code == 202
    tables = (
        "investment_account_revisions",
        "investment_plan_revisions",
        "run_investment_snapshots",
    )

    async def fingerprints():
        async with biz.business_transaction() as session:
            return [
                (
                    await session.execute(
                        text(f"SELECT md5(json_agg(t ORDER BY id)::text) FROM {table} t")
                    )
                ).scalar_one()
                for table in tables
            ]

    original = await fingerprints()
    assert all(original)
    root = Path(__file__).resolve().parents[2]
    for action, target in (("downgrade", "0009_run_uploads"), ("upgrade", "head")):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "server/alembic.ini", action, target],
            cwd=root,
            env=dict(os.environ, SERVER_DATABASE_URL=pg_dsn),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, "Isolated history migration failed"
        assert await fingerprints() == original
    with pytest.raises(DBAPIError, match="immutable"):
        async with biz.business_transaction() as session:
            await session.execute(delete(store.RunInvestmentSnapshot))


@pytest.mark.parametrize(
    "model",
    [store.InvestmentAccountRevision, store.InvestmentPlanRevision, store.RunInvestmentSnapshot],
)
@pytest.mark.parametrize("action", ["update", "delete"])
async def test_history_is_immutable_even_via_direct_sql(case, model, action):
    result = await submit(case)
    assert result.status_code == 202
    async with biz.business_transaction() as session:
        row_id = (await session.execute(select(model.id))).scalar_one()
    statement = (
        delete(model).where(model.id == row_id)
        if action == "delete"
        else (
            update(model)
            .where(model.id == row_id)
            .values(
                **(
                    {"schema_version": "corrupted"}
                    if model is store.RunInvestmentSnapshot
                    else {"record_state": "corrupted"}
                )
            )
        )
    )
    with pytest.raises(DBAPIError, match="immutable"):
        async with biz.business_transaction() as session:
            await session.execute(statement)


async def test_concurrent_edits_return_one_version_conflict(case):
    results = await asyncio.gather(
        update_account(case, 1, {"total_capital": "80000"}),
        update_account(case, 1, {"total_capital": "60000"}),
        return_exceptions=True,
    )
    assert sum(isinstance(result, biz.RevisionConflictError) for result in results) == 1
    assert sum(isinstance(result, biz.WriteOutcome) for result in results) == 1


async def test_two_dispatchers_cannot_claim_different_runs_of_one_research(case, stub_orchestrator):
    # More rows than one claimant locks forces the other to inspect a different batch.
    for _ in range(20):
        result = await submit(case)
        assert result.status_code == 202, result.text
    await asyncio.gather(
        dispatch.dispatch_once(stub_orchestrator), dispatch.dispatch_once(stub_orchestrator)
    )
    assert len(stub_orchestrator.submitted) == 1


@pytest.fixture
async def case(pg_clean, tmp_path, monkeypatch):
    monkeypatch.setattr(get_config(), "runs_root", tmp_path / "runs")
    monkeypatch.setenv("SERVER_RUNS_ROOT", str(tmp_path / "runs"))
    uid, rid = uuid.uuid4(), uuid.uuid4()
    async with biz.business_transaction() as session:
        session.add(store.User(id=uid, username="repair-test", password_hash="unused"))
        await session.flush()
        session.add(store.Session(id=rid, user_id=uid, title="research"))
        await session.flush()
        account = await biz.create_account(
            session,
            user_id=uid,
            name="account",
            base_currency="CNY",
            declared={
                "total_capital": "100000",
                "currency": "CNY",
                "capital_basis": "total",
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
        transport=httpx.ASGITransport(app=app), base_url="http://repair.test"
    ) as client:
        yield SimpleNamespace(
            uid=uid,
            rid=rid,
            aid=uuid.UUID(account.result["account_id"]),
            pid=uuid.UUID(plan.result["plan_id"]),
            client=client,
            headers={"Authorization": f"Bearer {create_access_token(uid)}"},
        )


def investment(case, **extra):
    return {
        "use_case": "plan_analysis",
        "account": {"id": str(case.aid)},
        "plan": {"id": str(case.pid)},
        "idempotency_key": uuid.uuid4().hex,
        **extra,
    }


async def submit(case, data=None, *, research_id=None, file=None):
    body = {
        "message": "analyze",
        "session_id": str(research_id or case.rid),
        "investment_input": data if data is not None else investment(case),
    }
    if file is None:
        return await case.client.post("/api/runs", json=body, headers=case.headers)
    body["investment_input"] = json.dumps(body["investment_input"])
    return await case.client.post(
        "/api/runs",
        data=body,
        files={"files": ("input.txt", file, "text/plain")},
        headers=case.headers,
    )


async def update_account(case, revision, declared):
    async with biz.business_transaction() as session:
        return await biz.update_account(
            session,
            user_id=case.uid,
            account_id=case.aid,
            expected_revision=revision,
            declared=declared,
            idempotency_key=uuid.uuid4().hex,
        )


@pytest.mark.parametrize("status", ["draft_pending", "pending_clarification", "absent"])
async def test_pending_values_never_become_effective(case, status):
    response = await case.client.patch(
        f"/api/business/accounts/{case.aid}",
        json={
            "expected_revision": 1,
            "declared": {"total_capital": {"value": "90000", "status": status}},
        },
        headers={**case.headers, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert response.status_code == 200, response.text
    assert response.json()["record_state"] == "incomplete"
    result = await submit(case)
    assert result.status_code == 400, result.text


async def test_cleared_capital_stays_missing_after_unrelated_edit(case):
    await update_account(case, 1, {"total_capital": None})
    await update_account(case, 2, {"capital_basis": "available"})
    async with biz.business_transaction() as session:
        row = (
            await session.execute(
                select(store.InvestmentAccountRevision).where(
                    store.InvestmentAccountRevision.account_id == case.aid,
                    store.InvestmentAccountRevision.revision == 3,
                )
            )
        ).scalar_one()
        assert row.total_capital is None
        assert row.record_state == "incomplete"
    assert (await submit(case)).status_code == 400


async def test_incomplete_account_can_be_completed_using_available_capital(case):
    async with biz.business_transaction() as session:
        outcome = await biz.create_account(
            session,
            user_id=case.uid,
            name="incomplete",
            base_currency="CNY",
            declared={},
            use_case="plan_analysis",
            allow_incomplete=True,
            idempotency_key=uuid.uuid4().hex,
        )
    case.aid = uuid.UUID(outcome.result["account_id"])
    outcome = await update_account(
        case,
        1,
        {
            "available_capital": "50000",
            "currency": "CNY",
            "capital_basis": "available",
            "as_of": "2026-10-03T00:00:00Z",
        },
    )
    assert outcome.result["record_state"] == "submitted"
    assert (await submit(case)).status_code == 202


@pytest.mark.parametrize("pending", [False, True])
async def test_trade_correction_does_not_restore_zero_or_pending_values(case, pending):
    async with biz.business_transaction() as session:
        trade = await biz.register_trade(
            session,
            user_id=case.uid,
            account_id=case.aid,
            declared={
                "symbol": "600519.SH",
                "market": "CN",
                "side": "buy",
                "quantity": "10",
                "price": "18",
                "currency": "CNY",
                "traded_at": "2026-10-03T00:00:00Z",
            },
            idempotency_key=uuid.uuid4().hex,
        )
    patch = (
        {"price": {"value": "12", "status": "pending_clarification"}, "fees": "1"}
        if pending
        else {"price": "0"}
    )
    if pending:
        with pytest.raises(biz.PurposeRequirementError):
            async with biz.business_transaction() as session:
                await biz.correct_trade(
                    session,
                    user_id=case.uid,
                    trade_id=uuid.UUID(trade.result["trade_id"]),
                    declared=patch,
                    idempotency_key=uuid.uuid4().hex,
                )
    else:
        async with biz.business_transaction() as session:
            result = await biz.correct_trade(
                session,
                user_id=case.uid,
                trade_id=uuid.UUID(trade.result["trade_id"]),
                declared=patch,
                idempotency_key=uuid.uuid4().hex,
            )
            corrected = await session.get(store.TradeRecord, uuid.UUID(result.result["trade_id"]))
            assert corrected.price == Decimal("0")


@pytest.mark.parametrize("field,value", [("symbol", "OTHER"), ("currency", "USD")])
async def test_snapshot_rejects_mismatched_trade(case, field, value):
    declared = {
        "symbol": "600519.SH",
        "market": "CN",
        "side": "buy",
        "quantity": "10",
        "price": "18",
        "currency": "CNY",
        "traded_at": "2026-10-03T00:00:00Z",
    }
    declared[field] = value
    async with biz.business_transaction() as session:
        trade = await biz.register_trade(
            session,
            user_id=case.uid,
            account_id=case.aid,
            declared=declared,
            idempotency_key=uuid.uuid4().hex,
        )
    result = await submit(
        case, investment(case, use_case="holding_cost", trade={"id": trade.result["trade_id"]})
    )
    assert result.status_code == 400, result.text


async def test_partial_declaration_uses_saved_fields(case):
    spec = snap.parse_investment_input(investment(case, declared={"total_capital": "80000"}))
    async with biz.business_transaction() as session:
        resolved = await snap.resolve_for_run(
            session, user_id=case.uid, research_id=case.rid, spec=spec
        )
    assert not resolved.missing
    assert Decimal(resolved.values["total_capital"]["value"]) == Decimal("80000")


async def test_save_and_analyze_is_atomic_and_replayable(case):
    data = investment(
        case,
        declared={"total_capital": "80000"},
        account={"id": str(case.aid), "expected_revision": 1},
    )
    first = await submit(case, data)
    assert first.status_code == 202, first.text
    second = await submit(case, data)
    assert second.status_code == 202, second.text
    assert first.json()["run_id"] == second.json()["run_id"]
    assert first.json()["operation_id"]
    async with biz.business_transaction() as session:
        account = await session.get(store.InvestmentAccount, case.aid)
        assert account.current_revision == 2
        row = (
            await session.execute(
                select(store.InvestmentAccountRevision).where(
                    store.InvestmentAccountRevision.account_id == case.aid,
                    store.InvestmentAccountRevision.revision == 2,
                )
            )
        ).scalar_one()
        assert row.total_capital == Decimal("80000")
        snapshot = await snap.get_snapshot(
            session, user_id=case.uid, run_id=uuid.UUID(first.json()["run_id"])
        )
        assert snapshot.account_revision == 2


async def test_failed_analysis_rolls_back_business_write(case):
    data = investment(
        case,
        declared={"total_capital": "80000"},
        account={"id": str(case.aid), "expected_revision": 1},
        plan={"id": str(uuid.uuid4())},
    )
    assert (await submit(case, data)).status_code == 404
    async with biz.business_transaction() as session:
        assert (await session.get(store.InvestmentAccount, case.aid)).current_revision == 1


async def test_new_research_created_with_business_run(case):
    rid = uuid.uuid4()
    result = await submit(
        case, {"use_case": "general_reading", "idempotency_key": uuid.uuid4().hex}, research_id=rid
    )
    assert result.status_code == 202, result.text
    async with biz.business_transaction() as session:
        assert (await session.get(store.Session, rid)).user_id == case.uid


async def test_completed_runs_release_queue_capacity(case, stub_orchestrator, monkeypatch):
    monkeypatch.setattr(get_config(), "dispatch_research_queue_limit", 1)
    first = await submit(case)
    assert first.status_code == 202, first.text
    assert await dispatch.dispatch_once(stub_orchestrator) == 1
    async with biz.business_transaction() as session:
        (await session.get(store.Run, uuid.UUID(first.json()["run_id"]))).status = "completed"
    second = await submit(case)
    assert second.status_code == 202, second.text


async def test_changed_attachment_is_not_an_idempotent_replay(case):
    data = investment(case)
    assert (await submit(case, data, file=b"first")).status_code == 202
    second = await submit(case, data, file=b"changed")
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "idempotency_key_reuse"


async def test_expired_dispatcher_cannot_submit_after_takeover(
    case, monkeypatch, stub_orchestrator
):
    first = await submit(case)
    run_id = uuid.UUID(first.json()["run_id"])
    paused, resume = asyncio.Event(), asyncio.Event()
    calls = 0

    async def delayed_publish(_):
        nonlocal calls
        calls += 1
        if calls == 1:
            paused.set()
            await resume.wait()
        return 0

    monkeypatch.setattr(dispatch.uploads, "publish_for_run", delayed_publish)
    task = asyncio.create_task(dispatch.dispatch_once(stub_orchestrator))
    try:
        await asyncio.wait_for(paused.wait(), 5)
        async with biz.business_transaction() as session:
            row = await dispatch.get_for_run(session, run_id=run_id)
            row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await dispatch.dispatch_once(stub_orchestrator)
    finally:
        resume.set()
        await task
    assert len(stub_orchestrator.submitted) == 1


async def test_rerun_uses_latest_saved_capital(case):
    first = await submit(
        case,
        investment(
            case,
            declared={"total_capital": "80000"},
            account={"id": str(case.aid), "expected_revision": 1},
        ),
    )
    assert first.status_code == 202, first.text
    async with biz.business_transaction() as session:
        revision = (await session.get(store.InvestmentAccount, case.aid)).current_revision
    await update_account(case, revision, {"total_capital": "60000"})
    result = await case.client.post(
        f"/api/runs/{first.json()['run_id']}/rerun",
        json={},
        headers={**case.headers, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert result.status_code == 202, result.text
    async with biz.business_transaction() as session:
        snapshot = await snap.get_snapshot(
            session, user_id=case.uid, run_id=uuid.UUID(result.json()["run_id"])
        )
        assert Decimal(snapshot.resolved_json["total_capital"]["value"]) == Decimal("60000")


async def test_rerun_cannot_change_research(case):
    first = await submit(case)
    result = await case.client.post(
        f"/api/runs/{first.json()['run_id']}/rerun",
        json={"session_id": str(uuid.uuid4())},
        headers={**case.headers, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert result.status_code == 400, result.text


@pytest.mark.parametrize(
    "patch",
    [
        {"direction": "nonsense"},
        {"plan_price": None, "plan_price_low": "10"},
        {"plan_price": None, "plan_price_low": "30", "plan_price_high": "20"},
    ],
)
async def test_invalid_plan_cannot_be_used_for_analysis(case, patch):
    async with biz.business_transaction() as session:
        try:
            await biz.update_plan(
                session,
                user_id=case.uid,
                plan_id=case.pid,
                expected_revision=1,
                declared=patch,
                idempotency_key=uuid.uuid4().hex,
            )
        except biz.BusinessError:
            return
    assert (await submit(case)).status_code == 400
