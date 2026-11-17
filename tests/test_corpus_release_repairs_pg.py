"""Opt-in disposable-database recovery tests. No real provider calls or corpus mutations.

CORPUS_RELEASE_TEST_PG=1 uv run --env-file .env pytest tests/test_corpus_release_repairs_pg.py
"""

import json
import os
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from plugins.corpus.retrieval import contextual, contextual_pg, index_pg
from plugins.corpus.retrieval.embedding import (
    EmbeddingError,
    EmbeddingResult,
    VectorConfig,
    text_hash,
)
from plugins.corpus.service import dsn

pytestmark = pytest.mark.skipif(
    os.getenv("CORPUS_RELEASE_TEST_PG") != "1", reason="disposable PG database opt-in required"
)


class RedactedDSN(str):
    def __repr__(self):
        return "<disposable-test-dsn>"


@pytest.fixture
def database(monkeypatch):
    name = "vector_pilot_repair_" + uuid4().hex[:12]
    admin_dsn = dsn()
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    target_dsn = RedactedDSN(make_conninfo("", **{**conninfo_to_dict(admin_dsn), "dbname": name}))
    monkeypatch.setenv("CORPUS_TARGET_DB", name)
    monkeypatch.setattr(contextual_pg, "_pause", lambda *a: None)
    try:
        with psycopg.connect(target_dsn, autocommit=True) as conn:
            conn.execute("CREATE EXTENSION vector")
            conn.execute(index_pg.DDL)
            conn.execute(contextual_pg.DDL)
        yield target_dsn, name, VectorConfig(target_db=name, dimensions=2)
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def test_uncertain_retry_is_bounded_durable_locked_and_reuses_ready(database, monkeypatch):
    from plugins.corpus.retrieval import native_sync

    target, _, config = database
    text = "测试输入"
    inputs = {text_hash(text): text}
    calls = []

    def fail(text, role):
        calls.append(text)
        raise EmbeddingError("provider_transport_uncertain", uncertain=True)

    with psycopg.connect(target, autocommit=True) as conn:
        assert contextual_pg._embed_missing(conn, config, inputs, fail, 1) == 1
    with psycopg.connect(target, autocommit=True) as conn:
        assert contextual_pg._embed_missing(conn, config, inputs, fail, 1) == 0

        def success(text, role):
            calls.append(text)
            seed = SimpleNamespace(manifest={"profile": config.profile}, chunks=[], vectors={})
            monkeypatch.setattr(native_sync, "refresh", lambda *a: seed)
            with pytest.raises(EmbeddingError, match="writer_already_running"):
                native_sync.sync(target, config.target_db, seed, config, fail, max_requests=1)
            with (
                psycopg.connect(target, autocommit=True) as competitor,
                pytest.raises(EmbeddingError, match="writer_already_running"),
            ):
                contextual_pg._embed_missing(
                    competitor, config, inputs, fail, 1, retry_uncertain=True
                )
            return EmbeddingResult((1.0, 0.0), {"total_tokens": 3})

        assert (
            contextual_pg._embed_missing(conn, config, inputs, success, 1, retry_uncertain=True)
            == 1
        )
        assert (
            contextual_pg._embed_missing(conn, config, inputs, fail, 1, retry_uncertain=True) == 0
        )
        assert len(calls) == 2
        assert conn.execute(
            "SELECT state FROM corpus_retrieval.context_attempts ORDER BY attempt"
        ).fetchall() == [("uncertain",), ("ready",)]
        assert conn.execute(
            "SELECT status,attempts,error_code FROM corpus_retrieval.embeddings"
        ).fetchone() == ("ready", 2, None)


def test_vector_retry_budget_survives_restarts(database):
    target, _, config = database

    def fail(*args):
        raise EmbeddingError("provider_transport_uncertain", uncertain=True)

    for expected in (1, 1, 0):
        with psycopg.connect(target, autocommit=True) as conn:
            assert (
                contextual_pg._embed_missing(
                    conn, config, {text_hash("x"): "x"}, fail, 10, retry_uncertain=True
                )
                == expected
            )


@pytest.fixture
def source(monkeypatch):
    text = "2026.11.1310:16期五。公司扩展产能。"
    chunk = {"build_id": "b", "source_id": "s", "chunk_id": "c", "search_text": text}
    monkeypatch.setattr(contextual_pg, "_active", lambda cur: {"s": {"build_id": "b"}})
    monkeypatch.setattr(contextual_pg, "_projected", lambda *a: [chunk])
    monkeypatch.setattr(contextual_pg, "_documents", lambda *a: {"b": text})
    return text


def test_rejected_notes_resume_without_paid_retry_and_keep_receipt(database, source):
    target, name, _ = database
    config = contextual.NoteConfig(model="test")

    def invalid(*args):
        return contextual.NoteBatch({"c": "2026.11.13的产能计划"}, {"total_tokens": 7})

    first = contextual_pg.generate(target, name, config, invalid, max_requests=1)
    assert first["missing"] == 1
    assert first["reported_tokens_this_run"] == 7
    second = contextual_pg.generate(
        target, name, config, lambda *a: pytest.fail("no retry"), max_requests=1
    )
    assert second["requests_this_run"] == 0
    recovered = contextual_pg.generate(
        target,
        name,
        config,
        lambda *a: pytest.fail("no model"),
        max_requests=0,
        extractive_fallback=True,
    )
    assert recovered["missing"] == 0
    assert recovered["notes_extracted_this_run"] == 1
    with psycopg.connect(target, autocommit=True) as conn:
        note, meta = conn.execute(
            "SELECT note,generator FROM corpus_retrieval.chunk_context"
        ).fetchone()
        contextual.validate_stored_note(note, source, meta)
        assert conn.execute(
            "SELECT usage->>'total_tokens' FROM corpus_retrieval.context_attempts"
        ).fetchone() == ("7",)


def test_note_crash_is_not_silently_retried(database, source):
    target, name, _ = database
    config = contextual.NoteConfig(model="test")

    def crash(*args):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        contextual_pg.generate(target, name, config, crash, max_requests=1)
    skipped = contextual_pg.generate(
        target, name, config, lambda *a: pytest.fail("unknown outcome"), max_requests=1
    )
    assert skipped["requests_this_run"] == 0
    result = contextual_pg.generate(
        target,
        name,
        config,
        lambda *a: contextual.NoteBatch({"c": "公司扩展产能"}, {"total_tokens": 2}),
        max_requests=1,
        retry_uncertain=True,
    )
    assert result["missing"] == 0


def test_partial_pack_preserves_baseline_and_isolates_new_failures(database, monkeypatch, tmp_path):
    from plugins.corpus.retrieval.native import NativeIndex

    target, name, config = database
    config = replace(config, input_variant="contextual-note-v1")
    texts = {
        text_hash("s1"): "公司原有的产能计划依然有效。",
        text_hash("s2"): "新增公司的经营情况良好。",
        text_hash("s3"): "故障公司的供应链发生变化。",
        text_hash("s4"): "尚未生成说明的研究材料。",
    }
    active = {}
    chunks = []
    units = {}
    for sid, text in texts.items():
        active[sid] = {
            "build_id": sid,
            "generation": 1,
            "date": None,
            "basis": "unknown",
            "names": [sid],
        }
        chunks.append(
            {
                "source_id": sid,
                "build_id": sid,
                "chunk_id": sid,
                "kind": "body",
                "search_text": text,
                "unit_refs": [sid],
            }
        )
        units[sid, sid] = {
            "build_id": sid,
            "unit_id": sid,
            "raw_text": text,
            "content_hash": text_hash(text),
            "location": {"page": 1},
            "kind": "paragraph",
            "status": "kept",
            "eligible": True,
        }
    monkeypatch.setattr(contextual_pg, "_active", lambda cur: active)
    monkeypatch.setattr(
        contextual_pg,
        "_projected",
        lambda cur, selected: [c for c in chunks if c["source_id"] in selected],
    )
    monkeypatch.setattr(contextual_pg, "_documents", lambda cur, builds: texts)
    monkeypatch.setattr(contextual_pg, "_units", lambda cur, builds: units)
    monkeypatch.setattr(contextual_pg, "refresh", lambda dsn, target, index: index)

    def notes(doc, batch):
        return contextual.NoteBatch({cid: "公司研究材料" for cid, _ in batch}, {})

    contextual_pg.generate(
        target,
        name,
        contextual.NoteConfig(),
        notes,
        max_requests=3,
        source_ids=[text_hash("s1"), text_hash("s2"), text_hash("s3")],
    )

    def embed(text, role):
        if "故障" in text:
            raise EmbeddingError("provider_transport_uncertain", uncertain=True)
        return EmbeddingResult((1.0, 0.0), {})

    baseline = tmp_path / "baseline"
    contextual_pg.build_pack(
        target, name, baseline, config, embed=embed, max_requests=1, source_ids=[text_hash("s1")]
    )
    result = contextual_pg.build_pack(
        target,
        name,
        tmp_path / "partial",
        config,
        embed=embed,
        max_requests=3,
        source_ids=list(texts),
        partial_from=baseline / "manifest.json",
    )
    assert result["partial"] is True and result["web_activated"] is False
    assert result["sources"] == 2
    assert result["deferred_sources"] == {
        text_hash("s3"): "contextual_pack_vectors_pending",
        text_hash("s4"): "contextual_pack_notes_incomplete",
    }
    old = NativeIndex(baseline / "manifest.json")
    new = NativeIndex(tmp_path / "partial" / "manifest.json")
    assert new.chunks[0] == old.chunks[0]
    assert (
        new.units[text_hash("s1"), text_hash("s1")] == old.units[text_hash("s1"), text_hash("s1")]
    )

    def fail_validation(*args):
        raise contextual.ContextNoteError("test_validation_failure")

    monkeypatch.setattr(contextual_pg, "refresh", fail_validation)
    with pytest.raises(contextual.ContextNoteError, match="test_validation_failure"):
        contextual_pg.build_pack(
            target, name, tmp_path / "invalid", config, source_ids=[text_hash("s1")]
        )
    assert not (tmp_path / "invalid").exists()


def test_full_backup_covers_native_tables_and_can_restore(database, tmp_path):
    from plugins.corpus.backup import full_backup
    from plugins.corpus.service import CorpusService

    target, _, _ = database
    with psycopg.connect(target, autocommit=True) as conn:
        conn.execute("CREATE SCHEMA corpus")
        conn.execute("CREATE TABLE corpus.example(id integer PRIMARY KEY, body text)")
        conn.execute("INSERT INTO corpus.example VALUES (1,'完整原文')")
    archive = tmp_path / "source"
    archive.mkdir()
    (archive / "original.md").write_text("完整原文")
    container = os.getenv("CORPUS_TEST_PG_CONTAINER")
    dump = full_backup(target, tmp_path / "backup", archive_root=archive, container=container)
    manifest = json.loads(dump.with_name("manifest.json").read_text())
    assert manifest["counts"]["corpus.example"] == 1
    assert "corpus_retrieval.chunk_context" in manifest["counts"]
    assert (dump.parent / "archive" / "original.md").read_text() == "完整原文"
    # Only disposable fixture DB is cleared and restored; the production DB is never a target.
    with psycopg.connect(target, autocommit=True) as conn:
        conn.execute("DROP SCHEMA corpus CASCADE")
        conn.execute("DROP SCHEMA corpus_retrieval CASCADE")
    service = CorpusService(target)
    restored = service.restore(
        dump, target, archive_out=tmp_path / "restored", pg_container=container
    )
    assert restored == manifest["counts"]
    assert (tmp_path / "restored" / "original.md").read_text() == "完整原文"
    with psycopg.connect(target, autocommit=True) as conn:
        assert conn.execute("SELECT * FROM corpus.example").fetchone() == (1, "完整原文")
        for qualified, count in manifest["counts"].items():
            schema, table = qualified.split(".")
            assert (
                conn.execute(
                    sql.SQL("SELECT count(*) FROM {}.{}").format(
                        sql.Identifier(schema), sql.Identifier(table)
                    )
                ).fetchone()[0]
                == count
            )
