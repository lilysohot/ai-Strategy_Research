"""Add the monitoring-rule model and immutable version rows (DATA-09)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013_watch_rules"
down_revision = "0012_business_events"
branch_labels = None
depends_on = None


def _uuid() -> sa.types.TypeEngine:
    return postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite")


# 与 store.MONEY（NUMERIC(30,10)）保持一致；精确数值不用 float。
MONEY = sa.Numeric(precision=30, scale=10, asdecimal=True)


def upgrade() -> None:
    op.create_table(
        "watch_rules",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("research_id", _uuid(), nullable=False),
        sa.Column("plan_id", _uuid()),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_check_at", sa.DateTime(timezone=True)),
        sa.Column("last_valid_quote_at", sa.DateTime(timezone=True)),
        sa.Column("last_valid_quote_price", MONEY),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["research_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["investment_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "id", name="uq_watch_rules_user_id"),
    )
    op.create_index("ix_watch_rules_research_status", "watch_rules", ["research_id", "status"])

    op.create_table(
        "watch_rule_revisions",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("rule_id", _uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("market", sa.String(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("quote_basis", sa.String(), nullable=False, server_default="last"),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("threshold_low", MONEY),
        sa.Column("threshold_high", MONEY),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("trigger_mode", sa.String(), nullable=False, server_default="single"),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("task", sa.Text()),
        sa.Column("budget_json", sa.JSON(), nullable=False),
        sa.Column(
            "on_create_already_met", sa.String(), nullable=False, server_default="trigger_now"
        ),
        sa.Column(
            "disconnect_recovery", sa.String(), nullable=False, server_default="trigger_once"
        ),
        sa.Column("source_kind", sa.String(), nullable=False, server_default="form"),
        sa.Column("source_ref", sa.String()),
        sa.Column("changed_fields", sa.JSON()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["rule_id"], ["watch_rules.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id", "version", name="uq_watch_rule_revisions_version"),
    )
    op.create_index("ix_watch_rule_revisions_rule", "watch_rule_revisions", ["rule_id"])


def downgrade() -> None:
    op.drop_index("ix_watch_rule_revisions_rule", table_name="watch_rule_revisions")
    op.drop_table("watch_rule_revisions")
    op.drop_index("ix_watch_rules_research_status", table_name="watch_rules")
    op.drop_table("watch_rules")
