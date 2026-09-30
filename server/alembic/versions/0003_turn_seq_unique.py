"""unique turn sequence per session

Revision ID: 0003_turn_seq_unique
Revises: 0002_run_usage
Create Date: 2026-09-30

F16. ``turns.seq`` is the transcript position and is allocated as
``MAX(seq)+1`` inside ``server.store.append_turn``. Two writers of the same
session can read the same maximum before either commits, and the schema had
nothing to stop both rows from landing — the conversation then contained two
messages at the same position (reproduced by the storage-chain audit).

A UNIQUE index is used rather than a table constraint because it is the form
both SQLite (which cannot ``ALTER TABLE ... ADD CONSTRAINT``) and PostgreSQL
can add to an existing table, so the ORM declaration and this migration create
the same object. ``append_turn`` retries once the index rejects the loser.

Pre-flight: duplicates already in the table would make the index creation fail
with an opaque error, so they are reported explicitly here instead. This
migration never rewrites existing rows — deciding how to renumber a real
transcript is an operator decision, not a migration side effect.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_turn_seq_unique"
down_revision = "0002_run_usage"
branch_labels = None
depends_on = None

_INDEX_NAME = "uq_turns_session_seq"


def upgrade() -> None:
    duplicates = op.get_bind().execute(
        sa.text(
            "SELECT session_id, seq, COUNT(*) AS n FROM turns "
            "GROUP BY session_id, seq HAVING COUNT(*) > 1"
        )
    ).fetchall()
    if duplicates:
        sample = ", ".join(f"{row[0]}:{row[1]}x{row[2]}" for row in duplicates[:5])
        raise RuntimeError(
            f"refusing to create {_INDEX_NAME}: {len(duplicates)} session/seq pairs "
            f"already hold duplicate turns ({sample}). Renumber or remove them first; "
            "this migration will not rewrite a real transcript."
        )
    op.create_index(_INDEX_NAME, "turns", ["session_id", "seq"], unique=True)


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="turns")
