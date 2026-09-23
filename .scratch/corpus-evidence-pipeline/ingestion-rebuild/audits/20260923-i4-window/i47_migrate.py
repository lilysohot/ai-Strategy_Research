"""I4-7 migrate：postgres 库（127.0.0.1:5432）新建 corpus schema——i0c-r1 冻结 DDL 九表。

依据 i4-cutover-manifest.json change_list_migrate[0]（U 2026-09-23 停写窗口批准）：
「postgres 库执行 i2/sandbox_schema.sql（CREATE SCHEMA corpus + 九表 DDL + 扩展幂等 +
zhcfg 条件创建），仅建 schema 不搬数据」。零模型调用；public 旧表零写入。

门禁（fail-closed，任何一项不满足即中止，不落半截产物）：
- G1 目标核验：CORPUS_WINDOW_DSN 指向 127.0.0.1:5432/postgres（凭据不落日志）；
- G2 冻结绑定：DDL 字节 sha256 == i0c-r4 绑定值（i0c-r5 声明字节未变沿用）；
- G3 前提：corpus schema 缺席；zhcfg 基线等价（24 token 全→simple，含 'm' 数词，
  自定义词典 0 行——20260923-i4-window/i47_zhcfg_probe.py 两库实测一致）；
- G4 停写零漂移：public 九表 + 两遗留表行数 == i42-reset-facts.json 事实值；
- G5 单事务执行 DDL，提交后结构核对：9 表 / 19 索引（10 个显式 CREATE INDEX
  + 9 张表 PRIMARY KEY 支撑索引——pg_indexes 含约束撑引，首跑事件见
  i47-migrate-incident.json）/ 0 序列，且列、约束、索引与沙箱库
  i2_sandbox_corpus.corpus（权威同构参照）逐字段一致；
- G6 write-once：i47-migrate-report.json 已存在即拒绝。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

ROOT = Path("/home/administrator/FrontierAgent")
ING = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
AUD = ING / "audits/20260923-i4-window"
SQL_PATH = ING / "i2/sandbox_schema.sql"
CUTOVER = ING / "i4-cutover-manifest.json"
FACTS = AUD / "i42-reset-facts.json"
OUT = AUD / "i47-migrate-report.json"

# G2：i0c-r4 binding 值（r5 声明 sandbox_schema.sql 字节未变，循 r4 核验）
EXPECTED_DDL_SHA = "c4bc8aff02ccbc62f383356c7456200935e7dfe3a6a8158e6357dc800fb32eb9"
EXPECTED_CHAIN_HEAD = "i0c-r5g"
EXPECTED_CHAIN_HEAD_SHA = (
    "5ef07ef0244f2f197a54f35eb63942f08741d30a778b962f0e12ee9f0bff0eb6"
)

PG_DSN = "postgresql://postgres:postgres@127.0.0.1:5432/postgres"
SBX_DSN = "postgresql://postgres:postgres@127.0.0.1:543/i2_sandbox_corpus"

ZHCFG_TOKENS = set("a,b,c,e,f,h,i,j,k,l,m,n,o,p,q,r,s,t,u,v,w,x,y,z".split(","))
EXPECTED_TABLES = 9
# 19 = 10 个显式 CREATE INDEX + 9 张表 PRIMARY KEY 支撑索引（pg_indexes 计入撑引；
# 首跑误设 10 → 触发 rollback[0]，见 i47-migrate-incident.json）
EXPECTED_INDEXES = 19

RESET_TABLES = [
    "blocks", "documents", "claims", "claims_v2", "claim_block_runs",
    "claim_block_runs_v2", "corpus_evidence_runs", "ingest_runs", "ingest_failures",
]
LEGACY_TABLES = ["docs", "chinese_docs"]

COLUMNS_SQL = """
SELECT table_name, column_name, ordinal_position, data_type, udt_name, is_nullable,
       column_default, is_generated, character_maximum_length
FROM information_schema.columns
WHERE table_schema = 'corpus'
ORDER BY table_name, ordinal_position
"""
CONSTRAINTS_SQL = """
SELECT conname, conrelid::regclass::text AS tbl, contype, pg_get_constraintdef(oid) AS def
FROM pg_constraint
WHERE connamespace = 'corpus'::regnamespace
ORDER BY conrelid::regclass::text, conname
"""
INDEXES_SQL = """
SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'corpus' ORDER BY indexname
"""


def _abort(msg: str) -> None:
    raise SystemExit(f"拒绝（漂移/前提不成立即停）：{msg}")


def _g1_target_dsn() -> str:
    raw = os.environ.get("CORPUS_WINDOW_DSN", "")
    if not raw:
        _abort("CORPUS_WINDOW_DSN 未设置（cutover manifest target.dsn_env）")
    if not raw.startswith("postgresql://"):
        _abort("CORPUS_WINDOW_DSN 必须为 postgresql:// URL 形式")
    rest = raw[len("postgresql://"):]
    _, _, hostport_db = rest.rpartition("@")
    hostport, _, dbname = hostport_db.partition("/")
    host, _, port = hostport.partition(":")
    if (host, port, dbname) != ("127.0.0.1", "5432", "postgres"):
        _abort(f"目标 {host}:{port}/{dbname} ≠ 127.0.0.1:5432/postgres（cutover manifest target）")
    return raw


def _zhcfg_baseline(cur: psycopg.Cursor) -> dict[str, object]:
    cur.execute("SELECT 'zhcfg'::regconfig::oid AS oid")
    row = cur.fetchone()
    assert row is not None
    cur.execute(
        "SELECT m.maptokentype, d.dictname FROM pg_ts_config_map m"
        " JOIN pg_ts_dict d ON d.oid = m.mapdict WHERE m.mapcfg = %s::regconfig",
        (row["oid"],),
    )
    mapping = {r["maptokentype"]: r["dictname"] for r in cur.fetchall()}
    tokens = {chr(t) if isinstance(t, int) else str(t) for t in mapping}
    cur.execute("SELECT count(*) AS n FROM zhparser.zhprs_custom_word")
    custom = cur.fetchone()["n"]
    ok = tokens == ZHCFG_TOKENS and set(mapping.values()) == {"simple"} and custom == 0
    return {
        "oid": row["oid"],
        "token_count": len(mapping),
        "all_simple": set(mapping.values()) == {"simple"},
        "missing_tokens": sorted(ZHCFG_TOKENS - tokens),
        "custom_words": custom,
        "baseline_ok": ok,
    }


def _g4_zero_drift(cur: psycopg.Cursor, facts_counts: dict[str, int]) -> dict[str, int]:
    now: dict[str, int] = {}
    for t in RESET_TABLES + LEGACY_TABLES:
        cur.execute(f"SELECT count(*) AS n FROM public.{t}")  # noqa: S608 — 表名来自清单白名单
        now[t] = cur.fetchone()["n"]
    drifted = {t: {"recorded": facts_counts[t], "now": now[t]} for t in now if now[t] != facts_counts.get(t)}
    if drifted:
        _abort(f"public 表行数相对 i42-reset-facts.json 漂移：{drifted}")
    return now


def _snapshot_structure(cur: psycopg.Cursor) -> dict[str, object]:
    cur.execute(COLUMNS_SQL)
    columns = [dict(r) for r in cur.fetchall()]
    cur.execute(CONSTRAINTS_SQL)
    constraints = [dict(r) for r in cur.fetchall()]
    cur.execute(INDEXES_SQL)
    indexes = [dict(r) for r in cur.fetchall()]
    cur.execute(
        "SELECT count(*) AS n FROM pg_class WHERE relnamespace = 'corpus'::regnamespace"
        " AND relkind = 'r'"
    )
    tables = cur.fetchone()["n"]
    cur.execute(
        "SELECT count(*) AS n FROM pg_class WHERE relnamespace = 'corpus'::regnamespace"
        " AND relkind = 'S'"
    )
    sequences = cur.fetchone()["n"]
    return {
        "tables": tables,
        "sequences": sequences,
        "columns": columns,
        "constraints": constraints,
        "indexes": indexes,
    }


def main() -> int:
    if OUT.exists():
        _abort(f"write-once 报告已存在：{OUT}")
    tz = timezone(timedelta(hours=8))
    cutover = json.loads(CUTOVER.read_text(encoding="utf-8"))
    if cutover["code_version_binding"]["freeze_chain_head"] != EXPECTED_CHAIN_HEAD:
        _abort("cutover manifest 链头 ≠ i0c-r5g")
    if cutover["code_version_binding"]["chain_head_sha256"] != EXPECTED_CHAIN_HEAD_SHA:
        _abort("cutover manifest 链头 sha ≠ i0c-r5g 快照")

    ddl = SQL_PATH.read_text(encoding="utf-8")
    ddl_sha = hashlib.sha256(ddl.encode()).hexdigest()
    if ddl_sha != EXPECTED_DDL_SHA:
        _abort(f"DDL sha {ddl_sha} ≠ i0c-r4 冻结绑定值")

    dsn = _g1_target_dsn()
    report: dict[str, object] = {
        "purpose": "I4-7 migrate：postgres 库新建 corpus schema（i0c-r1 冻结 DDL 九表），仅建 schema 不搬数据",
        "executed_at": datetime.now(tz).isoformat(timespec="seconds"),
        "guard_config": "guards/i4-window.json",
        "guard_config_sha256": hashlib.sha256(
            (ING / "guards/i4-window.json").read_bytes()
        ).hexdigest(),
        "target": cutover["target"],
        "ddl": {
            "path": str(SQL_PATH.relative_to(ROOT)),
            "sha256": ddl_sha,
            "frozen": "i0c-r4 binding（i0c-r5 声明字节未变沿用；cutover manifest ddl.frozen_in=i0c-r1 布局）",
        },
        "credentials_in_report": False,
        "prior_incident": {
            "record": "i47-migrate-incident.json",
            "summary": "首跑 DDL 提交后验证器索引期望值错误（10 vs 19），按 cutover manifest rollback[0] 逐字 DROP SCHEMA corpus CASCADE，零残留核验通过后重跑本报告",
        },
    }

    # ── 前提门禁（单连接内先校验，全部通过才执行 DDL）────────────────
    with psycopg.connect(dsn) as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT current_database() AS db, version() AS ver, pg_current_wal_lsn() AS lsn")
        tgt = cur.fetchone()
        assert tgt is not None
        if tgt["db"] != "postgres":
            _abort(f"current_database={tgt['db']!r} ≠ postgres")
        cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = 'corpus'")
        if cur.fetchone() is not None:
            _abort("corpus schema 已存在（重演须先按 cutover manifest rollback 逐字记录后 DROP）")
        ext = {"pg_trgm", "plpgsql", "vector", "zhparser"}
        cur.execute("SELECT extname FROM pg_extension")
        have = {r["extname"] for r in cur.fetchall()}
        if not ext <= have:
            _abort(f"扩展缺失：{sorted(ext - have)}")
        zhcfg = _zhcfg_baseline(cur)
        if not zhcfg["baseline_ok"]:
            _abort(f"zhcfg 基线不等价（i47_zhcfg_probe 先例：两库应一致）：{zhcfg}")
        facts = json.loads(FACTS.read_text(encoding="utf-8"))["facts"]
        counts_now = _g4_zero_drift(cur, facts["row_counts"])

        # ── G5：单事务执行 DDL（zhcfg 已等价存在 → 条件创建为无操作，不改任何既有对象）──
        cur.execute(sql.SQL(ddl))
    conn.close()

    # ── 提交后结构核对（生产侧 + 沙箱参照侧，均只读）─────────────────
    with psycopg.connect(PG_DSN, autocommit=True) as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        prod = _snapshot_structure(cur)
        cur.execute("SELECT pg_current_wal_lsn() AS lsn")
        wal_after = cur.fetchone()["lsn"]
    with psycopg.connect(SBX_DSN, autocommit=True) as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        sbx = _snapshot_structure(cur)

    if prod["tables"] != EXPECTED_TABLES:
        _abort(f"corpus 表数 {prod['tables']} ≠ {EXPECTED_TABLES}")
    if len(prod["indexes"]) != EXPECTED_INDEXES:
        _abort(f"corpus 索引数 {len(prod['indexes'])} ≠ {EXPECTED_INDEXES}")
    if prod["sequences"] != 0:
        _abort(f"corpus 序列数 {prod['sequences']} ≠ 0（DDL 不含 serial）")
    for key in ("columns", "constraints", "indexes"):
        if prod[key] != sbx[key]:
            _abort(f"结构核对失败（{key} 与沙箱库 corpus schema 不一致）")

    report.update(
        {
            "server_version": tgt["ver"].split(",")[0],
            "wal_lsn_before": tgt["lsn"],
            "wal_lsn_after": wal_after,
            "preconditions": {
                "corpus_schema_absent": True,
                "extensions_present": sorted(ext),
                "zhcfg_baseline": zhcfg,
                "zhcfg_created": False,
                "zhcfg_note": "postgres 库既有 zhcfg（旧链 initdb 产物）与沙箱基线逐字段一致，条件创建无操作",
                "zero_drift_row_counts": counts_now,
            },
            "structure_check": {
                "tables": prod["tables"],
                "sequences": prod["sequences"],
                "indexes": [i["indexname"] for i in prod["indexes"]],
                "columns_identical_to_sandbox": True,
                "constraints_identical_to_sandbox": True,
                "indexes_identical_to_sandbox": True,
                "sandbox_reference": "i2_sandbox_corpus.corpus（i0c-r1 同构权威参照，只读比对）",
            },
            "columns_dump": prod["columns"],
            "constraints_dump": prod["constraints"],
            "indexes_dump": prod["indexes"],
        }
    )
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("columns_dump", "constraints_dump", "indexes_dump")}, ensure_ascii=False, indent=2))
    print("sha256:", hashlib.sha256(OUT.read_bytes()).hexdigest()[:16], "…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
