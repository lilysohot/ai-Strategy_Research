"""I1-7 全链编排引擎回归测试（架构 §9 plan→execute→publish + §4.1 + §8.1）。

覆盖验收线：原子置入和重复执行（同 build 幂等不重复增行）；登记失败可恢复
（job FAILED 后重跑接管）；不覆盖正式原文（解析读归档副本、源文件只读、
未决/排除不发布、排除撤下活动版本）。另含 6 份开发材料全链只读 smoke 与
零模型/零 PG 导入纪律检查。
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from plugins.corpus.preparation.admission import POLICY_REV_V1, AdmissionPolicy
from plugins.corpus.preparation.contract import (
    AdmissionDecision,
    AdmissionReasonCode,
    LeaseConfig,
    ResearchDomain,
    ReviewDecision,
    ReviewedDecision,
    UnitStatus,
    sha256_of_bytes,
)
from plugins.corpus.preparation.engine import (
    EngineError,
    PlanEntry,
    execute_builds,
    plan_builds,
    publish_build,
)
from plugins.corpus.preparation.readers import read_document
from plugins.corpus.preparation.readers.base import ReaderError
from plugins.corpus.preparation.repository import MemoryStore, StoreError

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
POLICY = AdmissionPolicy(
    policy_rev=POLICY_REV_V1,
    allowed_domains=(ResearchDomain.COMPANY, ResearchDomain.INDUSTRY, ResearchDomain.MACRO),
)
LEASE = LeaseConfig(
    lease_ttl_seconds=300,
    heartbeat_interval_seconds=60,
    stage_timeout_seconds=600,
    max_attempts=3,
)

REPORT_MD = """# 华泰证券：某某科技深度报告

正文首段介绍公司主营业务与行业地位，内容足够长以便切块装配为正文检索块。

## 财务摘要

公司营收保持增长，利润率保持稳定，经营现金流为正。

## 免责声明

免责声明：本报告基于公开信息编制，仅供内部参考，不构成投资建议。

## 风险提示

行业竞争加剧的风险，以及技术迭代不及预期的风险。
"""


def _make_review(
    source_id: str,
    decision_id: str = "r1",
    decision: ReviewDecision = ReviewDecision.ADMITTED,
    supersedes: str | None = None,
) -> ReviewedDecision:
    return ReviewedDecision(
        decision_id=decision_id,
        source_id=source_id,
        reviewer="alice",
        reviewed_at=NOW,
        decision=decision,
        rationale="锁定研报正例",
        supersedes=supersedes,
    )


def _write_report(tmp_path: Path, name: str = "report.md", content: str = REPORT_MD) -> Path:
    source_file = tmp_path / name
    source_file.write_text(content, encoding="utf-8")
    return source_file


def _execute(
    store: MemoryStore,
    tmp_path: Path,
    entries: list[PlanEntry],
    *,
    reader: object = read_document,
) -> object:
    plan = plan_builds(entries, policy=POLICY)
    return execute_builds(
        store,
        plan,
        policy=POLICY,
        archive_root=tmp_path / "archive",
        owner_id="engine-test",
        now=NOW,
        lease=LEASE,
        reader=reader,  # type: ignore[arg-type]
    )


def _in_scope_entry(source_file: Path, decision_ids: tuple[str, ...] = ("r1",)) -> PlanEntry:
    return PlanEntry(
        path=str(source_file),
        domain_hint=ResearchDomain.COMPANY,
        review_decision_ids=decision_ids,
    )


# --- 全链：接收→解析（归档副本）→清洗→切块→准入→登记 ---


def test_execute_full_chain_registers_all_stages(tmp_path: Path) -> None:
    store = MemoryStore(clock=lambda: NOW)
    source_file = _write_report(tmp_path)
    original_bytes = source_file.read_bytes()
    store.put_reviewed_decision(_make_review(sha256_of_bytes(original_bytes)))

    report = _execute(store, tmp_path, [_in_scope_entry(source_file)])
    outcome = report.outcomes[0]  # type: ignore[attr-defined]

    assert outcome.admission.decision is AdmissionDecision.IN_SCOPE
    assert outcome.build is not None
    build_id = outcome.build.build_id
    assert outcome.unit_count > 0 and outcome.chunk_count > 0
    # units：raw_text 权威 + 清洗投影字段；噪声区保留原因不删除
    units = [
        store.get_unit(build_id, f"unit:{index:04d}") for index in range(1, outcome.unit_count + 1)
    ]
    assert all(unit is not None for unit in units)
    kept = [unit for unit in units if unit.status is UnitStatus.KEPT]
    assert kept and all(unit.clean_view is not None for unit in kept)
    noise = [unit for unit in units if unit.status is UnitStatus.NOISE]
    assert noise and all(unit.reasons for unit in noise)  # 免责声明节保留原单元与原因
    # chunks：引用只能指向本 build 真实单元
    chunk = store.get_chunk(f"{build_id[:16]}:body:0000")
    assert chunk is not None and chunk.unit_refs
    assert all(store.get_unit(build_id, ref) is not None for ref in chunk.unit_refs)
    # 未发布前无活动指针；用户原文件保持只读不被改写
    assert store.get_publication(outcome.source.source_id) is None
    assert source_file.read_bytes() == original_bytes


def test_execute_parses_archive_copy_not_original(tmp_path: Path) -> None:
    store = MemoryStore(clock=lambda: NOW)
    source_file = _write_report(tmp_path)
    store.put_reviewed_decision(_make_review(sha256_of_bytes(source_file.read_bytes())))
    calls: list[Path] = []

    def spy_reader(path: Path) -> object:
        calls.append(path)
        return read_document(path)

    report = _execute(store, tmp_path, [_in_scope_entry(source_file)], reader=spy_reader)
    outcome = report.outcomes[0]  # type: ignore[attr-defined]
    archive_root = tmp_path / "archive"

    assert calls == [archive_root / outcome.source.archive_path]  # 解析只读归档副本
    assert calls[0] != source_file


# --- 重复执行幂等（同 build 不重复增行） ---


def test_execute_rerun_is_idempotent(tmp_path: Path) -> None:
    store = MemoryStore(clock=lambda: NOW)
    source_file = _write_report(tmp_path)
    store.put_reviewed_decision(_make_review(sha256_of_bytes(source_file.read_bytes())))
    entries = [_in_scope_entry(source_file)]

    first = _execute(store, tmp_path, entries).outcomes[0]  # type: ignore[attr-defined]
    second = _execute(store, tmp_path, entries).outcomes[0]  # type: ignore[attr-defined]

    assert second.source == first.source
    assert second.admission == first.admission  # put_admission 幂等重放，指针不回退
    assert second.build == first.build
    assert second.unit_count == first.unit_count and second.chunk_count == first.chunk_count
    assert second.source_reused and second.archive_reused
    build_id = first.build.build_id  # type: ignore[union-attr]
    assert store.get_unit(build_id, "unit:0001") is not None
    assert store.latest_admission(first.source.source_id).decision_id == first.admission.decision_id


def test_same_bytes_different_path_replays_one_source(tmp_path: Path) -> None:
    store = MemoryStore(clock=lambda: NOW)
    content = sha256_of_bytes(_write_report(tmp_path, "a.md").read_bytes())
    renamed = tmp_path / "b.md"
    renamed.write_text(REPORT_MD, encoding="utf-8")
    store.put_reviewed_decision(_make_review(content))
    entries = [
        _in_scope_entry(tmp_path / "a.md"),
        _in_scope_entry(renamed),
    ]

    report = _execute(store, tmp_path, entries)
    first, replay = report.outcomes  # type: ignore[attr-defined]

    assert replay.source == first.source  # 来源身份由字节决定，首记录为准
    assert replay.build == first.build
    assert replay.source_reused is True
    assert replay.admission == first.admission


# --- 准入门：未决不发布 / 排除撤下活动版本 / 源变化复核 ---


def test_review_required_registers_admission_but_refuses_publish(tmp_path: Path) -> None:
    store = MemoryStore(clock=lambda: NOW)
    source_file = _write_report(tmp_path)
    report = _execute(
        store, tmp_path, [PlanEntry(path=str(source_file), domain_hint=ResearchDomain.COMPANY)]
    )
    outcome = report.outcomes[0]  # type: ignore[attr-defined]

    assert outcome.admission.decision is AdmissionDecision.REVIEW_REQUIRED
    assert AdmissionReasonCode.MISSING_REVIEW in outcome.admission.reason_codes
    # 未决不能发布：引擎不建 build，publish 无从发生（无 build 即无活动指针）。
    assert outcome.build is None and outcome.unit_count == 0
    assert store.get_publication(outcome.source.source_id) is None
    with pytest.raises(EngineError, match="build 不存在"):
        publish_build(store, "f" * 64, activated_at=NOW)


def test_excluded_decision_retires_active_publication(tmp_path: Path) -> None:
    store = MemoryStore(clock=lambda: NOW)
    source_file = _write_report(tmp_path)
    sha = sha256_of_bytes(source_file.read_bytes())
    store.put_reviewed_decision(_make_review(sha, "r1"))
    first = _execute(store, tmp_path, [_in_scope_entry(source_file, ("r1",))]).outcomes[0]  # type: ignore[attr-defined]
    publication = publish_build(store, first.build.build_id, activated_at=NOW)  # type: ignore[union-attr]
    assert publication.active_build_id == first.build.build_id  # type: ignore[union-attr]

    store.put_reviewed_decision(_make_review(sha, "r2", ReviewDecision.EXCLUDED, supersedes="r1"))
    # 取代链全历史必须一起给出（断链即 conflicting_review，I1-5 契约）。
    second = _execute(store, tmp_path, [_in_scope_entry(source_file, ("r1", "r2"))]).outcomes[0]  # type: ignore[attr-defined]

    assert second.admission.decision is AdmissionDecision.EXCLUDED_BY_POLICY
    assert second.build is None
    retired = store.get_publication(first.source.source_id)
    assert retired is not None and retired.active_build_id is None  # 活动版本原子撤下
    assert retired.generation == 2
    assert store.get_build(first.build.build_id) is not None  # 旧 build 仅供审计，不被删除


def test_source_changed_binds_new_hash_and_requires_review(tmp_path: Path) -> None:
    store = MemoryStore(clock=lambda: NOW)
    source_file = _write_report(tmp_path)
    stale_sha = sha256_of_bytes(source_file.read_bytes())
    store.put_reviewed_decision(_make_review(stale_sha))
    source_file.write_text(REPORT_MD.replace("行业地位", "行业格局"), encoding="utf-8")

    report = _execute(store, tmp_path, [_in_scope_entry(source_file)])
    outcome = report.outcomes[0]  # type: ignore[attr-defined]

    assert outcome.source.source_id == sha256_of_bytes(source_file.read_bytes())  # 新哈希新来源
    assert outcome.admission.decision is AdmissionDecision.REVIEW_REQUIRED
    assert AdmissionReasonCode.SOURCE_CHANGED in outcome.admission.reason_codes  # 新哈希不继承批准
    assert outcome.build is None


# --- 发布检查门与 generation ---


def test_publish_switches_active_pointer_and_retry_is_idempotent(tmp_path: Path) -> None:
    store = MemoryStore(clock=lambda: NOW)
    source_file = _write_report(tmp_path)
    store.put_reviewed_decision(_make_review(sha256_of_bytes(source_file.read_bytes())))
    outcome = _execute(store, tmp_path, [_in_scope_entry(source_file)]).outcomes[0]  # type: ignore[attr-defined]
    build_id = outcome.build.build_id  # type: ignore[union-attr]

    first = publish_build(store, build_id, activated_at=NOW)
    second = publish_build(store, build_id, activated_at=NOW)

    assert first.generation == 1 and first.active_build_id == build_id
    # publish_idempotency_v2（I0-C 裁决）：相同目标状态 (决定, build) 的重复调用
    # 是提交重试，幂等返回不递增 generation、不刷新 activated_at（不以时间为键）。
    assert second == first
    lost_response = publish_build(store, build_id, activated_at=NOW + timedelta(seconds=1))
    assert lost_response == first and lost_response.generation == 1  # 响应丢失+时钟前进恒幂等
    with pytest.raises(EngineError, match="build 不存在"):
        publish_build(store, "f" * 64, activated_at=NOW)


# --- 登记失败可恢复（job FAILED → 重跑接管） ---


class _FlakyChunkStore(MemoryStore):
    """模拟 CHUNKED 阶段 PG 写入一次性失败。"""

    def __init__(self) -> None:
        super().__init__(clock=lambda: NOW)  # 注入固定时钟（复核 R2 可注入时钟协议）
        self.fail_chunk_writes = True

    def put_chunks(
        self,
        build_id: str,
        chunks: object,
        *,
        owner_id: str | None = None,
        fence_token: str | None = None,
    ) -> None:
        if self.fail_chunk_writes:
            raise StoreError("pg 写入失败（模拟）")
        super().put_chunks(build_id, chunks, owner_id=owner_id, fence_token=fence_token)


def test_execute_recovers_from_stage_write_failure(tmp_path: Path) -> None:
    store = _FlakyChunkStore()
    source_file = _write_report(tmp_path)
    store.put_reviewed_decision(_make_review(sha256_of_bytes(source_file.read_bytes())))
    entries = [_in_scope_entry(source_file)]
    reads: list[Path] = []

    def spy_reader(path: Path) -> object:
        reads.append(path)
        return read_document(path)

    with pytest.raises(StoreError, match="pg 写入失败"):
        _execute(store, tmp_path, entries, reader=spy_reader)

    store.fail_chunk_writes = False
    recovered = _execute(store, tmp_path, entries, reader=spy_reader).outcomes[0]  # type: ignore[attr-defined]

    assert recovered.build is not None and recovered.chunk_count > 0
    # C6：PARSED 阶段产物在首跑已入库，重试经解析检查点复用，reader 只调用一次。
    assert len(reads) == 1
    chunk = store.get_chunk(f"{recovered.build.build_id[:16]}:body:0000")
    assert chunk is not None


# --- plan 清单校验（只读，无模型无 PG） ---


def test_plan_rejects_empty_oversize_and_unsupported(tmp_path: Path) -> None:
    from plugins.corpus.preparation.source import IngestLimits

    empty = tmp_path / "empty.md"
    empty.write_text("", encoding="utf-8")
    big = tmp_path / "big.md"
    big.write_text("x" * 64, encoding="utf-8")
    unsupported = tmp_path / "notes.txt"
    unsupported.write_text("plain", encoding="utf-8")

    with pytest.raises(EngineError, match="空文件"):
        plan_builds([PlanEntry(path=str(empty))], policy=POLICY)
    with pytest.raises(EngineError, match="大小上限"):
        plan_builds([PlanEntry(path=str(big))], policy=POLICY, limits=IngestLimits(max_bytes=8))
    with pytest.raises(ReaderError):
        plan_builds([PlanEntry(path=str(unsupported))], policy=POLICY)


def test_execute_rejects_unknown_review_and_stale_policy(tmp_path: Path) -> None:
    store = MemoryStore(clock=lambda: NOW)
    source_file = _write_report(tmp_path)
    with pytest.raises(EngineError, match="不存在"):
        _execute(store, tmp_path, [_in_scope_entry(source_file, ("ghost",))])
    stale = AdmissionPolicy(policy_rev="v0-00000000", allowed_domains=POLICY.allowed_domains)
    plan = plan_builds([_in_scope_entry(source_file)], policy=stale)
    with pytest.raises(EngineError, match="不一致"):
        execute_builds(
            store,
            plan,
            policy=POLICY,
            archive_root=tmp_path / "archive",
            owner_id="engine-test",
            now=NOW,
            lease=LEASE,
        )


# --- 6 份开发材料全链只读 smoke：真实 PDF 走完解析/清洗/切块后未决复核 ---


def _dev_materials() -> list[Path]:
    config_path = REPO / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    return [REPO / raw for raw in config["sources"]["allowed_source_paths"]]


def test_dev_materials_execute_smoke(tmp_path: Path) -> None:
    store = MemoryStore(clock=lambda: NOW)
    entries = [PlanEntry(path=str(path)) for path in _dev_materials()]
    plan = plan_builds(entries, policy=POLICY)

    first = _execute(store, tmp_path, entries)
    replay = _execute(store, tmp_path, entries)

    assert len(first.outcomes) == len(plan.entries) == 6  # type: ignore[attr-defined]
    for outcome, replayed in zip(first.outcomes, replay.outcomes, strict=True):  # type: ignore[attr-defined]
        assert outcome.admission.decision is AdmissionDecision.REVIEW_REQUIRED  # 无审核不发布
        assert outcome.build is None
        assert replayed.source == outcome.source and replayed.admission == outcome.admission
        assert replayed.source_reused and replayed.archive_reused  # 重复执行幂等


# --- 导入纪律 ---


def test_engine_does_not_import_pg_or_model_client() -> None:
    # 干净子进程断言：同进程其他测试文件（如 metadata 的 psycopg）不应污染本纪律
    code = (
        "import sys; import plugins.corpus.preparation.engine;"
        "bad = [m for m in ('psycopg', 'psycopg2', 'asyncpg', 'sqlalchemy',"
        " 'openai', 'anthropic') if m in sys.modules];"
        "print(f'leaked: {bad}'); sys.exit(1 if bad else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
