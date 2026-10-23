"""Resumable side-index construction after publication; no publication mutations."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import psycopg
from psycopg.types.json import Jsonb

from plugins.corpus.preparation.search_pg import _check_target
from plugins.corpus.retrieval.context import (
    SourceMetadata,
    contextual_model_input,
    deterministic_context_prefix,
)
from plugins.corpus.retrieval.embedding import (
    EmbeddingError,
    EmbeddingResult,
    VectorConfig,
    text_hash,
    validate_vector,
)

if TYPE_CHECKING:
    from plugins.corpus.retrieval.embedding import Role

DDL = """
CREATE SCHEMA IF NOT EXISTS corpus_retrieval;
CREATE TABLE IF NOT EXISTS corpus_retrieval.spaces (
    profile text PRIMARY KEY,
    definition jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS corpus_retrieval.embeddings (
    profile text NOT NULL,
    input_hash text NOT NULL,
    dimensions integer NOT NULL,
    status text NOT NULL CHECK (status IN ('running', 'ready', 'failed', 'uncertain')),
    embedding vector,
    usage jsonb NOT NULL DEFAULT '{}',
    attempts integer NOT NULL DEFAULT 0,
    error_code text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (profile, input_hash),
    CHECK (embedding IS NULL OR vector_dims(embedding) = dimensions),
    CHECK ((status = 'ready') = (embedding IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS corpus_retrieval.source_metadata (
    source_id text PRIMARY KEY,
    report_title text NOT NULL,
    institution text,
    confirmed_publication_date date,
    field_evidence jsonb NOT NULL,
    reviewed_by text NOT NULL,
    reviewed_at timestamptz NOT NULL,
    metadata_hash text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (length(metadata_hash) = 64)
);
CREATE TABLE IF NOT EXISTS corpus_retrieval.chunk_vectors (
    profile text NOT NULL,
    source_id text NOT NULL,
    build_id text NOT NULL,
    chunk_id text NOT NULL,
    input_hash text NOT NULL,
    input_text text NOT NULL,
    context_prefix text NOT NULL DEFAULT '',
    section_path text[] NOT NULL DEFAULT '{}',
    metadata_hash text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (profile, build_id, chunk_id),
    FOREIGN KEY (profile, input_hash)
        REFERENCES corpus_retrieval.embeddings(profile, input_hash)
);
ALTER TABLE corpus_retrieval.chunk_vectors
    ADD COLUMN IF NOT EXISTS context_prefix text NOT NULL DEFAULT '';
ALTER TABLE corpus_retrieval.chunk_vectors
    ADD COLUMN IF NOT EXISTS section_path text[] NOT NULL DEFAULT '{}';
ALTER TABLE corpus_retrieval.chunk_vectors
    ADD COLUMN IF NOT EXISTS metadata_hash text NOT NULL DEFAULT '';
"""

ACTIVE_SQL = """
SELECT p.source_id, c.build_id, c.chunk_id, c.search_text, c.section_path,
       m.report_title, m.institution, m.confirmed_publication_date::text,
       m.field_evidence, m.reviewed_by, m.reviewed_at::text, m.metadata_hash
FROM corpus.corpus_publications p
JOIN corpus.corpus_chunks c ON c.build_id = p.active_build_id
LEFT JOIN corpus_retrieval.source_metadata m ON m.source_id = p.source_id
ORDER BY p.source_id, c.build_id, c.chunk_id
"""

ACTIVE_SQL_WITHOUT_METADATA = """
SELECT p.source_id, c.build_id, c.chunk_id, c.search_text, c.section_path,
       NULL::text, NULL::text, NULL::text, NULL::jsonb, NULL::text,
       NULL::text, NULL::text
FROM corpus.corpus_publications p
JOIN corpus.corpus_chunks c ON c.build_id = p.active_build_id
ORDER BY p.source_id, c.build_id, c.chunk_id
"""

# Current publication and exact input both participate in validity. A stale binding
# cannot make a changed chunk "ready", even if its identifiers were incorrectly reused.
COVERAGE_SQL = """
SELECT count(*), count(e.embedding)
FROM corpus.corpus_publications p
JOIN corpus.corpus_chunks c ON c.build_id = p.active_build_id
LEFT JOIN corpus_retrieval.source_metadata m ON m.source_id = p.source_id
LEFT JOIN corpus_retrieval.chunk_vectors v
  ON v.profile = %(profile)s AND v.source_id = p.source_id
  AND v.build_id = c.build_id AND v.chunk_id = c.chunk_id
  AND v.input_text = c.search_text
  AND v.section_path = c.section_path
  AND (
    (%(input_variant)s = 'published-search-text-v1' AND v.metadata_hash = '')
    OR
    (%(input_variant)s = 'reviewed-context-prefix-v1'
     AND v.metadata_hash = m.metadata_hash)
  )
LEFT JOIN corpus_retrieval.embeddings e
  ON e.profile = v.profile AND e.input_hash = v.input_hash
  AND e.status = 'ready' AND e.dimensions = %(dimensions)s
"""


@dataclass(frozen=True)
class PublishedChunk:
    source_id: str
    build_id: str
    chunk_id: str
    text: str
    section_path: tuple[str, ...]
    metadata: SourceMetadata | None
    metadata_hash: str

    @classmethod
    def from_row(cls, row: tuple) -> PublishedChunk:
        metadata = None
        if row[5] is not None:
            evidence = row[8] if isinstance(row[8], dict) else {}
            metadata = SourceMetadata(
                source_id=str(row[0]),
                report_title=str(row[5]),
                institution=str(row[6]) if row[6] is not None else None,
                confirmed_publication_date=str(row[7]) if row[7] is not None else None,
                field_evidence={
                    str(key): tuple(str(ref) for ref in refs) for key, refs in evidence.items()
                },
                reviewed_by=str(row[9]),
                reviewed_at=str(row[10]),
            )
        return cls(
            source_id=str(row[0]),
            build_id=str(row[1]),
            chunk_id=str(row[2]),
            text=str(row[3]),
            section_path=tuple(str(part) for part in (row[4] or ())),
            metadata=metadata,
            metadata_hash=str(row[11] or ""),
        )

    def context_prefix(self, config: VectorConfig) -> str:
        if config.input_variant == "published-search-text-v1":
            return ""
        if self.metadata is None or self.metadata.metadata_hash != self.metadata_hash:
            raise EmbeddingError("source_metadata_missing_or_stale")
        return deterministic_context_prefix(self.metadata, self.section_path)

    def model_input(self, config: VectorConfig) -> str:
        prefix = self.context_prefix(config)
        return contextual_model_input(prefix, self.text) if prefix else self.text

    def input_hash(self, config: VectorConfig) -> str:
        return text_hash(self.model_input(config))


def _metadata_table_exists(cur: psycopg.Cursor) -> bool:
    cur.execute("SELECT to_regclass('corpus_retrieval.source_metadata')")
    row = cur.fetchone()
    return row is not None and row[0] is not None


def _active_chunks(cur: psycopg.Cursor) -> list[PublishedChunk]:
    cur.execute(ACTIVE_SQL if _metadata_table_exists(cur) else ACTIVE_SQL_WITHOUT_METADATA)
    return [PublishedChunk.from_row(row) for row in cur.fetchall()]


def ready_counts(cur: psycopg.Cursor, config: VectorConfig) -> tuple[int, int]:
    cur.execute(
        COVERAGE_SQL,
        {
            "profile": config.profile,
            "dimensions": config.dimensions,
            "input_variant": config.input_variant,
        },
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0]), int(row[1])


class VectorIndex:
    """Small-corpus exact index with durable request state and single-writer locking."""

    def __init__(self, dsn: str, config: VectorConfig) -> None:
        self.dsn = dsn
        self.config = config

    def connect(self) -> psycopg.Connection:
        conn = psycopg.connect(self.dsn, autocommit=True, connect_timeout=10)
        try:
            _check_target(conn, self.config.target_db)
        except Exception:
            conn.close()
            raise
        return conn

    def initialize(self) -> None:
        """Explicit command only; search never creates schemas or extensions."""
        with self.connect() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(DDL)
            # Preserve readiness of the original profile after adding structural
            # validity columns to an already-populated pilot database.
            cur.execute(
                """UPDATE corpus_retrieval.chunk_vectors v
                SET section_path=c.section_path
                FROM corpus.corpus_chunks c
                WHERE v.build_id=c.build_id AND v.chunk_id=c.chunk_id
                  AND v.input_text=c.search_text AND v.context_prefix=''"""
            )
            cur.execute(
                "INSERT INTO corpus_retrieval.spaces (profile, definition) VALUES (%s, %s) "
                "ON CONFLICT (profile) DO NOTHING",
                (self.config.profile, Jsonb(self.config.definition())),
            )

    def load_metadata(self, entries: tuple[SourceMetadata, ...]) -> dict[str, object]:
        """Replace the complete reviewed sidecar set for active pilot sources."""
        self.initialize()
        with self.connect() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                "SELECT source_id FROM corpus.corpus_publications "
                "WHERE active_build_id IS NOT NULL ORDER BY source_id"
            )
            active = {str(row[0]) for row in cur.fetchall()}
            supplied = {entry.source_id for entry in entries}
            if active != supplied:
                raise EmbeddingError("source_metadata_manifest_not_complete")
            cur.execute(
                """SELECT p.source_id,
                          a.metadata_snapshot->'report_publication'->>'value'
                FROM corpus.corpus_publications p
                JOIN corpus.corpus_builds b ON b.build_id=p.active_build_id
                JOIN corpus.corpus_admissions a ON a.decision_id=b.decision_id"""
            )
            admitted_dates = {str(source): value for source, value in cur.fetchall()}
            for entry in entries:
                admitted = admitted_dates.get(entry.source_id)
                if (
                    admitted
                    and entry.confirmed_publication_date
                    and str(admitted) != entry.confirmed_publication_date
                ):
                    raise EmbeddingError("source_metadata_date_conflicts_with_admission")
                cur.execute(
                    """INSERT INTO corpus_retrieval.source_metadata
                    (source_id, report_title, institution, confirmed_publication_date,
                     field_evidence, reviewed_by, reviewed_at, metadata_hash)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source_id) DO UPDATE SET
                      report_title=EXCLUDED.report_title,
                      institution=EXCLUDED.institution,
                      confirmed_publication_date=EXCLUDED.confirmed_publication_date,
                      field_evidence=EXCLUDED.field_evidence,
                      reviewed_by=EXCLUDED.reviewed_by,
                      reviewed_at=EXCLUDED.reviewed_at,
                      metadata_hash=EXCLUDED.metadata_hash,
                      updated_at=now()""",
                    (
                        entry.source_id,
                        entry.report_title,
                        entry.institution,
                        entry.confirmed_publication_date,
                        Jsonb(entry.field_evidence),
                        entry.reviewed_by,
                        datetime.fromisoformat(entry.reviewed_at.replace("Z", "+00:00")),
                        entry.metadata_hash,
                    ),
                )
        return self.status()

    def status(self) -> dict[str, object]:
        """Readiness and durable usage, with no secret or document text in the result."""
        with self.connect() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            chunks = _active_chunks(cur)
            cur.execute("SELECT to_regclass('corpus_retrieval.embeddings')")
            schema_row = cur.fetchone()
            exists = schema_row is not None and schema_row[0] is not None
            retrieval_schema_ready = exists and _metadata_table_exists(cur)
            counts = ready_counts(cur, self.config) if retrieval_schema_ready else (len(chunks), 0)
            states: dict[str, int] = {}
            tokens = attempts = 0
            cached: set[str] = set()
            if exists:
                cur.execute(
                    "SELECT input_hash, status, attempts, usage "
                    "FROM corpus_retrieval.embeddings WHERE profile = %s",
                    (self.config.profile,),
                )
                for input_hash, state, tried, usage in cur.fetchall():
                    states[state] = states.get(state, 0) + 1
                    attempts += tried
                    tokens += int(usage.get("total_tokens", 0))
                    if state == "ready":
                        cached.add(input_hash)
        valid_inputs: list[tuple[PublishedChunk, str]] = []
        missing_metadata = 0
        for chunk in chunks:
            try:
                valid_inputs.append((chunk, chunk.model_input(self.config)))
            except EmbeddingError:
                missing_metadata += 1
        unique = {text_hash(model_input) for _, model_input in valid_inputs}
        metadata_by_source = {
            chunk.source_id: chunk.metadata for chunk in chunks if chunk.metadata is not None
        }
        return {
            "target_db": self.config.target_db,
            "profile": self.config.profile,
            "model": self.config.model,
            "dimensions": self.config.dimensions,
            "input_variant": self.config.input_variant,
            "api_key_configured": bool(self.config.api_key),
            "schema_initialized": exists,
            "retrieval_schema_ready": retrieval_schema_ready,
            "sources": len({c.source_id for c in chunks}),
            "active_chunks": counts[0],
            "ready_chunks": counts[1],
            "unique_inputs": len(unique),
            "uncached_inputs": len(unique - cached),
            "max_input_chars": max((len(value) for _, value in valid_inputs), default=0),
            "invalid_inputs": sum(
                not value.strip() or len(value) > self.config.max_chars for _, value in valid_inputs
            )
            + missing_metadata,
            "metadata_sources": len(metadata_by_source),
            "metadata_titles": sum(bool(item.report_title) for item in metadata_by_source.values()),
            "metadata_institutions": sum(
                bool(item.institution) for item in metadata_by_source.values()
            ),
            "metadata_confirmed_dates": sum(
                bool(item.confirmed_publication_date) for item in metadata_by_source.values()
            ),
            "metadata_missing_chunks": missing_metadata,
            "cache_states": states,
            "attempts": attempts,
            "reported_total_tokens": tokens,
            "snapshot": text_hash(
                json.dumps(
                    [
                        (
                            chunk.source_id,
                            chunk.build_id,
                            chunk.chunk_id,
                            text_hash(model_input),
                        )
                        for chunk, model_input in valid_inputs
                    ]
                )
            ),
        }

    def build(
        self,
        embed: Callable[[str, Role], EmbeddingResult],
        *,
        max_requests: int = 10,
        retry_failed: bool = False,
        retry_uncertain: bool = False,
    ) -> dict[str, object]:
        """Resume/rebind cached inputs. Unknown outcomes require an explicit retry flag.

        No network call runs inside a transaction. Session advisory locking prevents
        two builders from charging the same profile/input simultaneously. A crash
        leaves `running`, treated exactly like `uncertain` on the next invocation.
        """
        requested = reused = bound = blocked = 0
        error: str | None = None
        cfg = self.config
        if max_requests < 0:
            raise ValueError("max_requests must be nonnegative")
        if cfg.input_variant == "contextual-note-v1":
            # 该口径的输入是「说明 + 片段」，只能由 contextual_pg 建包，不在这里拼。
            raise EmbeddingError("contextual_variant_native_only")
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
                ("corpus-vector:" + cfg.profile,),
            )
            lock_row = cur.fetchone()
            if lock_row is None or not lock_row[0]:
                raise EmbeddingError("index_writer_already_running")
            chunks = _active_chunks(cur)
            for chunk in chunks:
                try:
                    model_input = chunk.model_input(cfg)
                    context_prefix = chunk.context_prefix(cfg)
                except EmbeddingError as exc:
                    error = exc.code
                    blocked += 1
                    continue
                if not model_input.strip() or len(model_input) > cfg.max_chars:
                    blocked += 1
                    continue
                input_hash = text_hash(model_input)
                key = (cfg.profile, input_hash)
                cur.execute(
                    "SELECT status FROM corpus_retrieval.embeddings "
                    "WHERE profile = %s AND input_hash = %s",
                    key,
                )
                row = cur.fetchone()
                state = row[0] if row else None
                if state != "ready":
                    if state in ("running", "uncertain") and not retry_uncertain:
                        blocked += 1
                        continue
                    if state == "failed" and not retry_failed:
                        blocked += 1
                        continue
                    if requested >= max_requests:
                        continue
                    cur.execute(
                        """INSERT INTO corpus_retrieval.embeddings
                        (profile, input_hash, dimensions, status, attempts)
                        VALUES (%s, %s, %s, 'running', 1)
                        ON CONFLICT (profile, input_hash) DO UPDATE SET
                          status='running', embedding=NULL, error_code=NULL,
                          attempts=corpus_retrieval.embeddings.attempts+1, updated_at=now()""",
                        (*key, cfg.dimensions),
                    )
                    requested += 1
                    try:
                        result = embed(model_input, "document")
                        vector = validate_vector(result.vector, cfg.dimensions)
                    except EmbeddingError as exc:
                        error = exc.code
                        cur.execute(
                            """UPDATE corpus_retrieval.embeddings
                            SET status=%s, error_code=%s, updated_at=now()
                            WHERE profile=%s AND input_hash=%s""",
                            ("uncertain" if exc.uncertain else "failed", exc.code, *key),
                        )
                        break  # No blind retry of auth/length/rate-limit/unknown errors.
                    cur.execute(
                        """UPDATE corpus_retrieval.embeddings
                        SET status='ready', embedding=%s::vector, usage=%s,
                            error_code=NULL, updated_at=now()
                        WHERE profile=%s AND input_hash=%s""",
                        (json.dumps(vector), Jsonb(result.usage), *key),
                    )
                else:
                    reused += 1
                # Publication may have moved during the API call. Bind only if this
                # exact text is still active; cached work remains reusable later.
                cur.execute(
                    """INSERT INTO corpus_retrieval.chunk_vectors
                    (profile, source_id, build_id, chunk_id, input_hash, input_text,
                     context_prefix, section_path, metadata_hash)
                    SELECT %s, p.source_id, c.build_id, c.chunk_id, %s, c.search_text,
                           %s, c.section_path, %s
                    FROM corpus.corpus_publications p
                    JOIN corpus.corpus_chunks c ON c.build_id=p.active_build_id
                    WHERE p.source_id=%s AND c.build_id=%s AND c.chunk_id=%s
                      AND c.search_text=%s AND c.section_path=%s
                      AND (
                        %s='published-search-text-v1'
                        OR EXISTS (
                          SELECT 1 FROM corpus_retrieval.source_metadata m
                          WHERE m.source_id=p.source_id AND m.metadata_hash=%s
                        )
                      )
                    ON CONFLICT (profile, build_id, chunk_id) DO UPDATE SET
                      input_hash=EXCLUDED.input_hash,
                      input_text=EXCLUDED.input_text,
                      context_prefix=EXCLUDED.context_prefix,
                      section_path=EXCLUDED.section_path,
                      metadata_hash=EXCLUDED.metadata_hash""",
                    (
                        cfg.profile,
                        input_hash,
                        context_prefix,
                        chunk.metadata_hash
                        if cfg.input_variant == "reviewed-context-prefix-v1"
                        else "",
                        chunk.source_id,
                        chunk.build_id,
                        chunk.chunk_id,
                        chunk.text,
                        list(chunk.section_path),
                        cfg.input_variant,
                        chunk.metadata_hash,
                    ),
                )
                bound += cur.rowcount
        return {
            "requests_this_run": requested,
            "reused_this_run": reused,
            "bound_this_run": bound,
            "blocked_this_run": blocked,
            "error_code": error,
            **self.status(),
        }
