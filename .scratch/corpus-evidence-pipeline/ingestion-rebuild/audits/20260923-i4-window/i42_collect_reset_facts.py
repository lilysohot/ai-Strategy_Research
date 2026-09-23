"""I4-2 事实采集：生产库（127.0.0.1:5432/postgres）**只读**收集 reset-limited 清单事实。

产出（write-once）：``i42-reset-facts.json``——

- 九张旧链表 + 两张遗留表的精确行数与对象身份；
- 全部 FK 依赖边（conname / 从表 → 主表），据此推出**精确清理顺序**；
- 序列归属（owned_by），区分 reset 范围序列与保留表序列；
- 保留项核对：扩展清单、corpus schema 缺席性（迁移前状态）。

fail-closed：连接只读（default_transaction_read_only 会话级设置）；任何异常即中止，
不写半截产物。零模型调用、零写库。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg

ROOT = Path("/home/administrator/FrontierAgent")
AUD = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window"
DSN = "postgresql://postgres:postgres@127.0.0.1:5432/postgres"

RESET_TABLES = [
    "blocks",
    "documents",
    "claims",
    "claims_v2",
    "claim_block_runs",
    "claim_block_runs_v2",
    "corpus_evidence_runs",
    "ingest_runs",
    "ingest_failures",
]
LEGACY_TABLES = ["docs", "chinese_docs"]  # public 遗留表，C12 待 U 单独裁决，默认保留


def main() -> int:
    facts: dict[str, object] = {}
    with psycopg.connect(DSN, autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SELECT current_database(), version(), pg_current_wal_lsn()")
        row = cur.fetchone()
        facts["target"] = {
            "database": row[0],
            "version": row[1].split(",")[0],
            "wal_lsn_at_collect": row[2],
        }

        # 逐表行数（精确计数）
        counts: dict[str, int] = {}
        for t in RESET_TABLES + LEGACY_TABLES:
            cur.execute(f"SELECT count(*) FROM public.{t}")  # noqa: S608 — 表名来自白名单
            counts[t] = cur.fetchone()[0]
        facts["row_counts"] = counts

        # FK 依赖边（reset 表之间 + 指向保留表的边）
        cur.execute(
            """
            SELECT conname, conrelid::regclass::text, confrelid::regclass::text
            FROM pg_constraint
            WHERE contype = 'f'
              AND connamespace = 'public'::regnamespace
            ORDER BY conrelid::regclass::text, conname
            """
        )
        fks = [{"constraint": r[0], "from": r[1], "to": r[2]} for r in cur.fetchall()]
        facts["foreign_keys"] = fks

        # 序列归属（pg_depend deptype='a'：序列被表列自动拥有）
        cur.execute(
            """
            SELECT s.relname, t.relname
            FROM pg_class s
            JOIN pg_depend d ON d.objid = s.oid AND d.deptype = 'a'
            JOIN pg_class t ON t.oid = d.refobjid
            WHERE s.relnamespace = 'public'::regnamespace AND s.relkind = 'S'
            ORDER BY s.relname
            """
        )
        seqs = [{"sequence": r[0], "owned_by": r[1]} for r in cur.fetchall()]
        facts["sequences"] = seqs

        # 迁移前状态：corpus schema 必须缺席（fail-closed 前提）
        cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = 'corpus'")
        facts["corpus_schema_present"] = cur.fetchone() is not None

        # 保留项：扩展清单
        cur.execute("SELECT extname, extversion FROM pg_extension ORDER BY extname")
        facts["extensions"] = [{"name": r[0], "version": r[1]} for r in cur.fetchall()]

    # 清理顺序推导：拓扑序（被引用者后清）。声明为可复核事实而非自动执行逻辑。
    fk_edges = [
        (f["from"].split(".")[-1], f["to"].split(".")[-1])
        for f in fks
        if f["from"].split(".")[-1] in RESET_TABLES and f["to"].split(".")[-1] in RESET_TABLES
    ]
    facts["reset_fk_edges_within_scope"] = sorted(fk_edges)

    tz = timezone(timedelta(hours=8))
    payload = {
        "purpose": "I4-2 reset-limited 清单事实（生产只读采集）",
        "collected_at": datetime.now(tz).isoformat(timespec="seconds"),
        "facts": facts,
    }
    out = AUD / "i42-reset-facts.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(facts, ensure_ascii=False, indent=2)[:4000])
    print("sha256:", hashlib.sha256(out.read_bytes()).hexdigest()[:16], "…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
