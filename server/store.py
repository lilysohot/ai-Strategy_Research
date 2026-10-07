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
from decimal import Decimal

from sqlalchemy import (
    DDL,
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
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
    __table_args__ = (Index("uq_turns_session_seq", "session_id", "seq", unique=True),)


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


# ——— 业务资料对象（DATA-02 / PR-DATA-13 / PR-BIZ-01） ——————————————————————
#
# 这一组表是“用户业务事实”的真源：账户、研究所属计划、手工持仓/成交、策略版本
# 和研究绑定。契约见 docs/design/web-business-data-contract.md，约束要点：
#   * 金额/价格/数量用精确数值；缺失是 NULL，绝不用 0 冒充（AC-03/26）；
#   * 版本行只追加、不修改：每次变更写一个新的 ``revision`` 行，当前表只做指针；
#   * 计划必须且只能属于一个研究；主计划只能从该研究自己的计划集合中选（AC-01）；
#   * 账户归用户、可被多个研究引用；计划不跨研究共享（AC-17）。

#: 金额 / 价格 / 数量：30 位总精度、10 位小数，覆盖资产范围且不经过浮点。
MONEY = Numeric(precision=30, scale=10, asdecimal=True)
#: 比例 / 盈亏比：20 位总精度、10 位小数，且必须配合 ``unit`` 才有意义。
RATIO = Numeric(precision=20, scale=10, asdecimal=True)


class InvestmentAccount(Base):
    """交易账户资料的当前指针行（与平台登录账号无关）。"""

    __tablename__ = "investment_accounts"
    __table_args__ = (
        # 聊天里说“当前账户”时，账户名必须能唯一定位到一个对象（AC-02）。
        UniqueConstraint("user_id", "name", name="uq_investment_accounts_user_name"),
        # 让研究绑定可以声明“账户属于同一用户”的复合外键（AC-09）。
        UniqueConstraint("user_id", "id", name="uq_investment_accounts_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    base_currency: Mapped[str] = mapped_column(String, nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: 已落库的最大版本号；读取版本明细时用 revisions 表，不在此行复制正文。
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InvestmentAccountRevision(Base):
    """账户资料的不可变版本行：只 INSERT，不 UPDATE、不 DELETE。"""

    __tablename__ = "investment_account_revisions"
    __table_args__ = (
        UniqueConstraint("account_id", "revision", name="uq_account_revisions_version"),
        Index("ix_account_revisions_account", "account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("investment_accounts.id"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    #: 总资金 / 可用资金分开保存；没有数据就是 NULL，不是 0（AC-03）。
    total_capital: Mapped[Decimal | None] = mapped_column(MONEY)
    available_capital: Mapped[Decimal | None] = mapped_column(MONEY)
    capital_basis: Mapped[str | None] = mapped_column(String)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    #: 业务时点（用户资料“截至何时”），与 created_at（记录时间）分开。
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: submitted=用户主动提交的完整资料；incomplete=主动保存但仍待补充，不可用于依赖计算。
    record_state: Mapped[str] = mapped_column(String, nullable=False, default="submitted")
    source_kind: Mapped[str] = mapped_column(String, nullable=False, default="form")
    source_ref: Mapped[str | None] = mapped_column(String)
    changed_fields: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvestmentPlan(Base):
    """投资计划的当前指针行。**必须且只能属于一个研究**（AC-01）。"""

    __tablename__ = "investment_plans"
    __table_args__ = (
        # 让研究绑定可以声明“主计划属于本研究计划集合”的复合外键（AC-01）。
        UniqueConstraint("research_id", "id", name="uq_investment_plans_research_id"),
        Index("ix_investment_plans_research", "research_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    #: 研究（sessions）。非空是“计划不能脱离研究存在”的库级保证。
    research_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InvestmentPlanRevision(Base):
    """计划资料的不可变版本行。计划价与实际成交价分属不同对象（AC-26）。"""

    __tablename__ = "investment_plan_revisions"
    __table_args__ = (
        UniqueConstraint("plan_id", "revision", name="uq_plan_revisions_version"),
        Index("ix_plan_revisions_plan", "plan_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investment_plans.id"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    symbol: Mapped[str | None] = mapped_column(String)
    market: Mapped[str | None] = mapped_column(String)
    asset_type: Mapped[str | None] = mapped_column(String)
    direction: Mapped[str | None] = mapped_column(String)
    plan_price: Mapped[Decimal | None] = mapped_column(MONEY)
    plan_price_low: Mapped[Decimal | None] = mapped_column(MONEY)
    plan_price_high: Mapped[Decimal | None] = mapped_column(MONEY)
    target_price: Mapped[Decimal | None] = mapped_column(MONEY)
    #: 风险预算可能是金额也可能是百分比：数值与单位分开保存，不靠字段名猜。
    risk_budget_value: Mapped[Decimal | None] = mapped_column(MONEY)
    risk_budget_unit: Mapped[str | None] = mapped_column(String)
    position_limit_value: Mapped[Decimal | None] = mapped_column(MONEY)
    position_limit_unit: Mapped[str | None] = mapped_column(String)
    time_window: Mapped[str | None] = mapped_column(String)
    invalidation: Mapped[str | None] = mapped_column(Text)
    profit_loss_ratio: Mapped[Decimal | None] = mapped_column(RATIO)
    profit_loss_ratio_definition: Mapped[str | None] = mapped_column(String)
    currency: Mapped[str | None] = mapped_column(String)
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    record_state: Mapped[str] = mapped_column(String, nullable=False, default="submitted")
    source_kind: Mapped[str] = mapped_column(String, nullable=False, default="form")
    source_ref: Mapped[str | None] = mapped_column(String)
    changed_fields: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PositionSnapshot(Base):
    """用户手工录入的持仓快照；不与其他记录叠加重算资金（PRD §3.2）。"""

    __tablename__ = "position_snapshots"
    __table_args__ = (Index("ix_position_snapshots_account", "account_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("investment_accounts.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    market: Mapped[str | None] = mapped_column(String)
    quantity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cost_basis: Mapped[str | None] = mapped_column(String)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_kind: Mapped[str] = mapped_column(String, nullable=False, default="form")
    source_ref: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    #: 更正链：新行指向被更正的旧行，旧行保留原值。
    corrects_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("position_snapshots.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TradeRecord(Base):
    """用户提供的成交记录。更正保留前值，不因更正而抹掉历史（AC-22）。"""

    __tablename__ = "trade_records"
    __table_args__ = (Index("ix_trade_records_account_symbol", "account_id", "symbol"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("investment_accounts.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    market: Mapped[str | None] = mapped_column(String)
    side: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    fees: Mapped[Decimal | None] = mapped_column(MONEY)
    traded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_kind: Mapped[str] = mapped_column(String, nullable=False, default="form")
    source_ref: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    corrects_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trade_records.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResearchInvestmentLink(Base):
    """研究 → 账户引用 + 当前主计划（第一版一个研究至多一个账户）。

    两个复合外键把“归属一致性”下沉到数据库：账户必须属于同一用户，
    主计划必须属于本研究自己的计划集合 —— 这正是 AC-01 与 AC-09 的库级保证。
    """

    __tablename__ = "research_investment_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "account_id"],
            ["investment_accounts.user_id", "investment_accounts.id"],
            name="fk_research_links_account_owner",
        ),
        ForeignKeyConstraint(
            ["research_id", "primary_plan_id"],
            ["investment_plans.research_id", "investment_plans.id"],
            name="fk_research_links_plan_research",
        ),
    )

    research_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("investment_accounts.id"))
    primary_plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("investment_plans.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StrategyVersion(Base):
    """系统策略产物版本；用户采纳后在所属研究创建计划，不变成已成交事实。"""

    __tablename__ = "strategy_versions"
    __table_args__ = (Index("ix_strategy_versions_research", "research_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    research_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str | None] = mapped_column(String)
    artifact_rel_path: Mapped[str | None] = mapped_column(String)
    payload_ref: Mapped[str | None] = mapped_column(Text)
    adopted_plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("investment_plans.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BusinessOperation(Base):
    """一次业务写操作的幂等记录与结果快照（DATA-03）。

    保存动作必须是可重放的：网络超时后客户端不知道服务端是否已写入，盲目重试会
    产生第二个版本甚至第二个 Run。这里以 ``(user_id, idempotency_key)`` 唯一约束
    承接“同键同内容返回原结果、同键不同内容拒绝”，并把结果保存下来，使刷新后的
    页面能用不含业务正文的 ``operation_id`` 找回提交结果。
    """

    __tablename__ = "business_operations"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_business_operations_key"),
        Index("ix_business_operations_user_recent", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    #: 操作类型（``account.create`` / ``plan.update`` / …），与幂等键共同限定作用域。
    scope: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    #: 规范化请求摘要：同键不同内容据此拒绝，避免把摘要比较交给调用方。
    request_digest: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="in_progress")
    result_json: Mapped[dict | None] = mapped_column(JSON)
    error_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    #: 保留期边界；清理不得让原动作再次执行，只影响“还能查多久”。
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunInvestmentSnapshot(Base):
    """一个 Run 采用的业务输入快照（DATA-05 / AC-06、07、26、27）。

    快照是**提交那一刻**的事实：把账户/计划/持仓/成交的对象版本与解析后的完整有效值
    一起冻结，Run 之后无论资料怎么改、无论是压缩还是换模型，读到的都是这一份。
    只存 ID 不算快照 —— 那样等执行时再读，读到的是那时的数据。

    行只 INSERT 不 UPDATE：创建后不可变是快照的全部意义，重算用**新 Run + 新快照**，
    旧轨迹与旧快照原样保留。
    """

    __tablename__ = "run_investment_snapshots"
    __table_args__ = (
        # 一个 Run 至多一份快照；重复冻结会在库层失败而不是悄悄覆盖。
        UniqueConstraint("run_id", name="uq_run_investment_snapshots_run"),
        Index("ix_run_snapshots_research", "research_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    #: 研究（sessions）；快照永远属于一个研究，计划也必须属于同一研究。
    research_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    #: 快照结构版本：读取方据此判断是否还能解释这份快照。
    schema_version: Mapped[str] = mapped_column(String, nullable=False)
    use_case: Mapped[str] = mapped_column(String, nullable=False, default="general_reading")
    #: manual=用户手动提交；watch_event=监控触发（DATA-11 使用）。
    source: Mapped[str] = mapped_column(String, nullable=False, default="manual")
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("investment_accounts.id"))
    account_revision: Mapped[int | None] = mapped_column(Integer)
    plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("investment_plans.id"))
    plan_revision: Mapped[int | None] = mapped_column(Integer)
    position_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("position_snapshots.id")
    )
    trade_record_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trade_records.id"))
    #: 重算关联：新 Run 指向被重算的旧 Run，旧快照不被修改。
    rerun_of_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id"))
    #: 解析后的完整有效值：字段 → {value, currency, unit, as_of, status, source}。
    resolved_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    #: 用途必需但缺失的字段：只记录，不在此处用当前值回填。
    missing_json: Mapped[dict | None] = mapped_column(JSON)
    #: 本次提交显式声明的值，原样保存便于审计（值为十进制文本）。
    declared_json: Mapped[dict | None] = mapped_column(JSON)
    #: 冻结时点：与 created_at（记录时间）分开，重算时两个 Run 各不相同。
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InputRequest(Base):
    """Durable request for facts required before analysis can continue (DATA-07)."""

    __tablename__ = "input_requests"
    __table_args__ = (
        Index("ix_input_requests_user_status", "user_id", "status", "created_at"),
        Index("ix_input_requests_research", "research_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    research_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    source_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id"))
    # DATA-11 owns the watch-event table. Keep this opaque until that table exists.
    watch_event_id: Mapped[uuid.UUID | None] = mapped_column()
    follow_up_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id"), unique=True)
    use_case: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    fields_json: Mapped[list] = mapped_column(JSON, nullable=False)
    known_versions_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    continuation_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    collected_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InputRequestAnswer(Base):
    """Append-only answer history; partial and ambiguous replies remain auditable."""

    __tablename__ = "input_request_answers"
    __table_args__ = (
        UniqueConstraint("request_id", "revision", name="uq_input_request_answer_revision"),
        Index("ix_input_request_answers_request", "request_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("input_requests.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    declared_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    operation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("business_operations.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BusinessEvent(Base):
    """Durable user notification outside per-Run trajectory events (DATA-12 B slice)."""

    __tablename__ = "business_events"
    __table_args__ = (
        UniqueConstraint("id", name="uq_business_events_id"),
        Index("ix_business_events_user_cursor", "user_id", "cursor"),
    )

    cursor: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    id: Mapped[uuid.UUID] = mapped_column(default=_uuid, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    research_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    request_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("input_requests.id"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id"))
    kind: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    detail_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WatchRule(Base):
    """监控规则的当前指针行（DATA-09 / PR-WATCH-01）。

    规则**必须且只能属于一个研究**，可选绑定该研究所属计划；计划改版不静默修改已保存的
    阈值（阈值只存在于版本行）。生命周期状态（active/paused/cancelled）在指针行维护，
    配置每次编辑落一条不可变 ``WatchRuleRevision``，改版不复用旧版报价基线与触发资格
    （判定语义由 DATA-10 消费）。
    """

    __tablename__ = "watch_rules"
    __table_args__ = (
        # 让"规则必须属于同用户/同研究"可声明为复合外键的归属依据（AC-09）。
        UniqueConstraint("user_id", "id", name="uq_watch_rules_user_id"),
        Index("ix_watch_rules_research_status", "research_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    research_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    #: 该研究所属计划（可为空：提醒/纯标的规则不强制绑定计划）。
    plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("investment_plans.id"))
    name: Mapped[str] = mapped_column(String, nullable=False)
    #: active=生效；paused=暂停（恢复按新观测重新校验，不补发积压旧触发）；cancelled=终态。
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    #: 已落库的最大配置版本号；配置明细读取版本行，不在指针行复制正文。
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: 最近一次检查时间与"有效行情"观测（DATA-10 判定侧写入；无可靠观测不得用 now 冒充）。
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_valid_quote_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_valid_quote_price: Mapped[Decimal | None] = mapped_column(MONEY)
    #: 单次触发资格：True=本版本仍可触发一次；触发后置 False，分析失败不恢复（DATA-10）。
    armed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: 最近一次用于穿越判定的已核验价格（基线）。编辑（新版本）时复位，不复用旧版基线。
    baseline_price: Mapped[Decimal | None] = mapped_column(MONEY)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: 最近一次未触发原因（单次资格已消耗 / 冷却中穿越等），供 UI 展示，不反复建分析。
    last_suppressed_reason: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WatchRuleRevision(Base):
    """监控规则的不可变配置版本行：只 INSERT，不 UPDATE、不 DELETE。

    版本行是规则触发语义的唯一真源：阈值、方向、有效期、触发资格策略在创建/编辑时冻结，
    计划改版、暂停/恢复都不改写既有版本（契约 §9）。
    """

    __tablename__ = "watch_rule_revisions"
    __table_args__ = (
        UniqueConstraint("rule_id", "version", name="uq_watch_rule_revisions_version"),
        Index("ix_watch_rule_revisions_rule", "rule_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("watch_rules.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    market: Mapped[str] = mapped_column(String, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    #: 行情口径（如 last）；实际是否可达由 DATA-10 按供应商核验，本行只冻结用户选择。
    quote_basis: Mapped[str] = mapped_column(String, nullable=False, default="last")
    #: up=上穿、down=下穿、range=进入区间。up/down 用 threshold_low；range 用 low/high。
    direction: Mapped[str] = mapped_column(String, nullable=False)
    threshold_low: Mapped[Decimal | None] = mapped_column(MONEY)
    threshold_high: Mapped[Decimal | None] = mapped_column(MONEY)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: C 阶段只开放 single；repeat（含冷却/重新布防参数）在 D 阶段。
    trigger_mode: Mapped[str] = mapped_column(String, nullable=False, default="single")
    #: notify=仅提醒（不调用模型）；auto_analyze=按已保存指令创建分析 Run（DATA-11）。
    action: Mapped[str] = mapped_column(String, nullable=False)
    #: auto_analyze 时的分析任务指令；notify 时为空。
    task: Mapped[str | None] = mapped_column(Text)
    budget_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: 创建时已满足条件：trigger_now=立即触发一次；wait_requalify=等待重新穿越。
    on_create_already_met: Mapped[str] = mapped_column(
        String, nullable=False, default="trigger_now"
    )
    #: 断线恢复后首个报价已满足条件：trigger_once=触发一次并标注观测缺口；
    #: wait_requalify=不补发，等待新的有效穿越。
    disconnect_recovery: Mapped[str] = mapped_column(String, nullable=False, default="trigger_once")
    source_kind: Mapped[str] = mapped_column(String, nullable=False, default="form")
    source_ref: Mapped[str | None] = mapped_column(String)
    changed_fields: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WatchObservation(Base):
    """监控判定的观测真源（DATA-10）。

    与 ``plugins.market.Quote``（float + 适配器可回退本地时间）分开：本表保存判定用到的
    **精确价格**、供应商观测时间/本地接收时间、时间来源与可信度。``observed_at_ms`` 为
    ``None`` 表示供应商未提供可靠观测时间（``time_source=unknown``），不得以本地 now 冒充。
    """

    __tablename__ = "watch_observations"
    __table_args__ = (
        # 去重身份：同规则、同时点、同价格的重复投递只记一次，不重复判定。
        UniqueConstraint("dedup_hash", name="uq_watch_observations_dedup"),
        Index("ix_watch_observations_rule_time", "rule_id", "received_at_ms"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("watch_rules.id"), nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    research_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    market: Mapped[str] = mapped_column(String, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    quote_basis: Mapped[str] = mapped_column(String, nullable=False, default="last")
    #: 判定用精确价格（观测归一到最小报价单位或保留原值，不用 float 参与比较）。
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    observed_at_ms: Mapped[int | None] = mapped_column(BigInteger)
    received_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    time_source: Mapped[str] = mapped_column(String, nullable=False, default="vendor")
    #: 真实适配器只能给 float 时置 True：值已经过 float 往返，精度受限但判定仍可用。
    precision_limited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_ref: Mapped[str | None] = mapped_column(String)
    dedup_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WatchEvent(Base):
    """监控触发事实（DATA-10 创建；DATA-11 消费为自动分析 Run）。

    事件唯一身份 = 规则版本 + 一次触发资格：C 阶段单次模式一个规则版本至多一个事件，
    重复投递与并发判定不重复消耗资格。``pending`` 表示等待 DATA-11 调度。
    """

    __tablename__ = "watch_events"
    __table_args__ = (
        UniqueConstraint("rule_id", "rule_version", name="uq_watch_events_rule_version"),
        Index("ix_watch_events_research_status", "research_id", "status"),
        Index("ix_watch_events_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("watch_rules.id"), nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    research_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    market: Mapped[str] = mapped_column(String, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    quote_basis: Mapped[str] = mapped_column(String, nullable=False, default="last")
    direction: Mapped[str] = mapped_column(String, nullable=False)
    threshold_low: Mapped[Decimal | None] = mapped_column(MONEY)
    threshold_high: Mapped[Decimal | None] = mapped_column(MONEY)
    prev_price: Mapped[Decimal | None] = mapped_column(MONEY)
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    observed_at_ms: Mapped[int | None] = mapped_column(BigInteger)
    received_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    time_source: Mapped[str] = mapped_column(String, nullable=False, default="vendor")
    trigger_reason: Mapped[str] = mapped_column(String, nullable=False)
    #: pending=待 DATA-11 调度；dispatching=已建 Run 待执行；completed/failed 由 Run 终态
    #: 对账写入；expired/merged/blocked_budget/needs_input 由调度侧写入。
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    #: 本次分析关联的 Run（最近一次生成；完整代次历史见 watch_event_runs）。
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id"))
    #: 分析代次：每事件每代次唯一（重试沿用，重新分析 +1 且保留旧终态）。
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: 合并去向：同研究同标的同意图的待派发事件只保留最早一条，其余置 merged。
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("watch_events.id"))
    budget_reason: Mapped[str | None] = mapped_column(String)
    #: 分析截止（received_at + 最大排队延迟）；超过仍未调度 → expired。
    analysis_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WatchEventRun(Base):
    """事件 → Run 的分析代次链路（DATA-11）。

    每事件每代次唯一（``(event_id, generation)``）：派发重试沿用原 Run/快照；终态后的
    重新分析创建新代次并保留旧终态，不因"同一事件"覆盖旧分析。
    """

    __tablename__ = "watch_event_runs"
    __table_args__ = (
        UniqueConstraint("event_id", "generation", name="uq_watch_event_runs_generation"),
        Index("ix_watch_event_runs_event", "event_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("watch_events.id"), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WatchBudgetUsage(Base):
    """每规则版本的自动分析预算台账（DATA-11）。

    调度时**原子预留并记账**：``runs_created`` 供 max_runs 次数上限裁决；``runs_attempted``
    记录实际调用尝试。释放/结算保持幂等（同一规则版本同一行累加，不重复计数）。
    """

    __tablename__ = "watch_budget_usage"
    __table_args__ = (
        UniqueConstraint("rule_id", "rule_version", name="uq_watch_budget_usage_rule_version"),
        Index("ix_watch_budget_usage_rule", "rule_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("watch_rules.id"), nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    runs_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    runs_attempted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RunDispatch(Base):
    """Run 的持久派发记录（outbox，DATA-06 / AC-05、15、23）。

    业务 Run 的创建（资料、快照、Run 行、用户消息）与它的"待派发"意图落在**同一个
    事务**里：提交成功但进程崩溃，重启后这条记录还在，派发可以恢复；提交失败则
    什么都不存在，不会出现"资料已保存但分析永远不来"。

    状态与 Run 状态**分离**（契约 §7）：
    pending → claimed → dispatched；失败回 retryable_failed（到期再领）；
    重试耗尽或被取消 → abandoned。租约 + 领取版本让多进程安全领取：
    过期租约只有核定了旧 worker 状态（Run 是否真的启动过）才允许重投。
    """

    __tablename__ = "run_dispatch_outbox"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_run_dispatch_outbox_run"),
        Index("ix_run_dispatch_due", "status", "next_attempt_at"),
        Index("ix_run_dispatch_research", "research_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    research_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    #: 编排器的会话键（客户端 session_id 字符串）。派发必须用**同一个键**排队，
    #: 同研究的串行才不会被不同的字符串拆散。
    session_key: Mapped[str] = mapped_column(String, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_addendum: Mapped[str | None] = mapped_column(Text)
    agent_tools: Mapped[str] = mapped_column(String, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    #: 下次允许领取的时间；重试退避与研究忙延迟都靠它。
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: 领取版本：续投/完成回报必须带上领取时的版本，过期领取者的回报不被接受。
    claim_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RunUpload(Base):
    """一次提交里上传附件的持久清单（DATA-06 / AC-05、23）。

    文件字节不属于数据库事务，但"有哪些附件、内容摘要是什么、是否已发布到
    ``inputs``"必须是持久事实，否则会出现"数据库成功但启动缺文件的分析"：

    * 提交时先把字节写进受控**暂存区**（``<run_root>/staging``），算出 ``sha256``，
      并在与 Run/outbox **同一事务**里写下清单行（``status=staged``）——即"发布意图"；
    * worker 领取前，派发侧先按清单做**发布校验**：暂存文件存在且摘要一致才移入
      ``inputs`` 并置 ``published``；校验不过就不派发（退避重试，最终 abandoned）；
    * ``(run_id, stored_name)`` 唯一：同一 Run 的存储名不重复，附件不会互相覆盖。
    """

    __tablename__ = "run_uploads"
    __table_args__ = (
        UniqueConstraint("run_id", "stored_name", name="uq_run_uploads_run_name"),
        Index("ix_run_uploads_run", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    #: 客户端原始名（已扁平化为安全 basename，仅用于展示/审计）。
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    #: 落盘名；同名在提交时即被拒，故它在同一 Run 内唯一。
    stored_name: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String, nullable=False)
    #: staged=已入暂存区且清单已记；published=已校验并移入 inputs。
    status: Mapped[str] = mapped_column(String, nullable=False, default="staged")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


_engine: AsyncEngine | None = None
_SessionMaker: async_sessionmaker[AsyncSession] | None = None


# create_all is still used by local SQLite installations. Give it the same
# protection as Alembic; PostgreSQL production installs it through migrations
# 0010 / 0014. 版本行只 INSERT，任何 UPDATE/DELETE 都意味着改写已冻结事实。
for _history_model in (
    InvestmentAccountRevision,
    InvestmentPlanRevision,
    RunInvestmentSnapshot,
    WatchRuleRevision,
):
    for _history_action in ("UPDATE", "DELETE"):
        _history_table = _history_model.__tablename__
        event.listen(
            _history_model.__table__,
            "after_create",
            DDL(
                f"CREATE TRIGGER IF NOT EXISTS immutable_{_history_table}_{_history_action.lower()} "
                f"BEFORE {_history_action} ON {_history_table} BEGIN "
                "SELECT RAISE(ABORT, 'business history is immutable'); END"
            ).execute_if(dialect="sqlite"),
        )


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
            update(UserLLMConfig).where(UserLLMConfig.user_id == user_id).values(is_default=False)
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


class LLMCredentialError(Exception):
    """The user's default LLM config exists but its api_key cannot be decrypted.

    Distinct from "no config": a missing default legitimately falls back to the
    server's own provider, but an *undecryptable* key (SERVER_MASTER_KEY rotated
    or lost, ciphertext corrupted) used to be swallowed into the same ``None``
    — so the run silently ran on the server's credentials while its snapshot
    still claimed ``user-config`` (F07-KEY-1). Callers must treat this as
    fail-closed: refuse the submission instead of rerouting it.
    """


async def user_llm_cred_state(*, user_id: uuid.UUID) -> str:
    """Classify the user's default LLM credential without leaking the secret.

    Returns ``"ok"`` (a default config exists and decrypts), ``"none"`` (no
    default config — the server default is the legitimate route), or
    ``"error"`` (a default config exists but decryption fails). The submission
    route uses this as its gate so a master-key loss becomes a 503 instead of
    a silently rerouted run.
    """
    default = await get_default_llm_config(user_id=user_id)
    if default is None:
        return "none"
    try:
        await get_decrypted_api_key(user_id=user_id, config_id=default.id)
    except Exception:
        return "error"
    return "ok"


async def resolve_user_llm_env(*, user_id: uuid.UUID) -> dict | None:
    """Resolve a user's default LLM config into worker env vars, or None.

    Returns ``{"OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"}`` only when
    all three are present (T2.5: "all non-empty or all absent"). A partial config
    (e.g. a model with no key) yields ``None`` so the caller falls back to the
    server's own ``.env`` instead of silently injecting a half-set that would
    route a user key to the wrong endpoint. The api_key is decrypted in-process
    and handed straight to the environment — it is never logged or returned in any
    serialized form.

    An *undecryptable* key raises :class:`LLMCredentialError` rather than
    returning ``None`` (F07-KEY-1): "no config" and "config exists but the key
    is lost" are different situations, and only the former may reroute to the
    server default.
    """
    default = await get_default_llm_config(user_id=user_id)
    if default is None:
        return None
    try:
        key = await get_decrypted_api_key(user_id=user_id, config_id=default.id)
    except Exception as exc:
        raise LLMCredentialError(
            f"LLM config {default.id} exists but its api_key cannot be decrypted"
        ) from exc
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


async def ensure_session_in(
    session: AsyncSession, *, session_id: uuid.UUID, user_id: uuid.UUID, title: str
) -> Session:
    """Non-committing :func:`ensure_session` for the atomic submit path (DATA-06).

    Same ownership rule, same lazy creation — the caller's transaction decides
    when it becomes durable, so "session row + run + turn + snapshot + outbox"
    is one all-or-nothing commit instead of four.
    """
    row = await session.get(Session, session_id, with_for_update=True)
    if row is None:
        try:
            async with session.begin_nested():
                row = Session(id=session_id, user_id=user_id, title=title)
                session.add(row)
                await session.flush()
        except IntegrityError:
            row = await session.get(Session, session_id, with_for_update=True)
    if row is None or row.user_id != user_id or row.deleted_at is not None:
        raise SessionOwnershipError(str(session_id))
    return row


async def append_turn_in(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
    role: str,
    content: str,
    run_id: uuid.UUID | None = None,
) -> Turn:
    """Non-committing :func:`append_turn` with the same ``max(seq)+1`` retry."""
    for attempt in range(_APPEND_TURN_ATTEMPTS):
        try:
            # A savepoint keeps a lost seq race from aborting the caller's whole
            # transaction: only this insert rolls back, then the retry re-reads
            # the maximum inside a fresh savepoint.
            async with session.begin_nested():
                result = await session.execute(
                    select(func.coalesce(func.max(Turn.seq), 0)).where(
                        Turn.session_id == session_id
                    )
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
                await session.flush()
            return turn
        except IntegrityError:
            if attempt == _APPEND_TURN_ATTEMPTS - 1:
                raise
    raise AssertionError("unreachable")  # pragma: no cover - loop always returns or raises


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


def add_run(
    session: AsyncSession,
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
    """Insert a run row **without committing** (DATA-05/06).

    :func:`create_run` commits on its own, which makes it impossible to put the
    Run row and its business snapshot in one transaction: a snapshot that failed
    to freeze would leave a queued Run behind. This variant lets the caller own
    the transaction boundary so "Run + 快照"要么一起生效，要么一起消失。
    """
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
        result = await session.execute(select(Run).where(Run.status.in_(ACTIVE_RUN_STATUSES)))
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
        # DATA-07 closes the source Run before asking its worker to stop. A
        # delayed/foreign-process completion must not resurrect that Run as
        # completed or failed after the input request is already visible.
        if row.status == "stopped" and row.stopped_by == "input_required":
            if final_answer is not None and row.final_answer is None:
                row.final_answer = final_answer
            if row.finished_at is None:
                row.finished_at = datetime.now(UTC)
            await session.commit()
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
            (await session.execute(select(Artifact).where(Artifact.run_id == run_id)))
            .scalars()
            .all()
        )
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
                (
                    await session.execute(
                        select(ControlRecord).where(
                            ControlRecord.kind == kind,
                            ControlRecord.external_id == external_id,
                        )
                    )
                )
                .scalars()
                .first()
            )
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
            (
                await session.execute(
                    select(ControlRecord).where(
                        ControlRecord.kind == kind,
                        ControlRecord.external_id == external_id,
                    )
                )
            )
            .scalars()
            .first()
        )


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
                (
                    await session.execute(
                        select(ControlRecord).where(
                            ControlRecord.kind == kind,
                            ControlRecord.external_id == external_id,
                        )
                    )
                )
                .scalars()
                .first()
            )
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
            (await session.execute(select(ControlRecord).where(ControlRecord.run_id == run_id)))
            .scalars()
            .all()
        )
        closed = 0
        for row in rows:
            if not control_is_open(row):
                continue
            row.status = STEER_DROPPED if row.kind == CONTROL_KIND_STEER else APPROVAL_ABANDONED
            row.detail_json = {**(row.detail_json or {}), "closed_by": closed_by}
            row.resolved_at = datetime.now(UTC)
            closed += 1
        if closed:
            await session.commit()
        return closed
