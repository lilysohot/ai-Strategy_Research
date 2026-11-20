"""Add isolated Super-link communication records; no legacy data conversion."""

import sqlalchemy as sa
from alembic import op

revision = "sl_0001_communication"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "super_link_spaces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("creation_key", sa.Uuid(), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("goal_version", sa.Integer(), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("user_id", "creation_key"),
    )
    op.create_table(
        "super_link_participants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("space_id", sa.Uuid(), sa.ForeignKey("super_link_spaces.id"), nullable=False),
        sa.Column(
            "session_id", sa.Uuid(), sa.ForeignKey("sessions.id"), nullable=False, unique=True
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.UniqueConstraint("space_id", "role"),
        sa.UniqueConstraint("id", "space_id"),
        sa.CheckConstraint("role IN ('team', 'single')", name="ck_super_link_role"),
    )
    op.create_table(
        "super_link_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("space_id", sa.Uuid(), sa.ForeignKey("super_link_spaces.id"), nullable=False),
        sa.Column("sender_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.Column("source_run_id", sa.Uuid(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("registration_key", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("in_reply_to", sa.Uuid()),
        sa.Column("goal_version", sa.Integer(), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("continuity_sha256", sa.String(64)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("source_run_id", "registration_key"),
        sa.UniqueConstraint("id", "space_id"),
        sa.ForeignKeyConstraint(
            ["sender_id", "space_id"],
            ["super_link_participants.id", "super_link_participants.space_id"],
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id", "space_id"],
            ["super_link_participants.id", "super_link_participants.space_id"],
        ),
        sa.ForeignKeyConstraint(
            ["in_reply_to", "space_id"],
            ["super_link_messages.id", "super_link_messages.space_id"],
        ),
        sa.CheckConstraint("sender_id <> recipient_id", name="ck_super_link_peer"),
        sa.CheckConstraint(
            "state IN ('registered', 'published')", name="ck_super_link_message_state"
        ),
    )
    op.create_index("ix_super_link_messages_request_id", "super_link_messages", ["request_id"])
    op.create_table(
        "super_link_outbox",
        sa.Column(
            "message_id", sa.Uuid(), sa.ForeignKey("super_link_messages.id"), primary_key=True
        ),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.CheckConstraint(
            "state IN ('pending', 'received', 'quarantined')", name="ck_super_link_outbox_state"
        ),
    )
    op.create_index("ix_super_link_outbox_pending", "super_link_outbox", ["state", "notified_at"])
    op.create_table(
        "super_link_receipts",
        sa.Column(
            "message_id", sa.Uuid(), sa.ForeignKey("super_link_messages.id"), primary_key=True
        ),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("state = 'awaiting_check'", name="ck_super_link_receipt_state"),
    )


def downgrade() -> None:
    # Explicit operator downgrade only; disabling collaboration never drops data.
    op.drop_table("super_link_receipts")
    op.drop_index("ix_super_link_outbox_pending", table_name="super_link_outbox")
    op.drop_table("super_link_outbox")
    op.drop_index("ix_super_link_messages_request_id", table_name="super_link_messages")
    op.drop_table("super_link_messages")
    op.drop_table("super_link_participants")
    op.drop_table("super_link_spaces")
