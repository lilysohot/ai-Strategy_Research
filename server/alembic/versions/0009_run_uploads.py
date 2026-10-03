"""run uploads: persistent manifest for staged attachments (DATA-06)

Revision ID: 0009_run_uploads
Revises: 0008_run_dispatch
Create Date: 2026-10-03

Attachment bytes are not part of a database transaction, but "which files were
uploaded, what is their content digest, and have they been published into the
run's read-only inputs" must be durable. Otherwise a run can be committed while
a worker starts against a missing or truncated input.

The manifest is written in the SAME transaction as the run/outbox (status
``staged``); the dispatcher verifies the staged bytes against the recorded
sha256 and only then publishes them into ``inputs`` (status ``published``)
before a worker is spawned.

Additive only; legacy runs simply have no rows here and keep direct dispatch.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_run_uploads"
down_revision = "0008_run_dispatch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_uploads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("stored_name", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "stored_name", name="uq_run_uploads_run_name"),
    )
    op.create_index("ix_run_uploads_run", "run_uploads", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_run_uploads_run", table_name="run_uploads")
    op.drop_table("run_uploads")
