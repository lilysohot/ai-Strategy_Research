"""Account locks serialize reservations and fills on an isolated PostgreSQL database."""

import asyncio
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select

from server import business_service as biz
from server import capital_accounting, store

pytestmark = [pytest.mark.pg, pytest.mark.usefixtures("pg_clean")]


@pytest.fixture
async def account():
    user = await store.create_user(username="cash-concurrency", password_hash="x")
    async with biz.business_transaction() as session:
        result = await biz.create_account(
            session,
            user_id=user.id,
            name="账户",
            base_currency="CNY",
            declared={"available_capital": "10000", "currency": "CNY"},
            make_default=True,
            idempotency_key="account",
        )
    return user.id, UUID(result.result["account_id"])


async def capital(account, amount):
    research = await store.create_session(user_id=account[0], title="会话")
    async with biz.business_transaction() as session:
        result = await biz.create_capital_plan(
            session,
            user_id=account[0],
            research_id=research.id,
            declared={"allocated_capital": amount, "currency": "CNY"},
            idempotency_key=str(research.id),
        )
    return UUID(result.result["capital_plan_id"])


async def buy(account, capital_id, key):
    async with biz.business_transaction() as session:
        return await biz.create_buy_sell_plan(
            session,
            user_id=account[0],
            capital_plan_id=capital_id,
            declared={
                "symbol": "TEST",
                "price": "10",
                "quantity": "300",
                "side": "buy",
                "currency": "CNY",
            },
            idempotency_key=key,
        )


async def test_competing_sessions_cannot_overallocate(account):
    results = await asyncio.wait_for(
        asyncio.gather(
            capital(account, "6000"),
            capital(account, "6000"),
            return_exceptions=True,
        ),
        10,
    )
    assert sum(isinstance(result, UUID) for result in results) == 1
    assert sum(isinstance(result, biz.ValidationError) for result in results) == 1


async def test_parallel_fills_cannot_overspend_one_session(account):
    capital_id = await capital(account, "5000")
    results = await asyncio.wait_for(
        asyncio.gather(
            buy(account, capital_id, "one"),
            buy(account, capital_id, "two"),
            return_exceptions=True,
        ),
        10,
    )
    assert sum(isinstance(result, biz.WriteOutcome) for result in results) == 1
    assert sum(isinstance(result, biz.ValidationError) for result in results) == 1
    async with biz.business_transaction() as session:
        row = await session.get(store.InvestmentAccount, account[1])
        values = await capital_accounting.account_values(session, row)
        assert values["available_capital"] == Decimal("7000")


async def test_parallel_retries_post_only_once(account):
    capital_id = await capital(account, "6000")
    results = await asyncio.wait_for(
        asyncio.gather(
            buy(account, capital_id, "same"),
            buy(account, capital_id, "same"),
        ),
        10,
    )
    assert sum(result.replayed for result in results) == 1
    async with biz.business_transaction() as session:
        row = await session.get(store.InvestmentAccount, account[1])
        assert row.current_revision == 2
        assert await capital_accounting.cash_effect(session, capital_id) == Decimal("-3000")


async def test_account_then_capital_reader_does_not_deadlock_fill(account):
    capital_id = await capital(account, "6000")
    locked = asyncio.Event()

    async def read_snapshot():
        async with biz.business_transaction() as session:
            await session.execute(
                select(store.InvestmentAccount)
                .where(store.InvestmentAccount.id == account[1])
                .with_for_update()
            )
            locked.set()
            await asyncio.sleep(0.1)
            await session.execute(
                select(store.CapitalPlan)
                .where(store.CapitalPlan.id == capital_id)
                .with_for_update()
            )

    async def concurrent_fill():
        await locked.wait()
        await buy(account, capital_id, "while-snapshot")

    await asyncio.wait_for(asyncio.gather(read_snapshot(), concurrent_fill()), 10)


async def test_rebinding_serializes_with_fill_without_charging_wrong_account(account, monkeypatch):
    capital_id = await capital(account, "6000")
    async with biz.business_transaction() as session:
        result = await biz.create_account(
            session,
            user_id=account[0],
            name="新账户",
            base_currency="CNY",
            declared={"available_capital": "20000", "currency": "CNY"},
            idempotency_key="second-account",
        )
    target_id = UUID(result.result["account_id"])
    read_old_binding = asyncio.Event()
    rebound = asyncio.Event()
    real_lock = capital_accounting.lock_account

    async def paused_lock(session, *, user_id, account_id):
        if account_id == account[1]:
            read_old_binding.set()
            await rebound.wait()
        return await real_lock(session, user_id=user_id, account_id=account_id)

    monkeypatch.setattr(capital_accounting, "lock_account", paused_lock)

    async def switch():
        await read_old_binding.wait()
        try:
            async with biz.business_transaction() as session:
                await biz.bind_capital_account(
                    session,
                    user_id=account[0],
                    capital_plan_id=capital_id,
                    account_id=target_id,
                    expected_revision=1,
                    idempotency_key="switch",
                )
        finally:
            rebound.set()

    results = await asyncio.wait_for(
        asyncio.gather(
            buy(account, capital_id, "stale-fill"),
            switch(),
            return_exceptions=True,
        ),
        10,
    )
    assert isinstance(results[0], biz.RevisionConflictError)
    assert results[1] is None
    await buy(account, capital_id, "retry-fill")
    async with biz.business_transaction() as session:
        original = await session.get(store.InvestmentAccount, account[1])
        target = await session.get(store.InvestmentAccount, target_id)
        assert (await capital_accounting.account_values(session, original))[
            "available_capital"
        ] == 10000
        assert (await capital_accounting.account_values(session, target))[
            "available_capital"
        ] == 17000
        assert await capital_accounting.reservations(session, account[1]) == 0
        assert await capital_accounting.reservations(session, target_id) == 3000


async def test_opposite_account_rebindings_do_not_deadlock(account):
    first = await capital(account, "3000")
    async with biz.business_transaction() as session:
        result = await biz.create_account(
            session,
            user_id=account[0],
            name="新账户",
            base_currency="CNY",
            declared={"available_capital": "10000", "currency": "CNY"},
            idempotency_key="second-account",
            make_default=True,
        )
    second_account_id = UUID(result.result["account_id"])
    second = await capital((account[0], second_account_id), "4000")

    async def switch(capital_id, target_id):
        async with biz.business_transaction() as session:
            return await biz.bind_capital_account(
                session,
                user_id=account[0],
                capital_plan_id=capital_id,
                account_id=target_id,
                expected_revision=1,
                idempotency_key=str(capital_id),
            )

    await asyncio.wait_for(
        asyncio.gather(
            switch(first, second_account_id),
            switch(second, account[1]),
        ),
        10,
    )
    async with biz.business_transaction() as session:
        assert await capital_accounting.reservations(session, account[1]) == 4000
        assert await capital_accounting.reservations(session, second_account_id) == 3000
