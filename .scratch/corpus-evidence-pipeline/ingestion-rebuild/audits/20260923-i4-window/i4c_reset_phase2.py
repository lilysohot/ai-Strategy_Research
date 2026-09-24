"""I4-reset 阶段 2：按 i4-reset-manifest.json phases[2] 单语句 TRUNCATE 六表（U 已解除暂缓批准）。

manifest 锁定原文（phases[1].when）：「新链重建并核对后（I4-4 验证通过 + U 复核）——design-review
前置条件；不在 I4-7 执行，随 I4-close 落地」。前置已满足：I4-4 8/8 验证通过
（i44-rebuild-report.json summary）；U 2026-09-24 复核窗口报告后批准执行（「好的，执行吧」，
解除同日「暂缓，先出窗口报告」裁决）。statement_note：五张引用表阶段 1 后已空，但仍结构性
引用 documents，须同语句列出（满足 FK 结构规则，不使用 CASCADE）；重复 TRUNCATE 空表无副作用。

execution_gates 全部落实：
1. 守卫 i4-window.json 安装 + run_selfcheck 通过（i47-guard-selfcheck.json，
   config sha 必须与当前守卫文件及绑定常量一致）；
2. 导出前提核对：reset manifest export_binding 的 artifact-manifest.sha256 哈希 == 绑定值；
   I4-close 对照件三件（i4c-exports-manifest.json / crosswalk jsonl / docid-source-map）
   文件哈希与绑定常量及清单自述逐一一致；
3. 执行前逐表行数 == rows_before（blocks 1101 / documents 89 来自 manifest phases[2]；
   claims/claims_v2/claim_block_runs/claim_block_runs_v2 == 0 来自阶段 1 报告 post；
   漂移即停，不扩大删除）；
4. 单事务执行 manifest phases[2].statements 逐字一语句（语句/对象/行数三对账）；
5. 执行后六表行数 == 0；blocks/documents 无 owned 序列（manifest sequences_reset=[]）；
   保留序列（docs_id_seq/chinese_docs_id_seq）与见证表（docs/chinese_docs）不变；
6. 零模型调用（守卫阻断）；留出件零读取（守卫 forbidden_roots）。
产出 write-once：i4c-reset-phase2-report.json。
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
SELFCHECK = AUD / "i47-guard-selfcheck.json"
PHASE1_REPORT = AUD / "i47-reset-phase1-report.json"
I44_REPORT = AUD / "i44-rebuild-report.json"
EXPORTS_MANIFEST = AUD / "i4c-exports/i4c-exports-manifest.json"
CROSSWALK = AUD / "i4c-exports/i4c-old-evidence-locator-crosswalk.jsonl"
DOCID_MAP = AUD / "i4c-exports/i4c-docid-source-map.json"
OUT = AUD / "i4c-reset-phase2-report.json"

PG_DSN = "postgresql://postgres:postgres@127.0.0.1:5432/postgres"
GUARD_CFG = ING / "guards/i4-window.json"
GUARD_CFG_SHA = "e599d9b438e26d6d6df97074e8611091b8120b1292c287da7999b90327e58ba0"
BACKUP_DIR = ING / "backups/i4-final-20260923T1544Z"
BACKUP_MANIFEST_SHA = "085abf4c499bc0fc24a69abfe1e8d71634b4b9efbad097b81ca24d9f3bb648fb"
EXPORTS_MANIFEST_SHA = "61d378a51655feaadaae23bc59f796ecb6c185c6532d4ef581f38461bdabd6b1"
CROSSWALK_SHA = "a97fda27001695842b88a6d9817cf2559e314bb361f08839b3e6f7dc56a7b92b"
DOCID_MAP_SHA = "142273cb5f0093487eeb1af6bb12689bccb33bd31d5cf68dd7f729a5b67c7612"

PHASE = 2
# 五张引用表阶段 1 后已空，仍结构性引用 documents，须随语句同列（FK 结构规则，不用 CASCADE）
REFERENCE_TABLES_ZERO = ["claims", "claims_v2", "claim_block_runs", "claim_block_runs_v2"]
RETAINED_SEQS = ["public.docs_id_seq", "public.chinese_docs_id_seq"]  # not_in_scope
WITNESS_TABLES = ["docs", "chinese_docs"]  # C12 归属未定，默认保留（blocks/documents 本次在删）

STMT_TABLE_RE = re.compile(r"public\.([A-Za-z_][A-Za-z0-9_]*)")


def _abort(msg: str) -> None:
    raise SystemExit(f"拒绝（漂移即停）：{msg}")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    phase = next(p for p in manifest["phases"] if p["phase"] == PHASE)
    statements: list[str] = phase["statements"]
    if len(statements) != 1 or not statements[0].startswith("TRUNCATE public.") or not statements[0].endswith("RESTART IDENTITY;"):
        _abort("phases[2].statements 与锁定清单结构不符")
    assert phase["sequences_reset"] == []  # blocks/documents 无 owned 序列（fk_order_basis）
    # rows_before：blocks/documents 来自 manifest；四张引用表以阶段 1 报告 post==0 为准
    manifest_rows = {t["table"].removeprefix("public."): t["rows_before"] for t in phase["tables"]}
    if set(manifest_rows) != {"blocks", "documents"}:
        _abort(f"phases[2].tables 与锁定清单不符：{sorted(manifest_rows)}")
    p1 = json.loads(PHASE1_REPORT.read_text(encoding="utf-8"))
    p1_post = p1["post"]["table_counts_all_zero"]
    ref_drift = {t: p1_post.get(t) for t in REFERENCE_TABLES_ZERO if p1_post.get(t) != 0}
    if ref_drift:
        _abort(f"阶段 1 报告显示引用表非零：{ref_drift}")
    rows_before: dict[str, int] = {**manifest_rows, **dict.fromkeys(REFERENCE_TABLES_ZERO, 0)}

    # ── 门 1：守卫自检通过且配置未变 + I4-4 验证通过（phases[2].when 前置）──
    sc = json.loads(SELFCHECK.read_text(encoding="utf-8"))
    if not sc["passed"] or sc["phase"] != "i4-window":
        _abort("守卫自检未通过或阶段不符")
    cur_guard_sha = _sha(GUARD_CFG)
    if sc["config_sha256"] != cur_guard_sha or cur_guard_sha != GUARD_CFG_SHA:
        _abort("守卫配置自检后变更或与绑定常量不一致（漂移即停）")
    i44 = json.loads(I44_REPORT.read_text(encoding="utf-8"))
    s44 = i44["summary"]
    if not (s44["published"] == 8 and s44["active"] == 8 and s44["blocked"] == 0 and s44["all_new_build_active"] is True):
        _abort(f"I4-4 报告摘要与「8/8 验证通过」不符：{s44}")

    # ── 门 2：导出前提（备份 manifest + I4-close 对照件三件）────────────
    bm_path = BACKUP_DIR / "artifact-manifest.sha256"
    if _sha(bm_path) != BACKUP_MANIFEST_SHA:
        _abort("backup artifact-manifest.sha256 与 reset manifest export_binding 不一致")
    if _sha(EXPORTS_MANIFEST) != EXPORTS_MANIFEST_SHA:
        _abort("i4c-exports-manifest.json 与绑定常量不一致")
    exports = json.loads(EXPORTS_MANIFEST.read_text(encoding="utf-8"))
    export_checks: dict[str, object] = {}
    for path, const, rec in (
        (CROSSWALK, CROSSWALK_SHA, exports["crosswalk"]),
        (DOCID_MAP, DOCID_MAP_SHA, exports["docid_source_map"]),
    ):
        actual = _sha(path)
        if actual != const or actual != rec["sha256"]:
            _abort(f"对照件哈希不一致：{path.name}")
        export_checks[path.name] = actual
    cw = exports["crosswalk"]
    if cw["rows"] != 307 or cw["matched"] != 290 or cw["unmatched_missing_block"] != 0:
        _abort(f"crosswalk 清单自述与绑定事实不符：{cw}")
    crosswalk_lines = len(CROSSWALK.read_text(encoding="utf-8").splitlines())
    if crosswalk_lines != cw["rows"]:
        _abort(f"crosswalk 实测行数 {crosswalk_lines} ≠ 清单 {cw['rows']}")
    if exports["docid_source_map"]["documents_total"] != 89:
        _abort("docid_source_map 清单自述与绑定事实不符")
    if exports["inputs"]["backup_artifact_manifest_sha256"] != BACKUP_MANIFEST_SHA:
        _abort("exports manifest 引用的备份绑定与 reset manifest 不一致")

    # ── 门 3-5：单事务（前置核对 → 逐字执行 → 后置核对），异常即整体回滚 ──
    report: dict[str, object] = {
        "purpose": "I4-reset 阶段 2：manifest phases[2] 单语句 TRUNCATE 六表（U 2026-09-24 复核窗口报告后批准执行「好的，执行吧」，解除同日「暂缓，先出窗口报告」裁决）",
        "executed_at": datetime.now(tz).isoformat(timespec="seconds"),
        "manifest_sha256": _sha(RESET_MANIFEST),
        "statements_source": "i4-reset-manifest.json phases[2].statements（运行时读取逐字执行）",
        "when_precedent": {
            "i4_4_verified": True,
            "u_recheck_approval": "2026-09-24 窗口报告复核后批准执行（解除同日暂缓裁决）",
        },
        "export_binding_check": {
            "backup_artifact_manifest_sha256": BACKUP_MANIFEST_SHA,
            "exports_manifest_sha256": EXPORTS_MANIFEST_SHA,
            "crosswalk_sha256": CROSSWALK_SHA,
            "crosswalk_lines": crosswalk_lines,
            "docid_source_map_sha256": DOCID_MAP_SHA,
            "files": export_checks,
        },
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
            _abort("corpus schema 不存在——新链未重建，不满足 phases[2].when 前置")
        report["wal_lsn_before"] = row["lsn"]

        # 门 3：执行前逐表行数 == rows_before（漂移即停）
        pre_counts = {t: _count(cur, t) for t in rows_before}
        drift = {t: {"rows_before": rows_before[t], "now": n} for t, n in pre_counts.items() if n != rows_before[t]}
        if drift:
            _abort(f"执行前行数漂移：{drift}")
        # 三对账：语句 → 对象 → 行数
        objs = STMT_TABLE_RE.findall(statements[0])
        if set(objs) != set(rows_before):
            _abort(f"语句对象与 rows_before 集合不一致：{sorted(set(objs))} vs {sorted(rows_before)}")
        recon = [{"statement": statements[0], "objects": objs, "rows_before": dict(rows_before)}]
        seq_before = {s: _seq_state(cur, s) for s in RETAINED_SEQS}
        witnesses_before = {t: _count(cur, t) for t in WITNESS_TABLES}
        report["pre"] = {
            "table_counts": pre_counts,
            "statement_object_row_reconciliation": recon,
            "retained_sequences_before": seq_before,
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
        seq_after = {s: _seq_state(cur, s) for s in RETAINED_SEQS}
        if seq_after != seq_before:
            _abort(f"保留序列被改动：{seq_after} ≠ {seq_before}")
        witnesses_after = {t: _count(cur, t) for t in WITNESS_TABLES}
        if witnesses_after != witnesses_before:
            _abort(f"保留见证表行数变化：{witnesses_after} ≠ {witnesses_before}")
        cur.execute("SELECT pg_current_wal_lsn() AS lsn")
        report["wal_lsn_after"] = cur.fetchone()["lsn"]
        report["post"] = {
            "table_counts_all_zero": post_counts,
            "sequences_reset": phase["sequences_reset"],
            "retained_sequences_unchanged": RETAINED_SEQS,
            "witness_tables_after": witnesses_after,
        }
    # with 块正常退出 = 提交；任何异常已整体回滚且未写报告

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("sha256:", _sha(OUT)[:16], "…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
