"""I4-1 生产库只读盘点刷新（窗口前准备）。

纪律（任务清单 I4-1/I4-2、v1.1 §12.4、design-review.json i0c_1_branch）：
- 零 DDL/DML：仅系统目录与应用表 SELECT；连接层 default_transaction_read_only=on 兜底。
- 先装守卫再连接：guard.install(i4-inventory) + DSN host/port 必须命中 allowed_targets。
- 连接串经显式环境变量 CORPUS_INVENTORY_DSN 传入，不读 CORPUS_DSN（守卫投毒）。
- 盘点内容：对象/行数漂移核对（vs I0A-1 基线）、corpus schema 存在性（期望：不存在，
  DDL 仅在 I4 窗口执行）、写入者枚举（pg_stat_activity，R1 必需风险的前置证据）、
  复制槽/pg_cron/后台写入任务排查、扩展与词典。
- 输出 findings JSON 不含任何凭据（DSN 仅记 host/port/db/user）。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

_REPO_ROOT = Path(__file__).resolve().parents[5]
_GUARD_CONFIG = _REPO_ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i4-inventory.json"
_BASELINE = _REPO_ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i0a1-inventory-findings.json"
_DEV_MANIFEST = _REPO_ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/dev-manifest.json"
_AUDIT_DIR = Path(__file__).resolve().parent

RESET_CANDIDATES = [
    "documents", "blocks", "claims", "claims_v2", "claim_block_runs",
    "claim_block_runs_v2", "corpus_evidence_runs", "ingest_runs", "ingest_failures",
]


def _fail(msg: str) -> NoReturn:
    print(f"I4-1 盘点拒绝执行: {msg}", file=sys.stderr)
    raise SystemExit(2)


def main() -> None:
    dsn = os.environ.get("CORPUS_INVENTORY_DSN", "").strip()
    if not dsn:
        _fail("环境变量 CORPUS_INVENTORY_DSN 未设置；连接串必须显式传入，禁止读 CORPUS_DSN/.env")

    from plugins.corpus.preparation import guard

    cfg = guard.install(_GUARD_CONFIG)

    from psycopg.conninfo import conninfo_to_dict

    dsn_parts = conninfo_to_dict(dsn)
    host = dsn_parts.get("host") or "localhost"
    port = int(dsn_parts.get("port") or 5432)
    approved = {(h, p) for h, p in cfg.allowed_targets}
    if (host, port) not in approved:
        _fail(f"目标 {host}:{port} 不在守卫阶段 {cfg.phase} 的 allowed_targets {sorted(approved)} 中")

    import psycopg
    from psycopg.rows import dict_row

    findings: dict[str, Any] = {
        "artifact": "i41-inventory-findings.json",
        "task": "I4-1 生产库只读盘点刷新（窗口前准备；预演授权 U 2026-09-23 本会话核定）",
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
        autocommit=True,
        options="-c default_transaction_read_only=on",
    )
    try:
        with conn.cursor() as cur:
            _collect(cur, "identity",
                "SELECT version() AS version, current_database() AS db, current_user AS usr, "
                "pg_postmaster_start_time() AS start_time, pg_current_wal_lsn()::text AS wal_lsn_now")
            _collect(cur, "databases",
                "SELECT datname, pg_size_pretty(pg_database_size(datname)) AS size, "
                "pg_database_size(datname) AS size_bytes, datallowconn FROM pg_database ORDER BY datname")
            _collect(cur, "schemas",
                "SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema' ORDER BY 1")
            # corpus schema 存在性：期望不存在（生产 DDL 仅在 I4 窗口执行）
            _collect(cur, "corpus_schema_objects",
                "SELECT c.relkind, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='corpus' ORDER BY c.relname")
            # public 全表行数（精确 COUNT，I0B-2 教训：不用 n_live_tup）
            _collect(cur, "public_tables_exact_counts", """
                SELECT c.relname, c.reltuples::bigint AS est,
                       (SELECT count(*) FROM pg_class k WHERE k.oid=c.oid) AS self_ref
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' AND c.relkind='r' ORDER BY c.relname""")
            # reset 候选逐表精确行数
            for t in RESET_CANDIDATES:
                _collect(cur, f"exact_count:{t}",
                    f"SELECT count(*) AS n FROM public.{t}" if t not in ("claims_v2", "claim_block_runs_v2", "corpus_evidence_runs", "ingest_runs", "ingest_failures", "documents", "blocks", "claims", "claim_block_runs")
                    else f"SELECT count(*) AS n FROM public.{t}")
            _collect(cur, "sequences_public",
                "SELECT sequencename, last_value FROM pg_sequences WHERE schemaname='public' ORDER BY 1")
            _collect(cur, "candidate_indexes",
                "SELECT tablename, indexname, indexdef FROM pg_indexes "
                "WHERE schemaname='public' AND tablename = ANY(%s) ORDER BY tablename, indexname",
                (RESET_CANDIDATES,))
            _collect(cur, "extensions",
                "SELECT extname, extversion FROM pg_extension ORDER BY 1")
            _collect(cur, "zhparser_dict",
                "SELECT count(*) AS n FROM zhparser.zhprs_custom_word")
            # 写入者枚举（R1 前置证据）：全部活动后端
            _collect(cur, "pg_stat_activity", """
                SELECT pid, usename, application_name, client_addr::text AS client_addr,
                       backend_start, state, backend_type,
                       left(coalesce(query,''), 200) AS query_head,
                       (query ~* '\\m(INSERT|UPDATE|DELETE|TRUNCATE|MERGE|COPY|CREATE|ALTER|DROP)\\M') AS write_query,
                       (state IN ('idle in transaction', 'idle in transaction (aborted)')) AS in_open_xact
                FROM pg_stat_activity WHERE pid <> pg_backend_pid() ORDER BY backend_start""")
            _collect(cur, "replication_slots",
                "SELECT slot_name, slot_type, active FROM pg_replication_slots")
            _collect(cur, "scheduled_jobs",
                "SELECT jobid, schedule, command, active FROM cron.job ORDER BY jobid")
    finally:
        conn.close()

    # ---- 漂移核对 vs I0A-1 基线 ----
    drift: dict[str, Any] = {"baseline": str(_BASELINE)}
    if _BASELINE.exists():
        base = json.loads(_BASELINE.read_text(encoding="utf-8"))
        base_counts = {}
        for row in base.get("public_tables_exact_counts", []) or base.get("public_tables", []):
            if isinstance(row, dict) and "relname" in row:
                base_counts[row["relname"]] = row.get("exact_n", row.get("n", row.get("est")))
        now_counts = {}
        for row in findings.get("public_tables_exact_counts", []):
            now_counts[row["relname"]] = row.get("est")
        # est 仅是统计值；精确值在 exact_count:* 键
        for t in RESET_CANDIDATES:
            v = findings.get(f"exact_count:{t}")
            if isinstance(v, list) and v:
                now_counts[t] = v[0].get("n")
        drift["row_counts"] = {
            t: {"baseline": base_counts.get(t), "now": now_counts.get(t),
                "changed": base_counts.get(t) is not None and now_counts.get(t) is not None and base_counts[t] != now_counts[t]}
            for t in sorted(set(base_counts) | set(now_counts))
        }
        drift["changed_tables"] = sorted(t for t, v in drift["row_counts"].items() if v["changed"])
        base_schemas = sorted(r["nspname"] for r in base.get("schemas", []) if isinstance(r, dict))
        now_schemas = sorted(r["nspname"] for r in findings.get("schemas", []))
        drift["schemas"] = {"baseline": base_schemas, "now": now_schemas}
        base_ext = {r["extname"]: r["extversion"] for r in base.get("extensions", []) if isinstance(r, dict)}
        now_ext = {r["extname"]: r["extversion"] for r in findings.get("extensions", [])}
        drift["extensions"] = {"baseline": base_ext, "now": now_ext}
    findings["drift_vs_i0a1"] = drift

    # ---- 来源文件漂移核对（vs dev-manifest 73 源；5 份留出仅 stat 不读内容） ----
    src_drift: dict[str, Any] = {"baseline": str(_DEV_MANIFEST), "matched": 0, "changed": [], "missing": [], "added": [], "holdout_stat_only": []}
    if _DEV_MANIFEST.exists():
        dm = json.loads(_DEV_MANIFEST.read_text(encoding="utf-8"))
        forbidden = set()
        for x in cfg.forbidden_roots:
            xp = Path(x)
            forbidden.add(str(xp if xp.is_absolute() else (_REPO_ROOT / xp).resolve()))
        manifest_paths = {}
        for s in dm.get("sources", []):
            p = s.get("path", "")
            if p:
                manifest_paths[p] = s
        seen = set()
        corpus_root = _REPO_ROOT / "data/corpus"
        for f in sorted(corpus_root.rglob("*")):
            if not f.is_file():
                continue
            rel = str(f.relative_to(_REPO_ROOT))
            if str(f) in forbidden:
                st = f.stat()
                src_drift["holdout_stat_only"].append({"path": rel, "size": st.st_size, "mtime_ns": st.st_mtime_ns})
                if rel in manifest_paths:
                    seen.add(rel)
                continue
            if rel in manifest_paths:
                seen.add(rel)
                h = hashlib.sha256(f.read_bytes()).hexdigest()
                if h != manifest_paths[rel].get("source_id"):
                    src_drift["changed"].append({"path": rel, "now_sha256": h})
                else:
                    src_drift["matched"] += 1
            else:
                src_drift["added"].append(rel)
        src_drift["missing"] = sorted(p for p in manifest_paths if p not in seen)
        src_drift["added_count"] = len(src_drift["added"])
    findings["source_drift_vs_dev_manifest"] = src_drift
    findings["summary"] = {
        "corpus_schema_present": bool(findings.get("corpus_schema_objects")),
        "reset_candidate_counts": {t: (findings.get(f"exact_count:{t}") or [{}])[0].get("n") for t in RESET_CANDIDATES},
        "drift_changed_tables": drift.get("changed_tables", []),
        "source_files_matched": src_drift.get("matched"),
        "source_files_changed": len(src_drift.get("changed", [])),
        "source_files_missing": len(src_drift.get("missing", [])),
        "source_files_added": len(src_drift.get("added", [])),
        "active_backends": len(findings.get("pg_stat_activity", [])),
        "possibly_writing_backends": sum(1 for r in findings.get("pg_stat_activity", []) if r.get("possibly_writing")),
        "replication_slots": len(findings.get("replication_slots", [])),
        "cron_jobs": len(findings.get("scheduled_jobs", [])),
        "errors": len(findings.get("errors", [])),
    }

    out = _AUDIT_DIR / "i41-inventory-findings.json"
    out.write_text(json.dumps(findings, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(findings["summary"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
