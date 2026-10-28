"""Business-source regressions using the isolated SQLite test database."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from server import business_service as biz
from server import investment_snapshot as snapshots
from server import store


@pytest.fixture
async def business_rows():
    await store.init_db()
    user_id, research_id, plan_id, capital_id, account_id = [uuid.uuid4() for _ in range(5)]
    async with store.get_sessionmaker()() as session:
        session.add(store.User(id=user_id, username=str(user_id), password_hash="x"))
        await session.flush()
        session.add(store.Session(id=research_id, user_id=user_id, title="research"))
        session.add(
            store.InvestmentAccount(
                id=account_id,
                user_id=user_id,
                name="account",
                base_currency="CNY",
                current_revision=1,
            )
        )
        await session.flush()
        session.add(
            store.InvestmentAccountRevision(
                account_id=account_id,
                revision=1,
                total_capital=Decimal("200000"),
                available_capital=Decimal("200000"),
                capital_basis="tradable_assets",
                currency="CNY",
                as_of=datetime.now(UTC),
            )
        )
        session.add(
            store.InvestmentPlan(
                id=plan_id,
                research_id=research_id,
                user_id=user_id,
                name="retired",
                current_revision=1,
            )
        )
        session.add(
            store.CapitalPlan(
                id=capital_id,
                research_id=research_id,
                user_id=user_id,
                account_id=account_id,
                allocated_capital=Decimal("30000"),
                currency="CNY",
                current_revision=1,
            )
        )
        await session.flush()
        session.add(
            store.InvestmentPlanRevision(
                plan_id=plan_id,
                revision=1,
                symbol="OLD",
                market="CN",
                direction="buy",
                allocated_capital=Decimal("10000"),
                currency="CNY",
            )
        )
        await session.commit()
    return SimpleNamespace(
        user_id=user_id,
        research_id=research_id,
        plan_id=plan_id,
        capital_id=capital_id,
        account_id=account_id,
    )


@pytest.mark.parametrize("declared", [{}, {"plan": {"allocated_capital": {"value": "15000"}}}])
async def test_session_capital_wins_over_retired_plan_and_declared_amount(business_rows, declared):
    row = business_rows
    async with store.get_sessionmaker()() as session:
        result = await snapshots.resolve_for_run(
            session,
            user_id=row.user_id,
            research_id=row.research_id,
            spec=snapshots.InvestmentInputSpec(
                plan=snapshots.ObjectRef(row.plan_id),
                declared=declared,
            ),
        )
    value = result.values["plan.allocated_capital"]
    assert Decimal(value["value"]) == Decimal("30000")
    assert value["source"]["kind"] == "capital_plan"
    assert result.values["capital.allocated_capital"] == value


async def test_ordinary_run_gets_capital_without_a_retired_plan(business_rows):
    row = business_rows
    async with store.get_sessionmaker()() as session:
        result = await snapshots.resolve_for_run(
            session,
            user_id=row.user_id,
            research_id=row.research_id,
            spec=snapshots.InvestmentInputSpec(use_case="unspecified"),
        )
    assert result.values["capital.allocated_capital"]["value"] == "30000.0000000000"
    assert result.values["plan.allocated_capital"]["source"]["kind"] == "capital_plan"


async def test_trade_window_reports_truncation_and_accurate_provenance(business_rows):
    row = business_rows
    async with store.get_sessionmaker()() as session:
        for _ in range(11):
            trade = store.BuySellPlan(
                capital_plan_id=row.capital_id,
                research_id=row.research_id,
                user_id=row.user_id,
                current_revision=1,
            )
            session.add(trade)
            await session.flush()
            session.add(
                store.BuySellPlanRevision(
                    buy_sell_plan_id=trade.id,
                    revision=1,
                    symbol="601138",
                    market="CN",
                    side="buy",
                    price=Decimal("47"),
                    quantity=Decimal("100"),
                    currency="CNY",
                )
            )
        await session.commit()
        result = await snapshots.resolve_for_run(
            session,
            user_id=row.user_id,
            research_id=row.research_id,
            spec=snapshots.InvestmentInputSpec(),
        )
    assert result.values["buy_sell.count"]["value"] == "10"
    assert result.values["buy_sell.total_count"]["value"] == "11"
    assert result.values["buy_sell.truncated"]["value"] == "true"
    assert result.values["buy_sell.1.price"]["source"]["kind"] == "buy_sell_revision"


async def test_new_runs_read_increases_and_resets_without_rewriting_previous_values(business_rows):
    row = business_rows
    spec = snapshots.InvestmentInputSpec(
        account=snapshots.ObjectRef(row.account_id),
        plan=snapshots.ObjectRef(row.plan_id),
    )
    async with store.get_sessionmaker()() as session:
        first = await snapshots.resolve_for_run(
            session,
            user_id=row.user_id,
            research_id=row.research_id,
            spec=spec,
        )
        await session.commit()
    async with store.get_sessionmaker()() as session:
        await biz.allocate_capital(
            session,
            user_id=row.user_id,
            capital_plan_id=row.capital_id,
            allocation_delta="5000",
            expected_revision=1,
            idempotency_key="increase",
        )
        await session.commit()
    async with store.get_sessionmaker()() as session:
        second = await snapshots.resolve_for_run(
            session,
            user_id=row.user_id,
            research_id=row.research_id,
            spec=spec,
        )
        await session.commit()
    async with store.get_sessionmaker()() as session:
        await biz.reset_capital(
            session,
            user_id=row.user_id,
            capital_plan_id=row.capital_id,
            allocated_capital="12000",
            expected_revision=2,
            idempotency_key="reset",
        )
        await session.commit()
    async with store.get_sessionmaker()() as session:
        third = await snapshots.resolve_for_run(
            session,
            user_id=row.user_id,
            research_id=row.research_id,
            spec=spec,
        )
        retired = await session.get(store.InvestmentPlan, row.plan_id)
        assert retired.current_revision == 1
    for result, amount, revision in [
        (first, "30000", 1),
        (second, "35000", 2),
        (third, "12000", 3),
    ]:
        entry = result.values["capital.allocated_capital"]
        assert Decimal(entry["value"]) == Decimal(amount)
        assert entry["source"]["revision"] == revision
        assert Decimal(result.values["account.available_capital"]["value"]) == Decimal("200000")
        assert result.values["account.available_capital"]["source"]["revision"] == 1


async def test_current_inputs_ignore_retired_link_and_watch_selects_its_symbol(business_rows):
    from server import watch_scheduler

    row = business_rows
    async with store.get_sessionmaker()() as session:
        for index, symbol in enumerate(["601138", "600519.SH"]):
            trade = store.BuySellPlan(
                capital_plan_id=row.capital_id,
                research_id=row.research_id,
                user_id=row.user_id,
                current_revision=1,
            )
            session.add(trade)
            await session.flush()
            session.add(
                store.BuySellPlanRevision(
                    buy_sell_plan_id=trade.id,
                    revision=1,
                    symbol=symbol,
                    market="CN",
                    side="buy",
                    price=Decimal("47"),
                    quantity=Decimal("100"),
                    currency="CNY",
                    traded_at=datetime(2026, 10, 27, tzinfo=UTC) + timedelta(hours=index),
                )
            )
        await session.flush()
        link = SimpleNamespace(
            user_id=row.user_id,
            research_id=row.research_id,
            primary_plan_id=row.plan_id,
            account_id=row.account_id,
        )
        ordinary = await snapshots.current_research_input(
            session, link=link, use_case="unspecified"
        )
        assert ordinary.plan is None
        assert ordinary.declared["plan"]["symbol"]["value"] == "600519.SH"
        event = SimpleNamespace(
            id=uuid.uuid4(),
            generation=1,
            user_id=row.user_id,
            research_id=row.research_id,
            symbol="601138.SH",
        )
        watch, failure = await watch_scheduler._auto_analysis_spec(session, event=event, link=link)
        assert failure is None and watch.plan is None
        assert watch.declared["plan"]["symbol"]["value"] == "601138"
        mismatch = await snapshots.current_research_input(
            session,
            link=link,
            use_case="unspecified",
            symbol="600519.SZ",
        )
        assert mismatch.plan is None and mismatch.declared == {}


async def test_incomplete_current_capital_cannot_revive_retired_amount(business_rows):
    row = business_rows
    async with store.get_sessionmaker()() as session:
        capital = await session.get(store.CapitalPlan, row.capital_id)
        capital.record_state = "incomplete"
        capital.allocated_capital = None
        await session.flush()
        result = await snapshots.resolve_for_run(
            session,
            user_id=row.user_id,
            research_id=row.research_id,
            spec=snapshots.InvestmentInputSpec(plan=snapshots.ObjectRef(row.plan_id)),
        )
    assert result.values["capital.allocated_capital"]["status"] == "missing"
    assert result.values["capital.allocated_capital"]["value"] is None
    assert "plan.allocated_capital" not in result.values


async def test_run_entry_freezes_latest_allocation_once_and_continuations_use_current_model(
    business_rows,
    tmp_path,
):
    from server import input_requests

    row = business_rows
    first_id, second_id = uuid.uuid4(), uuid.uuid4()
    async with store.get_sessionmaker()() as session:
        session.add(
            store.ResearchInvestmentLink(
                research_id=row.research_id,
                user_id=row.user_id,
                account_id=row.account_id,
                primary_plan_id=row.plan_id,
            )
        )
        for run_id in (first_id, second_id):
            session.add(
                store.Run(
                    id=run_id,
                    session_id=row.research_id,
                    user_id=row.user_id,
                    status="queued",
                    pipeline_id="stateful-react-agent",
                    prompt="research",
                    run_dir=str(tmp_path / run_id.hex),
                )
            )
        trade = store.BuySellPlan(
            capital_plan_id=row.capital_id,
            research_id=row.research_id,
            user_id=row.user_id,
            current_revision=1,
        )
        session.add(trade)
        await session.flush()
        session.add(
            store.BuySellPlanRevision(
                buy_sell_plan_id=trade.id,
                revision=1,
                symbol="601138",
                market="CN",
                side="buy",
                price=Decimal("47"),
                currency="CNY",
            )
        )
        await session.commit()
    assert await snapshots.ensure_research_bound_snapshot(run_id=first_id, user_id=row.user_id)
    async with store.get_sessionmaker()() as session:
        await biz.reset_capital(
            session,
            user_id=row.user_id,
            capital_plan_id=row.capital_id,
            allocated_capital="12000",
            expected_revision=1,
            idempotency_key="reset-between-runs",
        )
        await session.commit()
    assert not await snapshots.ensure_research_bound_snapshot(run_id=first_id, user_id=row.user_id)
    assert await snapshots.ensure_research_bound_snapshot(run_id=second_id, user_id=row.user_id)
    async with store.get_sessionmaker()() as session:
        for run_id, amount in ((first_id, "30000"), (second_id, "12000")):
            frozen = await snapshots.get_snapshot(session, user_id=row.user_id, run_id=run_id)
            assert frozen.plan_id is None
            assert frozen.resolved_json["plan.symbol"]["value"] == "601138"
            assert Decimal(frozen.resolved_json["capital.allocated_capital"]["value"]) == Decimal(
                amount
            )
        spec = await input_requests._spec_from_research_link(
            session,
            user_id=row.user_id,
            research_id=row.research_id,
            use_case="plan_analysis",
        )
        assert spec.plan is None and spec.account.expected_revision == 1
        assert spec.declared["plan"]["symbol"]["value"] == "601138"


async def test_new_session_without_allocation_has_canonical_missing_and_consistent_gate(business_rows):
    import json

    from plugins.tools.investment_context import (
        _investment_position_sizing,
        bind_investment_context,
        reset_investment_context,
    )
    row = business_rows
    async with store.get_sessionmaker()() as session:
        await session.delete(await session.get(store.CapitalPlan, row.capital_id))
        await session.commit()
        spec = snapshots.InvestmentInputSpec(account=snapshots.ObjectRef(row.account_id))
        result = await snapshots.resolve_for_run(
            session, user_id=row.user_id, research_id=row.research_id, spec=spec,
        )
        assert result.values["capital.allocated_capital"]["status"] == "missing"
        from dataclasses import replace
        with pytest.raises(biz.PurposeRequirementError) as exc:
            await snapshots.resolve_for_run(
                session, user_id=row.user_id, research_id=row.research_id,
                spec=replace(spec, use_case="plan_analysis"),
            )
        assert set(exc.value.fields) == {"plan.allocated_capital"}
    tokens = bind_investment_context({"values": result.values})
    try:
        sizing = json.loads(await _investment_position_sizing(43, entry_low=46, entry_high=49))
        assert sizing["missing"] == ["plan.allocated_capital"]
    finally:
        reset_investment_context(tokens)


async def test_allocation_without_trades_allows_analysis_and_preserves_account(business_rows):
    import json

    from plugins.tools.investment_context import (
        _investment_position_sizing,
        bind_investment_context,
        reset_investment_context,
    )
    row = business_rows
    async with store.get_sessionmaker()() as session:
        result = await snapshots.resolve_for_run(
            session, user_id=row.user_id, research_id=row.research_id,
            spec=snapshots.InvestmentInputSpec(
                account=snapshots.ObjectRef(row.account_id), use_case="plan_analysis",
            ),
        )
    tokens = bind_investment_context({"values": result.values})
    try:
        sizing = json.loads(await _investment_position_sizing(43, entry_low=46, entry_high=49))
        assert sizing["ok"] is True
        assert sizing["risk_validated"] is False
        assert sizing["additional_buying_capacity"] is None
        from plugins.tools.investment_input_request import (
            bind_input_intent,
            pending_input_intent,
            request_investment_input,
            reset_input_intent,
        )
        intent_token = bind_input_intent()
        try:
            verdict = await request_investment_input.func("plan_analysis", "检查资料")
            assert "无需创建补数请求" in verdict
            assert pending_input_intent() is None
        finally:
            reset_input_intent(intent_token)
        assert result.values["account.available_capital"]["value"] == "200000.0000000000"
    finally:
        reset_investment_context(tokens)


@pytest.mark.parametrize("existing_capital", [False, True])
async def test_new_session_input_answer_persists_allocation_and_queues_followup(
    business_rows, tmp_path, existing_capital,
):
    import json

    from sqlalchemy import select

    from server import input_requests
    row = business_rows
    run_id = uuid.uuid4()
    async with store.get_sessionmaker()() as session:
        current = await session.get(store.CapitalPlan, row.capital_id)
        if existing_capital:
            current.allocated_capital = None
            current.record_state = "incomplete"
        else:
            await session.delete(current)
        session.add(store.ResearchInvestmentLink(
            research_id=row.research_id, user_id=row.user_id, account_id=row.account_id,
            primary_plan_id=row.plan_id if existing_capital else None,
        ))
        session.add(store.Run(
            id=run_id, session_id=row.research_id, user_id=row.user_id, status="running",
            pipeline_id="stateful-react-agent", prompt="研究工业富联", run_dir=str(tmp_path),
        ))
        await session.commit()
    assert await snapshots.ensure_research_bound_snapshot(run_id=run_id, user_id=row.user_id)
    (tmp_path / "input-request.json").write_text(json.dumps({
        "schema_version": "input-request/1", "use_case": "plan_analysis", "reason": "缺规划资金",
    }))
    async with biz.business_transaction() as session:
        created = await input_requests.materialize_worker_intent(session, run_id=run_id)
        request = await session.get(store.InputRequest, uuid.UUID(created["request_id"]))
        assert {x["name"] for x in request.fields_json} == {"plan.allocated_capital"}
        answer = await input_requests.answer_request(
            session, user_id=row.user_id, request_id=request.id, answer_text="分配30000",
            declared={"plan": {"allocated_capital": {"value": "30000"}}},
            expected_versions={"account": 1}, idempotency_key="new-session-answer",
        )
        capital = await session.scalar(select(store.CapitalPlan).where(
            store.CapitalPlan.research_id == row.research_id,
        ))
        assert capital is not None and capital.allocated_capital == Decimal("30000")
        followup = await snapshots.get_snapshot(
            session, user_id=row.user_id, run_id=uuid.UUID(answer.result["follow_up_run_id"]),
        )
        assert followup.plan_id is None
        assert followup.resolved_json["capital.allocated_capital"]["value"].startswith("30000")
        assert followup.resolved_json["account.available_capital"]["value"].startswith("200000")
