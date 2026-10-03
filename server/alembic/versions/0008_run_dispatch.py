"""run dispatch outbox: persistent, lease-claimed run dispatch (DATA-06)

Revision ID: 0008_run_dispatch
Revises: 0007_run_snapshot
Create Date: 2026-10-03

A business submit must not depend on the API process staying alive between
"run row committed" and "worker spawned": a crash in between left runs queued
forever with nothing referencing why. The outbox row is written in the SAME
transaction as the run/snapshot/turn, so a committed submit always has a
resumable dispatch intent, and dispatch itself becomes recoverable state with
leases and a claim version instead of an in-memory side effect.

Additive only; existing (non-business) runs simply have no row here and keep
their direct in-process dispatch.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_run_dispatch"
down_revision = "0007_run_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_dispatch_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("research_id", sa.Uuid(), nullable=False),
        sa.Column("session_key", sa.String(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("prompt_addendum", sa.Text(), nullable=True),
        sa.Column("agent_tools", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_version", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["research_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_run_dispatch_outbox_run"),
    )
    op.create_index("ix_run_dispatch_due", "run_dispatch_outbox", ["status", "next_attempt_at"])
    op.create_index("ix_run_dispatch_research", "run_dispatch_outbox", ["research_id"])


def downgrade() -> None:
    op.drop_index("ix_run_dispatch_research", table_name="run_dispatch_outbox")
    op.drop_index("ix_run_dispatch_due", table_name="run_dispatch_outbox")
    op.drop_table("run_dispatch_outbox")
