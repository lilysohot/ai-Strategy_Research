"""DATA-12 C: notification levels, dedup, hidden, and per-user settings.

- ``business_events`` 追加：``level``（low/medium/high/urgent）、``dedup_key``（per-user
  唯一，可空 = 不参与去重）、``hidden``（隐藏只是视图动作）。
- 新增 ``notification_settings``：每用户按类型/等级开关（默认全开）。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017_business_notifications"
down_revision = "0016_watch_auto_analysis"
branch_labels = None
depends_on = None


def _uuid() -> sa.types.TypeEngine:
    return postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite")


def upgrade() -> None:
    op.add_column(
        "business_events",
        sa.Column("level", sa.String(), nullable=False, server_default="medium"),
    )
    op.add_column("business_events", sa.Column("dedup_key", sa.String()))
    op.add_column(
        "business_events",
        sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_unique_constraint(
        "uq_business_events_dedup", "business_events", ["user_id", "dedup_key"]
    )

    op.create_table(
        "notification_settings",
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("muted_kinds_json", sa.JSON(), nullable=False),
        sa.Column("muted_levels_json", sa.JSON(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("notification_settings")
    op.drop_constraint("uq_business_events_dedup", "business_events", type_="unique")
    op.drop_column("business_events", "hidden")
    op.drop_column("business_events", "dedup_key")
    op.drop_column("business_events", "level")
