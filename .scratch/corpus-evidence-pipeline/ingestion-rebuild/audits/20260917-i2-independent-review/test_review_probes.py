"""Independent review probes. Synthetic rows only; never connect to PostgreSQL.

Assertions describe required behavior, so confirmed defects remain failing.
Database context managers/cursors are substituted, not the methods under review.
"""

import json
import runpy
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plugins.corpus.preparation.contract import Build, JobStage
from plugins.corpus.preparation.repository import StoreError
from plugins.corpus.preparation.repository_pg import PgStore


ROOT = Path(__file__).resolve().parents[5]
NOW = datetime(2026, 9, 17, tzinfo=UTC)
SID = "a" * 64
BID = "b" * 64


@pytest.fixture(autouse=True)
def no_real_connections(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Review probes must never connect to a database")

    monkeypatch.setattr("psycopg.connect", forbidden)


def fake_store(rows):
    store = PgStore.__new__(PgStore)
    cur = MagicMock()
    cur.__enter__.return_value = cur
    cur.fetchone.side_effect = rows
    conn = MagicMock()
    conn.transaction.side_effect = nullcontext
    conn.cursor.return_value = cur
    store._conn = conn
    return store, cur


@pytest.mark.parametrize("scope", [None, "pages:1-2"])
def test_publish_accepts_matching_scope(monkeypatch, scope):
    # Return exactly the columns selected by the real SQL, including after a fix.
    store, cur = fake_store([])
    def fetch():
        statement = cur.execute.call_args.args[0]
        if "FROM corpus.corpus_builds" in statement:
            return (SID, "d1", scope) if "scope_ref" in statement else (SID, "d1")
        if "FROM corpus.corpus_admissions" in statement:
            return (SID, "in_scope", scope)
        if "FROM corpus.corpus_sources" in statement:
            return ("d1",)
        raise AssertionError(statement)

    cur.fetchone.side_effect = fetch
    monkeypatch.setattr(store, "_db_now", lambda cur: NOW)
    monkeypatch.setattr(store, "_current_job_row", lambda *a, **k: (
        1, "running", "w", "token", NOW + timedelta(seconds=300), NOW, None, None
    ))
    monkeypatch.setattr(store, "_set_publication", lambda *a: "published")
    assert store.publish(SID, "d1", BID, NOW, owner_id="w", fence_token="token") == "published"


def test_build_roundtrip_allows_same_object_retry():
    quality = '{"oversized_chunks":[],"gap_regions":[]}'
    original = Build(BID, SID, "d1", "p", "c", "k", "i", quality_report=quality)
    row = (SID, "d1", "p", "c", "k", "i", None, None, [], json.loads(quality))
    store, _ = fake_store([row])
    # Same original object replay after INSERT must remain idempotent.
    store.put_build(original)


def test_job_checkpoint_roundtrip_preserves_interface_type():
    row = (1, "failed", "w", "token", None, NOW, "failure", {"version": 1})
    job = PgStore._job_from_row(BID, JobStage.PARSED, row)
    assert isinstance(job.checkpoint, str)
    assert json.loads(job.checkpoint) == {"version": 1}


def test_ownership_uses_time_after_waiting_for_lock(monkeypatch):
    store, _ = fake_store([])
    locked = False

    def current_job(*args, **kwargs):
        nonlocal locked
        # Simulate the row lock returning after a two-second wait, with no takeover.
        locked = True
        return (1, "running", "w", "token", NOW + timedelta(seconds=1), NOW, None, None)

    monkeypatch.setattr(store, "_db_now", lambda cur: NOW + timedelta(seconds=2 if locked else 0))
    monkeypatch.setattr(store, "_current_job_row", current_job)
    with pytest.raises(StoreError, match="过期"):
        store.put_units(BID, [], owner_id="w", fence_token="token")


def test_cleanup_rejects_wrong_database_before_truncate(monkeypatch):
    monkeypatch.setenv("CORPUS_I2_DSN", "postgresql://invalid:invalid@127.0.0.1:543/i0b2_verify_postgres")
    cur = MagicMock()
    cur.__enter__.return_value = cur
    cur.fetchone.return_value = ("i0b2_verify_postgres",)
    cur.fetchall.return_value = [("postgres",), ("i0b2_verify_postgres",)]
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value = cur
    monkeypatch.setattr("psycopg.connect", lambda *a, **k: conn)
    module = runpy.run_path(str(ROOT / "tests/test_corpus_preparation_repository_pg.py"))
    cleanup = module["_clean_tables"].__wrapped__()
    try:
        next(cleanup)
    except (Exception, SystemExit):
        pass
    finally:
        cleanup.close()
    statements = [call.args[0] for call in cur.execute.call_args_list]
    assert not any(s.startswith("TRUNCATE") for s in statements), statements


def test_current_freeze_validator_detects_inherited_implementation_drift(monkeypatch):
    original = Path.read_bytes
    engine = ROOT / "plugins/corpus/preparation/engine.py"
    def drift(path):
        data = original(path)
        return data + b"\n# simulated drift: no file is changed\n" if path == engine else data

    monkeypatch.setattr(Path, "read_bytes", drift)
    validator = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"
    with pytest.raises(SystemExit) as caught:
        runpy.run_path(str(validator), run_name="__main__")
    assert caught.value.code != 0
