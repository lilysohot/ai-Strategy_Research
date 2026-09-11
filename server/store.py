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
    Integer,
    LargeBinary,
    String,
    Text,
    event,
    func,
    select,
    update,
)
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

    __table_args__ = ()


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
    """Lightweight health check."""
    try:
        async with get_sessionmaker()() as s:
            await s.execute(select(func.count()).select_from(User.__table__))
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


async def ensure_session(*, session_id: uuid.UUID, user_id: uuid.UUID, title: str) -> Session:
    """Idempotently obtain a session row, creating it if absent.

    Sessions are created lazily on the first run of a conversation thread
    (T2.7 exposes full CRUD); this keeps the run path self-contained without a
    separate session-creation call.
    """
    async with get_sessionmaker()() as session:
        row = await session.get(Session, session_id)
        if row is None:
            row = Session(id=session_id, user_id=user_id, title=title)
            session.add(row)
            await session.commit()
        return row


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
    """
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
