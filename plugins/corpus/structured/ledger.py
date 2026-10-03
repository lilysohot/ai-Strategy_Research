"""Durable planning, attempt reservation, replay, execution, and read-only audit.

This is the only ledger for the structured role-isolation pilot.  Every model
request is reserved in SQLite before I/O; deterministic work has no attempt.
The file store used here is deliberately limited to immutable execution objects.
Semantic publication remains the responsibility of ``structured.store``.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import sqlite3
import tempfile
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal, Never, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from plugins.corpus.claims import LlmCallError, LlmResponse
from plugins.corpus.evidence_pipeline import CLAIMS_PROSE_PROTOCOL, CLAIMS_TABLE_PROTOCOL
from plugins.corpus.material_semantics import (
    MATERIAL_ITEMS_VALIDATION_VERSION,
    MATERIAL_RELATION_JSONL_VERSION,
    MATERIAL_SLOT_JSONL_VERSION,
    RELATION_CANDIDATE_RULE_VERSION,
    MaterialRun,
)
from plugins.corpus.structured.adapter import ExtractionAdapter, TransportFactory
from plugins.corpus.structured.config import (
    ExtractionConfig,
    ExtractionConfigError,
    RoleBinding,
    canonical_hash,
)
from plugins.corpus.structured.roles import (
    ROUTING_RULE_VERSION,
    RoleArtifact,
    RoleExecution,
    RoleRequest,
    RoleRoutingPlan,
    execute_claims_role,
    execute_material_items_role,
    execute_material_relations_role,
    route_snapshot,
)
from plugins.corpus.structured.snapshot import EvidenceSnapshot

PLAN_SCHEMA_VERSION = "corpus-batch-plan-v1"
LEDGER_SCHEMA_VERSION = "corpus-execution-ledger-v1"
REPLAY_SCHEMA_VERSION = "corpus-replay-response-v1"
DB_SCHEMA_VERSION = 1
STORE_ROOT_ENV = "CORPUS_STRUCTURED_ROOT"

Role = Literal["claims", "material_items", "material_relations"]
ExecutionStatus = Literal[
    "planned",
    "ready",
    "reserved",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "deferred",
    "outcome_unknown",
    "blocked",
]

_TERMINAL = {"succeeded", "failed", "cancelled", "outcome_unknown"}
_DIAGNOSTIC_KEYS = {
    "adapter_version",
    "attempt_id",
    "attempts",
    "completion_tokens",
    "content_chars",
    "cost",
    "duration_ms",
    "error_code",
    "error_type",
    "execution_status",
    "finish_reason",
    "http_status",
    "model",
    "profile_sha256",
    "prompt_tokens",
    "protocol",
    "protocol_status",
    "provider",
    "reasoning_tokens",
    "request_model",
    "request_sha256",
    "response_model",
    "role",
    "role_profile_sha256",
    "total_tokens",
    "usage",
}
_EXIT_CODES = {
    "CS_INPUT_INVALID": 2,
    "CS_SCHEMA_UNSUPPORTED": 2,
    "CS_PROTOCOL_UNSUPPORTED": 2,
    "CS_CONFIG_MISSING": 3,
    "CS_STORE_ROOT_REQUIRED": 3,
    "CS_PATH_OUTSIDE_ROOT": 3,
    "CS_BUDGET_EXHAUSTED": 4,
    "CS_DEPENDENCY_NOT_READY": 4,
    "CS_CONTEXT_INCOMPLETE": 4,
    "CS_NOT_FOUND": 5,
    "CS_ARTIFACT_CORRUPT": 5,
    "CS_OUTCOME_UNKNOWN": 6,
}


class StructuredExecutionError(RuntimeError):
    """Bounded public error with a contract error code and no provider secrets."""

    def __init__(self, code: str, reason: str) -> None:
        self.code = code
        self.reason = reason
        self.exit_code = _EXIT_CODES.get(code, 2)
        super().__init__(f"{code}: {reason}")


class FrozenRoleProfile(BaseModel):
    """Credential-free profile identity captured by a plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Role
    protocol: str
    configured: bool
    provider: str | None
    model: str | None
    base_url: str | None
    credential_ref: str | None
    adapter_version: str | None
    request_options: dict[str, Any] | None
    profile_sha256: str
    role_profile_sha256: str


class PlannedTask(BaseModel):
    """Stable initial or derived logical task."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str
    logical_key: str
    role: Role
    protocol: str
    method: Literal["deterministic", "model"]
    scoped_unit_ids: tuple[str, ...]
    input_sha256: str
    profile_sha256: str
    role_profile_sha256: str
    max_attempts: int = Field(ge=0)
    dependency_task_ids: tuple[str, ...] = ()
    deadline_epoch: float | None = None
    derived: bool = False
    endpoint_item_ids: tuple[str, ...] = ()


class RelationPlan(BaseModel):
    """Frozen rule and capacity for appending relation work after items validation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = True
    rule_version: Literal["material-relation-candidates-v1"] = RELATION_CANDIDATE_RULE_VERSION
    items_validation_version: Literal["material-items-validation-v1"] = (
        MATERIAL_ITEMS_VALIDATION_VERSION
    )
    max_tasks: int = Field(default=1, ge=0)
    max_attempts: int = Field(default=0, ge=0)


class BatchPlan(BaseModel):
    """Self-contained immutable plan used by execute and replay in another process."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["corpus-batch-plan-v1"] = PLAN_SCHEMA_VERSION
    batch_id: str
    plan_sha256: str
    snapshot: EvidenceSnapshot
    routing: RoleRoutingPlan
    routing_sha256: str
    tasks: tuple[PlannedTask, ...]
    profiles: tuple[FrozenRoleProfile, ...]
    max_attempts: int = Field(ge=0)
    role_max_attempts: dict[Role, int]
    currency: str | None = None
    relations: RelationPlan

    def verify_identity(self) -> None:
        self.snapshot.verify_identity()
        if set(self.role_max_attempts) != {
            "claims",
            "material_items",
            "material_relations",
        } or any(type(value) is not int or value < 0 for value in self.role_max_attempts.values()):
            raise StructuredExecutionError("CS_INPUT_INVALID", "invalid_role_budget")
        payload = self.model_dump(mode="json", exclude={"batch_id", "plan_sha256"})
        expected = canonical_hash(payload)
        if self.plan_sha256 != expected or self.batch_id != f"batch:{expected[7:]}":
            raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "plan_identity_mismatch")
        if (
            self.routing.snapshot_id != self.snapshot.snapshot_id
            or self.routing_sha256 != canonical_hash(self.routing.model_dump(mode="json"))
        ):
            raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "plan_routing_mismatch")
        ids = {task.task_id for task in self.tasks}
        if len(ids) != len(self.tasks) or any(
            dependency not in ids for task in self.tasks for dependency in task.dependency_task_ids
        ):
            raise StructuredExecutionError("CS_INPUT_INVALID", "invalid_initial_task_graph")
        expected_protocols = {
            "claims": CLAIMS_PROSE_PROTOCOL,
            "material_items": MATERIAL_SLOT_JSONL_VERSION,
            "material_relations": MATERIAL_RELATION_JSONL_VERSION,
        }
        profiles = {profile.role: profile for profile in self.profiles}
        if len(profiles) != len(self.profiles) or set(profiles) != set(expected_protocols):
            raise StructuredExecutionError("CS_INPUT_INVALID", "invalid_role_profiles")
        if any(profile.protocol != expected_protocols[role] for role, profile in profiles.items()):
            raise StructuredExecutionError("CS_INPUT_INVALID", "invalid_role_profile_protocol")
        expected_routes: set[tuple[str, str, str, tuple[str, ...]]] = set()
        for protocol in (CLAIMS_TABLE_PROTOCOL, CLAIMS_PROSE_PROTOCOL):
            scope = self.routing.claims_scope(protocol)
            if scope:
                expected_routes.add(
                    (
                        "claims",
                        protocol,
                        "deterministic" if protocol == CLAIMS_TABLE_PROTOCOL else "model",
                        scope,
                    )
                )
        if self.routing.material_items_scope:
            expected_routes.add(
                (
                    "material_items",
                    MATERIAL_SLOT_JSONL_VERSION,
                    "model",
                    self.routing.material_items_scope,
                )
            )
        actual_routes = {
            (task.role, task.protocol, task.method, task.scoped_unit_ids) for task in self.tasks
        }
        if actual_routes != expected_routes or any(
            task.derived or task.dependency_task_ids or task.endpoint_item_ids
            for task in self.tasks
        ):
            raise StructuredExecutionError("CS_INPUT_INVALID", "initial_tasks_do_not_match_routing")
        for task in self.tasks:
            profile = profiles[task.role]
            identity = {
                "snapshot_id": self.snapshot.snapshot_id,
                "role": task.role,
                "protocol": task.protocol,
                "method": task.method,
                "scope": task.scoped_unit_ids,
                "profile": profile.role_profile_sha256,
                "routing_rule_version": ROUTING_RULE_VERSION,
                "deadline_epoch": task.deadline_epoch,
            }
            logical_key = canonical_hash(identity)
            expected_attempts = self.role_max_attempts[task.role] if task.method == "model" else 0
            if (
                task.logical_key != logical_key
                or task.input_sha256 != logical_key
                or task.task_id != f"task:{logical_key[7:]}"
                or task.profile_sha256 != profile.profile_sha256
                or task.role_profile_sha256 != profile.role_profile_sha256
                or task.max_attempts != expected_attempts
            ):
                raise StructuredExecutionError("CS_INPUT_INVALID", "invalid_initial_task_identity")


class ReplayResponse(BaseModel):
    """One explicit fake/replay response; task and sequence select it exactly once."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["corpus-replay-response-v1"] = REPLAY_SCHEMA_VERSION
    task_id: str | None = None
    parent_task_id: str | None = None
    sequence: int = Field(ge=1)
    role: Role
    protocol: str
    request_sha256: str | None = None
    content: str
    diagnostics: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_selector(self) -> ReplayResponse:
        if bool(self.task_id) == bool(self.parent_task_id):
            raise ValueError("exactly one replay task selector is required")
        return self


class LedgerBudget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_attempts: int
    reserved_attempts: int
    actual_attempts: int
    currency: str | None


class LedgerTask(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str
    role: Role
    method: Literal["deterministic", "model"]
    input_sha256: str
    profile_sha256: str
    execution_status: ExecutionStatus
    protocol_status: Literal["not_checked", "valid", "invalid", "unsupported"]
    quality_status: Literal["unassessed", "accepted", "review_required", "rejected"]
    publication_status: Literal["unpublished", "candidate", "published", "withdrawn", "superseded"]
    context_status: Literal["complete", "partial", "missing", "ambiguous", "budget_exceeded"]
    dependency_task_ids: tuple[str, ...]
    artifact_sha256: str | None = None
    error_codes: tuple[str, ...]


class LedgerAttempt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    attempt_id: str
    task_id: str
    attempt_number: int
    execution_status: ExecutionStatus
    request_sha256: str
    response_sha256: str | None = None
    provider: str
    request_model: str
    response_model: str | None
    usage: dict[str, Any] | None
    cost: dict[str, Any] | None


class ExecutionLedger(BaseModel):
    """Exact v1 contract envelope exported by the read-only check."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["corpus-execution-ledger-v1"] = LEDGER_SCHEMA_VERSION
    batch_id: str
    plan_sha256: str
    snapshot_id: str
    budget: LedgerBudget
    tasks: tuple[LedgerTask, ...]
    attempts: tuple[LedgerAttempt, ...]


class CostSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    model: str
    currency: str | None
    kind: str | None
    price_version: str | None
    known_amount: float
    known_calls: int
    unknown_calls: int


class RoleBudgetSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_attempts: int
    reserved_attempts: int


class BatchCheck(BaseModel):
    """Read-only structural audit; it never substitutes for semantic quality review."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ledger: ExecutionLedger
    plan_consistent: bool
    findings: tuple[str, ...]
    derivations: dict[str, str]
    role_budgets: dict[Role, RoleBudgetSummary]
    cost_summary: tuple[CostSummary, ...]


Checkpoint = Callable[[str], None]


def _noop_checkpoint(_name: str) -> None:
    return None


def _safe_diagnostics(value: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only JSON-safe, credential-free fields used for audit and costing."""
    result: dict[str, Any] = {}
    for key in _DIAGNOSTIC_KEYS & value.keys():
        item = value[key]
        try:
            json.dumps(item, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            continue
        result[key] = item
    return result


def _context_for_units(snapshot: EvidenceSnapshot, unit_ids: tuple[str, ...]) -> str:
    statuses = [
        str(unit.metadata.get("context_status", "complete"))
        for unit in snapshot.units
        if unit.unit_id in unit_ids
    ]
    for status in ("missing", "ambiguous", "budget_exceeded", "partial"):
        if status in statuses:
            return status
    return "complete" if statuses else "missing"


def _frozen_profiles(
    config: ExtractionConfig | None,
    role_configs: Mapping[Role, ExtractionConfig] | None = None,
) -> tuple[FrozenRoleProfile, ...]:
    result: list[FrozenRoleProfile] = []
    for role, protocol in (
        ("claims", CLAIMS_PROSE_PROTOCOL),
        ("material_items", MATERIAL_SLOT_JSONL_VERSION),
        ("material_relations", MATERIAL_RELATION_JSONL_VERSION),
    ):
        selected = (role_configs or {}).get(cast(Role, role), config)
        if selected is not None and selected.configured:
            binding = RoleBinding(role=cast(Role, role), protocol=protocol, config=selected)
            profile = selected.require_profile()
            result.append(
                FrozenRoleProfile(
                    role=cast(Role, role),
                    protocol=protocol,
                    configured=True,
                    provider=profile.provider,
                    model=profile.model,
                    base_url=profile.base_url,
                    credential_ref=profile.credential_ref,
                    adapter_version=profile.adapter_version,
                    request_options=profile.options.model_dump(mode="json"),
                    profile_sha256=profile.fingerprint,
                    role_profile_sha256=binding.fingerprint,
                )
            )
        else:
            profile_hash = canonical_hash({"configuration": "missing", "role": role})
            result.append(
                FrozenRoleProfile(
                    role=cast(Role, role),
                    protocol=protocol,
                    configured=False,
                    provider=None,
                    model=None,
                    base_url=None,
                    credential_ref=None,
                    adapter_version=None,
                    request_options=None,
                    profile_sha256=profile_hash,
                    role_profile_sha256=canonical_hash(
                        {"profile": profile_hash, "protocol": protocol, "role": role}
                    ),
                )
            )
    return tuple(result)


def _planned_task(
    *,
    snapshot: EvidenceSnapshot,
    role: Role,
    protocol: str,
    method: Literal["deterministic", "model"],
    scope: tuple[str, ...],
    profile: FrozenRoleProfile,
    max_attempts: int,
    deadline_epoch: float | None,
) -> PlannedTask:
    identity = {
        "snapshot_id": snapshot.snapshot_id,
        "role": role,
        "protocol": protocol,
        "method": method,
        "scope": scope,
        "profile": profile.role_profile_sha256,
        "routing_rule_version": ROUTING_RULE_VERSION,
        "deadline_epoch": deadline_epoch,
    }
    logical_key = canonical_hash(identity)
    return PlannedTask(
        task_id=f"task:{logical_key[7:]}",
        logical_key=logical_key,
        role=role,
        protocol=protocol,
        method=method,
        scoped_unit_ids=scope,
        input_sha256=canonical_hash(identity),
        profile_sha256=profile.profile_sha256,
        role_profile_sha256=profile.role_profile_sha256,
        max_attempts=max_attempts if method == "model" else 0,
        deadline_epoch=deadline_epoch,
    )


def plan_batch(
    snapshot: EvidenceSnapshot,
    *,
    config: ExtractionConfig | None = None,
    role_configs: Mapping[Role, ExtractionConfig] | None = None,
    max_attempts: int = 0,
    role_max_attempts: Mapping[Role, int] | None = None,
    currency: str | None = None,
    relations_enabled: bool = True,
    max_relation_tasks: int = 1,
    max_relation_attempts: int | None = None,
    deadline_epoch: float | None = None,
) -> BatchPlan:
    """Freeze deterministic routing, profiles, budgets, and relation derivation; no I/O."""
    snapshot.verify_identity()
    if type(max_attempts) is not int or max_attempts < 0:
        raise StructuredExecutionError("CS_INPUT_INVALID", "invalid_batch_budget")
    if type(max_relation_tasks) is not int or max_relation_tasks < 0:
        raise StructuredExecutionError("CS_INPUT_INVALID", "invalid_relation_task_limit")
    if deadline_epoch is not None:
        if (
            isinstance(deadline_epoch, bool)
            or not isinstance(deadline_epoch, (int, float))
            or not math.isfinite(deadline_epoch)
        ):
            raise StructuredExecutionError("CS_INPUT_INVALID", "invalid_deadline")
        deadline_epoch = float(deadline_epoch)
    budgets: dict[Role, int] = {
        "claims": max_attempts,
        "material_items": max_attempts,
        "material_relations": max_attempts,
    }
    if role_max_attempts is not None:
        if set(role_max_attempts) - set(budgets):
            raise StructuredExecutionError("CS_INPUT_INVALID", "unknown_role_budget")
        budgets.update(role_max_attempts)
    if any(type(value) is not int or value < 0 for value in budgets.values()):
        raise StructuredExecutionError("CS_INPUT_INVALID", "invalid_role_budget")
    relation_attempts = (
        budgets["material_relations"] if max_relation_attempts is None else max_relation_attempts
    )
    if type(relation_attempts) is not int or relation_attempts < 0:
        raise StructuredExecutionError("CS_INPUT_INVALID", "invalid_relation_attempt_limit")

    routing = route_snapshot(snapshot)
    if role_configs is not None and set(role_configs) - {
        "claims",
        "material_items",
        "material_relations",
    }:
        raise StructuredExecutionError("CS_INPUT_INVALID", "unknown_role_config")
    profiles = _frozen_profiles(config, role_configs)
    by_role = {profile.role: profile for profile in profiles}
    tasks: list[PlannedTask] = []
    for protocol in (CLAIMS_TABLE_PROTOCOL, CLAIMS_PROSE_PROTOCOL):
        scope = routing.claims_scope(protocol)
        if scope:
            tasks.append(
                _planned_task(
                    snapshot=snapshot,
                    role="claims",
                    protocol=protocol,
                    method="deterministic" if protocol == CLAIMS_TABLE_PROTOCOL else "model",
                    scope=scope,
                    profile=by_role["claims"],
                    max_attempts=budgets["claims"],
                    deadline_epoch=deadline_epoch,
                )
            )
    if routing.material_items_scope:
        tasks.append(
            _planned_task(
                snapshot=snapshot,
                role="material_items",
                protocol=MATERIAL_SLOT_JSONL_VERSION,
                method="model",
                scope=routing.material_items_scope,
                profile=by_role["material_items"],
                max_attempts=budgets["material_items"],
                deadline_epoch=deadline_epoch,
            )
        )
    base = BatchPlan(
        batch_id="batch:pending",
        plan_sha256="sha256:" + "0" * 64,
        snapshot=snapshot,
        routing=routing,
        routing_sha256=canonical_hash(routing.model_dump(mode="json")),
        tasks=tuple(tasks),
        profiles=profiles,
        max_attempts=max_attempts,
        role_max_attempts=budgets,
        currency=currency,
        relations=RelationPlan(
            enabled=relations_enabled,
            max_tasks=max_relation_tasks,
            max_attempts=relation_attempts,
        ),
    )
    identity = base.model_dump(mode="json", exclude={"batch_id", "plan_sha256"})
    plan_hash = canonical_hash(identity)
    plan = base.model_copy(update={"batch_id": f"batch:{plan_hash[7:]}", "plan_sha256": plan_hash})
    plan.verify_identity()
    return plan


def _store_root(value: str | Path | None, *, write: bool) -> Path:
    raw = value if value is not None else os.environ.get(STORE_ROOT_ENV)
    if raw is None or not str(raw).strip():
        raise StructuredExecutionError("CS_STORE_ROOT_REQUIRED", "structured_root_missing")
    path = Path(raw)
    if not path.is_absolute():
        raise StructuredExecutionError("CS_PATH_OUTSIDE_ROOT", "structured_root_not_absolute")
    if path.exists() and path.is_symlink():
        raise StructuredExecutionError("CS_PATH_OUTSIDE_ROOT", "structured_root_is_symlink")
    resolved = path.resolve(strict=False)
    if write:
        try:
            resolved.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not resolved.is_dir():
                raise OSError
        except OSError as exc:
            raise StructuredExecutionError(
                "CS_STORE_ROOT_REQUIRED", "structured_root_unwritable"
            ) from exc
    elif not resolved.is_dir():
        raise StructuredExecutionError("CS_NOT_FOUND", "structured_root_not_found")
    return resolved


def _database_path(root: Path) -> Path:
    return _safe_path(root, root / "index" / "structured.sqlite3", "database_path_escape")


def _safe_path(root: Path, path: Path, reason: str) -> Path:
    """Keep a path below the resolved root and reject symlinked descendants."""
    resolved = path.resolve(strict=False)
    if resolved != root and root not in resolved.parents:
        raise StructuredExecutionError("CS_PATH_OUTSIDE_ROOT", reason)
    current = path
    while current != root:
        if current.is_symlink():
            raise StructuredExecutionError("CS_PATH_OUTSIDE_ROOT", reason)
        current = current.parent
    return path


def _writer(root: Path) -> sqlite3.Connection:
    index = _safe_path(root, root / "index", "database_path_escape")
    index.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = _database_path(root)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=10000")
        _create_schema(connection)
    except StructuredExecutionError:
        if connection is not None:
            connection.close()
        raise
    except sqlite3.DatabaseError as exc:
        if connection is not None:
            connection.close()
        raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "structured_index_invalid") from exc
    with suppress(OSError):
        os.chmod(path, 0o600)
    return connection


def _reader(root: Path) -> sqlite3.Connection:
    path = _database_path(root)
    if not path.is_file() or path.is_symlink():
        raise StructuredExecutionError("CS_NOT_FOUND", "structured_index_not_found")
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            path.as_uri() + "?mode=ro", uri=True, timeout=10, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA foreign_keys=ON")
        row = connection.execute(
            "SELECT value FROM ledger_metadata WHERE key='schema_version'"
        ).fetchone()
    except sqlite3.DatabaseError as exc:
        if connection is not None:
            with suppress(Exception):
                connection.close()
        raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "structured_index_invalid") from exc
    assert connection is not None
    if row is None or row[0] != str(DB_SCHEMA_VERSION):
        connection.close()
        raise StructuredExecutionError("CS_SCHEMA_UNSUPPORTED", "ledger_schema_version")
    return connection


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS ledger_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS batches (
            batch_id TEXT PRIMARY KEY,
            plan_sha256 TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            plan_json TEXT NOT NULL,
            max_attempts INTEGER NOT NULL CHECK(max_attempts >= 0),
            reserved_attempts INTEGER NOT NULL DEFAULT 0 CHECK(reserved_attempts >= 0),
            actual_attempts INTEGER NOT NULL DEFAULT 0 CHECK(actual_attempts >= 0),
            currency TEXT,
            cancelled INTEGER NOT NULL DEFAULT 0 CHECK(cancelled IN (0, 1))
        );
        CREATE TABLE IF NOT EXISTS role_budgets (
            batch_id TEXT NOT NULL REFERENCES batches(batch_id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            max_attempts INTEGER NOT NULL CHECK(max_attempts >= 0),
            reserved_attempts INTEGER NOT NULL DEFAULT 0 CHECK(reserved_attempts >= 0),
            PRIMARY KEY(batch_id, role)
        );
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL REFERENCES batches(batch_id) ON DELETE CASCADE,
            logical_key TEXT NOT NULL,
            role TEXT NOT NULL,
            protocol TEXT NOT NULL,
            method TEXT NOT NULL,
            input_sha256 TEXT NOT NULL,
            profile_sha256 TEXT NOT NULL,
            role_profile_sha256 TEXT NOT NULL,
            execution_status TEXT NOT NULL,
            protocol_status TEXT NOT NULL,
            quality_status TEXT NOT NULL,
            publication_status TEXT NOT NULL,
            context_status TEXT NOT NULL,
            dependency_task_ids TEXT NOT NULL,
            scoped_unit_ids TEXT NOT NULL,
            endpoint_item_ids TEXT NOT NULL,
            max_attempts INTEGER NOT NULL,
            deadline_epoch REAL,
            derived INTEGER NOT NULL CHECK(derived IN (0, 1)),
            artifact_sha256 TEXT,
            artifact_id TEXT,
            payload_sha256 TEXT,
            payload_object_sha256 TEXT,
            error_codes TEXT NOT NULL,
            reason_codes TEXT NOT NULL,
            UNIQUE(batch_id, logical_key)
        );
        CREATE TABLE IF NOT EXISTS attempts (
            attempt_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
            attempt_number INTEGER NOT NULL CHECK(attempt_number >= 1),
            execution_status TEXT NOT NULL,
            role_request_sha256 TEXT NOT NULL,
            request_sha256 TEXT NOT NULL,
            response_sha256 TEXT,
            response_object_sha256 TEXT,
            provider TEXT NOT NULL,
            request_model TEXT NOT NULL,
            response_model TEXT,
            profile_sha256 TEXT NOT NULL,
            role_profile_sha256 TEXT NOT NULL,
            usage TEXT,
            cost TEXT,
            diagnostics TEXT NOT NULL,
            error_code TEXT,
            UNIQUE(task_id, attempt_number),
            UNIQUE(task_id, role_request_sha256)
        );
        CREATE TABLE IF NOT EXISTS derivations (
            parent_task_id TEXT PRIMARY KEY REFERENCES tasks(task_id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            derived_task_id TEXT REFERENCES tasks(task_id),
            reason_code TEXT
        );
        """
    )
    row = connection.execute(
        "SELECT value FROM ledger_metadata WHERE key='schema_version'"
    ).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO ledger_metadata(key, value) VALUES ('schema_version', ?)",
            (str(DB_SCHEMA_VERSION),),
        )
    elif row[0] != str(DB_SCHEMA_VERSION):
        raise StructuredExecutionError("CS_SCHEMA_UNSUPPORTED", "ledger_schema_version")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _write_object(root: Path, value: object) -> str:
    raw = _json(value).encode("utf-8")
    object_sha = _hash_bytes(raw)
    digest = object_sha[7:]
    directory = _safe_path(root, root / "objects" / "sha256" / digest[:2], "object_path_escape")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = _safe_path(root, directory / f"{digest}.json", "object_path_escape")
    if path.exists():
        if path.read_bytes() != raw:
            raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "immutable_object_collision")
        return object_sha
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", suffix=".json", dir=directory)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary)
    return object_sha


def _read_object(root: Path, object_sha: str) -> Any:
    if not object_sha.startswith("sha256:") or len(object_sha) != 71:
        raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "invalid_object_hash")
    digest = object_sha[7:]
    path = _safe_path(
        root,
        root / "objects" / "sha256" / digest[:2] / f"{digest}.json",
        "object_path_escape",
    )
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise StructuredExecutionError("CS_NOT_FOUND", "object_not_found") from exc
    if _hash_bytes(raw) != object_sha:
        raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "object_hash_mismatch")
    try:
        return json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "object_json_invalid") from exc


class ExecutionJournal:
    """SQLite owner for one writer process; transactions are safe across processes."""

    def __init__(self, root: Path, connection: sqlite3.Connection, plan: BatchPlan) -> None:
        self.root = root
        self.connection = connection
        self.plan = plan

    @classmethod
    def open(cls, plan: BatchPlan, store_root: str | Path | None) -> ExecutionJournal:
        plan.verify_identity()
        root = _store_root(store_root, write=True)
        journal = cls(root, _writer(root), plan)
        journal._initialize()
        return journal

    def close(self) -> None:
        self.connection.close()

    def _initialize(self) -> None:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT plan_sha256, snapshot_id FROM batches WHERE batch_id=?",
                (self.plan.batch_id,),
            ).fetchone()
            if row is None:
                self.connection.execute(
                    "INSERT INTO batches(batch_id, plan_sha256, snapshot_id, plan_json, "
                    "max_attempts, currency) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        self.plan.batch_id,
                        self.plan.plan_sha256,
                        self.plan.snapshot.snapshot_id,
                        self.plan.model_dump_json(),
                        self.plan.max_attempts,
                        self.plan.currency,
                    ),
                )
                for role, limit in self.plan.role_max_attempts.items():
                    self.connection.execute(
                        "INSERT INTO role_budgets(batch_id, role, max_attempts) VALUES (?, ?, ?)",
                        (self.plan.batch_id, role, limit),
                    )
                for task in self.plan.tasks:
                    self._insert_task(task)
                    if task.role == "material_items":
                        self.connection.execute(
                            "INSERT INTO derivations(parent_task_id, status) VALUES (?, ?)",
                            (
                                task.task_id,
                                "waiting" if self.plan.relations.enabled else "disabled",
                            ),
                        )
            elif (row["plan_sha256"], row["snapshot_id"]) != (
                self.plan.plan_sha256,
                self.plan.snapshot.snapshot_id,
            ):
                raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "batch_plan_mismatch")
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def _insert_task(self, task: PlannedTask) -> None:
        context = _context_for_units(self.plan.snapshot, task.scoped_unit_ids)
        self.connection.execute(
            "INSERT INTO tasks(task_id, batch_id, logical_key, role, protocol, method, "
            "input_sha256, profile_sha256, role_profile_sha256, execution_status, "
            "protocol_status, quality_status, publication_status, context_status, "
            "dependency_task_ids, scoped_unit_ids, endpoint_item_ids, max_attempts, "
            "deadline_epoch, derived, error_codes, reason_codes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', 'not_checked', 'unassessed', "
            "'unpublished', ?, ?, ?, ?, ?, ?, ?, '[]', '[]')",
            (
                task.task_id,
                self.plan.batch_id,
                task.logical_key,
                task.role,
                task.protocol,
                task.method,
                task.input_sha256,
                task.profile_sha256,
                task.role_profile_sha256,
                context,
                _json(task.dependency_task_ids),
                _json(task.scoped_unit_ids),
                _json(task.endpoint_item_ids),
                task.max_attempts,
                task.deadline_epoch,
                int(task.derived),
            ),
        )

    def recover_pending(self) -> int:
        """Conservatively freeze interrupted sends; never make them retryable."""
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            rows = self.connection.execute(
                "SELECT attempt_id, task_id FROM attempts WHERE execution_status IN ('reserved','running')"
            ).fetchall()
            for row in rows:
                self.connection.execute(
                    "UPDATE attempts SET execution_status='outcome_unknown', "
                    "error_code='CS_OUTCOME_UNKNOWN' WHERE attempt_id=?",
                    (row["attempt_id"],),
                )
                self.connection.execute(
                    "UPDATE tasks SET execution_status='outcome_unknown', "
                    "error_codes='[\"CS_OUTCOME_UNKNOWN\"]' WHERE task_id=?",
                    (row["task_id"],),
                )
            self.connection.execute("COMMIT")
            return len(rows)
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def verify_references(self) -> None:
        """Fail closed on any referenced immutable object before resuming work."""
        rows = self.connection.execute(
            "SELECT response_object_sha256 FROM attempts WHERE response_object_sha256 IS NOT NULL"
        ).fetchall()
        rows += self.connection.execute(
            "SELECT artifact_sha256 FROM tasks WHERE artifact_sha256 IS NOT NULL"
        ).fetchall()
        rows += self.connection.execute(
            "SELECT payload_object_sha256 FROM tasks WHERE payload_object_sha256 IS NOT NULL"
        ).fetchall()
        for row in rows:
            _read_object(self.root, row[0])

    def task_status(self, task_id: str) -> str:
        row = self.connection.execute(
            "SELECT execution_status FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone()
        if row is None:
            raise StructuredExecutionError("CS_NOT_FOUND", "task_not_found")
        return str(row[0])

    def parent_task_id(self, task_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT dependency_task_ids, derived FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone()
        if row is None:
            raise StructuredExecutionError("CS_NOT_FOUND", "task_not_found")
        dependencies = tuple(json.loads(row["dependency_task_ids"]))
        return dependencies[0] if row["derived"] and len(dependencies) == 1 else None

    def reserve_attempt(
        self,
        request: RoleRequest,
        *,
        request_sha256: str,
        provider: str,
        request_model: str,
        profile_sha256: str,
        role_profile_sha256: str,
    ) -> str:
        """Atomically check batch, role and task budgets and reserve one attempt."""
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            batch = self.connection.execute(
                "SELECT max_attempts, reserved_attempts, cancelled FROM batches WHERE batch_id=?",
                (self.plan.batch_id,),
            ).fetchone()
            task = self.connection.execute(
                "SELECT role, max_attempts, execution_status, profile_sha256, "
                "role_profile_sha256, deadline_epoch FROM tasks WHERE task_id=?",
                (request.task_id,),
            ).fetchone()
            role_budget = self.connection.execute(
                "SELECT max_attempts, reserved_attempts FROM role_budgets "
                "WHERE batch_id=? AND role=?",
                (self.plan.batch_id, request.role),
            ).fetchone()
            if batch is None or task is None or role_budget is None:
                raise StructuredExecutionError("CS_NOT_FOUND", "reservation_scope_not_found")
            if (
                task["role"] != request.role
                or task["profile_sha256"] != profile_sha256
                or task["role_profile_sha256"] != role_profile_sha256
            ):
                raise StructuredExecutionError("CS_INPUT_INVALID", "request_profile_binding")
            if batch["cancelled"]:
                raise StructuredExecutionError("CS_DEPENDENCY_NOT_READY", "batch_cancelled")
            if task["deadline_epoch"] is not None and time.time() >= task["deadline_epoch"]:
                self.connection.execute(
                    "UPDATE tasks SET execution_status='cancelled', "
                    "reason_codes='[\"deadline_exceeded\"]' WHERE task_id=?",
                    (request.task_id,),
                )
                raise StructuredExecutionError("CS_DEPENDENCY_NOT_READY", "deadline_exceeded")
            if task["execution_status"] in _TERMINAL:
                raise StructuredExecutionError("CS_DEPENDENCY_NOT_READY", "task_terminal")
            duplicate = self.connection.execute(
                "SELECT attempt_id FROM attempts WHERE task_id=? AND role_request_sha256=?",
                (request.task_id, request.request_sha256),
            ).fetchone()
            if duplicate is not None:
                raise StructuredExecutionError("CS_INPUT_INVALID", "duplicate_request_attempt")
            task_count = self.connection.execute(
                "SELECT count(*) FROM attempts WHERE task_id=?", (request.task_id,)
            ).fetchone()[0]
            if (
                batch["reserved_attempts"] >= batch["max_attempts"]
                or role_budget["reserved_attempts"] >= role_budget["max_attempts"]
                or task_count >= task["max_attempts"]
            ):
                raise StructuredExecutionError("CS_BUDGET_EXHAUSTED", "attempt_budget_exhausted")
            attempt_number = task_count + 1
            attempt_id = (
                "attempt:"
                + canonical_hash(
                    {
                        "task_id": request.task_id,
                        "attempt_number": attempt_number,
                        "request_sha256": request_sha256,
                    }
                )[7:]
            )
            self.connection.execute(
                "INSERT INTO attempts(attempt_id, task_id, attempt_number, execution_status, "
                "role_request_sha256, request_sha256, provider, request_model, profile_sha256, "
                "role_profile_sha256, diagnostics) VALUES (?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, '{}')",
                (
                    attempt_id,
                    request.task_id,
                    attempt_number,
                    request.request_sha256,
                    request_sha256,
                    provider,
                    request_model,
                    profile_sha256,
                    role_profile_sha256,
                ),
            )
            self.connection.execute(
                "UPDATE batches SET reserved_attempts=reserved_attempts+1, "
                "actual_attempts=actual_attempts+1 WHERE batch_id=?",
                (self.plan.batch_id,),
            )
            self.connection.execute(
                "UPDATE role_budgets SET reserved_attempts=reserved_attempts+1 "
                "WHERE batch_id=? AND role=?",
                (self.plan.batch_id, request.role),
            )
            self.connection.execute(
                "UPDATE tasks SET execution_status='running' WHERE task_id=?",
                (request.task_id,),
            )
            self.connection.execute("COMMIT")
            return attempt_id
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def existing_attempt(self, request: RoleRequest) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM attempts WHERE task_id=? AND role_request_sha256=?",
            (request.task_id, request.request_sha256),
        ).fetchone()

    def complete_attempt(
        self,
        attempt_id: str,
        response: LlmResponse,
        *,
        checkpoint: Checkpoint,
    ) -> None:
        diagnostics = _safe_diagnostics(response.diagnostics)
        raw_sha = canonical_hash(str(response))
        object_sha = _write_object(
            self.root,
            {
                "schema_version": "corpus-model-response-v1",
                "content": str(response),
                "diagnostics": diagnostics,
            },
        )
        checkpoint("after_response_object")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            cursor = self.connection.execute(
                "UPDATE attempts SET execution_status='succeeded', response_sha256=?, "
                "response_object_sha256=?, response_model=?, usage=?, cost=?, diagnostics=? "
                "WHERE attempt_id=? AND execution_status='running'",
                (
                    raw_sha,
                    object_sha,
                    diagnostics.get("response_model"),
                    _json(diagnostics["usage"])
                    if isinstance(diagnostics.get("usage"), dict)
                    else None,
                    _json(diagnostics["cost"])
                    if isinstance(diagnostics.get("cost"), dict)
                    else None,
                    _json(diagnostics),
                    attempt_id,
                ),
            )
            if cursor.rowcount != 1:
                raise StructuredExecutionError("CS_OUTCOME_UNKNOWN", "attempt_not_running")
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        checkpoint("after_response_commit")

    def fail_attempt(self, attempt_id: str, diagnostics: Mapping[str, Any]) -> None:
        safe = _safe_diagnostics(diagnostics)
        status = (
            "outcome_unknown" if safe.get("execution_status") == "outcome_unknown" else "failed"
        )
        error_code = safe.get("error_code")
        if status == "outcome_unknown":
            error_code = "CS_OUTCOME_UNKNOWN"
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                "UPDATE attempts SET execution_status=?, response_model=?, usage=?, cost=?, "
                "diagnostics=?, error_code=? WHERE attempt_id=? AND execution_status='running'",
                (
                    status,
                    safe.get("response_model"),
                    _json(safe["usage"]) if isinstance(safe.get("usage"), dict) else None,
                    _json(safe["cost"]) if isinstance(safe.get("cost"), dict) else None,
                    _json(safe),
                    error_code,
                    attempt_id,
                ),
            )
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def reusable_response(self, row: sqlite3.Row) -> LlmResponse:
        status = row["execution_status"]
        if status == "succeeded" and row["response_object_sha256"]:
            value = _read_object(self.root, row["response_object_sha256"])
            if (
                not isinstance(value, dict)
                or value.get("schema_version") != "corpus-model-response-v1"
            ):
                raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "response_object_schema")
            content, diagnostics = value.get("content"), value.get("diagnostics")
            if not isinstance(content, str) or not isinstance(diagnostics, dict):
                raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "response_object_shape")
            return LlmResponse(content, diagnostics)
        diagnostics = json.loads(row["diagnostics"])
        diagnostics.setdefault("execution_status", status)
        if status == "outcome_unknown":
            diagnostics["error_code"] = "CS_OUTCOME_UNKNOWN"
        raise LlmCallError(diagnostics)

    def save_execution(self, task: PlannedTask, execution: RoleExecution) -> None:
        execution.artifact.verify_identity()
        payload = execution.payload.model_dump(mode="json")
        payload_object = _write_object(self.root, payload)
        if canonical_hash(payload) != execution.artifact.payload_sha256:
            raise StructuredExecutionError("CS_ARTIFACT_CORRUPT", "role_payload_hash_mismatch")
        artifact_payload = execution.artifact.model_dump(mode="json")
        artifact_object = _write_object(self.root, artifact_payload)
        publication = (
            "candidate" if execution.artifact.quality_status == "accepted" else "unpublished"
        )
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                "UPDATE tasks SET execution_status=?, protocol_status=?, quality_status=?, "
                "publication_status=?, context_status=?, artifact_sha256=?, artifact_id=?, "
                "payload_sha256=?, payload_object_sha256=?, error_codes=?, reason_codes=? "
                "WHERE task_id=?",
                (
                    execution.artifact.execution_status,
                    execution.artifact.protocol_status,
                    execution.artifact.quality_status,
                    publication,
                    execution.artifact.context_status,
                    artifact_object,
                    execution.artifact.artifact_id,
                    execution.artifact.payload_sha256,
                    payload_object,
                    _json(execution.artifact.error_codes),
                    _json(execution.artifact.coverage.reason_codes),
                    task.task_id,
                ),
            )
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def set_task_state(
        self,
        task_id: str,
        status: ExecutionStatus,
        *,
        error_codes: tuple[str, ...] = (),
        reasons: tuple[str, ...] = (),
    ) -> None:
        self.connection.execute(
            "UPDATE tasks SET execution_status=?, error_codes=?, reason_codes=? WHERE task_id=?",
            (status, _json(error_codes), _json(reasons), task_id),
        )

    def load_items_execution(self, task_id: str) -> RoleExecution:
        row = self.connection.execute(
            "SELECT artifact_sha256, payload_object_sha256 FROM tasks WHERE task_id=?",
            (task_id,),
        ).fetchone()
        if row is None or not row["artifact_sha256"] or not row["payload_object_sha256"]:
            raise StructuredExecutionError("CS_DEPENDENCY_NOT_READY", "items_artifact_missing")
        artifact = RoleArtifact.model_validate(_read_object(self.root, row["artifact_sha256"]))
        payload = MaterialRun.model_validate(_read_object(self.root, row["payload_object_sha256"]))
        artifact.verify_identity()
        payload.verify_identity()
        return RoleExecution(artifact=artifact, payload=payload)

    def derive_relation_task(self, parent: PlannedTask) -> PlannedTask | None:
        derivation = self.connection.execute(
            "SELECT status, derived_task_id FROM derivations WHERE parent_task_id=?",
            (parent.task_id,),
        ).fetchone()
        if derivation is None or derivation["status"] == "disabled":
            return None
        if derivation["derived_task_id"]:
            return self._task_from_row(derivation["derived_task_id"])
        row = self.connection.execute(
            "SELECT execution_status, protocol_status, quality_status, artifact_id, "
            "payload_object_sha256 FROM tasks WHERE task_id=?",
            (parent.task_id,),
        ).fetchone()
        if row is None or (
            row["execution_status"],
            row["protocol_status"],
            row["quality_status"],
        ) != ("succeeded", "valid", "accepted"):
            self.connection.execute(
                "UPDATE derivations SET status='dependency_not_ready', "
                "reason_code='CS_DEPENDENCY_NOT_READY' WHERE parent_task_id=?",
                (parent.task_id,),
            )
            return None
        items_run = MaterialRun.model_validate(
            _read_object(self.root, row["payload_object_sha256"])
        )
        endpoints = tuple(item.item_id for item in items_run.understanding.items)
        profile = next(
            profile for profile in self.plan.profiles if profile.role == "material_relations"
        )
        identity = {
            "snapshot_id": self.plan.snapshot.snapshot_id,
            "parent_task_id": parent.task_id,
            "items_artifact_id": row["artifact_id"],
            "items_run_id": items_run.run_id,
            "endpoint_item_ids": sorted(endpoints),
            "rule_version": self.plan.relations.rule_version,
            "items_validation_version": self.plan.relations.items_validation_version,
            "profile": profile.role_profile_sha256,
        }
        logical = canonical_hash(identity)
        task = PlannedTask(
            task_id=f"task:{logical[7:]}",
            logical_key=logical,
            role="material_relations",
            protocol=MATERIAL_RELATION_JSONL_VERSION,
            method="model",
            scoped_unit_ids=parent.scoped_unit_ids,
            input_sha256=canonical_hash(identity),
            profile_sha256=profile.profile_sha256,
            role_profile_sha256=profile.role_profile_sha256,
            max_attempts=self.plan.relations.max_attempts,
            dependency_task_ids=(parent.task_id,),
            deadline_epoch=parent.deadline_epoch,
            derived=True,
            endpoint_item_ids=endpoints,
        )
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            current = self.connection.execute(
                "SELECT derived_task_id FROM derivations WHERE parent_task_id=?",
                (parent.task_id,),
            ).fetchone()
            if current is not None and current["derived_task_id"]:
                existing_id = str(current["derived_task_id"])
                self.connection.execute("COMMIT")
                return self._task_from_row(existing_id)
            count = self.connection.execute(
                "SELECT count(*) FROM tasks WHERE batch_id=? AND derived=1",
                (self.plan.batch_id,),
            ).fetchone()[0]
            if count >= self.plan.relations.max_tasks:
                self.connection.execute(
                    "UPDATE derivations SET status='budget_exhausted', "
                    "reason_code='CS_BUDGET_EXHAUSTED' WHERE parent_task_id=?",
                    (parent.task_id,),
                )
                self.connection.execute("COMMIT")
                return None
            self._insert_task(task)
            self.connection.execute(
                "UPDATE derivations SET status='registered', derived_task_id=?, reason_code=NULL "
                "WHERE parent_task_id=?",
                (task.task_id, parent.task_id),
            )
            self.connection.execute("COMMIT")
        except sqlite3.IntegrityError:
            self.connection.execute("ROLLBACK")
            existing = self.connection.execute(
                "SELECT task_id FROM tasks WHERE batch_id=? AND logical_key=?",
                (self.plan.batch_id, logical),
            ).fetchone()
            if existing is None:
                raise
            self.connection.execute(
                "UPDATE derivations SET status='registered', derived_task_id=? "
                "WHERE parent_task_id=?",
                (existing[0], parent.task_id),
            )
            return self._task_from_row(existing[0])
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        return task

    def update_derivation(self, parent_task_id: str, execution: RoleExecution) -> None:
        status = (
            "no_candidates"
            if (
                execution.relation_candidates is not None
                and not execution.relation_candidates.candidates
            )
            else execution.artifact.execution_status
        )
        self.connection.execute(
            "UPDATE derivations SET status=? WHERE parent_task_id=?",
            (status, parent_task_id),
        )

    def _task_from_row(self, task_id: str) -> PlannedTask:
        row = self.connection.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise StructuredExecutionError("CS_NOT_FOUND", "derived_task_not_found")
        return PlannedTask(
            task_id=row["task_id"],
            logical_key=row["logical_key"],
            role=row["role"],
            protocol=row["protocol"],
            method=row["method"],
            scoped_unit_ids=tuple(json.loads(row["scoped_unit_ids"])),
            input_sha256=row["input_sha256"],
            profile_sha256=row["profile_sha256"],
            role_profile_sha256=row["role_profile_sha256"],
            max_attempts=row["max_attempts"],
            dependency_task_ids=tuple(json.loads(row["dependency_task_ids"])),
            deadline_epoch=row["deadline_epoch"],
            derived=bool(row["derived"]),
            endpoint_item_ids=tuple(json.loads(row["endpoint_item_ids"])),
        )


class _BatchLease:
    """OS-released single-runner lease; a crashed process cannot strand it."""

    def __init__(self, descriptor: int) -> None:
        self.descriptor = descriptor

    @classmethod
    def acquire(cls, root: Path, batch_id: str) -> _BatchLease:
        directory = _safe_path(root, root / "scratch", "lease_path_escape")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        name = canonical_hash(batch_id)[7:] + ".lock"
        path = _safe_path(root, directory / name, "lease_path_escape")
        descriptor = -1
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            with suppress(OSError):
                os.close(descriptor)
            raise StructuredExecutionError(
                "CS_DEPENDENCY_NOT_READY", "batch_runner_already_active"
            ) from exc
        return cls(descriptor)

    def close(self) -> None:
        with suppress(OSError):
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        with suppress(OSError):
            os.close(self.descriptor)


class ReplayDirectory:
    """Read a finite, non-recursive response set without searching outside it."""

    def __init__(self, directory: str | Path) -> None:
        path = Path(directory)
        if not path.is_absolute() or path.is_symlink() or not path.is_dir():
            raise StructuredExecutionError("CS_INPUT_INVALID", "invalid_replay_directory")
        responses: dict[tuple[str, str, int], ReplayResponse] = {}
        for child in sorted(path.iterdir()):
            if child.is_symlink() or not child.is_file() or child.suffix != ".json":
                continue
            try:
                response = ReplayResponse.model_validate_json(child.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError) as exc:
                raise StructuredExecutionError(
                    "CS_INPUT_INVALID", "invalid_replay_response"
                ) from exc
            selector = response.task_id or response.parent_task_id
            assert selector is not None
            key = ("task" if response.task_id else "parent", selector, response.sequence)
            if key in responses:
                raise StructuredExecutionError("CS_INPUT_INVALID", "duplicate_replay_response")
            responses[key] = response
        self.responses = responses

    def get(self, request: RoleRequest, *, parent_task_id: str | None = None) -> ReplayResponse:
        response = self.responses.get(("task", request.task_id, request.sequence))
        if response is None and parent_task_id is not None:
            response = self.responses.get(("parent", parent_task_id, request.sequence))
        if response is None:
            raise StructuredExecutionError("CS_NOT_FOUND", "replay_response_missing")
        if (
            response.role != request.role
            or response.protocol != request.protocol
            or response.request_sha256 not in {None, request.request_sha256}
        ):
            raise StructuredExecutionError("CS_INPUT_INVALID", "replay_response_binding")
        return response


def _profile(plan: BatchPlan, role: Role) -> FrozenRoleProfile:
    return next(item for item in plan.profiles if item.role == role)


def _raise_dispatch(error: StructuredExecutionError) -> Never:
    status = (
        "blocked" if error.code in {"CS_BUDGET_EXHAUSTED", "CS_DEPENDENCY_NOT_READY"} else "failed"
    )
    raise LlmCallError(
        {"execution_status": status, "error_code": error.code, "error_type": error.reason}
    )


def _replay_dispatch(
    journal: ExecutionJournal,
    source: ReplayDirectory,
    checkpoint: Checkpoint,
) -> Callable[[RoleRequest], str]:
    def dispatch(request: RoleRequest) -> str:
        existing = journal.existing_attempt(request)
        if existing is not None:
            return journal.reusable_response(existing)
        try:
            parent = journal.parent_task_id(request.task_id)
            replay = source.get(request, parent_task_id=parent)
            profile = _profile(journal.plan, request.role)
            attempt_id = journal.reserve_attempt(
                request,
                request_sha256=request.request_sha256,
                provider="replay",
                request_model=profile.model or "replay-fixture",
                profile_sha256=profile.profile_sha256,
                role_profile_sha256=profile.role_profile_sha256,
            )
        except StructuredExecutionError as exc:
            _raise_dispatch(exc)
        checkpoint("after_reserve")
        diagnostics = _safe_diagnostics(replay.diagnostics)
        diagnostics.update(
            {
                "attempt_id": attempt_id,
                "attempts": 1,
                "execution_status": "succeeded",
                "provider": "replay",
                "request_model": profile.model or "replay-fixture",
                "response_model": diagnostics.get("response_model"),
                "profile_sha256": profile.profile_sha256,
                "role_profile_sha256": profile.role_profile_sha256,
                "request_sha256": request.request_sha256,
            }
        )
        response = LlmResponse(replay.content, diagnostics)
        checkpoint("after_response")
        journal.complete_attempt(attempt_id, response, checkpoint=checkpoint)
        return response

    return dispatch


def _live_dispatch(
    journal: ExecutionJournal,
    bindings: Mapping[Role, RoleBinding],
    transports: Mapping[Role, TransportFactory] | None,
    checkpoint: Checkpoint,
) -> Callable[[RoleRequest], str]:
    def dispatch(request: RoleRequest) -> str:
        existing = journal.existing_attempt(request)
        if existing is not None:
            return journal.reusable_response(existing)
        binding = bindings[request.role]
        attempt_id: str | None = None

        def authorize(intent: Any) -> str:
            nonlocal attempt_id
            try:
                attempt_id = journal.reserve_attempt(
                    request,
                    request_sha256=intent.request_sha256,
                    provider=intent.provider,
                    request_model=intent.request_model,
                    profile_sha256=intent.profile_sha256,
                    role_profile_sha256=intent.role_profile_sha256,
                )
            except StructuredExecutionError as exc:
                _raise_dispatch(exc)
            checkpoint("after_reserve")
            return cast(str, attempt_id)

        adapter = ExtractionAdapter(
            binding,
            authorize,
            transports.get(request.role) if transports is not None else None,
        )
        try:
            response = adapter(request.prompt)
            checkpoint("after_response")
            assert attempt_id is not None
            journal.complete_attempt(attempt_id, response, checkpoint=checkpoint)
            return response
        except LlmCallError as exc:
            if attempt_id is not None:
                journal.fail_attempt(attempt_id, exc.diagnostics)
            raise

    return dispatch


def _run_task(
    journal: ExecutionJournal,
    task: PlannedTask,
    dispatch: Callable[[RoleRequest], str] | None,
) -> RoleExecution | None:
    status = journal.task_status(task.task_id)
    if status in _TERMINAL:
        return None
    if task.deadline_epoch is not None and time.time() >= task.deadline_epoch:
        journal.set_task_state(task.task_id, "cancelled", reasons=("deadline_exceeded",))
        return None
    if task.method == "model" and task.role != "material_relations" and task.max_attempts == 0:
        journal.set_task_state(
            task.task_id,
            "blocked",
            error_codes=("CS_BUDGET_EXHAUSTED",),
            reasons=("role_attempt_budget_exhausted",),
        )
        return None
    try:
        if task.role == "claims":
            result = execute_claims_role(
                journal.plan.snapshot,
                task_id=task.task_id,
                protocol=task.protocol,
                max_calls=task.max_attempts,
                scoped_unit_ids=task.scoped_unit_ids,
                dispatch=dispatch if task.method == "model" else None,
            )
        elif task.role == "material_items":
            result = execute_material_items_role(
                journal.plan.snapshot,
                task_id=task.task_id,
                protocol=task.protocol,
                max_calls=task.max_attempts,
                dispatch=dispatch,
            )
        else:
            parent_id = task.dependency_task_ids[0]
            items = journal.load_items_execution(parent_id)
            result = execute_material_relations_role(
                journal.plan.snapshot,
                task_id=task.task_id,
                protocol=task.protocol,
                items_execution=items,
                endpoint_item_ids=task.endpoint_item_ids,
                items_validation_version=journal.plan.relations.items_validation_version,
                candidate_rule_version=journal.plan.relations.rule_version,
                max_calls=task.max_attempts,
                dispatch=dispatch,
            )
        journal.save_execution(task, result)
        return result
    except StructuredExecutionError:
        raise
    except Exception as exc:
        if isinstance(exc, ExtractionConfigError):
            code = "CS_CONFIG_MISSING"
        elif isinstance(exc, ValueError) and str(exc).startswith("CS_"):
            code = str(exc).split(":", 1)[0]
        else:
            code = "CS_INPUT_INVALID"
        journal.set_task_state(
            task.task_id, "failed", error_codes=(code,), reasons=(type(exc).__name__,)
        )
        return None


def _run_plan(
    plan: BatchPlan,
    store_root: str | Path | None,
    dispatch_factory: Callable[[ExecutionJournal], Callable[[RoleRequest], str]],
) -> BatchCheck:
    root = _store_root(store_root, write=True)
    lease = _BatchLease.acquire(root, plan.batch_id)
    journal: ExecutionJournal | None = None
    try:
        journal = ExecutionJournal.open(plan, root)
        journal.recover_pending()
        journal.verify_references()
        dispatch = dispatch_factory(journal)
        for task in plan.tasks:
            _run_task(journal, task, dispatch if task.method == "model" else None)
        for parent in (task for task in plan.tasks if task.role == "material_items"):
            derived = journal.derive_relation_task(parent)
            if derived is not None:
                result = _run_task(journal, derived, dispatch)
                if result is not None:
                    journal.update_derivation(parent.task_id, result)
    finally:
        if journal is not None:
            journal.close()
        lease.close()
    return check_batch(plan.batch_id, store_root=root)


def replay_batch(
    plan: BatchPlan,
    *,
    responses: str | Path,
    store_root: str | Path | None = None,
    checkpoint: Checkpoint = _noop_checkpoint,
) -> BatchCheck:
    """Execute only deterministic work plus explicit local replay responses."""
    source = ReplayDirectory(responses)
    return _run_plan(
        plan,
        store_root,
        lambda journal: _replay_dispatch(journal, source, checkpoint),
    )


def execute_batch(
    plan: BatchPlan,
    *,
    store_root: str | Path | None = None,
    allow_model: bool = False,
    config: ExtractionConfig | None = None,
    role_configs: Mapping[Role, ExtractionConfig] | None = None,
    transport_factories: Mapping[Role, TransportFactory] | None = None,
    checkpoint: Checkpoint = _noop_checkpoint,
) -> BatchCheck:
    """Execute live adapters only after explicit authority and frozen config matching."""
    plan.verify_identity()
    roles: tuple[Role, ...] = ("claims", "material_items", "material_relations")
    selected: dict[Role, ExtractionConfig | None] = {
        role: (role_configs or {}).get(role, config) for role in roles
    }
    config_error = not allow_model or any(
        item is None or not item.configured for item in selected.values()
    )
    bindings: dict[Role, RoleBinding] = {}
    if not config_error:
        bindings = {
            role: RoleBinding(
                role=role,
                protocol=_profile(plan, role).protocol,
                config=cast(ExtractionConfig, selected[role]),
            )
            for role in selected
        }
    for profile in plan.profiles:
        binding = bindings.get(profile.role)
        if (
            binding is None
            or not profile.configured
            or (
                profile.profile_sha256 != binding.config.require_profile().fingerprint
                or profile.role_profile_sha256 != binding.fingerprint
            )
        ):
            config_error = True
    if config_error:
        root = _store_root(store_root, write=True)
        lease = _BatchLease.acquire(root, plan.batch_id)
        journal: ExecutionJournal | None = None
        try:
            journal = ExecutionJournal.open(plan, root)
            journal.recover_pending()
            journal.verify_references()
            for task in plan.tasks:
                if task.method == "deterministic":
                    _run_task(journal, task, None)
                elif journal.task_status(task.task_id) not in _TERMINAL:
                    journal.set_task_state(
                        task.task_id,
                        "blocked",
                        error_codes=("CS_CONFIG_MISSING",),
                        reasons=(
                            "allow_model_required"
                            if not allow_model
                            else "dedicated_extraction_config_required",
                        ),
                    )
                    if task.role == "material_items":
                        journal.connection.execute(
                            "UPDATE derivations SET status='dependency_not_ready', "
                            "reason_code='CS_CONFIG_MISSING' WHERE parent_task_id=?",
                            (task.task_id,),
                        )
        finally:
            if journal is not None:
                journal.close()
            lease.close()
        return check_batch(plan.batch_id, store_root=root)
    return _run_plan(
        plan,
        store_root,
        lambda journal: _live_dispatch(journal, bindings, transport_factories, checkpoint),
    )


def cancel_batch(batch_id: str, *, store_root: str | Path | None = None) -> None:
    """Explicit operator cancellation; it never deletes attempts or releases budget."""
    root = _store_root(store_root, write=False)
    connection = _writer(root)
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT batch_id FROM batches WHERE batch_id=?", (batch_id,)
        ).fetchone()
        if row is None:
            raise StructuredExecutionError("CS_NOT_FOUND", "batch_not_found")
        connection.execute("UPDATE batches SET cancelled=1 WHERE batch_id=?", (batch_id,))
        connection.execute(
            "UPDATE tasks SET execution_status='cancelled', "
            "reason_codes='[\"operator_cancelled\"]' "
            "WHERE batch_id=? AND execution_status IN ('planned','ready','deferred','blocked')",
            (batch_id,),
        )
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def _cost_summary(rows: list[sqlite3.Row]) -> tuple[CostSummary, ...]:
    groups: dict[tuple[str, str, str | None, str | None, str | None], dict[str, float | int]] = {}
    for row in rows:
        cost = json.loads(row["cost"]) if row["cost"] else None
        currency = cost.get("currency") if isinstance(cost, dict) else None
        kind = cost.get("kind") if isinstance(cost, dict) else None
        price_version = cost.get("price_version") if isinstance(cost, dict) else None
        key = (
            row["provider"],
            row["request_model"],
            currency if isinstance(currency, str) else None,
            kind if isinstance(kind, str) else None,
            price_version if isinstance(price_version, str) else None,
        )
        group = groups.setdefault(key, {"known_amount": 0.0, "known_calls": 0, "unknown_calls": 0})
        amount = cost.get("amount") if isinstance(cost, dict) else None
        if isinstance(amount, (int, float)) and not isinstance(amount, bool):
            group["known_amount"] += float(amount)
            group["known_calls"] += 1
        else:
            group["unknown_calls"] += 1
    return tuple(
        CostSummary(
            provider=key[0],
            model=key[1],
            currency=key[2],
            kind=key[3],
            price_version=key[4],
            known_amount=float(value["known_amount"]),
            known_calls=int(value["known_calls"]),
            unknown_calls=int(value["unknown_calls"]),
        )
        for key, value in sorted(groups.items(), key=lambda item: tuple(str(v) for v in item[0]))
    )


def check_batch(batch_id: str, *, store_root: str | Path | None = None) -> BatchCheck:
    """Read and reconcile one batch using a read-only SQLite connection."""
    root = _store_root(store_root, write=False)
    connection = _reader(root)
    try:
        batch = connection.execute("SELECT * FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
        if batch is None:
            raise StructuredExecutionError("CS_NOT_FOUND", "batch_not_found")
        try:
            plan = BatchPlan.model_validate_json(batch["plan_json"])
            plan.verify_identity()
            consistent = (
                plan.batch_id == batch_id
                and plan.plan_sha256 == batch["plan_sha256"]
                and plan.snapshot.snapshot_id == batch["snapshot_id"]
            )
        except (ValueError, StructuredExecutionError):
            plan = None
            consistent = False
        task_rows = connection.execute(
            "SELECT * FROM tasks WHERE batch_id=? ORDER BY rowid", (batch_id,)
        ).fetchall()
        attempt_rows = connection.execute(
            "SELECT attempts.* FROM attempts JOIN tasks USING(task_id) "
            "WHERE tasks.batch_id=? ORDER BY attempts.rowid",
            (batch_id,),
        ).fetchall()
        referenced_objects = [
            row["response_object_sha256"] for row in attempt_rows if row["response_object_sha256"]
        ]
        referenced_objects.extend(
            row[key]
            for row in task_rows
            for key in ("artifact_sha256", "payload_object_sha256")
            if row[key]
        )
        object_values = {
            object_sha: _read_object(root, object_sha) for object_sha in set(referenced_objects)
        }
        tasks = tuple(
            LedgerTask(
                task_id=row["task_id"],
                role=row["role"],
                method=row["method"],
                input_sha256=row["input_sha256"],
                profile_sha256=row["profile_sha256"],
                execution_status=row["execution_status"],
                protocol_status=row["protocol_status"],
                quality_status=row["quality_status"],
                publication_status=row["publication_status"],
                context_status=row["context_status"],
                dependency_task_ids=tuple(json.loads(row["dependency_task_ids"])),
                artifact_sha256=row["artifact_sha256"],
                error_codes=tuple(json.loads(row["error_codes"])),
            )
            for row in task_rows
        )
        attempts = tuple(
            LedgerAttempt(
                attempt_id=row["attempt_id"],
                task_id=row["task_id"],
                attempt_number=row["attempt_number"],
                execution_status=row["execution_status"],
                request_sha256=row["request_sha256"],
                response_sha256=row["response_sha256"],
                provider=row["provider"],
                request_model=row["request_model"],
                response_model=row["response_model"],
                usage=json.loads(row["usage"]) if row["usage"] else None,
                cost=json.loads(row["cost"]) if row["cost"] else None,
            )
            for row in attempt_rows
        )
        findings: list[str] = []
        if not consistent:
            findings.append("plan_identity_mismatch")
        task_row_by_id = {row["task_id"]: row for row in task_rows}
        if plan is not None:
            initial_ids = {task.task_id for task in plan.tasks}
            planned_by_id = {task.task_id: task for task in plan.tasks}
            missing = initial_ids - set(task_row_by_id)
            unexpected_initial = {
                row["task_id"]
                for row in task_rows
                if not row["derived"] and row["task_id"] not in initial_ids
            }
            findings.extend(f"planned_task_missing:{task_id}" for task_id in sorted(missing))
            findings.extend(
                f"unplanned_initial_task:{task_id}" for task_id in sorted(unexpected_initial)
            )
            if missing or unexpected_initial:
                consistent = False
            if batch["max_attempts"] != plan.max_attempts or batch["currency"] != plan.currency:
                findings.append("batch_budget_binding_mismatch")
                consistent = False
            for task_id, planned in planned_by_id.items():
                row = task_row_by_id.get(task_id)
                if row is None:
                    continue
                actual = (
                    row["logical_key"],
                    row["role"],
                    row["protocol"],
                    row["method"],
                    row["input_sha256"],
                    row["profile_sha256"],
                    row["role_profile_sha256"],
                    tuple(json.loads(row["dependency_task_ids"])),
                    tuple(json.loads(row["scoped_unit_ids"])),
                    tuple(json.loads(row["endpoint_item_ids"])),
                    row["max_attempts"],
                    row["deadline_epoch"],
                    bool(row["derived"]),
                )
                expected = (
                    planned.logical_key,
                    planned.role,
                    planned.protocol,
                    planned.method,
                    planned.input_sha256,
                    planned.profile_sha256,
                    planned.role_profile_sha256,
                    planned.dependency_task_ids,
                    planned.scoped_unit_ids,
                    planned.endpoint_item_ids,
                    planned.max_attempts,
                    planned.deadline_epoch,
                    planned.derived,
                )
                if actual != expected:
                    findings.append(f"planned_task_binding_mismatch:{task_id}")
                    consistent = False
            profile_by_role = {profile.role: profile for profile in plan.profiles}
            for row in task_rows:
                profile = profile_by_role.get(row["role"])
                logical = row["logical_key"]
                stable_identity = (
                    isinstance(logical, str)
                    and logical.startswith("sha256:")
                    and row["task_id"] == f"task:{logical[7:]}"
                    and row["input_sha256"] == logical
                )
                if not stable_identity:
                    findings.append(f"task_identity_mismatch:{row['task_id']}")
                    consistent = False
                if (
                    profile is None
                    or row["profile_sha256"] != profile.profile_sha256
                    or row["role_profile_sha256"] != profile.role_profile_sha256
                ):
                    findings.append(f"task_profile_mismatch:{row['task_id']}")
                    consistent = False
        findings.extend(
            f"task_not_terminal:{task.task_id}:{task.execution_status}"
            for task in tasks
            if task.execution_status not in _TERMINAL
        )
        findings.extend(
            f"attempt_outcome_unknown:{attempt.attempt_id}"
            for attempt in attempts
            if attempt.execution_status == "outcome_unknown"
        )
        findings.extend(
            f"attempt_not_terminal:{attempt.attempt_id}:{attempt.execution_status}"
            for attempt in attempts
            if attempt.execution_status in {"planned", "ready", "reserved", "running"}
        )
        task_profiles = {row["task_id"]: row["profile_sha256"] for row in task_rows}
        task_role_profiles = {row["task_id"]: row["role_profile_sha256"] for row in task_rows}
        findings.extend(
            f"attempt_profile_mismatch:{row['attempt_id']}"
            for row in attempt_rows
            if task_profiles.get(row["task_id"]) != row["profile_sha256"]
            or task_role_profiles.get(row["task_id"]) != row["role_profile_sha256"]
        )
        if any(finding.startswith("attempt_profile_mismatch:") for finding in findings):
            consistent = False
        attempts_by_task: dict[str, list[sqlite3.Row]] = {}
        for row in attempt_rows:
            attempts_by_task.setdefault(row["task_id"], []).append(row)
            expected_attempt_id = (
                "attempt:"
                + canonical_hash(
                    {
                        "task_id": row["task_id"],
                        "attempt_number": row["attempt_number"],
                        "request_sha256": row["request_sha256"],
                    }
                )[7:]
            )
            if row["attempt_id"] != expected_attempt_id:
                findings.append(f"attempt_identity_mismatch:{row['attempt_id']}")
                consistent = False
            response_object = row["response_object_sha256"]
            if response_object:
                value = object_values[response_object]
                if (
                    not isinstance(value, dict)
                    or value.get("schema_version") != "corpus-model-response-v1"
                    or not isinstance(value.get("content"), str)
                    or not isinstance(value.get("diagnostics"), dict)
                    or row["response_sha256"] != canonical_hash(value.get("content"))
                ):
                    findings.append(f"response_binding_mismatch:{row['attempt_id']}")
                    consistent = False
            elif row["execution_status"] == "succeeded" or row["response_sha256"] is not None:
                findings.append(f"response_reference_missing:{row['attempt_id']}")
                consistent = False
        for task_id, rows in attempts_by_task.items():
            numbers = sorted(row["attempt_number"] for row in rows)
            if numbers != list(range(1, len(rows) + 1)):
                findings.append(f"attempt_sequence_mismatch:{task_id}")
                consistent = False
        if batch["reserved_attempts"] != len(attempt_rows):
            findings.append("batch_reserved_counter_mismatch")
            consistent = False
        if batch["actual_attempts"] != len(attempt_rows):
            findings.append("batch_actual_counter_mismatch")
            consistent = False
        for row in task_rows:
            attempt_count = sum(item["task_id"] == row["task_id"] for item in attempt_rows)
            if attempt_count > row["max_attempts"]:
                findings.append(f"task_attempt_budget_exceeded:{row['task_id']}")
                consistent = False
        role_budget_rows = connection.execute(
            "SELECT role, max_attempts, reserved_attempts FROM role_budgets WHERE batch_id=?",
            (batch_id,),
        ).fetchall()
        raw_role_budgets = {row["role"]: row for row in role_budget_rows}
        canonical_roles = {"claims", "material_items", "material_relations"}
        if set(raw_role_budgets) != canonical_roles:
            findings.append("role_budget_rows_mismatch")
            consistent = False
        role_budgets: dict[Role, RoleBudgetSummary] = {
            cast(Role, row["role"]): RoleBudgetSummary(
                max_attempts=row["max_attempts"], reserved_attempts=row["reserved_attempts"]
            )
            for row in role_budget_rows
            if row["role"] in canonical_roles
        }
        if plan is not None:
            for role, limit in plan.role_max_attempts.items():
                row = raw_role_budgets.get(role)
                if row is None or row["max_attempts"] != limit:
                    findings.append(f"role_budget_plan_mismatch:{role}")
                    consistent = False
        for role, summary in role_budgets.items():
            count = sum(task_row_by_id[item["task_id"]]["role"] == role for item in attempt_rows)
            if count != summary.reserved_attempts or count > summary.max_attempts:
                findings.append(f"role_budget_counter_mismatch:{role}")
                consistent = False
        derivation_rows = connection.execute(
            "SELECT parent_task_id, status, derived_task_id, reason_code FROM derivations "
            "WHERE parent_task_id IN (SELECT task_id FROM tasks WHERE batch_id=?)",
            (batch_id,),
        ).fetchall()
        derivations = {
            row["parent_task_id"]: (
                row["status"]
                if row["reason_code"] is None
                else f"{row['status']}:{row['reason_code']}"
            )
            for row in derivation_rows
        }
        derived_ids = {row["task_id"] for row in task_rows if row["derived"]}
        referenced_derived_ids = {
            row["derived_task_id"] for row in derivation_rows if row["derived_task_id"]
        }
        for row in derivation_rows:
            derived_id = row["derived_task_id"]
            if derived_id is None:
                continue
            task_row = task_row_by_id.get(derived_id)
            if (
                task_row is None
                or task_row["role"] != "material_relations"
                or tuple(json.loads(task_row["dependency_task_ids"])) != (row["parent_task_id"],)
            ):
                findings.append(f"derived_task_binding_mismatch:{derived_id}")
                consistent = False
        for task_id in sorted(derived_ids - referenced_derived_ids):
            findings.append(f"derived_task_unregistered:{task_id}")
            consistent = False
        for row in task_rows:
            artifact_reference = row["artifact_sha256"]
            payload_reference = row["payload_object_sha256"]
            references_complete = bool(artifact_reference) == bool(payload_reference)
            if not references_complete:
                findings.append(f"artifact_reference_incomplete:{row['task_id']}")
                consistent = False
                continue
            if not artifact_reference:
                if row["execution_status"] == "succeeded":
                    findings.append(f"artifact_reference_missing:{row['task_id']}")
                    consistent = False
                continue
            try:
                artifact = RoleArtifact.model_validate(object_values[artifact_reference])
                artifact.verify_identity()
                payload = object_values[payload_reference]
                artifact_matches = (
                    artifact.task_id == row["task_id"]
                    and artifact.role == row["role"]
                    and artifact.protocol == row["protocol"]
                    and artifact.snapshot_id == batch["snapshot_id"]
                    and artifact.artifact_id == row["artifact_id"]
                    and artifact.payload_sha256 == row["payload_sha256"]
                    and artifact.payload_sha256 == canonical_hash(payload)
                    and artifact.execution_status == row["execution_status"]
                    and artifact.protocol_status == row["protocol_status"]
                    and artifact.quality_status == row["quality_status"]
                    and artifact.context_status == row["context_status"]
                )
            except (TypeError, ValueError):
                artifact_matches = False
            if not artifact_matches:
                findings.append(f"artifact_binding_mismatch:{row['task_id']}")
                consistent = False
        ledger = ExecutionLedger(
            batch_id=batch_id,
            plan_sha256=batch["plan_sha256"],
            snapshot_id=batch["snapshot_id"],
            budget=LedgerBudget(
                max_attempts=batch["max_attempts"],
                reserved_attempts=batch["reserved_attempts"],
                actual_attempts=batch["actual_attempts"],
                currency=batch["currency"],
            ),
            tasks=tasks,
            attempts=attempts,
        )
        return BatchCheck(
            ledger=ledger,
            plan_consistent=consistent,
            findings=tuple(findings),
            derivations=derivations,
            role_budgets=role_budgets,
            cost_summary=_cost_summary(attempt_rows),
        )
    finally:
        connection.close()


__all__ = [
    "PLAN_SCHEMA_VERSION",
    "REPLAY_SCHEMA_VERSION",
    "STORE_ROOT_ENV",
    "BatchCheck",
    "BatchPlan",
    "ExecutionJournal",
    "ExecutionLedger",
    "FrozenRoleProfile",
    "LedgerAttempt",
    "LedgerBudget",
    "LedgerTask",
    "PlannedTask",
    "RelationPlan",
    "ReplayResponse",
    "RoleBudgetSummary",
    "StructuredExecutionError",
    "cancel_batch",
    "check_batch",
    "execute_batch",
    "plan_batch",
    "replay_batch",
]
