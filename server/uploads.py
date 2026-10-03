"""受控附件暂存、持久清单与发布校验（DATA-06 / AC-05、23）。

上传字节不属于数据库事务，但"有哪些附件、摘要是什么、是否已发布到 ``inputs``"必须
是持久事实：一个已提交的 Run 不能在 worker 启动时缺文件，一个回滚的提交也不能在盘上
留下无人认领、永远不会被清理的文件。

流程：

1. **校验**（:func:`plan`）：先做文件数、单文件大小与**重名**校验，全部通过才写盘 ——
   失败不留任何字节；
2. **暂存**（:func:`stage`）：写入受控暂存区 ``<run_root>/staging``，逐文件算 ``sha256``；
   落盘名即"唯一存储名"（重名已在第 1 步拒绝），因此同一 Run 内不会互相覆盖；
3. **记录发布意图**（:func:`record` / :func:`record_for_run`）：清单行与 Run/outbox
   **同一事务**写入（``status=staged``）；
4. **发布校验**（:func:`publish_for_run`）：worker 领取前逐个核对暂存文件存在且摘要一致，
   再原子移入 ``inputs`` 并置 ``published``；任一项不通过就抛错，**不派发**。可重入：
   已发布的跳过，"移动成功但提交失败"的用目标文件摘要核对后按已发布处理；
5. **补偿与孤儿清理**（:func:`discard` / :func:`sweep_orphan_staging`）：提交失败删除本次
   暂存；启动时清掉没有对应 Run 行的暂存目录。
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server import store
from server.config import build_run_paths, get_config, run_dir_for

logger = logging.getLogger(__name__)

#: 清单状态：已暂存（发布意图已记）/ 已发布（已校验并移入 inputs）。
STAGED = "staged"
PUBLISHED = "published"

_CHUNK = 1024 * 1024


class UploadError(Exception):
    """上传前置校验失败；``status_code`` 由路由映射成 HTTP 状态码。"""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class UploadPublishError(Exception):
    """发布校验失败：附件不可读或摘要不符，此时绝不能把 worker 放出去。"""


@dataclass(frozen=True)
class Planned:
    """通过校验、待在 :func:`stage` 中落盘的原始分片。"""

    part: Any
    stored_name: str
    display_name: str


@dataclass(frozen=True)
class StagedUpload:
    """已落盘并算好摘要的附件（写清单用）。"""

    display_name: str
    stored_name: str
    size_bytes: int
    sha256: str


def flatten_filename(name: str) -> str:
    """把上传名压成安全的单段 basename。

    目录分隔符、盘符与父目录标记都被替换掉，文件只可能落在 Run 自己的目录里，
    绝不会跑到客户端暗示的相邻路径。
    """
    for sep in ("/", "\\"):
        name = name.replace(sep, "_")
    name = name.replace("..", "_").replace(":", "_")
    return name.strip() or ""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def plan(files: list[Any], *, max_files: int, max_bytes: int) -> list[Planned]:
    """先做完所有前置校验（文件数 / 单文件大小 / 重名），再允许写盘。

    校验失败抛 :class:`UploadError`，调用方在任何字节落盘前就能拒绝请求。
    """
    if len(files) > max_files:
        raise UploadError(f"too many files: {len(files)} > {max_files}", status_code=413)
    planned: list[Planned] = []
    seen: set[str] = set()
    for part in files:
        raw_name = (part.filename or "").strip()
        if not raw_name:
            continue
        safe_name = flatten_filename(raw_name)
        if not safe_name:
            continue
        if safe_name in seen:
            # 同一次提交里重名会让后写的覆盖先写的：这是重名校验，不是去重。
            raise UploadError(f"duplicate file name: {safe_name}", status_code=409)
        data = await part.read()
        if len(data) > max_bytes:
            raise UploadError(
                f"file {safe_name} too large: {len(data)} > {max_bytes} bytes", status_code=413
            )
        # 让 :func:`stage` 能重新读一遍：校验与写盘分成两趟，避免边校验边落盘。
        await part.seek(0)
        seen.add(safe_name)
        planned.append(Planned(part=part, stored_name=safe_name, display_name=safe_name))
    return planned


async def stage(run_id: str, planned: list[Planned]) -> list[StagedUpload]:
    """把校验过的分片写进受控暂存区。整批要么全落盘，要么一个不留。"""
    if not planned:
        return []
    staging = build_run_paths(run_id)["staging"]
    staged: list[StagedUpload] = []
    try:
        for item in planned:
            data = await item.part.read()
            (staging / item.stored_name).write_bytes(data)
            staged.append(
                StagedUpload(
                    display_name=item.display_name,
                    stored_name=item.stored_name,
                    size_bytes=len(data),
                    sha256=_sha256_bytes(data),
                )
            )
    except BaseException:
        discard(run_id)
        raise
    return staged


def record(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    staged: list[StagedUpload],
) -> list[store.RunUpload]:
    """在调用方事务里记录发布意图（只 add + flush，不提交）。"""
    rows: list[store.RunUpload] = []
    for item in staged:
        row = store.RunUpload(
            run_id=run_id,
            user_id=user_id,
            display_name=item.display_name,
            stored_name=item.stored_name,
            size_bytes=item.size_bytes,
            sha256=item.sha256,
            status=STAGED,
        )
        session.add(row)
        rows.append(row)
    return rows


async def record_for_run(run_id: uuid.UUID, user_id: uuid.UUID, staged: list[StagedUpload]) -> None:
    """旧客户端直投路径的手动事务记录（无 outbox 时的等价落库）。"""
    if not staged:
        return
    async with store.get_sessionmaker()() as session, session.begin():
        record(session, run_id=run_id, user_id=user_id, staged=staged)


async def publish_for_run(run_id: uuid.UUID) -> int:
    """按清单校验暂存附件并发布到 ``inputs``；返回本次发布数量。

    可重入：已发布的跳过；``staging`` 里找不到但 ``inputs`` 已有且摘要一致的（上一次
    移动成功、提交失败的残局）按已发布处理。任何不可恢复的不一致都抛
    :class:`UploadPublishError`，由调用方决定退避重试或放弃 —— 绝不带着缺失附件启动 worker。
    """
    run_id_hex = run_id.hex
    published = 0
    paths = build_run_paths(run_id_hex)
    staging = paths["staging"]
    inputs = paths["inputs"]
    async with store.get_sessionmaker()() as session, session.begin():
        rows = (
            (
                await session.execute(
                    select(store.RunUpload).where(
                        store.RunUpload.run_id == run_id,
                        store.RunUpload.status == STAGED,
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            source = staging / row.stored_name
            dest = inputs / row.stored_name
            if not source.exists():
                if dest.exists() and _sha256_file(dest) == row.sha256:
                    row.status = PUBLISHED
                    row.published_at = datetime.now(UTC)
                    published += 1
                    continue
                raise UploadPublishError(f"暂存附件缺失：{row.stored_name}")
            if _sha256_file(source) != row.sha256:
                raise UploadPublishError(f"暂存附件摘要不符：{row.stored_name}")
            # 同一文件系统内的原子移动：worker 要么看不到，要么看到完整文件。
            source.replace(dest)
            row.status = PUBLISHED
            row.published_at = datetime.now(UTC)
            published += 1
    if published:
        _prune_empty_staging(staging)
    return published


def _prune_empty_staging(staging: Path) -> None:
    with contextlib.suppress(OSError):
        # 还有别的文件（并发或未发布项）就留着，不是错误。
        staging.rmdir()


def discard(run_id: str) -> None:
    """提交失败/回滚时的可重入补偿：删掉本次的整个 Run 目录。"""
    shutil.rmtree(run_dir_for(run_id), ignore_errors=True)


async def sweep_orphan_staging(*, keep_seconds: int = 3600) -> int:
    """启动时清理"没有对应 Run 行"的暂存目录（提交失败留下的孤儿）。

    只清理早于 ``keep_seconds`` 的目录，避免和正在进行的提交抢目录。返回清理数量。
    """
    root = get_config().runs_root
    if not root.exists():
        return 0
    cutoff = time.time() - keep_seconds
    removed = 0
    candidates: list[tuple[Path, uuid.UUID]] = []
    for staging in root.glob("*/staging"):
        try:
            if staging.stat().st_mtime > cutoff:
                continue
            candidates.append((staging, uuid.UUID(staging.parent.name)))
        except (ValueError, OSError):
            continue
    if not candidates:
        return 0
    async with store.get_sessionmaker()() as session:
        for staging, run_uuid in candidates:
            exists = await session.get(store.Run, run_uuid)
            if exists is not None:
                continue
            shutil.rmtree(staging, ignore_errors=True)
            removed += 1
    return removed
