"""business operations: idempotent write ledger

Revision ID: 0006_business_operations
Revises: 0005_business_objects
Create Date: 2026-10-02

DATA-03 / PR-BIZ-04. A save that times out leaves the client unable to tell
"never arrived" from "already written", and the honest retry — sending it again —
is exactly what creates a duplicate version or a second Run. This table is what
makes the retry safe: ``(user_id, idempotency_key)`` is unique, the request
digest is stored next to it, and the original result is kept so a page that lost
its response can look the operation up by id (no business payload needed).

Additive only: no table or column from 0001—0005 is touched.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_business_operations"
down_revision = "0005_business_objects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "business_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("request_digest", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="in_progress", nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        # 同键只认一次：第二次写入在此处失败，而不是再产生一个版本。
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_business_operations_key"),
    )
    op.create_index(
        "ix_business_operations_user_recent",
        "business_operations",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_business_operations_user_recent", table_name="business_operations")
    op.drop_table("business_operations")
