"""I5-1 场景库创建（M8 启动，r5n m8_kickoff 授权范围）：corpus-db 隔离实例四个一次性库。

依据 tasks.md §3.8 I5-1 + U 2026-09-24 批准验证范围（全四场景 × 全部 8 个活动源；
源变化/新规则/复用解析在隔离环境执行，不触碰生产活动来源）。逐场景独立一次性库：
i51_s1_rerun（同源同版本重跑）/ i51_s2_srcchg（源变化）/ i51_s3_newrule（新规则 build）/
i51_s4_idxreb（复用解析重建索引）。生产 pg 容器（5432）零触碰。

纪律（沿 i2s1_apply.py 先例，fail-closed）：
- 目标仅 127.0.0.1:543；实例含 apodex 库 → 判定生产实例，拒绝；
- 缺 M2 验证库标记（i0b2_verify_postgres/i0b2_verify_apodex）→ 非预期容器，拒绝；
- 预期外数据库（白名单外）→ 拒绝；
- 任一场景库已含 corpus schema → 拒绝（不做 teardown，重演须先人工处置）；
- 凭据经 .env（CORPUS_DB_USER/CORPUS_DB_PASSWORD）注入，不写入任何文件。

用法（仓库根）::

    env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONPATH="$PWD" HOME="$HOME" \\
      PYTHONDONTWRITEBYTECODE=1 CORPUS_DB_USER=... CORPUS_DB_PASSWORD=... \\
      .venv/bin/python -B audits/i51_setup_dbs.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
REPO = HERE.parents[4]
SQL_PATH = BASE / "i2/sandbox_schema.sql"
HOST, PORT = "127.0.0.1", 543
SCENARIO_DBS = ("i51_s1_rerun", "i51_s2_srcchg", "i51_s3_newrule", "i51_s4_idxreb")
# 容器现状白名单：M2 验证库 + i2 沙箱 + G3 一次性库（已验证保留）+ 本批场景库。
EXPECTED_DBS = {
    "postgres",
    "template1",
    "i0b2_verify_postgres",
    "i0b2_verify_apodex",
    "i2_sandbox_corpus",
    "i4_g3_restore_20260924",
    *SCENARIO_DBS,
}
ZHCFG_MAPPING = "a,b,c,e,f,h,i,j,k,l,m,n,o,p,q,r,s,t,u,v,w,x,y,z"
OUT = HERE / "i51-setup-dbs-report.json"


def dsn(db: str) -> str:
    user = os.environ.get("CORPUS_DB_USER", "")
    pw = os.environ.get("CORPUS_DB_PASSWORD", "")
    if not user or not pw:
        raise SystemExit("拒绝：CORPUS_DB_USER/CORPUS_DB_PASSWORD 未注入")
    return f"postgresql://{user}:{pw}@{HOST}:{PORT}/{db}"


def main() -> int:
    if OUT.exists():
        raise SystemExit(f"拒绝：write-once 报告已存在 {OUT}")

    admin = dsn("postgres")
    with psycopg.connect(admin, autocommit=True) as conn, conn.cursor() as cur:
        # 连接端口按实际拨号值核验（容器内监听 5432，宿主映射 543；inet_server_port 为容器内端口）。
        if conn.info.port != PORT or conn.info.host != HOST:
            raise SystemExit(f"拒绝：实际连接 {conn.info.host}:{conn.info.port} ≠ {HOST}:{PORT}")
        cur.execute("SELECT datname FROM pg_database WHERE datallowconn")
        dbs = {r[0] for r in cur.fetchall()}
        if "apodex" in dbs:
            raise SystemExit("拒绝：目标实例含 apodex 库——判定为生产实例，禁止演练写入")
        if not (dbs & {"i0b2_verify_postgres", "i0b2_verify_apodex"}):
            raise SystemExit(f"拒绝：目标实例缺 M2 验证库标记（实际 {sorted(dbs)}）")
        extra = dbs - EXPECTED_DBS
        if extra:
            raise SystemExit(f"拒绝：目标实例出现预期外数据库 {sorted(extra)}（fail-closed）")

        created: list[str] = []
        for db in SCENARIO_DBS:
            if db not in dbs:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db)))
                created.append(db)

    results: dict[str, dict] = {}
    for db in SCENARIO_DBS:
        with psycopg.connect(dsn(db)) as conn, conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            if cur.fetchone()[0] != db:
                raise SystemExit(f"拒绝：current_database ≠ {db}")
            cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = 'corpus'")
            if cur.fetchone() is not None:
                raise SystemExit(f"拒绝：{db} 已含 corpus schema（重演须先人工处置）")
            cur.execute("SELECT 1 FROM pg_ts_config WHERE cfgname = 'zhcfg'")
            has_zhcfg = cur.fetchone() is not None
            if not has_zhcfg:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
                cur.execute("CREATE EXTENSION IF NOT EXISTS zhparser")
                cur.execute("CREATE TEXT SEARCH CONFIGURATION zhcfg (PARSER = zhparser)")
                cur.execute(
                    f"ALTER TEXT SEARCH CONFIGURATION zhcfg ADD MAPPING FOR {ZHCFG_MAPPING} WITH simple"
                )
            ddl = SQL_PATH.read_text(encoding="utf-8")
            cur.execute(sql.SQL(ddl))
            conn.commit()
            cur.execute(
                "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'corpus' AND c.relkind = 'r'"
            )
            tables = int(cur.fetchone()[0])
            cur.execute("SELECT count(*) FROM pg_indexes WHERE schemaname = 'corpus'")
            indexes = int(cur.fetchone()[0])
            results[db] = {
                "created_now": db in created,
                "zhcfg_created": not has_zhcfg,
                "tables": tables,
                "indexes": indexes,
            }

    report = {
        "artifact": "i51-setup-dbs",
        "target": {"host": HOST, "port": PORT, "instance": "corpus-db（隔离容器）"},
        "sql_path": str(SQL_PATH.relative_to(REPO)),
        "sql_sha256": hashlib.sha256(SQL_PATH.read_bytes()).hexdigest(),
        "databases": results,
        "summary": {"scenario_dbs": len(SCENARIO_DBS), "created_now": created},
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    print("sha256:", hashlib.sha256(OUT.read_bytes()).hexdigest()[:16], "…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
