"""Add the B-phase durable business-event notification stream (DATA-12)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_business_events"
down_revision = "0011_input_requests"
branch_labels = None
depends_on = None


def _uuid() -> sa.types.TypeEngine:
    return postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite")


def upgrade() -> None:
    op.create_table(
        "business_events",
        sa.Column(
            "cursor",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("research_id", _uuid(), nullable=False),
        sa.Column("request_id", _uuid()),
        sa.Column("run_id", _uuid()),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("detail_json", sa.JSON(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["research_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["request_id"], ["input_requests.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("cursor"),
        sa.UniqueConstraint("id", name="uq_business_events_id"),
    )
    op.create_index("ix_business_events_user_cursor", "business_events", ["user_id", "cursor"])


def downgrade() -> None:
    op.drop_index("ix_business_events_user_cursor", table_name="business_events")
    op.drop_table("business_events")
