"""I4-7 reset 阶段 1：按 i4-reset-manifest.json 逐表 TRUNCATE 七表（U 已一次具名批准）。

manifest 锁定原文（phases[0].when）：「I4-7（U 批准后、迁移 DDL 完成后），窗口内执行」；
execution_gates 全部落实：
1. 守卫 i4-window.json 安装 + run_selfcheck 通过（i47-guard-selfcheck.json，
   config sha 必须与当前守卫文件一致）；
2. 导出前提核对：backup_binding artifact-manifest.sha256 文件哈希 == 绑定值，
   五张导出表的 jsonl/csv + _counts.json 存在且内容哈希与清单逐条一致；
3. 执行前逐表行数 == rows_before（漂移即停，不扩大删除）；
4. 单事务执行 manifest phases[0].statements 逐字六语句（语句/对象/行数三对账）；
5. 执行后逐表行数 == 0；3 个 owned 序列归零（last_value=1, is_called=false）；
   保留表（docs/chinese_docs/blocks/documents）行数与其序列状态不变；
6. 零模型调用（守卫阻断）；留出件零读取（守卫 forbidden_roots）。
产出 write-once：i47-reset-phase1-report.json。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path("/home/administrator/FrontierAgent")
ING = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
AUD = ING / "audits/20260923-i4-window"
RESET_MANIFEST = ING / "i4-reset-manifest.json"
CUTOVER = ING / "i4-cutover-manifest.json"
SELFCHECK = AUD / "i47-guard-selfcheck.json"
APPROVAL = AUD / "i42-approval.json"
OUT = AUD / "i47-reset-phase1-report.json"

PG_DSN = "postgresql://postgres:postgres@127.0.0.1:5432/postgres"
GUARD_CFG = ING / "guards/i4-window.json"
BACKUP_DIR = ING / "backups/i4-final-20260923T1544Z"
BACKUP_MANIFEST_SHA = "085abf4c499bc0fc24a69abfe1e8d71634b4b9efbad097b81ca24d9f3bb648fb"
LEDGERS = BACKUP_DIR / "ledgers"

CHAIR_SEQS = [  # 阶段 1 reset 范围内 owned 序列（manifest sequences_reset）
    "public.claims_claim_id_seq",
    "public.claims_v2_claim_id_seq",
    "public.ingest_runs_run_id_seq",
]
RETAINED_SEQS = ["public.docs_id_seq", "public.chinese_docs_id_seq"]  # not_in_scope
WITNESS_TABLES = ["blocks", "documents", "docs", "chinese_docs"]  # 保留见证（阶段 2 之外）

STMT_TABLE_RE = re.compile(r"public\.([A-Za-z_][A-Za-z0-9_]*)")


def _abort(msg: str) -> None:
    raise SystemExit(f"拒绝（漂移即停）：{msg}")


def _seq_state(cur: psycopg.Cursor, name: str) -> dict[str, object]:
    cur.execute(f"SELECT last_value, is_called FROM {name}")  # noqa: S608 — 序列名来自清单
    row = cur.fetchone()
    assert row is not None
    return {"last_value": row["last_value"], "is_called": row["is_called"]}


def _count(cur: psycopg.Cursor, table: str) -> int:
    cur.execute(f"SELECT count(*) AS n FROM public.{table}")  # noqa: S608 — 表名来自清单
    row = cur.fetchone()
    assert row is not None
    return int(row["n"])


def main() -> int:
    if OUT.exists():
        _abort(f"write-once 报告已存在：{OUT}")
    tz = timezone(timedelta(hours=8))
    manifest = json.loads(RESET_MANIFEST.read_text(encoding="utf-8"))
    cutover = json.loads(CUTOVER.read_text(encoding="utf-8"))
    phase = next(p for p in manifest["phases"] if p["phase"] == 1)
    statements: list[str] = phase["statements"]
    rows_before: dict[str, int] = {t["table"].removeprefix("public."): t["rows_before"] for t in phase["tables"]}
    assert len(statements) == 6 and all(
        s.startswith("TRUNCATE public.") and s.endswith("RESTART IDENTITY;") for s in statements
    )

    # ── 门 1：守卫自检通过且配置未变 ────────────────────────────────
    sc = json.loads(SELFCHECK.read_text(encoding="utf-8"))
    if not sc["passed"] or sc["phase"] != "i4-window":
        _abort("守卫自检未通过或阶段不符")
    cur_guard_sha = hashlib.sha256(GUARD_CFG.read_bytes()).hexdigest()
    if sc["config_sha256"] != cur_guard_sha:
        _abort("守卫配置自检后发生变更（漂移即停）")
    if not APPROVAL.exists():
        _abort("U 具名批准记录（i42-approval.json）缺失")

    # ── 门 2：导出前提（I4-6 最终备份 ledger 逐条核对）──────────────
    bm_path = BACKUP_DIR / "artifact-manifest.sha256"
    if hashlib.sha256(bm_path.read_bytes()).hexdigest() != BACKUP_MANIFEST_SHA:
        _abort("backup artifact-manifest.sha256 与 reset manifest export_binding 不一致")
    recorded: dict[str, str] = {}
    for line in bm_path.read_text(encoding="utf-8").splitlines():
        sha, _, rel = line.partition("  ")
        recorded[rel.strip()] = sha
    export_ledgers: dict[str, str] = {
        t["table"].removeprefix("public."): t["export"]
        for t in phase["tables"]
        if "无导出需求" not in t["export"]
    }
    ledger_check: dict[str, object] = {}
    for table, _note in export_ledgers.items():
        for ext in ("jsonl", "csv"):
            rel = f"ledgers/{table}.{ext}"
            path = BACKUP_DIR / rel
            if not path.exists():
                _abort(f"导出前提缺失：{rel}")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if recorded.get(rel) != actual:
                _abort(f"导出件哈希不一致：{rel}")
            ledger_check[rel] = actual
    counts_rel = "ledgers/_counts.json"
    if not (BACKUP_DIR / counts_rel).exists():
        _abort("导出前提缺失：ledgers/_counts.json")
    ledger_check[counts_rel] = recorded.get(counts_rel)

    # ── 门 3-5：单事务（前置核对 → 逐字执行 → 后置核对），异常即整体回滚 ──
    report: dict[str, object] = {
        "purpose": "I4-7 reset 阶段 1：manifest 逐表 TRUNCATE 七表（U 2026-09-24 一次具名批准）",
        "executed_at": datetime.now(tz).isoformat(timespec="seconds"),
        "manifest_sha256": hashlib.sha256(RESET_MANIFEST.read_bytes()).hexdigest(),
        "statements_source": "i4-reset-manifest.json phases[0].statements（运行时读取逐字执行）",
        "export_binding_check": {"artifact_manifest_sha256": BACKUP_MANIFEST_SHA, "ledgers": ledger_check},
        "zero_model_calls": True,
    }
    with psycopg.connect(PG_DSN) as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT current_database() AS db, pg_current_wal_lsn() AS lsn")
        row = cur.fetchone()
        assert row is not None
        if row["db"] != "postgres":
            _abort(f"current_database={row['db']!r} ≠ postgres")
        cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = 'corpus'")
        if cur.fetchone() is None:
            _abort("corpus schema 不存在——迁移 DDL 未完成，不满足 phases[0].when 前置")
        report["wal_lsn_before"] = row["lsn"]

        # 门 3：执行前逐表行数 == rows_before（漂移即停）
        pre_counts = {t: _count(cur, t) for t in rows_before}
        drift = {t: {"rows_before": rows_before[t], "now": n} for t, n in pre_counts.items() if n != rows_before[t]}
        if drift:
            _abort(f"执行前行数漂移：{drift}")
        # 三对账：语句 → 对象 → 行数
        recon: list[dict[str, object]] = []
        for i, stmt in enumerate(statements, 1):
            objs = STMT_TABLE_RE.findall(stmt)
            recon.append(
                {"statement": stmt, "objects": objs, "rows_before": {o: rows_before[o] for o in objs}}
            )
        seq_before = {s: _seq_state(cur, s) for s in CHAIR_SEQS + RETAINED_SEQS}
        witnesses_before = {t: _count(cur, t) for t in WITNESS_TABLES}
        report["pre"] = {
            "table_counts": pre_counts,
            "statement_object_row_reconciliation": recon,
            "sequences_before": seq_before,
            "witness_tables_before": witnesses_before,
        }

        # 门 4：逐字执行（同一事务）
        for stmt in statements:
            cur.execute(stmt)

        # 门 5：执行后核对
        post_counts = {t: _count(cur, t) for t in rows_before}
        nonzero = {t: n for t, n in post_counts.items() if n != 0}
        if nonzero:
            _abort(f"执行后非零表：{nonzero}")
        seq_after = {s: _seq_state(cur, s) for s in CHAIR_SEQS + RETAINED_SEQS}
        for s in CHAIR_SEQS:
            if seq_after[s] != {"last_value": 1, "is_called": False}:
                _abort(f"owned 序列未归零：{s} → {seq_after[s]}")
        for s in RETAINED_SEQS:
            if seq_after[s] != seq_before[s]:
                _abort(f"保留序列被改动：{s}")
        witnesses_after = {t: _count(cur, t) for t in WITNESS_TABLES}
        if witnesses_after != witnesses_before:
            _abort(f"保留见证表行数变化：{witnesses_after} ≠ {witnesses_before}")
        cur.execute("SELECT pg_current_wal_lsn() AS lsn")
        report["wal_lsn_after"] = cur.fetchone()["lsn"]
        report["post"] = {
            "table_counts_all_zero": post_counts,
            "sequences_after": seq_after,
            "sequences_reset_verified": CHAIR_SEQS,
            "retained_sequences_unchanged": RETAINED_SEQS,
            "witness_tables_after": witnesses_after,
        }
    # with 块正常退出 = 提交；任何异常已整体回滚且未写报告

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("sha256:", hashlib.sha256(OUT.read_bytes()).hexdigest()[:16], "…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
