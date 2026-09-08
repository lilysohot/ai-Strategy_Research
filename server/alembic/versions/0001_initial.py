"""initial business schema

Revision ID: 0001_initial
Revises: 
Create Date: 2026-08-31

Creates users / user_llm_configs / sessions / runs / turns / artifacts /
audit_log per tech-stack.md §6.1. Trajectory files are NOT stored here (§6.2).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "user_llm_configs",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("api_key_cipher", sa.LargeBinary(), nullable=False),
        sa.Column("params_json", sa.JSON(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verify_ok", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_user_llm_configs_user_id", "user_llm_configs", ["user_id"])

    op.create_table(
        "sessions",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_sessions_user", "sessions", ["user_id", "updated_at"], unique=False
    )

    op.create_table(
        "runs",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("session_id", sa.UUID(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("pipeline_id", sa.String(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("final_answer", sa.Text(), nullable=True),
        sa.Column("stopped_by", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("llm_config_id", sa.UUID(), sa.ForeignKey("user_llm_configs.id"), nullable=True),
        sa.Column("llm_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("run_dir", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_runs_session", "runs", ["session_id", "created_at"], unique=False)

    op.create_table(
        "turns",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.UUID(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("run_id", sa.UUID(), sa.ForeignKey("runs.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_turns_session", "turns", ["session_id", "seq"], unique=True)

    op.create_table(
        "artifacts",
        sa.Column("run_id", sa.UUID(), sa.ForeignKey("runs.id"), primary_key=True, nullable=False),
        sa.Column("rel_path", sa.String(), primary_key=True, nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("detail_json", sa.JSON(), nullable=True),
        sa.Column("ip", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("artifacts")
    op.drop_index("idx_turns_session", table_name="turns")
    op.drop_table("turns")
    op.drop_index("idx_runs_session", table_name="runs")
    op.drop_table("runs")
    op.drop_index("idx_sessions_user", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_user_llm_configs_user_id", table_name="user_llm_configs")
    op.drop_table("user_llm_configs")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
