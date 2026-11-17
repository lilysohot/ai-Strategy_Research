"""Durable request receipts. Callers hold a session lock across claim/request/finish."""

from __future__ import annotations

import time

import psycopg
from psycopg.types.json import Jsonb

DDL = """
CREATE TABLE IF NOT EXISTS corpus_retrieval.context_attempts (
    operation text NOT NULL,
    request_key text NOT NULL,
    attempt integer NOT NULL,
    state text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    elapsed_ms bigint,
    usage jsonb NOT NULL DEFAULT '{}',
    error_code text,
    transport_kind text,
    PRIMARY KEY(operation, request_key, attempt)
);
"""


def begin(cur: psycopg.Cursor, operation: str, key: str, attempt: int) -> float:
    """Commit a request-start record before issuing an external request."""
    cur.execute(
        "UPDATE corpus_retrieval.context_attempts SET state='uncertain',"
        "error_code='interrupted_before_receipt' WHERE operation=%s AND request_key=%s "
        "AND state='running'",
        (operation, key),
    )
    cur.execute(
        "INSERT INTO corpus_retrieval.context_attempts "
        "(operation,request_key,attempt,state) VALUES (%s,%s,%s,'running')",
        (operation, key, attempt),
    )
    return time.monotonic()


def finish(
    cur: psycopg.Cursor,
    operation: str,
    key: str,
    attempt: int,
    started: float,
    state: str,
    usage: dict,
    code: str | None = None,
    transport_kind: str | None = None,
) -> None:
    cur.execute(
        "UPDATE corpus_retrieval.context_attempts SET state=%s,usage=%s,error_code=%s,"
        "elapsed_ms=%s,transport_kind=%s,finished_at=now() "
        "WHERE operation=%s AND request_key=%s AND attempt=%s",
        (
            state,
            Jsonb(usage),
            code,
            round((time.monotonic() - started) * 1000),
            transport_kind,
            operation,
            key,
            attempt,
        ),
    )


def can_retry(
    state: str | None, tried: int, maximum: int, *, failed: bool, uncertain: bool
) -> bool:
    if tried >= maximum:
        return False
    return (
        state is None
        or (failed and state in ("failed", "rejected"))
        or (uncertain and state in ("uncertain", "running"))
    )
