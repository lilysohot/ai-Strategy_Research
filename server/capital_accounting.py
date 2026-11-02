"""Account cash and session reservations, committed with the originating business write.

Lock order: account, capital plan, buy/sell row (if any). All cross-session
checks run under the account lock. Budgets reserve cash; fills spend that
reservation, so buying never deducts the same money twice.
"""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server import store

ZERO = Decimal(0)


def decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def money_sum(*amounts: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 70
        return sum(amounts, ZERO)


def remaining_capital(allocated: Decimal, net_cash_flow: Decimal) -> Decimal:
    # Sales replenish the budget; surplus proceeds are available to the account.
    return money_sum(allocated, min(net_cash_flow, ZERO))


async def cash_effect(session: AsyncSession, capital_id: Any) -> Decimal:
    value = (
        await session.execute(
            select(func.coalesce(func.sum(store.BuySellPlan.cash_effect), 0)).where(
                store.BuySellPlan.capital_plan_id == capital_id
            )
        )
    ).scalar_one()
    return value if value is not None else ZERO


async def binding_locked(session: AsyncSession, capital_id: Any) -> bool:
    return bool(
        await session.scalar(
            select(store.BuySellPlan.id)
            .where(
                store.BuySellPlan.capital_plan_id == capital_id,
                store.BuySellPlan.cash_effect.is_not(None),
            )
            .limit(1)
        )
    )


async def reservations(session: AsyncSession, account_id: Any, *, excluding: Any = None) -> Decimal:
    effects = (
        select(
            store.BuySellPlan.capital_plan_id,
            func.sum(store.BuySellPlan.cash_effect).label("net"),
        )
        .group_by(store.BuySellPlan.capital_plan_id)
        .subquery()
    )
    plans = (
        await session.execute(
            select(store.CapitalPlan.id, store.CapitalPlan.allocated_capital, effects.c.net)
            .outerjoin(effects, effects.c.capital_plan_id == store.CapitalPlan.id)
            .join(store.Session, store.Session.id == store.CapitalPlan.research_id)
            .where(store.CapitalPlan.account_id == account_id, store.Session.deleted_at.is_(None))
        )
    ).all()
    total = ZERO
    for plan in plans:
        if plan.id != excluding:
            total = money_sum(
                total,
                max(remaining_capital(plan.allocated_capital or ZERO, plan.net or ZERO), ZERO),
            )
    return total


async def lock_account(
    session: AsyncSession, *, user_id: Any, account_id: Any
) -> store.InvestmentAccount:
    from server import business_service as biz

    account = (
        await session.execute(
            select(store.InvestmentAccount)
            .where(
                store.InvestmentAccount.id == account_id,
                store.InvestmentAccount.user_id == user_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if account is None:
        raise biz.PurposeRequirementError("请先绑定主账户", fields={"account_id": "缺少有效账户"})
    if account.archived:
        raise biz.ObjectArchivedError("账户已归档，不能再调整资金")
    return account


async def account_values(session: AsyncSession, account: store.InvestmentAccount) -> dict:
    from server import business_service as biz

    return await biz._load_revision_values(
        session, store.InvestmentAccountRevision, "account_id", account.id, account.current_revision
    )


async def check_budget(
    session: AsyncSession, *, plan: store.CapitalPlan, amount: Decimal | None
) -> None:
    from server import business_service as biz

    account = await lock_account(session, user_id=plan.user_id, account_id=plan.account_id)
    values = await account_values(session, account)
    if (
        plan.currency != account.base_currency
        or values.get("currency", plan.currency) != plan.currency
    ):
        raise biz.ValidationError(
            "规划资金必须与账户币种一致", fields={"currency": "不支持自动换汇"}
        )
    if amount is None:
        return
    if amount >= Decimal("1e20"):
        raise biz.ValidationError("规划资金超出支持范围")
    net = await cash_effect(session, plan.id) if plan.id else ZERO
    remaining = remaining_capital(amount, net)
    if remaining < 0:
        raise biz.ValidationError(
            "规划资金不能低于已使用净额", fields={"allocated_capital": str(-net)}
        )
    available = values.get("available_capital")
    if available is None:
        raise biz.PurposeRequirementError(
            "请先补齐账户可用资金", fields={"available_capital": "缺少现金余额"}
        )
    other = await reservations(session, account.id, excluding=plan.id)
    if money_sum(remaining, other) > available:
        raise biz.ValidationError(
            "规划资金超过账户可分配额度",
            fields={
                "allocated_capital": f"当前会话最多可规划 {max(money_sum(available, -other, -min(net, ZERO)), ZERO)}"
            },
        )


async def book_fill(
    session: AsyncSession,
    *,
    capital: store.CapitalPlan,
    fill: store.BuySellPlan,
    values: dict[str, Any] | None,
) -> None:
    """Book a new fill, its replacement, or an archive (values=None) exactly once."""
    from server import business_service as biz

    account = await lock_account(session, user_id=capital.user_id, account_id=capital.account_id)
    previous = await account_values(session, account)
    if values is not None and (
        values.get("currency") != capital.currency
        or capital.currency != account.base_currency
        or previous.get("currency", capital.currency) != capital.currency
    ):
        raise biz.ValidationError(
            "成交、规划资金与账户币种必须一致", fields={"currency": "不支持自动换汇"}
        )
    old_effect = fill.cash_effect or ZERO
    if values is None or values.get("quantity") is None:
        effect = ZERO
    else:
        if values["quantity"] <= 0 or values["price"] <= 0:
            raise biz.ValidationError(
                "成交价格与数量必须大于零", fields={"quantity": "请填写真实正数成交量"}
            )
        with localcontext() as ctx:
            ctx.prec = 70
            gross = values["price"] * values["quantity"]
            fees = values.get("fees") or ZERO
            effect = (-gross - fees if values["side"] == "buy" else gross - fees).quantize(
                Decimal("0.0000000001")
            )
        if effect.copy_abs() >= Decimal("1e20"):
            raise biz.ValidationError("成交金额超出支持范围")
    delta = money_sum(effect, old_effect.copy_negate())
    if delta:
        available = previous.get("available_capital")
        if available is None or capital.allocated_capital is None:
            raise biz.PurposeRequirementError(
                "入账前请补齐账户现金与会话规划资金", fields={"available_capital": "缺少资金基准"}
            )
        net = await cash_effect(session, capital.id)
        remaining = remaining_capital(capital.allocated_capital, money_sum(net, delta))
        if remaining < 0:
            raise biz.ValidationError(
                "成交超出本会话剩余额度", fields={"quantity": "请先追加规划资金"}
            )
        new_cash = money_sum(available, delta)
        other = await reservations(session, account.id, excluding=capital.id)
        if new_cash < money_sum(max(remaining, ZERO), other):
            raise biz.ValidationError("账户现金不足，不能占用其他会话额度")
        if new_cash >= Decimal("1e20"):
            raise biz.ValidationError("账户现金超出支持范围")
        revision = account.current_revision + 1
        merged = {key: previous.get(key) for key in biz.ACCOUNT_VALUE_COLUMNS}
        merged["available_capital"] = new_cash
        # Total capital is the user's asset valuation, not a second cash balance.
        session.add(
            store.InvestmentAccountRevision(
                account_id=account.id,
                revision=revision,
                **merged,
                record_state=previous.get("record_state", "submitted"),
                source_kind="buy_sell_plan",
                source_ref=str(fill.id),
                changed_fields={
                    "fields": ["available_capital"],
                    "pending_fields": (previous.get("changed_fields") or {}).get(
                        "pending_fields", []
                    ),
                    "cash_delta": str(delta),
                    "buy_sell_plan_id": str(fill.id),
                },
            )
        )
        account.current_revision = revision
        biz._append_audit(
            session,
            user_id=capital.user_id,
            action="business.account.fill",
            detail={
                "account_id": str(account.id),
                "buy_sell_plan_id": str(fill.id),
                "revision": revision,
            },
        )
    fill.cash_effect = effect if values is None or values.get("quantity") is not None else None
    await session.flush()


async def account_summary(session: AsyncSession, account: store.InvestmentAccount) -> dict:
    values = await account_values(session, account)
    reserved = await reservations(session, account.id)
    available = values.get("available_capital")
    return {
        "reserved_capital": decimal_text(reserved),
        "allocatable_capital": decimal_text(money_sum(available, reserved.copy_negate()))
        if available is not None
        else None,
    }


async def plan_summary(session: AsyncSession, plan: store.CapitalPlan) -> dict:
    net = await cash_effect(session, plan.id)
    pending = (
        await session.execute(
            select(func.count())
            .select_from(store.BuySellPlan)
            .where(
                store.BuySellPlan.capital_plan_id == plan.id,
                store.BuySellPlan.archived.is_(False),
                store.BuySellPlan.cash_effect.is_(None),
            )
        )
    ).scalar_one()
    return {
        "net_cash_flow": decimal_text(net),
        "remaining_capital": decimal_text(remaining_capital(plan.allocated_capital, net))
        if plan.allocated_capital is not None
        else None,
        "unbooked_count": pending,
    }
