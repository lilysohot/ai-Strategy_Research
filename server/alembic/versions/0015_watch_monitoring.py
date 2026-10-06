"""DATA-10: monitoring observations, trigger state, and trigger events.

- ``watch_rules`` 指针行追加单次触发资格状态（armed / baseline_price / last_triggered_at /
  last_suppressed_reason）。编辑（新版本）由服务层复位，不改写旧版本行。
- ``watch_observations``：判定的观测真源（精确价格 + 观测/接收时间 + 时间来源可信度 + 去重）。
- ``watch_events``：触发事实，唯一身份 = 规则版本 + 一次触发资格；status=pending 待 DATA-11。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015_watch_monitoring"
down_revision = "0014_watch_rule_history"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(precision=30, scale=10, asdecimal=True)


def _uuid() -> sa.types.TypeEngine:
    return postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite")


def _ms() -> sa.types.TypeEngine:
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.add_column(
        "watch_rules",
        sa.Column("armed", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("watch_rules", sa.Column("baseline_price", MONEY))
    op.add_column("watch_rules", sa.Column("last_triggered_at", sa.DateTime(timezone=True)))
    op.add_column("watch_rules", sa.Column("last_suppressed_reason", sa.String()))

    op.create_table(
        "watch_observations",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("rule_id", _uuid(), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("research_id", _uuid(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("market", sa.String(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("quote_basis", sa.String(), nullable=False, server_default="last"),
        sa.Column("price", MONEY, nullable=False),
        sa.Column("observed_at_ms", _ms()),
        sa.Column("received_at_ms", _ms(), nullable=False),
        sa.Column("time_source", sa.String(), nullable=False, server_default="vendor"),
        sa.Column("precision_limited", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_ref", sa.String()),
        sa.Column("dedup_hash", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["rule_id"], ["watch_rules.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["research_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedup_hash", name="uq_watch_observations_dedup"),
    )
    op.create_index(
        "ix_watch_observations_rule_time", "watch_observations", ["rule_id", "received_at_ms"]
    )

    op.create_table(
        "watch_events",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("rule_id", _uuid(), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("research_id", _uuid(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("market", sa.String(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("quote_basis", sa.String(), nullable=False, server_default="last"),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("threshold_low", MONEY),
        sa.Column("threshold_high", MONEY),
        sa.Column("prev_price", MONEY),
        sa.Column("price", MONEY, nullable=False),
        sa.Column("observed_at_ms", _ms()),
        sa.Column("received_at_ms", _ms(), nullable=False),
        sa.Column("time_source", sa.String(), nullable=False, server_default="vendor"),
        sa.Column("trigger_reason", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("detail_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["rule_id"], ["watch_rules.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["research_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id", "rule_version", name="uq_watch_events_rule_version"),
    )
    op.create_index("ix_watch_events_research_status", "watch_events", ["research_id", "status"])
    op.create_index("ix_watch_events_user_created", "watch_events", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_watch_events_user_created", table_name="watch_events")
    op.drop_index("ix_watch_events_research_status", table_name="watch_events")
    op.drop_table("watch_events")
    op.drop_index("ix_watch_observations_rule_time", table_name="watch_observations")
    op.drop_table("watch_observations")
    op.drop_column("watch_rules", "last_suppressed_reason")
    op.drop_column("watch_rules", "last_triggered_at")
    op.drop_column("watch_rules", "baseline_price")
    op.drop_column("watch_rules", "armed")
