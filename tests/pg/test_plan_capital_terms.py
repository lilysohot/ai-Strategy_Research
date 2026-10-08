"""DATA-02/03 会话计划口径定向验收（2026-10-08）。

覆盖 PRD v0.7 §3.2/§4.2 与契约 v0.2 §4/§5 的服务端部分：

* 规划资金不得超过所属账户可用资金（新建与修改），超额不产生半个写入；
* 账户无可用资金时上限退化为总资金；研究未绑定账户时不阻断保存；
* 计划价字段取消：提交即 ``unknown_field_rejected``；
* 期望盈利数值必须带单位；
* 读接口不再输出废弃价格列，输出 ``allocated_capital`` 与 ``target_profit`` 分组。
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from server import business_service as biz
from server import store
from server.routes import business as business_routes

pytestmark = pytest.mark.pg

CAPITAL = {
    "total_capital": "100000",
    "available_capital": "60000",
    "capital_basis": "total",
    "as_of": "2026-10-02T00:00:00Z",
}
PLAN = {
    "symbol": "600519.SH",
    "market": "CN",
    "direction": "buy",
    "allocated_capital": "10000",
    "currency": "CNY",
}


async def _new_user(session, name: str) -> uuid.UUID:
    user_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO users (id, username, password_hash, status) "
            "VALUES (:id, :name, 'x', 'active')"
        ),
        {"id": user_id, "name": name},
    )
    return user_id


async def _new_research(session, user_id: uuid.UUID) -> uuid.UUID:
    research_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO sessions (id, user_id, title) VALUES (:id, :uid, '研究')"),
        {"id": research_id, "uid": user_id, "title": "研究"},
    )
    return research_id


async def _bind_account(user_id: uuid.UUID, research_id: uuid.UUID, account_id: str) -> None:
    async with biz.business_transaction() as session:
        session.add(
            store.ResearchInvestmentLink(
                research_id=research_id, user_id=user_id, account_id=uuid.UUID(account_id)
            )
        )


async def _create_account(user_id: uuid.UUID, key: str, declared=None) -> dict:
    async with biz.business_transaction() as session:
        outcome = await biz.create_account(
            session,
            user_id=user_id,
            name="主账户",
            base_currency="CNY",
            declared=dict(declared or CAPITAL),
            idempotency_key=key,
        )
    return outcome.result


async def _create_plan(user_id: uuid.UUID, research_id: uuid.UUID, key: str, declared=None) -> dict:
    async with biz.business_transaction() as session:
        outcome = await biz.create_plan(
            session,
            user_id=user_id,
            research_id=research_id,
            name="计划",
            declared=dict(declared or PLAN),
            idempotency_key=key,
        )
    return outcome.result


async def _case(name: str, capital=None) -> tuple[uuid.UUID, uuid.UUID]:
    async with biz.business_transaction() as session:
        user_id = await _new_user(session, name)
        research_id = await _new_research(session, user_id)
    account = await _create_account(user_id, f"{name}-acc", capital)
    await _bind_account(user_id, research_id, account["account_id"])
    return user_id, research_id


async def test_allocation_above_available_is_rejected() -> None:
    """超出可用资金 → 字段级校验错误，且不产生半个写入。"""
    user_id, research_id = await _case("sp-over")
    with pytest.raises(biz.ValidationError) as err:
        await _create_plan(
            user_id, research_id, "sp-over-plan", {**PLAN, "allocated_capital": "70000"}
        )
    assert err.value.code == "validation_error"
    assert "allocated_capital" in err.value.fields
    async with biz.business_transaction() as session:
        count = (
            await session.execute(
                select(func.count())
                .select_from(store.InvestmentPlan)
                .where(store.InvestmentPlan.research_id == research_id)
            )
        ).scalar_one()
    assert count == 0, "超额请求不应留下半个写入"


async def test_allocation_equal_to_available_is_accepted() -> None:
    """恰好等于可用资金 → 通过并逐位保存。"""
    user_id, research_id = await _case("sp-equal")
    plan = await _create_plan(
        user_id, research_id, "sp-equal-plan", {**PLAN, "allocated_capital": "60000"}
    )
    async with biz.business_transaction() as session:
        row = (
            await session.execute(
                select(store.InvestmentPlanRevision).where(
                    store.InvestmentPlanRevision.plan_id == uuid.UUID(plan["plan_id"])
                )
            )
        ).scalar_one()
    assert row.allocated_capital == Decimal("60000")


async def test_allocation_falls_back_to_total_capital() -> None:
    """账户只有总资金时，上限退化为总资金（登记于 spec）。"""
    user_id, research_id = await _case(
        "sp-total",
        {"total_capital": "100000", "capital_basis": "total", "as_of": "2026-10-02T00:00:00Z"},
    )
    ok = await _create_plan(
        user_id, research_id, "sp-total-ok", {**PLAN, "allocated_capital": "90000"}
    )
    assert ok["plan_id"]
    with pytest.raises(biz.ValidationError):
        await _create_plan(
            user_id, research_id, "sp-total-bad", {**PLAN, "allocated_capital": "110000"}
        )


async def test_allocation_unchecked_without_account_link() -> None:
    """研究未绑定账户：写入侧不阻断（依赖该项的分析另行缺数阻断）。"""
    async with biz.business_transaction() as session:
        user_id = await _new_user(session, "sp-nolink")
        research_id = await _new_research(session, user_id)
    plan = await _create_plan(
        user_id, research_id, "sp-nolink-plan", {**PLAN, "allocated_capital": "999999"}
    )
    assert plan["plan_id"]


async def test_update_plan_checks_allocation() -> None:
    """修改计划同样受上限约束。"""
    user_id, research_id = await _case("sp-update")
    plan = await _create_plan(user_id, research_id, "sp-update-plan")
    with pytest.raises(biz.ValidationError):
        async with biz.business_transaction() as session:
            await biz.update_plan(
                session,
                user_id=user_id,
                plan_id=uuid.UUID(plan["plan_id"]),
                expected_revision=1,
                declared={"allocated_capital": "70000"},
                idempotency_key="sp-update-bad",
            )


async def test_plan_price_fields_are_rejected() -> None:
    """计划价字段已取消：提交即 unknown_field_rejected。"""
    user_id, research_id = await _case("sp-noprice")
    with pytest.raises(biz.UnknownFieldError) as err:
        await _create_plan(user_id, research_id, "sp-noprice-plan", {**PLAN, "plan_price": "19.90"})
    assert err.value.code == "unknown_field_rejected"
    assert "plan_price" in err.value.fields


async def test_target_profit_requires_unit() -> None:
    """期望盈利是金额/比例口径：缺单位不能区分。"""
    user_id, research_id = await _case("sp-profit")
    with pytest.raises(biz.ValidationError) as err:
        await _create_plan(
            user_id, research_id, "sp-profit-bad", {**PLAN, "target_profit_value": "20"}
        )
    assert err.value.fields
    ok = await _create_plan(
        user_id,
        research_id,
        "sp-profit-ok",
        {**PLAN, "target_profit_value": "20", "target_profit_unit": "percent"},
    )
    assert ok["plan_id"]


def test_plan_view_hides_deprecated_price_fields() -> None:
    """读接口不再输出废弃价格列，输出规划资金与期望盈利分组。"""

    class Row:
        symbol = "600519.SH"
        market = "CN"
        asset_type = None
        direction = "buy"
        target_price = None
        allocated_capital = None
        risk_budget_value = None
        risk_budget_unit = None
        position_limit_value = None
        position_limit_unit = None
        time_window = None
        invalidation = None
        profit_loss_ratio = None
        profit_loss_ratio_definition = None
        target_profit_value = None
        target_profit_unit = None
        currency = "CNY"
        as_of = None
        record_state = "submitted"

    view = business_routes._plan_values(Row())
    assert "allocated_capital" in view
    assert view["target_profit"] == {"value": None, "unit": None}
    for deprecated in ("plan_price", "plan_price_low", "plan_price_high"):
        assert deprecated not in view


def test_plan_analysis_requires_allocated_capital() -> None:
    """准入改为要求规划资金，不再要求计划价或目标价。"""
    admission = biz.admit_group(
        "plan", {"symbol": "600519.SH", "market": "CN", "direction": "buy"}
    )
    missing = biz.evaluate_purpose("plan_analysis", {"plan": admission})
    assert "plan.allocated_capital" in missing
    assert "plan.plan_price" not in missing
    assert "plan.target_price" not in missing
