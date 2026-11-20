"""Durable space lifecycle and stale-command fencing; retain all research records."""

import sqlalchemy as sa
from alembic import op

revision = "sl_0005_controls"
down_revision = "sl_0004_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "super_link_spaces",
        sa.Column(
            "control_state",
            sa.String(16),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "super_link_spaces",
        sa.Column(
            "control_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column("super_link_spaces", sa.Column("delivery_cutoff", sa.DateTime(timezone=True)))
    op.execute("UPDATE super_link_spaces SET control_state = 'paused' WHERE paused = true")


def downgrade() -> None:
    for name in ("delivery_cutoff", "control_version", "control_state"):
        op.drop_column("super_link_spaces", name)
