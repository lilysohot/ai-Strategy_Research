"""F07: retention planning, backup manifest and restore verification.

These cover the decisions that can silently destroy or misplace a study:
an active run being swept, a missing directory being reported as "cleaned",
a plan that deletes without being asked, and a path that escapes the run root.

Everything runs against temporary directories — no business DB, no real run
data, no pg_dump.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.run_retention import (
    Disposition,
    Manifest,
    RetentionPolicy,
    RunStorage,
    apply_cleanup,
    main,
    plan_cleanup,
    scan_run_dir,
    verify_against,
)

NOW = datetime(2026, 9, 30, tzinfo=UTC)
POLICY = RetentionPolicy(keep_days=30)


def _run(run_id: str, status: str = "completed", days_ago: int = 90, **extra) -> RunStorage:
    finished = (NOW - timedelta(days=days_ago)).isoformat()
    return RunStorage(run_id=run_id, status=status, finished_at=finished, **extra)


def _dispositions(actions) -> dict[str, str]:
    return {a.run_id: str(a.disposition) for a in actions}


# — classification ——————————————————————————————————————————————————————————
def test_old_finished_run_is_expired():
    actions = plan_cleanup([_run("r1", days_ago=90, exists=True)], POLICY, NOW)
    assert _dispositions(actions) == {"r1": "expired"}
    assert actions[0].cleanable is True


def test_recent_run_is_retained():
    actions = plan_cleanup([_run("r1", days_ago=5, exists=True)], POLICY, NOW)
    assert _dispositions(actions) == {"r1": "retained"}
    assert actions[0].cleanable is False


def test_active_run_is_protected_even_when_old():
    """A run with a live worker must never be swept, however stale it looks."""
    actions = plan_cleanup(
        [_run("r1", status="running", days_ago=365, exists=True)], POLICY, NOW,
    )
    assert _dispositions(actions) == {"r1": "active"}
    assert actions[0].cleanable is False


def test_run_without_completion_time_is_protected():
    run = RunStorage(run_id="r1", status="completed", finished_at=None, exists=True)
    actions = plan_cleanup([run], POLICY, NOW)
    assert _dispositions(actions) == {"r1": "unfinished"}


def test_missing_directory_is_not_expired():
    """The core F07 distinction: gone is a restore problem, not a cleanup one."""
    actions = plan_cleanup([_run("r1", days_ago=90, exists=False)], POLICY, NOW)
    assert _dispositions(actions) == {"r1": "missing"}
    assert actions[0].cleanable is False


def test_missing_and_expired_are_distinguishable():
    runs = [_run("gone", days_ago=90, exists=False), _run("old", days_ago=90, exists=True)]
    result = _dispositions(plan_cleanup(runs, POLICY, NOW))
    assert result["gone"] == "missing"
    assert result["old"] == "expired"
    assert result["gone"] != result["old"]


def test_other_users_runs_are_out_of_scope():
    runs = [
        RunStorage(run_id="mine", user_id="u1", status="completed", exists=True,
                   finished_at=(NOW - timedelta(days=90)).isoformat()),
        RunStorage(run_id="theirs", user_id="u2", status="completed", exists=True,
                   finished_at=(NOW - timedelta(days=90)).isoformat()),
    ]
    result = _dispositions(plan_cleanup(runs, RetentionPolicy(keep_days=30, user_id="u1"), NOW))
    assert result["mine"] == "expired"
    assert result["theirs"] == "out_of_scope"


# — planning must not touch the disk —————————————————————————————————————————
def test_plan_never_deletes(tmp_path):
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "trace.jsonl").write_text("{}", encoding="utf-8")
    runs = [_run("r1", days_ago=90, exists=True, run_dir=str(run_dir))]
    plan_cleanup(runs, POLICY, NOW)
    assert run_dir.exists(), "planning is dry-run by construction"


def test_apply_removes_only_expired(tmp_path):
    root = tmp_path / "runs"
    expired = root / "r-old"
    retained = root / "r-new"
    for d in (expired, retained):
        d.mkdir(parents=True)
        (d / "f.txt").write_text("x", encoding="utf-8")

    actions = plan_cleanup([
        _run("r-old", days_ago=90, exists=True, run_dir=str(expired)),
        _run("r-new", days_ago=1, exists=True, run_dir=str(retained)),
    ], POLICY, NOW)
    removed = apply_cleanup(actions, root)

    assert removed == ["r-old"]
    assert not expired.exists()
    assert retained.exists(), "a retained run must survive an apply"


def test_apply_refuses_paths_outside_the_run_root(tmp_path):
    root = tmp_path / "runs"
    root.mkdir()
    outside = tmp_path / "elsewhere" / "r1"
    outside.mkdir(parents=True)
    (outside / "f.txt").write_text("x", encoding="utf-8")

    actions = plan_cleanup(
        [_run("r1", days_ago=90, exists=True, run_dir=str(outside))], POLICY, NOW,
    )
    assert actions[0].disposition is Disposition.EXPIRED, "plan says expired; apply still refuses"
    assert apply_cleanup(actions, root) == []
    assert outside.exists(), "a reference escaping the run root must not be followed"


# — manifest scanning and verification ——————————————————————————————————————
def test_scan_reports_size_and_digests(tmp_path):
    d = tmp_path / "r1"
    (d / "sub").mkdir(parents=True)
    (d / "a.txt").write_text("hello", encoding="utf-8")
    (d / "sub" / "b.txt").write_text("world", encoding="utf-8")
    count, total, digests = scan_run_dir(d)
    assert count == 2
    assert total == 10
    assert set(digests) == {"a.txt", "sub/b.txt"}


def test_scan_of_missing_directory_is_empty_not_error(tmp_path):
    assert scan_run_dir(tmp_path / "nope") == (0, 0, {})


def test_verify_detects_intact_missing_and_mismatch(tmp_path):
    intact = tmp_path / "r1"
    partial = tmp_path / "r2"
    changed = tmp_path / "r3"
    for d in (intact, partial, changed):
        d.mkdir(parents=True)
        (d / "f.txt").write_text("original", encoding="utf-8")
    (partial / "f.txt").unlink()

    _, _, good = scan_run_dir(intact)
    _, _, stale = scan_run_dir(changed)
    (changed / "f.txt").write_text("tampered", encoding="utf-8")

    runs = [
        RunStorage(run_id="r1", run_dir=str(intact), exists=True, digests=good),
        # digests recorded before the file disappeared
        RunStorage(run_id="r2", run_dir=str(partial), exists=True,
                   digests={"f.txt": "0" * 64}),
        RunStorage(run_id="r3", run_dir=str(changed), exists=True, digests=stale),
    ]
    results = {r.run_id: r.status for r in verify_against(runs)}

    assert results["r1"] == "ok"
    assert results["r2"] == "missing_files"
    assert results["r3"] == "digest_mismatch"


def test_verify_reports_a_vanished_directory(tmp_path):
    runs = [RunStorage(run_id="r1", run_dir=str(tmp_path / "gone"), exists=False,
                       digests={"f.txt": "0" * 64})]
    result = verify_against(runs)[0]
    assert result.status == "missing_dir"
    assert result.missing == ("f.txt",)


def test_manifest_round_trip(tmp_path):
    manifest = Manifest(generated_at="now", runs_root="/runs",
                        runs=[RunStorage(run_id="r1", status="completed", exists=True)])
    payload = json.loads(json.dumps(manifest.to_dict()))
    restored = Manifest.from_dict(payload)
    assert restored.runs[0].run_id == "r1"
    assert restored.runs[0].status == "completed"


def test_orphan_inventory_shapes_rows_without_user_text():
    from scripts.run_retention import build_orphan_class

    rows = [("run-1", "completed", "2026-09-01", "session-x"),
            ("run-2", "failed", "2026-09-02", "session-y")]
    cls = build_orphan_class("runs -> missing session", rows,
                             [("turns", 3), ("artifacts", 0)], limit=1)

    assert cls.count == 2, "count is the whole class, not the sample"
    assert cls.impact == {"turns": 3, "artifacts": 0}
    assert len(cls.sample) == 1, "sample is capped so the export stays small"
    assert cls.sample[0]["id"] == "run-1"
    assert cls.sample[0]["reference"] == "session-x"
    assert cls.remediation, "a class with no documented option cannot be decided on"


def test_orphan_inventory_tolerates_null_columns():
    from scripts.run_retention import build_orphan_class

    cls = build_orphan_class("turns -> missing run", [("t-1", None, None, None)], None)
    assert cls.sample[0]["detail"] == ""
    assert cls.sample[0]["created_at"] == ""
    assert cls.impact == {}


def test_verdict_distinguishes_clean_from_dirty():
    from scripts.run_retention import verdict_for

    assert verdict_for([("runs -> missing session", 0), ("audit_log -> missing user", 0)]) == "clean"
    dirty = verdict_for([("runs -> missing session", 517), ("audit_log -> missing user", 0)])
    assert "runs -> missing session" in dirty
    assert "audit_log" not in dirty, "only the non-zero classes belong in the verdict"


# — CLI guards ——————————————————————————————————————————————————————————————
def test_cli_plan_is_dry_run_by_default(tmp_path, capsys):
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "f.txt").write_text("x", encoding="utf-8")
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps(Manifest(
        generated_at="now", runs_root=str(tmp_path / "runs"),
        runs=[_run("r1", days_ago=90, exists=True, run_dir=str(run_dir))],
    ).to_dict()), encoding="utf-8")

    assert main(["plan", "--manifest", str(manifest)]) == 0
    assert run_dir.exists(), "the CLI must not delete unless asked to"
    assert "dry-run" in capsys.readouterr().out


def test_cli_apply_without_yes_is_refused(tmp_path):
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps(
        Manifest(generated_at="now", runs_root=str(tmp_path)).to_dict()), encoding="utf-8")
    assert main(["plan", "--manifest", str(manifest), "--apply"]) == 2


@pytest.mark.parametrize("status", sorted({"queued", "running"}))
def test_every_active_status_is_protected(status):
    actions = plan_cleanup([_run("r1", status=status, days_ago=999, exists=True)], POLICY, NOW)
    assert actions[0].disposition is Disposition.ACTIVE
