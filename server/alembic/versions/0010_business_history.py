"""Protect immutable business revisions and Run snapshots from UPDATE/DELETE."""

from alembic import op

revision = "0010_business_history"
down_revision = "0009_run_uploads"
branch_labels = None
depends_on = None

TABLES = ("investment_account_revisions", "investment_plan_revisions", "run_investment_snapshots")


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION reject_business_history_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN
              RAISE EXCEPTION 'business history is immutable' USING ERRCODE = '23514';
            END $$
        """)
        for table in TABLES:
            op.execute(
                f"CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION reject_business_history_mutation()"
            )
    else:
        for table in TABLES:
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action.lower()} "
                    f"BEFORE {action} ON {table} BEGIN "
                    "SELECT RAISE(ABORT, 'business history is immutable'); END"
                )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in TABLES:
            op.execute(f"DROP TRIGGER immutable_history ON {table}")
        op.execute("DROP FUNCTION reject_business_history_mutation()")
    else:
        for table in TABLES:
            for action in ("update", "delete"):
                op.execute(f"DROP TRIGGER IF EXISTS immutable_{table}_{action}")
