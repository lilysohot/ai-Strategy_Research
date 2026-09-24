"""Run the new-chain consumer regression on the isolated PG sandbox and restore it exactly."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
OLD = (
    ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i37-final-reverify"
)
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("i37_runner", OLD / "run_tests.py")
if spec is None or spec.loader is None:
    raise SystemExit("cannot load the isolated-PG lane helper")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
runner.HERE = OUT

dsn = runner.build_dsn()
admin_dsn = f"postgresql://{runner.build_admin_cred()}@127.0.0.1:543/postgres"
with psycopg.connect(admin_dsn) as connection:
    if connection.info.host != "127.0.0.1" or connection.info.port != 543:
        raise SystemExit("refuse non-isolated PostgreSQL target")
    names = {row[0] for row in connection.execute("SELECT datname FROM pg_database")}
    if "apodex" in names or "i0b2_verify_postgres" not in names:
        raise SystemExit("refuse unexpected PostgreSQL instance")
    database_user = connection.info.user


def snapshot() -> dict[str, object]:
    """Hash every non-system table via a read-only connection."""
    with psycopg.connect(dsn, options="-c default_transaction_read_only=on") as connection:
        tables = connection.execute(
            "SELECT schemaname, tablename FROM pg_tables "
            "WHERE schemaname NOT IN ('pg_catalog', 'information_schema') ORDER BY 1, 2"
        ).fetchall()
        result: dict[str, object] = {}
        for schema_name, table_name in tables:
            statement = sql.SQL(
                "SELECT row_to_json(row)::text FROM {}.{} row ORDER BY row_to_json(row)::text"
            ).format(sql.Identifier(schema_name), sql.Identifier(table_name))
            rows = connection.execute(statement).fetchall()
            result[f"{schema_name}.{table_name}"] = {
                "count": len(rows),
                "sha256": hashlib.sha256(json.dumps(rows).encode()).hexdigest(),
            }
        return result


before = snapshot()
(OUT / "sandbox-before.json").write_text(json.dumps(before, indent=2), encoding="utf-8")
dump = OUT / "sandbox-before.dump"
with dump.open("xb") as stream:
    subprocess.run(
        ["docker", "exec", "corpus-db", "pg_dump", "-U", database_user, "-Fc", "i2_sandbox_corpus"],
        stdout=stream,
        check=True,
        timeout=120,
    )

environment = runner.lane_env(guard=runner.GUARD_I2V, dsn=dsn)
environment.update(
    CORPUS_TARGET_DB="",
    CORPUS_DSN="postgresql://disabled:disabled@127.0.0.1:1/disabled?connect_timeout=1",
    PYTHON_DOTENV_DISABLED="1",
)
result: dict[str, object] | None = None
restore_error: str | None = None
try:
    result = runner.run_lane(
        "i5-consumers-pg",
        ["tests/test_corpus_consumers_pg.py"],
        environment,
    )
finally:
    with dump.open("rb") as stream:
        restore = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                "corpus-db",
                "pg_restore",
                "-U",
                database_user,
                "--clean",
                "--if-exists",
                "--exit-on-error",
                "-d",
                "i2_sandbox_corpus",
            ],
            stdin=stream,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=180,
        )
    (OUT / "sandbox-restore.log").write_text(restore.stdout, encoding="utf-8")
    if restore.returncode:
        restore_error = restore.stdout[-1000:]

after = snapshot()
report = {
    "lane": result,
    "sandbox_restored_exact_table_contents": before == after,
    "dump_sha256": hashlib.sha256(dump.read_bytes()).hexdigest(),
    "restore_error": restore_error,
}
(OUT / "consumers-pg-results.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
if restore_error or before != after or result is None or result["exit_code"] != 0:
    raise SystemExit(1)
