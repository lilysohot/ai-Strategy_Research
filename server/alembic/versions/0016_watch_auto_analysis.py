"""DATA-11: event→Run linkage, analysis generations, and budget ledger.

- ``watch_events`` 追加：关联 Run、分析代次、合并去向、预算原因、调度/尝试/完成时间与
  分析截止（最大排队延迟）。
- ``watch_event_runs``：事件→Run 的分析代次链路，``(event_id, generation)`` 唯一 ——
  每事件每代次唯一，重试沿用原 Run，重新分析 +1 且保留旧终态。
- ``watch_budget_usage``：每规则版本的自动分析预算台账（runs_created / runs_attempted），
  调度时原子预留并记账，幂等累加。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_watch_auto_analysis"
down_revision = "0015_watch_monitoring"
branch_labels = None
depends_on = None


def _uuid() -> sa.types.TypeEngine:
    return postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite")


def upgrade() -> None:
    op.add_column("watch_events", sa.Column("run_id", _uuid()))
    op.add_column(
        "watch_events",
        sa.Column("generation", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("watch_events", sa.Column("merged_into_id", _uuid()))
    op.add_column("watch_events", sa.Column("budget_reason", sa.String()))
    op.add_column("watch_events", sa.Column("analysis_expires_at", sa.DateTime(timezone=True)))
    op.add_column("watch_events", sa.Column("scheduled_at", sa.DateTime(timezone=True)))
    op.add_column("watch_events", sa.Column("attempted_at", sa.DateTime(timezone=True)))
    op.add_column("watch_events", sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.create_foreign_key("fk_watch_events_run", "watch_events", "runs", ["run_id"], ["id"])
    op.create_foreign_key(
        "fk_watch_events_merged_into", "watch_events", "watch_events", ["merged_into_id"], ["id"]
    )

    op.create_table(
        "watch_event_runs",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("event_id", _uuid(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("run_id", _uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["event_id"], ["watch_events.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "generation", name="uq_watch_event_runs_generation"),
    )
    op.create_index("ix_watch_event_runs_event", "watch_event_runs", ["event_id"])

    op.create_table(
        "watch_budget_usage",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("rule_id", _uuid(), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("runs_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("runs_attempted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["rule_id"], ["watch_rules.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id", "rule_version", name="uq_watch_budget_usage_rule_version"),
    )
    op.create_index("ix_watch_budget_usage_rule", "watch_budget_usage", ["rule_id"])


def downgrade() -> None:
    op.drop_index("ix_watch_budget_usage_rule", table_name="watch_budget_usage")
    op.drop_table("watch_budget_usage")
    op.drop_index("ix_watch_event_runs_event", table_name="watch_event_runs")
    op.drop_table("watch_event_runs")
    op.drop_constraint("fk_watch_events_merged_into", "watch_events", type_="foreignkey")
    op.drop_constraint("fk_watch_events_run", "watch_events", type_="foreignkey")
    op.drop_column("watch_events", "completed_at")
    op.drop_column("watch_events", "attempted_at")
    op.drop_column("watch_events", "scheduled_at")
    op.drop_column("watch_events", "analysis_expires_at")
    op.drop_column("watch_events", "budget_reason")
    op.drop_column("watch_events", "merged_into_id")
    op.drop_column("watch_events", "generation")
    op.drop_column("watch_events", "run_id")
