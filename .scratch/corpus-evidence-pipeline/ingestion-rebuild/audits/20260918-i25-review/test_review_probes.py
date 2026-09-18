"""I2-5 independent diagnostic probes: no database/network/model calls.

The PG terminal replay branch is exercised with a synthetic cursor row; engine
recovery uses the actual MemoryStore + synthetic parse/build/publish chain.
These probes are not a replacement for the required real-PG gate.
"""

import runpy
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plugins.corpus.preparation.contract import (
    Admission, AdmissionDecision, JobStage, JobState, LeaseConfig, MaterialType,
)
from plugins.corpus.preparation.engine import publish_build
from plugins.corpus.preparation.repository import StoreError
from plugins.corpus.preparation.repository_pg import PgStore

ROOT = Path(__file__).resolve().parents[5]
NOW = datetime(2026, 9, 17, 12, tzinfo=UTC)
LEASE = LeaseConfig(300, 60, 600, 3)


def prepared(tmp_path):
    module = runpy.run_path(str(ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260917-i0c-protocol/test_i0c_protocol_probes.py"))
    return module["_prepare_md"](tmp_path)


def test_pg_stale_finish_after_takeover_terminal_is_rejected(monkeypatch):
    store = PgStore.__new__(PgStore)
    conn, cur = MagicMock(), MagicMock()
    cur.__enter__.return_value = cur
    conn.transaction.side_effect = nullcontext
    conn.cursor.return_value = cur
    store._conn = conn
    # w2 has taken over attempt 2 and completed it. w1 retries attempt 1.
    row = (2, "succeeded", "w2", "new-token", None, NOW, None, {"owner": "w2"})
    monkeypatch.setattr(store, "_current_job_row", lambda *a, **k: row)
    with pytest.raises(StoreError, match="lease_lost|token|所有权"):
        store.finish_job("b" * 64, JobStage.PARSED, "w1", "old-token", NOW,
                         JobState.SUCCEEDED, checkpoint='{"owner":"w1"}')


def test_memory_stale_finish_after_takeover_terminal_is_rejected(tmp_path):
    store, bid = prepared(tmp_path)
    store.register_job(bid, JobStage.PUBLISHED)
    old = store.acquire_job(bid, JobStage.PUBLISHED, "w1", NOW, LEASE)
    later = NOW + timedelta(seconds=301)
    new = store.acquire_job(bid, JobStage.PUBLISHED, "w2", later, LEASE)
    store.finish_job(bid, JobStage.PUBLISHED, "w2", new.fence_token, later, JobState.SUCCEEDED)
    with pytest.raises(StoreError, match="lease_lost|token|所有权"):
        store.finish_job(bid, JobStage.PUBLISHED, "w1", old.fence_token, later, JobState.SUCCEEDED)


def test_publish_retry_reconciles_unfinished_publication_job(tmp_path, monkeypatch):
    store, bid = prepared(tmp_path)
    finish = store.finish_job
    raised = False

    def lost_finish(*args, **kwargs):
        nonlocal raised
        if args[1] is JobStage.PUBLISHED and not raised:
            raised = True
            raise ConnectionError("simulated disconnect after publication, before job completion")
        return finish(*args, **kwargs)

    monkeypatch.setattr(store, "finish_job", lost_finish)
    with pytest.raises(ConnectionError):
        publish_build(store, bid, activated_at=NOW)
    assert store.get_job(bid, JobStage.PUBLISHED).state is JobState.RUNNING
    result = publish_build(store, bid, activated_at=NOW)
    assert result.generation == 1
    assert store.get_job(bid, JobStage.PUBLISHED).state is JobState.SUCCEEDED


def test_engine_retry_must_not_accept_superseded_admission(tmp_path):
    store, bid = prepared(tmp_path)
    first = publish_build(store, bid, activated_at=NOW)
    store.put_admission(Admission(
        decision_id="new-exclusion", source_id=first.source_id,
        material_type=MaterialType.PIPELINE_ARTIFACT, research_domain=None,
        decision=AdmissionDecision.EXCLUDED_BY_POLICY,
    ))
    with pytest.raises((StoreError, RuntimeError)):
        publish_build(store, bid, activated_at=NOW)


def test_control_normal_publish_and_same_attempt_replay(tmp_path):
    store, bid = prepared(tmp_path)
    first = publish_build(store, bid, activated_at=NOW)
    assert publish_build(store, bid, activated_at=NOW) == first
    job = store.get_job(bid, JobStage.PUBLISHED)
    assert job.state is JobState.SUCCEEDED
    assert store.finish_job(bid, JobStage.PUBLISHED, job.owner_id, job.fence_token,
                            NOW, JobState.SUCCEEDED) == job
