"""Re-execute I5-1 scenarios on reset isolated databases and restore their prior contents."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
OLD = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260924-i51-scenarios"
BASE = OLD.parents[1]
SCHEMA = BASE / "i2/sandbox_schema.sql"
SCENARIOS = {
    "s1": ("i51_s1_rerun", "i51_s1_rerun.py"),
    "s2": ("i51_s2_srcchg", "i51_s2_srcchange.py"),
    "s3": ("i51_s3_newrule", "i51_s3_newrule.py"),
    "s4": ("i51_s4_idxreb", "i51_s4_idxreb.py"),
}
PROD_COUNTS = (
    "SELECT (SELECT count(*) FROM corpus.corpus_sources) AS sources,"
    " (SELECT count(*) FROM corpus.corpus_review_decisions) AS decisions,"
    " (SELECT count(*) FROM corpus.corpus_builds) AS builds,"
    " (SELECT count(*) FROM corpus.corpus_chunks) AS chunks,"
    " (SELECT count(*) FROM corpus.corpus_units) AS units,"
    " (SELECT count(*) FROM corpus.corpus_publications) AS publications,"
    " (SELECT count(*) FROM corpus.corpus_publications WHERE active_build_id IS NOT NULL) AS active"
)


def credentials() -> tuple[str, str]:
    values: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    user, password = values.get("CORPUS_DB_USER", ""), values.get("CORPUS_DB_PASSWORD", "")
    if not user or not password:
        raise SystemExit("CORPUS_DB_USER/CORPUS_DB_PASSWORD are required")
    return user, password


def dsn(user: str, password: str, port: int, database: str) -> str:
    return f"postgresql://{user}:{password}@127.0.0.1:{port}/{database}"


def strict_readonly_snapshot(dsn_value: str) -> dict[str, Any]:
    """Read production under one explicit read-only transaction, not autocommit."""
    with psycopg.connect(dsn_value) as connection, connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute("SHOW transaction_read_only")
        if cursor.fetchone()[0] != "on":
            raise SystemExit("production snapshot was not made read-only")
        cursor.execute(PROD_COUNTS)
        counts = dict(
            zip([column.name for column in cursor.description], cursor.fetchone(), strict=True)
        )
        cursor.execute(
            "SELECT s.source_id, p.active_build_id FROM corpus.corpus_publications p "
            "JOIN corpus.corpus_sources s ON s.source_id = p.source_id ORDER BY 1"
        )
        active = {row[0]: row[1] for row in cursor.fetchall()}
    return {"counts": counts, "active_by_source": active, "transaction_read_only": True}


def assert_isolated(admin_dsn: str, database: str) -> str:
    with psycopg.connect(admin_dsn) as connection:
        if connection.info.host != "127.0.0.1" or connection.info.port != 543:
            raise SystemExit("refuse a non-isolated PostgreSQL instance")
        names = {row[0] for row in connection.execute("SELECT datname FROM pg_database")}
        if "apodex" in names or "i0b2_verify_postgres" not in names or database not in names:
            raise SystemExit("refuse an unexpected isolated PostgreSQL target")
        return connection.info.user


def table_hashes(sandbox_dsn: str) -> dict[str, Any]:
    with psycopg.connect(sandbox_dsn, options="-c default_transaction_read_only=on") as connection:
        tables = connection.execute(
            "SELECT schemaname, tablename FROM pg_tables "
            "WHERE schemaname NOT IN ('pg_catalog', 'information_schema') ORDER BY 1, 2"
        ).fetchall()
        result: dict[str, Any] = {}
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


def reset_schema(sandbox_dsn: str) -> None:
    ddl = SCHEMA.read_text(encoding="utf-8")
    with psycopg.connect(sandbox_dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_database(), EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'zhcfg')"
        )
        database, zhcfg = cursor.fetchone()
        if database not in {value[0] for value in SCENARIOS.values()} or zhcfg is None:
            raise SystemExit("refuse reset: database/configuration mismatch")
        cursor.execute("DROP SCHEMA corpus CASCADE")
        cursor.execute(sql.SQL(ddl))


def rewritten_source(name: str, scenario_out: Path) -> str:
    source = (OLD / SCENARIOS[name][1]).read_text(encoding="utf-8")
    source = source.replace(
        "HERE = Path(__file__).resolve().parent", f"HERE = Path({str(scenario_out)!r})", 1
    )
    if name == "s1":
        source = source.replace(
            "len(stable) == 1 and len(churned) == 7  # F1 形态逐字符合预期",
            "len(stable) == 8 and len(churned) == 0  # F1 修复后必须全量稳定",
            1,
        )
    if name == "s4":
        start = source.index('        "parse_rev_same_only_md": (')
        end = source.index('        "run2_parse_rev_matches_expected_formula":', start)
        replacement = (
            '        "parse_rev_same_all_sources": all(\n'
            '            (row.get("revs") or {}).get("parse_rev_same") for row in run2_rows\n'
            "        ),\n"
        )
        source = source[:start] + replacement + source[end:]
        source = source.replace(
            'record["summary"]["parse_rev_same_only_md"]',
            'record["summary"]["parse_rev_same_all_sources"]',
        )
    return source


def execute(name: str) -> int:
    scenario_out = OUT / f"replay-{name}-post-f1"
    scenario_out.mkdir(exist_ok=True)
    sys.path.insert(0, str(OLD))
    import i51_common as common

    common.prod_readonly_snapshot = strict_readonly_snapshot
    namespace: dict[str, Any] = {
        "__name__": "__main__",
        "__file__": str(OLD / SCENARIOS[name][1]),
    }
    try:
        exec(
            compile(rewritten_source(name, scenario_out), namespace["__file__"], "exec"), namespace
        )
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def run_one(name: str) -> dict[str, Any]:
    database, _script = SCENARIOS[name]
    scenario_out = OUT / f"replay-{name}-post-f1"
    scenario_out.mkdir(exist_ok=True)
    user, password = credentials()
    sandbox_dsn = dsn(user, password, 543, database)
    admin_dsn = dsn(user, password, 543, "postgres")
    prod_dsn = dsn(user, password, 5432, "postgres")
    database_user = assert_isolated(admin_dsn, database)
    before = table_hashes(sandbox_dsn)
    (scenario_out / "sandbox-before.json").write_text(
        json.dumps(before, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    dump = scenario_out / "sandbox-before.dump"
    with dump.open("xb") as stream:
        subprocess.run(
            ["docker", "exec", "corpus-db", "pg_dump", "-U", database_user, "-Fc", database],
            stdout=stream,
            check=True,
            timeout=180,
        )
    prod_pre = strict_readonly_snapshot(prod_dsn)
    exit_code: int | None = None
    restore_error: str | None = None
    try:
        reset_schema(sandbox_dsn)
        child = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--execute", name],
            cwd=ROOT,
            env={
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "LANG": "C.UTF-8",
                "PYTHONPATH": str(ROOT),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=1800,
        )
        exit_code = child.returncode
        (scenario_out / "execution.log").write_text(child.stdout, encoding="utf-8")
    finally:
        with dump.open("rb") as stream:
            restored = subprocess.run(
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
                    database,
                ],
                stdin=stream,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=240,
            )
        (scenario_out / "sandbox-restore.log").write_text(restored.stdout, encoding="utf-8")
        if restored.returncode:
            restore_error = restored.stdout[-1000:]
    after = table_hashes(sandbox_dsn)
    prod_post = strict_readonly_snapshot(prod_dsn)
    record = {
        "scenario": name,
        "scenario_database": database,
        "execution_exit_code": exit_code,
        "sandbox_restored_exact_table_contents": before == after,
        "production_readonly_pre_post_equal": prod_pre == prod_post,
        "production_snapshot_readonly": prod_pre["transaction_read_only"]
        and prod_post["transaction_read_only"],
        "sandbox_dump_sha256": hashlib.sha256(dump.read_bytes()).hexdigest(),
        "restore_error": restore_error,
    }
    (scenario_out / "wrapper-results.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if exit_code != 0 or before != after or restore_error or prod_pre != prod_post:
        raise SystemExit(1)
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=SCENARIOS, nargs="?")
    parser.add_argument("--execute", choices=SCENARIOS)
    args = parser.parse_args()
    if args.execute:
        return execute(args.execute)
    names = [args.scenario] if args.scenario else list(SCENARIOS)
    results = [run_one(name) for name in names]
    (OUT / "i51-replay-summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
