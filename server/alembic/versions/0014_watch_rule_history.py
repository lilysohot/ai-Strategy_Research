"""Protect immutable WatchRuleRevision rows from UPDATE/DELETE (DATA-09).

0010 只保护账户/计划版本与 Run 快照；规则版本同样"只 INSERT"，改版不复用旧版
报价基线与触发资格，任何 UPDATE/DELETE 都意味着改写已冻结的触发语义（契约 §9）。
沿用 0010 的触发器形态，单列为独立迁移以免改动已发布的 0010。
"""

from alembic import op

revision = "0014_watch_rule_history"
down_revision = "0013_watch_rules"
branch_labels = None
depends_on = None

TABLE = "watch_rule_revisions"


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # ``reject_business_history_mutation`` 由 0010 创建且先于本迁移执行；
        # 这里只补该表自身的触发器，不重复建函数。
        op.execute(
            f"CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON {TABLE} "
            "FOR EACH ROW EXECUTE FUNCTION reject_business_history_mutation()"
        )
    else:
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER IF NOT EXISTS immutable_{TABLE}_{action.lower()} "
                f"BEFORE {action} ON {TABLE} BEGIN "
                "SELECT RAISE(ABORT, 'business history is immutable'); END"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP TRIGGER immutable_history ON {TABLE}")
    else:
        for action in ("update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS immutable_{TABLE}_{action}")
