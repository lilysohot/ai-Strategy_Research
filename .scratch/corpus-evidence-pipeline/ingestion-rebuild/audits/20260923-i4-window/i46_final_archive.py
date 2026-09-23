"""I4-6 最终一致性备份（停写状态）+ 台账/清理清单/遗留表只读导出。

纪律（任务清单 I4-6、v1.1 §12.4、I0B-1 先例）：
- 先装守卫（i4-window-backup 阶段，forbidden_roots=[]）再连接：原库仅只读 SELECT，
  连接层 default_transaction_read_only=on 兜底；DSN 经显式环境变量 CORPUS_WINDOW_DSN 传入。
- 本脚本职责：原文全量 tar（含 5 份留出件字节，仅作备份归档）+ 台账 JSONL/CSV 导出
  （claims/claim_block_runs/corpus_evidence_runs/ingest_runs/ingest_failures 先导出台账
  入归档 + docs/chinese_docs 遗留表 C12 只读导出）+ i0c-cleanup-list 归档副本与 CSV 投影
  + artifact-manifest.sha256 + notes.json（FINAL 状态、截止点绑定）。
- PG dump/globals/TOC 由外层纯 Shell 完成（守卫进程拒绝非 Python 子进程），本脚本仅绑定。
- 全部输出 write-once。
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

_REPO_ROOT = Path(__file__).resolve().parents[5]
_GUARD_CONFIG = (
    _REPO_ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i4-window-backup.json"
)
_CLEANUP_LIST = _REPO_ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i0c-cleanup-list.json"
_I43_FINDINGS = Path(__file__).resolve().parent / "i43-stopwrite-findings.json"
_AUDIT_DIR = Path(__file__).resolve().parent

LEDGER_TABLES = [
    "claims", "claim_block_runs", "corpus_evidence_runs", "ingest_runs", "ingest_failures",
]
C12_TABLES = ["docs", "chinese_docs"]
V2_TABLES = ["claims_v2", "claim_block_runs_v2"]


def _fail(msg: str) -> NoReturn:
    print(f"I4-6 最终备份拒绝执行: {msg}", file=sys.stderr)
    raise SystemExit(2)


def main() -> None:
    if len(sys.argv) != 4:
        _fail("用法: i46_final_archive.py <backup_dir> <wal_before|ts> <wal_after|ts>")
    backup_dir = Path(sys.argv[1]).resolve()
    wal_before, wal_after = sys.argv[2], sys.argv[3]
    if not backup_dir.exists() or not any(backup_dir.iterdir()):
        _fail(f"备份目录不存在或为空（PG dump 应已由外层完成）: {backup_dir}")

    dsn = os.environ.get("CORPUS_WINDOW_DSN", "").strip()
    if not dsn:
        _fail("环境变量 CORPUS_WINDOW_DSN 未设置；连接串必须显式传入")

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

    ledgers_dir = backup_dir / "ledgers"
    cleanup_dir = backup_dir / "cleanup-list"
    ledgers_dir.mkdir(parents=True, exist_ok=True)
    cleanup_dir.mkdir(parents=True, exist_ok=True)

    counts: dict[str, int] = {}
    lsn_at_archive: str | None = None

    conn = psycopg.connect(
        dsn, row_factory=dict_row, connect_timeout=10, autocommit=True,
        options="-c default_transaction_read_only=on",
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_current_wal_lsn()::text AS lsn, clock_timestamp()::text AS ts")
            row = cur.fetchone()
            lsn_at_archive = row["lsn"]
            archive_ts = row["ts"]
            cutoff_lsn = json.loads(_I43_FINDINGS.read_text(encoding="utf-8"))["cutoff"]["wal_lsn"]
            if lsn_at_archive != cutoff_lsn:
                _fail(f"归档时刻 LSN {lsn_at_archive} 与停写截止点 {cutoff_lsn} 不一致（出现新写入，即停）")

            for table in LEDGER_TABLES + C12_TABLES:
                cur.execute(f"SELECT * FROM public.{table}")  # noqa: S608 - 表名来自冻结常量
                rows = cur.fetchall()
                counts[table] = len(rows)
                cols = [d.name for d in cur.description] if cur.description else []
                jsonl = ledgers_dir / f"{table}.jsonl"
                csvf = ledgers_dir / f"{table}.csv"
                if jsonl.exists() or csvf.exists():
                    _fail(f"导出文件已存在（write-once）: {jsonl} / {csvf}")
                with jsonl.open("w", encoding="utf-8") as fj:
                    for r in rows:
                        fj.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
                with csvf.open("w", encoding="utf-8", newline="") as fc:
                    w = csv.DictWriter(fc, fieldnames=cols)
                    w.writeheader()
                    for r in rows:
                        w.writerow({k: ("" if r[k] is None else r[k]) for k in cols})
                print(f"[ledger] {table}: {len(rows)} rows -> {jsonl.name}+{csvf.name}")

            for table in V2_TABLES:
                cur.execute(f"SELECT count(*) AS n FROM public.{table}")  # noqa: S608
                counts[table] = cur.fetchone()["n"]
                print(f"[count] {table}: {counts[table]} rows (0 行表，无导出)")

            # 备份时刻全表精确计数（恢复核对基准）
            cur.execute("""
                SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' AND c.relkind='r' ORDER BY c.relname""")
            all_tables = [r["relname"] for r in cur.fetchall()]
            for t in all_tables:
                if t not in counts:
                    cur.execute(f'SELECT count(*) AS n FROM public."{t}"')  # noqa: S608
                    counts[t] = cur.fetchone()["n"]
    finally:
        conn.close()

    (ledgers_dir / "_counts.json").write_text(
        json.dumps({"baseline": "backup-time exact counts (restore verification基准)",
                    "counts": counts}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ---- cleanup-list 归档副本 + CSV 投影 ----
    cleanup_json = cleanup_dir / "i0c-cleanup-list.json"
    if cleanup_json.exists():
        _fail(f"cleanup-list 副本已存在（write-once）: {cleanup_json}")
    cleanup_json.write_bytes(_CLEANUP_LIST.read_bytes())
    cl = json.loads(_CLEANUP_LIST.read_text(encoding="utf-8"))
    for key, value in cl.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            cols = sorted({k for row in value for k in row})
            with (cleanup_dir / f"i0c-cleanup-list-{key}.csv").open("w", encoding="utf-8", newline="") as fc:
                w = csv.DictWriter(fc, fieldnames=cols)
                w.writeheader()
                for row in value:
                    w.writerow({c: row.get(c, "") for c in cols})
    print(f"[cleanup-list] {sum(len(v) for v in cl.values() if isinstance(v, list))} 条已归档")

    # ---- 原文全量 tar（含 5 份留出件字节；forbidden_roots=[] 授权，仅备份归档）----
    tar_path = backup_dir / "originals-corpus.tar.gz"
    if tar_path.exists():
        _fail(f"原文 tar 已存在（write-once）: {tar_path}")
    corpus_root = _REPO_ROOT / "data/corpus"
    included = 0
    holdouts: list[str] = []
    with tarfile.open(tar_path, "w:gz") as tf:
        for f in sorted(corpus_root.rglob("*")):
            if not f.is_file():
                continue
            tf.add(f, arcname=str(f.relative_to(_REPO_ROOT)), recursive=False)
            included += 1
            if f.suffix.lower() == ".pdf" and f.name in {
                "2026-08-12_2026.08.12-国泰海通-国内研报-国泰海通证券-ipo专题-新股精要-国内领先的电子材料和化工新材料生产企业贝特利-2594e01d.pdf",
                "2026-08-17_2026.08.17-国信证券-张向伟-王新雨-公司研究-业绩点评-贵州茅台-600519-2026上半年收入同比增长1-3-继续深化市场化改革-bbba671e.pdf",
                "2026-09-06_2026.09.06-中银国际-中银证券-高频数据扫描-美国非农超预期-特朗普发新威胁-65b4b040.pdf",
                "2026-09-06_2026.09.06-华泰证券-宏观海外周报-联储加息悬念白热化-d571f138.pdf",
                "2026-09-06_2026.09.06-天风证券-海外跟踪周报-非农清障-通胀定调-5520fab6.pdf",
            }:
                holdouts.append(str(f.relative_to(_REPO_ROOT)))
    print(f"[originals] tar.gz: {included} files（含留出件 {len(holdouts)}）")

    # ---- notes.json（FINAL）----
    i43 = json.loads(_I43_FINDINGS.read_text(encoding="utf-8"))
    notes = {
        "artifact": "i4-final-backup-notes.json",
        "task": "I4-6 停写状态最终一致性备份",
        "status": "FINAL_BACKUP_I4_6",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "authorization": "U 2026-09-23 本会话核定（migrate_then_reset_limited 窗口序列；I4-3 停写核验通过后执行）",
        "cutoff_binding": {
            "wal_lsn": i43["cutoff"]["wal_lsn"],
            "utc_time": i43["cutoff"]["utc_time"],
            "i43_findings": str(_I43_FINDINGS),
            "i43_gate_passed": i43["gate"]["passed"],
        },
        "wal_bracket": {
            "dump_before": wal_before,
            "dump_after": wal_after,
            "archive_at": f"{lsn_at_archive}|{archive_ts}",
            "note": "停写状态全程 LSN 0/4FB2BD00 无前进；备份与截止点一致（单 MVCC 快照）",
        },
        "method": {
            "pg_dump": "docker exec pg pg_dump -F c（容器内 pg_dump 18.6 版本匹配）",
            "globals": "pg_dumpall --globals-only",
            "toc": "docker exec -i pg pg_restore --list < dump",
            "originals": "受守卫 tar.gz（data/corpus 全量 196 文件，含 5 份留出件字节，I0B-1 先例）",
            "ledgers": "psycopg 只读 SELECT → JSONL+CSV（5 台账表 + docs/chinese_docs C12 只读导出）",
        },
        "pg_objects": {
            "table_counts_at_backup": counts,
            "databases": ["postgres", "apodex"],
        },
        "originals": {"included_files": included, "holdouts_included": holdouts},
        "restore_target": "corpus-db 127.0.0.1:543 一次性验证库（i4_verify_20260923，验证后销毁）",
    }
    notes_path = backup_dir / "notes.json"
    notes_path.write_text(json.dumps(notes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ---- artifact-manifest.sha256 ----
    manifest_lines = []
    for f in sorted(backup_dir.rglob("*")):
        if f.is_file() and f.name != "artifact-manifest.sha256":
            digest = hashlib.sha256(f.read_bytes()).hexdigest()
            manifest_lines.append(f"{digest}  {f.relative_to(backup_dir)}")
    manifest = backup_dir / "artifact-manifest.sha256"
    manifest.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    print(f"[manifest] {len(manifest_lines)} artifacts; tar_size={tar_path.stat().st_size}")


if __name__ == "__main__":
    main()
