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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="read-only orphan + row-count report")

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
