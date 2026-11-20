"""PostgreSQL commit-boundary checks for the SSE-T03 snapshot (T3.6).

SQLite runs every read inside one implicit transaction, so it cannot show that
``REPEATABLE READ`` pins the event head and the space view to the same commit
boundary. These tests therefore live behind the opt-in ``tests/pg`` entry.
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from server import store
from server.config import get_config
from server.super_link import events, stream
from server.super_link import models as sl
from server.super_link.contracts import CollaborationError
from tests.test_super_link import seed_pair

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[2]


def migrate_optional(*args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "server/super_link/alembic.ini", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(scope="session")
def sl_migrated(pg_migrated):
    migrate_optional("upgrade", "head")


@pytest.fixture
async def case(sl_migrated, pg_clean):
    sessions = store.get_sessionmaker()
    uid, pair = await seed_pair(sessions)
    return sessions, uid, pair


async def _snapshot(session, uid, space_id, *, min_cursor=None):
    return await stream.snapshot_payload(
        session,
        user_id=uid,
        space_id=space_id,
        min_cursor=min_cursor,
        limit=50,
    )


async def test_snapshot_pins_head_and_view_to_one_commit_boundary(
    case, monkeypatch
):
    monkeypatch.setattr(get_config(), "super_link_enabled", True)
    sessions, uid, pair = case

    async with stream.snapshot_session() as session:
        before = await _snapshot(session, uid, pair.space_id)
        assert before["space"]["control_state"] == "active"

        # A different connection commits a control change and its fact after the
        # snapshot transaction has already read the head and the space view.
        async with sessions.begin() as other:
            space = await other.get(sl.SuperLinkSpace, pair.space_id)
            space.control_state = "stopped"
            space.control_version += 1
            await events.stage_for_space(
                other,
                pair.space_id,
                type="sl.space.control_changed",
                change_key="pg-snapshot-boundary",
                data={
                    "control_state": space.control_state,
                    "control_version": space.control_version,
                },
                invalidate=("space",),
                source_kind="space",
                source_id=str(pair.space_id),
            )
            await events.seal_changes(other)

        # The same transaction must keep the original commit boundary: old space
        # state and the old cursor, even though the row is committed elsewhere.
        after = await _snapshot(session, uid, pair.space_id)
        assert after["space"]["control_state"] == "active"
        assert after["space"]["control_version"] == before["space"]["control_version"]
        assert after["cursor"] == before["cursor"]

    # A new snapshot sees both the state change and the advanced cursor.
    fresh = await stream.read_snapshot(user_id=uid, space_id=pair.space_id)
    assert fresh["space"]["control_state"] == "stopped"
    assert fresh["cursor"] != before["cursor"]

    page = await events.read_events(
        user_id=uid, space_id=pair.space_id, after=before["cursor"], limit=10
    )
    assert [item["type"] for item in page.events] == ["sl.space.control_changed"]
    assert page.events[0]["data"]["control_state"] == "stopped"


async def test_min_cursor_accepts_the_snapshot_it_already_covers(case, monkeypatch):
    monkeypatch.setattr(get_config(), "super_link_enabled", True)
    _sessions, uid, pair = case

    first = await stream.read_snapshot(user_id=uid, space_id=pair.space_id)
    second = await stream.read_snapshot(
        user_id=uid, space_id=pair.space_id, min_cursor=first["cursor"]
    )
    assert second["cursor"] == first["cursor"]

    head = first["cursor"].split(":")
    ahead = f"sl1:{pair.space_id}:{head[2]}:{int(head[3]) + 1}"
    with pytest.raises(CollaborationError, match="invalid_cursor"):
        await stream.read_snapshot(
            user_id=uid, space_id=pair.space_id, min_cursor=ahead
        )

    stale_epoch = f"sl1:{pair.space_id}:{uuid.uuid4()}:{head[3]}"
    with pytest.raises(CollaborationError, match="resync_required"):
        await stream.read_snapshot(
            user_id=uid, space_id=pair.space_id, min_cursor=stale_epoch
        )
