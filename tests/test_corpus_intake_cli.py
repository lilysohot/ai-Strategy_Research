"""Source receipts bind bytes; registration never bypasses admission policy."""

import copy
import json
import os
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from plugins.corpus import cli
from plugins.corpus.preparation.intake import authorization_decisions, source_hash
from plugins.corpus.preparation.repository import MemoryStore
from plugins.corpus.retrieval.contextual import ContextNoteError
from plugins.corpus.retrieval.source_scope import extend_scope, load_scope, select_sources


@pytest.fixture
def intake(tmp_path, monkeypatch):
    source = tmp_path / "report.md"
    source.write_text("# Company research report\n\nCompany earnings rose in 2026.")
    sid = source_hash(str(source))
    manifest = {
        "archive_root": str(tmp_path / "archive"),
        "sources": [
            {
                "path": str(source),
                "source_id": sid,
                "domain_hint": "company",
                "review_decision_ids": ["approval-1"],
            }
        ],
    }
    record = {
        "operator": "test-operator",
        "authorized_by": "test-user",
        "authorized_at": "2026-10-31T12:00:00+08:00",
        "authorization_ref": "test-user-message",
        "sources": [
            {
                "source_id": sid,
                "decision_id": "approval-1",
                "material_type": "research_report",
                "research_domain": "company",
            }
        ],
    }
    store = MemoryStore(clock=lambda: datetime.now(UTC))
    monkeypatch.setattr(cli, "_open_store", lambda _: nullcontext(store))
    monkeypatch.setattr(cli.read_pg, "coverage_snapshot", lambda *args, **kwargs: {})
    return source, manifest, record, store


def write(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return str(path)


def test_admit_build_check_publish_roundtrip(intake, tmp_path, capsys):
    _, manifest, record, store = intake
    mp = write(tmp_path, "manifest.json", manifest)
    rp = write(tmp_path, "authorization.json", record)
    for _ in range(2):
        assert cli.main(["admit", "--manifest", mp, "--record", rp]) == 0
        capsys.readouterr()
    decision = store.get_reviewed_decision(record["sources"][0]["decision_id"])
    assert decision.reviewer == "test-user"
    assert json.loads(decision.rationale)["operator"] == "test-operator"
    assert store.get_publication(decision.source_id) is None
    assert cli.main(["build", "--manifest", mp]) == 0
    result = json.loads(capsys.readouterr().out)
    bid = result["outcomes"][0]["build_id"]
    assert bid
    assert cli.main(["check", "--build", bid]) == 0
    capsys.readouterr()
    assert cli.main(["publish", "--build", bid, "--operator", "test"]) == 0
    assert store.get_publication(decision.source_id).active_build_id == bid


def test_changed_bytes_fail_before_registration_or_build(intake, tmp_path):
    source, manifest, record, store = intake
    source.write_text("changed bytes")
    mp = write(tmp_path, "manifest.json", manifest)
    rp = write(tmp_path, "authorization.json", record)
    assert cli.main(["admit", "--manifest", mp, "--record", rp]) == 2
    assert store.get_reviewed_decision("approval-1") is None
    assert cli.main(["build", "--manifest", mp]) == 2


@pytest.mark.parametrize(
    "change", ["missing", "extra", "wrong_id", "duplicate", "naive_time", "partial"]
)
def test_receipt_rejects_ambiguous_scope(intake, change):
    _, manifest, record, _ = intake
    if change == "missing":
        record["sources"] = []
    elif change == "extra":
        record["sources"][0]["source_id"] = "f" * 64
    elif change == "wrong_id":
        record["sources"][0]["decision_id"] = "another"
    elif change == "duplicate":
        record["sources"].append(copy.deepcopy(record["sources"][0]))
    elif change == "partial":
        record["sources"][0]["scope_ref"] = "page:1"
    else:
        record["authorized_at"] = "2026-10-31"
    with pytest.raises(ValueError):
        authorization_decisions(manifest, record)


def test_conflicting_receipt_is_not_overwritten(intake, tmp_path):
    _, manifest, record, store = intake
    decision = authorization_decisions(manifest, record)[0]
    old = replace(decision, reviewer="another-user")
    store.put_reviewed_decision(old)
    assert (
        cli.main(
            [
                "admit",
                "--manifest",
                write(tmp_path, "manifest.json", manifest),
                "--record",
                write(tmp_path, "record.json", record),
            ]
        )
        == 4
    )
    assert store.get_reviewed_decision(decision.decision_id) == old


def test_incremental_scope_preserves_exclusions_and_rejects_inactive(intake, tmp_path):
    _, manifest, _, _ = intake
    sid = manifest["sources"][0]["source_id"]
    write_path = tmp_path / "manifest.json"
    write_path.write_text(json.dumps(manifest))
    scope = extend_scope(["a" * 64], write_path)
    assert set(scope["source_allowlist"]) == {"a" * 64, sid}
    scope_path = tmp_path / "scope.json"
    scope_path.write_text(json.dumps(scope))
    ids = load_scope(scope_path)
    active = {key: {"build_id": key} for key in ["a" * 64, "b" * 64, sid]}
    assert set(select_sources(active, ids)) == {"a" * 64, sid}
    del active[sid]
    with pytest.raises(ContextNoteError, match="not_active"):
        select_sources(active, ids)


def test_empty_scope_cannot_expand_to_all():
    with pytest.raises(ContextNoteError):
        select_sources({"a" * 64: {}}, [])


@pytest.mark.parametrize("operation", ["plan", "status", "generate", "build_pack"])
def test_all_context_operations_filter_before_reading_or_generating(
    operation, monkeypatch, tmp_path
):
    from unittest.mock import MagicMock

    from plugins.corpus.retrieval import contextual_pg

    class ProjectionReached(Exception):
        pass

    wanted = "a" * 64
    excluded = "b" * 64
    active = {wanted: {"build_id": "wanted"}, excluded: {"build_id": "excluded"}}
    conn = MagicMock()
    cur = conn.__enter__.return_value.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (True,)
    monkeypatch.setattr(contextual_pg, "_connect", lambda *args: conn)
    monkeypatch.setattr(contextual_pg, "initialize", lambda *args: None)
    monkeypatch.setattr(contextual_pg, "_active", lambda _: active)

    def project(_, selected):
        assert set(selected) == {wanted}
        raise ProjectionReached

    monkeypatch.setattr(contextual_pg, "_projected", project)
    config = MagicMock(input_variant="contextual-note-v1")
    args = ("dsn", "test")
    if operation == "generate":
        args += (config, MagicMock())
    elif operation == "build_pack":
        args += (tmp_path / "pack", config)
    with pytest.raises(ProjectionReached):
        getattr(contextual_pg, operation)(*args, source_ids=[wanted])


def test_admission_receipt_does_not_bypass_policy(intake, tmp_path, capsys):
    _, manifest, record, store = intake
    record["sources"][0]["material_type"] = "personal_or_external_subscription"
    mp = write(tmp_path, "manifest.json", manifest)
    assert (
        cli.main(["admit", "--manifest", mp, "--record", write(tmp_path, "record.json", record)])
        == 0
    )
    capsys.readouterr()
    assert cli.main(["build", "--manifest", mp]) == 4
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["outcomes"][0]["decision"] == "review_required"
    assert payload["outcomes"][0]["build_id"] is None
    assert store.get_publication(manifest["sources"][0]["source_id"]) is None


@pytest.mark.skipif(not os.getenv("CORPUS_INTAKE_TEST_DB"), reason="dedicated PG database required")
def test_pg_admit_build_check_publish(intake, tmp_path, capsys, monkeypatch):
    from psycopg.conninfo import make_conninfo

    from plugins.corpus.preparation.repository_pg import PgStore
    from plugins.corpus.service import dsn

    monkeypatch.undo()  # Exercise the real PG coverage read as well as the write path.
    target = os.environ["CORPUS_INTAKE_TEST_DB"]
    assert target.startswith("corpus_intake_test_")
    connection = make_conninfo(dsn(), dbname=target)
    monkeypatch.setenv("CORPUS_TARGET_DB", target)
    monkeypatch.setenv("CORPUS_I2_DSN", connection)
    monkeypatch.setattr(cli, "_open_store", lambda _: PgStore(connection, sandbox_db=target))
    source, manifest, record, _ = intake
    source.write_text(source.read_text() + f"\nSynthetic run: {tmp_path}\n")
    sid = source_hash(str(source))
    did = "integration-" + sid
    manifest["sources"][0].update(source_id=sid, review_decision_ids=[did])
    record["sources"][0].update(source_id=sid, decision_id=did)
    with PgStore(connection, sandbox_db=target) as store:
        test_admit_build_check_publish_roundtrip(
            (source, manifest, record, store), tmp_path, capsys
        )
