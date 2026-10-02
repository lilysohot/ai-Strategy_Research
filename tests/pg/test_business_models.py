"""DATA-02 验收：业务对象在真实 PostgreSQL 上的精度、约束与归属行为。

每条用例对应持久化任务 DATA-02 的一条验收或一条 PRD AC：

* 列精度与十进制往返 → 契约 §1.1（缺失不是 0，金额不走浮点）
* 版本唯一 / 只追加 → “版本不能原地覆盖”
* 复合外键 → AC-01（主计划只能来自本研究）、AC-09（不能引用他人账户）
* 成交更正链 → AC-22（更正保留前值）

这些性质在 SQLite 上不成立或不可靠（NUMERIC 是仿射类型、外键默认关闭），
因此只放在 PG 集成入口下运行。
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.pg

PRECISION_SAMPLE = "1234567890.1234567890"


async def _insert_user(session, name: str) -> uuid.UUID:
    user_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO users (id, username, password_hash, status) "
            "VALUES (:id, :name, :hash, 'active')"
        ),
        {"id": user_id, "name": name, "hash": "not-a-real-hash"},
    )
    return user_id


async def _insert_session(session, user_id: uuid.UUID, title: str) -> uuid.UUID:
    session_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO sessions (id, user_id, title) VALUES (:id, :uid, :title)"),
        {"id": session_id, "uid": user_id, "title": title},
    )
    return session_id


async def _insert_account(session, user_id: uuid.UUID, name: str) -> uuid.UUID:
    account_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO investment_accounts (id, user_id, name, base_currency) "
            "VALUES (:id, :uid, :name, 'CNY')"
        ),
        {"id": account_id, "uid": user_id, "name": name},
    )
    return account_id


async def _insert_plan(session, research_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
    plan_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO investment_plans (id, research_id, user_id, name) "
            "VALUES (:id, :rid, :uid, 'plan')"
        ),
        {"id": plan_id, "rid": research_id, "uid": user_id},
    )
    return plan_id


async def test_money_columns_are_exact_numerics(pg_session) -> None:
    """契约 §1.1：金额列为 NUMERIC(30,10)，比例列为 NUMERIC(20,10)。"""
    rows = (
        await pg_session.execute(
            text(
                "SELECT table_name, column_name, numeric_precision, numeric_scale "
                "FROM information_schema.columns "
                "WHERE table_name IN ('investment_account_revisions',"
                " 'investment_plan_revisions') "
                "AND column_name IN ('total_capital', 'available_capital',"
                " 'plan_price', 'profit_loss_ratio')"
            )
        )
    ).all()

    shape = {(r[0], r[1]): (r[2], r[3]) for r in rows}
    assert shape[("investment_account_revisions", "total_capital")] == (30, 10)
    assert shape[("investment_plan_revisions", "plan_price")] == (30, 10)
    assert shape[("investment_plan_revisions", "profit_loss_ratio")] == (20, 10)


async def test_decimal_round_trip_keeps_every_digit(pg_session) -> None:
    """用户填的十进制数经写入与读回必须逐位相同（DATA-02 精度验收）。"""
    user_id = await _insert_user(pg_session, "pg-biz-precision")
    account_id = await _insert_account(pg_session, user_id, "主账户")

    await pg_session.execute(
        text(
            "INSERT INTO investment_account_revisions "
            "(id, account_id, revision, total_capital, available_capital, currency,"
            " capital_basis, record_state) "
            "VALUES (:id, :aid, 1, :total, :available, 'CNY', 'total', 'submitted')"
        ),
        {
            "id": uuid.uuid4(),
            "aid": account_id,
            "total": Decimal(PRECISION_SAMPLE),
            "available": Decimal("0.0000000001"),
        },
    )
    await pg_session.commit()

    stored = (
        await pg_session.execute(
            text(
                "SELECT total_capital::text, available_capital::text "
                "FROM investment_account_revisions WHERE account_id = :aid"
            ),
            {"aid": account_id},
        )
    ).one()

    assert stored[0] == PRECISION_SAMPLE, stored[0]
    assert stored[1] == "0.0000000001", stored[1]


async def test_missing_capital_stays_null_not_zero(pg_session) -> None:
    """缺失是 NULL，不是 0（AC-03 / AC-26）。"""
    user_id = await _insert_user(pg_session, "pg-biz-null")
    account_id = await _insert_account(pg_session, user_id, "空账户")
    await pg_session.execute(
        text(
            "INSERT INTO investment_account_revisions "
            "(id, account_id, revision, currency, record_state) "
            "VALUES (:id, :aid, 1, 'CNY', 'incomplete')"
        ),
        {"id": uuid.uuid4(), "aid": account_id},
    )
    await pg_session.commit()

    total = (
        await pg_session.execute(
            text("SELECT total_capital FROM investment_account_revisions WHERE account_id = :aid"),
            {"aid": account_id},
        )
    ).scalar_one()
    assert total is None, "缺失字段被写成了 0 或其他默认值"


async def test_revision_cannot_be_reused(pg_session) -> None:
    """版本不可变：(account_id, revision) 重复即拒绝（版本不能原地覆盖）。"""
    user_id = await _insert_user(pg_session, "pg-biz-version")
    account_id = await _insert_account(pg_session, user_id, "版本账户")

    insert = text(
        "INSERT INTO investment_account_revisions "
        "(id, account_id, revision, currency, total_capital) "
        "VALUES (:id, :aid, 1, 'CNY', :total)"
    )
    await pg_session.execute(insert, {"id": uuid.uuid4(), "aid": account_id, "total": Decimal("1")})
    await pg_session.commit()

    with pytest.raises(IntegrityError):
        await pg_session.execute(
            insert, {"id": uuid.uuid4(), "aid": account_id, "total": Decimal("2")}
        )
        await pg_session.commit()
    await pg_session.rollback()


async def test_primary_plan_must_belong_to_the_same_research(pg_session) -> None:
    """AC-01：主计划只能来自本研究自己的计划集合，跨研究引用被数据库拒绝。"""
    user_id = await _insert_user(pg_session, "pg-biz-plan-link")
    research_a = await _insert_session(pg_session, user_id, "研究A")
    research_b = await _insert_session(pg_session, user_id, "研究B")
    plan_a = await _insert_plan(pg_session, research_a, user_id)
    await pg_session.commit()

    link = text(
        "INSERT INTO research_investment_links "
        "(research_id, user_id, primary_plan_id) VALUES (:rid, :uid, :pid)"
    )
    await pg_session.execute(link, {"rid": research_a, "uid": user_id, "pid": plan_a})
    await pg_session.commit()

    with pytest.raises(IntegrityError):
        await pg_session.execute(link, {"rid": research_b, "uid": user_id, "pid": plan_a})
        await pg_session.commit()
    await pg_session.rollback()


async def test_research_cannot_reference_another_users_account(pg_session) -> None:
    """AC-09：研究绑定不能引用他人账户（复合外键，而非仅靠服务层约定）。"""
    owner = await _insert_user(pg_session, "pg-biz-owner")
    other = await _insert_user(pg_session, "pg-biz-other")
    research = await _insert_session(pg_session, owner, "研究")
    foreign_account = await _insert_account(pg_session, other, "他人账户")
    await pg_session.commit()

    with pytest.raises(IntegrityError):
        await pg_session.execute(
            text(
                "INSERT INTO research_investment_links (research_id, user_id, account_id) "
                "VALUES (:rid, :uid, :aid)"
            ),
            {"rid": research, "uid": owner, "aid": foreign_account},
        )
        await pg_session.commit()
    await pg_session.rollback()


async def test_trade_correction_keeps_the_original_row(pg_session) -> None:
    """AC-22：成交更正创建新行并保留前值，不原地改写历史。"""
    user_id = await _insert_user(pg_session, "pg-biz-trade")
    account_id = await _insert_account(pg_session, user_id, "交易账户")

    original = uuid.uuid4()
    await pg_session.execute(
        text(
            "INSERT INTO trade_records "
            "(id, user_id, account_id, symbol, side, quantity, price, currency, status) "
            "VALUES (:id, :uid, :aid, '600519.SH', 'buy', :qty, :price, 'CNY', 'active')"
        ),
        {"id": original, "uid": user_id, "aid": account_id, "qty": Decimal("100"), "price": Decimal("20")},
    )
    await pg_session.commit()

    await pg_session.execute(
        text(
            "INSERT INTO trade_records "
            "(id, user_id, account_id, symbol, side, quantity, price, currency, status,"
            " corrects_id) "
            "VALUES (:id, :uid, :aid, '600519.SH', 'buy', :qty, :price, 'CNY', 'active', :orig)"
        ),
        {
            "id": uuid.uuid4(),
            "uid": user_id,
            "aid": account_id,
            "qty": Decimal("100"),
            "price": Decimal("20.5"),
            "orig": original,
        },
    )
    await pg_session.execute(
        text("UPDATE trade_records SET status = 'corrected' WHERE id = :id"),
        {"id": original},
    )
    await pg_session.commit()

    rows = (
        await pg_session.execute(
            text(
                "SELECT price::text, status, corrects_id IS NULL AS is_original "
                "FROM trade_records WHERE account_id = :aid ORDER BY created_at"
            ),
            {"aid": account_id},
        )
    ).all()
    # NUMERIC(30,10) 以定点形式回显（20.0000000000），比较用 Decimal 数值等价。
    assert [Decimal(r[0]) for r in rows] == [Decimal("20"), Decimal("20.5")], rows
    assert [r[1] for r in rows] == ["corrected", "active"], rows
    assert rows[1][2] is False, "更正行必须指向被更正的原行"
