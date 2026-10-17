"""Durable monitoring delivery and browser presence.

Revision ID: 0021_monitor_streams
Revises: 0020_default_investment_account
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0021_monitor_streams"
down_revision = "0020_default_investment_account"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "watch_rules",
        sa.Column("lifecycle_epoch", sa.Integer(), nullable=False, server_default="0"),
    )
    uid = postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite")
    dt = sa.DateTime(timezone=True)
    op.create_table(
        "monitor_presence",
        sa.Column("user_id", uid, sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("expires_at", dt, nullable=False),
        sa.Column("started_at", dt, nullable=False),
    )
    op.create_table(
        "monitor_targets",
        sa.Column("key", sa.String(200), primary_key=True),
        sa.Column("next_poll_at", dt, nullable=False),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_until", dt),
        sa.Column("last_error", sa.String(200)),
        sa.Column("last_poll_at", dt),
    )
    op.create_table(
        "monitor_messages",
        sa.Column("id", uid, primary_key=True),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", dt, nullable=False),
        sa.Column("published_at", dt),
        sa.Column("completed_at", dt),
        sa.Column("result", sa.JSON()),
        sa.Column("created_at", dt, nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_monitor_messages_delivery", "monitor_messages", ["channel", "state", "available_at"]
    )
    op.create_table(
        "monitor_workers",
        sa.Column("role", sa.String(32), primary_key=True),
        sa.Column("heartbeat_at", dt, nullable=False),
        sa.Column("last_error", sa.String(200)),
    )


def downgrade() -> None:
    op.drop_column("watch_rules", "lifecycle_epoch")
    for table in ("monitor_workers", "monitor_messages", "monitor_targets", "monitor_presence"):
        op.drop_table(table)
