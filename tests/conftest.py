"""Shared test fixtures.

One rule is enforced here, globally: **no test may touch the storage the server
is configured to use** — neither its database nor its run-data root.

``SERVER_DATABASE_URL`` points at PostgreSQL, and several server tests build
their client without switching it — before this fixture existed they created
tables and registered users in the real business database, and failed once
``create_all`` hit a schema that was already in use. Forcing an isolated SQLite
file per test makes that impossible no matter what an individual test forgets
to do; a test that wants a different database can still set
``cfg.database_url`` itself (the value is restored afterwards either way).

``runs_root`` needed the same treatment (2026-10-01): the worker-spawning e2e
files (``test_web_m1``, ``test_upload_t210``, ``test_stop_t28``, …) submit runs
whose directories land under the *configured* root while their database rows go
to the throwaway SQLite — twenty-six orphan directories accumulated in the real
data root in one day, the same residue class F01 had already pruned once. Tests
that redirect ``runs_root`` themselves keep working; their monkeypatch simply
re-points the value this fixture set.
"""

from __future__ import annotations

import os

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
    saved_db = cfg.database_url
    saved_runs_root = cfg.runs_root
    saved_env = os.environ.get("SERVER_RUNS_ROOT")
    cfg.database_url = f"sqlite+aiosqlite:///{tmp_path / 'isolated.db'}"
    cfg.runs_root = tmp_path / "runs"
    # The worker is a SEPARATE process and re-derives its run directory from its
    # own environment (server/worker.py calls run_dir_for itself), so mutating
    # this process's config object cannot reach it — the redirect has to travel
    # through SERVER_RUNS_ROOT, the same variable a real deployment sets, which
    # the spawned worker inherits. This is the config-across-processes rule from
    # web-storage-validation-environment.md §4.
    os.environ["SERVER_RUNS_ROOT"] = str(cfg.runs_root)
    await reset_engine()
    try:
        yield
    finally:
        cfg.database_url = saved_db
        cfg.runs_root = saved_runs_root
        if saved_env is None:
            os.environ.pop("SERVER_RUNS_ROOT", None)
        else:
            os.environ["SERVER_RUNS_ROOT"] = saved_env
        await reset_engine()
