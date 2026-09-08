"""run usage metering columns

Revision ID: 0002_run_usage
Revises: 0001_initial
Create Date: 2026-09-01

Adds the T2.11 token-metering columns to ``runs``. Usage is aggregated from the
runtime trajectory (``react_agent.jsonl``) at each run's terminal state, so no
new table is needed — the counters live next to the run they meter.

``cache_read_tokens`` (cache hit) and ``cache_write_tokens`` (cache creation)
are stored separately because they bill at different rates; collapsing them
under-attributes write spend on Anthropic.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_run_usage"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("cache_read_tokens", sa.Integer(), nullable=True))
    op.add_column("runs", sa.Column("cache_write_tokens", sa.Integer(), nullable=True))
    op.add_column("runs", sa.Column("reasoning_tokens", sa.Integer(), nullable=True))
    op.add_column("runs", sa.Column("llm_calls", sa.Integer(), nullable=True))
    op.add_column("runs", sa.Column("usage_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "usage_json")
    op.drop_column("runs", "llm_calls")
    op.drop_column("runs", "reasoning_tokens")
    op.drop_column("runs", "cache_write_tokens")
    op.drop_column("runs", "cache_read_tokens")
