"""Explicit PostgreSQL integration entry for the Web business-data work (DATA-00).

``tests/conftest.py`` forces every test under ``tests/`` onto a throwaway SQLite
file. That is the right default for the existing suite, but it makes PostgreSQL
behaviour — NUMERIC precision, transactional DDL, unique constraints, concurrent
revisions — unverifiable, and those are exactly the properties DATA-02/03/05/06
depend on. This directory is the opt-in escape hatch:

* it is **off** unless ``PG_INTEGRATION=1``;
* when on, it **fails closed** unless the DSN is PostgreSQL *and* the database
  name is a registered test database (never ``apodex``, never ``postgres``);
* it overrides the SQLite fixture instead of working around it, so a test in
  this directory can never silently run against SQLite.

Running it against the shared business database is the failure mode the
environment plan calls out explicitly: a second process reconciles orphan runs
by scanning ``queued/running`` rows and cannot see the first process' handles.
The name guard is what keeps that from happening by accident.

Usage (see docs/plan/web-business-data-env-baseline.md §4 for the registration
steps — creating the database and role is an operator action, not a test one)::

    PG_INTEGRATION=1 \
    PG_BUSINESS_TEST_DB=apodex_biz_test \
    SERVER_DATABASE_URL=postgresql+asyncpg://biz_test:<pwd>@localhost:5432/apodex_biz_test \
    uv run pytest tests/pg -q
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest

#: Opt-in switch. Without it this directory collects nothing.
OPT_IN_ENV = "PG_INTEGRATION"
#: DSN under test. Same variable a real deployment sets, so the value is what
#: ``server.config`` and the spawned worker both read.
DSN_ENV = "SERVER_DATABASE_URL"
#: Database the operator registered for this batch (§4 of the env baseline).
REGISTERED_DB_ENV = "PG_BUSINESS_TEST_DB"

#: Never allowed as an integration target, whatever the flags say.
PROTECTED_DBS = frozenset({"apodex", "postgres", "template0", "template1"})

REPO_ROOT = Path(__file__).resolve().parents[2]


def _dsn_database(dsn: str) -> str:
    return urlparse(dsn).path.lstrip("/")


def _entry_dsn() -> str:
    """Return the DSN, skipping (not opted in) or failing (misconfigured)."""
    if os.environ.get(OPT_IN_ENV) != "1":
        pytest.skip(
            f"PG 集成入口未启用：设置 {OPT_IN_ENV}=1、{REGISTERED_DB_ENV}=<登记库名> 与 "
            f"{DSN_ENV}=<该库的 DSN> 后运行 tests/pg"
        )

    dsn = os.environ.get(DSN_ENV, "").strip()
    if not dsn:
        # The variable is the deployment-facing one; ``server.config`` reads the
        # same value from .env. Tests that spawn a worker must still export it,
        # because the child process re-derives its own paths from the environment.
        from server.config import get_config

        dsn = get_config().database_url
    if not dsn.startswith("postgresql"):
        pytest.fail(
            f"PG 集成入口拒绝非 PostgreSQL 连接（{DSN_ENV} 当前 dialect 不是 postgresql）。"
            " 不接受回退 SQLite。"
        )

    registered = os.environ.get(REGISTERED_DB_ENV, "").strip()
    if not registered:
        pytest.fail(f"未登记测试库：请设置 {REGISTERED_DB_ENV}=<本批测试库名>")

    database = _dsn_database(dsn)
    if database != registered:
        pytest.fail(
            f"{DSN_ENV} 的库名 {database!r} 与 {REGISTERED_DB_ENV}={registered!r} 不一致；"
            "父子进程配置必须指向同一登记库"
        )
    if database in PROTECTED_DBS:
        pytest.fail(f"拒绝在受保护库 {database!r} 上运行 PG 集成入口（业务库/系统库）")
    if not (database.endswith("_test") or database.startswith("test_")):
        pytest.fail(f"测试库名 {database!r} 必须以 _test 结尾或 test_ 开头，避免误连业务库")
    return dsn


@pytest.fixture(autouse=True)
def _pg_entry_gate() -> str:
    """Every test in this directory runs through the entry guard."""
    return _entry_dsn()


@pytest.fixture(autouse=True)
async def _isolated_database():
    """Override ``tests/conftest.py``'s SQLite redirect with a dialect assertion.

    Same name as the parent fixture, so pytest uses this one for tests under
    ``tests/pg``. It does not redirect anywhere: it only resets the engine and
    refuses to proceed if the configured URL is not PostgreSQL — the closest
    thing to "the SQLite fixture cannot silently win".
    """
    from server.config import get_config
    from server.store import reset_engine

    cfg = get_config()
    if not cfg.database_url.startswith("postgresql"):
        pytest.fail(
            f"PG 集成入口检测到配置已回落为 {cfg.database_url!r}；拒绝以非 PostgreSQL 执行业务验收"
        )
    await reset_engine()
    try:
        yield
    finally:
        await reset_engine()


class StubOrchestrator:
    """A recorder that never spawns a worker subprocess.

    Run submission (DATA-05) is verified here for its *persistence* — snapshot,
    run row, idempotency — not for execution. A real ``Orchestrator.submit``
    forks a worker that needs an LLM config and a writable run root, which would
    make these tests slow, flaky and dependent on credentials. The stub keeps the
    submission path honest: the route still has to build the run and freeze the
    snapshot before it can "submit" anything.
    """

    def __init__(self) -> None:
        self.submitted: list[dict[str, Any]] = []
        self.stopped: list[str] = []

    async def submit(self, **kwargs: Any) -> None:
        self.submitted.append(kwargs)

    def stop(self, run_id: str) -> bool:
        self.stopped.append(run_id)
        return False

    def has_worker(self, run_id: str) -> bool:
        return False

    def subscribe(self, run_id: str) -> None:
        return None


@pytest.fixture(autouse=True)
def stub_orchestrator(monkeypatch):
    """Replace the orchestrator for every PG test (no worker subprocess)."""
    stub = StubOrchestrator()
    monkeypatch.setattr("server.orchestrator.get_orchestrator", lambda: stub)
    monkeypatch.setattr("server.routes.runs.get_orchestrator", lambda: stub)
    return stub


@pytest.fixture(scope="session")
def pg_dsn() -> str:
    return _entry_dsn()


@pytest.fixture(scope="session")
def pg_migrated(pg_dsn: str) -> str:
    """Bring the registered test database to Alembic head.

    Migrations read ``SERVER_DATABASE_URL`` through ``server.config`` (see
    ``server/alembic/env.py``), so the URL travels through the environment —
    the same path a deployment uses, and the only one a subprocess inherits.
    A non-zero exit fails the session instead of letting tests run on a schema
    from an older revision.
    """
    env = dict(os.environ, SERVER_DATABASE_URL=pg_dsn)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(REPO_ROOT / "server" / "alembic.ini"),
            "upgrade",
            "head",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.fail(
            "alembic upgrade head 失败（测试库未达 head，不能继续）："
            f"\n{proc.stdout}\n{proc.stderr}"
        )
    return pg_dsn


@pytest.fixture
async def pg_clean(pg_migrated: str):
    """Empty every application table between tests, keeping ``alembic_version``."""
    from server import store

    engine = store.get_engine()
    async with engine.begin() as conn:
        rows = await conn.exec_driver_sql(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' "
            "AND tablename <> 'alembic_version'"
        )
        names = [row[0] for row in rows]
        if names:
            quoted = ", ".join(f'public."{name}"' for name in names)
            await conn.exec_driver_sql(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE")
    yield


@pytest.fixture
async def pg_session(pg_clean: None):
    from server import store

    # ``session_scope`` is an async factory (it returns a session, it is not one),
    # so it has to be awaited before it can be used as a context manager.
    session = await store.session_scope()
    async with session:
        yield session
