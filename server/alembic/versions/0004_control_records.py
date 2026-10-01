"""control records for steer / approval traceability

Revision ID: 0004_control_records
Revises: 0003_turn_seq_unique
Create Date: 2026-10-01

F21. A mid-run steer and a tool-call approval verdict were both in-memory
events: the SSE frame was the only record that they ever happened, so "received",
"queued" and "actually took effect" could not be told apart afterwards, and a
page refresh lost a parked approval entirely. This adds the table that persists
who acted, on which run, in what state, and where the action landed.

The table is additive — no existing column or row is touched — so the only
pre-flight is that ``runs`` / ``sessions`` / ``users`` already exist (they do:
this revision follows the initial schema).

Deployment note: ``init_db()``'s ``create_all`` will NOT add this table to an
existing database. Run ``alembic upgrade head`` once (0003 and 0004 together).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_control_records"
down_revision = "0003_turn_seq_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "control_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=True),
        sa.Column("decision", sa.String(), nullable=True),
        sa.Column("replacement_command", sa.Text(), nullable=True),
        sa.Column("adopted_turn_seq", sa.Integer(), nullable=True),
        sa.Column("detail_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        # One row per worker-side approval id: a retried decision updates that
        # row instead of appending a second verdict.
        sa.UniqueConstraint("kind", "external_id", name="uq_control_records_kind_external"),
    )
    op.create_index("ix_control_records_run_id", "control_records", ["run_id"])
    op.create_index(
        "ix_control_records_session_status", "control_records", ["session_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_control_records_session_status", table_name="control_records")
    op.drop_index("ix_control_records_run_id", table_name="control_records")
    op.drop_table("control_records")
