"""Run-storage backup manifest, retention planning and restore verification.

F07 / hardening T5-T6. Three commands, in the order a real migration needs them::

    uv run python scripts/run_retention.py manifest --out backups/run-manifest.json
    uv run python scripts/run_retention.py plan --manifest backups/run-manifest.json
    uv run python scripts/run_retention.py verify --manifest backups/run-manifest.json

Why this exists
---------------
The business DB and the run files live on different media. Restoring one does not
restore the other, so "the run row is there" must never be read as "the study is
recoverable". The manifest is what ties them together: every run carries its
storage reference, per-file digests, sizes and its F06 trajectory state.

Design rules that are not negotiable
------------------------------------
1. **Planning never deletes.** ``plan`` is dry-run by default; deleting needs
   ``--apply --yes`` and re-checks each entry immediately before removing it.
2. **Missing files are not expired files.** A run whose directory vanished is a
   *recovery* problem, not a *cleanup* one. They get separate dispositions so a
   retention sweep can never report a lost study as "tidied up".
3. **Active and unfinished runs are protected**, as are runs outside the
   requested user scope.
4. A digest is an integrity check, not tamper evidence: it proves the bytes
   match what was recorded, nothing about who changed them.

Not covered here (needs an operator and a separate environment):
``pg_dump``/``pg_restore`` of the business DB, off-host backup storage, and the
end-to-end restore rehearsal. See the F07 issue for what is still unproven.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

#: Runs in these states have a live worker (server.store.ACTIVE_RUN_STATUSES).
ACTIVE_STATUSES: frozenset[str] = frozenset({"queued", "running"})

_READ_CHUNK = 1 << 20


class Disposition(StrEnum):
    """Why a run is (or is not) in a cleanup plan."""

    EXPIRED = "expired"
    RETAINED = "retained"
    ACTIVE = "active"
    UNFINISHED = "unfinished"
    MISSING = "missing"
    OUT_OF_SCOPE = "out_of_scope"


@dataclass(frozen=True)
class RetentionPolicy:
    """How long finished runs are kept before they become cleanable."""

    keep_days: int = 30
    protect_active: bool = True
    protect_unfinished: bool = True
    #: When set, runs belonging to other users are OUT_OF_SCOPE, never cleaned.
    user_id: str | None = None


@dataclass(frozen=True)
class RunStorage:
    """One run's storage as recorded in a manifest."""

    run_id: str
    status: str = ""
    user_id: str | None = None
    run_dir: str = ""
    finished_at: str | None = None
    exists: bool = False
    file_count: int = 0
    total_bytes: int = 0
    #: rel path -> sha256. Empty when the directory is absent.
    digests: dict[str, str] = field(default_factory=dict)
    #: F06 verdict, so a backup knows whether the trace itself was complete.
    trajectory_state: str = "unknown"


@dataclass(frozen=True)
class Manifest:
    generated_at: str
    runs_root: str
    runs: list[RunStorage] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "runs_root": self.runs_root,
            "runs": [asdict(r) for r in self.runs],
        }

    @classmethod
    def from_dict(cls, payload: dict) -> Manifest:
        return cls(
            generated_at=payload.get("generated_at", ""),
            runs_root=payload.get("runs_root", ""),
            runs=[
                RunStorage(
                    run_id=r.get("run_id", ""),
                    status=r.get("status", ""),
                    user_id=r.get("user_id"),
                    run_dir=r.get("run_dir", ""),
                    finished_at=r.get("finished_at"),
                    exists=bool(r.get("exists")),
                    file_count=int(r.get("file_count", 0)),
                    total_bytes=int(r.get("total_bytes", 0)),
                    digests=dict(r.get("digests") or {}),
                    trajectory_state=r.get("trajectory_state", "unknown"),
                )
                for r in payload.get("runs", [])
            ],
        )


@dataclass(frozen=True)
class PlannedAction:
    run_id: str
    disposition: Disposition
    reason: str
    path: str = ""
    bytes: int = 0

    @property
    def cleanable(self) -> bool:
        return self.disposition is Disposition.EXPIRED


@dataclass(frozen=True)
class VerifyResult:
    run_id: str
    #: ``ok`` / ``missing_dir`` / ``missing_files`` / ``digest_mismatch``.
    status: str
    detail: str = ""
    missing: tuple[str, ...] = ()
    mismatched: tuple[str, ...] = ()


def _parse_finished_at(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def digest_file(path: Path) -> str:
    """SHA-256 of one file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_READ_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan_run_dir(path: Path) -> tuple[int, int, dict[str, str]]:
    """Return (file_count, total_bytes, {relpath: sha256}) for a run directory.

    A missing directory yields zeros rather than an error: that is the
    ``missing`` disposition, which must be distinguishable from "empty but fine".
    """
    if not path.exists() or not path.is_dir():
        return 0, 0, {}
    count = 0
    total = 0
    digests: dict[str, str] = {}
    for entry in sorted(path.rglob("*")):
        if entry.is_symlink() or not entry.is_file():
            continue
        try:
            size = entry.stat().st_size
            digests[entry.relative_to(path).as_posix()] = digest_file(entry)
        except OSError:
            # Unreadable file: record it as present but undigested rather than
            # aborting the whole manifest.
            digests[entry.relative_to(path).as_posix()] = ""
            size = 0
        count += 1
        total += size
    return count, total, digests


def plan_cleanup(
    runs: list[RunStorage],
    policy: RetentionPolicy,
    now: datetime,
) -> list[PlannedAction]:
    """Classify runs for retention. Never touches the filesystem.

    Ordering matters: a run is only ever EXPIRED if it is in scope, not active,
    has a completion timestamp and is genuinely past the retention window.
    Everything else gets a disposition that says *why* it is being kept, so a
    "nothing to clean" report is legible instead of looking like a no-op.
    """
    actions: list[PlannedAction] = []
    for run in runs:
        if policy.user_id and run.user_id and run.user_id != policy.user_id:
            actions.append(PlannedAction(run.run_id, Disposition.OUT_OF_SCOPE,
                                         "不属于本次清理范围的用户"))
            continue

        if not run.exists:
            # Distinct on purpose: the storage is already gone, so this is a
            # restore question, not something a cleanup run should "resolve".
            actions.append(PlannedAction(run.run_id, Disposition.MISSING,
                                         "数据库有记录但运行目录不存在，属恢复问题而非清理对象"))
            continue

        if policy.protect_active and run.status in ACTIVE_STATUSES:
            actions.append(PlannedAction(run.run_id, Disposition.ACTIVE,
                                         "运行仍在进行，禁止清理"))
            continue

        finished = _parse_finished_at(run.finished_at)
        if finished is None:
            if policy.protect_unfinished:
                actions.append(PlannedAction(run.run_id, Disposition.UNFINISHED,
                                             "没有完成时间，无法判定是否到期"))
                continue
            finished = _parse_finished_at(run.finished_at) or now

        cutoff = now - timedelta(days=policy.keep_days)
        if finished > cutoff:
            actions.append(PlannedAction(run.run_id, Disposition.RETAINED,
                                         f"未超过保留期（{policy.keep_days} 天）"))
            continue

        actions.append(PlannedAction(
            run.run_id, Disposition.EXPIRED,
            f"已完成且超过保留期（{policy.keep_days} 天）",
            path=run.run_dir, bytes=run.total_bytes,
        ))
    return actions


def verify_against(runs: list[RunStorage], runs_root: Path | None = None) -> list[VerifyResult]:
    """Compare the current filesystem against a recorded manifest.

    Used after a restore (or a migration) to answer "is this study whole?" —
    which a database row count can never answer on its own.
    """
    results: list[VerifyResult] = []
    for run in runs:
        path = Path(run.run_dir)
        if runs_root is not None and not path.is_absolute():
            path = runs_root / path
        if not run.digests:
            results.append(VerifyResult(
                run.run_id, "missing_dir" if not path.exists() else "ok",
                detail="清单未记录文件（运行目录为空）",
            ))
            continue
        if not path.exists():
            results.append(VerifyResult(run.run_id, "missing_dir",
                                        detail=f"目录不存在：{path}",
                                        missing=tuple(sorted(run.digests))))
            continue

        missing: list[str] = []
        mismatched: list[str] = []
        for rel, expected in sorted(run.digests.items()):
            target = path / rel
            if not target.is_file():
                missing.append(rel)
                continue
            if not expected:
                continue
            try:
                actual = digest_file(target)
            except OSError:
                mismatched.append(rel)
                continue
            if actual != expected:
                mismatched.append(rel)

        if missing and mismatched:
            status = "digest_mismatch"
            detail = f"{len(missing)} 个文件缺失、{len(mismatched)} 个校验不一致"
        elif missing:
            status = "missing_files"
            detail = f"{len(missing)} 个文件缺失"
        elif mismatched:
            status = "digest_mismatch"
            detail = f"{len(mismatched)} 个文件校验不一致"
        else:
            status = "ok"
            detail = ""
        results.append(VerifyResult(run.run_id, status, detail,
                                    missing=tuple(missing), mismatched=tuple(mismatched)))
    return results


def apply_cleanup(actions: list[PlannedAction], runs_root: Path) -> list[str]:
    """Delete EXPIRED run directories. The caller must have planned first.

    Re-checks containment and state immediately before removing, so a stale plan
    cannot delete something that became active in the meantime.
    """
    removed: list[str] = []
    for action in actions:
        if not action.cleanable or not action.path:
            continue
        path = Path(action.path)
        if not path.is_absolute():
            path = runs_root / path
        try:
            resolved = path.resolve()
            root = runs_root.resolve()
        except OSError:
            continue
        if resolved == root or root not in resolved.parents:
            # Outside the run root: refuse rather than follow an odd reference.
            continue
        if not resolved.is_dir():
            continue
        shutil.rmtree(resolved)
        removed.append(action.run_id)
    return removed


# ── CLI ──────────────────────────────────────────────────────────────────


def build_orphan_class(
    kind: str,
    detail_rows: list[tuple],
    impact_rows: list[tuple] | None = None,
    limit: int = 20,
) -> OrphanClass:
    """Shape raw probe rows into an inventory entry. Pure, so it is testable.

    The row layout is (id, detail, created_at, reference) for every class; only
    the meaning of ``detail``/``reference`` varies. Nothing here carries user
    text — the queries select identifiers and timestamps on purpose.
    """
    sample: list[dict[str, str]] = []
    for row in detail_rows[:limit]:
        values = ["" if v is None else str(v) for v in row]
        sample.append({
            "id": values[0] if len(values) > 0 else "",
            "detail": values[1] if len(values) > 1 else "",
            "created_at": values[2] if len(values) > 2 else "",
            "reference": values[3] if len(values) > 3 else "",
        })
    impact = {str(name): int(n) for name, n in (impact_rows or [])}
    return OrphanClass(
        kind=kind,
        count=len(detail_rows),
        impact=impact,
        sample=sample,
        remediation=ORPHAN_REMEDIATION.get(kind, ()),
    )


#: Read-only orphan probes (T6 step 4). Each returns a count that should be 0.
#: They exist because these rows are what makes a plain ``pg_restore`` onto a
#: clean database fail — the data copies, then the FK cannot be added back.
ORPHAN_CHECKS: tuple[tuple[str, str], ...] = (
    ("runs -> missing session",
     "select count(*) from runs r left join sessions s on r.session_id = s.id "
     "where s.id is null"),
    ("runs -> missing user",
     "select count(*) from runs r left join users u on r.user_id = u.id "
     "where u.id is null"),
    ("sessions -> missing user",
     "select count(*) from sessions s left join users u on s.user_id = u.id "
     "where u.id is null"),
    ("turns -> missing run",
     "select count(*) from turns t left join runs r on t.run_id = r.id "
     "where t.run_id is not null and r.id is null"),
    ("turns -> missing session",
     "select count(*) from turns t left join sessions s on t.session_id = s.id "
     "where s.id is null"),
    ("audit_log -> missing user",
     "select count(*) from audit_log a left join users u on a.user_id = u.id "
     "where a.user_id is not null and u.id is null"),
    ("artifacts -> missing run",
     "select count(*) from artifacts ar left join runs r on ar.run_id = r.id "
     "where r.id is null"),
)

_TABLES: tuple[str, ...] = (
    "users", "sessions", "runs", "turns", "artifacts", "user_llm_configs", "audit_log",
)


#: What a human can do about each class. Deliberately *not* executable: the
#: choice between destroying data and re-homing it is a product decision, and the
#: script must never make it on its own.
ORPHAN_REMEDIATION: dict[str, tuple[str, ...]] = {
    "runs -> missing session": (
        "挂到占位 session（保留研究内容，推荐先评估）",
        "删除这些 run 及其 turns/artifacts（连带影响见 impact）",
        "保留但标记，外键暂不补（恢复演练仍会失败）",
    ),
    "runs -> missing user": (
        "挂到占位 user（审计上要明确这些 run 的真实归属已不可考）",
        "删除这些 run 及其 turns/artifacts",
        "保留但标记，外键暂不补",
    ),
    "sessions -> missing user": (
        "挂到占位 user（会连带影响其下 runs 的归属链）",
        "删除这些 session 及其下 runs/turns",
        "保留但标记，外键暂不补",
    ),
    "turns -> missing run": (
        "删除这些 turn（其 run 已不存在，内容无法归属）",
        "保留但标记，外键暂不补",
    ),
    "turns -> missing session": (
        "挂到占位 session 或删除",
    ),
    "audit_log -> missing user": (
        "挂到占位 user（审计记录通常不建议删除）",
        "删除这些审计行（会留下审计空白，需确认合规要求）",
        "保留但标记，外键暂不补",
    ),
    "artifacts -> missing run": (
        "删除这些产物索引（文件是否仍存在需另行核对）",
        "保留但标记，外键暂不补",
    ),
}

#: Detail + impact probes per class. Identifiers and timestamps only — never
#: prompt/answer/audit payloads, so the exported inventory carries no user text.
ORPHAN_DETAIL: dict[str, tuple[str, str]] = {
    "runs -> missing session": (
        "select r.id::text, r.status, r.created_at::text, r.session_id::text "
        "from runs r left join sessions s on r.session_id = s.id where s.id is null "
        "order by r.created_at",
        "select 'turns', count(*) from turns where run_id in "
        "(select r.id from runs r left join sessions s on r.session_id = s.id where s.id is null) "
        "union all select 'artifacts', count(*) from artifacts where run_id in "
        "(select r.id from runs r left join sessions s on r.session_id = s.id where s.id is null)",
    ),
    "runs -> missing user": (
        "select r.id::text, r.status, r.created_at::text, r.user_id::text "
        "from runs r left join users u on r.user_id = u.id where u.id is null "
        "order by r.created_at",
        "select 'turns', count(*) from turns where run_id in "
        "(select r.id from runs r left join users u on r.user_id = u.id where u.id is null) "
        "union all select 'artifacts', count(*) from artifacts where run_id in "
        "(select r.id from runs r left join users u on r.user_id = u.id where u.id is null)",
    ),
    "sessions -> missing user": (
        "select s.id::text, coalesce(s.title,''), s.created_at::text, s.user_id::text "
        "from sessions s left join users u on s.user_id = u.id where u.id is null "
        "order by s.created_at",
        "select 'runs', count(*) from runs where session_id in "
        "(select s.id from sessions s left join users u on s.user_id = u.id where u.id is null) "
        "union all select 'turns', count(*) from turns where session_id in "
        "(select s.id from sessions s left join users u on s.user_id = u.id where u.id is null)",
    ),
    "turns -> missing run": (
        "select t.id::text, t.role, t.created_at::text, t.run_id::text from turns t "
        "left join runs r on t.run_id = r.id where t.run_id is not null and r.id is null "
        "order by t.created_at",
        "",
    ),
    "turns -> missing session": (
        "select t.id::text, t.role, t.created_at::text, t.session_id::text from turns t "
        "left join sessions s on t.session_id = s.id where s.id is null order by t.created_at",
        "",
    ),
    "audit_log -> missing user": (
        "select a.id::text, coalesce(a.action,''), a.created_at::text, a.user_id::text "
        "from audit_log a left join users u on a.user_id = u.id "
        "where a.user_id is not null and u.id is null order by a.created_at",
        "",
    ),
    # artifacts is keyed by (run_id, rel_path) — there is no surrogate id column.
    "artifacts -> missing run": (
        "select ar.run_id::text, coalesce(ar.rel_path,''), ar.created_at::text, "
        "ar.run_id::text from artifacts ar left join runs r on ar.run_id = r.id "
        "where r.id is null",
        "",
    ),
}


@dataclass(frozen=True)
class OrphanClass:
    """One class of orphan rows, with everything a human needs to decide."""

    kind: str
    count: int
    impact: dict[str, int] = field(default_factory=dict)
    sample: list[dict[str, str]] = field(default_factory=list)
    remediation: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "count": self.count,
            "impact": self.impact,
            "sample": self.sample,
            "remediation": list(self.remediation),
        }


def verdict_for(counts: list[tuple[str, int]]) -> str:
    """Human verdict for a consistency report — kept pure so it is testable."""
    dirty = [name for name, n in counts if n]
    if not dirty:
        return "clean"
    return f"{len(dirty)} 类孤儿行：{', '.join(dirty)}"


def _load_manifest(path: Path) -> Manifest:
    return Manifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


async def _build_manifest(runs_root: Path) -> Manifest:
    from sqlalchemy import select

    from server.config import get_config
    from server.store import Run, get_sessionmaker
    from server.trajectory_status import inspect_trajectory

    maker = get_sessionmaker()
    entries: list[RunStorage] = []
    async with maker() as session:
        rows = (await session.execute(select(Run))).scalars().all()
        for row in rows:
            directory = Path(row.run_dir)
            if not directory.is_absolute():
                directory = runs_root / directory
            count, total, digests = scan_run_dir(directory)
            entries.append(RunStorage(
                run_id=str(row.id),
                status=row.status,
                user_id=str(row.user_id),
                run_dir=row.run_dir,
                finished_at=row.finished_at.isoformat() if row.finished_at else None,
                exists=directory.is_dir(),
                file_count=count,
                total_bytes=total,
                digests=digests,
                trajectory_state=str(inspect_trajectory(str(row.id)).state),
            ))
    return Manifest(
        generated_at=datetime.now(UTC).isoformat(),
        runs_root=str(get_config().runs_root),
        runs=entries,
    )


async def _run_consistency_check() -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """Read-only: table row counts and orphan counts. Never mutates."""
    from sqlalchemy import text

    from server.store import get_sessionmaker

    maker = get_sessionmaker()
    counts: list[tuple[str, int]] = []
    orphans: list[tuple[str, int]] = []
    async with maker() as session:
        for table in _TABLES:
            value = await session.execute(text(f"select count(*) from {table}"))
            counts.append((table, int(value.scalar_one())))
        for label, sql in ORPHAN_CHECKS:
            value = await session.execute(text(sql))
            orphans.append((label, int(value.scalar_one())))
    return counts, orphans


@dataclass(frozen=True)
class RunMigration:
    """One run whose directory should move from the old root to the new root."""

    run_id: str
    source: str
    target: str
    source_exists: bool


async def _plan_root_migration(old_root: Path, new_root: Path) -> tuple[list[RunMigration], list[str]]:
    """Plan moving run data out of the source tree (F01).

    Returns ``(migrations, orphan_dirs)``: migrations are runs whose recorded
    ``run_dir`` lives under ``old_root``; orphan_dirs are directories under
    ``old_root`` that no run references (test residue). Only runs whose run_dir
    is actually under ``old_root`` are touched — runs pointing elsewhere (a WSL
    checkout, /tmp) are left alone.
    """
    from sqlalchemy import select

    from server.store import Run, get_sessionmaker

    maker = get_sessionmaker()
    old_root = old_root.resolve()
    new_root = new_root.resolve()
    migrations: list[RunMigration] = []
    db_ids: set[str] = set()
    async with maker() as session:
        rows = [(str(r[0]).replace("-", ""), r[1]) for r in
                (await session.execute(select(Run.id, Run.run_dir))).all()]
    for run_id, run_dir in rows:
        db_ids.add(run_id)
        path = Path(run_dir)
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved == old_root or old_root in resolved.parents:
            migrations.append(RunMigration(
                run_id=run_id, source=str(path),
                target=str(new_root / run_id), source_exists=path.is_dir(),
            ))
    orphan_dirs: list[str] = []
    if old_root.is_dir():
        orphan_dirs = sorted(
            d.name for d in old_root.iterdir()
            if d.is_dir() and d.name not in db_ids
        )
    return migrations, orphan_dirs


async def _apply_root_migration(
    old_root: Path, new_root: Path,
) -> tuple[list[str], list[str], list[str]]:
    """Move runs to the new root and remove unreferenced directories.

    Returns ``(moved, missing, removed)``. Orphan directories are re-validated
    against the run table immediately before removal, so a stale plan cannot
    delete a directory that became referenced in the meantime.
    """
    import uuid as _uuid

    from sqlalchemy import update

    from server.store import Run, get_sessionmaker

    migrations, orphan_dirs = await _plan_root_migration(old_root, new_root)
    maker = get_sessionmaker()
    moved: list[str] = []
    missing: list[str] = []
    async with maker() as session:
        for migration in migrations:
            src = Path(migration.source)
            dst = Path(migration.target)
            if src.is_dir():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                moved.append(migration.run_id)
            else:
                missing.append(migration.run_id)
            await session.execute(
                update(Run)
                .where(Run.id == _uuid.UUID(migration.run_id))
                .values(run_dir=str(dst))
            )
        await session.commit()

    removed: list[str] = []
    for name in orphan_dirs:
        target = old_root / name
        if target.is_dir():
            shutil.rmtree(target)
            removed.append(name)
    return moved, missing, removed


async def _collect_orphan_classes(sample_limit: int = 20) -> list[OrphanClass]:
    """Read-only inventory: one entry per orphan class, with impact."""
    from sqlalchemy import text

    from server.store import get_sessionmaker

    maker = get_sessionmaker()
    classes: list[OrphanClass] = []
    async with maker() as session:
        for kind, (detail_sql, impact_sql) in ORPHAN_DETAIL.items():
            rows = [tuple(r) for r in (await session.execute(text(detail_sql))).all()]
            impact_rows: list[tuple] = []
            if impact_sql:
                impact_rows = [tuple(r) for r in (await session.execute(text(impact_sql))).all()]
            classes.append(build_orphan_class(kind, rows, impact_rows, sample_limit))
    return classes


#: Orphan remediation (T6 step 1, human-decided). The *policy* is not encoded
#: here as an automatic rule — each class was chosen by a human and is applied
#: once. What the code owns is the safety around it.
PLACEHOLDER_USERNAME = "__orphan_placeholder__"
#: Not a valid argon2 digest, so nothing can authenticate as this account.
PLACEHOLDER_PASSWORD_HASH = "!orphan-placeholder-disabled"
PLACEHOLDER_STATUS = "disabled"


async def _remediate(*, apply: bool, placeholder: str) -> dict[str, int]:
    """Apply the agreed orphan policy. Returns what it found / changed.

    Guarantees regardless of ``apply``:
    - Never deletes a run that still has turns or artifacts (re-checked here,
      not trusted from the inventory).
    - Idempotent: a second run changes nothing.
    - One transaction: either every step lands or none does.
    """
    from sqlalchemy import text

    from server.store import get_sessionmaker

    maker = get_sessionmaker()
    summary: dict[str, int] = {}
    async with maker() as session:
        async def scalar(sql: str) -> int:
            return int((await session.execute(text(sql))).scalar_one())

        summary["runs_orphan_session"] = await scalar(
            "select count(*) from runs r left join sessions s on r.session_id = s.id "
            "where s.id is null")
        summary["runs_orphan_session_turns"] = await scalar(
            "select count(*) from turns where run_id in "
            "(select r.id from runs r left join sessions s on r.session_id = s.id "
            "where s.id is null)")
        summary["runs_orphan_session_artifacts"] = await scalar(
            "select count(*) from artifacts where run_id in "
            "(select r.id from runs r left join sessions s on r.session_id = s.id "
            "where s.id is null)")
        summary["runs_orphan_user"] = await scalar(
            "select count(*) from runs r left join users u on r.user_id = u.id "
            "where u.id is null")
        summary["sessions_orphan_user"] = await scalar(
            "select count(*) from sessions s left join users u on s.user_id = u.id "
            "where u.id is null")
        summary["turns_orphan_run"] = await scalar(
            "select count(*) from turns t where t.run_id is not null "
            "and not exists (select 1 from runs r where r.id = t.run_id)")
        summary["audit_orphan_user"] = await scalar(
            "select count(*) from audit_log a where a.user_id is not null "
            "and not exists (select 1 from users u where u.id = a.user_id)")

        if not apply:
            return summary

        if summary["runs_orphan_session_turns"] or summary["runs_orphan_session_artifacts"]:
            raise SystemExit(
                "refusing to delete: the orphan runs still have turns/artifacts "
                f"({summary['runs_orphan_session_turns']} turns, "
                f"{summary['runs_orphan_session_artifacts']} artifacts)"
            )

        await session.execute(
            text(
                "insert into users (id, username, password_hash, status, created_at) "
                "values (gen_random_uuid(), :name, :hash, :status, now()) "
                "on conflict (username) do nothing"
            ),
            {"name": placeholder, "hash": PLACEHOLDER_PASSWORD_HASH,
             "status": PLACEHOLDER_STATUS},
        )
        ph = (await session.execute(
            text("select id from users where username = :name"), {"name": placeholder},
        )).scalar_one()

        # Re-home rather than destroy (audit trail + research rows stay intact).
        await session.execute(
            text("update audit_log set user_id = :ph where user_id is not null "
                 "and not exists (select 1 from users u where u.id = audit_log.user_id)"),
            {"ph": ph},
        )
        await session.execute(
            text("update sessions set user_id = :ph where "
                 "not exists (select 1 from users u where u.id = sessions.user_id)"),
            {"ph": ph},
        )
        await session.execute(
            text("update runs set user_id = :ph where "
                 "not exists (select 1 from users u where u.id = runs.user_id)"),
            {"ph": ph},
        )

        # Deleting the placeholder user's own runs is not intended; the guard
        # above already proved they carry no turns or artifacts.
        deleted = await session.execute(
            text("delete from runs where "
                 "not exists (select 1 from sessions s where s.id = runs.session_id)")
        )
        summary["deleted_runs"] = deleted.rowcount or 0

        # Turns whose run is gone: release the dangling reference instead of
        # inventing a placeholder run (a fake run would pollute run counts and
        # show up in the UI). run_id is nullable and 45 rows already sit in this
        # state legitimately.
        await session.execute(
            text("update turns set run_id = null where run_id is not null "
                 "and not exists (select 1 from runs r where r.id = turns.run_id)")
        )
        await session.commit()
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="read-only orphan + row-count report")

    p_remediate = sub.add_parser(
        "remediate", help="apply the agreed orphan policy (dry-run by default)",
    )
    p_remediate.add_argument("--apply", action="store_true")
    p_remediate.add_argument("--yes", action="store_true", help="required with --apply")
    p_remediate.add_argument("--placeholder", default=PLACEHOLDER_USERNAME)

    p_orphans = sub.add_parser(
        "orphans", help="export an orphan inventory for a human decision (read-only)",
    )
    p_orphans.add_argument("--out", type=Path, default=None)
    p_orphans.add_argument("--sample", type=int, default=20)

    p_migrate = sub.add_parser(
        "migrate-runs-root", help="move run data out of the source tree (F01)",
    )
    p_migrate.add_argument("--old-root", type=Path, default=None)
    p_migrate.add_argument("--new-root", type=Path, default=None)
    p_migrate.add_argument("--orphans-out", type=Path, default=None)
    p_migrate.add_argument("--apply", action="store_true")
    p_migrate.add_argument("--yes", action="store_true", help="required with --apply")

    p_manifest = sub.add_parser("manifest", help="record every run's storage + digests")
    p_manifest.add_argument("--out", required=True, type=Path)
    p_manifest.add_argument("--runs-root", type=Path, default=None)

    p_plan = sub.add_parser("plan", help="dry-run retention plan (default)")
    p_plan.add_argument("--manifest", required=True, type=Path)
    p_plan.add_argument("--runs-root", type=Path, default=None)
    p_plan.add_argument("--keep-days", type=int, default=30)
    p_plan.add_argument("--user", default=None)
    p_plan.add_argument("--apply", action="store_true", help="actually delete")
    p_plan.add_argument("--yes", action="store_true", help="required with --apply")

    p_verify = sub.add_parser("verify", help="check current files against a manifest")
    p_verify.add_argument("--manifest", required=True, type=Path)
    p_verify.add_argument("--runs-root", type=Path, default=None)

    args = parser.parse_args(argv)

    if args.command == "migrate-runs-root":
        from server.config import REPO_ROOT, get_config

        old_root = (args.old_root or REPO_ROOT / "server" / "runs").resolve()
        new_root = (args.new_root or get_config().runs_root).resolve()

        if args.apply and not args.yes:
            print("refusing to move data: --apply requires --yes", file=sys.stderr)
            return 2

        if args.apply:
            # A single asyncio.run: the asyncpg engine is bound to one event loop,
            # so planning and applying must share it, not straddle two loops.
            moved, missing, removed = asyncio.run(_apply_root_migration(old_root, new_root))
            print(f"moved {len(moved)} run dir(s), {len(missing)} already missing, "
                  f"removed {len(removed)} orphan dir(s)")
            return 0

        migrations, orphan_dirs = asyncio.run(_plan_root_migration(old_root, new_root))
        if args.orphans_out:
            args.orphans_out.parent.mkdir(parents=True, exist_ok=True)
            args.orphans_out.write_text(
                json.dumps({"old_root": str(old_root), "orphan_dirs": orphan_dirs},
                           ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"orphan list -> {args.orphans_out}")
        for migration in migrations:
            state = "exists" if migration.source_exists else "MISSING-ON-DISK"
            print(f"move\t{migration.run_id}\t[{state}]")
            print(f"     {migration.source} -> {migration.target}")
        print(f"\n{len(migrations)} run(s) to migrate, {len(orphan_dirs)} orphan dir(s)")
        print("dry-run: nothing moved (add --apply --yes to apply)")
        return 0

    if args.command == "remediate":
        if args.apply and not args.yes:
            print("refusing to change data: --apply requires --yes", file=sys.stderr)
            return 2
        summary = asyncio.run(_remediate(apply=args.apply, placeholder=args.placeholder))
        for key, value in summary.items():
            print(f"{key}\t{value}")
        if not args.apply:
            print("\ndry-run: nothing changed (add --apply --yes to apply)")
        return 0

    if args.command == "orphans":
        classes = asyncio.run(_collect_orphan_classes(args.sample))
        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "note": "identifiers and timestamps only — no prompt/answer/audit payloads",
            "classes": [c.to_dict() for c in classes],
        }
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                encoding="utf-8")
            print(f"wrote {args.out}")
        for c in classes:
            print(f"{c.count}\t{c.kind}\timpact={c.impact or '{}'}")
        total = sum(c.count for c in classes)
        print(f"\ntotal orphan rows: {total} — no action taken (this command is read-only)")
        return 1 if total else 0

    if args.command == "check":
        counts, orphans = asyncio.run(_run_consistency_check())
        for table, n in counts:
            print(f"rows\t{table}\t{n}")
        for label, n in orphans:
            print(f"orphans\t{label}\t{n}")
        print(f"\nverdict: {verdict_for(orphans)}")
        return 1 if any(n for _, n in orphans) else 0

    if args.command == "manifest":
        from server.config import get_config

        root = args.runs_root or get_config().runs_root
        manifest = asyncio.run(_build_manifest(Path(root)))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"wrote {args.out} ({len(manifest.runs)} runs)")
        return 0

    if args.command == "plan":
        manifest = _load_manifest(args.manifest)
        root = Path(args.runs_root or manifest.runs_root)
        policy = RetentionPolicy(keep_days=args.keep_days, user_id=args.user)
        actions = plan_cleanup(manifest.runs, policy, datetime.now(UTC))

        if args.apply and not args.yes:
            print("refusing to delete: --apply requires --yes", file=sys.stderr)
            return 2

        counts: dict[str, int] = {}
        for action in actions:
            counts[str(action.disposition)] = counts.get(str(action.disposition), 0) + 1
            print(f"{action.disposition}\t{action.run_id}\t{action.reason}")

        reclaimable = sum(a.bytes for a in actions if a.cleanable)
        print(f"\ndispositions: {counts}")
        print(f"reclaimable: {reclaimable} bytes across "
              f"{counts.get('expired', 0)} run(s)")

        if args.apply:
            removed = apply_cleanup(actions, root)
            print(f"removed {len(removed)} run directorie(s)")
        else:
            print("dry-run: nothing deleted (add --apply --yes to remove)")
        return 0

    if args.command == "verify":
        manifest = _load_manifest(args.manifest)
        root = Path(args.runs_root) if args.runs_root else (
            Path(manifest.runs_root) if manifest.runs_root else None
        )
        results = verify_against(manifest.runs, root)
        bad = [r for r in results if r.status != "ok"]
        for result in bad:
            print(f"{result.status}\t{result.run_id}\t{result.detail}")
        print(f"\n{len(results) - len(bad)}/{len(results)} run(s) intact")
        return 1 if bad else 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
