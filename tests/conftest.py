"""Shared test fixtures.

One rule is enforced here, globally: **no test may touch the database the
server is configured to use.**

``SERVER_DATABASE_URL`` points at PostgreSQL, and several server tests build
their client without switching it — before this fixture existed they created
tables and registered users in the real business database, and failed once
``create_all`` hit a schema that was already in use. Forcing an isolated SQLite
file per test makes that impossible no matter what an individual test forgets
to do; a test that wants a different database can still set
``cfg.database_url`` itself (the value is restored afterwards either way).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
async def _isolated_database(tmp_path):
    """Point the server store at a throwaway SQLite file for every test."""
    try:
        from server.config import get_config
        from server.store import reset_engine
    except ImportError:
        # The web dependency group is not installed: nothing server-side can
        # run, so there is no database to isolate.
        yield
        return

    cfg = get_config()
    saved = cfg.database_url
    cfg.database_url = f"sqlite+aiosqlite:///{tmp_path / 'isolated.db'}"
    await reset_engine()
    try:
        yield
    finally:
        cfg.database_url = saved
        await reset_engine()
