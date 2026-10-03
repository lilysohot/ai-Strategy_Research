"""Run 派发 outbox：持久化、租约领取、研究级串行与恢复（DATA-06）。

一个业务 Run 的"提交成功"必须独立于提交它的那个 API 进程的存活：资料、快照、
Run 行、用户消息与**待派发意图**在同一个事务里提交；之后由本模块的派发循环把
意图变成 worker。提交成功但进程崩溃，重启后派发可以继续；提交失败则什么都不
存在，不会出现"资料已保存但分析永远不来"（AC-05/23）。

派发是可恢复状态，不是内存副作用：

* **领取**：``SKIP LOCKED`` 抢占 due 的行，写租约（owner/到期）并递增领取版本；
  多进程共享派发工作时互不重复。
* **研究级串行**：领取时若同研究已有 queued/running 的 Run，本次领取改为延后
  （研究忙退避），保证同研究不并发执行；判定基于库而不是内存，跨进程成立。
* **租约过期**：不直接重投。先核定旧 worker 状态 —— Run 已启动（running 或终态）
  就不再重投；仍是 queued 才允许回到 pending。领取版本让过期领取者的回报失效。
* **失败**：submit 抛错记为 ``retryable_failed`` 并退避；重试耗尽 → ``abandoned``。
  重试复用**原 Run**，不重复业务写入。
* **附件门禁**：投递前先按上传清单校验暂存附件并发布到 ``inputs``（见
  :mod:`server.uploads`）；文件缺失或摘要不符就不投递，避免"数据库成功但启动缺文件"。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server import store, uploads
from server.config import get_config

logger = logging.getLogger(__name__)

#: 契约 §7 的派发状态；与 Run 状态分离。
PENDING = "pending"
CLAIMED = "claimed"
DISPATCHED = "dispatched"
RETRYABLE_FAILED = "retryable_failed"
ABANDONED = "abandoned"

#: 计入"研究队列深度"的状态：还在等着被执行（或被取消）的派发意图。
QUEUE_STATUSES = (PENDING, RETRYABLE_FAILED, CLAIMED, DISPATCHED)

#: 实例身份：租约 owner。领取互斥靠行锁与租约到期，不靠 owner 全局唯一。
_OWNER = f"api-{uuid.uuid4().hex[:12]}"


def _now() -> datetime:
    return datetime.now(UTC)


async def enqueue(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    research_id: uuid.UUID,
    session_key: str,
    prompt: str,
    prompt_addendum: str = "",
    max_attempts: int | None = None,
) -> store.RunDispatch:
    """在同一事务内登记派发意图（只 flush，不提交）。"""
    cfg = get_config()
    row = store.RunDispatch(
        run_id=run_id,
        user_id=user_id,
        research_id=research_id,
        session_key=session_key,
        prompt=prompt,
        prompt_addendum=prompt_addendum or None,
        status=PENDING,
        max_attempts=max_attempts if max_attempts is not None else cfg.dispatch_max_attempts,
        claim_version=0,
    )
    session.add(row)
    await session.flush()
    return row


async def get_for_run(session: AsyncSession, *, run_id: uuid.UUID) -> store.RunDispatch | None:
    return (
        await session.execute(select(store.RunDispatch).where(store.RunDispatch.run_id == run_id))
    ).scalar_one_or_none()


def _is_recoverable(dispatch_status: str, run_status: str) -> bool:
    """这条派发意图是否"提交成功但还没产生 worker"—— 重启后由派发循环接手。

    * ``pending`` / ``retryable_failed``：还没投出去，会被领取；
    * ``claimed`` 且 Run 仍是 ``queued``：旧领取从未把 worker 跑起来，租约回收会重投。
    ``dispatched``/``abandoned`` 以及「``claimed`` 且 Run 已 ``running``」都不算 ——
    前者 worker 已随进程消失，后者是真正的孤儿。
    """
    if dispatch_status in (PENDING, RETRYABLE_FAILED):
        return True
    return dispatch_status == CLAIMED and run_status == "queued"


async def recoverable_run_ids(session: AsyncSession, run_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """返回有存活派发意图的 Run —— 孤儿扫描必须跳过它们。

    一个已提交、只在等派发的 Run 崩溃后仍是 ``queued`` 且没有本进程的内存 handle；
    若 :meth:`Orchestrator.reconcile_orphan_runs` 只看 handles 就把它判死并作废
    outbox，"提交成功但进程崩溃，重启后派发可以继续" 的承诺就落空了（AC-05）。
    判定基于库里的派发状态，跨进程成立。
    """
    if not run_ids:
        return set()
    result = await session.execute(
        select(store.RunDispatch.run_id, store.RunDispatch.status, store.Run.status)
        .join(store.Run, store.Run.id == store.RunDispatch.run_id)
        .where(store.RunDispatch.run_id.in_(run_ids))
    )
    return {
        run_id
        for run_id, dispatch_status, run_status in result
        if _is_recoverable(dispatch_status, run_status)
    }


async def research_queue_depth(
    session: AsyncSession, research_id: uuid.UUID, *, exclude_run: uuid.UUID | None = None
) -> int:
    """同研究"会执行"的派发意图数量 —— 逐研究队列上限的判据（DATA-06）。

    ``abandoned`` 不算：它不会被投递，也不占队列。``exclude_run`` 用于重算：被取代的
    旧 Run 即将在同一事务里作废，不该把它计入、把新 Run 顶到上限之外。
    """
    statement = (
        select(func.count())
        .select_from(store.RunDispatch)
        .join(store.Run, store.Run.id == store.RunDispatch.run_id)
        .where(
            store.RunDispatch.research_id == research_id,
            store.RunDispatch.status.in_(QUEUE_STATUSES),
            store.Run.status.in_(["queued", "running"]),
        )
    )
    if exclude_run is not None:
        statement = statement.where(store.RunDispatch.run_id != exclude_run)
    return int((await session.execute(statement)).scalar_one())


def dispatch_view(row: store.RunDispatch) -> dict[str, Any]:
    return {
        "dispatch_id": str(row.id),
        "run_id": row.run_id.hex,
        "status": row.status,
        "attempt": row.attempt,
        "max_attempts": row.max_attempts,
        "lease_owner": row.lease_owner,
        "lease_expires_at": row.lease_expires_at.isoformat() if row.lease_expires_at else None,
        "next_attempt_at": row.next_attempt_at.isoformat() if row.next_attempt_at else None,
        "last_error": row.last_error,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _research_has_active_run(
    session: AsyncSession, research_id: uuid.UUID, exclude_run: uuid.UUID
) -> bool:
    """同研究是否已有"会执行"的 Run —— 研究级互斥的判据，基于库，跨进程成立。

    ``queued`` 不等于会执行：还在等 outbox 派发的行（pending/retryable_failed/
    abandoned）不会自己跑起来，真正占住研究的是——

    * status = ``running``（worker 在跑）；
    * status = ``queued`` 且没有 outbox 行（旧客户端直投路径，必执行）；
    * status = ``queued`` 且 outbox 行已被领取/投出（已在编排器队列里）。
    """
    claimed_or_dispatched = (
        select(store.RunDispatch.run_id)
        .where(
            store.RunDispatch.run_id == store.Run.id,
            store.RunDispatch.status.in_([CLAIMED, DISPATCHED]),
        )
        .exists()
    )
    awaiting_dispatch = (
        select(store.RunDispatch.run_id)
        .where(
            store.RunDispatch.run_id == store.Run.id,
            store.RunDispatch.status.in_([PENDING, RETRYABLE_FAILED, ABANDONED]),
        )
        .exists()
    )
    busy = (store.Run.status == "running") | (
        (store.Run.status == "queued") & (~awaiting_dispatch | claimed_or_dispatched)
    )
    result = await session.execute(
        select(store.Run.id).where(
            store.Run.session_id == research_id,
            store.Run.id != exclude_run,
            busy,
        )
    )
    return result.first() is not None


async def claim_due(session: AsyncSession, *, limit: int = 8) -> list[store.RunDispatch]:
    """领取到期的待派发行；返回本轮要投递的行。

    * 研究忙：改 ``next_attempt_at`` 延后，不算失败（AC-13 串行语义）；
    * Run 已不在 queued（被取消/已终态）：行置 abandoned，不再投递；
    * 正常候选：写租约并递增领取版本。
    """
    now = _now()
    cfg = get_config()
    claimed: list[store.RunDispatch] = []
    result = await session.execute(
        select(store.RunDispatch)
        .where(
            store.RunDispatch.status.in_([PENDING, RETRYABLE_FAILED]),
            (store.RunDispatch.next_attempt_at.is_(None))
            | (store.RunDispatch.next_attempt_at <= now),
        )
        .order_by(store.RunDispatch.created_at)
        .limit(limit * 2)
        .with_for_update(skip_locked=True)
    )
    for row in result.scalars():
        if len(claimed) >= limit:
            break
        run = await session.get(store.Run, row.run_id)
        if run is None or run.status != "queued":
            row.status = ABANDONED
            row.last_error = "run 已不在排队状态，取消派发"
            continue
        # Lock the research, not only this outbox row: another dispatcher may
        # have selected a different row belonging to the same research.
        research = (
            await session.execute(
                select(store.Session)
                .where(
                    store.Session.id == row.research_id,
                )
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if research is None:
            continue
        if research.deleted_at is not None:
            row.status = ABANDONED
            row.last_error = "研究已删除"
            continue
        if await _research_has_active_run(session, row.research_id, row.run_id):
            row.next_attempt_at = now + timedelta(seconds=cfg.dispatch_busy_delay_seconds)
            continue
        row.status = CLAIMED
        row.attempt += 1
        row.claim_version += 1
        row.lease_owner = _OWNER
        row.lease_expires_at = now + timedelta(seconds=cfg.dispatch_lease_seconds)
        claimed.append(row)
    await session.flush()
    return claimed


async def mark_dispatched(session: AsyncSession, row_id: uuid.UUID, *, claim_version: int) -> bool:
    """投递成功回报；领取版本不符（租约已被他人接管）时忽略本次回报。"""
    current = await session.get(store.RunDispatch, row_id, with_for_update=True)
    if current is None or current.claim_version != claim_version or current.status != CLAIMED:
        return False
    current.status = DISPATCHED
    current.lease_owner = None
    current.lease_expires_at = None
    current.last_error = None
    await session.flush()
    return True


async def mark_submit_failed(
    session: AsyncSession, row_id: uuid.UUID, *, claim_version: int, error: str
) -> None:
    """投递失败：退避重试；重试耗尽置 abandoned（Run 保持 queued 可被取消重提）。"""
    current = await session.get(store.RunDispatch, row_id, with_for_update=True)
    if current is None or current.claim_version != claim_version or current.status != CLAIMED:
        return
    current.last_error = error[:2000]
    if current.attempt >= current.max_attempts:
        current.status = ABANDONED
    else:
        current.status = RETRYABLE_FAILED
        current.next_attempt_at = _now() + timedelta(seconds=min(60, 2**current.attempt))
    await session.flush()


async def reclaim_expired(session: AsyncSession) -> int:
    """回收过期租约 —— 先核定旧 worker 状态，再决定是否重新可领。

    * Run 已 running 或终态：旧 worker 确实在跑/已收尾，**绝不**重投第二个；
      行落 dispatched（在跑）或 abandoned（已终态且无人回报）。
    * Run 仍 queued：原领取从未把 worker 跑起来，回到 pending 允许重新领取。
    """
    now = _now()
    result = await session.execute(
        select(store.RunDispatch)
        .where(
            store.RunDispatch.status == CLAIMED,
            store.RunDispatch.lease_expires_at.is_not(None),
            store.RunDispatch.lease_expires_at < now,
        )
        .with_for_update(skip_locked=True)
    )
    released = 0
    for row in result.scalars():
        run = await session.get(store.Run, row.run_id)
        if run is None:
            row.status = ABANDONED
            row.last_error = "run 记录缺失"
            released += 1
        elif run.status == "queued":
            row.status = PENDING
            row.claim_version += 1
            row.next_attempt_at = now
            row.lease_owner = None
            row.lease_expires_at = None
            row.last_error = "租约过期：原领取未启动 worker，重新可领"
            released += 1
        elif run.status == "running":
            row.status = DISPATCHED
            row.lease_owner = None
            row.lease_expires_at = None
            row.last_error = "租约过期但 worker 已启动，不重投"
            released += 1
        else:
            row.status = ABANDONED
            row.lease_owner = None
            row.lease_expires_at = None
            row.last_error = f"租约过期且 run 已终态（{run.status}），不再投递"
            released += 1
    await session.flush()
    return released


async def cancel_pending(session: AsyncSession, *, run_id: uuid.UUID, reason: str) -> bool:
    """取消尚未投递的派发（排队任务"取消重提"的取消半边）。

    只有 ``pending``/``retryable_failed`` 可以安全取消：claimed 的行属于某个
    活跃派发者，可能下一毫秒就投出去；已 dispatched 的由编排器/worker 负责。
    """
    row = await get_for_run(session, run_id=run_id)
    if row is None or row.status not in (PENDING, RETRYABLE_FAILED):
        return False
    row.status = ABANDONED
    row.last_error = reason[:2000]
    await session.flush()
    return True


async def abandon_for_run(session: AsyncSession, *, run_id: uuid.UUID, reason: str) -> bool:
    """孤儿恢复联动：Run 被判定为无人认领时，其派发意图一并作废。"""
    row = await get_for_run(session, run_id=run_id)
    if row is None or row.status in (DISPATCHED, ABANDONED):
        return False
    row.status = ABANDONED
    row.last_error = reason[:2000]
    await session.flush()
    return True


async def dispatch_once(orch: Any) -> int:
    """一轮：回收过期租约 → 领取 → 投递 → 回报。返回本轮投递数。"""
    dispatched = 0
    async with store.get_sessionmaker()() as session, session.begin():
        await reclaim_expired(session)
        claimed = await claim_due(session)
        # 先取参数快照再提交领取事务：投递必须发生在租约已落库之后。
        batch = [
            (
                row.id,
                row.run_id,
                row.session_key,
                row.prompt,
                row.prompt_addendum or "",
                row.user_id,
                row.claim_version,
            )
            for row in claimed
        ]

    for row_id, run_id, session_key, prompt, addendum, user_id, claim_version in batch:
        try:
            # 附件门禁：worker 只能看到已校验并发布的 inputs。暂存文件缺失或摘要不符
            # 时这里抛错，于是投递失败退避重试，绝不会"数据库成功但启动缺文件"。
            await uploads.publish_for_run(run_id)
            # Fence the side effect itself. Keep the claim locked through the
            # enqueue and receipt commit so reclamation cannot interleave here.
            async with store.get_sessionmaker()() as session, session.begin():
                row = await session.get(store.RunDispatch, row_id, with_for_update=True)
                if (
                    row is None
                    or row.status != CLAIMED
                    or row.claim_version != claim_version
                    or row.lease_expires_at is None
                    or row.lease_expires_at.replace(tzinfo=UTC) <= _now()
                ):
                    continue
                run = await session.get(store.Run, run_id)
                research = await session.get(store.Session, row.research_id)
                if (
                    run is None
                    or run.status != "queued"
                    or research is None
                    or research.deleted_at is not None
                ):
                    row.status = ABANDONED
                    continue
                await orch.submit(
                    run_id=run_id.hex,
                    session_id=session_key,
                    prompt=prompt,
                    user_id=user_id,
                    agent_tools="",
                    prompt_addendum=addendum,
                    backfill_turn=False,
                )
                await mark_dispatched(session, row_id, claim_version=claim_version)
                dispatched += 1
        except Exception as exc:
            logger.warning("outbox dispatch submit failed for %s: %s", run_id.hex, exc)
            async with store.get_sessionmaker()() as session, session.begin():
                await mark_submit_failed(
                    session, row_id, claim_version=claim_version, error=str(exc)
                )
            continue
    return dispatched


async def dispatch_loop(orch: Any) -> None:
    """常驻派发循环；随 API 进程生命周期启停（见 ``app.lifespan``）。"""
    cfg = get_config()
    while True:
        try:
            await dispatch_once(orch)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("dispatch loop iteration failed")
        await asyncio.sleep(cfg.dispatch_poll_seconds)
