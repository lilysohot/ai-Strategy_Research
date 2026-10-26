"""规划资金（会话 1:1）与买卖计划（规划资金 1:N）拆分验收（2026-10-26）。

覆盖：

* 会话 ↔ 规划资金一对一：同一会话第二次创建被拒绝，不产生第二条；
* 规划资金累加：多次 ``allocations`` 在现值上相加，不互相覆盖；
* 规划资金重置：显式重设为指定总额，历史版本仍按 ``op_type`` 可追溯；
* 买卖计划与规划资金一对多：同一规划资金可登记多笔实际买卖价格；
* 买卖计划登记必须落在既有规划资金下，缺失所属对象按 ``not_found`` 处理。
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from server import business_service as biz
from server import store

pytestmark = pytest.mark.pg


async def _new_user(session, name: str) -> uuid.UUID:
    user_id = uuid.uuid4()
    session.add(store.User(id=user_id, username=name, password_hash="x", status="active"))
    await session.flush()
    return user_id


async def _new_research(session, user_id: uuid.UUID) -> uuid.UUID:
    research_id = uuid.uuid4()
    session.add(store.Session(id=research_id, user_id=user_id, title="研究"))
    await session.flush()
    return research_id


async def _new_account(session, user_id: uuid.UUID) -> uuid.UUID:
    account_id = uuid.uuid4()
    session.add(
        store.InvestmentAccount(
            id=account_id,
            user_id=user_id,
            name=f"账户-{account_id.hex[:6]}",
            base_currency="CNY",
            archived=False,
            current_revision=0,
        )
    )
    await session.flush()
    return account_id


async def _context(name: str) -> tuple[uuid.UUID, uuid.UUID]:
    async with biz.business_transaction() as session:
        user_id = await _new_user(session, name)
        research_id = await _new_research(session, user_id)
        account_id = await _new_account(session, user_id)
        session.add(
            store.ResearchInvestmentLink(
                research_id=research_id, user_id=user_id, account_id=account_id
            )
        )
    return user_id, research_id


async def _create_capital(
    user_id: uuid.UUID, research_id: uuid.UUID, amount: str, key: str
) -> dict:
    async with biz.business_transaction() as session:
        outcome = await biz.create_capital_plan(
            session,
            user_id=user_id,
            research_id=research_id,
            declared={
                "allocated_capital": {"value": amount},
                "currency": {"value": "CNY"},
            },
            idempotency_key=key,
        )
    return outcome.result


async def test_capital_plan_is_one_to_one_per_research() -> None:
    user_id, research_id = await _context("cp-one")
    first = await _create_capital(user_id, research_id, "10000", "cp-one-1")
    assert first["revision"] == 1

    with pytest.raises(biz.RevisionConflictError) as err:
        await _create_capital(user_id, research_id, "20000", "cp-one-2")
    assert err.value.current["capital_plan_id"] == first["capital_plan_id"]

    async with biz.business_transaction() as session:
        rows = (
            (
                await session.execute(
                    select(store.CapitalPlan).where(store.CapitalPlan.research_id == research_id)
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1


async def test_allocations_accumulate_instead_of_overwriting() -> None:
    user_id, research_id = await _context("cp-accumulate")
    created = await _create_capital(user_id, research_id, "10000", "cp-acc-1")
    plan_id = uuid.UUID(created["capital_plan_id"])

    totals = []
    for index, delta in enumerate(("5000", "2500.5"), start=1):
        async with biz.business_transaction() as session:
            outcome = await biz.allocate_capital(
                session,
                user_id=user_id,
                capital_plan_id=plan_id,
                allocation_delta=delta,
                expected_revision=index,
                idempotency_key=f"cp-acc-{index + 1}",
            )
        totals.append(Decimal(outcome.result["allocated_capital"]))
    assert totals == [Decimal("15000"), Decimal("17500.5")]

    async with biz.business_transaction() as session:
        plan = await biz.get_capital_plan(session, user_id=user_id, research_id=research_id)
        revisions = await biz.list_capital_plan_revisions(
            session, user_id=user_id, capital_plan_id=plan_id, limit=10, offset=0
        )
    assert plan is not None
    assert plan["values"]["allocated_capital"] == Decimal("17500.5")
    assert [row["op_type"] for row in revisions] == ["alloc", "alloc", "initial"]
    # 版本按 revision 倒序：最新一次累加（2500.5）在前。
    assert [Decimal(row["allocation_delta"]) for row in revisions[:2]] == [
        Decimal("2500.5"),
        Decimal("5000"),
    ]


async def test_reset_supersedes_total_but_keeps_history() -> None:
    user_id, research_id = await _context("cp-reset")
    created = await _create_capital(user_id, research_id, "10000", "cp-reset-1")
    plan_id = uuid.UUID(created["capital_plan_id"])

    async with biz.business_transaction() as session:
        outcome = await biz.reset_capital(
            session,
            user_id=user_id,
            capital_plan_id=plan_id,
            allocated_capital="3000",
            expected_revision=1,
            idempotency_key="cp-reset-2",
        )
    assert Decimal(outcome.result["allocated_capital"]) == Decimal("3000")
    assert Decimal(outcome.result["previous_allocated_capital"]) == Decimal("10000")

    async with biz.business_transaction() as session:
        plan = await biz.get_capital_plan(session, user_id=user_id, research_id=research_id)
    assert plan is not None
    assert plan["revision"] == 2
    assert plan["values"]["allocated_capital"] == Decimal("3000")


async def test_buy_sell_plans_are_many_under_one_capital_plan() -> None:
    user_id, research_id = await _context("cp-buysell")
    created = await _create_capital(user_id, research_id, "10000", "cp-bs-1")
    plan_id = uuid.UUID(created["capital_plan_id"])

    async with biz.business_transaction() as session:
        buy = await biz.create_buy_sell_plan(
            session,
            user_id=user_id,
            capital_plan_id=plan_id,
            declared={
                "symbol": {"value": "600519.SH"},
                "market": {"value": "CN"},
                "side": {"value": "buy"},
                "price": {"value": "1680.5"},
                "quantity": {"value": "100"},
                "currency": {"value": "CNY"},
            },
            idempotency_key="cp-bs-2",
        )
        sell = await biz.create_buy_sell_plan(
            session,
            user_id=user_id,
            capital_plan_id=plan_id,
            declared={
                "symbol": {"value": "600519.SH"},
                "market": {"value": "CN"},
                "side": {"value": "sell"},
                "price": {"value": "1750"},
                "currency": {"value": "CNY"},
            },
            idempotency_key="cp-bs-3",
        )
    assert buy.result["values"]["price"] == "1680.5"
    assert sell.result["values"]["side"] == "sell"

    async with biz.business_transaction() as session:
        rows = await biz.list_buy_sell_plans(
            session, user_id=user_id, capital_plan_id=plan_id, limit=10, offset=0
        )
    assert len(rows) == 2
    assert {row["values"]["side"] for row in rows} == {"buy", "sell"}
    assert all(uuid.UUID(row["research_id"]) == research_id for row in rows)


async def test_buy_sell_plan_requires_existing_capital_plan() -> None:
    user_id, _ = await _context("cp-bs-missing")
    with pytest.raises(biz.NotFoundOrForbiddenError):
        async with biz.business_transaction() as session:
            await biz.create_buy_sell_plan(
                session,
                user_id=user_id,
                capital_plan_id=uuid.uuid4(),
                declared={
                    "symbol": {"value": "600519.SH"},
                    "side": {"value": "buy"},
                    "price": {"value": "1680"},
                    "currency": {"value": "CNY"},
                },
                idempotency_key="cp-bs-missing-1",
            )
