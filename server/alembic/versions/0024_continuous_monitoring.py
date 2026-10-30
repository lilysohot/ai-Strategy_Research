"""Session rounds and durable FIFO monitoring signals; legacy rules stay single."""

import sqlalchemy as sa
from alembic import op

revision = "0024_continuous_monitoring"
down_revision = "0023_capital_trade_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("watch_rules", sa.Column("agent_intent", sa.String()))
    op.add_column(
        "watch_rules", sa.Column("managed_by", sa.String(), nullable=False, server_default="human")
    )
    op.add_column("watch_rules", sa.Column("rationale", sa.JSON()))
    op.create_table(
        "monitor_sessions",
        sa.Column("research_id", sa.Uuid(), sa.ForeignKey("sessions.id"), primary_key=True),
        sa.Column("auto_manage", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("next_poll_at", sa.DateTime(timezone=True)),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "monitor_rounds",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("research_id", sa.Uuid(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("lease_token", sa.String(), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("targets", sa.JSON(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("research_id", "sequence", name="uq_monitor_round_seq"),
    )
    op.add_column(
        "watch_events", sa.Column("round_id", sa.Uuid(), sa.ForeignKey("monitor_rounds.id"))
    )
    op.add_column("watch_events", sa.Column("queue_sequence", sa.Integer()))
    op.drop_constraint("uq_watch_events_rule_version", "watch_events", type_="unique")
    op.create_index(
        "uq_watch_events_rule_version",
        "watch_events",
        ["rule_id", "rule_version"],
        unique=True,
        postgresql_where=sa.text("round_id IS NULL"),
    )
    op.create_unique_constraint(
        "uq_watch_events_round", "watch_events", ["research_id", "round_id"]
    )


def downgrade() -> None:
    # Repeating events cannot be collapsed without destroying their audit history.
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT count(*) FROM watch_events WHERE round_id IS NOT NULL")):
        raise RuntimeError("Archive continuous monitoring data before downgrading")
    op.drop_constraint("uq_watch_events_round", "watch_events", type_="unique")
    op.drop_index("uq_watch_events_rule_version", table_name="watch_events")
    op.create_unique_constraint(
        "uq_watch_events_rule_version", "watch_events", ["rule_id", "rule_version"]
    )
    op.drop_column("watch_events", "queue_sequence")
    op.drop_column("watch_events", "round_id")
    op.drop_table("monitor_rounds")
    op.drop_table("monitor_sessions")
    op.drop_column("watch_rules", "rationale")
    op.drop_column("watch_rules", "managed_by")
    op.drop_column("watch_rules", "agent_intent")
