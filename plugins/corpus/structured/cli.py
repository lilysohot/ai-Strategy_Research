"""Explicit process entry points for structured plan, execution, replay, and audit."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import Literal, cast

from pydantic import ValidationError

from plugins.corpus.structured.config import load_extraction_config
from plugins.corpus.structured.ledger import (
    BatchCheck,
    BatchPlan,
    StructuredExecutionError,
    check_batch,
    execute_batch,
    plan_batch,
    replay_batch,
)
from plugins.corpus.structured.snapshot import EvidenceSnapshot, SnapshotIntegrityError

Role = Literal["claims", "material_items", "material_relations"]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m plugins.corpus.structured.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    plan = commands.add_parser("plan", help="freeze a zero-call execution plan")
    plan.add_argument("--snapshot", required=True)
    plan.add_argument("--out", required=True)
    plan.add_argument("--max-attempts", type=int, default=0)
    plan.add_argument(
        "--role-budget",
        action="append",
        default=[],
        metavar="ROLE=COUNT",
        help="optional per-role ceiling; batch ceiling still applies",
    )
    plan.add_argument("--max-relation-tasks", type=int, default=1)
    plan.add_argument("--max-relation-attempts", type=int)
    plan.add_argument("--disable-relations", action="store_true")
    plan.add_argument("--deadline-epoch", type=float)
    plan.add_argument("--currency")

    execute = commands.add_parser("execute", help="run explicitly authorized model adapters")
    execute.add_argument("--plan", required=True)
    execute.add_argument("--store-root")
    execute.add_argument("--allow-model", action="store_true")

    replay = commands.add_parser("replay", help="consume an explicit local response directory")
    replay.add_argument("--plan", required=True)
    replay.add_argument("--responses", required=True)
    replay.add_argument("--store-root")

    check = commands.add_parser("check", help="read one batch without mutations or requests")
    check.add_argument("--batch-id", required=True)
    check.add_argument("--store-root")
    return parser


def _read_snapshot(path: str) -> EvidenceSnapshot:
    try:
        snapshot = EvidenceSnapshot.model_validate_json(Path(path).read_text(encoding="utf-8"))
        snapshot.verify_identity()
        return snapshot
    except (OSError, UnicodeError, ValidationError, SnapshotIntegrityError) as exc:
        raise StructuredExecutionError("CS_INPUT_INVALID", "snapshot_invalid") from exc


def _read_plan(path: str) -> BatchPlan:
    try:
        plan = BatchPlan.model_validate_json(Path(path).read_text(encoding="utf-8"))
        plan.verify_identity()
        return plan
    except (OSError, UnicodeError, ValidationError, StructuredExecutionError) as exc:
        raise StructuredExecutionError("CS_INPUT_INVALID", "plan_invalid") from exc


def _write_plan(path: str, plan: BatchPlan) -> None:
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".pending", dir=target.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(plan.model_dump_json(indent=2))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary)
    except OSError as exc:
        raise StructuredExecutionError("CS_INPUT_INVALID", "plan_output_unwritable") from exc


def _role_budgets(values: list[str]) -> dict[Role, int]:
    result: dict[Role, int] = {}
    for value in values:
        try:
            role, raw_count = value.split("=", 1)
            count = int(raw_count)
        except (ValueError, TypeError) as exc:
            raise StructuredExecutionError("CS_INPUT_INVALID", "invalid_role_budget") from exc
        if role not in {"claims", "material_items", "material_relations"} or count < 0:
            raise StructuredExecutionError("CS_INPUT_INVALID", "invalid_role_budget")
        result[cast(Role, role)] = count
    return result


def _output(value: object) -> None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")  # type: ignore[union-attr]
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _result_exit(check: BatchCheck) -> int:
    statuses = {attempt.execution_status for attempt in check.ledger.attempts}
    task_statuses = {task.execution_status for task in check.ledger.tasks}
    error_codes = {code for task in check.ledger.tasks for code in task.error_codes}
    if "outcome_unknown" in statuses | task_statuses or "CS_OUTCOME_UNKNOWN" in error_codes:
        return 6
    if "CS_CONFIG_MISSING" in error_codes:
        return 3
    if statuses & {"reserved", "running"}:
        return 6
    if task_statuses & {
        "blocked",
        "deferred",
        "cancelled",
        "planned",
        "ready",
        "reserved",
        "running",
    }:
        return 4
    if task_statuses & {"failed"}:
        return 2
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run one structured ledger command and return its frozen process exit code."""

    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            snapshot = _read_snapshot(args.snapshot)
            config = load_extraction_config()
            role_budgets = _role_budgets(args.role_budget)
            plan = plan_batch(
                snapshot,
                config=config,
                max_attempts=args.max_attempts,
                role_max_attempts=role_budgets or None,
                currency=args.currency,
                relations_enabled=not args.disable_relations,
                max_relation_tasks=args.max_relation_tasks,
                max_relation_attempts=args.max_relation_attempts,
                deadline_epoch=args.deadline_epoch,
            )
            _write_plan(args.out, plan)
            _output(
                {
                    "batch_id": plan.batch_id,
                    "plan_sha256": plan.plan_sha256,
                    "snapshot_id": plan.snapshot.snapshot_id,
                    "model_requests": 0,
                }
            )
            return 0
        if args.command == "execute":
            plan = _read_plan(args.plan)
            result = execute_batch(
                plan,
                store_root=args.store_root,
                allow_model=args.allow_model,
                config=load_extraction_config(),
            )
        elif args.command == "replay":
            plan = _read_plan(args.plan)
            result = replay_batch(
                plan,
                responses=Path(args.responses).resolve(),
                store_root=args.store_root,
            )
        else:
            result = check_batch(args.batch_id, store_root=args.store_root)
        _output(result)
        return _result_exit(result)
    except StructuredExecutionError as exc:
        print(f"{exc.code}: {exc.reason}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
