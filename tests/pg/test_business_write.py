"""DATA-03 验收：统一写入服务在真实 PostgreSQL 上的准入、版本、幂等与原子性。

覆盖 PR-BIZ-02/04 与 AC-02/04/05/22/25—28 的服务端部分：

* 假设/估计/疑问候选值不写入有效字段，且失败后不留半个写入（原子）
* 版本冲突返回当前版本，不静默覆盖
* 同键同内容只写一次；同键不同内容拒绝
* 用途必需字段未满足时不放行受影响的计算输入
* 归属：owner 绑定、跨用户/跨研究拒绝、不存在与无权同结果
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from server import business_service as biz
from server import store

pytestmark = pytest.mark.pg


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


async def _new_research(session, user_id: uuid.UUID, title: str = "研究") -> uuid.UUID:
    research_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO sessions (id, user_id, title) VALUES (:id, :uid, :title)"),
        {"id": research_id, "uid": user_id, "title": title},
    )
    return research_id


CAPITAL = {"total_capital": "100000", "available_capital": "60000",
           "capital_basis": "total", "as_of": "2026-10-02T00:00:00Z"}
PLAN_DECLARED = {
    "symbol": "600519.SH",
    "market": "CN",
    "direction": "buy",
    "plan_price": "19.90",
    "target_price": "24.00",
    "currency": "CNY",
}


async def _create_account(user_id, key, declared=None, **kwargs):
    async with biz.business_transaction() as session:
        return await biz.create_account(
            session,
            user_id=user_id,
            name="主账户",
            base_currency="CNY",
            declared=declared if declared is not None else dict(CAPITAL),
            idempotency_key=key,
            **kwargs,
        )


async def test_create_then_replay_same_key_writes_once(pg_clean) -> None:
    """AC-05：同键同内容重试只保存一次，第二次是重放。"""
    async with biz.business_transaction() as session:
        user_id = await _new_user(session, "pg-write-idem")

    first = await _create_account(user_id, "key-same-1")
    second = await _create_account(user_id, "key-same-1")

    assert first.replayed is False and second.replayed is True
    assert first.result["account_id"] == second.result["account_id"]

    async with biz.business_transaction() as session:
        count = (
            await session.execute(
                select(func.count()).select_from(store.InvestmentAccountRevision)
            )
        ).scalar_one()
        revisions = (
            await session.execute(
                select(store.InvestmentAccountRevision.revision).where(
                    store.InvestmentAccountRevision.account_id
                    == uuid.UUID(first.result["account_id"])
                )
            )
        ).scalars().all()
    assert count == 1, "重放产生了第二个版本"
    assert revisions == [1]


async def test_same_key_with_different_content_is_refused(pg_clean) -> None:
    """同键不同内容必须明确拒绝，不能悄悄按新内容写入。"""
    async with biz.business_transaction() as session:
        user_id = await _new_user(session, "pg-write-reuse")

    await _create_account(user_id, "key-reuse-1")
    with pytest.raises(biz.IdempotencyReuseError):
        await _create_account(
            user_id, "key-reuse-1", declared={"total_capital": "80000", "currency": "CNY"}
        )


async def test_assumed_value_is_refused_and_leaves_nothing_behind(pg_clean) -> None:
    """AC-02/25/28：假设值不写有效字段；失败后数据库不留半个账户。"""
    async with biz.business_transaction() as session:
        user_id = await _new_user(session, "pg-write-assume")

    with pytest.raises(biz.AssumptionRejectedError) as excinfo:
        await _create_account(
            user_id,
            "key-assume-1",
            declared={"total_capital": {"value": "80000", "status": "assumed"}},
        )
    assert excinfo.value.code == "assumption_rejected"

    async with biz.business_transaction() as session:
        accounts = (
            await session.execute(select(func.count()).select_from(store.InvestmentAccount))
        ).scalar_one()
        operations = (
            await session.execute(select(func.count()).select_from(store.BusinessOperation))
        ).scalar_one()
    assert (accounts, operations) == (0, 0), "被拒绝的写入没有整体回滚"


async def test_purpose_requirement_blocks_incomplete_capital(pg_clean) -> None:
    """AC-02：资金缺失而用途依赖它时，不放行“已可用于分析”的资料。"""
    async with biz.business_transaction() as session:
        user_id = await _new_user(session, "pg-write-purpose")

    with pytest.raises(biz.PurposeRequirementError) as excinfo:
        await _create_account(
            user_id, "key-purpose-1", declared={"currency": "CNY"}, use_case="plan_analysis"
        )
    assert "account.total_capital" in str(excinfo.value.fields) or any(
        "total_capital" in key for key in excinfo.value.fields
    )


async def test_explicit_incomplete_save_is_persisted_but_marked(pg_clean) -> None:
    """用户主动保存的不完整资料可读，但不是可用于依赖计算的完整记录。"""
    async with biz.business_transaction() as session:
        user_id = await _new_user(session, "pg-write-incomplete")

    # 用途依赖资金但用户只填了币种：主动保存后可读，但必须标为待补充。
    outcome = await _create_account(
        user_id,
        "key-incomplete-1",
        declared={"currency": "CNY"},
        use_case="plan_analysis",
        allow_incomplete=True,
    )
    assert outcome.result["record_state"] == "incomplete"
    assert outcome.result["incomplete"]

    async with biz.business_transaction() as session:
        row = (
            await session.execute(
                select(store.InvestmentAccountRevision).where(
                    store.InvestmentAccountRevision.revision == 1
                )
            )
        ).scalar_one()
    assert row.total_capital is None, "缺失字段被写成了默认值"
    assert row.record_state == "incomplete"


async def test_revision_conflict_returns_current_version(pg_clean) -> None:
    """AC-04：基于旧版本修改被拒，并返回当前版本供对比后重提。"""
    async with biz.business_transaction() as session:
        user_id = await _new_user(session, "pg-write-conflict")

    created = await _create_account(user_id, "key-conflict-create")
    account_id = uuid.UUID(created.result["account_id"])

    async with biz.business_transaction() as session:
        await biz.update_account(
            session,
            user_id=user_id,
            account_id=account_id,
            expected_revision=1,
            declared={"total_capital": "80000"},
            idempotency_key="key-conflict-2",
        )

    with pytest.raises(biz.RevisionConflictError) as excinfo:
        async with biz.business_transaction() as session:
            await biz.update_account(
                session,
                user_id=user_id,
                account_id=account_id,
                expected_revision=1,
                declared={"total_capital": "70000"},
                idempotency_key="key-conflict-3",
            )
    assert excinfo.value.current["revision"] == 2

    async with biz.business_transaction() as session:
        revisions = (
            await session.execute(
                select(store.InvestmentAccountRevision.revision).where(
                    store.InvestmentAccountRevision.account_id == account_id
                )
            )
        ).scalars().all()
    assert sorted(revisions) == [1, 2], "冲突写入不应产生第三个版本"


async def test_owner_cannot_be_supplied_by_client(pg_clean) -> None:
    """PR-BIZ-04：所有者由认证绑定，请求体指定身份一律拒绝。"""
    async with biz.business_transaction() as session:
        user_id = await _new_user(session, "pg-write-owner")

    with pytest.raises(biz.OwnerNotSettableError):
        await _create_account(
            user_id, "key-owner-1", declared={"user_id": str(uuid.uuid4()), "currency": "CNY"}
        )


async def test_unknown_field_is_rejected(pg_clean) -> None:
    """契约 §6：业务子结构里的未知字段明确拒绝，不被静默忽略。"""
    async with biz.business_transaction() as session:
        user_id = await _new_user(session, "pg-write-unknown")

    with pytest.raises(biz.UnknownFieldError):
        await _create_account(
            user_id, "key-unknown-1", declared={"total_capital": "1", "nickname": "x"}
        )


async def test_decimal_survives_the_service_layer(pg_clean) -> None:
    """服务层不得把用户输入的十进制数变成浮点。"""
    async with biz.business_transaction() as session:
        user_id = await _new_user(session, "pg-write-precision")

    declared = dict(CAPITAL)
    declared["total_capital"] = "1234567890.1234567890"
    outcome = await _create_account(user_id, "key-precision-1", declared=declared)

    async with biz.business_transaction() as session:
        stored = (
            await session.execute(
                text(
                    "SELECT total_capital::text FROM investment_account_revisions "
                    "WHERE account_id = :aid"
                ),
                {"aid": uuid.UUID(outcome.result["account_id"])},
            )
        ).scalar_one()
    assert stored == "1234567890.1234567890", stored


async def test_plan_belongs_to_one_research_only(pg_clean) -> None:
    """AC-01：计划只能在所属研究创建；主计划不能选别的研究的计划。"""
    async with biz.business_transaction() as session:
        user_id = await _new_user(session, "pg-write-plan")
        research_a = await _new_research(session, user_id, "研究A")
        research_b = await _new_research(session, user_id, "研究B")

    async with biz.business_transaction() as session:
        outcome = await biz.create_plan(
            session,
            user_id=user_id,
            research_id=research_a,
            name="计划A",
            declared=dict(PLAN_DECLARED),
            idempotency_key="key-plan-1",
        )
    plan_id = uuid.UUID(outcome.result["plan_id"])
    assert outcome.result["research_id"] == str(research_a)

    with pytest.raises(biz.NotFoundOrForbiddenError):
        async with biz.business_transaction() as session:
            await biz.set_research_link(
                session,
                user_id=user_id,
                research_id=research_b,
                primary_plan_id=plan_id,
                idempotency_key="key-link-1",
            )


async def test_other_users_account_is_invisible(pg_clean) -> None:
    """AC-09：他人账户既不能改也不能读，且与不存在返回同一结果。"""
    async with biz.business_transaction() as session:
        owner = await _new_user(session, "pg-write-owner-a")
        other = await _new_user(session, "pg-write-owner-b")

    created = await _create_account(owner, "key-iso-create")
    account_id = uuid.UUID(created.result["account_id"])

    with pytest.raises(biz.NotFoundOrForbiddenError):
        async with biz.business_transaction() as session:
            await biz.update_account(
                session,
                user_id=other,
                account_id=account_id,
                expected_revision=1,
                declared={"total_capital": "1"},
                idempotency_key="key-iso-1",
            )

    async with biz.business_transaction() as session:
        result = await biz.get_operation(
            session, user_id=other, operation_id=created.operation_id
        )
    assert result is None, "他人可以读取不属于自己的操作结果"


async def test_trade_correction_creates_a_new_row(pg_clean) -> None:
    """AC-22：成交更正保留原行并创建新行。"""
    async with biz.business_transaction() as session:
        user_id = await _new_user(session, "pg-write-trade")

    created = await _create_account(user_id, "key-trade-account")
    account_id = uuid.UUID(created.result["account_id"])

    async with biz.business_transaction() as session:
        trade = await biz.register_trade(
            session,
            user_id=user_id,
            account_id=account_id,
            declared={
                "symbol": "600519.SH",
                "side": "buy",
                "quantity": "100",
                "price": "20",
                "currency": "CNY",
                "traded_at": "2026-10-02T01:00:00Z",
            },
            idempotency_key="key-trade-1",
        )
    trade_id = uuid.UUID(trade.result["trade_id"])

    async with biz.business_transaction() as session:
        corrected = await biz.correct_trade(
            session,
            user_id=user_id,
            trade_id=trade_id,
            declared={"price": "20.5"},
            idempotency_key="key-trade-2",
        )
    assert corrected.result["corrects_id"] == str(trade_id)

    async with biz.business_transaction() as session:
        rows = (
            await session.execute(
                select(store.TradeRecord.status, store.TradeRecord.price).where(
                    store.TradeRecord.account_id == account_id
                )
            )
        ).all()
    prices = sorted(Decimal(str(r[1])) for r in rows)
    assert prices == [Decimal("20"), Decimal("20.5")], prices
    assert sorted(r[0] for r in rows) == ["active", "corrected"]


async def test_operation_can_be_looked_up_after_the_response_is_lost(pg_clean) -> None:
    """客户端丢响应后，用不含业务正文的 operation_id 找回结果。"""
    async with biz.business_transaction() as session:
        user_id = await _new_user(session, "pg-write-lookup")

    created = await _create_account(user_id, "key-lookup-1")

    async with biz.business_transaction() as session:
        found = await biz.get_operation(
            session, user_id=user_id, operation_id=created.operation_id
        )
        recent = await biz.list_recent_operations(session, user_id=user_id)
    assert found is not None and found["account_id"] == created.result["account_id"]
    assert recent and recent[0]["operation_id"] == created.operation_id
