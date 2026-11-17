"""Contextual Retrieval 的落地三件事：说明落库、说明盘点、上下文索引包。

职责边界：

- **说明（note）**：整篇文档 + 单个片段 → 模型生成的简短说明，只存侧表
  ``corpus_retrieval.chunk_context``，不是原文、不登记为证据。
- **索引包（pack）**：把「说明 + 原文片段」写成 ``native-evidence-contextual-1``，
  同一份 ``index_text`` 同时供词法（``search_tsv``）与稠密向量使用；原文投影与
  切片坐标保持原样。
- 不改 ``corpus_units`` / ``corpus_chunks`` / 发布指针，不重切块。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from plugins.corpus.preparation.search_pg import _check_target
from plugins.corpus.retrieval import attempts, contextual
from plugins.corpus.retrieval.embedding import (
    EmbeddingError,
    EmbeddingResult,
    Role,
    VectorConfig,
    text_hash,
    validate_vector,
)
from plugins.corpus.retrieval.native import NativeIndex
from plugins.corpus.retrieval.native_live import _date, _units, project, refresh
from plugins.corpus.retrieval.source_scope import select_sources

DDL = (
    """
CREATE SCHEMA IF NOT EXISTS corpus_retrieval;
CREATE TABLE IF NOT EXISTS corpus_retrieval.chunk_context (
    context_version text NOT NULL,
    source_id text NOT NULL,
    build_id text NOT NULL,
    chunk_id text NOT NULL,
    note text NOT NULL,
    note_chars integer NOT NULL,
    document_hash text NOT NULL,
    chunk_hash text NOT NULL,
    input_hash text NOT NULL,
    prompt_version text NOT NULL,
    generator jsonb NOT NULL DEFAULT '{}',
    status text NOT NULL CHECK (status IN ('running', 'ready', 'rejected')),
    reject_code text,
    attempts integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (context_version, build_id, chunk_id)
);
ALTER TABLE corpus_retrieval.chunk_context ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0;
"""
    + attempts.DDL
)

#: 只取活动发布范围，且来源与 build 都仍在范围内（撤回即不生成、不返回）。
ACTIVE_SQL = """
SELECT p.source_id, p.active_build_id, p.generation, s.original_names,
       m.confirmed_publication_date::text,
       a.metadata_snapshot->'report_publication'->>'value'
FROM corpus.corpus_publications p
JOIN corpus.corpus_sources s USING(source_id)
JOIN corpus.corpus_builds b ON b.build_id = p.active_build_id
JOIN corpus.corpus_admissions a ON a.decision_id = b.decision_id
JOIN corpus.corpus_admissions live ON live.decision_id = p.current_decision_id
JOIN corpus.corpus_admissions source_admission
  ON source_admission.decision_id = s.current_decision_id
LEFT JOIN corpus_retrieval.source_metadata m ON m.source_id = p.source_id
WHERE live.decision = 'in_scope' AND source_admission.decision = 'in_scope'
ORDER BY p.source_id
"""

CHUNK_SQL = """
SELECT build_id, chunk_id, kind, title_text, section_path, unit_refs, context_refs, search_text
FROM corpus.corpus_chunks WHERE build_id = ANY(%s::text[])
ORDER BY build_id, chunk_id
"""

DOCUMENT_SQL = """
SELECT build_id, unit_id, ordinal, raw_text FROM corpus.corpus_units
WHERE build_id = ANY(%s::text[]) ORDER BY build_id, ordinal NULLS LAST, unit_id
"""


def document_text(rows: Sequence[tuple[str, str, int | None, str]]) -> str:
    """整篇文档的确定性拼接：按 ordinal 排序，只丢空白单元，不改写任何字。"""
    parts = [raw for _, _, _, raw in rows if raw and raw.strip()]
    return "\n".join(parts)


def plan_batches(chunk_ids: Sequence[str], per_request: int) -> list[list[str]]:
    return contextual.plan_batches(chunk_ids, per_request)


def _connect(dsn: str, target: str) -> psycopg.Connection:
    conn = psycopg.connect(dsn, autocommit=True, connect_timeout=10)
    try:
        _check_target(conn, target)
    except Exception:
        conn.close()
        raise
    return conn


def _active(cur: psycopg.Cursor) -> dict[str, dict[str, Any]]:
    cur.execute(ACTIVE_SQL)
    result = {}
    for source_id, build_id, generation, names, reviewed, admitted in cur.fetchall():
        value, basis = _date(names, reviewed, admitted)
        result[source_id] = {
            "source_id": source_id,
            "build_id": build_id,
            "generation": generation,
            "names": names,
            "date": value,
            "basis": basis,
        }
    return result


def _projected(cur: psycopg.Cursor, active: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """按既有 native 投影口径选块；table 块不参与（与当前发布一致）。"""
    builds = [entry["build_id"] for entry in active.values()]
    if not builds:
        return []
    units = _units(cur, builds)
    owners = {entry["build_id"]: sid for sid, entry in active.items()}
    cur.execute(CHUNK_SQL, (builds,))
    result = []
    for row in cur.fetchall():
        build_id = row[0]
        by_build = {uid: u for (b, uid), u in units.items() if b == build_id}
        chunk = project(
            {
                "source_id": owners[build_id],
                "build_id": build_id,
                "chunk_id": row[1],
                "kind": row[2],
                "title_text": row[3],
                "section_path": row[4],
                "unit_refs": row[5],
                "context_refs": row[6],
                "search_text": row[7],
            },
            by_build,
        )
        if chunk:
            result.append(chunk)
    return result


def _documents(cur: psycopg.Cursor, builds: Sequence[str]) -> dict[str, str]:
    cur.execute(DOCUMENT_SQL, (list(builds),))
    grouped: dict[str, list[tuple[str, str, int | None, str]]] = {}
    for build_id, unit_id, ordinal, raw in cur.fetchall():
        grouped.setdefault(build_id, []).append((build_id, unit_id, ordinal, raw))
    return {build_id: document_text(rows) for build_id, rows in grouped.items()}


def _ready_notes(cur: psycopg.Cursor, version: str) -> dict[tuple[str, str], str]:
    cur.execute(
        "SELECT build_id, chunk_id, note FROM corpus_retrieval.chunk_context "
        "WHERE context_version=%s AND status='ready'",
        (version,),
    )
    return {(bid, cid): note for bid, cid, note in cur.fetchall()}


def _schema_ready(cur: psycopg.Cursor) -> bool:
    cur.execute("SELECT to_regclass('corpus_retrieval.chunk_context')")
    row = cur.fetchone()
    return row is not None and row[0] is not None


def initialize(dsn: str, target: str) -> None:
    with _connect(dsn, target) as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute(DDL)


def plan(
    dsn: str,
    target: str,
    *,
    context_version: str = contextual.CONTEXT_VERSION,
    chunks_per_request: int = 6,
    source_ids: Sequence[str] | None = None,
) -> dict:
    """只读盘点：多少块、多少文档、要花多少次请求与多少 token。不动库、不调模型。"""
    with _connect(dsn, target) as conn, conn.cursor() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        active = select_sources(_active(cur), source_ids)
        chunks = _projected(cur, active)
        documents = _documents(cur, [entry["build_id"] for entry in active.values()])
        have = _ready_notes(cur, context_version) if _schema_ready(cur) else {}
    batches = 0
    estimated = 0
    for build_id, group in _by_build(chunks).items():
        doc = documents.get(build_id, "")
        for batch in plan_batches([c["chunk_id"] for c in group], chunks_per_request):
            batches += 1
            estimated += contextual.token_estimate(doc)
            estimated += sum(
                contextual.token_estimate(c["search_text"])
                for c in group
                if c["chunk_id"] in set(batch)
            )
    texts = {text_hash(c["search_text"]) for c in chunks}
    return {
        "context_version": context_version,
        "prompt_version": contextual.PROMPT_VERSION,
        "sources": len(active),
        "projected_chunks": len(chunks),
        "unique_chunk_texts": len(texts),
        "documents": len(documents),
        "document_chars": sum(len(value) for value in documents.values()),
        "chunks_per_request": chunks_per_request,
        "estimated_requests": batches,
        "estimated_input_tokens": estimated,
        "notes_ready": sum(1 for c in chunks if (c["build_id"], c["chunk_id"]) in have),
        "notes_missing": sum(1 for c in chunks if (c["build_id"], c["chunk_id"]) not in have),
        "tables_excluded": True,
    }


def _by_build(chunks: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        grouped.setdefault(chunk["build_id"], []).append(chunk)
    return grouped


def status(
    dsn: str,
    target: str,
    *,
    context_version: str = contextual.CONTEXT_VERSION,
    source_ids: Sequence[str] | None = None,
) -> dict:
    with _connect(dsn, target) as conn, conn.cursor() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        active = select_sources(_active(cur), source_ids)
        chunks = _projected(cur, active)
        if not _schema_ready(cur):
            return {
                "context_version": context_version,
                "schema_ready": False,
                "projected_chunks": len(chunks),
            }
        cur.execute(
            "SELECT status, count(*) FROM corpus_retrieval.chunk_context "
            "WHERE context_version=%s AND build_id = ANY(%s::text[]) GROUP BY status",
            (context_version, [a["build_id"] for a in active.values()]),
        )
        states = {str(row[0]): int(row[1]) for row in cur.fetchall()}
        cur.execute(
            "SELECT coalesce(sum((generator->>'total_tokens')::bigint),0) "
            "FROM corpus_retrieval.chunk_context WHERE context_version=%s "
            "AND build_id = ANY(%s::text[])",
            (context_version, [a["build_id"] for a in active.values()]),
        )
        token_row = cur.fetchone()
        tokens = int(token_row[0]) if token_row else 0
        have = _ready_notes(cur, context_version)
        cur.execute("SELECT to_regclass('corpus_retrieval.context_attempts')")
        receipt_table = cur.fetchone()
        recorded_tokens = unknown_attempts = 0
        if receipt_table and receipt_table[0]:
            keys = [
                text_hash(context_version + ":" + c["build_id"] + ":" + c["chunk_id"])
                for c in chunks
            ]
            cur.execute(
                "SELECT coalesce(sum((usage->>'total_tokens')::bigint),0),"
                "count(*) FILTER (WHERE state IN ('running','uncertain')) "
                "FROM corpus_retrieval.context_attempts "
                "WHERE operation='note' AND request_key=ANY(%s::text[])",
                (keys,),
            )
            totals = cur.fetchone()
            if totals:
                recorded_tokens, unknown_attempts = map(int, totals)
    return {
        "context_version": context_version,
        "schema_ready": True,
        "sources": len(active),
        "projected_chunks": len(chunks),
        "ready": sum(1 for c in chunks if (c["build_id"], c["chunk_id"]) in have),
        "missing": sum(1 for c in chunks if (c["build_id"], c["chunk_id"]) not in have),
        "states": states,
        "reported_total_tokens": tokens,
        "usage_basis": "latest_note_rows_not_cumulative",
        "recorded_attempt_tokens": recorded_tokens,
        "unknown_cost_attempts": unknown_attempts,
        "attempt_history_scope": "receipts_since_recovery_upgrade_only",
    }


def generate(
    dsn: str,
    target: str,
    config: contextual.NoteConfig,
    generate_batch: Callable[[str, list[tuple[str, str]]], contextual.NoteBatch],
    *,
    max_requests: int = 0,
    context_version: str = contextual.CONTEXT_VERSION,
    source_ids: Sequence[str] | None = None,
    retry_failed: bool = False,
    retry_uncertain: bool = False,
    max_attempts: int = 2,
    extractive_fallback: bool = False,
) -> dict[str, Any]:
    """Resume notes under a session lock; unknown outcomes require explicit permission."""
    if max_requests < 0 or not 1 <= max_attempts <= 10:
        raise contextual.ContextNoteError("invalid_request_budget")
    initialize(dsn, target)
    requested = ready = rejected = blocked = extracted = tokens = 0
    error: str | None = None
    with _connect(dsn, target) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s,0))",
            ("corpus-context:" + context_version,),
        )
        row = cur.fetchone()
        if row is None or not row[0]:
            raise contextual.ContextNoteError("context_writer_already_running")
        active = select_sources(_active(cur), source_ids)
        chunks = _projected(cur, active)
        documents = _documents(cur, [entry["build_id"] for entry in active.values()])
        cur.execute(
            "SELECT build_id,chunk_id,status,attempts,reject_code "
            "FROM corpus_retrieval.chunk_context WHERE context_version=%s",
            (context_version,),
        )
        existing = {
            (bid, cid): (state, max(1, tried), code)
            for bid, cid, state, tried, code in cur.fetchall()
        }
        for build_id, group in _by_build(chunks).items():
            document = documents.get(build_id, "")
            if not document.strip():
                blocked += len(group)
                continue
            pending = []
            for chunk in group:
                state, tried, code = existing.get((build_id, chunk["chunk_id"]), (None, 0, None))
                if state == "ready":
                    continue
                # Rejected content can be recovered without paying for another model call.
                if (
                    extractive_fallback
                    and state == "rejected"
                    and _extract_rejected(cur, context_version, chunk, document, config, code)
                ):
                    ready += 1
                    extracted += 1
                    continue
                if attempts.can_retry(
                    state, tried, max_attempts, failed=retry_failed, uncertain=retry_uncertain
                ):
                    pending.append(chunk)
                else:
                    blocked += 1
            by_id = {c["chunk_id"]: c for c in pending}
            for batch_ids in plan_batches(list(by_id), config.chunks_per_request):
                if requested >= max_requests:
                    break
                batch = [(cid, by_id[cid]["search_text"]) for cid in batch_ids]
                receipts = {}
                # Transaction commits both the running markers and receipts before network I/O.
                with conn.transaction():
                    for cid, _ in batch:
                        tried = existing.get((build_id, cid), (None, 0, None))[1] + 1
                        key = text_hash(context_version + ":" + build_id + ":" + cid)
                        started = attempts.begin(cur, "note", key, tried)
                        receipts[cid] = (key, tried, started)
                        _write(
                            cur,
                            context_version,
                            by_id[cid],
                            note="",
                            document=document,
                            state="running",
                            code="request_started",
                            generator=config,
                            usage={},
                            attempt_count=tried,
                        )
                requested += 1
                try:
                    result = generate_batch(document, batch)
                except contextual.ContextNoteError as exc:
                    error = exc.code
                    with conn.transaction():
                        for cid, _ in batch:
                            key, tried, started = receipts[cid]
                            attempts.finish(
                                cur,
                                "note",
                                key,
                                tried,
                                started,
                                "uncertain" if exc.uncertain else "failed",
                                {},
                                exc.code,
                                exc.transport_kind,
                            )
                            _write(
                                cur,
                                context_version,
                                by_id[cid],
                                note="",
                                document=document,
                                state="running" if exc.uncertain else "rejected",
                                code=exc.code,
                                generator=config,
                                usage={},
                                attempt_count=tried,
                            )
                    # Transport/authentication failures stop paid work; completed rows persist.
                    break
                tokens += int(result.usage.get("total_tokens", 0))
                for cid, _ in batch:
                    raw = result.notes.get(cid, "")
                    usage = result.usage if cid == batch[0][0] else {}
                    code = None
                    try:
                        contextual.validate_note(raw, document)
                    except contextual.ContextNoteError as exc:
                        code = exc.code
                    key, tried, started = receipts[cid]
                    with conn.transaction():
                        attempts.finish(
                            cur,
                            "note",
                            key,
                            tried,
                            started,
                            "rejected" if code else "ready",
                            usage,
                            code,
                        )
                        _write(
                            cur,
                            context_version,
                            by_id[cid],
                            note=raw[: contextual.NOTE_MAX_CHARS * 2],
                            document=document,
                            state="rejected" if code else "ready",
                            code=code,
                            generator=config,
                            usage=usage,
                            attempt_count=tried,
                        )
                        if (
                            code
                            and extractive_fallback
                            and _extract_rejected(
                                cur, context_version, by_id[cid], document, config, code
                            )
                        ):
                            extracted += 1
                            code = None
                    if code:
                        rejected += 1
                    else:
                        ready += 1
            if error:
                break
    return {
        **status(dsn, target, context_version=context_version, source_ids=source_ids),
        "requests_this_run": requested,
        "notes_ready_this_run": ready,
        "notes_rejected_this_run": rejected,
        "notes_extracted_this_run": extracted,
        "blocked_this_run": blocked,
        "reported_tokens_this_run": tokens,
        "error_code": error,
    }


def _extract_rejected(
    cur: psycopg.Cursor,
    version: str,
    chunk: dict,
    document: str,
    config: contextual.NoteConfig,
    reason: str | None,
) -> bool:
    try:
        headings = [chunk.get("title_text") or "", *(chunk.get("section_path") or [])]
        note, provenance = contextual.extract_note(document, chunk["search_text"], headings)
    except contextual.ContextNoteError:
        return False
    _write(
        cur,
        version,
        chunk,
        note=note,
        document=document,
        state="ready",
        code=None,
        generator=config,
        usage={},
        provenance={**provenance, "fallback_reason": reason},
    )
    return True


def _write(
    cur: psycopg.Cursor,
    version: str,
    chunk: dict[str, Any],
    *,
    note: str,
    document: str,
    state: str,
    code: str | None,
    generator: contextual.NoteConfig,
    usage: dict[str, int],
    attempt_count: int | None = None,
    provenance: dict | None = None,
) -> None:
    cur.execute(
        """INSERT INTO corpus_retrieval.chunk_context
        (context_version, source_id, build_id, chunk_id, note, note_chars,
         document_hash, chunk_hash, input_hash, prompt_version, generator,
         status, reject_code, attempts)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (context_version, build_id, chunk_id) DO UPDATE SET
          note=EXCLUDED.note, note_chars=EXCLUDED.note_chars,
          document_hash=EXCLUDED.document_hash, chunk_hash=EXCLUDED.chunk_hash,
          input_hash=EXCLUDED.input_hash, generator=EXCLUDED.generator,
          status=EXCLUDED.status, reject_code=EXCLUDED.reject_code,
          prompt_version=EXCLUDED.prompt_version,
          attempts=greatest(corpus_retrieval.chunk_context.attempts,EXCLUDED.attempts)""",
        (
            version,
            chunk["source_id"],
            chunk["build_id"],
            chunk["chunk_id"],
            note,
            len(note),
            text_hash(document),
            text_hash(chunk["search_text"]),
            contextual.input_hash(note, chunk["search_text"]) if state == "ready" else "",
            (provenance or {}).get("method", contextual.PROMPT_VERSION),
            Jsonb(
                {
                    "profile": generator.profile,
                    "model": generator.model,
                    **usage,
                    **(provenance or {}),
                }
            ),
            state,
            code,
            attempt_count or 0,
        ),
    )


def _pause(seconds: float | None = None) -> None:
    """连发 embedding 会触发供应商限流；默认 0.25s 间隔，可用环境变量关闭。"""
    delay = (
        float(os.getenv("CORPUS_CONTEXT_EMBED_PAUSE_SECONDS", "0.25"))
        if seconds is None
        else seconds
    )
    if delay > 0:
        time.sleep(delay)


def _embed_missing(
    conn: psycopg.Connection,
    config: VectorConfig,
    texts: dict[str, str],
    embed: Callable[[str, Role], EmbeddingResult],
    max_requests: int,
    *,
    retry_failed: bool = False,
    retry_uncertain: bool = False,
    max_attempts: int = 2,
) -> int:
    """Reuse ready vectors, explicitly retry terminal/abandoned requests within a durable cap."""
    if max_requests < 0 or not 1 <= max_attempts <= 10:
        raise contextual.ContextNoteError("invalid_request_budget")
    lock = "corpus-vector:" + config.profile
    row = conn.execute("SELECT pg_try_advisory_lock(hashtextextended(%s,0))", (lock,)).fetchone()
    if not row or not row[0]:
        raise EmbeddingError("index_writer_already_running")
    try:
        conn.execute(attempts.DDL)
        requested = 0
        for input_hash, text in sorted(texts.items()):
            row = conn.execute(
                "SELECT status,attempts FROM corpus_retrieval.embeddings "
                "WHERE profile=%s AND input_hash=%s",
                (config.profile, input_hash),
            ).fetchone()
            state, tried = row if row else (None, 0)
            if not attempts.can_retry(
                state, tried, max_attempts, failed=retry_failed, uncertain=retry_uncertain
            ):
                continue
            if requested >= max_requests:
                break
            attempt = tried + 1
            key = text_hash(config.profile + ":" + input_hash)
            with conn.transaction(), conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO corpus_retrieval.embeddings "
                    "(profile,input_hash,dimensions,status,attempts) VALUES(%s,%s,%s,'running',%s) "
                    "ON CONFLICT (profile,input_hash) DO UPDATE SET status='running',"
                    "attempts=EXCLUDED.attempts,error_code=NULL,updated_at=now()",
                    (config.profile, input_hash, config.dimensions, attempt),
                )
                started = attempts.begin(cur, "vector", key, attempt)
            requested += 1
            try:
                result = embed(text, "document")
                vector = validate_vector(result.vector, config.dimensions)
            except EmbeddingError as exc:
                state = "uncertain" if exc.uncertain else "failed"
                with conn.transaction(), conn.cursor() as cur:
                    cur.execute(
                        "UPDATE corpus_retrieval.embeddings SET status=%s,error_code=%s,"
                        "updated_at=now() WHERE profile=%s AND input_hash=%s",
                        (state, exc.code, config.profile, input_hash),
                    )
                    attempts.finish(
                        cur,
                        "vector",
                        key,
                        attempt,
                        started,
                        state,
                        {},
                        exc.code,
                        exc.transport_kind,
                    )
                _pause(2.0)
                continue
            with conn.transaction(), conn.cursor() as cur:
                cur.execute(
                    "UPDATE corpus_retrieval.embeddings SET status='ready',embedding=%s::vector,"
                    "usage=%s,error_code=NULL,updated_at=now() WHERE profile=%s AND input_hash=%s",
                    (json.dumps(vector), Jsonb(result.usage), config.profile, input_hash),
                )
                attempts.finish(cur, "vector", key, attempt, started, "ready", result.usage)
            _pause()
        return requested
    finally:
        conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (lock,))


def build_pack(
    dsn: str,
    target: str,
    out: Path,
    config: VectorConfig,
    *,
    embed: Callable[[str, Role], EmbeddingResult] | None = None,
    max_requests: int = 0,
    context_version: str = contextual.CONTEXT_VERSION,
    release_id: str | None = None,
    source_ids: Sequence[str] | None = None,
    retry_failed: bool = False,
    retry_uncertain: bool = False,
    max_attempts: int = 2,
    partial_from: Path | None = None,
) -> dict[str, Any]:
    """写 ``native-evidence-contextual-1``：说明 + 原文片段，词法与向量同一输入。"""
    if config.input_variant != "contextual-note-v1":
        raise contextual.ContextNoteError("contextual_pack_requires_contextual_variant")
    if out.exists() and any(out.iterdir()):
        raise contextual.ContextNoteError("contextual_pack_output_not_empty")
    baseline = NativeIndex(partial_from) if partial_from else None
    if baseline and (
        baseline.manifest["target_db"] != target
        or baseline.manifest["profile"] != config.profile
        or baseline.manifest.get("context_version") != context_version
    ):
        raise contextual.ContextNoteError("partial_baseline_mismatch")
    with _connect(dsn, target) as conn, conn.cursor() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        all_active = _active(cur)
        active = select_sources(all_active, source_ids)
        chunks = _projected(cur, active)
        documents = _documents(cur, [entry["build_id"] for entry in active.values()])
        units = _units(cur, [entry["build_id"] for entry in active.values()])
        notes = _ready_notes(cur, context_version) if _schema_ready(cur) else {}
        cur.execute(
            "SELECT build_id,chunk_id,generator FROM corpus_retrieval.chunk_context "
            "WHERE context_version=%s AND status='ready'",
            (context_version,),
        )
        provenance = {(bid, cid): meta for bid, cid, meta in cur.fetchall()}
    protected = set(baseline.manifest["source_allowlist"]) if baseline else set()
    if baseline:
        for sid, bid, generation in baseline.manifest["publications"]:
            if sid not in active or (active[sid]["build_id"], active[sid]["generation"]) != (
                bid,
                generation,
            ):
                raise contextual.ContextNoteError("partial_baseline_publication_changed")
    deferred: dict[str, str] = {}
    missing = [c for c in chunks if (c["build_id"], c["chunk_id"]) not in notes]
    if missing:
        excluded = {c["source_id"] for c in missing}
        if baseline is None or excluded & protected:
            raise contextual.ContextNoteError("contextual_pack_notes_incomplete")
        deferred.update({sid: "contextual_pack_notes_incomplete" for sid in excluded})
        active = {sid: entry for sid, entry in active.items() if sid not in excluded}
        chunks = [c for c in chunks if c["source_id"] not in excluded]

    packed: list[dict[str, Any]] = []
    for chunk in chunks:
        note = notes[chunk["build_id"], chunk["chunk_id"]]
        text = chunk["search_text"]
        contextual.validate_stored_note(
            note,
            documents.get(chunk["build_id"], ""),
            provenance[chunk["build_id"], chunk["chunk_id"]],
        )
        applies = contextual.note_applies(text)
        packed.append(
            {
                "source_id": chunk["source_id"],
                "build_id": chunk["build_id"],
                "chunk_id": chunk["chunk_id"],
                "kind": chunk["kind"],
                "title_text": chunk.get("title_text"),
                "section_path": list(chunk.get("section_path") or ()),
                "unit_refs": list(chunk["unit_refs"]),
                "context_refs": [],
                "source_ranges": [],
                "search_text": text,
                "index_text": contextual.index_text(note, text) if applies else text,
                "input_hash": (contextual.input_hash(note, text) if applies else text_hash(text)),
            }
        )
    texts = {c["input_hash"]: c["index_text"] for c in packed}
    with _connect(dsn, target) as conn:
        embedded = (
            _embed_missing(
                conn,
                config,
                texts,
                embed,
                max_requests,
                retry_failed=retry_failed,
                retry_uncertain=retry_uncertain,
                max_attempts=max_attempts,
            )
            if embed
            else 0
        )
        vectors: dict[str, Any] = {}
        for input_hash in sorted(texts):
            row = conn.execute(
                "SELECT embedding::text FROM corpus_retrieval.embeddings "
                "WHERE profile=%s AND input_hash=%s AND status='ready' AND dimensions=%s",
                (config.profile, input_hash, config.dimensions),
            ).fetchone()
            if row is None:
                continue
            vectors[input_hash] = {
                "vector": validate_vector(json.loads(row[0]), config.dimensions),
                "origin": "embedding_cache",
            }
    pending = len(texts) - len(vectors)
    if pending:
        excluded = {c["source_id"] for c in packed if c["input_hash"] not in vectors}
        if baseline is None or excluded & protected:
            raise contextual.ContextNoteError("contextual_pack_vectors_pending")
        deferred.update({sid: "contextual_pack_vectors_pending" for sid in excluded})
        active = {sid: entry for sid, entry in active.items() if sid not in excluded}
        packed = [c for c in packed if c["source_id"] not in excluded]
        texts = {c["input_hash"]: c["index_text"] for c in packed}
        vectors = {key: value for key, value in vectors.items() if key in texts}
    if baseline:
        old = {(c["build_id"], c["chunk_id"]): c for c in baseline.chunks}
        retained = {
            (c["build_id"], c["chunk_id"]): c for c in packed if c["source_id"] in protected
        }
        if set(old) != set(retained) or any(
            old[key][field] != retained[key][field]
            for key in old
            for field in ("search_text", "index_text", "input_hash", "unit_refs")
        ):
            raise contextual.ContextNoteError("partial_baseline_content_changed")
        if any(
            key not in units
            or any(
                units[key][field] != unit[field]
                for field in ("raw_text", "content_hash", "location", "status", "eligible")
            )
            for key, unit in baseline.units.items()
        ) or any(
            tuple(vectors[c["input_hash"]]["vector"])
            != tuple(baseline.vectors[c["input_hash"]]["vector"])
            for c in old.values()
        ):
            raise contextual.ContextNoteError("partial_baseline_evidence_changed")

    source_of = {c["build_id"]: c["source_id"] for c in packed}
    needed = {(c["build_id"], uid) for c in packed for uid in c["unit_refs"]}
    unit_rows = []
    for key in sorted(needed):
        unit = units[key]
        unit_rows.append(
            {
                "source_id": source_of[key[0]],
                "build_id": key[0],
                "unit_id": key[1],
                "kind": unit["kind"],
                "raw_text": unit["raw_text"],
                "content_hash": unit["content_hash"],
                "location": unit["location"],
                "status": unit["status"],
                "eligible": unit["eligible"],
            }
        )
    dates = [
        {"source_id": sid, "date": entry["date"], "basis": entry["basis"], "names": entry["names"]}
        for sid, entry in sorted(active.items())
    ]
    # notes.json 只放「实际叠加进索引」的说明；碎片说明留在侧表可查，但不参与索引。
    note_rows = [
        {
            "build_id": c["build_id"],
            "chunk_id": c["chunk_id"],
            "note": notes[c["build_id"], c["chunk_id"]],
            "context_version": context_version,
            "prompt_version": provenance[c["build_id"], c["chunk_id"]].get(
                "method", contextual.PROMPT_VERSION
            ),
            "provenance": provenance[c["build_id"], c["chunk_id"]],
        }
        for c in packed
        if c["index_text"] != c["search_text"]
    ]
    payload = {
        "chunks.json": packed,
        "units.json": unit_rows,
        "vectors.json": vectors,
        "dates.json": dates,
        "notes.json": note_rows,
    }
    files = {}
    encoded = {}
    for name, value in payload.items():
        raw = json.dumps(value, ensure_ascii=False).encode()
        encoded[name] = raw
        files[name] = hashlib.sha256(raw).hexdigest()
    manifest = {
        "schema": "native-evidence-contextual-1",
        "target_db": target,
        "cutoff": date.today().isoformat(),
        "profile": config.profile,
        "dimensions": config.dimensions,
        "context_version": context_version,
        "prompt_version": contextual.PROMPT_VERSION,
        "publications": [
            [sid, entry["build_id"], entry["generation"]] for sid, entry in sorted(active.items())
        ],
        "source_allowlist": sorted(active),
        "excluded_source_ids": sorted(set(all_active) - set(active)),
        "files": files,
        "scope_note": (
            "Contextual Retrieval: note+chunk for lexical and dense indexing; "
            "raw-unit slices and evidence remain the unchanged projection."
        ),
    }
    manifest["release_id"] = release_id or f"contextual-{context_version}"
    if baseline:
        manifest["base_index_id"] = baseline.index_id
        manifest["deferred_sources"] = deferred
    raw = json.dumps(manifest, ensure_ascii=False).encode()
    out.parent.mkdir(parents=True, exist_ok=True)
    # Failed validation never leaves a half-written release at the requested path.
    with tempfile.TemporaryDirectory(prefix=".context-pack-", dir=out.parent) as temporary:
        staging = Path(temporary)
        for name, content in encoded.items():
            (staging / name).write_bytes(content)
        (staging / "manifest.json").write_bytes(raw)
        index = NativeIndex(staging / "manifest.json")
        refreshed = refresh(dsn, target, index)
        if len(refreshed.chunks) != len(index.chunks):
            raise contextual.ContextNoteError("contextual_pack_publication_changed")
        with _connect(dsn, target) as conn, conn.cursor() as cur:
            current = _active(cur)
            if any(
                sid not in current
                or (current[sid]["build_id"], current[sid]["generation"])
                != (entry["build_id"], entry["generation"])
                for sid, entry in active.items()
            ):
                raise contextual.ContextNoteError("contextual_pack_publication_changed")
        os.replace(staging, out)
    return {
        "out": str(out),
        "index_id": index.index_id,
        "sources": len(active),
        "chunks": len(packed),
        "unique_inputs": len(texts),
        "vectors_requested_this_run": embedded,
        "notes": len(note_rows),
        "fragments_without_note": len(packed) - len(note_rows),
        "live_chunks": len(refreshed.chunks),
        "dimensions": config.dimensions,
        "max_index_input_chars": max((len(v) for v in texts.values()), default=0),
        "context_version": context_version,
        "partial": bool(deferred),
        "deferred_sources": deferred,
        "web_activated": False,
    }


def read_note_coverage(index: NativeIndex) -> dict[str, object]:
    """只读核对：包内说明能否覆盖全部块、索引输入是否都以原文结尾。"""
    if not index.contextual:
        return {"contextual": False}
    return {
        "contextual": True,
        "chunks": len(index.chunks),
        "notes": len(index.notes),
        "complete": len(index.notes) == len(index.chunks),
        "context_version": index.manifest["context_version"],
        "prompt_version": index.manifest.get("prompt_version"),
        "max_index_input_chars": max((len(c["index_text"]) for c in index.chunks), default=0),
        "max_note_chars": max((len(n) for n in index.notes.values()), default=0),
    }
