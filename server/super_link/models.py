"""Optional collaboration schema, outside the legacy readiness metadata.

Cross-metadata foreign keys reference existing columns; only these optional tables are
created by the dedicated Super-link migration entry.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from server import store


class Base(DeclarativeBase):
    pass


class SuperLinkSpace(Base):
    """An opt-in collaboration; no shared research/monitoring business state."""

    __tablename__ = "super_link_spaces"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(store.User.__table__.c.id), nullable=False
    )
    creation_key: Mapped[uuid.UUID] = mapped_column(nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    goal_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    control_state: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    control_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivery_cutoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    automatic_run_limit: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("user_id", "creation_key"),)


class SuperLinkParticipant(Base):
    """One exclusive research session per participant; V1 permits one pair."""

    __tablename__ = "super_link_participants"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("super_link_spaces.id"), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(store.Session.__table__.c.id), nullable=False, unique=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (
        UniqueConstraint("space_id", "role"),
        UniqueConstraint("id", "space_id"),
        CheckConstraint("role IN ('team', 'single')", name="ck_super_link_role"),
    )


class SuperLinkMessage(Base):
    """Immutable registered content; publication is separate from receipt/execution."""

    __tablename__ = "super_link_messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("super_link_spaces.id"), nullable=False)
    sender_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    recipient_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    source_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(store.Run.__table__.c.id), nullable=False
    )
    registration_key: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    in_reply_to: Mapped[uuid.UUID | None] = mapped_column()
    revises_message_id: Mapped[uuid.UUID | None] = mapped_column()
    goal_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="registered")
    continuity_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("source_run_id", "registration_key"),
        UniqueConstraint("id", "space_id"),
        ForeignKeyConstraint(
            ["sender_id", "space_id"],
            ["super_link_participants.id", "super_link_participants.space_id"],
        ),
        ForeignKeyConstraint(
            ["recipient_id", "space_id"],
            ["super_link_participants.id", "super_link_participants.space_id"],
        ),
        ForeignKeyConstraint(
            ["in_reply_to", "space_id"],
            ["super_link_messages.id", "super_link_messages.space_id"],
        ),
        ForeignKeyConstraint(
            ["revises_message_id", "space_id"],
            ["super_link_messages.id", "super_link_messages.space_id"],
        ),
        CheckConstraint("sender_id <> recipient_id", name="ck_super_link_peer"),
        CheckConstraint("state IN ('registered', 'published')", name="ck_super_link_message_state"),
    )


class SuperLinkOutbox(Base):
    """Recoverable notifications. Redis never owns the message payload."""

    __tablename__ = "super_link_outbox"

    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("super_link_messages.id"), primary_key=True
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_super_link_outbox_pending", "state", "notified_at"),
        CheckConstraint(
            "state IN ('pending', 'received', 'quarantined')", name="ck_super_link_outbox_state"
        ),
    )


class SuperLinkReceipt(Base):
    """Durable transport receipt, NOT reviewer approval or execution acceptance."""

    __tablename__ = "super_link_receipts"

    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("super_link_messages.id"), primary_key=True
    )
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="awaiting_check")
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("state = 'awaiting_check'", name="ck_super_link_receipt_state"),
    )


class SuperLinkFinalization(Base):
    """Host exit witness; a terminal model frame is insufficient for publication."""

    __tablename__ = "super_link_finalizations"
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(store.Run.__table__.c.id), primary_key=True
    )
    worker_exited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_code: Mapped[int | None] = mapped_column(Integer)
    expected_head_run_id: Mapped[uuid.UUID | None] = mapped_column()
    state: Mapped[str] = mapped_column(String(16), default="executing", nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recovery_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    recovery_limit: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    process_identity: Mapped[dict | None] = mapped_column(JSON)
    __table_args__ = (
        CheckConstraint(
            "state IN ('executing', 'pending', 'ready', 'failed')", name="ck_sl_finalize"
        ),
    )


class SuperLinkReview(Base):
    """Independent inspection result, pinned to the immutable delivery and goal."""

    __tablename__ = "super_link_reviews"
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("super_link_messages.id"), primary_key=True
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    goal_version: Mapped[int] = mapped_column(Integer, nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer: Mapped[str] = mapped_column(String(200), nullable=False)
    admission_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    admission_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    admission_error: Mapped[str | None] = mapped_column(String(64))
    admission_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    admission_limit: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    admission_held: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    attempt_limit: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_kind: Mapped[str | None] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint(
            "verdict IN ('pass', 'caveat', 'block', 'incomplete')", name="ck_sl_review"
        ),
    )


class SuperLinkExecution(Base):
    """Execution acceptance, separate from transport receipt and inspection."""

    __tablename__ = "super_link_executions"
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("super_link_messages.id"), primary_key=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(store.Run.__table__.c.id), unique=True)


class SuperLinkEvidence(Base):
    """Immutable, bounded UTF-8 evidence; never a peer's private history/path grant."""

    __tablename__ = "super_link_evidence"
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("super_link_messages.id"), primary_key=True
    )
    rel_path: Mapped[str] = mapped_column(String(500), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)


class SuperLinkInboxAccess(Base):
    """Informational deliveries visible at the start of one run, never live injection."""

    __tablename__ = "super_link_inbox_access"
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(store.Run.__table__.c.id), primary_key=True
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("super_link_messages.id"), primary_key=True
    )


class SuperLinkReviewAttempt(Base):
    """Versioned inspector inputs and outcomes; only the current lease can complete."""

    __tablename__ = "super_link_review_attempts"
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("super_link_messages.id"), primary_key=True
    )
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    reviewer: Mapped[str] = mapped_column(String(200))
    input_json: Mapped[dict] = mapped_column(JSON)
    model_snapshot: Mapped[dict | None] = mapped_column(JSON)
    verdict: Mapped[str] = mapped_column(String(16), default="incomplete")
    explanation: Mapped[str] = mapped_column(Text, default="inspection_pending")
    failure_kind: Mapped[str | None] = mapped_column(String(24))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SuperLinkFeedback(Base):
    """Coordinator-owned correction task; the reviewer never dispatches a Run."""

    __tablename__ = "super_link_feedback"
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("super_link_messages.id"), primary_key=True
    )
    review_number: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(store.Run.__table__.c.id), unique=True
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    attempt_limit: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    held: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class SuperLinkRecoveryAction(Base):
    """Owner-authenticated, idempotent recovery decisions. Never an approval override."""

    __tablename__ = "super_link_recovery_actions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("super_link_spaces.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(store.User.__table__.c.id))
    idempotency_key: Mapped[uuid.UUID] = mapped_column()
    request_json: Mapped[dict] = mapped_column(JSON)
    result_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("space_id", "idempotency_key"),)


class SuperLinkEventHead(Base):
    """Per-space event frontier; the row lock serialises sequence allocation."""

    __tablename__ = "super_link_event_heads"

    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("super_link_spaces.id"), primary_key=True
    )
    stream_epoch: Mapped[uuid.UUID] = mapped_column(nullable=False, default=uuid.uuid4)
    last_seq: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    min_after: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )


class SuperLinkEvent(Base):
    """Committed, redacted fact; the database is authoritative and Redis only hints."""

    __tablename__ = "super_link_events"

    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("super_link_event_heads.space_id"), primary_key=True
    )
    stream_epoch: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(nullable=False, default=uuid.uuid4, unique=True)
    transaction_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    change_key: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="space")
    source_id: Mapped[str | None] = mapped_column(String(64))
    participant_id: Mapped[uuid.UUID | None] = mapped_column()
    session_id: Mapped[uuid.UUID | None] = mapped_column()
    run_id: Mapped[uuid.UUID | None] = mapped_column()
    data_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    invalidate_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("space_id", "stream_epoch", "change_key"),
        Index(
            "ix_super_link_events_pending",
            "notified_at",
            "space_id",
            "stream_epoch",
            "seq",
        ),
    )
