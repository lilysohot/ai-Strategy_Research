"""I2-1 隔离库 DDL 应用脚本（fail-closed 目标校验 → 建库 → 建表）。

依据：design-review.json（i0c-r1 冻结）§i0c_2_parameters.i2_targets：
- 演练库 = corpus-db 容器新建 i2_sandbox_corpus；
- i0b2_verify_postgres / i0b2_verify_apodex（M2 验证库）只读排除，不得作为可改写目标；
- 原库 pg:5432 与生产 postgres 库零触碰（apodex 库存在性作反证校验）。

用法（仓库根，守卫 env；凭据经 .env CORPUS_DB_PASSWORD 注入，不入文件）::

    set -a && . ./.env && set +a
    CORPUS_I2_DSN="postgresql://postgres:${CORPUS_DB_PASSWORD}@127.0.0.1:543/postgres" \\
    env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONPATH="$PWD" HOME="$HOME" \\
      PYTHONDONTWRITEBYTECODE=1 CORPUS_I2_DSN="$CORPUS_I2_DSN" \\
      .venv/bin/python -B .scratch/corpus-evidence-pipeline/ingestion-rebuild/i2/i2s1_apply.py

fail-closed：CORPUS_I2_DSN 未设或指向被投毒的 CORPUS_DSN 哨兵 → 拒绝；目标非
127.0.0.1:543 → 拒绝（守卫允许清单）；目标实例含 apodex 库 → 判定生产实例，拒绝；
i2_sandbox_corpus 已含 corpus schema → 拒绝（重演先 i2s1_teardown.py）。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql

REPO = Path(__file__).resolve().parents[4]
SQL_PATH = REPO / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i2/sandbox_schema.sql"
SANDBOX_DB = "i2_sandbox_corpus"
EXPECTED_CONTAINER_DBS = {"postgres", "template1", "i0b2_verify_postgres", "i0b2_verify_apodex",
                          SANDBOX_DB}
ZHCFG_MAPPING = "a,b,c,e,f,h,i,j,k,l,m,n,o,p,q,r,s,t,u,v,w,x,y,z"


def _dsn_parts() -> tuple[str, int, str, str]:
    raw = os.environ.get("CORPUS_I2_DSN", "")
    if not raw:
        raise SystemExit("拒绝：CORPUS_I2_DSN 未设置（CORPUS_DSN 被守卫投毒，不得使用）")
    if "corpus-guard" in raw:
        raise SystemExit("拒绝：CORPUS_I2_DSN 指向守卫哨兵 DSN")
    if not raw.startswith("postgresql://"):
        raise SystemExit("拒绝：CORPUS_I2_DSN 必须为 postgresql:// URL 形式")
    rest = raw[len("postgresql://"):]
    _, _, hostport_db = rest.rpartition("@")  # 凭据段仅用于切分，不落日志
    hostport, _, dbname = hostport_db.partition("/")
    host, _, port = hostport.partition(":")
    if host != "127.0.0.1" or port != "543":
        raise SystemExit(f"拒绝：目标 {host}:{port} 不在守卫允许清单（127.0.0.1:543）")
    return host, int(port), dbname or "postgres", raw


def _check_target_instance(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT datname FROM pg_database WHERE datallowconn")
        dbs = {row[0] for row in cur.fetchall()}
    if "apodex" in dbs:
        raise SystemExit("拒绝：目标实例含 apodex 库——判定为生产实例（pg:5432），禁止演练写入")
    if not (dbs & {"i0b2_verify_postgres", "i0b2_verify_apodex"}):
        raise SystemExit(
            f"拒绝：目标实例缺 M2 验证库标记（实际 {sorted(dbs)}）——非预期 corpus-db 容器"
        )
    extra = dbs - EXPECTED_CONTAINER_DBS
    if extra:
        raise SystemExit(f"拒绝：目标实例出现预期外数据库 {sorted(extra)}（fail-closed）")


def main() -> int:
    host, port, admin_db, raw_dsn = _dsn_parts()
    admin_dsn = f"postgresql://{raw_dsn.split('//', 1)[1].rsplit('/', 1)[0]}/{admin_db}"
    sandbox_dsn = f"postgresql://{admin_dsn.split('//', 1)[1].rsplit('/', 1)[0]}/{SANDBOX_DB}"

    with psycopg.connect(admin_dsn, autocommit=True) as conn, conn.cursor() as cur:
        _check_target_instance(conn)
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (SANDBOX_DB,))
        exists = cur.fetchone() is not None
        if not exists:
            cur.execute(f'CREATE DATABASE "{SANDBOX_DB}"')
            print(f"created database {SANDBOX_DB}")
        else:
            print(f"database {SANDBOX_DB} exists: reuse（corpus schema 存在性在沙箱连接内校验）")

    with psycopg.connect(sandbox_dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = 'corpus'")
        if cur.fetchone() is not None:
            raise SystemExit("拒绝：i2_sandbox_corpus 已含 corpus schema（重演须先 i2s1_teardown.py）")
        cur.execute("SELECT current_database(), inet_server_port()::text, version()")
        row = cur.fetchone()
        if row is None:
            raise SystemExit("拒绝：目标实例元数据不可读")
        db_name, _srv_port, version = row
        if db_name != SANDBOX_DB:
            raise SystemExit(f"拒绝：current_database={db_name!r} ≠ {SANDBOX_DB!r}")
        cur.execute("SELECT extname, extversion FROM pg_extension ORDER BY 1")
        pre_ext = dict(cur.fetchall())
        cur.execute("SELECT 1 FROM pg_ts_config WHERE cfgname = 'zhcfg'")
        has_zhcfg = cur.fetchone() is not None
        if not has_zhcfg:
            # 扩展先于 zhcfg（zhparser 解析器须先安装）；sandbox_schema.sql 中
            # 的 CREATE EXTENSION IF NOT EXISTS 幂等重入无害。
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            cur.execute("CREATE EXTENSION IF NOT EXISTS zhparser")
            cur.execute("CREATE TEXT SEARCH CONFIGURATION zhcfg (PARSER = zhparser)")
            cur.execute(
                f"ALTER TEXT SEARCH CONFIGURATION zhcfg ADD MAPPING FOR {ZHCFG_MAPPING} WITH simple"
            )
        ddl = SQL_PATH.read_text(encoding="utf-8")
        cur.execute(sql.SQL(ddl))
        cur.execute(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'corpus' AND c.relkind = 'r'"
        )
        count_row = cur.fetchone()
        tables = int(count_row[0]) if count_row is not None else -1
        cur.execute("SELECT count(*) FROM pg_indexes WHERE schemaname = 'corpus'")
        idx_row = cur.fetchone()
        indexes = int(idx_row[0]) if idx_row is not None else -1

    summary = {
        "step": "i2s1_apply",
        "target": {"host": host, "port": port, "database": SANDBOX_DB, "server_version": version},
        "zhcfg_created": not has_zhcfg,
        "pre_extensions": pre_ext,
        "tables_created": tables,
        "indexes_created": indexes,
        "sql_sha256": hashlib.sha256(ddl.encode()).hexdigest(),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
