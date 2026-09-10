"""One-shot migration of the web platform business DB: SQLite -> PostgreSQL.

Usage::

    uv run python scripts/migrate_sqlite_to_pg.py \
        --src sqlite+aiosqlite:///./server/dev.db \
        --dst postgresql+asyncpg://postgres:postgres@localhost:5432/apodex

    uv run python scripts/migrate_sqlite_to_pg.py --verify   # row-count check only

Design notes that matter:

* **Rows are moved through the ORM, not raw SQL.** SQLite stores ``Uuid`` as a
  32-char hex string, ``JSON`` as text, and ``LargeBinary`` as BLOB. Reading
  through the mapped classes lets SQLAlchemy normalise each side, so what lands
  in PostgreSQL is a native ``uuid`` / ``json`` / ``bytea`` value. A reflective
  copy would have shipped hex strings into ``uuid`` columns and double-encoded
  JSON.
* **Foreign keys are not enforced during the copy.** SQLite never enforced them,
  so the dev DB has accumulated orphans (runs pointing at deleted sessions,
  audit rows for deleted users). Copying with ``session_replication_role =
  replica`` preserves that history instead of silently dropping it; the script
  reports the orphan counts at the end so they can be cleaned up deliberately.
  The setting is per-connection, so the application's own connections are
  unaffected.
* **Parent tables are copied before children** and committed one table at a
  time, so a failure leaves the previous tables intact.
* **Naive datetimes are coerced to UTC.** The columns are declared
  ``DateTime(timezone=True)``; asyncpg rejects a mix of naive and aware values
  on those, and SQLite round-trips lose the offset on some rows.
* **The destination must be empty** unless ``--force`` is passed, and even then
  inserts are ``ON CONFLICT DO NOTHING``, so re-running cannot double the data.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from server.store import (  # noqa: E402  (sys.path setup must run first)
    Artifact,
    AuditLog,
    Run,
    Session,
    Turn,
    User,
    UserLLMConfig,
)

#: Child tables last — every entry depends only on tables above it.
COPY_ORDER: list[type[DeclarativeBase]] = [
    User,
    UserLLMConfig,
    Session,
    Run,
    Turn,
    Artifact,
    AuditLog,
]

#: Orphan checks reported after the copy, as ``(label, table, column, parent)``.
ORPHAN_CHECKS: list[tuple[str, str, str, str]] = [
    ("sessions.user_id", "sessions", "user_id", "users"),
    ("user_llm_configs.user_id", "user_llm_configs", "user_id", "users"),
    ("runs.user_id", "runs", "user_id", "users"),
    ("runs.session_id", "runs", "session_id", "sessions"),
    ("turns.session_id", "turns", "session_id", "sessions"),
    ("artifacts.run_id", "artifacts", "run_id", "runs"),
    ("audit_log.user_id", "audit_log", "user_id", "users"),
]

#: Tables whose ``id`` is a serial (``BigInteger`` + autoincrement). Their
#: sequences must be advanced after the copy — see :func:`_resync_sequences`.
SEQUENCE_TABLES: list[str] = ["turns", "audit_log"]

DEFAULT_SRC = "sqlite+aiosqlite:///./server/dev.db"


def _normalise(value: object) -> object:
    """Coerce SQLite-flavoured values into something asyncpg accepts."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _row_values(row: DeclarativeBase) -> dict[str, object]:
    """Column values of ``row`` as plain Python objects keyed by attribute."""
    return {
        attr.key: _normalise(getattr(row, attr.key))
        for attr in row.__mapper__.column_attrs  # type: ignore[attr-defined]
    }


async def _count_all(session: AsyncSession) -> dict[str, int]:
    counts: dict[str, int] = {}
    for model in COPY_ORDER:
        result = await session.execute(
            select(func.count()).select_from(model)  # type: ignore[arg-type]
        )
        counts[model.__tablename__] = int(result.scalar_one())
    return counts


async def _verify(src_url: str, dst_url: str) -> int:
    src_engine = create_async_engine(src_url)
    dst_engine = create_async_engine(dst_url)
    src_maker = async_sessionmaker(src_engine, expire_on_commit=False)
    dst_maker = async_sessionmaker(dst_engine, expire_on_commit=False)
    ok = True
    try:
        async with src_maker() as src, dst_maker() as dst:
            src_counts = await _count_all(src)
            dst_counts = await _count_all(dst)
        for model in COPY_ORDER:
            table = model.__tablename__
            s, d = src_counts[table], dst_counts[table]
            if s != d:
                ok = False
            print(f"{'OK ' if s == d else 'DIFF'} {table:<18} sqlite={s:<6} pg={d}")
    finally:
        await src_engine.dispose()
        await dst_engine.dispose()
    return 0 if ok else 1


async def _resync_sequences(dst_url: str) -> None:
    """Advance the serial sequences past the ids that were copied in.

    The copy supplies explicit primary keys, which never touch the sequence
    behind them. Left alone, the first new turn is handed ``id=2`` and collides
    with a row that already exists — surfacing as a 500 on ``POST /api/runs``.
    """
    engine = create_async_engine(dst_url)
    try:
        async with engine.connect() as conn:
            for table in SEQUENCE_TABLES:
                await conn.execute(
                    text(
                        "SELECT setval(pg_get_serial_sequence(:table, 'id'), "
                        f"coalesce((SELECT max(id) FROM {table}), 0))"
                    ),
                    {"table": table},
                )
            await conn.commit()
            rows = (
                await conn.execute(
                    text(
                        "SELECT sequencename, last_value FROM pg_sequences "
                        "WHERE schemaname = 'public' ORDER BY 1"
                    )
                )
            ).fetchall()
        print("\n序列同步：")
        for name, value in rows:
            print(f"  {name:<20} {value}")
    finally:
        await engine.dispose()


async def _report_orphans(dst_url: str) -> None:
    engine = create_async_engine(dst_url)
    try:
        async with engine.connect() as conn:
            print("\n孤儿行（SQLite 未强制外键遗留，已一并保留）：")
            for label, table, column, parent in ORPHAN_CHECKS:
                stmt = text(
                    f"SELECT count(*) FROM {table} "
                    f"WHERE {column} IS NOT NULL "
                    f"AND {column} NOT IN (SELECT id FROM {parent})"
                )
                n = int((await conn.execute(stmt)).scalar_one())
                print(f"  {label:<26} {n}")
    finally:
        await engine.dispose()


async def _migrate(src_url: str, dst_url: str, *, force: bool) -> int:
    src_engine = create_async_engine(src_url)
    dst_engine = create_async_engine(dst_url)
    src_maker = async_sessionmaker(src_engine, expire_on_commit=False)

    try:
        async with (
            src_maker() as src,
            dst_engine.connect() as conn,
        ):
            existing = int((await conn.execute(text("SELECT count(*) FROM users"))).scalar_one())
            if existing and not force:
                print(f"目标库非空（users={existing}），确认要写入请加 --force")
                return 1

            # Per-connection: the app's own connections still enforce FKs.
            await conn.exec_driver_sql("SET session_replication_role = replica")

            for model in COPY_ORDER:
                rows = (
                    (await src.execute(select(model))).scalars().all()  # type: ignore[arg-type]
                )
                payload = [_row_values(row) for row in rows]
                if payload:
                    stmt = pg_insert(model.__table__).values(payload)
                    await conn.execute(stmt.on_conflict_do_nothing())
                await conn.commit()
                print(f"copied {model.__tablename__:<18} {len(payload)} rows")

        await _resync_sequences(dst_url)
        print("\n校验：")
        code = await _verify(src_url, dst_url)
        await _report_orphans(dst_url)
        return code
    finally:
        await src_engine.dispose()
        await dst_engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate the business DB to PostgreSQL")
    parser.add_argument("--src", default=DEFAULT_SRC, help="源 SQLite URL")
    parser.add_argument(
        "--dst",
        default=None,
        help="目标 PostgreSQL URL，默认取 SERVER_DATABASE_URL",
    )
    parser.add_argument("--force", action="store_true", help="目标库非空时也继续")
    parser.add_argument("--verify", action="store_true", help="只对比行数")
    args = parser.parse_args()

    dst_url = args.dst
    if dst_url is None:
        from server.config import get_config

        dst_url = get_config().database_url
    if not dst_url.startswith("postgresql"):
        print(f"目标不是 PostgreSQL: {dst_url}")
        return 1

    print(f"src = {args.src}\ndst = {dst_url}\n")
    if args.verify:
        return asyncio.run(_verify(args.src, dst_url))
    return asyncio.run(_migrate(args.src, dst_url, force=args.force))


if __name__ == "__main__":
    raise SystemExit(main())
