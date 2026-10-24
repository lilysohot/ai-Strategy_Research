"""Archive immutable context source material for every committed Run.

Revision ID: 0022_run_context_sources
Revises: 0021_monitor_streams
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0022_run_context_sources"
down_revision = "0021_monitor_streams"
branch_labels = None
depends_on = None


def _uuid() -> sa.types.TypeEngine:
    return postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite")


def upgrade() -> None:
    op.create_table(
        "run_context_sources",
        sa.Column("run_id", _uuid(), nullable=False),
        sa.Column("session_id", _uuid(), nullable=False),
        sa.Column("pipeline_id", sa.String(), nullable=False, server_default=""),
        sa.Column("native_payload", sa.Text(), nullable=False),
        sa.Column("native_sha256", sa.String(length=64), nullable=False),
        sa.Column("portable_payload", sa.Text()),
        sa.Column("portable_sha256", sa.String(length=64)),
        sa.Column("completeness_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index(
        "ix_run_context_sources_session_id",
        "run_context_sources",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_run_context_sources_session_id", table_name="run_context_sources")
    op.drop_table("run_context_sources")
