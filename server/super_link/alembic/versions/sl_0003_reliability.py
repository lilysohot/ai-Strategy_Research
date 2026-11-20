"""Fair background retries and frozen informational inbox visibility."""

import sqlalchemy as sa
from alembic import op

revision = "sl_0003_reliability"
down_revision = "sl_0002_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("super_link_finalizations", sa.Column("retry_at", sa.DateTime(timezone=True)))
    op.add_column("super_link_finalizations", sa.Column("attempted_at", sa.DateTime(timezone=True)))
    op.add_column("super_link_reviews", sa.Column("admission_retry_at", sa.DateTime(timezone=True)))
    op.add_column(
        "super_link_reviews", sa.Column("admission_attempted_at", sa.DateTime(timezone=True))
    )
    op.add_column("super_link_reviews", sa.Column("admission_error", sa.String(64)))
    op.create_table(
        "super_link_inbox_access",
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id"), primary_key=True),
        sa.Column(
            "message_id", sa.Uuid(), sa.ForeignKey("super_link_messages.id"), primary_key=True
        ),
    )


def downgrade() -> None:
    op.drop_table("super_link_inbox_access")
    for column in ("admission_error", "admission_attempted_at", "admission_retry_at"):
        op.drop_column("super_link_reviews", column)
    for column in ("attempted_at", "retry_at"):
        op.drop_column("super_link_finalizations", column)
