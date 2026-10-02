"""Baseline proofs the business-data work depends on, on real PostgreSQL.

Each test here is a *precondition* of a DATA task, not a feature test:

* target guard        → DATA-00 (never run against the business database)
* schema head         → DATA-02 (migrations reach head on a real server)
* numeric round-trip  → DATA-02 (money/price/quantity must survive exactly)
* transactional DDL   → DATA-06 (business change + snapshot + outbox in one tx)

They are intentionally small and dependency-light so they can run before any
business table exists; later DATA tasks add their own files next to this one.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.pg


async def test_entry_target_is_the_registered_test_database(pg_session) -> None:
    """The connection must be PostgreSQL and the database the batch registered."""
    row = (
        await pg_session.execute(text("SELECT current_database(), current_user, version()"))
    ).one()
    database, user, version = str(row[0]), str(row[1]), str(row[2])

    assert database == os.environ["PG_BUSINESS_TEST_DB"]
    assert database not in {"apodex", "postgres"}
    assert "PostgreSQL" in version, version
    # An integration run that reaches the shared business DB would reconcile
    # orphan runs against another process' live handles.
    print(f"PG target: db={database} user={user} version={version}")


async def test_schema_stamp_matches_the_code_head(pg_session) -> None:
    """Alembic head in the repository is what the test database carries."""
    from server.readiness import expected_heads

    heads = expected_heads()
    assert len(heads) == 1, f"迁移存在多个 head，需先合并：{heads}"

    stamped = (
        (await pg_session.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
    )
    assert tuple(stamped) == heads, f"测试库 schema {stamped} 与代码 head {heads} 不一致"


async def test_numeric_round_trip_is_exact(pg_session) -> None:
    """十进制字符串经 PostgreSQL NUMERIC 往返不丢精度（DATA-02 前提）。

    Money, price and quantity travel as decimal strings precisely so JavaScript
    and Python floats cannot round them; the column type has to hold up its end.
    """
    value = "1234567890.1234567890"
    await pg_session.execute(text("CREATE TABLE pg_entry_numeric (v numeric(30,10))"))
    try:
        await pg_session.execute(text("INSERT INTO pg_entry_numeric (v) VALUES (:v)"), {"v": value})
        await pg_session.commit()
        stored = (
            await pg_session.execute(text("SELECT v::text FROM pg_entry_numeric"))
        ).scalar_one()
    finally:
        await pg_session.execute(text("DROP TABLE IF EXISTS pg_entry_numeric"))
        await pg_session.commit()

    assert stored.rstrip("0").rstrip(".") == value.rstrip("0").rstrip("."), stored


async def test_rolled_back_transaction_leaves_no_trace(pg_clean) -> None:
    """事务回滚必须撤销 DDL 与数据（DATA-06 原子提交前提）。

    “保存并分析”把业务变更、快照、queued Run 与 outbox 放进同一个事务：只要
    任一步失败，其余步骤必须一起消失，而不是留下半个已保存的 Run。
    """
    from server import store

    probe = "pg_entry_rollback_probe"
    async with await store.session_scope() as session, session.begin():
        await session.execute(text(f"CREATE TABLE {probe} (id int)"))
        await session.execute(text(f"INSERT INTO {probe} (id) VALUES (1)"))
        await session.rollback()

    async with await store.session_scope() as session:
        exists = (
            await session.execute(
                text("SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename = :name"),
                {"name": probe},
            )
        ).scalar_one_or_none()
    assert exists is None, "回滚后对象仍然存在，原子提交无法依赖该数据库语义"
