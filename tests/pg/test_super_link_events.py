"""PostgreSQL concurrency for the SSE-T02 event ledger (T2.5).

SQLite cannot exercise row locks or savepoints under contention, so these
tests only run through the opt-in ``tests/pg`` entry (``PG_INTEGRATION=1``).
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from server import store
from server.config import get_config
from server.super_link import events
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
    # Round-trip sl_0006 so a database migrated by an earlier build cannot keep
    # the old events -> spaces foreign key and silently invalidate these tests.
    migrate_optional("upgrade", "head")
    migrate_optional("downgrade", "sl_0005_controls")
    migrate_optional("upgrade", "head")


@pytest.fixture
async def case(sl_migrated, pg_clean):
    sessions = store.get_sessionmaker()
    uid, pair = await seed_pair(sessions)
    return sessions, uid, pair


async def test_a01_late_rollback_frees_the_head_for_the_next_sealer(case, monkeypatch):
    monkeypatch.setattr(get_config(), "super_link_enabled", True)
    sessions, _uid, pair = case

    first = sessions()
    await first.begin()
    await events.stage_for_space(
        first,
        pair.space_id,
        type="sl.action.recorded",
        change_key="late-source",
        data={"phase": "late"},
    )
    assert len(await events.seal_changes(first)) == 1

    staging = asyncio.Event()

    async def contender() -> None:
        async with sessions() as session, session.begin():
            await events.stage_for_space(
                session,
                pair.space_id,
                type="sl.action.recorded",
                change_key="next-source",
                data={"phase": "next"},
            )
            staging.set()
            await events.seal_changes(session)

    task = asyncio.create_task(contender())
    await asyncio.wait_for(staging.wait(), timeout=5)
    await asyncio.sleep(0.3)
    assert not task.done(), "second sealer must wait for the uncommitted head lock"

    await first.rollback()
    await first.close()
    await asyncio.wait_for(task, timeout=10)

    async with sessions() as session:
        head = await session.get(sl.SuperLinkEventHead, pair.space_id)
        assert head.last_seq == 1
        keys = (await session.scalars(select(sl.SuperLinkEvent.change_key))).all()
        assert list(keys) == ["next-source"]


async def test_a01_early_commit_allocates_before_the_next_sealer(case, monkeypatch):
    monkeypatch.setattr(get_config(), "super_link_enabled", True)
    sessions, _uid, pair = case

    first = sessions()
    await first.begin()
    await events.stage_for_space(
        first,
        pair.space_id,
        type="sl.action.recorded",
        change_key="early-source",
        data={"phase": "early"},
    )
    assert len(await events.seal_changes(first)) == 1

    staging = asyncio.Event()

    async def contender() -> None:
        async with sessions() as session, session.begin():
            await events.stage_for_space(
                session,
                pair.space_id,
                type="sl.action.recorded",
                change_key="next-source",
                data={"phase": "next"},
            )
            staging.set()
            await events.seal_changes(session)

    task = asyncio.create_task(contender())
    await asyncio.wait_for(staging.wait(), timeout=5)
    await asyncio.sleep(0.3)
    assert not task.done(), "second sealer must wait for the uncommitted head lock"

    await first.commit()
    await first.close()
    await asyncio.wait_for(task, timeout=10)

    async with sessions() as session:
        head = await session.get(sl.SuperLinkEventHead, pair.space_id)
        assert head.last_seq == 2
        keys = (
            await session.scalars(
                select(sl.SuperLinkEvent.change_key).order_by(sl.SuperLinkEvent.seq)
            )
        ).all()
        assert list(keys) == ["early-source", "next-source"]


async def test_event_insert_does_not_wait_for_the_space_row(case, monkeypatch):
    """Events reference the head, so a holder of the space row cannot join the lock cycle."""
    monkeypatch.setattr(get_config(), "super_link_enabled", True)
    sessions, _uid, pair = case
    inserting = sessions()
    await inserting.begin()
    holder = sessions()
    await holder.begin()
    try:
        head = await inserting.get(sl.SuperLinkEventHead, pair.space_id, with_for_update=True)
        assert head is not None
        await holder.get(sl.SuperLinkSpace, pair.space_id, with_for_update=True)
        await inserting.execute(text("SET LOCAL lock_timeout = '3s'"))
        inserting.add(
            sl.SuperLinkEvent(
                space_id=pair.space_id,
                stream_epoch=head.stream_epoch,
                seq=1,
                event_id=uuid.uuid4(),
                transaction_id=uuid.uuid4(),
                change_key="fk-probe",
                type="sl.action.recorded",
                schema_version=1,
                source_kind="space",
                source_id=str(pair.space_id),
                data_json={"probe": "fk"},
                invalidate_json=[],
            )
        )
        await asyncio.wait_for(inserting.flush(), timeout=5)
        await inserting.commit()
        locked = await asyncio.wait_for(
            holder.get(sl.SuperLinkEventHead, pair.space_id, with_for_update=True),
            timeout=5,
        )
        assert locked is not None
    finally:
        await holder.rollback()
        await holder.close()
        await inserting.close()


async def test_dual_space_lock_order_does_not_deadlock(case, monkeypatch):
    sessions, _uid, pair = case
    _other_uid, other = await seed_pair(sessions)
    monkeypatch.setattr(get_config(), "super_link_enabled", True)

    async def cycle(spaces: tuple[uuid.UUID, uuid.UUID]) -> None:
        async with sessions() as session, session.begin():
            for space_id in spaces:
                await events.stage_for_space(
                    session,
                    space_id,
                    type="sl.action.recorded",
                    change_key=f"cycle:{space_id}",
                    data={"space": str(space_id)},
                )
            await events.seal_changes(session)

    await asyncio.wait_for(
        asyncio.gather(
            cycle((pair.space_id, other.space_id)),
            cycle((other.space_id, pair.space_id)),
        ),
        timeout=15,
    )
    async with sessions() as session:
        for space_id in (pair.space_id, other.space_id):
            head = await session.get(sl.SuperLinkEventHead, space_id)
            assert head.last_seq == 1
        assert await session.scalar(select(func.count()).select_from(sl.SuperLinkEvent)) == 2


async def test_event_failure_rolls_back_the_source_write(case, monkeypatch):
    monkeypatch.setattr(get_config(), "super_link_enabled", True)
    sessions, uid, pair = case
    async with sessions.begin() as session:
        head = await session.get(sl.SuperLinkEventHead, pair.space_id)
        await session.delete(head)

    run_id = uuid.uuid4()
    with pytest.raises(CollaborationError, match="event_head_missing"):
        async with sessions() as session, session.begin():
            await store.add_run(
                session,
                run_id=run_id,
                session_id=pair.team_session_id,
                user_id=uid,
                prompt="Must roll back with its event",
                pipeline_id="stateful-react-agent",
                run_dir=f"runs/{run_id}",
            )
            await events.seal_changes(session)

    async with sessions() as session:
        assert await session.get(store.Run, run_id) is None
        assert await session.scalar(select(func.count()).select_from(sl.SuperLinkEvent)) == 0


async def test_migration_backfills_a_head_for_existing_spaces(case):
    sessions, _uid, pair = case
    async with sessions.begin() as session:
        head = await session.get(sl.SuperLinkEventHead, pair.space_id)
        await session.delete(head)

    migrate_optional("downgrade", "sl_0005_controls")
    migrate_optional("upgrade", "head")

    async with sessions() as session:
        head = await session.get(sl.SuperLinkEventHead, pair.space_id)
        assert head is not None and head.last_seq == 0
