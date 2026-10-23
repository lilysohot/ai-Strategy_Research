"""Manual bounded synchronization of native projection embeddings after publish."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from plugins.corpus.preparation import read_pg
from plugins.corpus.retrieval.embedding import (
    EmbeddingError,
    EmbeddingResult,
    VectorConfig,
    validate_vector,
)
from plugins.corpus.retrieval.native import NativeIndex, index_input
from plugins.corpus.retrieval.native_live import refresh


def sync(
    dsn: str,
    target: str,
    seed: NativeIndex,
    config: VectorConfig,
    embed: Callable[..., EmbeddingResult],
    *,
    max_requests: int = 0,
) -> dict[str, Any]:
    """Cache by exact projection hash; no publication changes or implicit retries."""
    if max_requests < 0 or target != config.target_db or config.profile != seed.manifest["profile"]:
        raise ValueError("native_sync_config_mismatch")
    index = refresh(dsn, target, seed)
    # 上下文包的向量输入是 index_text；原文投影只用于切片与取证。
    inputs = {c["input_hash"]: index_input(c) for c in index.chunks}
    requested = reused = imported = blocked = 0
    error = None
    with psycopg.connect(dsn, autocommit=True) as conn:
        read_pg._check_target(conn, target)
        for h, text in sorted(inputs.items()):
            key = config.profile, h
            if h in index.vectors:
                vector = validate_vector(index.vectors[h]["vector"], config.dimensions)
                row = conn.execute(
                    "INSERT INTO corpus_retrieval.embeddings(profile,input_hash,dimensions,status,embedding) "
                    "VALUES(%s,%s,%s,'ready',%s::vector) ON CONFLICT DO NOTHING RETURNING input_hash",
                    (*key, config.dimensions, json.dumps(vector)),
                ).fetchone()
                imported += row is not None
                reused += 1
                continue
            if requested == max_requests:
                continue
            # Committed claim before network I/O. A crash remains running and is
            # never automatically retried, avoiding duplicate provider billing.
            claimed = conn.execute(
                "INSERT INTO corpus_retrieval.embeddings(profile,input_hash,dimensions,status,attempts) "
                "VALUES(%s,%s,%s,'running',1) ON CONFLICT DO NOTHING RETURNING input_hash",
                (*key, config.dimensions),
            ).fetchone()
            if not claimed:
                blocked += 1
                continue
            requested += 1
            try:
                result = embed(text, "document")
                vector = validate_vector(result.vector, config.dimensions)
            except EmbeddingError as exc:
                error = exc.code
                conn.execute(
                    "UPDATE corpus_retrieval.embeddings SET status=%s,error_code=%s,updated_at=now() "
                    "WHERE profile=%s AND input_hash=%s",
                    ("uncertain" if exc.uncertain else "failed", exc.code, *key),
                )
                break
            conn.execute(
                "UPDATE corpus_retrieval.embeddings SET status='ready',embedding=%s::vector,usage=%s,"
                "updated_at=now() WHERE profile=%s AND input_hash=%s",
                (json.dumps(vector), Jsonb(result.usage), *key),
            )
    # Refresh again: a concurrent publish must not make the old input look ready.
    current = refresh(dsn, target, seed)
    return {
        "requests_this_run": requested,
        "reused_this_run": reused,
        "imported_cached_vectors": imported,
        "blocked_this_run": blocked,
        "error_code": error,
        "active_chunks": len(current.chunks),
        "pending_chunks": sum(c["input_hash"] not in current.vectors for c in current.chunks),
        "index_id": current.index_id,
    }
