"""Startup reconciliation of runs orphaned by a restart.

A ``runs`` row outlives the server process, but the worker handle that would
have finished it does not. After a crash, deploy or container reschedule every
row still marked queued/running is one nobody will complete — its SSE stream
will never produce a terminal frame, so the UI would spin on it forever.

Run with::
    uv run pytest tests/test_orphan_run_reconcile.py -q
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from server.config import get_config
from server.orchestrator import Orchestrator
from server.store import (
    create_run,
    create_session,
    create_user,
    get_run,
    init_db,
    reset_engine,
)


@pytest.fixture
async def db(tmp_path):
    """Point the store at a throwaway SQLite database for the test."""
    cfg = get_config()
    original_url = cfg.database_url
    cfg.database_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    await reset_engine()
    await init_db()
    yield cfg
    cfg.database_url = original_url
    await reset_engine()


async def _make_running_run(tmp_path, *, with_summary: bool = False):
    """Create a user + session + a run stuck in ``running``."""
    user = await create_user(
        username=f"u-{uuid.uuid4().hex[:8]}", password_hash="not-a-real-hash"
    )
    session = await create_session(user_id=user.id, title=None)
    run_dir = tmp_path / f"run-{uuid.uuid4().hex}"
    run_dir.mkdir(parents=True, exist_ok=True)
    if with_summary:
        (run_dir / "summary.json").write_text(
            json.dumps({"final_answer": "部分回答", "error": ""}), encoding="utf-8"
        )
    run = await create_run(
        run_id=uuid.uuid4(),
        session_id=session.id,
        user_id=user.id,
        prompt="hi",
        pipeline_id="stateful-react-agent",
        run_dir=str(run_dir),
        status="running",
    )
    return run


async def test_orphan_without_summary_becomes_failed(db, tmp_path):
    run = await _make_running_run(tmp_path)

    assert await Orchestrator().reconcile_orphan_runs() == 1

    row = await get_run(run_id=run.id, user_id=run.user_id)
    assert row is not None
    assert row.status == "failed"
    assert row.stopped_by == "server_restart"
    assert row.finished_at is not None
    assert "重启" in (row.error or "")


async def test_orphan_with_partial_answer_becomes_stopped(db, tmp_path):
    run = await _make_running_run(tmp_path, with_summary=True)

    assert await Orchestrator().reconcile_orphan_runs() == 1

    row = await get_run(run_id=run.id, user_id=run.user_id)
    assert row is not None
    # Stopped, never completed: the run was cut short even though it produced
    # something worth showing.
    assert row.status == "stopped"
    assert row.final_answer == "部分回答"
    assert row.stopped_by == "server_restart"


async def test_live_handle_is_skipped(db, tmp_path):
    """A run owned by *this* process must be left alone."""
    run = await _make_running_run(tmp_path)
    orch = Orchestrator()

    @dataclass
    class _LiveHandle:
        run_id: str = run.id.hex
        session_id: str = ""
        proc: Any = None
        frames: list = field(default_factory=list)

    orch._handles[run.id.hex] = _LiveHandle()

    assert await orch.reconcile_orphan_runs() == 0

    row = await get_run(run_id=run.id, user_id=run.user_id)
    assert row is not None
    assert row.status == "running"


async def test_finished_runs_are_untouched(db, tmp_path):
    """Reconciliation must not rewrite runs that already reached a terminal state."""
    run = await _make_running_run(tmp_path)
    from server.store import update_run_result

    await update_run_result(run_id=run.id, status="completed", final_answer="done")

    assert await Orchestrator().reconcile_orphan_runs() == 0

    row = await get_run(run_id=run.id, user_id=run.user_id)
    assert row is not None
    assert row.status == "completed"
    assert row.stopped_by is None
