"""business data: accounts, plans, positions, trades, research links, strategies

Revision ID: 0005_business_objects
Revises: 0004_control_records
Create Date: 2026-10-02

DATA-02 / PR-DATA-13 / PR-BIZ-01. Investment facts used to live only in chat
text: a page reload, a context trim or a later correction had no independent
source of truth, and nothing could tell "the user said 8 万" from "the report
assumed 8 万". This creates the tables that hold them as typed, versioned rows.

Design points that are load-bearing (see
docs/design/web-business-data-contract.md):

* **Exact numerics.** Money, price and quantity are ``NUMERIC(30,10)`` and
  ratios ``NUMERIC(20,10)`` — never float, because a float cannot represent a
  decimal the user typed and would silently re-round it.
* **Missing is NULL.** No column defaults to 0: "unknown" must stay unknown
  (AC-03, AC-26).
* **Versions are append-only.** ``*_revisions`` carry one immutable row per
  change, unique on ``(object_id, revision)``. The current row is a pointer;
  the service must never UPDATE a revision row.
* **Ownership is a constraint, not a convention.** ``research_investment_links``
  uses two composite foreign keys so the database — not just the service —
  rejects an account owned by another user (AC-09) and a primary plan that
  belongs to a different research (AC-01).

Purely additive: no existing table or column is touched, so the only pre-flight
is that ``users`` / ``sessions`` / ``runs`` exist (guaranteed by 0001).

Deployment note: ``init_db()``'s ``create_all`` will NOT add these tables to an
existing database. Run ``alembic upgrade head`` once.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_business_objects"
down_revision = "0004_control_records"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(precision=30, scale=10, asdecimal=True)
RATIO = sa.Numeric(precision=20, scale=10, asdecimal=True)


def upgrade() -> None:
    op.create_table(
        "investment_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("base_currency", sa.String(), nullable=False),
        sa.Column("archived", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("current_revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        # “当前账户”在聊天里必须能唯一定位（AC-02）。
        sa.UniqueConstraint("user_id", "name", name="uq_investment_accounts_user_name"),
        # 供 research_investment_links 的复合外键引用，把归属下沉到数据库。
        sa.UniqueConstraint("user_id", "id", name="uq_investment_accounts_user_id"),
    )

    op.create_table(
        "investment_account_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("total_capital", MONEY, nullable=True),
        sa.Column("available_capital", MONEY, nullable=True),
        sa.Column("capital_basis", sa.String(), nullable=True),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_state", sa.String(), server_default="submitted", nullable=False),
        sa.Column("source_kind", sa.String(), server_default="form", nullable=False),
        sa.Column("source_ref", sa.String(), nullable=True),
        sa.Column("changed_fields", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["investment_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "revision", name="uq_account_revisions_version"),
    )
    op.create_index("ix_account_revisions_account", "investment_account_revisions", ["account_id"])

    op.create_table(
        "investment_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("research_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="active", nullable=False),
        sa.Column("archived", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("current_revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["research_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        # 供 research_investment_links 的复合外键引用：主计划只能来自本研究的计划集合。
        sa.UniqueConstraint("research_id", "id", name="uq_investment_plans_research_id"),
    )
    op.create_index("ix_investment_plans_research", "investment_plans", ["research_id"])

    op.create_table(
        "investment_plan_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("market", sa.String(), nullable=True),
        sa.Column("asset_type", sa.String(), nullable=True),
        sa.Column("direction", sa.String(), nullable=True),
        sa.Column("plan_price", MONEY, nullable=True),
        sa.Column("plan_price_low", MONEY, nullable=True),
        sa.Column("plan_price_high", MONEY, nullable=True),
        sa.Column("target_price", MONEY, nullable=True),
        sa.Column("risk_budget_value", MONEY, nullable=True),
        sa.Column("risk_budget_unit", sa.String(), nullable=True),
        sa.Column("position_limit_value", MONEY, nullable=True),
        sa.Column("position_limit_unit", sa.String(), nullable=True),
        sa.Column("time_window", sa.String(), nullable=True),
        sa.Column("invalidation", sa.Text(), nullable=True),
        sa.Column("profit_loss_ratio", RATIO, nullable=True),
        sa.Column("profit_loss_ratio_definition", sa.String(), nullable=True),
        sa.Column("currency", sa.String(), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_state", sa.String(), server_default="submitted", nullable=False),
        sa.Column("source_kind", sa.String(), server_default="form", nullable=False),
        sa.Column("source_ref", sa.String(), nullable=True),
        sa.Column("changed_fields", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["plan_id"], ["investment_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "revision", name="uq_plan_revisions_version"),
    )
    op.create_index("ix_plan_revisions_plan", "investment_plan_revisions", ["plan_id"])

    op.create_table(
        "position_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("market", sa.String(), nullable=True),
        sa.Column("quantity", MONEY, nullable=False),
        sa.Column("cost_basis", sa.String(), nullable=True),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_kind", sa.String(), server_default="form", nullable=False),
        sa.Column("source_ref", sa.String(), nullable=True),
        sa.Column("status", sa.String(), server_default="active", nullable=False),
        sa.Column("corrects_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["investment_accounts.id"]),
        sa.ForeignKeyConstraint(["corrects_id"], ["position_snapshots.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_position_snapshots_account", "position_snapshots", ["account_id"])

    op.create_table(
        "trade_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("market", sa.String(), nullable=True),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("quantity", MONEY, nullable=False),
        sa.Column("price", MONEY, nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("fees", MONEY, nullable=True),
        sa.Column("traded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_kind", sa.String(), server_default="form", nullable=False),
        sa.Column("source_ref", sa.String(), nullable=True),
        sa.Column("status", sa.String(), server_default="active", nullable=False),
        sa.Column("corrects_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["investment_accounts.id"]),
        sa.ForeignKeyConstraint(["corrects_id"], ["trade_records.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trade_records_account_symbol", "trade_records", ["account_id", "symbol"])

    op.create_table(
        "research_investment_links",
        sa.Column("research_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("primary_plan_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["investment_accounts.id"]),
        # 账户必须属于同一用户（AC-09）。
        sa.ForeignKeyConstraint(
            ["user_id", "account_id"],
            ["investment_accounts.user_id", "investment_accounts.id"],
            name="fk_research_links_account_owner",
        ),
        sa.ForeignKeyConstraint(["primary_plan_id"], ["investment_plans.id"]),
        # 主计划必须属于本研究自己的计划集合（AC-01）。
        sa.ForeignKeyConstraint(
            ["research_id", "primary_plan_id"],
            ["investment_plans.research_id", "investment_plans.id"],
            name="fk_research_links_plan_research",
        ),
        sa.ForeignKeyConstraint(["research_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("research_id"),
    )

    op.create_table(
        "strategy_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("research_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("artifact_rel_path", sa.String(), nullable=True),
        sa.Column("payload_ref", sa.Text(), nullable=True),
        sa.Column("adopted_plan_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["adopted_plan_id"], ["investment_plans.id"]),
        sa.ForeignKeyConstraint(["research_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_strategy_versions_research", "strategy_versions", ["research_id"])


def downgrade() -> None:
    op.drop_index("ix_strategy_versions_research", table_name="strategy_versions")
    op.drop_table("strategy_versions")
    op.drop_table("research_investment_links")
    op.drop_index("ix_trade_records_account_symbol", table_name="trade_records")
    op.drop_table("trade_records")
    op.drop_index("ix_position_snapshots_account", table_name="position_snapshots")
    op.drop_table("position_snapshots")
    op.drop_index("ix_plan_revisions_plan", table_name="investment_plan_revisions")
    op.drop_table("investment_plan_revisions")
    op.drop_index("ix_investment_plans_research", table_name="investment_plans")
    op.drop_table("investment_plans")
    op.drop_index("ix_account_revisions_account", table_name="investment_account_revisions")
    op.drop_table("investment_account_revisions")
    op.drop_table("investment_accounts")
