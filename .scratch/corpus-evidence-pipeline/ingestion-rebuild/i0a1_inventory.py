"""I0A-1 在线只读盘点（PG 原库）。

纪律（任务清单 I0A-1 / v1.1 §12.4）：
- 零 DDL/DML：仅系统目录与应用表 SELECT；连接层强制 default_transaction_read_only=on 兜底。
- 先装守卫再连接：guard.install(i0-inventory) + DSN host/port 必须命中 allowed_targets，否则拒绝运行。
- 连接串经显式环境变量 CORPUS_INVENTORY_DSN 传入，不读 CORPUS_DSN（守卫投毒）。
- 输出 findings JSON 不含任何凭据（DSN 仅记 host/port/db/user）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GUARD_CONFIG = _REPO_ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i0-inventory.json"


def _fail(msg: str) -> NoReturn:
    print(f"I0A-1 盘点拒绝执行: {msg}", file=sys.stderr)
    raise SystemExit(2)


def main() -> None:
    parser = argparse.ArgumentParser(description="I0A-1 read-only PG inventory")
    parser.add_argument("--out", required=True, help="findings JSON 输出路径")
    parser.add_argument(
        "--dsn-env",
        default="CORPUS_INVENTORY_DSN",
        help="承载显式盘点连接串的环境变量名（默认 CORPUS_INVENTORY_DSN）",
    )
    args = parser.parse_args()

    dsn = os.environ.get(args.dsn_env, "").strip()
    if not dsn:
        _fail(f"环境变量 {args.dsn_env} 未设置；盘点连接串必须显式传入，禁止读 CORPUS_DSN/.env")

    # 先装守卫（投毒 CORPUS_DSN、禁模型模块、装网络 audit hook），再校验目标命中放行清单。
    from plugins.corpus.preparation import guard

    cfg = guard.install(_GUARD_CONFIG)

    from psycopg.conninfo import conninfo_to_dict

    dsn_parts = conninfo_to_dict(dsn)
    host = dsn_parts.get("host") or "localhost"
    port_raw = dsn_parts.get("port") or 5432
    port = int(port_raw)
    approved = {(h, p) for h, p in cfg.allowed_targets}
    if (host, port) not in approved:
        _fail(f"目标 {host}:{port} 不在守卫阶段 {cfg.phase} 的 allowed_targets {sorted(approved)} 中")

    import psycopg
    from psycopg.rows import dict_row

    findings: dict[str, Any] = {
        "artifact": "i0a1-inventory-findings.json",
        "task": "I0A-1 在线只读盘点",
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "guard": {
            "phase": cfg.phase,
            "config": str(_GUARD_CONFIG),
            "config_sha256": hashlib.sha256(_GUARD_CONFIG.read_bytes()).hexdigest(),
        },
        "target": {
            "host": host,
            "port": port,
            "database": dsn_parts.get("dbname"),
            "user": dsn_parts.get("user"),
            "note": "凭据不出现在本文件",
        },
        "errors": [],
    }

    def _collect(cursor: Any, key: str, sql: str, params: tuple = ()) -> None:
        try:
            cursor.execute(sql, params or None)
            findings[key] = cursor.fetchall()
        except Exception as exc:  # noqa: BLE001 - 单查询失败记录后继续，不中断盘点
            findings["errors"].append({"key": key, "error": f"{type(exc).__name__}: {exc}"})

    conn = psycopg.connect(
        dsn,
        row_factory=dict_row,
        connect_timeout=10,
        autocommit=True,  # 每条独立事务：单查询失败不污染后续；配合连接级只读兜底
        options="-c default_transaction_read_only=on",  # 连接层只读兜底
    )
    try:
        with conn.cursor() as cur:
            _collect(
                cur,
                "identity",
                "SELECT version() AS version, current_database() AS db, current_user AS usr, "
                "inet_server_addr()::text AS server_addr, inet_server_port() AS server_port, "
                "pg_postmaster_start_time() AS start_time",
            )
            _collect(
                cur,
                "settings",
                "SELECT name, setting FROM pg_settings WHERE name = ANY(%s)",
                (
                    [
                        "server_version",
                        "data_directory",
                        "config_file",
                        "hba_file",
                        "port",
                        "max_connections",
                        "wal_level",
                        "fsync",
                        "shared_preload_libraries",
                        "cron.database_name",
                    ],
                ),
            )
            _collect(
                cur,
                "databases",
                "SELECT d.datname, pg_get_userbyid(d.datdba) AS owner, d.datallowconn, "
                "pg_encoding_to_char(d.encoding) AS encoding, "
                "pg_size_pretty(pg_database_size(d.oid)) AS size "
                "FROM pg_database d ORDER BY d.datname",
            )
            _collect(
                cur,
                "extensions_installed",
                "SELECT e.extname, e.extversion, n.nspname AS schema "
                "FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace "
                "ORDER BY e.extname",
            )
            _collect(
                cur,
                "extensions_available_relevant",
                "SELECT name, default_version FROM pg_available_extensions "
                "WHERE name IN ('zhparser', 'vector', 'pg_trgm', 'pg_cron', 'pg_jieba') "
                "ORDER BY name",
            )
            _collect(
                cur,
                "schemas",
                "SELECT n.nspname, pg_get_userbyid(n.nspowner) AS owner "
                "FROM pg_namespace n "
                "WHERE n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema' "
                "ORDER BY n.nspname",
            )
            _collect(
                cur,
                "tables",
                "SELECT schemaname, tablename, tableowner, rowsecurity FROM pg_tables "
                "WHERE schemaname NOT IN ('pg_catalog', 'information_schema') "
                "ORDER BY schemaname, tablename",
            )
            _collect(
                cur,
                "views",
                "SELECT schemaname, viewname, viewowner FROM pg_views "
                "WHERE schemaname NOT IN ('pg_catalog', 'information_schema') "
                "ORDER BY schemaname, viewname",
            )
            _collect(
                cur,
                "matviews",
                "SELECT schemaname, matviewname, matviewowner FROM pg_matviews "
                "WHERE schemaname NOT IN ('pg_catalog', 'information_schema') "
                "ORDER BY schemaname, matviewname",
            )
            _collect(
                cur,
                "sequences",
                "SELECT schemaname, sequencename, sequenceowner FROM pg_sequences "
                "WHERE schemaname NOT IN ('pg_catalog', 'information_schema') "
                "ORDER BY schemaname, sequencename",
            )
            _collect(
                cur,
                "indexes",
                "SELECT schemaname, tablename, indexname, indexdef FROM pg_indexes "
                "WHERE schemaname NOT IN ('pg_catalog', 'information_schema') "
                "ORDER BY schemaname, tablename, indexname",
            )
            _collect(
                cur,
                "triggers",
                "SELECT n.nspname AS schema, c.relname AS table_name, t.tgname, "
                "t.tgenabled, proname AS function_name "
                "FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_proc p ON p.oid = t.tgfoid "
                "WHERE NOT t.tgisinternal "
                "AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "ORDER BY n.nspname, c.relname, t.tgname",
            )
            _collect(
                cur,
                "event_triggers",
                "SELECT evtname, evtevent, pg_get_userbyid(evtowner) AS owner "
                "FROM pg_event_trigger ORDER BY evtname",
            )
            _collect(
                cur,
                "replication_slots",
                "SELECT slot_name, slot_type, database, active, restart_lsn "
                "FROM pg_replication_slots",
            )
            _collect(cur, "publications", "SELECT pubname, puballtables FROM pg_publication")
            _collect(cur, "subscriptions", "SELECT subname FROM pg_subscription")
            _collect(
                cur,
                "stat_replication",
                "SELECT pid, usename, application_name, client_addr::text, state "
                "FROM pg_stat_replication",
            )
            _collect(
                cur,
                "activity",
                "SELECT pid, usename, datname, application_name, client_addr::text AS client_addr, "
                "backend_start, state, backend_type, left(query, 160) AS query_snippet "
                "FROM pg_stat_activity ORDER BY backend_start",
            )
            _collect(
                cur,
                "roles",
                "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolcanlogin, rolreplication "
                "FROM pg_roles WHERE rolname NOT LIKE 'pg\\_%' ORDER BY rolname",
            )

            # 应用表行数（逐表 SELECT count(*)，只读）
            from psycopg import sql

            findings["table_counts"] = {}
            for tbl in findings.get("tables", []):
                qual = sql.Identifier(tbl["schemaname"], tbl["tablename"])
                try:
                    cur.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(qual))
                    row = cur.fetchone()
                    findings["table_counts"][f"{tbl['schemaname']}.{tbl['tablename']}"] = row["n"]
                except Exception as exc:  # noqa: BLE001
                    findings["errors"].append(
                        {"key": f"count:{tbl['schemaname']}.{tbl['tablename']}", "error": f"{type(exc).__name__}: {exc}"}
                    )

            _collect(
                cur,
                "documents_summary",
                "SELECT count(*) AS docs, min(published) AS min_published, max(published) AS max_published, "
                "count(DISTINCT status) AS distinct_status FROM documents",
            )
            _collect(
                cur,
                "documents_by_status",
                "SELECT status, count(*) AS n FROM documents GROUP BY status ORDER BY status",
            )
            _collect(cur, "blocks_count", "SELECT count(*) AS blocks FROM blocks")
            _collect(
                cur,
                "comments_app_tables",
                "SELECT c.relname AS table_name, d.description FROM pg_description d "
                "JOIN pg_class c ON c.oid = d.objoid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE d.objsubid = 0 AND d.description IS NOT NULL "
                "AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "ORDER BY c.relname",
            )
    finally:
        conn.close()

    findings["read_only_note"] = (
        "连接层 default_transaction_read_only=on；全部语句为 SELECT（含系统目录）；零 DDL/DML"
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(findings, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(f"OK findings -> {out_path} (errors={len(findings['errors'])})")


if __name__ == "__main__":
    main()
