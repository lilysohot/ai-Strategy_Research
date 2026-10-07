"""恢复/迁移核对与后台任务闸门（DATA-14 / PR-BIZ-06）。

逻辑恢复可在原 PG 实例的独立库与测试目录进行；实例/卷故障使用独立故障环境。恢复后**一次核对**：

- **数据库备份水位**：``alembic_version`` 与当前迁移链 head 一致（缺迁移即失败）。
- **Run 目录迁移清单**：每个 Run 行对应目录存在，且 inputs / ws/outputs / spill / run /
  diff（回滚基线）/ staging 齐备；已启动 Run 的轨迹文件存在 —— 缺文件明确报错。
- **跨表引用完整性**：outbox / 快照 / 监控事件 / 事件→Run 代次 / 补数 / 通知对 Run、规则、
  事件的引用无孤立行。
- **外部调用水位**：WatchEventRun、预算 runs_created、RunDispatch 计数与 pending 事件数，
  供恢复后对照备份快照，**避免回滚后重复付费分析**。
- **密钥**：任何用户的默认 LLM 凭据解密失败即明确报错（缺密钥）。

恢复/迁移模式（``restore_mode``，默认 False）**默认禁止派发与行情消费**：dispatch/monitor/auto
后台循环不启动、运行中循环见到即停、手动提交 Run 拒绝；核对上述清单后**显式关闭**才恢复后台
任务。已有待处理监控事件由调度器按规则版本/有效期/取消状态重新裁决，不盲目重播。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from server import store
from server.config import REPO_ROOT, get_config, run_dir_for

logger = logging.getLogger(__name__)

#: Run 目录迁移清单（与 config.build_run_paths + diff.DiffRecorder 对齐）。
REQUIRED_RUN_DIRS = (
    "inputs",
    "ws",
    "ws/outputs",
    "spill",
    "run",
    "diff",
    "staging",
)
TRAJECTORY_RELPATH = Path("run") / "agent" / "trajectories" / "react_agent.jsonl"


def current_schema_head() -> str | None:
    """从迁移链解析当前 head（与 alembic_version 比对 = 备份水位）。"""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(REPO_ROOT / "server" / "alembic.ini"))
        return ScriptDirectory.from_config(cfg).get_current_head()
    except Exception:  # pragma: no cover - 配置缺失时明确失败由调用方处理
        logger.exception("resolve schema head failed")
        return None


def background_tasks_allowed() -> bool:
    """恢复/迁移模式关闭后台任务：禁止派发与行情消费（DATA-14）。"""
    return not get_config().restore_mode


async def _count_orphans(
    session: AsyncSession, *, child: Any, child_fk: Any, parent: type[Any], parent_pk: Any
) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(child)
                .where(
                    child_fk.is_not(None),
                    child_fk.not_in(select(parent_pk)),
                )
            )
        ).scalar_one()
    )


async def check_restore(
    session: AsyncSession,
    *,
    runs_root: Path | None = None,
    expected_head: str | None = None,
    max_users_for_keys: int = 100,
) -> dict[str, Any]:
    """只读核对：返回结构化报告；``ok`` 为 False 时不得恢复后台任务。

    AC-18「报告不可读时明确标识」：schema 水位先核（任何还原库都有
    ``alembic_version``）；其后任一分节因缺表/库错误失败时，把失败本身记入
    ``errors`` 并返回部分报告，而不是让核对崩溃、让操作员失去水位信息。
    """
    runs_root = Path(runs_root or get_config().runs_root)
    errors: list[str] = []

    # 1) 数据库备份水位。
    version = (
        await session.execute(text("select version_num from alembic_version"))
    ).scalar_one_or_none()
    head = expected_head or current_schema_head()
    schema_ok = version is not None and head is not None and version == head
    if not schema_ok:
        errors.append(f"schema watermark mismatch: version={version} head={head}")

    missing_dirs: list[str] = []
    missing_trajectories: list[str] = []
    relations: dict[str, int] = {}
    external_calls: dict[str, int] = {}
    bad_keys: list[str] = []
    run_count = 0
    try:
        # 2) Run 目录迁移清单（缺目录/缺轨迹文件 → 明确报错）。
        run_ids = (await session.execute(select(store.Run.id, store.Run.status))).all()
        run_count = len(run_ids)
        for run_id, run_status in run_ids:
            run_dir = run_dir_for(str(run_id))
            if not (runs_root / run_id.hex).exists() and not run_dir.exists():
                missing_dirs.append(f"{run_id.hex} (run dir missing)")
                continue
            for rel in REQUIRED_RUN_DIRS:
                if not (run_dir / rel).exists():
                    missing_dirs.append(f"{run_id.hex}/{rel}")
            if run_status != "queued" and not (run_dir / TRAJECTORY_RELPATH).exists():
                missing_trajectories.append(run_id.hex)
        if missing_dirs:
            errors.append(f"missing run dirs: {sorted(missing_dirs)[:20]}")
        if missing_trajectories:
            errors.append(f"missing trajectories: {sorted(missing_trajectories)[:20]}")

        # 3) 跨表引用完整性。
        orphan_checks = [
            (
                "RunDispatch.run_id",
                store.RunDispatch,
                store.RunDispatch.run_id,
                store.Run,
                store.Run.id,
            ),
            (
                "RunInvestmentSnapshot.run_id",
                store.RunInvestmentSnapshot,
                store.RunInvestmentSnapshot.run_id,
                store.Run,
                store.Run.id,
            ),
            (
                "WatchEvent.run_id",
                store.WatchEvent,
                store.WatchEvent.run_id,
                store.Run,
                store.Run.id,
            ),
            (
                "WatchEventRun.event_id",
                store.WatchEventRun,
                store.WatchEventRun.event_id,
                store.WatchEvent,
                store.WatchEvent.id,
            ),
            (
                "WatchEventRun.run_id",
                store.WatchEventRun,
                store.WatchEventRun.run_id,
                store.Run,
                store.Run.id,
            ),
            (
                "InputRequest.source_run_id",
                store.InputRequest,
                store.InputRequest.source_run_id,
                store.Run,
                store.Run.id,
            ),
            (
                "InputRequest.watch_event_id",
                store.InputRequest,
                store.InputRequest.watch_event_id,
                store.WatchEvent,
                store.WatchEvent.id,
            ),
            (
                "BusinessEvent.run_id",
                store.BusinessEvent,
                store.BusinessEvent.run_id,
                store.Run,
                store.Run.id,
            ),
        ]
        for name, child, child_fk, parent, parent_pk in orphan_checks:
            count = await _count_orphans(
                session, child=child, child_fk=child_fk, parent=parent, parent_pk=parent_pk
            )
            relations[name] = count
            if count:
                errors.append(f"orphan {name}: {count}")

        # 4) 外部调用水位（恢复后对照备份，防重复付费分析）。
        event_runs = (
            await session.execute(select(func.count()).select_from(store.WatchEventRun))
        ).scalar_one()
        runs_created = (
            await session.execute(
                select(func.coalesce(func.sum(store.WatchBudgetUsage.runs_created), 0))
            )
        ).scalar_one()
        dispatches = (
            await session.execute(select(func.count()).select_from(store.RunDispatch))
        ).scalar_one()
        pending_events = (
            await session.execute(
                select(func.count())
                .select_from(store.WatchEvent)
                .where(store.WatchEvent.status == "pending")
            )
        ).scalar_one()
        external_calls = {
            "watch_event_runs": int(event_runs),
            "budget_runs_created": int(runs_created),
            "run_dispatch_rows": int(dispatches),
            "pending_watch_events": int(pending_events),
        }

        # 5) 密钥：任何用户默认 LLM 凭据解密失败 → 明确报错。
        user_ids = (
            (await session.execute(select(store.User.id).limit(max_users_for_keys))).scalars().all()
        )
        for user_id in user_ids:
            state = await store.user_llm_cred_state(user_id=user_id)
            if state == "error":
                bad_keys.append(str(user_id))
        if bad_keys:
            errors.append(f"undecryptable llm keys: {bad_keys[:10]}")
    except Exception as exc:  # AC-18：报告不可读 → 明确标识，而非崩溃丢失水位信息。
        logger.exception("restore check section failed")
        errors.append(f"restore check incomplete: {exc}")

    return {
        "ok": not errors,
        "schema": {"alembic_version": version, "expected_head": head, "ok": schema_ok},
        "runs": {
            "run_count": run_count,
            "missing_dirs": missing_dirs[:20],
            "missing_trajectories": missing_trajectories[:20],
        },
        "relations": relations,
        "external_calls": external_calls,
        "credential_errors": bad_keys,
        "errors": errors,
    }


async def _main() -> None:
    """CLI：`SERVER_DATABASE_URL=... python -m server.restore_check [runs_root]`。"""
    import sys

    from server import business_service as biz

    runs_root = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    async with biz.business_transaction() as session:
        report = await check_restore(session, runs_root=runs_root)
    import json

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    asyncio.run(_main())
