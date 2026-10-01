"""F19 (second half): the storage readiness gate.

The first half of F19 made ``/healthz`` report an unreachable database. This file
covers what was still missing: a *reachable* database whose schema is not the one
this build expects, a run-data root that cannot be written to, and the startup
rule that refuses to serve in either case.

Every case runs against a throwaway SQLite file and a temp data root — no real
database, no network, no subprocess.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from server import readiness, store
from server.config import get_config

#: The migration this checkout expects a deployed database to be at.
HEAD = "0004_control_records"
BEHIND = "0003_turn_seq_unique"


@pytest.fixture
async def env(tmp_path, monkeypatch):
    """A reachable-but-unprepared database plus a writable data root."""
    cfg = get_config()
    monkeypatch.setattr(cfg, "database_url", f"sqlite+aiosqlite:///{tmp_path}/gate.db")
    monkeypatch.setattr(cfg, "runs_root", tmp_path / "runs")
    await store.reset_engine()
    yield cfg
    await store.reset_engine()


@contextmanager
def _logging_intact() -> Iterator[None]:
    """Keep Alembic's ``fileConfig`` from leaking into the rest of the session.

    ``server/alembic/env.py`` calls ``logging.config.fileConfig`` against the real
    ini, which replaces the root handlers and disables every existing logger —
    including pytest's capture handler, after which ``caplog`` silently sees
    nothing in all later tests (reproduced: the secret-validation suite passed
    alone and failed when this file ran first). Snapshot and restore around the
    migration so running it in-process stays safe.
    """
    root = logging.getLogger()
    saved_level = root.level
    saved_handlers = list(root.handlers)
    saved_loggers = {
        name: (logger.level, logger.disabled, logger.propagate)
        for name, logger in logging.Logger.manager.loggerDict.items()
        if isinstance(logger, logging.Logger)
    }
    try:
        yield
    finally:
        root.setLevel(saved_level)
        root.handlers[:] = saved_handlers
        for name, (level, disabled, propagate) in saved_loggers.items():
            logger = logging.getLogger(name)
            logger.setLevel(level)
            logger.disabled = disabled
            logger.propagate = propagate


async def _migrate(cfg, target: str = "head") -> None:
    """Run Alembic against the fixture's database (in a worker thread).

    Alembic's ``env.py`` drives its own event loop via ``asyncio.run``, so it
    cannot be called from inside this test's running loop; off-thread is also how
    a deploy step actually runs it. ``env.py`` derives the URL from the live
    config, so the fixture's monkeypatched ``database_url`` is what gets migrated
    — never the database in ``.env``.
    """
    config = Config("server/alembic.ini")
    config.set_main_option("sqlalchemy.url", cfg.database_url)
    with _logging_intact():
        await asyncio.to_thread(command.upgrade, config, target)


async def test_migration_graph_has_a_single_head():
    graph = readiness.migration_graph()
    assert set(graph) == {"0001_initial", "0002_run_usage", BEHIND, HEAD}
    assert readiness.expected_heads() == (HEAD,)
    assert readiness._is_ancestor("0001_initial", HEAD)
    assert readiness._is_ancestor(BEHIND, HEAD)
    assert not readiness._is_ancestor(HEAD, BEHIND)


async def test_empty_database_is_not_ready_and_says_so(env):
    # Reachable (the file exists) but with no tables at all: an empty database,
    # which is a different problem from an unreachable one and gets its own code.
    assert await store.check_db() is True
    verdict = await readiness.storage_readiness()
    assert not verdict.ok
    assert verdict.reasons == (readiness.SCHEMA_MISSING,)
    assert "users" in verdict.detail["missing_tables"]


async def test_database_behind_this_build_is_not_ready(env):
    await _migrate(env, BEHIND)  # an installation that was migrated, but not to head
    verdict = await readiness.storage_readiness()
    assert not verdict.ok
    assert verdict.reasons == (readiness.SCHEMA_BEHIND,)
    assert verdict.detail["current_revision"] == BEHIND
    assert verdict.detail["expected_head"] == HEAD


async def test_database_at_head_is_ready(env):
    await _migrate(env, "head")
    verdict = await readiness.storage_readiness()
    assert verdict.ok, (verdict.reasons, verdict.detail)
    assert verdict.reasons == ()
    assert verdict.as_body() == {"status": "ok"}


async def test_unstamped_database_with_all_tables_is_accepted(env):
    # The create_all dev path: no alembic_version, but the schema is complete.
    await store.init_db()
    verdict = await readiness.storage_readiness()
    assert verdict.ok, (verdict.reasons, verdict.detail)


async def test_unknown_revision_is_reported_as_ahead_not_behind(env):
    await _migrate(env, "head")
    async with store.get_engine().begin() as conn:
        await conn.execute(text("UPDATE alembic_version SET version_num='zz_future'"))
    verdict = await readiness.storage_readiness()
    assert not verdict.ok
    assert verdict.reasons == (readiness.SCHEMA_AHEAD,)
    assert verdict.detail["current_revision"] == "zz_future"


async def test_two_stamped_heads_are_ambiguous(env, monkeypatch):
    await _migrate(env, "head")
    monkeypatch.setattr(readiness, "expected_heads", lambda: ("a", "b"))
    verdict = await readiness.storage_readiness()
    assert not verdict.ok
    assert verdict.reasons == (readiness.SCHEMA_AMBIGUOUS,)


async def test_unwritable_data_root_is_not_ready(env, tmp_path):
    await _migrate(env, "head")
    # A path whose parent is a regular file cannot be created on any platform —
    # the cross-platform stand-in for a read-only mount.
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    verdict = await readiness.storage_readiness(data_root=blocker / "runs")
    assert not verdict.ok
    assert verdict.reasons == (readiness.DATA_ROOT_UNWRITABLE,)


async def test_data_root_probe_leaves_nothing_behind(env):
    await store.init_db()
    assert readiness.probe_data_root() is None
    leftovers = [p.name for p in Path(env.runs_root).iterdir() if p.name.startswith(".readyz")]
    assert leftovers == []


async def test_data_root_probe_writes_real_bytes(env, monkeypatch):
    """A 0-byte create still succeeds on a full tmpfs — data pages run out, not
    inodes — so an empty probe payload reported a full disk as ready (found by
    the E3 disk-full injection, 2026-10-01). The probe must write actual bytes."""
    await store.init_db()
    written: list[bytes] = []
    real_write_bytes = pathlib.Path.write_bytes

    def spy(self: pathlib.Path, data: bytes) -> int:
        if self.name.startswith(".readyz-probe-"):
            written.append(data)
        return real_write_bytes(self, data)

    monkeypatch.setattr(pathlib.Path, "write_bytes", spy)
    assert readiness.probe_data_root() is None
    assert written == [b"readyz-probe"]


def test_startup_gate_raises_in_production_and_warns_in_dev(caplog):
    verdict = readiness.Readiness(ok=False, reasons=(readiness.SCHEMA_BEHIND,))
    with pytest.raises(readiness.StorageNotReadyError) as excinfo:
        readiness.enforce_startup_readiness(verdict, debug=False)
    assert readiness.SCHEMA_BEHIND in str(excinfo.value)
    assert "alembic upgrade head" in str(excinfo.value)
    # Dev mode is the documented escape hatch (local SQLite is unstamped) and it
    # must be loud about what it is tolerating.
    with caplog.at_level("WARNING"):
        readiness.enforce_startup_readiness(verdict, debug=True)
    assert any("SERVER_DEBUG" in record.message for record in caplog.records)


def test_startup_gate_does_not_prescribe_a_migration_for_a_dead_database():
    """Migrating is the right answer to a schema mismatch and the wrong answer
    to an unreachable database."""
    verdict = readiness.Readiness(ok=False, reasons=(readiness.DB_UNAVAILABLE,))
    with pytest.raises(readiness.StorageNotReadyError) as excinfo:
        readiness.enforce_startup_readiness(verdict, debug=False)
    assert "alembic" not in str(excinfo.value)


def test_startup_gate_passes_a_ready_store():
    readiness.enforce_startup_readiness(readiness.Readiness(ok=True), debug=False)


async def test_readyz_is_stricter_than_healthz(env):
    """The two probes differ exactly where the remedies differ."""
    await _migrate(env, BEHIND)
    from server.app import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://gate") as client:
        health = await client.get("/healthz")
        ready = await client.get("/readyz")
    # The database answers, so liveness/storage connectivity is fine...
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    # ...but this build must not be handed work against the old schema.
    assert ready.status_code == 503
    assert ready.json() == {"status": "not_ready", "reasons": [readiness.SCHEMA_BEHIND]}


async def test_readyz_ok_after_migrating(env):
    await _migrate(env, "head")
    from server.app import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://gate") as client:
        response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_unreachable_database_outranks_the_schema_check(env, monkeypatch):
    """Connectivity is reported first: it is the one an operator retries."""
    monkeypatch.setattr(store, "check_db", lambda: asyncio.sleep(0, result=False))
    verdict = await readiness.storage_readiness()
    assert verdict.reasons == (readiness.DB_UNAVAILABLE,)
