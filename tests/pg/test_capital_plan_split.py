"""规划资金（会话 1:1）与买卖计划（规划资金 1:N）拆分验收（2026-10-26）。

覆盖：

* 会话 ↔ 规划资金一对一：同一会话第二次创建被拒绝，不产生第二条；
* 规划资金累加：多次 ``allocations`` 在现值上相加，不互相覆盖；
* 规划资金重置：显式重设为指定总额，历史版本仍按 ``op_type`` 可追溯；
* 买卖计划与规划资金一对多：同一规划资金可登记多笔实际买卖价格；
* 买卖计划登记必须落在既有规划资金下，缺失所属对象按 ``not_found`` 处理；
* Run 准入门禁：计划版本不再携带 ``allocated_capital`` 时，会话规划资金注入计划组，
  ``plan_analysis`` 用途不再因规划资金缺失被拒，且解析值来源标注 ``capital_plan``。
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from server import business_service as biz
from server import investment_snapshot as snapshots
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


async def _analysis_context(name: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """绑定账户+计划的完整分析上下文：计划版本不带 ``allocated_capital``。"""
    async with biz.business_transaction() as session:
        user_id = await _new_user(session, name)
        research_id = await _new_research(session, user_id)
    async with biz.business_transaction() as session:
        account = await biz.create_account(
            session,
            user_id=user_id,
            name=f"主账户-{name}",
            base_currency="CNY",
            declared={
                "total_capital": {"value": "100000"},
                "available_capital": {"value": "60000"},
                "capital_basis": {"value": "total"},
                "currency": {"value": "CNY"},
                "as_of": {"value": "2026-10-26T00:00:00Z"},
            },
            idempotency_key=f"{name}-acc",
        )
        plan = await biz.create_plan(
            session,
            user_id=user_id,
            research_id=research_id,
            name="计划",
            declared={
                "symbol": {"value": "600519.SH"},
                "market": {"value": "CN"},
                "direction": {"value": "buy"},
                "currency": {"value": "CNY"},
            },
            idempotency_key=f"{name}-plan",
        )
        account_id = uuid.UUID(account.result["account_id"])
        plan_id = uuid.UUID(plan.result["plan_id"])
        link = (
            await session.execute(
                select(store.ResearchInvestmentLink).where(
                    store.ResearchInvestmentLink.research_id == research_id
                )
            )
        ).scalar_one_or_none()
        if link is None:
            link = store.ResearchInvestmentLink(
                research_id=research_id, user_id=user_id, account_id=account_id
            )
            session.add(link)
        link.primary_plan_id = plan_id
    return user_id, research_id, account_id, plan_id


async def test_run_gate_accepts_capital_plan_without_plan_allocated_capital() -> None:
    """计划版本缺 allocated_capital 时，会话规划资金补齐门禁并注入解析值。"""
    user_id, research_id, account_id, plan_id = await _analysis_context("cp-gate")
    await _create_capital(user_id, research_id, "20000", "cp-gate-capital")

    spec = snapshots.InvestmentInputSpec(
        use_case="plan_analysis",
        account=snapshots.ObjectRef(account_id, 1),
        plan=snapshots.ObjectRef(plan_id, 1),
    )
    async with biz.business_transaction() as session:
        resolution = await snapshots.resolve_for_run(
            session, user_id=user_id, research_id=research_id, spec=spec
        )
    assert resolution.missing == {}, resolution.missing
    entry = resolution.values["plan.allocated_capital"]
    assert Decimal(entry["value"]) == Decimal("20000")
    assert entry["source"]["kind"] == "capital_plan"
    assert entry["currency"] == "CNY"


async def test_run_gate_still_fails_without_capital_plan() -> None:
    """没有会话规划资金时，门禁维持原样报缺 ``plan.allocated_capital``。"""
    user_id, research_id, account_id, plan_id = await _analysis_context("cp-gate-none")
    spec = snapshots.InvestmentInputSpec(
        use_case="plan_analysis",
        account=snapshots.ObjectRef(account_id, 1),
        plan=snapshots.ObjectRef(plan_id, 1),
    )
    with pytest.raises(biz.PurposeRequirementError) as err:
        async with biz.business_transaction() as session:
            await snapshots.resolve_for_run(
                session, user_id=user_id, research_id=research_id, spec=spec
            )
    assert "plan.allocated_capital" in err.value.fields


async def _unbind_primary_plan(user_id: uuid.UUID, research_id: uuid.UUID) -> None:
    async with biz.business_transaction() as session:
        link = (
            await session.execute(
                select(store.ResearchInvestmentLink).where(
                    store.ResearchInvestmentLink.research_id == research_id
                )
            )
        ).scalar_one()
        link.primary_plan_id = None


async def test_auto_analysis_spec_derives_plan_from_capital_plan() -> None:
    """无主计划时，监控自动分析以规划资金 + 最新有效买卖价格构造解析输入。"""
    from types import SimpleNamespace

    from server import watch_scheduler

    user_id, research_id, _account_id, _plan_id = await _analysis_context("cp-autospec")
    await _create_capital(user_id, research_id, "20000", "cp-autospec-capital")
    async with biz.business_transaction() as session:
        capital = (
            await session.execute(
                select(store.CapitalPlan).where(store.CapitalPlan.research_id == research_id)
            )
        ).scalar_one()
        await biz.create_buy_sell_plan(
            session,
            user_id=user_id,
            capital_plan_id=capital.id,
            declared={
                "symbol": {"value": "601138.SH"},
                "market": {"value": "CN"},
                "side": {"value": "buy"},
                "price": {"value": "47.25"},
                "currency": {"value": "CNY"},
            },
            idempotency_key="cp-autospec-bs",
        )
    await _unbind_primary_plan(user_id, research_id)

    event = SimpleNamespace(id=uuid.uuid4(), generation=1, research_id=research_id, user_id=user_id)
    async with biz.business_transaction() as session:
        link = (
            await session.execute(
                select(store.ResearchInvestmentLink).where(
                    store.ResearchInvestmentLink.research_id == research_id
                )
            )
        ).scalar_one()
        spec, failure = await watch_scheduler._auto_analysis_spec(session, event=event, link=link)
    assert failure is None
    assert spec is not None and spec.plan is None
    async with biz.business_transaction() as session:
        resolution = await snapshots.resolve_for_run(
            session, user_id=user_id, research_id=research_id, spec=spec
        )
    assert resolution.missing == {}, resolution.missing
    assert resolution.values["plan.symbol"]["value"] == "601138.SH"
    assert resolution.values["plan.direction"]["value"] == "buy"
    assert Decimal(resolution.values["plan.allocated_capital"]["value"]) == Decimal("20000")
    assert resolution.values["plan.allocated_capital"]["source"]["kind"] == "capital_plan"


async def test_auto_analysis_spec_requires_capital_plan_when_unbound() -> None:
    """未绑定主计划且没有规划资金 → 拒绝并返回 research_binding_missing。"""
    from types import SimpleNamespace

    from server import watch_scheduler

    user_id, research_id, _account_id, _plan_id = await _analysis_context("cp-autospec-none")
    await _unbind_primary_plan(user_id, research_id)
    event = SimpleNamespace(id=uuid.uuid4(), generation=1, research_id=research_id, user_id=user_id)
    async with biz.business_transaction() as session:
        link = (
            await session.execute(
                select(store.ResearchInvestmentLink).where(
                    store.ResearchInvestmentLink.research_id == research_id
                )
            )
        ).scalar_one()
        spec, failure = await watch_scheduler._auto_analysis_spec(session, event=event, link=link)
    assert spec is None
    assert failure == "research_binding_missing"


async def test_input_request_spec_uses_capital_plan_when_primary_plan_missing() -> None:
    """补数弹窗路径：无主计划时以规划资金 + 买卖价格构造 spec，回答持久化后门禁仍通过。"""
    from dataclasses import replace

    from server import input_requests

    user_id, research_id, _account_id, _plan_id = await _analysis_context("cp-irq-spec")
    await _create_capital(user_id, research_id, "20000", "cp-irq-capital")
    async with biz.business_transaction() as session:
        capital = (
            await session.execute(
                select(store.CapitalPlan).where(store.CapitalPlan.research_id == research_id)
            )
        ).scalar_one()
        await biz.create_buy_sell_plan(
            session,
            user_id=user_id,
            capital_plan_id=capital.id,
            declared={
                "symbol": {"value": "601138.SH"},
                "market": {"value": "CN"},
                "side": {"value": "buy"},
                "price": {"value": "47.25"},
                "currency": {"value": "CNY"},
            },
            idempotency_key="cp-irq-bs",
        )
    await _unbind_primary_plan(user_id, research_id)

    async with biz.business_transaction() as session:
        spec = await input_requests._spec_from_research_link(
            session, user_id=user_id, research_id=research_id, use_case="plan_analysis"
        )
    assert spec.plan is None
    assert spec.account is not None
    assert spec.declared["plan"]["symbol"]["value"] == "601138.SH"

    # 模拟回答路径：账户字段持久化；无引用的 plan declared 不报错、原样保留。
    async with biz.business_transaction() as session:
        saved_spec, saved = await snapshots.persist_declared(
            session,
            user_id=user_id,
            research_id=research_id,
            spec=replace(
                spec,
                declared={
                    **spec.declared,
                    "account": {"as_of": {"value": "2026-10-27T00:00:00Z"}},
                },
            ),
        )
    assert "account" in saved
    assert set(saved_spec.declared) == {"plan"}

    async with biz.business_transaction() as session:
        resolution = await snapshots.resolve_for_run(
            session, user_id=user_id, research_id=research_id, spec=saved_spec
        )
    assert resolution.missing == {}, resolution.missing
    assert resolution.values["plan.symbol"]["value"] == "601138.SH"
    assert Decimal(resolution.values["plan.allocated_capital"]["value"]) == Decimal("20000")
    assert resolution.values["plan.allocated_capital"]["source"]["kind"] == "capital_plan"


async def test_context_carries_active_buy_sell_prices_only() -> None:
    """快照上下文携带未归档实际买卖价格列表；软删除（归档）被过滤。"""
    user_id, research_id, _account_id, _plan_id = await _analysis_context("cp-bsctx")
    await _create_capital(user_id, research_id, "20000", "cp-bsctx-capital")
    async with biz.business_transaction() as session:
        capital = (
            await session.execute(
                select(store.CapitalPlan).where(store.CapitalPlan.research_id == research_id)
            )
        ).scalar_one()
        first = await biz.create_buy_sell_plan(
            session,
            user_id=user_id,
            capital_plan_id=capital.id,
            declared={
                "symbol": {"value": "601138.SH"},
                "market": {"value": "CN"},
                "side": {"value": "buy"},
                "price": {"value": "46.75"},
                "quantity": {"value": "100"},
                "currency": {"value": "CNY"},
            },
            idempotency_key="cp-bsctx-1",
        )
        await biz.create_buy_sell_plan(
            session,
            user_id=user_id,
            capital_plan_id=capital.id,
            declared={
                "symbol": {"value": "601138.SH"},
                "market": {"value": "CN"},
                "side": {"value": "buy"},
                "price": {"value": "48.12"},
                "currency": {"value": "CNY"},
            },
            idempotency_key="cp-bsctx-2",
        )
        archived = await biz.archive_buy_sell_plan(
            session,
            user_id=user_id,
            buy_sell_plan_id=first.result["buy_sell_plan_id"],
            idempotency_key="cp-bsctx-arch",
        )
        assert archived.result["archived"] is True

    spec = snapshots.InvestmentInputSpec(
        use_case="plan_analysis",
        account=snapshots.ObjectRef(_account_id, 1),
        plan=snapshots.ObjectRef(_plan_id, 1),
    )
    async with biz.business_transaction() as session:
        resolution = await snapshots.resolve_for_run(
            session, user_id=user_id, research_id=research_id, spec=spec
        )
    assert Decimal(resolution.values["buy_sell.count"]["value"]) == 1
    # 最新有效记录在前；被归档的 46.75 不得出现。
    assert Decimal(resolution.values["buy_sell.1.price"]["value"]) == Decimal("48.12")
    assert resolution.values["buy_sell.1.side"]["value"] == "buy"
    assert resolution.values["buy_sell.1.price"]["source"]["kind"] == "buy_sell_revision"
    assert all(not key.startswith("buy_sell.2.") for key in resolution.values)
