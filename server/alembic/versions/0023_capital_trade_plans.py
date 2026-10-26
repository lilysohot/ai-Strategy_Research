"""Split session plans: capital plan (1:1) and buy/sell plan (1:N).

Revision ID: 0023_capital_trade_plans
Revises: 0022_run_context_sources

会话记录原来把「规划资金」与「买卖价格」混在同一张 ``investment_plans`` 版本行里，
并且规划资金是覆盖式写入：第二次提交会把第一次的分配额改掉。本迁移把两者拆成
互相独立、层级明确的两组表：

* ``capital_plans`` — **一个会话至多一条**（``research_id`` 唯一）。``allocated_capital``
  是累计值，只通过 ``allocation_delta`` 累加或显式 ``reset`` 重设，版本行记录
  ``op_type`` 与本次增量，重复写入不再互相覆盖。
* ``buy_sell_plans`` — 规划资金下的 **1:N** 实际买卖价格记录（``side`` + ``price`` +
  ``quantity`` + ``traded_at``），与规划资金分表、各自独立版本。

存量回填（2026-10-08 之前的数据）：

1. 每个已有计划的会话，取主计划（``research_investment_links.primary_plan_id``）或最近
   更新的未归档计划，建一条 ``capital_plans``（id 复用原计划 id，便于追溯），并把该计划
   最新版本里的 ``allocated_capital`` 记为 ``initial`` 版本。
2. 同一计划最新版本若带方向与价格（``target_price`` 或已废弃的 ``plan_price``），回填
   一条 ``buy_sell_plans`` 实际价格记录；价格缺失则不造行（缺失 ≠ 0）。

旧表 ``investment_plans`` / ``investment_plan_revisions`` 保持原样只读保留：历史快照和
Run 快照仍引用它们的版本行，删除会破坏不可变历史。
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023_capital_trade_plans"
down_revision = "0022_run_context_sources"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(precision=30, scale=10, asdecimal=True)


def _uuid() -> sa.types.TypeEngine:
    return postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite")


def upgrade() -> None:
    op.create_table(
        "capital_plans",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("research_id", _uuid(), nullable=False),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("account_id", _uuid(), nullable=True),
        sa.Column("allocated_capital", MONEY, nullable=True),
        sa.Column("currency", sa.String(), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_state", sa.String(), server_default="submitted", nullable=False),
        sa.Column("source_kind", sa.String(), server_default="form", nullable=False),
        sa.Column("source_ref", sa.String(), nullable=True),
        sa.Column("current_revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.ForeignKeyConstraint(["research_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["investment_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        # 会话 ↔ 规划资金是一对一，由库层保证而不是只靠服务层判断。
        sa.UniqueConstraint("research_id", name="uq_capital_plans_research"),
    )
    op.create_index("ix_capital_plans_research", "capital_plans", ["research_id"])

    op.create_table(
        "capital_plan_revisions",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("capital_plan_id", _uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        #: initial / alloc（累加）/ reset（重设）
        sa.Column("op_type", sa.String(), nullable=False),
        sa.Column("allocation_delta", MONEY, nullable=True),
        sa.Column("allocated_capital", MONEY, nullable=True),
        sa.Column("currency", sa.String(), nullable=True),
        sa.Column("account_id", _uuid(), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_state", sa.String(), server_default="submitted", nullable=False),
        sa.Column("source_kind", sa.String(), server_default="form", nullable=False),
        sa.Column("source_ref", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.ForeignKeyConstraint(["capital_plan_id"], ["capital_plans.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["investment_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("capital_plan_id", "revision", name="uq_capital_plan_revisions_ver"),
    )
    op.create_index("ix_capital_plan_revisions_plan", "capital_plan_revisions", ["capital_plan_id"])

    op.create_table(
        "buy_sell_plans",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("capital_plan_id", _uuid(), nullable=False),
        sa.Column("research_id", _uuid(), nullable=False),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("status", sa.String(), server_default="active", nullable=False),
        sa.Column("archived", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("current_revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.ForeignKeyConstraint(["capital_plan_id"], ["capital_plans.id"]),
        sa.ForeignKeyConstraint(["research_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_buy_sell_plans_capital", "buy_sell_plans", ["capital_plan_id"])

    op.create_table(
        "buy_sell_plan_revisions",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("buy_sell_plan_id", _uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("market", sa.String(), nullable=True),
        sa.Column("asset_type", sa.String(), nullable=True),
        sa.Column("side", sa.String(), nullable=False),
        #: 实际买卖价格（成交价）。
        sa.Column("price", MONEY, nullable=False),
        sa.Column("quantity", MONEY, nullable=True),
        sa.Column("traded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("source_kind", sa.String(), server_default="form", nullable=False),
        sa.Column("source_ref", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.ForeignKeyConstraint(["buy_sell_plan_id"], ["buy_sell_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("buy_sell_plan_id", "revision", name="uq_buy_sell_plan_ver"),
    )
    op.create_index(
        "ix_buy_sell_plan_revisions_plan", "buy_sell_plan_revisions", ["buy_sell_plan_id"]
    )

    _backfill_from_investment_plans()
    _protect_new_history()


def _protect_new_history() -> None:
    """与 0010 一致：版本行只 INSERT，不接受 UPDATE/DELETE。"""
    tables = ("capital_plan_revisions", "buy_sell_plan_revisions")
    if op.get_bind().dialect.name == "postgresql":
        for table in tables:
            op.execute(
                f"CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION reject_business_history_mutation()"
            )
    else:
        for table in tables:
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action.lower()} "
                    f"BEFORE {action} ON {table} BEGIN "
                    "SELECT RAISE(ABORT, 'business history is immutable'); END"
                )


def _backfill_from_investment_plans() -> None:
    """把旧的会话计划回填成规划资金（1:1）与买卖价格（1:N）两组记录。

    只读取旧表，不修改它；每条回填都先查存在性，重复执行不会产生第二份。
    """
    bind = op.get_bind()

    sessions = (
        bind.execute(
            sa.text(
                """
            SELECT s.id AS research_id, s.user_id, l.primary_plan_id, l.account_id
            FROM sessions s
            JOIN investment_plans p ON p.research_id = s.id
            LEFT JOIN research_investment_links l ON l.research_id = s.id
            GROUP BY s.id, s.user_id, l.primary_plan_id, l.account_id
            """
            )
        )
        .mappings()
        .all()
    )

    for row in sessions:
        research_id = row["research_id"]
        user_id = row["user_id"]
        primary_plan_id = row["primary_plan_id"]

        chosen = None
        if primary_plan_id is not None:
            chosen = (
                bind.execute(
                    sa.text(
                        "SELECT id, current_revision FROM investment_plans "
                        "WHERE id = :pid AND research_id = :rid"
                    ),
                    {"pid": primary_plan_id, "rid": research_id},
                )
                .mappings()
                .first()
            )
        if chosen is None:
            chosen = (
                bind.execute(
                    sa.text(
                        "SELECT id, current_revision FROM investment_plans "
                        "WHERE research_id = :rid "
                        "ORDER BY archived ASC, updated_at DESC, created_at DESC LIMIT 1"
                    ),
                    {"rid": research_id},
                )
                .mappings()
                .first()
            )
        if chosen is None:  # pragma: no cover — JOIN 已保证至少一条
            continue

        plan_id = chosen["id"]
        revision = (
            bind.execute(
                sa.text(
                    """
                SELECT symbol, market, asset_type, direction, target_price, plan_price,
                       allocated_capital, currency, as_of, record_state
                FROM investment_plan_revisions
                WHERE plan_id = :pid AND revision = :rev
                """
                ),
                {"pid": plan_id, "rev": chosen["current_revision"]},
            )
            .mappings()
            .first()
        )

        exists = bind.execute(
            sa.text("SELECT 1 FROM capital_plans WHERE research_id = :rid"),
            {"rid": research_id},
        ).first()
        if exists is None:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO capital_plans (
                        id, research_id, user_id, account_id, allocated_capital,
                        currency, as_of, record_state, source_kind, source_ref,
                        current_revision
                    ) VALUES (
                        :id, :rid, :uid, :aid, :alloc,
                        :cur, :as_of, :state, 'migration', 'investment_plans', 1
                    )
                    """
                ),
                {
                    "id": plan_id,
                    "rid": research_id,
                    "uid": user_id,
                    "aid": row["account_id"],
                    "alloc": revision["allocated_capital"] if revision else None,
                    "cur": revision["currency"] if revision else None,
                    "as_of": revision["as_of"] if revision else None,
                    "state": (revision["record_state"] if revision else "submitted"),
                },
            )
            bind.execute(
                sa.text(
                    """
                    INSERT INTO capital_plan_revisions (
                        id, capital_plan_id, revision, op_type, allocation_delta,
                        allocated_capital, currency, account_id, as_of, record_state,
                        source_kind, source_ref
                    ) VALUES (
                        :id, :pid, 1, 'initial', :alloc,
                        :alloc, :cur, :aid, :as_of, :state,
                        'migration', 'investment_plans'
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "pid": plan_id,
                    "alloc": revision["allocated_capital"] if revision else None,
                    "cur": revision["currency"] if revision else None,
                    "aid": row["account_id"],
                    "as_of": revision["as_of"] if revision else None,
                    "state": (revision["record_state"] if revision else "submitted"),
                },
            )

        if revision is None:
            continue
        side = revision["direction"]
        price = revision["target_price"]
        if price is None:
            price = revision["plan_price"]
        symbol = revision["symbol"]
        if side not in {"buy", "sell"} or price is None or not symbol:
            # 计划只登记资金、没有价格时，不造买卖价格行（缺失 ≠ 0）。
            continue

        buy_sell_id = uuid.uuid4()
        bind.execute(
            sa.text(
                """
                INSERT INTO buy_sell_plans (
                    id, capital_plan_id, research_id, user_id, status, archived,
                    current_revision
                ) VALUES (
                    :id, :pid, :rid, :uid, 'active', false, 1
                )
                """
            ),
            {"id": buy_sell_id, "pid": plan_id, "rid": research_id, "uid": user_id},
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO buy_sell_plan_revisions (
                    id, buy_sell_plan_id, revision, symbol, market, asset_type, side,
                    price, quantity, traded_at, currency, source_kind, source_ref
                ) VALUES (
                    :id, :bsid, 1, :symbol, :market, :asset_type, :side,
                    :price, NULL, :traded_at, :currency, 'migration', 'investment_plans'
                )
                """
            ),
            {
                "id": uuid.uuid4(),
                "bsid": buy_sell_id,
                "symbol": symbol,
                "market": revision["market"],
                "asset_type": revision["asset_type"],
                "side": side,
                "price": price,
                "traded_at": revision["as_of"],
                "currency": revision["currency"] or "CNY",
            },
        )


def downgrade() -> None:
    tables = ("capital_plan_revisions", "buy_sell_plan_revisions")
    if op.get_bind().dialect.name == "postgresql":
        for table in tables:
            op.execute(f"DROP TRIGGER immutable_history ON {table}")
    else:
        for table in tables:
            for action in ("update", "delete"):
                op.execute(f"DROP TRIGGER IF EXISTS immutable_{table}_{action}")
    op.drop_index("ix_buy_sell_plan_revisions_plan", table_name="buy_sell_plan_revisions")
    op.drop_table("buy_sell_plan_revisions")
    op.drop_index("ix_buy_sell_plans_capital", table_name="buy_sell_plans")
    op.drop_table("buy_sell_plans")
    op.drop_index("ix_capital_plan_revisions_plan", table_name="capital_plan_revisions")
    op.drop_table("capital_plan_revisions")
    op.drop_index("ix_capital_plans_research", table_name="capital_plans")
    op.drop_table("capital_plans")
