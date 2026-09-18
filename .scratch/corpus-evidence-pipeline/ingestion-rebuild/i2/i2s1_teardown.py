"""I2-1 隔离临时对象清理（精确范围：仅 i2_sandbox_corpus 库内 corpus schema）。

纪律（任务验收门：隔离临时对象清理亦须精确范围）：
- 仅 DROP SCHEMA corpus CASCADE 于 i2_sandbox_corpus；不触碰 i0b2_verify_*、容器默认库、
  数据库本身（保留给 I2-2），更不触碰生产实例；
- fail-closed：实例含 apodex 库即拒绝；须显式 CONFIRM_TEARDOWN=i2_sandbox_corpus；
- 清理后核验：corpus schema 不存在、无残留用户表。

用法::

    CONFIRM_TEARDOWN=i2_sandbox_corpus CORPUS_I2_DSN=... .venv/bin/python -B i2s1_teardown.py
"""
from __future__ import annotations

import json
import os
import sys

import psycopg

SANDBOX_DB = "i2_sandbox_corpus"


def main() -> int:
    raw = os.environ.get("CORPUS_I2_DSN", "")
    if not raw or "corpus-guard" in raw:
        raise SystemExit("拒绝：CORPUS_I2_DSN 未设置或为守卫哨兵")
    if os.environ.get("CONFIRM_TEARDOWN") != SANDBOX_DB:
        raise SystemExit(f"拒绝：须显式 CONFIRM_TEARDOWN={SANDBOX_DB}")
    sandbox_dsn = f"postgresql://{raw.split('//', 1)[1].rsplit('/', 1)[0]}/{SANDBOX_DB}"
    with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        db_row = cur.fetchone()
        if db_row is None or db_row[0] != SANDBOX_DB:
            raise SystemExit("拒绝：current_database 非 i2_sandbox_corpus")
        cur.execute("SELECT datname FROM pg_database WHERE datallowconn")
        if "apodex" in {r[0] for r in cur.fetchall()}:
            raise SystemExit("拒绝：目标实例含 apodex 库（生产实例），禁止清理")
        cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = 'corpus'")
        if cur.fetchone() is None:
            print("corpus schema 不存在：无需清理")
            return 0
        cur.execute("DROP SCHEMA corpus CASCADE")
        cur.execute(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'corpus'"
        )
        residue_row = cur.fetchone()
        residue = residue_row[0] if residue_row is not None else -1
        if residue != 0:
            raise SystemExit(f"清理核验失败：corpus schema 残留对象 {residue}")
    print(json.dumps({"step": "i2s1_teardown", "dropped": "corpus schema (CASCADE)",
                      "database_kept": SANDBOX_DB, "residue": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
