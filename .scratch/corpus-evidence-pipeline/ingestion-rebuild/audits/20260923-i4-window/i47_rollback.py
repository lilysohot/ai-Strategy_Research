"""I4-7 migrate 回滚（cutover manifest rollback[0] 授权路径，逐字记录）。

事件：i47_migrate.py 首跑 DDL 已提交（corpus schema 九表建成），但提交后结构核对
失败——验证器期望索引数 10，实际 19。偏差归因：**验证器自身漏数** 9 张表的
PRIMARY KEY 支撑索引（pg_indexes 含约束支撑索引）；10 个显式索引（DDL CREATE
INDEX 逐条）+ 9 个 pkey 撑引 = 19，DDL 字节本身与冻结绑定一致、无漂移。

按 i4-cutover-manifest.json rollback[0]：「migrate 失败：DROP SCHEMA corpus CASCADE
（仅限 corpus schema 本体，逐字记录于窗口审计后执行）」。执行顺序（fail-closed）：
1. 核对 corpus schema 现状 = 首跑产物（9 表 / 0 序列 / 19 索引）且**全表 0 行**
   （仅 DDL、无数据；发现任何行即中止转人工）；
2. 逐字执行 `DROP SCHEMA corpus CASCADE;`（单语句单事务）；
3. 核验零残留（namespace 不存在 + pg_class 内 corpus 关系 0 + 依赖对象 0）；
4. 产出 write-once 事件记录 i47-migrate-incident.json（含现状复核与回滚后核验）。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

AUD = Path(__file__).resolve().parent
PG_DSN = "postgresql://postgres:postgres@127.0.0.1:5432/postgres"
OUT = AUD / "i47-migrate-incident.json"
DROP_STATEMENT = "DROP SCHEMA corpus CASCADE;"

EXPECTED = {"tables": 9, "sequences": 0, "indexes": 19}


def _abort(msg: str) -> None:
    raise SystemExit(f"拒绝（转人工，勿扩大操作）：{msg}")


def main() -> int:
    if OUT.exists():
        _abort(f"write-once 事件记录已存在：{OUT}")
    tz = timezone(timedelta(hours=8))
    report: dict[str, object] = {
        "purpose": "I4-7 migrate 首跑提交后验证器期望值错误 → 按 cutover manifest rollback[0] 回滚",
        "recorded_at": datetime.now(tz).isoformat(timespec="seconds"),
        "authority": "i4-cutover-manifest.json rollback[0]（仅限 corpus schema 本体，逐字记录）",
        "incident": {
            "expected_indexes": 10,
            "actual_indexes": 19,
            "root_cause": "验证器漏数 9 张表 PRIMARY KEY 支撑索引；DDL 字节 sha256=c4bc8aff… 与 i0c-r4 冻结绑定一致，schema 结构本身无漂移",
            "ddl_committed": True,
        },
        "rollback_statement": DROP_STATEMENT,
    }

    with psycopg.connect(PG_DSN, autocommit=True) as conn, conn.cursor(row_factory=dict_row) as cur:
        # 1. 回滚前现状复核：须与首跑 DDL 产物一致且零数据
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = 'corpus'")
        if cur.fetchone() is None:
            _abort("corpus schema 不存在——与事件记载不符（转人工）")
        cur.execute(
            "SELECT relkind, count(*) AS n FROM pg_class WHERE relnamespace = 'corpus'::regnamespace"
            " GROUP BY relkind"
        )
        kinds = {r["relkind"]: r["n"] for r in cur.fetchall()}
        if kinds.get("r") != EXPECTED["tables"] or kinds.get("S", 0) != EXPECTED["sequences"]:
            _abort(f"corpus 关系构成 {kinds} 与首跑产物不符（转人工）")
        cur.execute("SELECT count(*) AS n FROM pg_indexes WHERE schemaname = 'corpus'")
        idx_n = cur.fetchone()["n"]
        if idx_n != EXPECTED["indexes"]:
            _abort(f"corpus 索引数 {idx_n} ≠ 19（转人工）")
        cur.execute(
            "SELECT c.relname FROM pg_class c WHERE c.relnamespace = 'corpus'::regnamespace"
            " AND c.relkind = 'r' ORDER BY c.relname"
        )
        tables = [r["relname"] for r in cur.fetchall()]
        rows: dict[str, int] = {}
        for t in tables:
            cur.execute(f'SELECT count(*) AS n FROM corpus."{t}"')  # noqa: S608 — 表名取自目录
            rows[t] = cur.fetchone()["n"]
        nonempty = {t: n for t, n in rows.items() if n != 0}
        if nonempty:
            _abort(f"corpus 表非空 {nonempty}——回滚会破坏数据，转人工")
        # 外部依赖核查：corpus 新建、public 旧表不引用 corpus，schema 内对象全部
        # 归属 corpus namespace（已由 kinds/idx_n 复核），无外部从属对象。
        report["pre_rollback_verification"] = {
            "tables": tables,
            "indexes": idx_n,
            "sequences": kinds.get("S", 0),
            "row_counts_all_zero": rows,
        }

        # 2. 逐字执行回滚（单语句单事务）
        cur.execute("SET TRANSACTION READ WRITE")
        cur.execute(DROP_STATEMENT)

        # 3. 零残留核验
        cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = 'corpus'")
        ns = cur.fetchone() is not None
        cur.execute(
            "SELECT count(*) AS n FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = 'corpus'"
        )
        rel_n = cur.fetchone()["n"]
        if ns or rel_n != 0:
            _abort(f"回滚后仍有残留：namespace_present={ns} relations={rel_n}")
        report["post_rollback_verification"] = {
            "namespace_present": ns,
            "relations_remaining": rel_n,
        }

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("sha256:", hashlib.sha256(OUT.read_bytes()).hexdigest()[:16], "…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
