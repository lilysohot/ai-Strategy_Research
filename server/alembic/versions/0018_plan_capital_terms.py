"""DATA-02 会话计划口径：规划资金与期望盈利；计划价列 deprecated。

- ``investment_plan_revisions`` 追加 ``allocated_capital``（本标的规划资金，NUMERIC(30,10)）、
  ``target_profit_value``（NUMERIC(30,10)）与 ``target_profit_unit``。
- ``plan_price``/``plan_price_low``/``plan_price_high`` 保留但不再写入（deprecated）：
  删除列会破坏不可变历史版本，物理清理另议（见 .scratch/web-business-session-plan/spec.md）。
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_plan_capital_terms"
down_revision = "0017_business_notifications"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(precision=30, scale=10, asdecimal=True)


def upgrade() -> None:
    op.add_column("investment_plan_revisions", sa.Column("allocated_capital", MONEY, nullable=True))
    op.add_column(
        "investment_plan_revisions", sa.Column("target_profit_value", MONEY, nullable=True)
    )
    op.add_column(
        "investment_plan_revisions", sa.Column("target_profit_unit", sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("investment_plan_revisions", "target_profit_unit")
    op.drop_column("investment_plan_revisions", "target_profit_value")
    op.drop_column("investment_plan_revisions", "allocated_capital")
