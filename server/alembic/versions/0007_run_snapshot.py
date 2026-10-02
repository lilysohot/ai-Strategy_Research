"""run investment snapshots: frozen business input per Run

Revision ID: 0007_run_snapshot
Revises: 0006_business_operations
Create Date: 2026-10-03

DATA-05. A Run must not read the account/plan "as of whenever the worker gets
around to it" — by then the user may have corrected their capital, and the
analysis would silently use numbers the user never submitted (AC-06/07/27).
This table freezes, at submission time, which object versions were used and the
resolved effective values. Rows are INSERT-only: a rerun creates a NEW run with
a NEW snapshot and points back at the old run via ``rerun_of_run_id``; the old
trajectory and the old snapshot stay as they were.

Additive only: no table or column from 0001—0006 is touched, and existing runs
simply have no row here — which is exactly the "legacy run, no snapshot" state
the read endpoint must report (never backfilled from current data).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_run_snapshot"
down_revision = "0006_business_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_investment_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("research_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("use_case", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("account_revision", sa.Integer(), nullable=True),
        sa.Column("plan_id", sa.Uuid(), nullable=True),
        sa.Column("plan_revision", sa.Integer(), nullable=True),
        sa.Column("position_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("trade_record_id", sa.Uuid(), nullable=True),
        sa.Column("rerun_of_run_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_json", sa.JSON(), nullable=False),
        sa.Column("missing_json", sa.JSON(), nullable=True),
        sa.Column("declared_json", sa.JSON(), nullable=True),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["research_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["investment_accounts.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["investment_plans.id"]),
        sa.ForeignKeyConstraint(["position_snapshot_id"], ["position_snapshots.id"]),
        sa.ForeignKeyConstraint(["trade_record_id"], ["trade_records.id"]),
        sa.ForeignKeyConstraint(["rerun_of_run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_run_investment_snapshots_run"),
    )
    op.create_index(
        "ix_run_snapshots_research", "run_investment_snapshots", ["research_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_run_snapshots_research", table_name="run_investment_snapshots")
    op.drop_table("run_investment_snapshots")
