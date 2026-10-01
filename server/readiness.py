"""Storage readiness gate (F19, the half left over after the health probe).

The first half of F19 taught ``/healthz`` to say "the database does not answer".
That is necessary but not sufficient: a process can reach a database whose
*schema* is not the one this build was written against. A row that is fine for
revision ``0002`` is not a row for revision ``0004``, and the failure mode is
quiet — the API starts, accepts runs, and dies much later on a missing column.

So this module answers a single question: *may this process accept work?*

  * the database answers (``store.check_db``);
  * the schema is the one this build expects — either stamped by Alembic at the
    project's head revision, or (the ``create_all`` dev path) unstamped with
    every expected table actually present;
  * the run-data root exists and is writable, so the process would not accept a
    run it cannot persist.

Read-only by design: it never migrates, never creates tables, never repairs.
Deciding *what to do* about an unready store belongs to the caller —
``enforce_startup_readiness`` (fail closed in production, warn in dev) and the
``/readyz`` probe (report it, keep answering liveness). This mirrors
``server.trajectory_status``: derive the answer from what is really there, so a
restart cannot leave a stale in-memory "I already checked" behind.
"""

from __future__ import annotations

import contextlib
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from server import store
from server.config import get_config
from server.store import Base

#: Alembic's bookkeeping table. Its absence is meaningful, not an error.
VERSION_TABLE = "alembic_version"

# Reason codes. Stable strings: operators grep them, tests assert them, and the
# HTTP body must not carry paths or credentials.
DB_UNAVAILABLE = "database_unavailable"
SCHEMA_MISSING = "schema_missing"
SCHEMA_BEHIND = "schema_behind"
SCHEMA_AHEAD = "schema_ahead"
SCHEMA_AMBIGUOUS = "schema_ambiguous"
SCHEMA_UNREADABLE = "schema_unreadable"
DATA_ROOT_UNWRITABLE = "data_root_unwritable"

_REVISION_RE = re.compile(
    r"^revision(?:\s*:\s*[^=]+)?\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE
)
_DOWN_REVISION_RE = re.compile(
    r"^down_revision(?:\s*:\s*[^=]+)?\s*=\s*(?:[\"']([^\"']+)[\"']|\(([^)]*)\)|None)",
    re.MULTILINE,
)


@dataclass(frozen=True)
class Readiness:
    """The gate's verdict. ``reasons`` is empty exactly when ``ok`` is true."""

    ok: bool
    reasons: tuple[str, ...] = ()
    detail: dict[str, str] = field(default_factory=dict)

    def as_body(self) -> dict[str, object]:
        if self.ok:
            return {"status": "ok"}
        return {"status": "not_ready", "reasons": list(self.reasons)}


def _versions_dir() -> Path:
    return Path(__file__).resolve().parent / "alembic" / "versions"


def migration_graph() -> dict[str, tuple[str, ...]]:
    """Map ``revision -> its down_revisions`` from the migration scripts.

    Parsed from source rather than imported: the migration files are named with a
    leading digit (``0004_control_records.py``), so they are not importable as
    ordinary modules without importlib gymnastics, and this keeps the gate free
    of side effects from executing migration code.
    """
    graph: dict[str, tuple[str, ...]] = {}
    for path in sorted(_versions_dir().glob("*.py")):
        source = path.read_text(encoding="utf-8")
        match = _REVISION_RE.search(source)
        if match is None:
            continue
        down: list[str] = []
        down_match = _DOWN_REVISION_RE.search(source)
        if down_match is not None:
            if down_match.group(1):
                down.append(down_match.group(1))
            elif down_match.group(2):
                down.extend(
                    part.strip().strip("\"'")
                    for part in down_match.group(2).split(",")
                    if part.strip()
                )
        graph[match.group(1)] = tuple(down)
    return graph


def expected_heads() -> tuple[str, ...]:
    """Revision ids nothing else descends from — normally exactly one."""
    graph = migration_graph()
    parents = {parent for downs in graph.values() for parent in downs}
    return tuple(sorted(rev for rev in graph if rev not in parents))


@dataclass(frozen=True)
class SchemaStamp:
    """What Alembic recorded about this database.

    ``stamped=False`` means Alembic has never touched it (the ``create_all`` dev
    path) — a state the table inventory decides, not this read. ``revisions`` is
    non-empty only for a stamped database and is a tuple because Alembic stores
    one row per head; more than one is a real state (an unmerged branch) and must
    not be guessed at.
    """

    stamped: bool
    revisions: tuple[str, ...] = ()

    @property
    def current(self) -> str | None:
        return self.revisions[0] if len(self.revisions) == 1 else None


async def read_schema_stamp() -> SchemaStamp:
    """Read ``alembic_version``; an absent table is "unstamped", not an error.

    ``store.check_db`` has already established that the database answers, so a
    driver error here means the bookkeeping table itself is missing.
    """
    try:
        async with store.get_engine().connect() as conn:
            result = await conn.execute(text(f"SELECT version_num FROM {VERSION_TABLE}"))
            return SchemaStamp(True, tuple(str(v) for v in result.scalars().all()))
    except DBAPIError:
        return SchemaStamp(False)


async def missing_tables() -> tuple[str, ...]:
    """Expected tables absent from the live database (empty means complete)."""
    expected = [table.name for table in Base.metadata.sorted_tables]

    def _probe(sync_conn: Connection) -> list[str]:
        inspector = inspect(sync_conn)
        return [name for name in expected if not inspector.has_table(name)]

    async with store.get_engine().connect() as conn:
        absent = await conn.run_sync(_probe)
    return tuple(absent)


def probe_data_root(path: Path | None = None) -> str | None:
    """Return a reason code when the run-data root cannot be written to.

    A real write is the only honest probe: ``os.access`` lies on Windows and on
    read-only mounts it is the mount that decides. The probe writes actual
    bytes — a 0-byte create still succeeds on a full tmpfs (data pages, not
    inodes, are what run out), so an empty payload would report a full disk as
    ready (found by the E3 disk-full injection, 2026-10-01). The probe file is
    removed again, and a failure is reported as a code — the root path itself
    never reaches the HTTP body.
    """
    root = Path(path) if path is not None else Path(get_config().runs_root)
    probe = root / f".readyz-probe-{uuid.uuid4().hex[:8]}"
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"readyz-probe")
    except OSError:
        return DATA_ROOT_UNWRITABLE
    finally:
        with contextlib.suppress(OSError):
            probe.unlink()
    return None


async def storage_readiness(*, data_root: Path | None = None) -> Readiness:
    """Aggregate verdict: database answers, schema matches, data root writable."""
    if not await store.check_db():
        return Readiness(ok=False, reasons=(DB_UNAVAILABLE,))

    heads = expected_heads()
    stamp = await read_schema_stamp()
    detail: dict[str, str] = {"expected_head": ",".join(heads)}

    if stamp.stamped:
        # Several heads stamped at once (an unmerged branch in the database) is
        # not something a process may pick a winner from.
        if len(stamp.revisions) > 1 or len(heads) != 1:
            detail["current_revision"] = ",".join(stamp.revisions)
            return Readiness(ok=False, reasons=(SCHEMA_AMBIGUOUS,), detail=detail)
        current = stamp.current
        head = heads[0]
        detail["current_revision"] = current or ""
        if current is None:
            # Stamped, but with no revision recorded: nothing to compare against.
            return Readiness(ok=False, reasons=(SCHEMA_MISSING,), detail=detail)
        if current != head:
            # Behind and ahead are both stop signals: an old schema lacks columns
            # this code writes, a newer one may have moved them (a revision id we
            # do not know at all was migrated by a different branch/version).
            behind = current in migration_graph() and _is_ancestor(current, head)
            return Readiness(
                ok=False,
                reasons=(SCHEMA_BEHIND if behind else SCHEMA_AHEAD,),
                detail=detail,
            )
    else:
        # Never stamped: the create_all path (local SQLite, tests). Legitimate
        # only when every table this build expects is actually there.
        absent = await missing_tables()
        if absent:
            detail["missing_tables"] = ",".join(absent)
            return Readiness(ok=False, reasons=(SCHEMA_MISSING,), detail=detail)

    root_reason = probe_data_root(data_root)
    if root_reason is not None:
        return Readiness(ok=False, reasons=(root_reason,), detail=detail)
    return Readiness(ok=True, detail=detail)


def _is_ancestor(candidate: str, descendant: str) -> bool:
    """True when ``candidate`` is reachable by walking ``descendant``'s parents."""
    graph = migration_graph()
    seen: set[str] = set()
    frontier = list(graph.get(descendant, ()))
    while frontier:
        revision = frontier.pop()
        if revision == candidate:
            return True
        if revision in seen:
            continue
        seen.add(revision)
        frontier.extend(graph.get(revision, ()))
    return False


class StorageNotReadyError(RuntimeError):
    """Raised at startup when the store cannot be served and dev mode is off."""


#: What the operator should actually do, per reason. Migrating is the answer to a
#: schema mismatch and the wrong answer to an unreachable database, so the two
#: must not share one sentence.
_REMEDIES = {
    DB_UNAVAILABLE: "check that the database is reachable before starting",
    DATA_ROOT_UNWRITABLE: "check that the run-data root is mounted and writable",
}
_SCHEMA_REMEDY = "run `alembic upgrade head` against this database before starting"


def _remedy(reasons: tuple[str, ...]) -> str:
    for reason in reasons:
        if reason in _REMEDIES:
            return _REMEDIES[reason]
    return _SCHEMA_REMEDY


def enforce_startup_readiness(
    readiness: Readiness, *, debug: bool, logger: logging.Logger | None = None
) -> None:
    """Fail closed on an unready store — unless this is explicitly dev mode.

    Swallowing this was how a stale schema reached production: the process
    started, took work, and failed much later with an opaque error. ``debug`` is
    the one escape hatch, and it is loud on purpose: local SQLite databases are
    created by ``create_all`` and legitimately unstamped.
    """
    log = logger or logging.getLogger("server.readiness")
    if readiness.ok:
        log.info("storage readiness: ok (%s)", readiness.detail)
        return
    message = (
        f"storage not ready: {', '.join(readiness.reasons)} ({readiness.detail}); "
        f"{_remedy(readiness.reasons)}"
    )
    if debug:
        log.warning("%s — continuing because SERVER_DEBUG is on", message)
        return
    raise StorageNotReadyError(message)
