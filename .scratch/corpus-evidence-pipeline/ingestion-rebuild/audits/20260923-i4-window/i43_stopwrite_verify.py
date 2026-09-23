"""I4-3 窗口内停写核验（任务清单 I4-3、架构 v1.1 §12.4）。

纪律：
- 零 DDL/DML 于原库：仅系统目录/统计视图 SELECT；连接层 default_transaction_read_only=on 兜底。
- 先装守卫（i4-window-backup 阶段）再连接；DSN 经显式环境变量 CORPUS_WINDOW_DSN 传入。
- 证据链：pg_stat_activity 零客户端后端 + 零 idle-in-transaction；WAL LSN 括号
  （间隔 ~30s 两次采样，LSN 不前进即无新增提交的强信号）；xact_commit 增量
  与本会话自身提交数对账；复制槽/pg_cron 复核；旧写入口清单（I4-5 停用对象）
  代码级登记；corpus schema 存在性复核（期望不存在，DDL 属 I4-7）。
- 截止点（cutoff）：pg_current_wal_lsn + clock_timestamp，write-once 落盘。
- 输出 findings JSON 不含任何凭据。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

_REPO_ROOT = Path(__file__).resolve().parents[5]
_GUARD_CONFIG = (
    _REPO_ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i4-window-backup.json"
)
_DEV_MANIFEST = _REPO_ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/dev-manifest.json"
_AUDIT_DIR = Path(__file__).resolve().parent

OLD_WRITE_ENTRIES = [
    "ingest", "extract-claims", "claim-runs(写)", "derive-claims", "reconcile-claims(写)",
    "set-kind", "audit(写)", "backup/restore(写目标库)",
]


def _fail(msg: str) -> NoReturn:
    print(f"I4-3 停写核验拒绝执行: {msg}", file=sys.stderr)
    raise SystemExit(2)


def _snapshot(cur: Any) -> dict[str, Any]:
    cur.execute("SELECT pg_current_wal_lsn()::text AS lsn, clock_timestamp()::text AS ts")
    row = cur.fetchone()
    cur.execute("""
        SELECT datname, xact_commit, xact_rollback, tup_inserted, tup_updated, tup_deleted
        FROM pg_stat_database WHERE datname = current_database()""")
    stats = cur.fetchone()
    cur.execute("""
        SELECT pid, usename, application_name, client_addr::text AS client_addr,
               state, backend_type, wait_event_type, wait_event,
               left(coalesce(query,''), 200) AS query_head
        FROM pg_stat_activity WHERE pid <> pg_backend_pid() ORDER BY backend_start""")
    backends = cur.fetchall()
    clients = [b for b in backends if b["backend_type"] == "client backend"]
    idle_in_txn = [b for b in clients if b["state"] in ("idle in transaction", "idle in transaction (aborted)")]
    return {
        "lsn": row["lsn"],
        "ts": row["ts"],
        "db_stats": stats,
        "backends_total": len(backends),
        "backends_by_type": sorted({b["backend_type"] for b in backends}),
        "client_backends": clients,
        "client_backend_count": len(clients),
        "idle_in_transaction": idle_in_txn,
        "backend_pids": sorted(b["pid"] for b in backends),
    }


def main() -> None:
    dsn = os.environ.get("CORPUS_WINDOW_DSN", "").strip()
    if not dsn:
        _fail("环境变量 CORPUS_WINDOW_DSN 未设置；连接串必须显式传入，禁止读 CORPUS_DSN/.env")

    from plugins.corpus.preparation import guard

    cfg = guard.install(_GUARD_CONFIG)

    from psycopg.conninfo import conninfo_to_dict

    dsn_parts = conninfo_to_dict(dsn)
    host = dsn_parts.get("host") or "localhost"
    port = int(dsn_parts.get("port") or 5432)
    if (host, port) not in {(h, p) for h, p in cfg.allowed_targets}:
        _fail(f"目标 {host}:{port} 不在守卫阶段 {cfg.phase} 的 allowed_targets 中")

    import psycopg
    from psycopg.rows import dict_row

    findings: dict[str, Any] = {
        "artifact": "i43-stopwrite-findings.json",
        "task": "I4-3 窗口内停写核验 + 截止点记录（授权：U 2026-09-23 本会话核定，migrate_then_reset_limited 分支窗口序列）",
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "guard": {
            "phase": cfg.phase,
            "config": str(_GUARD_CONFIG),
            "config_sha256": hashlib.sha256(_GUARD_CONFIG.read_bytes()).hexdigest(),
        },
        "target": {
            "host": host, "port": port,
            "database": dsn_parts.get("dbname"), "user": dsn_parts.get("user"),
            "note": "凭据不出现在本文件",
        },
        "errors": [],
    }

    conn = psycopg.connect(
        dsn, row_factory=dict_row, connect_timeout=10, autocommit=True,
        options="-c default_transaction_read_only=on",
    )
    try:
        with conn.cursor() as cur:
            snap_a = _snapshot(cur)
            print(f"[bracket] A: lsn={snap_a['lsn']} ts={snap_a['ts']} clients={snap_a['client_backend_count']}")
            time.sleep(30)
            snap_b = _snapshot(cur)
            print(f"[bracket] B: lsn={snap_b['lsn']} ts={snap_b['ts']} clients={snap_b['client_backend_count']}")

            # 自身提交数对账：两次采样间本会话执行的语句数（autocommit 每语句一提交）
            self_xacts = 6  # A:3(lsn+ts,stats,activity) + B:3

            delta = {
                "lsn_advanced": snap_a["lsn"] != snap_b["lsn"],
                "xact_commit_delta": snap_b["db_stats"]["xact_commit"] - snap_a["db_stats"]["xact_commit"],
                "xact_rolled_back_delta": snap_b["db_stats"]["xact_rollback"] - snap_a["db_stats"]["xact_rollback"],
                "tup_inserted_delta": snap_b["db_stats"]["tup_inserted"] - snap_a["db_stats"]["tup_inserted"],
                "tup_updated_delta": snap_b["db_stats"]["tup_updated"] - snap_a["db_stats"]["tup_updated"],
                "tup_deleted_delta": snap_b["db_stats"]["tup_deleted"] - snap_a["db_stats"]["tup_deleted"],
                "self_statements_between": self_xacts,
                "interval_seconds": 30,
            }
            findings["wal_bracket"] = {"a": snap_a, "b": snap_b, "delta": delta}

            _collects: dict[str, Any] = {}
            cur.execute("SELECT count(*) AS n FROM pg_replication_slots")
            _collects["replication_slots"] = cur.fetchone()["n"]
            try:
                cur.execute("SELECT count(*) AS n FROM cron.job")
                _collects["cron_jobs"] = cur.fetchone()["n"]
            except psycopg.errors.UndefinedTable:
                _collects["cron_jobs"] = 0
                _collects["cron_note"] = "pg_cron 未安装（UndefinedTable 按 0 计，与 I4-1 盘点一致）"
            cur.execute("""
                SELECT nspname FROM pg_namespace
                WHERE nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema' ORDER BY 1""")
            _collects["schemas"] = [r["nspname"] for r in cur.fetchall()]
            cur.execute("""
                SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='corpus' ORDER BY c.relname""")
            _collects["corpus_schema_objects"] = [r["relname"] for r in cur.fetchall()]
            findings["preconditions"] = _collects
    finally:
        conn.close()

    # 截止点：write-once（取 B 括号点为停写截止点）
    findings["cutoff"] = {
        "wal_lsn": snap_b["lsn"],
        "utc_time": snap_b["ts"],
        "definition": "停写截止点 = 第二次括号采样点（snapshot B）；此后窗口内不得有任何对原库的写入",
        "write_once": True,
    }

    # 旧写入口清单（I4-5 停用对象登记；I2-7 已在消费者层退役 ingest/claims_v2 主路径）
    findings["old_write_entries"] = {
        "entries": OLD_WRITE_ENTRIES,
        "code_location": "plugins/corpus/service.py（CLI 子命令）",
        "status": "window_no_callers（pg_stat_activity 零客户端后端 = 无任何调用者）；正式停用记录在 I4-5 落账",
        "note": "I2-7 已退役消费者层 ingest/claims_v2 写路径；本清单为窗口内暂停批准范围 + I4-5 停用登记对象",
    }

    # 源归档清单绑定（dev-manifest；完整原文归档在 I4-6 执行）
    src_binding: dict[str, Any] = {"dev_manifest": str(_DEV_MANIFEST)}
    if _DEV_MANIFEST.exists():
        src_binding["dev_manifest_sha256"] = hashlib.sha256(_DEV_MANIFEST.read_bytes()).hexdigest()
        dm = json.loads(_DEV_MANIFEST.read_text(encoding="utf-8"))
        src_binding["source_count"] = len(dm.get("sources", []))
        src_binding["note"] = "完整归档清单与哈希在 I4-6 最终备份 artifact-manifest 落账"
    findings["source_archive_binding"] = src_binding

    # 门禁判定
    checks = {
        "zero_client_backends": snap_a["client_backend_count"] == 0 and snap_b["client_backend_count"] == 0,
        "zero_idle_in_transaction": not snap_a["idle_in_transaction"] and not snap_b["idle_in_transaction"],
        "wal_lsn_stable": not delta["lsn_advanced"],
        "no_third_party_commits": delta["xact_commit_delta"] <= self_xacts,
        "no_tuple_writes": all(delta[k] == 0 for k in ("tup_inserted_delta", "tup_updated_delta", "tup_deleted_delta")),
        "no_replication_slots": _collects["replication_slots"] == 0,
        "no_cron_jobs": _collects["cron_jobs"] == 0,
        "corpus_schema_absent": not _collects["corpus_schema_objects"],
    }
    findings["gate"] = {"checks": checks, "passed": all(checks.values())}

    out = _AUDIT_DIR / "i43-stopwrite-findings.json"
    if out.exists():
        _fail(f"输出已存在（write-once）: {out}")
    out.write_text(json.dumps(findings, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(findings["gate"], ensure_ascii=False, indent=1))
    print(f"cutoff: lsn={findings['cutoff']['wal_lsn']} utc={findings['cutoff']['utc_time']}")


if __name__ == "__main__":
    main()
