"""Cash/reservation regression tests on the isolated database, never the live account."""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from server import business_service as biz
from server import capital_accounting as accounting
from server import store


def declared(**values):
    return {key: {"value": value} for key, value in values.items()}


@pytest.fixture
async def context():
    await store.init_db()
    user = await store.create_user(username="cash-test", password_hash="x")
    async with biz.business_transaction() as session:
        account = await biz.create_account(
            session,
            user_id=user.id,
            name="主账户",
            base_currency="CNY",
            declared=declared(total_capital="10000", available_capital="10000", currency="CNY"),
            idempotency_key="account",
            make_default=True,
        )
    research = await store.create_session(user_id=user.id, title="资金联动")
    return user.id, research.id, UUID(account.result["account_id"])


async def create_capital(context, amount="6000", **kwargs):
    user_id, research_id, _ = context
    async with biz.business_transaction() as session:
        return await biz.create_capital_plan(
            session,
            user_id=user_id,
            research_id=research_id,
            declared=declared(allocated_capital=amount, currency=kwargs.get("currency", "CNY")),
            idempotency_key=kwargs.get("key", str(uuid4())),
            account_id=kwargs.get("account_id"),
        )


async def fill(context, capital, key=None, **values):
    data = {
        "symbol": "600000.SH",
        "side": "buy",
        "price": "10",
        "quantity": "100",
        "currency": "CNY",
    }
    data.update(values)
    async with biz.business_transaction() as session:
        return await biz.create_buy_sell_plan(
            session,
            user_id=context[0],
            capital_plan_id=UUID(capital.result["capital_plan_id"]),
            declared=declared(**{k: v for k, v in data.items() if v is not None}),
            idempotency_key=key or str(uuid4()),
        )


async def balances(context):
    async with biz.business_transaction() as session:
        account = await session.get(store.InvestmentAccount, context[2])
        values = await accounting.account_values(session, account)
        summary = await accounting.account_summary(session, account)
        plan = await biz.get_capital_plan(session, user_id=context[0], research_id=context[1])
        return values, summary, plan, account.current_revision


async def second_account(context, amount="20000", currency="CNY"):
    async with biz.business_transaction() as session:
        result = await biz.create_account(
            session,
            user_id=context[0],
            name="另一个账户",
            base_currency=currency,
            declared=declared(available_capital=amount, currency=currency),
            idempotency_key=str(uuid4()),
        )
    return UUID(result.result["account_id"])


async def rebind(context, capital, account_id, key="bind", revision=1):
    async with biz.business_transaction() as session:
        return await biz.bind_capital_account(
            session,
            user_id=context[0],
            capital_plan_id=UUID(capital.result["capital_plan_id"]),
            account_id=account_id,
            expected_revision=revision,
            idempotency_key=key,
        )


async def test_explicit_account_creation_and_fills_leave_default_unchanged(context):
    selected = await second_account(context)
    capital = await create_capital(context, account_id=selected)
    assert capital.result["account_id"] == str(selected)
    await fill(context, capital)
    original, original_summary, _, original_revision = await balances(context)
    chosen, chosen_summary, plan, _ = await balances((*context[:2], selected))
    assert original["available_capital"] == 10000 and original_revision == 1
    assert Decimal(original_summary["reserved_capital"]) == 0
    assert chosen["available_capital"] == 19000
    assert Decimal(chosen_summary["reserved_capital"]) == 5000
    assert plan["account_binding_locked"] is True
    async with biz.business_transaction() as session:
        preference = await session.get(store.UserInvestmentPreference, context[0])
        link = await session.scalar(
            select(store.ResearchInvestmentLink).where(
                store.ResearchInvestmentLink.research_id == context[1]
            )
        )
        assert preference.default_account_id == context[2]
        assert link.account_id == selected


async def test_rebind_moves_reservations_atomically_and_replays(context):
    capital = await create_capital(context)
    await fill(context, capital, quantity=None)
    selected = await second_account(context)
    first = await rebind(context, capital, selected)
    replay = await rebind(context, capital, selected)
    assert replay.replayed and replay.result == first.result
    assert first.result["revision"] == 2
    original, summary, _, revision = await balances(context)
    chosen, chosen_summary, plan, _ = await balances((*context[:2], selected))
    assert original["available_capital"] == 10000 and revision == 1
    assert Decimal(summary["reserved_capital"]) == 0
    assert chosen["available_capital"] == 20000
    assert Decimal(chosen_summary["reserved_capital"]) == 6000
    assert plan["account_binding_locked"] is False
    async with biz.business_transaction() as session:
        history = (
            await session.scalars(
                select(store.CapitalPlanRevision)
                .where(
                    store.CapitalPlanRevision.capital_plan_id
                    == UUID(capital.result["capital_plan_id"])
                )
                .order_by(store.CapitalPlanRevision.revision)
            )
        ).all()
        assert [row.account_id for row in history] == [context[2], selected]
        link = await session.scalar(
            select(store.ResearchInvestmentLink).where(
                store.ResearchInvestmentLink.research_id == context[1]
            )
        )
        assert link.account_id == selected
    await fill(context, capital)
    chosen, _, _, _ = await balances((*context[:2], selected))
    assert chosen["available_capital"] == 19000


@pytest.mark.parametrize("failure", ["insufficient", "currency", "archived", "foreign", "stale"])
async def test_failed_binding_preserves_original_reservation(context, failure):
    capital = await create_capital(context)
    selected = await second_account(
        context,
        amount="1000" if failure == "insufficient" else "20000",
        currency="USD" if failure == "currency" else "CNY",
    )
    if failure in {"archived", "foreign"}:
        other = await store.create_user(username="other-binding", password_hash="x")
        async with biz.business_transaction() as session:
            account = await session.get(store.InvestmentAccount, selected)
            if failure == "archived":
                account.archived = True
            else:
                account.user_id = other.id
    with pytest.raises(biz.BusinessError):
        await rebind(context, capital, selected, revision=0 if failure == "stale" else 1)
    _, summary, plan, _ = await balances(context)
    assert Decimal(summary["reserved_capital"]) == 6000
    assert plan["account_id"] == str(context[2])
    assert plan["revision"] == 1


@pytest.mark.parametrize("archived", [False, True])
async def test_booked_history_prevents_rebinding_even_after_reversal(context, archived):
    capital = await create_capital(context)
    entry = await fill(context, capital)
    if archived:
        async with biz.business_transaction() as session:
            await biz.archive_buy_sell_plan(
                session,
                user_id=context[0],
                buy_sell_plan_id=UUID(entry.result["buy_sell_plan_id"]),
                idempotency_key="archive-before-bind",
            )
    selected = await second_account(context)
    with pytest.raises(biz.ValidationError, match="已有资金入账"):
        await rebind(context, capital, selected)
    _, _, plan, _ = await balances(context)
    assert plan["account_binding_locked"] is True
    assert plan["account_id"] == str(context[2])


async def test_existing_unbound_budget_can_bind(context):
    capital = await create_capital(context)
    async with biz.business_transaction() as session:
        plan = await session.get(store.CapitalPlan, UUID(capital.result["capital_plan_id"]))
        plan.account_id = None  # A legacy session predating account linking.
    result = await rebind(context, capital, context[2])
    assert result.result["account_id"] == str(context[2])
    _, summary, _, _ = await balances(context)
    assert Decimal(summary["reserved_capital"]) == 6000


async def test_explicit_foreign_account_cannot_create_capital(context):
    other = await store.create_user(username="foreign-account", password_hash="x")
    selected = await second_account((other.id, context[1], context[2]))
    with pytest.raises(biz.NotFoundOrForbiddenError):
        await create_capital(context, account_id=selected)
    _, summary, plan, _ = await balances(context)
    assert plan is None and Decimal(summary["reserved_capital"]) == 0


async def test_http_create_binding_and_replay_contract(context):
    import httpx

    from server.app import app
    from server.security import create_access_token

    selected = await second_account(context)
    headers = {"Authorization": f"Bearer {create_access_token(context[0])}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://binding.test",
        headers=headers,
    ) as client:
        created = await client.post(
            f"/api/business/sessions/{context[1]}/capital-plan",
            json={
                "account_id": str(selected),
                "declared": declared(allocated_capital="6000", currency="CNY"),
            },
            headers={"Idempotency-Key": "http-create"},
        )
        assert created.status_code == 201, created.text
        assert created.json()["account_id"] == str(selected)
        path = f"/api/business/capital-plans/{created.json()['capital_plan_id']}/account"
        data = {"account_id": str(context[2]), "expected_revision": 1}
        no_key = await client.post(path, json=data)
        assert no_key.status_code == 400
        bound = await client.post(path, json=data, headers={"Idempotency-Key": "http-bind"})
        assert bound.status_code == 200, bound.text
        replay = await client.post(path, json=data, headers={"Idempotency-Key": "http-bind"})
        assert replay.status_code == 200 and replay.json()["replayed"] is True
        malformed = await client.post(
            path,
            json={**data, "expected_revision": True},
            headers={"Idempotency-Key": "http-malformed"},
        )
        assert malformed.status_code == 400
        view = await client.get(f"/api/business/sessions/{context[1]}/capital-plan")
        assert view.json()["capital_plan"]["account_id"] == str(context[2])
        assert view.json()["capital_plan"]["account_binding_locked"] is False


async def test_buy_sell_fees_budget_and_idempotency(context):
    capital = await create_capital(context)
    first = await fill(context, capital, key="buy", fees="5")
    replay = await fill(context, capital, key="buy", fees="5")
    assert replay.replayed and replay.result == first.result
    values, summary, plan, revision = await balances(context)
    assert values["available_capital"] == Decimal("8995")
    assert values["total_capital"] == Decimal("10000")
    assert Decimal(summary["reserved_capital"]) == Decimal("4995")
    assert Decimal(summary["allocatable_capital"]) == Decimal("4000")
    assert Decimal(plan["funding"]["remaining_capital"]) == Decimal("4995")
    assert revision == 2
    await fill(context, capital, side="sell", price="12", quantity="50", fees="2")
    values, summary, plan, revision = await balances(context)
    assert values["available_capital"] == Decimal("9593")
    assert Decimal(plan["funding"]["remaining_capital"]) == Decimal("5593")
    assert revision == 3


async def test_cross_session_budget_and_reset_release(context):
    capital = await create_capital(context)
    research = await store.create_session(user_id=context[0], title="另一会话")
    second = context[0], research.id, context[2]
    with pytest.raises(biz.ValidationError):
        await create_capital(second, "5000")
    async with biz.business_transaction() as session:
        await biz.reset_capital(
            session,
            user_id=context[0],
            capital_plan_id=UUID(capital.result["capital_plan_id"]),
            allocated_capital="4000",
            expected_revision=1,
            idempotency_key="reset",
        )
    await create_capital(second, "6000")
    _, summary, _, _ = await balances(context)
    assert Decimal(summary["allocatable_capital"]) == 0


async def test_fill_correction_archive_and_replay(context):
    capital = await create_capital(context)
    bought = await fill(context, capital)
    async with biz.business_transaction() as session:
        await biz.update_buy_sell_plan(
            session,
            user_id=context[0],
            buy_sell_plan_id=UUID(bought.result["buy_sell_plan_id"]),
            declared=declared(price="12", fees="3"),
            expected_revision=1,
            idempotency_key="correct",
        )
    values, _, _, revision = await balances(context)
    assert values["available_capital"] == Decimal("8797") and revision == 3
    for key in ("archive", "archive", "archive-again"):
        async with biz.business_transaction() as session:
            await biz.archive_buy_sell_plan(
                session,
                user_id=context[0],
                buy_sell_plan_id=UUID(bought.result["buy_sell_plan_id"]),
                idempotency_key=key,
            )
    values, _, _, revision = await balances(context)
    assert values["available_capital"] == Decimal("10000") and revision == 4


@pytest.mark.parametrize(
    "values",
    [
        {"quantity": "601"},
        {"currency": "USD"},
        {"quantity": "0"},
        {"price": "0"},
        {"fees": "-1"},
    ],
)
async def test_failed_fill_is_atomic(context, values):
    capital = await create_capital(context)
    with pytest.raises(biz.BusinessError):
        await fill(context, capital, **values)
    account, _, _, revision = await balances(context)
    assert account["available_capital"] == 10000 and revision == 1
    async with biz.business_transaction() as session:
        assert (
            await session.execute(select(func.count()).select_from(store.BuySellPlan))
        ).scalar_one() == 0


async def test_price_only_fill_books_once_after_quantity_supplied(context):
    capital = await create_capital(context)
    entry = await fill(context, capital, quantity=None)
    values, _, plan, revision = await balances(context)
    assert values["available_capital"] == 10000 and revision == 1
    assert plan["funding"]["unbooked_count"] == 1
    async with biz.business_transaction() as session:
        await biz.update_buy_sell_plan(
            session,
            user_id=context[0],
            buy_sell_plan_id=UUID(entry.result["buy_sell_plan_id"]),
            declared=declared(quantity="100"),
            expected_revision=1,
            idempotency_key="quantity",
        )
    values, _, plan, revision = await balances(context)
    assert values["available_capital"] == 9000 and revision == 2
    assert plan["funding"]["unbooked_count"] == 0


async def test_reset_cannot_release_spent_money(context):
    capital = await create_capital(context)
    await fill(context, capital)
    with pytest.raises(biz.ValidationError):
        async with biz.business_transaction() as session:
            await biz.reset_capital(
                session,
                user_id=context[0],
                capital_plan_id=UUID(capital.result["capital_plan_id"]),
                allocated_capital="999",
                expected_revision=1,
                idempotency_key="reset",
            )


async def test_account_cannot_withdraw_reserved_cash(context):
    await create_capital(context)
    with pytest.raises(biz.ValidationError):
        async with biz.business_transaction() as session:
            await biz.update_account(
                session,
                user_id=context[0],
                account_id=context[2],
                expected_revision=1,
                declared=declared(available_capital="5999"),
                idempotency_key="withdraw",
            )


async def test_default_fallback_and_pinned_account(context):
    # A session created before selecting the default account still inherits it on allocation.
    async with biz.business_transaction() as session:
        link = (
            await session.execute(
                select(store.ResearchInvestmentLink).where(
                    store.ResearchInvestmentLink.research_id == context[1]
                )
            )
        ).scalar_one()
        link.account_id = None
    capital = await create_capital(context)
    assert capital.result["account_id"] == str(context[2])
    with pytest.raises(biz.ValidationError):
        async with biz.business_transaction() as session:
            await biz.set_research_link(
                session,
                user_id=context[0],
                research_id=context[1],
                account_id=uuid4(),
                idempotency_key="switch",
            )


async def test_currency_mismatch_rejected(context):
    with pytest.raises(biz.ValidationError):
        await create_capital(context, currency="USD")


async def test_foreign_user_cannot_change_cash(context):
    capital = await create_capital(context)
    other = await store.create_user(username="other", password_hash="x")
    with pytest.raises(biz.NotFoundOrForbiddenError):
        await fill((other.id, context[1], context[2]), capital)


async def test_http_views_expose_funding(context):
    from server.routes import business as routes

    capital = await create_capital(context)
    await fill(context, capital, fees="5")
    async with biz.business_transaction() as session:
        user = await session.get(store.User, context[0])
    account = await routes.get_account(str(context[2]), user)
    plan = await routes.get_capital_plan(str(context[1]), user)
    rows = await routes.list_buy_sell_plans(capital.result["capital_plan_id"], user, 100, 0)
    assert Decimal(account["funding"]["allocatable_capital"]) == 4000
    assert Decimal(plan["capital_plan"]["funding"]["remaining_capital"]) == 4995
    assert rows["buy_sell_plans"][0]["values"]["fees"] == "5"
    assert Decimal(rows["buy_sell_plans"][0]["cash_effect"]) == -1005


async def test_sales_surplus_is_released_to_account(context):
    capital = await create_capital(context)
    await fill(context, capital)
    await fill(context, capital, side="sell", price="12")
    values, summary, plan, _ = await balances(context)
    assert values["available_capital"] == 10200
    assert Decimal(summary["allocatable_capital"]) == 4200
    assert Decimal(plan["funding"]["remaining_capital"]) == 6000
    async with biz.business_transaction() as session:
        await biz.reset_capital(
            session,
            user_id=context[0],
            capital_plan_id=UUID(capital.result["capital_plan_id"]),
            allocated_capital="0",
            expected_revision=1,
            idempotency_key="release-all",
        )
    _, summary, _, _ = await balances(context)
    assert Decimal(summary["allocatable_capital"]) == 10200


async def test_delete_session_releases_reservation_but_keeps_cash_facts(context):
    from server import business_archive

    capital = await create_capital(context)
    await fill(context, capital)
    async with biz.business_transaction() as session:
        await business_archive.delete_research(
            session,
            user_id=context[0],
            research_id=context[1],
            idempotency_key="delete",
        )
    values, summary, _, revision = await balances(context)
    assert values["available_capital"] == 9000 and revision == 2
    assert Decimal(summary["reserved_capital"]) == 0
    assert Decimal(summary["allocatable_capital"]) == 9000
    with pytest.raises(biz.NotFoundOrForbiddenError):
        await fill(context, capital)


async def test_archiving_unbooked_legacy_record_never_refunds_cash(context):
    capital = await create_capital(context)
    async with biz.business_transaction() as session:
        legacy = store.BuySellPlan(
            capital_plan_id=UUID(capital.result["capital_plan_id"]),
            user_id=context[0],
            research_id=context[1],
            current_revision=1,
        )
        session.add(legacy)
        await session.flush()
        session.add(
            store.BuySellPlanRevision(
                buy_sell_plan_id=legacy.id,
                revision=1,
                symbol="TEST",
                side="buy",
                price=Decimal("10"),
                quantity=Decimal("100"),
                currency="CNY",
            )
        )
        legacy_id = legacy.id
    async with biz.business_transaction() as session:
        await biz.update_buy_sell_plan(
            session,
            user_id=context[0],
            buy_sell_plan_id=legacy_id,
            expected_revision=1,
            declared=declared(price="11"),
            idempotency_key="edit-legacy-price",
        )
    values, _, plan, revision = await balances(context)
    assert values["available_capital"] == 10000 and revision == 1
    assert plan["funding"]["unbooked_count"] == 1
    async with biz.business_transaction() as session:
        await biz.archive_buy_sell_plan(
            session,
            user_id=context[0],
            buy_sell_plan_id=legacy_id,
            idempotency_key="archive-legacy",
        )
    values, _, _, revision = await balances(context)
    assert values["available_capital"] == 10000 and revision == 1


async def test_stale_revision_and_changed_idempotency_payload_do_not_post(context):
    capital = await create_capital(context)
    bought = await fill(context, capital, key="buy")
    with pytest.raises(biz.IdempotencyReuseError):
        await fill(context, capital, key="buy", price="11")
    with pytest.raises(biz.RevisionConflictError):
        async with biz.business_transaction() as session:
            await biz.update_buy_sell_plan(
                session,
                user_id=context[0],
                buy_sell_plan_id=UUID(bought.result["buy_sell_plan_id"]),
                declared=declared(price="11"),
                expected_revision=0,
                idempotency_key="stale",
            )
    values, _, _, revision = await balances(context)
    assert values["available_capital"] == 9000 and revision == 2
