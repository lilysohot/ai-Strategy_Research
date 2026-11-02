"""Link session fills to account cash without silently booking historical fills."""

import sqlalchemy as sa
from alembic import op

revision = "0025_session_cash_link"
down_revision = "0024_continuous_monitoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("buy_sell_plans", sa.Column("cash_effect", sa.Numeric(30, 10)))
    op.add_column("buy_sell_plan_revisions", sa.Column("fees", sa.Numeric(30, 10)))


def downgrade() -> None:
    op.drop_column("buy_sell_plan_revisions", "fees")
    op.drop_column("buy_sell_plans", "cash_effect")
