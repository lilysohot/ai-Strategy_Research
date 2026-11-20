"""Persistent event ledger with per-space sequence heads.

Adds only optional tables; existing spaces receive a baseline head in the same upgrade.
"""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "sl_0006_events"
down_revision = "sl_0005_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "super_link_event_heads",
        sa.Column(
            "space_id",
            sa.UUID(),
            sa.ForeignKey("super_link_spaces.id"),
            primary_key=True,
        ),
        sa.Column("stream_epoch", sa.UUID(), nullable=False),
        sa.Column("last_seq", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("min_after", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_table(
        "super_link_events",
        sa.Column(
            "space_id",
            sa.UUID(),
            sa.ForeignKey("super_link_event_heads.space_id"),
            primary_key=True,
        ),
        sa.Column("stream_epoch", sa.UUID(), primary_key=True),
        sa.Column("seq", sa.BigInteger(), primary_key=True),
        sa.Column("event_id", sa.UUID(), nullable=False, unique=True),
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column("change_key", sa.String(200), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_kind", sa.String(32), nullable=False, server_default="space"),
        sa.Column("source_id", sa.String(64)),
        sa.Column("participant_id", sa.UUID()),
        sa.Column("session_id", sa.UUID()),
        sa.Column("run_id", sa.UUID()),
        sa.Column("data_json", sa.JSON(), nullable=False),
        sa.Column("invalidate_json", sa.JSON(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("notified_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "space_id", "stream_epoch", "change_key", name="uq_sl_events_change_key"
        ),
    )
    op.create_index(
        "ix_super_link_events_pending",
        "super_link_events",
        ["notified_at", "space_id", "stream_epoch", "seq"],
    )

    bind = op.get_bind()
    spaces = sa.table("super_link_spaces", sa.column("id", sa.Uuid()))
    heads = sa.table(
        "super_link_event_heads",
        sa.column("space_id", sa.Uuid()),
        sa.column("stream_epoch", sa.Uuid()),
        sa.column("last_seq", sa.BigInteger()),
        sa.column("min_after", sa.BigInteger()),
    )
    for (space_id,) in bind.execute(sa.select(spaces.c.id)):
        bind.execute(
            heads.insert().values(
                space_id=space_id,
                stream_epoch=uuid.uuid4(),
                last_seq=0,
                min_after=0,
            )
        )


def downgrade() -> None:
    op.drop_index("ix_super_link_events_pending", table_name="super_link_events")
    op.drop_table("super_link_events")
    op.drop_table("super_link_event_heads")
