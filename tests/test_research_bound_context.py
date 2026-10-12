from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from server import business_service as biz
from server import investment_snapshot, store
from server.config import run_dir_for
from server.investment_context import InvestmentContextResolver


@pytest.mark.asyncio
async def test_new_research_inherits_the_users_most_recent_bound_account() -> None:
    """A new research keeps the account the user most recently chose."""
    await store.init_db()
    user_id = uuid.uuid4()
    first_research_id = uuid.uuid4()

    async with biz.business_transaction() as session:
        session.add(
            store.User(
                id=user_id,
                username=f"inherit-{user_id.hex}",
                password_hash="x",
                status="active",
            )
        )
    async with biz.business_transaction() as session:
        session.add(
            store.Session(id=first_research_id, user_id=user_id, title="已有研究")
        )

    async with biz.business_transaction() as session:
        account = await biz.create_account(
            session,
            user_id=user_id,
            name="主账户",
            base_currency="CNY",
            declared={
                "total_capital": "200000",
                "available_capital": "200000",
                "capital_basis": "tradable_assets",
                "as_of": "2026-10-12T00:00:00Z",
            },
            idempotency_key="inherited-main-account",
        )
        account_id = uuid.UUID(account.result["account_id"])

    async with biz.business_transaction() as session:
        await biz.set_research_link(
            session,
            user_id=user_id,
            research_id=first_research_id,
            account_id=account_id,
            idempotency_key="inherited-existing-link",
        )

    new_research = await store.create_session(user_id=user_id, title="新研究")

    async with biz.business_transaction() as session:
        link = (
            await session.execute(
                select(store.ResearchInvestmentLink).where(
                    store.ResearchInvestmentLink.research_id == new_research.id
                )
            )
        ).scalar_one_or_none()
    assert link is not None
    assert link.account_id == account_id
    assert link.primary_plan_id is None


@pytest.mark.asyncio
async def test_plain_run_freezes_the_research_bound_account_before_launch() -> None:
    """A plain Web chat inherits the account bound to its research."""
    await store.init_db()
    user_id = uuid.uuid4()
    research_id = uuid.uuid4()
    run_id = uuid.uuid4()

    async with biz.business_transaction() as session:
        session.add(
            store.User(
                id=user_id,
                username=f"bound-{user_id.hex}",
                password_hash="x",
                status="active",
            )
        )
    async with biz.business_transaction() as session:
        session.add(store.Session(id=research_id, user_id=user_id, title="工业富联研究"))

    async with biz.business_transaction() as session:
        account = await biz.create_account(
            session,
            user_id=user_id,
            name="主账户",
            base_currency="CNY",
            declared={
                "total_capital": "200000",
                "available_capital": "120000",
                "capital_basis": "tradable_assets",
                "as_of": "2026-10-12T00:00:00Z",
            },
            idempotency_key="bound-account",
        )
        account_id = uuid.UUID(account.result["account_id"])

    async with biz.business_transaction() as session:
        await biz.set_research_link(
            session,
            user_id=user_id,
            research_id=research_id,
            account_id=account_id,
            idempotency_key="bound-link",
        )

    await store.create_run(
        run_id=run_id,
        session_id=research_id,
        user_id=user_id,
        prompt="准备购买工业富联300股，你觉得合适吗",
        pipeline_id="stateful-react-agent",
        run_dir=str(run_dir_for(run_id.hex)),
    )

    created = await investment_snapshot.ensure_research_bound_snapshot(
        run_id=run_id,
        user_id=user_id,
    )
    assert created is True

    async with biz.business_transaction() as session:
        snapshot = await investment_snapshot.get_snapshot(session, user_id=user_id, run_id=run_id)
    assert snapshot is not None
    assert snapshot.source == "research_bound"
    assert snapshot.use_case == "unspecified"
    assert snapshot.account_id == account_id
    assert snapshot.plan_id is None

    context = await InvestmentContextResolver().resolve(run_id=run_id, user_id=user_id)
    assert context is not None
    assert Decimal(context.data["values"]["account.total_capital"]["value"]) == Decimal("200000")


@pytest.mark.asyncio
async def test_research_bound_freeze_never_overwrites_a_submission_snapshot() -> None:
    """Launch-time inheritance is insert-if-absent, never a snapshot rewrite."""
    await store.init_db()
    user_id = uuid.uuid4()
    research_id = uuid.uuid4()
    run_id = uuid.uuid4()
    snapshot_id = uuid.uuid4()

    async with biz.business_transaction() as session:
        session.add(
            store.User(
                id=user_id,
                username=f"manual-{user_id.hex}",
                password_hash="x",
                status="active",
            )
        )
    async with biz.business_transaction() as session:
        session.add(store.Session(id=research_id, user_id=user_id, title="研究"))
    async with biz.business_transaction() as session:
        store.add_run(
            session,
            run_id=run_id,
            session_id=research_id,
            user_id=user_id,
            prompt="已有业务提交",
            pipeline_id="stateful-react-agent",
            run_dir=str(run_dir_for(run_id.hex)),
        )
    async with biz.business_transaction() as session:
        session.add(
            store.RunInvestmentSnapshot(
                id=snapshot_id,
                run_id=run_id,
                user_id=user_id,
                research_id=research_id,
                schema_version=investment_snapshot.SNAPSHOT_SCHEMA_VERSION,
                use_case="general_reading",
                source="manual",
                resolved_json={"account.total_capital": {"value": "1"}},
                missing_json={},
                declared_json={},
                frozen_at=datetime.now(UTC),
            )
        )

    created = await investment_snapshot.ensure_research_bound_snapshot(
        run_id=run_id,
        user_id=user_id,
    )
    assert created is False
    async with biz.business_transaction() as session:
        snapshot = await investment_snapshot.get_snapshot(session, user_id=user_id, run_id=run_id)
    assert snapshot is not None
    assert snapshot.id == snapshot_id
    assert snapshot.source == "manual"
