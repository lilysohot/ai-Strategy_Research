"""Persist one explicit default investment account per user.

Existing users are backfilled from their most recently updated non-archived
research/account binding. New users choose the value explicitly; the first
created account is selected automatically by the write service.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020_default_investment_account"
down_revision = "0019_session_conversations"
branch_labels = None
depends_on = None


def _uuid() -> sa.types.TypeEngine:
    return postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite")


def upgrade() -> None:
    op.create_table(
        "user_investment_preferences",
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("default_account_id", _uuid(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id", "default_account_id"],
            ["investment_accounts.user_id", "investment_accounts.id"],
            name="fk_user_investment_preferences_account_owner",
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )

    # Preserve the practical main account that the previous implementation used.
    # DISTINCT ON is intentional: production migrations target PostgreSQL.
    op.execute(
        sa.text(
            """
            INSERT INTO user_investment_preferences
                (user_id, default_account_id, updated_at)
            SELECT DISTINCT ON (link.user_id)
                link.user_id, link.account_id, CURRENT_TIMESTAMP
            FROM research_investment_links AS link
            JOIN investment_accounts AS account
              ON account.id = link.account_id
             AND account.user_id = link.user_id
            WHERE link.account_id IS NOT NULL
              AND account.archived = FALSE
            ORDER BY link.user_id, link.updated_at DESC, link.research_id DESC
            """
        )
    )


def downgrade() -> None:
    op.drop_table("user_investment_preferences")
