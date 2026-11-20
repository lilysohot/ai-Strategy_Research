"""Auditable inspection attempts, revisions, correction dispatch and bounded recovery."""

import sqlalchemy as sa
from alembic import op

revision = "sl_0004_recovery"
down_revision = "sl_0003_reliability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("super_link_spaces", sa.Column("automatic_run_limit", sa.Integer()))
    op.add_column("super_link_messages", sa.Column("revises_message_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_sl_revision_space",
        "super_link_messages",
        "super_link_messages",
        ["revises_message_id", "space_id"],
        ["id", "space_id"],
    )
    for name, default in (("recovery_attempts", "0"), ("recovery_limit", "3")):
        op.add_column(
            "super_link_finalizations",
            sa.Column(name, sa.Integer(), nullable=False, server_default=default),
        )
    op.add_column("super_link_finalizations", sa.Column("process_identity", sa.JSON()))
    for name, default in (
        ("admission_attempts", "0"),
        ("admission_limit", "3"),
        ("attempt_count", "0"),
        ("attempt_limit", "3"),
    ):
        op.add_column(
            "super_link_reviews",
            sa.Column(name, sa.Integer(), nullable=False, server_default=default),
        )
    op.add_column(
        "super_link_reviews",
        sa.Column("admission_held", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    for name in ("lease_until", "retry_at"):
        op.add_column("super_link_reviews", sa.Column(name, sa.DateTime(timezone=True)))
    op.add_column("super_link_reviews", sa.Column("failure_kind", sa.String(24)))
    op.create_table(
        "super_link_review_attempts",
        sa.Column(
            "message_id", sa.Uuid(), sa.ForeignKey("super_link_messages.id"), primary_key=True
        ),
        sa.Column("number", sa.Integer(), primary_key=True),
        sa.Column("reviewer", sa.String(200), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("model_snapshot", sa.JSON()),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("failure_kind", sa.String(24)),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "super_link_feedback",
        sa.Column(
            "message_id", sa.Uuid(), sa.ForeignKey("super_link_messages.id"), primary_key=True
        ),
        sa.Column("review_number", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id"), unique=True),
        sa.Column("error_code", sa.String(64)),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
        sa.Column("attempted_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt_limit", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("held", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "super_link_recovery_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("space_id", sa.Uuid(), sa.ForeignKey("super_link_spaces.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("space_id", "idempotency_key"),
    )
    # Preserve pre-upgrade decisions as version 1, explicitly without invented inputs.
    op.execute("""UPDATE super_link_reviews SET attempt_count = 1,
        failure_kind = CASE WHEN explanation IN ('inspection_pending','inspection_failed')
        THEN 'technical' WHEN verdict IN ('block','incomplete') THEN 'business' ELSE NULL END""")
    op.execute("""INSERT INTO super_link_review_attempts
        (message_id, number, reviewer, input_json, verdict, explanation, failure_kind, started_at, finished_at)
        SELECT message_id, 1, reviewer, '{}', verdict, explanation, failure_kind, created_at, CURRENT_TIMESTAMP
        FROM super_link_reviews""")
    op.execute("""UPDATE super_link_reviews SET retry_at = CURRENT_TIMESTAMP,
        explanation = 'inspection_interrupted_upgrade'
        WHERE failure_kind = 'technical'""")


def downgrade() -> None:
    for table in (
        "super_link_recovery_actions",
        "super_link_feedback",
        "super_link_review_attempts",
    ):
        op.drop_table(table)
    for column in (
        "admission_attempts",
        "admission_limit",
        "admission_held",
        "attempt_count",
        "attempt_limit",
        "lease_until",
        "retry_at",
        "failure_kind",
    ):
        op.drop_column("super_link_reviews", column)
    for column in ("recovery_attempts", "recovery_limit", "process_identity"):
        op.drop_column("super_link_finalizations", column)
    op.drop_constraint("fk_sl_revision_space", "super_link_messages", type_="foreignkey")
    op.drop_column("super_link_messages", "revises_message_id")
    op.drop_column("super_link_spaces", "automatic_run_limit")
