"""I1-6 来源接收/归档回归测试（架构 §5.1 + §4.1）。

覆盖验收线：原子置入和重复执行（幂等）；登记失败可恢复（归档先行、恢复流程
接管）；不覆盖正式原文（源目录只读、篡改对象拒覆盖、改名不改来源身份、
变化产生新 source_id 而非就地覆盖）。另含 6 份开发材料只读 smoke 与
零模型/零 PG 导入纪律检查。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from plugins.corpus.preparation import source as source_module
from plugins.corpus.preparation.contract import DocumentFormat, sha256_of_bytes
from plugins.corpus.preparation.repository import MemoryStore, StoreError
from plugins.corpus.preparation.source import (
    INGEST_REV,
    IngestLimits,
    SourceChangeCheck,
    SourceIngestError,
    archive_relative_path,
    check_source_change,
    ingest_source,
    register_archived_source,
)

REPO = Path(__file__).resolve().parents[1]


def _write_pdf(path: Path, payload: bytes = b"fake pdf body") -> Path:
    path.write_bytes(b"%PDF-1.4\n" + payload)
    return path


def _archive_file(archive_root: Path, archive_path: str) -> Path:
    return archive_root / archive_path


# --- 接收：内容寻址归档 + 幂等登记 ---


def test_ingest_registers_content_addressed_source(tmp_path: Path) -> None:
    store = MemoryStore()
    source_file = _write_pdf(tmp_path / "a.pdf")
    archive_root = tmp_path / "archive"
    expected_id = sha256_of_bytes(source_file.read_bytes())

    outcome = ingest_source(store, source_file, archive_root)

    assert outcome.registered and not outcome.already_registered
    assert not outcome.reused_archive
    assert outcome.error is None
    assert outcome.ingest_rev == INGEST_REV
    source = outcome.source
    assert source.source_id == expected_id
    assert source.format is DocumentFormat.PDF
    assert source.mime_type == "application/pdf"
    assert source.size_bytes == len(source_file.read_bytes())
    assert source.original_names == ("a.pdf",)
    assert source.archive_path == archive_relative_path(expected_id, DocumentFormat.PDF)
    archived = _archive_file(archive_root, source.archive_path)
    assert archived.read_bytes() == source_file.read_bytes()
    assert store.get_source(expected_id) == source


def test_ingest_repeated_execution_idempotent(tmp_path: Path) -> None:
    store = MemoryStore()
    source_file = _write_pdf(tmp_path / "a.pdf")
    archive_root = tmp_path / "archive"

    first = ingest_source(store, source_file, archive_root)
    second = ingest_source(store, source_file, archive_root)

    assert second.registered and second.already_registered
    assert second.reused_archive
    assert second.source == first.source
    archived = _archive_file(archive_root, first.archive_path)
    assert [p for p in archive_root.rglob("*") if p.is_file()] == [archived]


def test_ingest_renamed_path_keeps_source_identity(tmp_path: Path) -> None:
    store = MemoryStore()
    source_file = _write_pdf(tmp_path / "a.pdf")
    renamed = tmp_path / "b.pdf"
    renamed.write_bytes(source_file.read_bytes())
    archive_root = tmp_path / "archive"

    first = ingest_source(store, source_file, archive_root)
    replay = ingest_source(store, renamed, archive_root)

    assert replay.already_registered and replay.registered
    assert replay.source == first.source  # 首记录为准；路径改名不改变来源身份
    assert store.get_source(first.source.source_id) == first.source


# --- 接收拒绝：空文件/超限/格式/接收中变化（fail-closed，不登记半份文件） ---


def test_ingest_rejects_empty_file(tmp_path: Path) -> None:
    store = MemoryStore()
    empty = tmp_path / "empty.md"  # md 无签名要求，专测非空校验本身
    empty.write_bytes(b"")
    with pytest.raises(SourceIngestError, match="为空"):
        ingest_source(store, empty, tmp_path / "archive")
    assert store.get_source(sha256_of_bytes(b"")) is None


def test_ingest_rejects_oversize(tmp_path: Path) -> None:
    store = MemoryStore()
    source_file = _write_pdf(tmp_path / "big.pdf", payload=b"x" * 100)
    with pytest.raises(SourceIngestError, match="大小上限"):
        ingest_source(store, source_file, tmp_path / "archive", limits=IngestLimits(max_bytes=8))


def test_ingest_rejects_unsupported_extension(tmp_path: Path) -> None:
    store = MemoryStore()
    text_file = tmp_path / "notes.txt"
    text_file.write_bytes(b"plain text")
    with pytest.raises(SourceIngestError, match="不支持的来源格式"):
        ingest_source(store, text_file, tmp_path / "archive")


def test_ingest_rejects_signature_mismatch(tmp_path: Path) -> None:
    store = MemoryStore()
    fake = tmp_path / "fake.pdf"
    fake.write_bytes(b"not a pdf at all")
    with pytest.raises(SourceIngestError, match="签名"):
        ingest_source(store, fake, tmp_path / "archive")


def test_ingest_rejects_source_changed_during_read(tmp_path: Path) -> None:
    store = MemoryStore()
    source_file = _write_pdf(tmp_path / "a.pdf", payload=b"first version")
    archive_root = tmp_path / "archive"
    before = source_file.read_bytes()
    after = b"%PDF-1.4\nsecond version"
    calls: list[bytes] = []

    def flaky_reader(path: Path) -> bytes:
        calls.append(b"")
        return before if len(calls) == 1 else after

    with pytest.raises(SourceIngestError, match="接收前后源文件内容变化"):
        ingest_source(store, source_file, archive_root, reader=flaky_reader)
    assert store.get_source(sha256_of_bytes(before)) is None
    assert not archive_root.exists() or not any(archive_root.rglob("*.pdf"))


# --- 归档纪律：不覆盖原文与既有内容寻址对象 ---


def test_ingest_never_overwrites_tampered_archive_object(tmp_path: Path) -> None:
    store = MemoryStore()
    source_file = _write_pdf(tmp_path / "a.pdf")
    data = source_file.read_bytes()
    source_id = sha256_of_bytes(data)
    archive_root = tmp_path / "archive"
    final = archive_root / archive_relative_path(source_id, DocumentFormat.PDF)
    final.parent.mkdir(parents=True)
    tampered = b"%PDF-1.4\ntampered object"
    final.write_bytes(tampered)

    with pytest.raises(SourceIngestError, match="拒绝覆盖"):
        ingest_source(store, source_file, archive_root)
    assert final.read_bytes() == tampered  # 疑似篡改对象原样保留，交人工处置
    assert store.get_source(source_id) is None


def test_ingest_does_not_modify_source_or_leave_temp(tmp_path: Path) -> None:
    store = MemoryStore()
    source_file = _write_pdf(tmp_path / "a.pdf")
    before = source_file.read_bytes()
    archive_root = tmp_path / "archive"

    outcome = ingest_source(store, source_file, archive_root)

    assert source_file.read_bytes() == before  # 用户原目录只读、不删除、不改写
    staging = archive_root / "_staging"
    assert not staging.exists() or not any(staging.iterdir())  # 暂存残留即失败
    archived = _archive_file(archive_root, outcome.archive_path)
    assert sha256_of_bytes(archived.read_bytes()) == outcome.source.source_id


def test_ingest_rejects_staging_symlink_before_creating_tempfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = MemoryStore()
    source_file = _write_pdf(tmp_path / "a.pdf")
    archive_root = tmp_path / "archive"
    outside = tmp_path / "outside"
    archive_root.mkdir()
    outside.mkdir()
    (archive_root / "_staging").symlink_to(outside, target_is_directory=True)
    calls: list[Path] = []
    original = source_module.tempfile.mkstemp

    def observe_tempfile(*args: object, **kwargs: object) -> tuple[int, str]:
        fd, name = original(*args, **kwargs)
        calls.append(Path(name).resolve())
        return fd, name

    monkeypatch.setattr(source_module.tempfile, "mkstemp", observe_tempfile)
    with pytest.raises(SourceIngestError, match="越出 archive_root"):
        ingest_source(store, source_file, archive_root)
    assert calls == []


# --- 登记失败可恢复：归档先行，恢复流程接管（§5.1.3） ---


class _BrokenRegistrationStore(MemoryStore):
    """模拟 PG 登记失败（文件系统归档已成功后的存储侧故障）。"""

    def put_source(self, source: object) -> None:  # type: ignore[override]
        raise StoreError("pg 不可写（模拟登记失败）")


def test_registration_failure_keeps_verifiable_archive_and_recovers(tmp_path: Path) -> None:
    broken = _BrokenRegistrationStore()
    source_file = _write_pdf(tmp_path / "a.pdf")
    archive_root = tmp_path / "archive"

    outcome = ingest_source(broken, source_file, archive_root)  # type: ignore[arg-type]

    assert outcome.registered is False
    assert outcome.already_registered is False
    assert outcome.error is not None and "pg 不可写" in outcome.error
    archived = _archive_file(archive_root, outcome.archive_path)
    assert sha256_of_bytes(archived.read_bytes()) == outcome.source.source_id  # 可核验未登记归档

    store = MemoryStore()
    recovered = register_archived_source(
        store, archive_root, outcome.archive_path, original_name="a.pdf"
    )
    assert recovered == outcome.source
    assert store.get_source(recovered.source_id) is not None


def test_register_archived_source_replays_idempotent_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    store = MemoryStore()
    source_file = _write_pdf(tmp_path / "a.pdf")
    archive_root = tmp_path / "archive"
    outcome = ingest_source(store, source_file, archive_root)

    replayed = register_archived_source(
        store, archive_root, outcome.archive_path, original_name="a.pdf"
    )
    assert replayed == outcome.source  # 同记录幂等重放

    archived = _archive_file(archive_root, outcome.archive_path)
    keep = archived.read_bytes()
    archived.write_bytes(b"%PDF-1.4\ntampered after ingest")
    with pytest.raises(SourceIngestError, match="哈希与内容寻址名不符"):
        register_archived_source(
            MemoryStore(), archive_root, outcome.archive_path, original_name="a.pdf"
        )
    archived.write_bytes(keep)  # 恢复现场供后续断言

    with pytest.raises(SourceIngestError, match="非法"):
        register_archived_source(store, archive_root, "../escape.pdf", original_name="x.pdf")
    with pytest.raises(SourceIngestError, match="内容寻址 SHA-256"):
        register_archived_source(store, archive_root, "ab/not-a-hash.pdf", original_name="x.pdf")


# --- 源变化检查：只报告变化，绝不就地覆盖旧版本（§4.1） ---


def test_check_source_change_unchanged_and_archive_intact(tmp_path: Path) -> None:
    store = MemoryStore()
    source_file = _write_pdf(tmp_path / "a.pdf")
    archive_root = tmp_path / "archive"
    outcome = ingest_source(store, source_file, archive_root)

    check: SourceChangeCheck = check_source_change(outcome.source, archive_root, source_file)

    assert check.changed is False
    assert check.archive_intact is True
    assert check.current_source_id == check.registered_source_id


def test_check_source_change_reports_new_bytes_keeps_old_version(tmp_path: Path) -> None:
    store = MemoryStore()
    source_file = _write_pdf(tmp_path / "a.pdf", payload=b"v1")
    archive_root = tmp_path / "archive"
    outcome = ingest_source(store, source_file, archive_root)
    old_id = outcome.source.source_id

    source_file.write_bytes(b"%PDF-1.4\nv2 updated content")
    check = check_source_change(outcome.source, archive_root, source_file)

    assert check.changed is True
    assert check.archive_intact is True  # 旧版本归档原样保留
    assert check.current_source_id != old_id
    assert store.get_source(old_id).source_id == old_id  # 旧登记未被覆盖


def test_check_source_change_flags_missing_archive(tmp_path: Path) -> None:
    store = MemoryStore()
    source_file = _write_pdf(tmp_path / "a.pdf")
    archive_root = tmp_path / "archive"
    outcome = ingest_source(store, source_file, archive_root)
    _archive_file(archive_root, outcome.archive_path).unlink()

    check = check_source_change(outcome.source, archive_root, source_file)

    assert check.changed is False
    assert check.archive_intact is False


# --- 6 份开发材料只读 smoke：显式路径接收全链可复跑 ---


def _dev_materials() -> list[Path]:
    config_path = REPO / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    return [REPO / raw for raw in config["sources"]["allowed_source_paths"]]


def test_dev_materials_ingest_smoke(tmp_path: Path) -> None:
    store = MemoryStore()
    archive_root = tmp_path / "archive"
    formats: set[DocumentFormat] = set()
    for path in _dev_materials():
        expected_id = sha256_of_bytes(path.read_bytes())
        outcome = ingest_source(store, path, archive_root)
        assert outcome.registered and outcome.error is None, path.name
        assert outcome.source.source_id == expected_id
        assert outcome.source.size_bytes == path.stat().st_size
        formats.add(outcome.source.format)

        replay = ingest_source(store, path, archive_root)
        assert replay.already_registered and replay.reused_archive, path.name

        check = check_source_change(outcome.source, archive_root, path)
        assert check.changed is False and check.archive_intact is True, path.name
    # 开发材料当前均为 PDF；DOCX/MD 格式覆盖由 readers 合成夹具承担，不在此强求。
    assert formats <= set(DocumentFormat) and formats


# --- 导入纪律：零模型、零 PG ---


def test_source_does_not_import_pg_or_model_client() -> None:
    # 干净子进程断言：同进程其他测试文件不应污染本纪律
    code = (
        "import sys; import plugins.corpus.preparation.source;"
        "bad = [m for m in ('psycopg', 'psycopg2', 'asyncpg', 'sqlalchemy',"
        " 'openai', 'anthropic') if m in sys.modules];"
        "print(f'leaked: {bad}'); sys.exit(1 if bad else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
