"""来源接收、源变化检查与内容寻址归档（任务 I1-6，架构 v1.1 §5.1 + §4.1）。

接收协议（架构 §5.1，全部为本地确定性代码，无模型调用、无网络/PG 连接）：

1. 只处理**显式路径**（冻结清单由 I1-7 engine 编排逐条传入），不递归扫描工作区；
   扩展名 + 文件签名 + 可读性校验复用 :func:`readers.base.detect_format`，另有
   非空与大小上限（:class:`IngestLimits`）。
2. 读取完整字节并计算 SHA-256（``source_id`` 仅由原始字节决定，§4.1）；接收后
   重读源文件复核哈希——前后不一致即拒绝，**不把尚未复制完成/正在变化的文件
   登记为成功**。字节读取可注入测试替身（架构 §9）。
3. 暂存副本写齐并回读核验哈希后，经 ``os.replace`` **原子置入**内容寻址目录
   （``<archive_root>/<sha256[:2]>/<sha256><ext>``）；已存在同名对象先核验哈希，
   不符即拒绝（怀疑篡改/冲突，**绝不覆盖**）。用户原目录只读，不删除、不改写。
4. 登记顺序为**归档先行、登记在后**：``put_source`` 失败时归档仍保留且可独立
   核验（返回 ``registered=False`` 的 :class:`IngestOutcome`），由
   :func:`register_archived_source` 恢复流程接管——不把文件系统与数据库冒充
   一个跨系统事务。
5. 文件内容中的命令、角色说明和系统提示始终是**来源数据**，不获得任何执行
   权限；本模块对内容只做字节级哈希与复制，不做任何解释执行。

重复执行幂等：同字节 → 同 ``source_id`` → 同归档路径 → 同登记记录；路径改名
不改变来源身份（已登记则首记录为准，不重复登记）；源文件更新产生新
``source_id``（:func:`check_source_change` 只报告变化，绝不就地覆盖旧版本）。
表驱动用例见 tests/test_corpus_preparation_source.py。
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from plugins.corpus.preparation.contract import (
    DocumentFormat,
    Source,
    sha256_of_bytes,
)
from plugins.corpus.preparation.readers.base import ReaderError, detect_format
from plugins.corpus.preparation.repository import Store, StoreError

INGEST_REV = "ingest-1"

# 大小上限默认值：防御性接收限制（显式路径仍受此约束），可按 IngestLimits 覆盖。
DEFAULT_MAX_BYTES = 64 * 1024 * 1024

_MIME_TYPES: dict[DocumentFormat, str] = {
    DocumentFormat.PDF: "application/pdf",
    DocumentFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    DocumentFormat.MARKDOWN: "text/markdown",
}

_ARCHIVE_SUFFIXES: dict[DocumentFormat, str] = {
    DocumentFormat.PDF: ".pdf",
    DocumentFormat.DOCX: ".docx",
    DocumentFormat.MARKDOWN: ".md",
}

_STAGING_DIR_NAME = "_staging"

# 接收用字节读取器（可注入测试替身，架构 §9）；默认整文件读取。
SourceReader = Callable[[Path], bytes]


class SourceIngestError(ValueError):
    """接收/归档/变化检查失败（fail-closed：不猜测、不降级、不覆盖）。"""


@dataclass(frozen=True)
class IngestLimits:
    """接收限制（架构 §5.1.1 大小限制；空文件一律拒绝）。"""

    max_bytes: int = DEFAULT_MAX_BYTES

    def __post_init__(self) -> None:
        if self.max_bytes <= 0:
            raise SourceIngestError("IngestLimits.max_bytes 必须为正")


@dataclass(frozen=True)
class IngestOutcome:
    """一次接收的结果：归档必已可核验，登记状态单列（§5.1.3 两阶段不冒充事务）。

    - ``registered=True`` 且 ``already_registered=False``：本次首次登记成功。
    - ``already_registered=True``：store 已有同源记录（幂等重放/改名重收），
      首记录为准，本模块不修改既有登记。
    - ``registered=False`` 且 ``error`` 非 None：归档成功但登记失败（可恢复），
      归档对象保留且哈希可核验，交 :func:`register_archived_source` 接管。
    """

    source: Source
    registered: bool
    already_registered: bool
    reused_archive: bool
    error: str | None = None
    ingest_rev: str = INGEST_REV

    @property
    def archive_path(self) -> str:
        return self.source.archive_path


@dataclass(frozen=True)
class SourceChangeCheck:
    """源变化检查结果（架构 §5.1.2：变化只报告，不猜测覆盖）。"""

    registered_source_id: str
    current_source_id: str
    changed: bool
    archive_intact: bool


def _detect(path: Path) -> tuple[DocumentFormat, Path]:
    """扩展名 + 签名 + 可读性校验；ReaderError 统一包装为接收错误。"""
    try:
        return detect_format(path)
    except ReaderError as exc:
        raise SourceIngestError(str(exc)) from exc


def _default_reader(path: Path) -> bytes:
    return path.read_bytes()


def archive_relative_path(source_id: str, fmt: DocumentFormat) -> str:
    """内容寻址相对路径 ``<sha256[:2]>/<sha256><ext>``（POSIX 分隔，跨平台确定）。"""
    return f"{source_id[:2]}/{source_id}{_ARCHIVE_SUFFIXES[fmt]}"


def _require_within_archive_root(archive_root: str | Path, candidate: Path) -> None:
    """归档信任边界核验（full-review C5，fail-closed）。

    路径字符串位于 archive_root 下**不代表**实际落点仍在该目录：分片目录可能
    是指向外部的符号链接。实际解析路径（含逐级符号链接展开）必须仍落在
    archive_root 内，否则拒绝写入/读取。核验先于 exists 检查与任何 I/O。
    """
    root = Path(archive_root).resolve()
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise SourceIngestError(
            f"归档实际落点越出 archive_root（疑似符号链接越界，拒绝写入/读取）: {candidate}"
        )


def _place_archive(data: bytes, source_id: str, final: Path, archive_root: str | Path) -> bool:
    """校验后原子置入内容寻址目录；返回是否复用既有对象（幂等）。

    竞态说明：``final.exists`` 检查与 ``os.replace`` 是两个步骤，并发写入者的
    no-clobber 保证不能由「原子重命名」本身给出（待 I2 以目录 fd/条件写入补
    竞态测试）；本函数先做符号链接边界核验，单进程内越界写入被拒绝。
    """
    _require_within_archive_root(archive_root, final)
    if final.exists():
        archived = final.read_bytes()
        if sha256_of_bytes(archived) != source_id:
            raise SourceIngestError(
                f"内容寻址对象已存在但哈希不符（拒绝覆盖疑似篡改对象）: {final.name}"
            )
        return True
    try:
        staging_dir = final.parent.parent / _STAGING_DIR_NAME
        # The staging directory is an actual write destination, not merely an
        # implementation detail.  Validate it before mkdir/mkstemp so a
        # pre-existing symlink cannot receive a complete source outside the
        # archive trust boundary.
        _require_within_archive_root(archive_root, staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=True)
        _require_within_archive_root(archive_root, staging_dir)
        fd, tmp_name = tempfile.mkstemp(dir=staging_dir, prefix="ingest-", suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            staged = tmp.read_bytes()
            if sha256_of_bytes(staged) != source_id:
                raise SourceIngestError("暂存副本哈希核验失败（不置入归档）")
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(tmp, final)  # 同一文件系统内原子置入
        finally:
            if tmp.exists():
                tmp.unlink()
        return False
    except OSError as exc:
        raise SourceIngestError(f"归档写入失败: {exc}") from exc


def ingest_source(
    store: Store,
    path: str | Path,
    archive_root: str | Path,
    *,
    limits: IngestLimits | None = None,
    original_name: str | None = None,
    reader: SourceReader = _default_reader,
) -> IngestOutcome:
    """接收显式路径：校验 → 双读哈希 → 原子归档 → 幂等登记（架构 §5.1）。"""
    bounds = limits if limits is not None else IngestLimits()
    file_path = Path(path)
    fmt, _ = _detect(file_path)
    try:
        data = reader(file_path)
    except OSError as exc:
        raise SourceIngestError(f"来源文件不可读: {file_path} ({exc})") from exc
    if not data:
        raise SourceIngestError(f"来源文件为空，不接收: {file_path.name}")
    if len(data) > bounds.max_bytes:
        raise SourceIngestError(
            f"来源文件超过大小上限 {bounds.max_bytes} 字节: {file_path.name}（{len(data)} 字节）"
        )
    source_id = sha256_of_bytes(data)
    # §5.1.2 接收前后源文件变化检查：前后哈希不一致即整体拒绝，不登记半份文件。
    try:
        data_again = reader(file_path)
    except OSError as exc:
        raise SourceIngestError(f"来源文件复核不可读: {file_path} ({exc})") from exc
    if sha256_of_bytes(data_again) != source_id:
        raise SourceIngestError(f"接收前后源文件内容变化，拒绝登记: {file_path.name}")

    rel_path = archive_relative_path(source_id, fmt)
    final = Path(archive_root) / rel_path
    if final.exists() and final.resolve() == file_path.resolve():
        # 内容寻址名与源路径重合只可能是字节相同；仍拒绝自我覆盖以守住「不覆盖原文」。
        raise SourceIngestError(f"归档目标与来源文件同路径，拒绝覆盖原文: {file_path}")
    reused = _place_archive(data, source_id, final, archive_root)
    source = Source(
        source_id=source_id,
        format=fmt,
        mime_type=_MIME_TYPES[fmt],
        size_bytes=len(data),
        archive_path=rel_path,
        original_names=(original_name if original_name is not None else file_path.name,),
    )
    existing = store.get_source(source_id)
    if existing is not None:
        # 来源身份由字节决定：已登记即幂等重放，首记录为准（§4.1 路径改名不改身份）。
        if existing.archive_path != rel_path or existing.format is not fmt:
            raise SourceIngestError(
                f"已登记来源 {source_id} 与本次接收的格式/归档路径不一致，拒绝静默覆盖"
            )
        return IngestOutcome(
            source=existing,
            registered=True,
            already_registered=True,
            reused_archive=reused,
        )
    try:
        store.put_source(source)
    except StoreError as exc:
        # §5.1.3：登记失败留下可核验的未登记归档，由恢复流程接管（不冒充跨系统事务）。
        return IngestOutcome(
            source=source,
            registered=False,
            already_registered=False,
            reused_archive=reused,
            error=str(exc),
        )
    return IngestOutcome(
        source=source,
        registered=True,
        already_registered=False,
        reused_archive=reused,
    )


def register_archived_source(
    store: Store,
    archive_root: str | Path,
    archive_path: str,
    *,
    original_name: str,
) -> Source:
    """恢复流程：把已归档但未登记（或登记重放）的对象核验后登记（§5.1.3）。

    核验：归档路径必须是内容寻址名（64 位十六进制 stem），扩展名 + 签名 + 完整
    哈希一致才登记；同源已登记且记录一致为幂等空操作，不一致由 store 冲突拒绝。
    """
    rel = str(archive_path)
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        raise SourceIngestError(f"归档路径非法（须为 archive_root 下的相对内容寻址路径）: {rel!r}")
    final = Path(archive_root) / rel
    # 恢复读入口复用同一信任边界（full-review C5）：符号链接越界的归档对象不读。
    _require_within_archive_root(archive_root, final)
    expected_id = final.stem
    if len(expected_id) != 64 or any(c not in "0123456789abcdef" for c in expected_id):
        raise SourceIngestError(f"归档文件名不是内容寻址 SHA-256: {final.name}")
    fmt, detected = _detect(final)
    try:
        data = detected.read_bytes()
    except OSError as exc:
        raise SourceIngestError(f"归档对象不可读: {final} ({exc})") from exc
    if sha256_of_bytes(data) != expected_id:
        raise SourceIngestError(f"归档对象哈希与内容寻址名不符: {final.name}")
    source = Source(
        source_id=expected_id,
        format=fmt,
        mime_type=_MIME_TYPES[fmt],
        size_bytes=len(data),
        archive_path=rel,
        original_names=(original_name,),
    )
    store.put_source(source)
    return source


def check_source_change(
    registered: Source,
    archive_root: str | Path,
    path: str | Path,
    *,
    reader: SourceReader = _default_reader,
) -> SourceChangeCheck:
    """对已登记来源做源变化检查（架构 §5.1.2 + §4.1）。

    - 当前字节哈希 ≠ ``registered.source_id`` → ``changed=True``：这是**新来源**
      （新 source_id，须重新走接收），绝不就地覆盖旧版本登记或归档。
    - ``archive_intact``：内容寻址对象仍在且哈希可核验（缺失/被改均 False）。
    - 路径扩展名/签名校验失败按接收错误拒绝（疑似损坏/篡改，交人工复核）。
    """
    file_path = Path(path)
    _detect(file_path)
    try:
        current = reader(file_path)
    except OSError as exc:
        raise SourceIngestError(f"来源文件不可读: {file_path} ({exc})") from exc
    current_id = sha256_of_bytes(current)
    archived_path = Path(archive_root) / registered.archive_path
    # 变化检查的归档复核读入口复用同一信任边界（full-review C5）。
    _require_within_archive_root(archive_root, archived_path)
    try:
        archive_intact = sha256_of_bytes(archived_path.read_bytes()) == registered.source_id
    except OSError:
        archive_intact = False
    return SourceChangeCheck(
        registered_source_id=registered.source_id,
        current_source_id=current_id,
        changed=current_id != registered.source_id,
        archive_intact=archive_intact,
    )
