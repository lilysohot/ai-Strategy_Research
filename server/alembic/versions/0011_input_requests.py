"""Add durable input requests and append-only answer history (DATA-07)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_input_requests"
down_revision = "0010_business_history"
branch_labels = None
depends_on = None


def _uuid() -> sa.types.TypeEngine:
    return postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite")


def upgrade() -> None:
    op.create_table(
        "input_requests",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("research_id", _uuid(), nullable=False),
        sa.Column("source_run_id", _uuid()),
        sa.Column("watch_event_id", _uuid()),
        sa.Column("follow_up_run_id", _uuid()),
        sa.Column("use_case", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("fields_json", sa.JSON(), nullable=False),
        sa.Column("known_versions_json", sa.JSON(), nullable=False),
        sa.Column("continuation_json", sa.JSON(), nullable=False),
        sa.Column("collected_json", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("answered_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["research_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["source_run_id"], ["runs.id"]),
        sa.ForeignKeyConstraint(["follow_up_run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("follow_up_run_id"),
    )
    op.create_index(
        "ix_input_requests_user_status", "input_requests", ["user_id", "status", "created_at"]
    )
    op.create_index("ix_input_requests_research", "input_requests", ["research_id", "created_at"])
    op.create_table(
        "input_request_answers",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("request_id", _uuid(), nullable=False),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("declared_json", sa.JSON(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("operation_id", _uuid()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["request_id"], ["input_requests.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["operation_id"], ["business_operations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", "revision", name="uq_input_request_answer_revision"),
    )
    op.create_index(
        "ix_input_request_answers_request", "input_request_answers", ["request_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_input_request_answers_request", table_name="input_request_answers")
    op.drop_table("input_request_answers")
    op.drop_index("ix_input_requests_research", table_name="input_requests")
    op.drop_index("ix_input_requests_user_status", table_name="input_requests")
    op.drop_table("input_requests")
