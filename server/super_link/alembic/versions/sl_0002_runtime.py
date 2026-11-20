"""Exit witnesses, fixed evidence, independent inspection and execution acceptance."""

import sqlalchemy as sa
from alembic import op

revision = "sl_0002_runtime"
down_revision = "sl_0001_communication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "super_link_finalizations",
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id"), primary_key=True),
        sa.Column("worker_exited_at", sa.DateTime(timezone=True)),
        sa.Column("exit_code", sa.Integer()),
        sa.Column("expected_head_run_id", sa.Uuid()),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.CheckConstraint(
            "state IN ('executing', 'pending', 'ready', 'failed')", name="ck_sl_finalize"
        ),
    )
    op.create_table(
        "super_link_reviews",
        sa.Column(
            "message_id", sa.Uuid(), sa.ForeignKey("super_link_messages.id"), primary_key=True
        ),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("goal_version", sa.Integer(), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "verdict IN ('pass', 'caveat', 'block', 'incomplete')", name="ck_sl_review"
        ),
    )
    op.create_table(
        "super_link_executions",
        sa.Column(
            "message_id", sa.Uuid(), sa.ForeignKey("super_link_messages.id"), primary_key=True
        ),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id"), nullable=False, unique=True),
    )
    op.create_table(
        "super_link_evidence",
        sa.Column(
            "message_id", sa.Uuid(), sa.ForeignKey("super_link_messages.id"), primary_key=True
        ),
        sa.Column("rel_path", sa.String(500), primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("super_link_evidence")
    op.drop_table("super_link_executions")
    op.drop_table("super_link_reviews")
    op.drop_table("super_link_finalizations")
