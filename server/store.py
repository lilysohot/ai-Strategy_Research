"""Database layer: SQLAlchemy 2.0 async engine + declarative models.

Holds the business schema (users / user_llm_configs / sessions / runs / turns /
artifacts / audit_log) from tech-stack.md §6.1. The trajectory files live on disk
under each run's ``run_dir`` and are NOT stored here (§6.2).

At M1 we only need the engine + a health check; the full CRUD lands in M2. Models
are defined now so Alembic can autogenerate the initial migration.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    select,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from server.config import get_config
from server.crypto import decrypt_api_key, encrypt_api_key, mask_api_key


class Base(DeclarativeBase):
    pass


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserLLMConfig(Base):
    __tablename__ = "user_llm_configs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    base_url: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    api_key_cipher: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    params_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verify_ok: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = ()


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    pipeline_id: Mapped[str] = mapped_column(String, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    final_answer: Mapped[str | None] = mapped_column(Text)
    stopped_by: Mapped[str | None] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(Text)
    llm_config_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user_llm_configs.id"))
    llm_snapshot_json: Mapped[dict | None] = mapped_column(JSON)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    # T2.11: cache READ (hit) and cache WRITE (creation) are metered separately
    # because they bill at different rates — collapsing them under-attributes
    # write spend on Anthropic. reasoning_tokens is billed as completion but
    # worth surfacing on its own for o-series / thinking models.
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer)
    #: Number of LLM turns that reported usage (not turns taken — an unmetered
    #: turn is not a billable one, see server.usage.aggregate_usage).
    llm_calls: Mapped[int | None] = mapped_column(Integer)
    #: Full aggregate (incl. model/provider labels) as metered, so a later
    #: re-scan can be diffed without re-reading the trajectory.
    usage_json: Mapped[dict | None] = mapped_column(JSON)
    run_dir: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Turn(Base):
    __tablename__ = "turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # F16: a session's turns are ordered by ``seq`` and read back as a
    # conversation, so two rows sharing one ``seq`` silently corrupt the
    # transcript. A UNIQUE index (rather than a table constraint) is what both
    # SQLite and PostgreSQL can add to an existing table, so the same object is
    # declared here and created by migration 0003 — see ``append_turn`` for how
    # a lost race is detected and retried.
    __table_args__ = (
        Index("uq_turns_session_seq", "session_id", "seq", unique=True),
    )


class Artifact(Base):
    __tablename__ = "artifacts"

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    rel_path: Mapped[str] = mapped_column(String, primary_key=True)
    size: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String, nullable=False)
    detail_json: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ControlRecord(Base):
    """A persisted user control action for one run (F21).

    Two kinds share one table because they share the same skeleton — who acted,
    on which run, when, and whether the action actually took effect — and differ
    only in the request payload and the decision columns:

    * ``kind="steer"`` — a mid-run direction (``steer_queued`` used to be an
      in-memory event only, so "queued but never injected" was indistinguishable
      from "adopted").
    * ``kind="approval"`` — a tool-call approval request/decision (the gate lives
      in the worker's memory, so a page refresh had no way to reconstruct what
      was still pending).

    ``request_json`` holds the **redacted** request (same ``redact_deep`` boundary
    as every SSE egress). The user's own raw steer text is deliberately NOT kept
    here: it reaches the transcript through ``turns`` when the steer is adopted,
    so this table adds no second raw-content store.
    """

    __tablename__ = "control_records"
    __table_args__ = (
        # An approval decision is keyed by the worker's ``approval_id``: a
        # retried POST must update that one row instead of duplicating the
        # decision (F15's "a terminal frame can arrive twice" lesson). Steers
        # carry no client-supplied id, so their NULLs stay distinct.
        UniqueConstraint("kind", "external_id", name="uq_control_records_kind_external"),
        Index("ix_control_records_run_id", "run_id"),
        Index("ix_control_records_session_status", "session_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"), nullable=False)
    # Derived server-side from the run row (never from a request body): the
    # history renderer reads adopted steers per session, so this denormalisation
    # saves a join on the run-spawn hot path.
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    # The actor, bound from the JWT — never accepted from the client (PR-BIZ-04).
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    external_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, nullable=False)
    request_json: Mapped[dict | None] = mapped_column(JSON)
    decision: Mapped[str | None] = mapped_column(String)
    replacement_command: Mapped[str | None] = mapped_column(Text)
    adopted_turn_seq: Mapped[int | None] = mapped_column(Integer)
    detail_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


_engine: AsyncEngine | None = None
_SessionMaker: async_sessionmaker[AsyncSession] | None = None


def _apply_sqlite_pragmas(engine: AsyncEngine) -> None:
    """Make SQLite tolerate concurrent writers (dev/test and single-node runs).

    The default ``database_url`` is SQLite, which allows exactly one writer at a
    time and, without a busy timeout, answers a concurrent write with an immediate
    ``database is locked`` error. The server has several independent writers: the
    orchestrator persists turns/runs/artifacts when a worker exits, routes write
    audit rows, and startup runs DDL. Two of those overlapping is normal, so:

    * ``journal_mode=WAL`` — readers no longer block the writer (and vice versa);
    * ``busy_timeout``     — a writer *waits* for the lock instead of failing.

    Both are no-ops on PostgreSQL (production), where the engine is already
    multi-writer. ``journal_mode`` persists in the database file; ``busy_timeout``
    is per-connection, so it is re-applied on every new connection.
    """
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_conn: object, _record: object) -> None:
        cursor = dbapi_conn.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=10000")
            # F16: SQLite ignores declared FOREIGN KEYs unless this is set PER
            # CONNECTION. The schema has always declared them (turns.session_id →
            # sessions.id, runs.session_id → sessions.id, ...), so an isolated
            # test database happily accepted rows whose parent did not exist —
            # the constraint was documentation, not enforcement.
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        cfg = get_config()
        _engine = create_async_engine(cfg.database_url, future=True)
        _apply_sqlite_pragmas(_engine)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _SessionMaker
    if _SessionMaker is None:
        _SessionMaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _SessionMaker


async def session_scope() -> AsyncSession:
    """Yield an ``AsyncSession``; caller ``async with`` it."""
    return get_sessionmaker()()


async def init_db() -> None:
    """Create tables if they don't exist (dev / SQLite fallback).

    Production uses Alembic migrations (``server/alembic``); this is the zero-
    config path for local dev and tests.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def check_db() -> bool:
    """Connectivity probe: does the database answer at all (F19).

    Deliberately ``SELECT 1`` rather than a table read. Whether the *schema* is
    the one this build expects is a different question with a different remedy
    ("migrate" vs "retry"), and it is answered by ``server.readiness``; a table
    read here conflated an empty database with an unreachable one.
    """
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def reset_engine() -> None:
    """Dispose the cached engine and sessionmaker.

    Needed when the database URL changes at runtime — tests point at a throwaway
    SQLite file, and a long-lived process may be re-pointed at another database.
    Without this the module-level singletons keep serving the first URL.
    """
    global _engine, _SessionMaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _SessionMaker = None


# ── User helpers (T2.2) ────────────────────────────────────────


class UsernameTaken(Exception):
    """Raised when a registration collides with an existing username."""


async def create_user(*, username: str, password_hash: str) -> User:
    """Insert a new user, raising :class:`UsernameTaken` on collision.

    Uniqueness is enforced by the database rather than by a pre-check: two
    concurrent registrations can both pass a SELECT and then race on the INSERT,
    so the unique constraint is the only correct arbiter.
    """
    from sqlalchemy.exc import IntegrityError

    user = User(username=username, password_hash=password_hash)
    async with get_sessionmaker()() as session:
        session.add(user)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise UsernameTaken(username) from exc
        await session.refresh(user)
    return user


async def get_user_by_username(username: str) -> User | None:
    async with get_sessionmaker()() as session:
        result = await session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()


async def get_user_by_id(user_id: uuid.UUID) -> User | None:
    async with get_sessionmaker()() as session:
        return await session.get(User, user_id)


async def update_password_hash(user_id: uuid.UUID, password_hash: str) -> None:
    async with get_sessionmaker()() as session:
        user = await session.get(User, user_id)
        if user is not None:
            user.password_hash = password_hash
            await session.commit()


async def write_audit_log(
    *,
    action: str,
    user_id: uuid.UUID | None = None,
    detail: dict | None = None,
    ip: str | None = None,
) -> None:
    """Append an audit record.

    Covers the sensitive operations the requirements call out: register, login,
    login failure, logout, password change, and (later) LLM-config changes and
    key rotation.
    """
    entry = AuditLog(user_id=user_id, action=action, detail_json=detail, ip=ip)
    async with get_sessionmaker()() as session:
        session.add(entry)
        await session.commit()


# ── User LLM config helpers (T2.3) ──────────────────────────────


class ConfigNotFoundError(Exception):
    """Raised when a config id does not exist or belongs to another user."""


class OnlyOneDefaultAllowed(Exception):
    """Raised when an operation would leave the user with no default config."""


def _serialize_config(cfg: UserLLMConfig) -> dict:
    """Public view of a config: api_key is ALWAYS masked, never plaintext.

    The ciphertext column is excluded entirely; only ``masked_api_key`` is shown.
    """
    return {
        "id": str(cfg.id),
        "name": cfg.name,
        "base_url": cfg.base_url,
        "model": cfg.model,
        "masked_api_key": mask_api_key(_decrypt_for_display(cfg.api_key_cipher)),
        "params": cfg.params_json or {},
        "is_default": cfg.is_default,
        "last_verified_at": cfg.last_verified_at.isoformat() if cfg.last_verified_at else None,
        "last_verify_ok": cfg.last_verify_ok,
        "created_at": cfg.created_at.isoformat() if cfg.created_at else None,
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
    }


def _decrypt_for_display(ciphertext: bytes) -> str:
    """Best-effort decrypt for masking; returns a placeholder on failure.

    A corrupt or undecryptable blob must never crash a list/read, and must never
    leak into the response — we surface a fixed sentinel instead.
    """
    try:
        return decrypt_api_key(ciphertext)
    except Exception:
        return ""


async def create_llm_config(
    *,
    user_id: uuid.UUID,
    name: str,
    base_url: str,
    model: str,
    api_key: str,
    params: dict | None = None,
    is_default: bool = False,
) -> dict:
    """Insert a new LLM config; the api_key is Fernet-encrypted at rest.

    Setting ``is_default=True`` demotes any existing default for that user first,
    so the user has at most one default at all times.
    """
    cipher = encrypt_api_key(api_key)
    async with get_sessionmaker()() as session:
        if is_default:
            await session.execute(
                update(UserLLMConfig)
                .where(UserLLMConfig.user_id == user_id)
                .values(is_default=False)
            )
        cfg = UserLLMConfig(
            user_id=user_id,
            name=name,
            base_url=base_url,
            model=model,
            api_key_cipher=cipher,
            params_json=params,
            is_default=is_default,
        )
        session.add(cfg)
        await session.commit()
        await session.refresh(cfg)
        return _serialize_config(cfg)


async def list_llm_configs(*, user_id: uuid.UUID) -> list[dict]:
    """Return all configs for a user, masked, newest first."""
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(UserLLMConfig)
            .where(UserLLMConfig.user_id == user_id)
            .order_by(UserLLMConfig.created_at.desc())
        )
        return [_serialize_config(c) for c in result.scalars().all()]


async def get_llm_config(*, user_id: uuid.UUID, config_id: uuid.UUID) -> dict:
    """Return one config (masked) or raise :class:`ConfigNotFoundError`."""
    cfg = await _get_owned_config(user_id, config_id)
    return _serialize_config(cfg)


async def _get_owned_config(user_id: uuid.UUID, config_id: uuid.UUID) -> UserLLMConfig:
    """Load a config row, enforcing user ownership (anti-IDOR)."""
    async with get_sessionmaker()() as session:
        cfg = await session.get(UserLLMConfig, config_id)
        if cfg is None or cfg.user_id != user_id:
            raise ConfigNotFoundError(str(config_id))
        # Re-attach to this session for callers that want to mutate + commit.
        return cfg


async def update_llm_config(
    *,
    user_id: uuid.UUID,
    config_id: uuid.UUID,
    name: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    params: dict | None = None,
    is_default: bool | None = None,
) -> dict:
    """Patch an existing config; ``None`` leaves a field unchanged.

    Changing ``is_default=True`` demotes every other config for the user.
    """
    async with get_sessionmaker()() as session:
        cfg = await session.get(UserLLMConfig, config_id)
        if cfg is None or cfg.user_id != user_id:
            raise ConfigNotFoundError(str(config_id))

        if name is not None:
            cfg.name = name
        if base_url is not None:
            cfg.base_url = base_url
        if model is not None:
            cfg.model = model
        if params is not None:
            cfg.params_json = params
        if api_key is not None:
            cfg.api_key_cipher = encrypt_api_key(api_key)
        if is_default is True:
            await session.execute(
                update(UserLLMConfig)
                .where(UserLLMConfig.user_id == user_id)
                .values(is_default=False)
            )
            cfg.is_default = True

        await session.commit()
        await session.refresh(cfg)
        return _serialize_config(cfg)


async def set_default_llm_config(*, user_id: uuid.UUID, config_id: uuid.UUID) -> dict:
    """Promote ``config_id`` to the user's single default config."""
    async with get_sessionmaker()() as session:
        cfg = await session.get(UserLLMConfig, config_id)
        if cfg is None or cfg.user_id != user_id:
            raise ConfigNotFoundError(str(config_id))
        await session.execute(
            update(UserLLMConfig)
            .where(UserLLMConfig.user_id == user_id)
            .values(is_default=False)
        )
        cfg.is_default = True
        await session.commit()
        await session.refresh(cfg)
        return _serialize_config(cfg)


async def delete_llm_config(*, user_id: uuid.UUID, config_id: uuid.UUID) -> None:
    """Delete a config, refusing to orphan the user's only default.

    If the row being deleted is the user's default and they have others, the most
    recently created remaining config is promoted. If it is the only config, the
    delete is rejected so the user always has at least one (the system default
    fallback is for runs, not for a user's own list).
    """
    async with get_sessionmaker()() as session:
        cfg = await session.get(UserLLMConfig, config_id)
        if cfg is None or cfg.user_id != user_id:
            raise ConfigNotFoundError(str(config_id))

        remaining = (
            (
                await session.execute(
                    select(UserLLMConfig)
                    .where(
                        UserLLMConfig.user_id == user_id,
                        UserLLMConfig.id != config_id,
                    )
                    .order_by(UserLLMConfig.created_at.desc())
                )
            )
            .scalars()
            .all()
        )

        if cfg.is_default and not remaining:
            raise OnlyOneDefaultAllowed("cannot delete the user's only LLM config")

        await session.delete(cfg)
        if cfg.is_default and remaining:
            remaining[0].is_default = True
        await session.commit()


async def get_default_llm_config(*, user_id: uuid.UUID) -> UserLLMConfig | None:
    """Return the user's default config row, or None (T2.5 uses this for inject)."""
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(UserLLMConfig).where(
                UserLLMConfig.user_id == user_id,
                UserLLMConfig.is_default == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()


async def get_decrypted_api_key(*, user_id: uuid.UUID, config_id: uuid.UUID) -> str:
    """Decrypt a stored api_key for the injection chain (T2.5).

    Ownership is enforced; the caller must treat the result as a secret and never
    log or return it.
    """
    cfg = await _get_owned_config(user_id, config_id)
    return decrypt_api_key(cfg.api_key_cipher)


async def record_verify_result(
    *,
    user_id: uuid.UUID,
    config_id: uuid.UUID,
    ok: bool,
    error_summary: str | None = None,
) -> None:
    """Persist a connectivity-check outcome (T2.4 ``POST /{id}/test``).

    Updates ``last_verified_at`` / ``last_verify_ok`` only — never the api_key or
    any other field, so a failed probe cannot clobber stored credentials.
    """
    async with get_sessionmaker()() as session:
        cfg = await session.get(UserLLMConfig, config_id)
        if cfg is None or cfg.user_id != user_id:
            raise ConfigNotFoundError(str(config_id))
        cfg.last_verified_at = datetime.now(UTC)
        cfg.last_verify_ok = ok
        # Stash the error summary without leaking the key: we only keep a short,
        # caller-supplied message (never the raw response or credentials).
        cfg.params_json = {
            **(cfg.params_json or {}),
            "_last_verify_error": (error_summary or "")[:500] if not ok else "",
        }
        await session.commit()


async def resolve_user_llm_env(*, user_id: uuid.UUID) -> dict | None:
    """Resolve a user's default LLM config into worker env vars, or None.

    Returns ``{"OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"}`` only when
    all three are present (T2.5: "all non-empty or all absent"). A partial config
    (e.g. a model with no key) yields ``None`` so the caller falls back to the
    server's own ``.env`` instead of silently injecting a half-set that would
    route a user key to the wrong endpoint. The api_key is decrypted in-process
    and handed straight to the environment — it is never logged or returned in any
    serialized form.
    """
    default = await get_default_llm_config(user_id=user_id)
    if default is None:
        return None
    try:
        key = await get_decrypted_api_key(user_id=user_id, config_id=default.id)
    except Exception:
        return None
    if not (default.model and default.base_url and key):
        return None
    return {
        "OPENAI_API_KEY": key,
        "OPENAI_BASE_URL": default.base_url,
        "OPENAI_MODEL": default.model,
    }


async def build_llm_snapshot(*, user_id: uuid.UUID | None) -> dict:
    """Construct a key-free snapshot for the runs table (T2.5).

    Records *which* config drove a run and the non-secret fields, so usage and
    debugging never need the api_key. Falls back to ``server-default`` when the
    user has no usable default config.
    """
    if user_id is None:
        return {"source": "server-default"}
    default = await get_default_llm_config(user_id=user_id)
    if default is None:
        return {"source": "server-default"}
    return {
        "source": "user-config",
        "config_id": str(default.id),
        "model": default.model,
        "base_url": default.base_url,
        "last_verify_ok": default.last_verify_ok,
    }


# ── Sessions & turns (T2.6 multi-turn backfill) ────────────────────


class SessionOwnershipError(Exception):
    """Raised when a session exists and belongs to another user (F08).

    Distinct from "absent" because the two are answered differently *inside*
    the server (create lazily vs reject) while both read as 404 to the caller.
    """


async def ensure_session(*, session_id: uuid.UUID, user_id: uuid.UUID, title: str) -> Session:
    """Idempotently obtain a session row, creating it if absent.

    Sessions are created lazily on the first run of a conversation thread
    (T2.7 exposes full CRUD); this keeps the run path self-contained without a
    separate session-creation call.

    Fail-closed ownership (F08): a session that already belongs to a DIFFERENT
    user is never returned. Returning it is exactly how one user's prompt used
    to land in another user's conversation — the HTTP boundary checks ownership
    first, but the orchestrator reaches this function too, so the check is
    repeated here rather than trusted to the caller.
    """
    async with get_sessionmaker()() as session:
        row = await session.get(Session, session_id)
        if row is None:
            row = Session(id=session_id, user_id=user_id, title=title)
            session.add(row)
            await session.commit()
            return row
        if row.user_id != user_id:
            raise SessionOwnershipError(str(session_id))
        return row


#: How many times ``append_turn`` re-reads ``MAX(seq)`` after losing the unique
#: constraint. Contention is between two writers OF THE SAME SESSION (the user
#: turn written at submission and the assistant turn written at completion, plus
#: any queued run in that session), so a handful of retries is ample.
_APPEND_TURN_ATTEMPTS = 5


async def append_turn(
    *,
    session_id: uuid.UUID,
    role: str,
    content: str,
    run_id: uuid.UUID | None = None,
) -> Turn:
    """Append a turn (user prompt or assistant answer) to a session.

    ``seq`` is computed as ``max(existing seq)+1`` within the session so turns
    stay ordered even when many arrive in the same second.

    F16: two writers can read the same ``max`` before either inserts, so the
    read-then-write is not atomic on its own. ``uq_turns_session_seq`` turns that
    lost race into an ``IntegrityError``, and the retry re-reads the maximum; the
    loser then lands on the next free slot instead of duplicating one. Without
    the constraint the database accepted both rows and the transcript silently
    contained two messages at the same position.
    """
    for attempt in range(_APPEND_TURN_ATTEMPTS):
        try:
            return await _insert_turn(
                session_id=session_id, role=role, content=content, run_id=run_id
            )
        except IntegrityError:
            if attempt == _APPEND_TURN_ATTEMPTS - 1:
                raise
    raise AssertionError("unreachable")  # pragma: no cover - loop always returns or raises


async def _insert_turn(
    *,
    session_id: uuid.UUID,
    role: str,
    content: str,
    run_id: uuid.UUID | None,
) -> Turn:
    """One ``MAX(seq)+1`` attempt; callers retry on the unique-constraint loss."""
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(func.coalesce(func.max(Turn.seq), 0)).where(Turn.session_id == session_id)
        )
        next_seq = (result.scalar_one() or 0) + 1
        turn = Turn(
            session_id=session_id,
            seq=next_seq,
            role=role,
            content=content,
            run_id=run_id,
        )
        session.add(turn)
        await session.commit()
        await session.refresh(turn)
        return turn


async def list_turns(
    *,
    session_id: uuid.UUID,
    limit: int | None = None,
    before_seq: int | None = None,
) -> list[Turn]:
    """Return a session's turns in chronological (seq) order.

    ``limit`` returns only the most recent N turns — used by the history
    renderer to bound prompt size on very long threads, and by the web client so
    a thousand-turn conversation does not arrive in one response.

    ``before_seq`` pages backwards: only turns with a lower ``seq`` are
    considered, so repeated calls walk towards the start of the conversation
    without re-sending what the client already has.
    """
    async with get_sessionmaker()() as session:
        conditions = [Turn.session_id == session_id]
        if before_seq is not None:
            conditions.append(Turn.seq < before_seq)
        stmt = select(Turn).where(*conditions)
        if limit is not None:
            # Take the newest N, then re-sort ascending for stable output.
            stmt = stmt.order_by(Turn.seq.desc()).limit(limit)
            rows = list(reversed((await session.execute(stmt)).scalars().all()))
            return rows
        return list((await session.execute(stmt.order_by(Turn.seq.asc()))).scalars().all())


# ── Session CRUD (T2.7) ─────────────────────────────────────────────


class SessionNotFoundError(Exception):
    """Raised when a session id does not exist or belongs to another user."""


async def create_session(*, user_id: uuid.UUID, title: str | None = None) -> Session:
    """Create a brand-new session for a user.

    ``title`` may be supplied by the client; when omitted the caller derives it
    from the first user message (see ``derive_title``) before calling this.
    """
    async with get_sessionmaker()() as session:
        row = Session(user_id=user_id, title=title or "新对话")
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


def derive_title(text: str, *, limit: int = 60) -> str:
    """Derive a session title from the first user message.

    Collapses whitespace, strips newlines, and truncates — the title is a short
    one-line summary shown in the conversation list, not the full prompt.
    """
    cleaned = " ".join(text.split()).strip()
    if not cleaned:
        return "新对话"
    return cleaned[:limit]


async def get_session(*, session_id: uuid.UUID, user_id: uuid.UUID) -> Session | None:
    """Return a session only if it belongs to ``user_id`` (anti-IDOR).

    Soft-deleted sessions (``deleted_at`` set) are invisible: they read as not
    found so a non-owner cannot distinguish "deleted" from "never existed".
    """
    async with get_sessionmaker()() as session:
        row = await session.get(Session, session_id)
        if row is None:
            return None
        if row.user_id != user_id or row.deleted_at is not None:
            return None
        return row


async def session_exists(session_id: uuid.UUID) -> bool:
    """Whether a session row exists at all, regardless of owner or soft delete.

    Paired with :func:`get_session` at the run-submission boundary (F08):
    ``get_session`` returning ``None`` means "not yours, or gone", and this
    tells the caller whether to answer 404 for an existing-but-foreign session
    or to lazily create a brand-new one. The distinction never leaves the
    server — a caller cannot use it to probe which session ids exist.
    """
    async with get_sessionmaker()() as session:
        return (await session.get(Session, session_id)) is not None


async def list_sessions(
    *, user_id: uuid.UUID, limit: int | None = None, offset: int = 0
) -> list[Session]:
    """List a user's non-deleted sessions, most recent first.

    ``limit``/``offset`` page through the list; the conversation list grows
    without bound otherwise.
    """
    async with get_sessionmaker()() as session:
        stmt = (
            select(Session)
            .where(Session.user_id == user_id, Session.deleted_at.is_(None))
            .order_by(Session.updated_at.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        return list((await session.execute(stmt)).scalars().all())


async def count_sessions(*, user_id: uuid.UUID) -> int:
    """Total non-deleted sessions owned by ``user_id``.

    Paired with :func:`list_sessions` so the API can report whether more pages
    exist — a client that only sees the current page cannot tell.
    """
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(func.count())
            .select_from(Session)
            .where(Session.user_id == user_id, Session.deleted_at.is_(None))
        )
        return int(result.scalar_one())


async def delete_session(*, session_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Soft-delete a session owned by ``user_id`` (idempotent, anti-IDOR)."""
    async with get_sessionmaker()() as session:
        row = await session.get(Session, session_id)
        if row is None or row.user_id != user_id:
            raise SessionNotFoundError(str(session_id))
        row.deleted_at = datetime.now(UTC)
        await session.commit()


# ── Run persistence (T2.7) ──────────────────────────────────────────


class RunNotFoundError(Exception):
    """Raised when a run id does not exist or belongs to another user."""


async def create_run(
    *,
    run_id: uuid.UUID,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    prompt: str,
    pipeline_id: str,
    run_dir: str,
    status: str = "queued",
    llm_config_id: uuid.UUID | None = None,
    llm_snapshot_json: dict | None = None,
) -> Run:
    """Insert a run row at submission time (status="queued")."""
    async with get_sessionmaker()() as session:
        row = Run(
            id=run_id,
            session_id=session_id,
            user_id=user_id,
            prompt=prompt,
            pipeline_id=pipeline_id,
            run_dir=run_dir,
            status=status,
            llm_config_id=llm_config_id,
            llm_snapshot_json=llm_snapshot_json,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def get_run(*, run_id: uuid.UUID, user_id: uuid.UUID) -> Run | None:
    """Return a run only if it belongs to ``user_id`` (anti-IDOR)."""
    async with get_sessionmaker()() as session:
        row = await session.get(Run, run_id)
        if row is None or row.user_id != user_id:
            return None
        return row


#: A run is only ever in one of these while the process that owns it is alive.
#: Anything still in one of them after a start-up belongs to a worker that no
#: longer exists — see :meth:`server.orchestrator.Orchestrator.reconcile_orphan_runs`.
ACTIVE_RUN_STATUSES: tuple[str, ...] = ("queued", "running")


async def list_active_runs() -> list[Run]:
    """Return every run still marked ``queued``/``running``, across all users.

    Deliberately not filtered by owner: reconciliation is a server-wide sweep
    performed at start-up, where there is no request user to filter by, and a
    run abandoned by a crash belongs to whoever submitted it.
    """
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(Run).where(Run.status.in_(ACTIVE_RUN_STATUSES))
        )
        return list(result.scalars().all())


async def update_run_result(
    *,
    run_id: uuid.UUID,
    status: str,
    final_answer: str | None = None,
    error: str | None = None,
    stopped_by: str | None = None,
) -> None:
    """Persist a run's terminal state (T2.7 / T2.6 backfill sink).

    Called by the orchestrator when the worker emits ``run_finished``. Only
    terminal-status fields are touched; credentials and the prompt are never
    overwritten here.
    """
    async with get_sessionmaker()() as session:
        row = await session.get(Run, run_id)
        if row is None:
            return
        row.status = status
        if final_answer is not None:
            row.final_answer = final_answer
        if error is not None:
            row.error = error
        if stopped_by is not None:
            row.stopped_by = stopped_by
        row.finished_at = datetime.now(UTC)
        await session.commit()


async def mark_run_failed_if_active(*, run_id: uuid.UUID, error: str) -> bool:
    """Close a run that failed to launch (F22 / F06-RUN-1).

    A submission is accepted and queued *before* the worker starts. When the
    launch itself fails — e.g. the run-data root is full and writing
    ``history.txt`` raises ENOSPC — the row must not be left ``queued`` forever
    with no worker and no terminal state. Only an ACTIVE run is closed: a run
    that already reached a terminal state is left alone, so a late launch error
    can never overwrite a real outcome. Returns True when it closed a run.
    """
    async with get_sessionmaker()() as session:
        row = await session.get(Run, run_id)
        if row is None or row.status not in ACTIVE_RUN_STATUSES:
            return False
        row.status = "failed"
        row.error = error
        row.finished_at = datetime.now(UTC)
        await session.commit()
        return True


async def mark_run_started(*, run_id: uuid.UUID) -> None:
    """Record that a worker actually began (F20).

    A run row is inserted ``queued`` at submission, and the only proof the
    worker launched is its ``run_started`` frame. Nothing used to consume that
    frame, so the row stayed ``queued`` with an empty ``started_at`` for the
    whole (arbitrarily long) run: the UI could not tell a running run apart from
    one whose worker never started, and a crash left no way to reconstruct when
    it began. The first frame wins — a replayed frame must not move the clock.
    """
    async with get_sessionmaker()() as session:
        row = await session.get(Run, run_id)
        if row is None:
            return
        row.status = "running"
        if row.started_at is None:
            row.started_at = datetime.now(UTC)
        await session.commit()


async def update_run_usage(*, run_id: uuid.UUID, usage: dict) -> None:
    """Persist a run's aggregated token usage (T2.11).

    Called once at the run's terminal state with the output of
    ``server.usage.aggregate_usage``. Writes the summed counters onto the Run row
    and keeps the full aggregate in ``usage_json`` for auditing.

    Unlike :func:`update_run_result` this does NOT touch ``finished_at`` — usage
    is metered after the run has already been closed, and re-metering a finished
    run must not move its completion time.
    """
    async with get_sessionmaker()() as session:
        row = await session.get(Run, run_id)
        if row is None:
            return
        row.prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        row.completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        row.total_tokens = int(usage.get("total_tokens", 0) or 0)
        row.cache_read_tokens = int(usage.get("cache_read_tokens", 0) or 0)
        row.cache_write_tokens = int(usage.get("cache_write_tokens", 0) or 0)
        row.reasoning_tokens = int(usage.get("reasoning_tokens", 0) or 0)
        row.llm_calls = int(usage.get("llm_calls", 0) or 0)
        row.usage_json = dict(usage)
        await session.commit()


# ── Artifacts (T2.9) ─────────────────────────────────────────────


async def record_artifacts(*, run_id: uuid.UUID, artifacts: list[dict]) -> list[Artifact]:
    """Upsert a run's scanned deliverables (size + sha256) into artifacts.

    Called once per run at its terminal state (T2.9) with the output of
    ``server.artifacts.scan_outputs``. The primary key is ``(run_id, rel_path)``,
    so a re-scan (e.g. a re-run or a retried persist) updates size/sha256 in place
    rather than duplicating rows. ``rel_path`` is always relative to the run's
    outputs dir — never an absolute path, so nothing here can point outside it.
    """
    if not artifacts:
        return []
    rows: list[Artifact] = []
    async with get_sessionmaker()() as session:
        for item in artifacts:
            rel = item.get("rel_path")
            if not rel:
                continue
            existing = await session.get(Artifact, (run_id, rel))
            if existing is None:
                row = Artifact(
                    run_id=run_id,
                    rel_path=rel,
                    size=item.get("size"),
                    sha256=item.get("sha256"),
                )
                session.add(row)
            else:
                # Refresh size/sha256: the file may have changed between scans.
                existing.size = item.get("size")
                existing.sha256 = item.get("sha256")
                row = existing
            rows.append(row)
        await session.commit()
    return rows


async def sync_run_artifacts(*, run_id: uuid.UUID, artifacts: list[dict]) -> list[Artifact]:
    """Make a run's artifact index match a fresh scan (F18).

    ``record_artifacts`` upserts, which is right when a run finishes but wrong
    after a revert: a file restored to its baseline keeps its row, and only its
    SIZE and HASH changed — the index then described a file that no longer
    existed in that form, so the UI offered a stale digest and could not tell a
    reverted deliverable from an untouched one. Rows whose path is gone from the
    scan are removed for the same reason.

    Pruning is skipped when the scan hit its file bound: a truncated scan is not
    evidence that the unlisted files disappeared.
    """
    from server.artifacts import _MAX_FILES

    rows = await record_artifacts(run_id=run_id, artifacts=artifacts)
    if len(artifacts) >= _MAX_FILES:
        return rows
    present = {item.get("rel_path") for item in artifacts if item.get("rel_path")}
    async with get_sessionmaker()() as session:
        existing = (
            await session.execute(select(Artifact).where(Artifact.run_id == run_id))
        ).scalars().all()
        for row in existing:
            if row.rel_path not in present:
                await session.delete(row)
        await session.commit()
    return rows


async def list_artifacts(*, run_id: uuid.UUID, user_id: uuid.UUID) -> list[Artifact]:
    """List a run's artifacts, enforcing ownership on the parent run (anti-IDOR).

    The run's owner is checked first, so a guessed run id yields an empty list
    rather than leaking which artifacts exist.
    """
    async with get_sessionmaker()() as session:
        row = await session.get(Run, run_id)
        if row is None or row.user_id != user_id:
            return []
        result = await session.execute(
            select(Artifact).where(Artifact.run_id == run_id).order_by(Artifact.rel_path.asc())
        )
        return list(result.scalars().all())


async def get_artifact(*, run_id: uuid.UUID, rel_path: str, user_id: uuid.UUID) -> Artifact | None:
    """Return one artifact row only if its run belongs to ``user_id``."""
    async with get_sessionmaker()() as session:
        row = await session.get(Run, run_id)
        if row is None or row.user_id != user_id:
            return None
        return await session.get(Artifact, (run_id, rel_path))


# ── Control records (F21) ───────────────────────────────────────────
#
# See :class:`ControlRecord` for the two kinds. Status values are per kind; the
# single ``status`` column keeps the table small and the state machine explicit.

CONTROL_KIND_STEER = "steer"
CONTROL_KIND_APPROVAL = "approval"

# steer: accepted → (delivered | never delivered) → (adopted | dropped)
STEER_UNDELIVERED = "undelivered"  # the POST arrived with no live worker (409)
STEER_QUEUED = "queued"  # handed to the worker's stdin, waiting for a boundary
STEER_ADOPTED = "adopted"  # injected into the conversation at a turn boundary
STEER_DROPPED = "dropped"  # the run ended before the steer could be injected

# approval: requested → (adopted | rejected | expired | abandoned)
APPROVAL_PENDING = "pending"
APPROVAL_ADOPTED = "adopted"  # user approved and the call ran under that decision
APPROVAL_REJECTED = "rejected"  # the user declined
APPROVAL_EXPIRED = "expired"  # the gate timed out and failed closed
APPROVAL_ABANDONED = "abandoned"  # run stopped / worker died while still pending

#: Steer statuses that can still move (everything else is terminal).
STEER_OPEN_STATUSES: frozenset[str] = frozenset({STEER_QUEUED})
#: Approval statuses that can still move.
APPROVAL_OPEN_STATUSES: frozenset[str] = frozenset({APPROVAL_PENDING})


def control_is_open(record: ControlRecord) -> bool:
    """True while the action can still change state (used for run-end closure)."""
    if record.kind == CONTROL_KIND_STEER:
        return record.status in STEER_OPEN_STATUSES
    return record.status in APPROVAL_OPEN_STATUSES


def control_to_dict(record: ControlRecord) -> dict:
    """Project a record for the HTTP surface (``request_json`` already redacted).

    ``external_id`` is the worker-side id (the ``approval_id`` a decision must
    echo for the gate to match it). Without it a dialog rebuilt from the durable
    record after a refresh could only send the row id — which the worker's gate
    cannot match, so the decision was silently dropped and the run stayed parked
    until the gate timed out (found by the F21 browser validation).
    """
    return {
        "control_id": record.id.hex,
        "external_id": record.external_id,
        "run_id": record.run_id.hex,
        "kind": record.kind,
        "status": record.status,
        "request": dict(record.request_json or {}),
        "decision": record.decision,
        "replacement_command": record.replacement_command,
        "adopted_turn_seq": record.adopted_turn_seq,
        "detail": dict(record.detail_json or {}),
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "resolved_at": record.resolved_at.isoformat() if record.resolved_at else None,
    }


async def create_control(
    *,
    run_id: uuid.UUID,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    kind: str,
    status: str,
    request_payload: dict | None = None,
    external_id: str | None = None,
    detail: dict | None = None,
) -> ControlRecord:
    """Persist a control action's first known state.

    Idempotent for approval requests: the row is keyed by
    ``(kind, external_id)``, so a re-delivered ``approval_requested`` frame
    returns the existing record instead of duplicating the request.
    """
    async with get_sessionmaker()() as session:
        if external_id:
            existing = (
                await session.execute(
                    select(ControlRecord).where(
                        ControlRecord.kind == kind,
                        ControlRecord.external_id == external_id,
                    )
                )
            ).scalars().first()
            if existing is not None:
                return existing
        row = ControlRecord(
            run_id=run_id,
            session_id=session_id,
            user_id=user_id,
            kind=kind,
            status=status,
            external_id=external_id,
            request_json=request_payload,
            detail_json=detail,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def get_control(*, control_id: uuid.UUID) -> ControlRecord | None:
    """Fetch one control record by its id."""
    async with get_sessionmaker()() as session:
        return await session.get(ControlRecord, control_id)


async def get_control_by_external_id(*, kind: str, external_id: str) -> ControlRecord | None:
    """Fetch the record a worker-side id maps to (approval_id → record)."""
    async with get_sessionmaker()() as session:
        return (
            await session.execute(
                select(ControlRecord).where(
                    ControlRecord.kind == kind,
                    ControlRecord.external_id == external_id,
                )
            )
        ).scalars().first()


async def list_controls(
    *,
    run_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    kind: str | None = None,
    statuses: list[str] | None = None,
) -> list[ControlRecord]:
    """List control records oldest-first, optionally filtered.

    ``session_id`` is what the history renderer uses to find the steers a
    conversation has already adopted; the route uses ``run_id``/``statuses``.
    """
    async with get_sessionmaker()() as session:
        conditions = []
        if run_id is not None:
            conditions.append(ControlRecord.run_id == run_id)
        if session_id is not None:
            conditions.append(ControlRecord.session_id == session_id)
        if kind is not None:
            conditions.append(ControlRecord.kind == kind)
        if statuses:
            conditions.append(ControlRecord.status.in_(statuses))
        stmt = select(ControlRecord).where(*conditions).order_by(ControlRecord.created_at.asc())
        return list((await session.execute(stmt)).scalars().all())


async def resolve_control(
    *,
    control_id: uuid.UUID | None = None,
    kind: str | None = None,
    external_id: str | None = None,
    status: str,
    decision: str | None = None,
    replacement_command: str | None = None,
    adopted_turn_seq: int | None = None,
    request_payload: dict | None = None,
    detail: dict | None = None,
) -> ControlRecord | None:
    """Move a control record to ``status`` (a terminal state, in practice).

    Terminal states are not overwritten: a duplicate ``approval_resolved`` frame
    (or a retried decision POST) must not rewrite a decision that already
    landed — the same idempotence rule the run's terminal frame follows (F15).
    ``None`` means no such record; callers decide whether to create one late.
    """
    async with get_sessionmaker()() as session:
        if control_id is not None:
            row = await session.get(ControlRecord, control_id)
        elif kind is not None and external_id is not None:
            row = (
                await session.execute(
                    select(ControlRecord).where(
                        ControlRecord.kind == kind,
                        ControlRecord.external_id == external_id,
                    )
                )
            ).scalars().first()
        else:
            raise ValueError("resolve_control needs a control_id or (kind, external_id)")
        if row is None:
            return None
        if not control_is_open(row):
            return row
        row.status = status
        if decision is not None:
            row.decision = decision
        if replacement_command is not None:
            row.replacement_command = replacement_command
        if adopted_turn_seq is not None:
            row.adopted_turn_seq = adopted_turn_seq
        if request_payload is not None and row.request_json is None:
            row.request_json = request_payload
        if detail:
            row.detail_json = {**(row.detail_json or {}), **detail}
        row.resolved_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(row)
        return row


async def close_open_controls(
    *,
    run_id: uuid.UUID,
    closed_by: str,
) -> int:
    """Close every still-open control record of a finished run (F21).

    A run that ends while a steer sits in the worker's inbox, or while an
    approval is parked on the gate, would otherwise leave a record that reads
    "still pending" forever — the exact "收到/排队/采用无法长期区分" failure this
    task exists to fix. Steers become ``dropped`` (delivered but never injected),
    approvals become ``abandoned`` (nobody can decide once the worker is gone).

    Returns how many rows were closed.
    """
    async with get_sessionmaker()() as session:
        rows = (
            await session.execute(
                select(ControlRecord).where(ControlRecord.run_id == run_id)
            )
        ).scalars().all()
        closed = 0
        for row in rows:
            if not control_is_open(row):
                continue
            row.status = (
                STEER_DROPPED if row.kind == CONTROL_KIND_STEER else APPROVAL_ABANDONED
            )
            row.detail_json = {**(row.detail_json or {}), "closed_by": closed_by}
            row.resolved_at = datetime.now(UTC)
            closed += 1
        if closed:
            await session.commit()
        return closed
