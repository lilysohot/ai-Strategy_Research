"""F07 operational backup script — pure-helper regression tests.

The script's real evidence is the live backup + isolated restore drill
(audit/f07-backup-script.json). These tests pin the deterministic parts that
do not need a live PostgreSQL: URL parsing/normalisation, retention selection
and the fail-closed target probe.
"""

from __future__ import annotations

import datetime as dt

import pytest

from scripts.web_backup import parse_url, probe_dir, prune


def test_parse_url_normalises_asyncpg_scheme_and_split():
    info = parse_url("postgresql+asyncpg://postgres:pw@db.example:5432/apodex")
    assert info == {
        "scheme": "postgresql",
        "user": "postgres",
        "password": "pw",
        "host": "db.example",
        "port": "5432",
        "db": "apodex",
    }


def test_parse_url_defaults_port_when_absent():
    info = parse_url("postgres://u:p@localhost/apodex")
    assert info["port"] == "5432"
    assert info["host"] == "localhost"


def test_parse_url_rejects_malformed():
    with pytest.raises(SystemExit):
        parse_url("not-a-url")


def test_probe_dir_fails_closed_on_file_target(tmp_path):
    target = tmp_path / "not-a-dir"
    target.write_text("x")
    with pytest.raises(SystemExit):
        probe_dir(target)


def test_prune_selects_only_old_matching_prefix(tmp_path):
    import os

    now = dt.datetime.now(dt.UTC)
    old = tmp_path / "apodex-OLD.dump"
    fresh = tmp_path / "apodex-NEW.dump"
    other = tmp_path / "unrelated.bin"
    old.touch()
    fresh.touch()
    other.touch()
    # Age the two files deterministically via mtime (utime wants (atime, mtime)).
    old_mtime = (now - dt.timedelta(days=40)).timestamp()
    fresh_mtime = (now - dt.timedelta(days=2)).timestamp()
    os.utime(old, (old_mtime, old_mtime))
    os.utime(fresh, (fresh_mtime, fresh_mtime))

    stale = prune(tmp_path, "apodex", keep_days=30, dry_run=True)
    assert stale == [old]
    # Dry-run must not delete.
    assert old.exists() and fresh.exists()

    pruned = prune(tmp_path, "apodex", keep_days=30, dry_run=False)
    assert pruned == [old]
    assert not old.exists()
    assert fresh.exists()
    assert other.exists(), "prune must never touch non-matching files"
