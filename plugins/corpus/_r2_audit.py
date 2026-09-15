"""Explicit local audit journal for offline R2 adapters; never a corpus store.

SQLite transactions reserve before send. Unknown outcomes consume their slot and
halt the journal. This version cannot authorize any real model or network call.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from plugins.corpus._r2_plan import digest


@dataclass(frozen=True)
class OfflineGrant:
    plan_id: str
    max_calls: int = 0
    max_request_bytes: int = 65536
    max_response_bytes: int = 65536
    mode: str = "offline-only"

    def check(self) -> None:
        if (
            not self.plan_id
            or self.mode != "offline-only"
            or type(self.max_calls) is not int
            or not 0 <= self.max_calls <= 128
            or type(self.max_request_bytes) is not int
            or self.max_request_bytes <= 0
            or type(self.max_response_bytes) is not int
            or self.max_response_bytes <= 0
        ):
            raise ValueError("invalid_offline_grant")


@dataclass(frozen=True)
class Attempt:
    number: int
    key: str
    request: str
    request_sha: str
    status: str
    raw: str | None
    raw_sha: str | None
    adapter_mode: str | None
    error: str | None


@dataclass(frozen=True)
class AuditSnapshot:
    grant: OfflineGrant
    attempts: tuple[Attempt, ...]
    halted: str | None

    @property
    def sha256(self) -> str:
        return digest(asdict(self))

    def verify(self, expected_sha: str) -> None:
        self.grant.check()
        if self.sha256 != expected_sha or len(self.attempts) > self.grant.max_calls:
            raise ValueError("audit_binding")
        if len({a.key for a in self.attempts}) != len(self.attempts):
            raise ValueError("duplicate_attempt_key")
        for number, attempt in enumerate(self.attempts, 1):
            if attempt.number != number or digest(attempt.request) != attempt.request_sha:
                raise ValueError("audit_request_binding")
            if attempt.status not in ("reserved", "received", "failed", "unknown_outcome"):
                raise ValueError("audit_status")
            if attempt.status == "received":
                if (
                    attempt.raw is None
                    or digest(attempt.raw) != attempt.raw_sha
                    or attempt.adapter_mode not in ("fake", "replay")
                ):
                    raise ValueError("audit_raw_binding")
            elif attempt.raw is not None or attempt.raw_sha is not None:
                raise ValueError("audit_unreceived_raw")


class AuditJournal:
    """Explicitly created 0600 file. Retain this object/path across resume.

    External runner pins the grant/path and the snapshot hash. A new journal is
    not a continuation. Real budget authorization and provider adapters are absent.
    """

    def __init__(self, connection: sqlite3.Connection, grant: OfflineGrant) -> None:
        self.connection = connection
        self.grant = grant

    @classmethod
    def create(cls, path: Path, grant: OfflineGrant) -> AuditJournal:
        grant.check()
        if not path.is_absolute() or path.parent.resolve() != path.parent:
            raise ValueError("journal_path")
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(descriptor)
        connection = sqlite3.connect(path, timeout=5, isolation_level=None)
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute(
            "CREATE TABLE attempts (number INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, "
            "request TEXT NOT NULL, request_sha TEXT NOT NULL, status TEXT NOT NULL, "
            "raw TEXT, raw_sha TEXT, adapter_mode TEXT, error TEXT)"
        )
        connection.execute("INSERT INTO metadata VALUES ('grant', ?)", (json.dumps(asdict(grant)),))
        connection.execute("INSERT INTO metadata VALUES ('halted', 'null')")
        # Persist the directory entry as well as SQLite's transaction commits.
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return cls(connection, grant)

    @classmethod
    def open(cls, path: Path, grant: OfflineGrant) -> AuditJournal:
        grant.check()
        if path.is_symlink() or not path.is_file() or path.resolve() != path:
            raise ValueError("journal_path")
        if path.stat().st_mode & 0o077:
            raise ValueError("journal_permissions")
        connection = sqlite3.connect(
            path.as_uri() + "?mode=rw", uri=True, timeout=5, isolation_level=None
        )
        connection.execute("PRAGMA synchronous=FULL")
        row = connection.execute("SELECT value FROM metadata WHERE key='grant'").fetchone()
        if row is None or json.loads(row[0]) != asdict(grant):
            connection.close()
            raise ValueError("journal_grant_binding")
        return cls(connection, grant)

    def close(self) -> None:
        self.connection.close()

    def snapshot(self) -> AuditSnapshot:
        self.connection.execute("BEGIN")
        try:
            rows = self.connection.execute("SELECT * FROM attempts ORDER BY number").fetchall()
            halted = json.loads(
                self.connection.execute("SELECT value FROM metadata WHERE key='halted'").fetchone()[
                    0
                ]
            )
            snapshot = AuditSnapshot(self.grant, tuple(Attempt(*row) for row in rows), halted)
            snapshot.verify(snapshot.sha256)
            return snapshot
        finally:
            self.connection.execute("ROLLBACK")

    def reserve(self, key: str, request: str) -> int:
        if not key or len(request.encode()) > self.grant.max_request_bytes:
            raise ValueError("request_capacity")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            halted = json.loads(
                self.connection.execute("SELECT value FROM metadata WHERE key='halted'").fetchone()[
                    0
                ]
            )
            rows = self.connection.execute("SELECT key, status FROM attempts").fetchall()
            if halted or any(
                status in ("reserved", "unknown_outcome", "failed") for _, status in rows
            ):
                raise ValueError("journal_halted_or_pending")
            if any(old_key == key for old_key, _ in rows):
                raise ValueError("duplicate_obligation_attempt")
            if len(rows) >= self.grant.max_calls:
                raise ValueError("offline_call_capacity")
            number = len(rows) + 1
            self.connection.execute(
                "INSERT INTO attempts VALUES (?, ?, ?, ?, 'reserved', NULL, NULL, NULL, NULL)",
                (number, key, request, digest(request)),
            )
            self.connection.execute("COMMIT")
            return number
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def received(self, number: int, raw: str, adapter_mode: str) -> None:
        if adapter_mode not in ("fake", "replay"):
            raise ValueError("real_adapter_not_authorized")
        overflow = len(raw.encode()) > self.grant.max_response_bytes
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            cursor = self.connection.execute(
                "UPDATE attempts SET status='received', raw=?, raw_sha=?, adapter_mode=?, error=? "
                "WHERE number=? AND status='reserved'",
                (raw, digest(raw), adapter_mode, "response_capacity" if overflow else None, number),
            )
            if cursor.rowcount != 1:
                raise ValueError("attempt_not_reserved")
            if overflow:
                self.connection.execute(
                    "UPDATE metadata SET value=? WHERE key='halted'",
                    (json.dumps("response_capacity"),),
                )
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def failed(self, number: int, code: str) -> None:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            cursor = self.connection.execute(
                "UPDATE attempts SET status='failed', error=? WHERE number=? AND status='reserved'",
                (code, number),
            )
            if cursor.rowcount != 1:
                raise ValueError("attempt_not_reserved")
            self.connection.execute(
                "UPDATE metadata SET value=? WHERE key='halted'", (json.dumps(code),)
            )
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def recover_unknown(self) -> None:
        """Explicit operator recovery after workers stop; never retry unknown sends."""
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            cursor = self.connection.execute(
                "UPDATE attempts SET status='unknown_outcome', error='interrupted' WHERE status='reserved'"
            )
            if cursor.rowcount:
                self.connection.execute(
                    "UPDATE metadata SET value=? WHERE key='halted'",
                    (json.dumps("unknown_outcome"),),
                )
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
