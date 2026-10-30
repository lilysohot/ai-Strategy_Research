"""The same behavior contracts plus concurrent writers on migrated PostgreSQL."""

# Imported test functions are collected here with the PostgreSQL fixtures.
# ruff: noqa: F401

import asyncio

import pytest
from sqlalchemy import select

from server import business_service as biz
from server import monitor_longterm as monitor
from server import store
from tests.test_monitor_longterm import (
    Source,
    create,
    events,
    test_agent_authorization_atomic_capacity_and_idempotence,
    test_agent_cancel_replace_and_human_takeover,
    test_agent_cannot_write_another_session,
    test_batch_invalid_rolls_back_and_paused_intent_cannot_reappear,
    test_bridge_capability_and_live_pause_guard,
    test_cancel_all_targets_releases_already_queued_run,
    test_expired_quote_and_source_errors_do_not_trigger,
    test_launch_offline_is_deferred_not_failed,
    test_monitor_settings_scope_and_queued_status,
    test_offline_preserves_queue_and_resumes,
    test_pause_during_acquisition_excludes_target,
    test_repeats_fifo_and_price_return_does_not_cancel,
    test_three_targets_one_signal_and_no_same_round_replay,
)
from tests.test_monitor_longterm import (
    case as sqlite_case,
)

pytestmark = pytest.mark.pg


@pytest.fixture
async def case(pg_clean, monkeypatch):
    return await sqlite_case.__wrapped__(monkeypatch)


async def test_concurrent_last_slot_has_one_winner(case):
    await create(case, "20")
    await create(case, "21")
    results = await asyncio.gather(create(case, "22"), create(case, "23"), return_exceptions=True)
    assert sum(isinstance(r, biz.ValidationError) for r in results) == 1
    async with biz.business_transaction() as session:
        assert len(await monitor.targets(session, case.rid)) == 3


async def test_concurrent_collectors_emit_one_signal(case):
    await create(case)
    await create(case, "22")
    await asyncio.gather(*(monitor.collect_once(Source(case), now=case.clock[0]) for _ in range(2)))
    assert len(await events()) == 1
    async with biz.business_transaction() as session:
        assert len(list((await session.scalars(select(store.MonitorRound))).all())) == 1
