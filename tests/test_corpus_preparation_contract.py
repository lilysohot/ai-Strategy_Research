"""I1-1 契约数据模型与内存存储 Adapter 测试。

验收（任务 I1-1）：数据模型与 M1 一致，非法组合拒绝；测试不构造真实 PG/模型
客户端。本文件仅依赖纯标准库模型，不 import openai/anthropic/material_semantics
或 PostgreSQL 驱动。
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest

from plugins.corpus.preparation import contract
from plugins.corpus.preparation.contract import (
    AdmissionDecision,
    AdmissionReasonCode,
    Availability,
    Build,
    Coverage,
    CoverageProcessing,
    DocumentFormat,
    JobStage,
    JobState,
    LeaseConfig,
    MaterialType,
    PublicationDateOrigin,
    PublicationDatePrecision,
    PublicationDateStatus,
    QueryStatus,
    ReportPublication,
    ResearchDomain,
    ReviewDecision,
    Source,
    Unit,
    UnitStatus,
    compute_build_id,
    source_id_from_bytes,
)
from plugins.corpus.preparation.repository import MemoryStore, StoreError

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
SOURCE_ID = "a" * 64


def _source(source_id: str = SOURCE_ID) -> Source:
    return Source(
        source_id=source_id,
        format=DocumentFormat.PDF,
        mime_type="application/pdf",
        size_bytes=100,
        archive_path=f"data/blob/{source_id}.pdf",
    )


def _admission(
    source_id: str = SOURCE_ID,
    *,
    decision: AdmissionDecision = AdmissionDecision.IN_SCOPE,
    domain: ResearchDomain | None = ResearchDomain.COMPANY,
    decision_id: str = "d0",
) -> contract.Admission:
    return contract.Admission(
        decision_id=decision_id,
        source_id=source_id,
        material_type=MaterialType.RESEARCH_REPORT,
        research_domain=domain,
        decision=decision,
    )


def _build(source_id: str = SOURCE_ID, decision_id: str = "d0") -> Build:
    build_id = compute_build_id(
        source_id=source_id,
        decision_id=decision_id,
        parse_rev="p1",
        clean_rev="c1",
        chunk_rev="k1",
        index_rev="i1",
        scope_ref="full",
    )
    return Build(
        build_id=build_id,
        source_id=source_id,
        decision_id=decision_id,
        parse_rev="p1",
        clean_rev="c1",
        chunk_rev="k1",
        index_rev="i1",
        scope_ref="full",
    )


# --- 枚举与 M1 契约一致性 ---


def test_decision_enum_matches_m1_values() -> None:
    assert {d.value for d in AdmissionDecision} == {
        "in_scope",
        "excluded_by_policy",
        "review_required",
    }


def test_minimum_reason_codes_are_covered() -> None:
    assert {c.value for c in AdmissionReasonCode} >= contract.MINIMUM_REASON_CODES


def test_research_domain_and_stage_order() -> None:
    assert {d.value for d in ResearchDomain} == {"company", "industry", "macro"}
    assert tuple(s.value for s in JobStage) == contract.JOB_STAGE_ORDER


def test_job_states_and_review_decisions() -> None:
    assert {s.value for s in JobState} == {"queued", "running", "succeeded", "failed", "cancelled"}
    assert {d.value for d in ReviewDecision} == {"admitted", "excluded", "excluded_from_active"}


# --- 非法组合在构造即拒绝 ---


def test_report_publication_known_requires_value_and_origin() -> None:
    ReportPublication(
        value="2026-09-06",
        precision=PublicationDatePrecision.DATE,
        status=PublicationDateStatus.KNOWN,
        origin=PublicationDateOrigin.SOURCE_EXPLICIT,
        evidence_refs=("doc:page:1",),
    )
    with pytest.raises(contract.ContractError):
        ReportPublication(
            value=None,
            precision=PublicationDatePrecision.DATE,
            status=PublicationDateStatus.KNOWN,
            origin=PublicationDateOrigin.SOURCE_EXPLICIT,
        )
    with pytest.raises(contract.ContractError):
        ReportPublication(
            value="2026-09-06",
            precision=PublicationDatePrecision.DATE,
            status=PublicationDateStatus.UNKNOWN,
            origin=None,
        )


def test_admission_in_scope_requires_report_and_domain() -> None:
    _admission(decision=AdmissionDecision.IN_SCOPE, domain=ResearchDomain.MACRO)
    with pytest.raises(contract.ContractError):
        _admission(decision=AdmissionDecision.IN_SCOPE, domain=None)
    with pytest.raises(contract.ContractError):
        contract.Admission(
            decision_id="d1",
            source_id=SOURCE_ID,
            material_type=MaterialType.PERSONAL_OR_EXTERNAL_SUBSCRIPTION,
            research_domain=None,
            decision=AdmissionDecision.IN_SCOPE,
        )


def test_build_id_is_deterministic_and_binds_scope() -> None:
    args = dict(
        source_id=SOURCE_ID,
        decision_id="d0",
        parse_rev="p1",
        clean_rev="c1",
        chunk_rev="k1",
        index_rev="i1",
        scope_ref="full",
    )
    assert compute_build_id(**args) == compute_build_id(**args)
    assert compute_build_id(**args) != compute_build_id(**{**args, "scope_ref": "scoped"})
    assert compute_build_id(**args) != compute_build_id(**{**args, "decision_id": "d1"})
    # I2-3：index_rev 参与 build_id——索引/分词配置升级必须换新 rev（⇒ 新 build
    # 全量重建），同名配置原地沿用旧版本在身份层面不可表达。
    assert compute_build_id(**args) != compute_build_id(**{**args, "index_rev": "i2"})


def test_unit_content_hash_must_match_raw_text() -> None:
    raw = "原文片段"
    Unit(
        unit_id="u1",
        build_id=compute_build_id(
            source_id=SOURCE_ID,
            decision_id="d0",
            parse_rev="p",
            clean_rev="c",
            chunk_rev="k",
            index_rev="i",
            scope_ref=None,
        ),
        kind="paragraph",
        raw_text=raw,
        content_hash=source_id_from_bytes(raw.encode("utf-8")),
    )
    with pytest.raises(contract.ContractError):
        Unit(
            unit_id="u1",
            build_id=compute_build_id(
                source_id=SOURCE_ID,
                decision_id="d0",
                parse_rev="p",
                clean_rev="c",
                chunk_rev="k",
                index_rev="i",
                scope_ref=None,
            ),
            kind="paragraph",
            raw_text=raw,
            content_hash=source_id_from_bytes(b"tampered"),
        )


def test_coverage_failed_implies_unknown_and_scope_required() -> None:
    Coverage(
        admission_decision=AdmissionDecision.IN_SCOPE,
        processing=CoverageProcessing.FULL,
        query_status=QueryStatus.MATCHED,
        availability=Availability.AVAILABLE,
        requested_scope_ref="s",
        effective_scope_ref="s",
        publication_snapshot_ref="p",
    )
    with pytest.raises(contract.ContractError):
        Coverage(
            admission_decision=AdmissionDecision.IN_SCOPE,
            processing=CoverageProcessing.FULL,
            query_status=QueryStatus.FAILED,
            availability=Availability.AVAILABLE,
            requested_scope_ref="s",
            effective_scope_ref="s",
            publication_snapshot_ref="p",
        )
    with pytest.raises(contract.ContractError):
        Coverage(
            admission_decision=AdmissionDecision.IN_SCOPE,
            processing=CoverageProcessing.FULL,
            query_status=QueryStatus.MATCHED,
            availability=Availability.AVAILABLE,
        )


def test_lease_config_heartbeat_constraints() -> None:
    LeaseConfig(
        lease_ttl_seconds=120,
        heartbeat_interval_seconds=30,
        stage_timeout_seconds=360,
        max_attempts=3,
    )
    with pytest.raises(contract.ContractError):
        LeaseConfig(
            lease_ttl_seconds=120,
            heartbeat_interval_seconds=120,
            stage_timeout_seconds=360,
            max_attempts=3,
        )
    with pytest.raises(contract.ContractError):
        LeaseConfig(
            lease_ttl_seconds=120,
            heartbeat_interval_seconds=41,
            stage_timeout_seconds=360,
            max_attempts=3,
        )


# --- 内存存储 Adapter：幂等 / 追加 / 发布 / 租约 ---


def test_memory_source_idempotent_and_conflict() -> None:
    store = MemoryStore()
    store.put_source(_source())
    store.put_source(_source())  # 同内容幂等
    conflicting = Source(
        source_id=SOURCE_ID,
        format=DocumentFormat.DOCX,
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=999,
        archive_path="data/blob/other.docx",
    )
    with pytest.raises(StoreError):
        store.put_source(conflicting)
    assert store.get_source(SOURCE_ID) == _source()


def test_memory_admission_append_only_latest() -> None:
    store = MemoryStore()
    store.put_admission(_admission(decision_id="d0"))
    store.put_admission(_admission(decision_id="d1"))
    assert store.latest_admission(SOURCE_ID).decision_id == "d1"
    assert store.get_admission("d0").decision == AdmissionDecision.IN_SCOPE


def test_memory_unit_and_chunk_idempotent() -> None:
    store = MemoryStore()
    build = _build()
    store.put_build(build)
    store.put_build(build)  # 幂等
    raw = "段落"
    unit = Unit(
        unit_id="u1",
        build_id=build.build_id,
        kind="paragraph",
        raw_text=raw,
        content_hash=source_id_from_bytes(raw.encode("utf-8")),
        status=UnitStatus.KEPT,
    )
    # 复核 R2 fail-closed：权威写入须先登记 PARSED job 并由当前租约持有者携带
    # owner/token 执行（测试夹具与业务走同一协议，无旁路）。
    lease = LeaseConfig(
        lease_ttl_seconds=120,
        heartbeat_interval_seconds=30,
        stage_timeout_seconds=360,
        max_attempts=3,
    )
    store.register_job(build.build_id, JobStage.PARSED)
    acquired = store.acquire_job(
        build.build_id, JobStage.PARSED, "fixture", datetime.now(UTC), lease
    )
    store.put_units(
        build.build_id,
        [unit, unit],  # 同内容幂等
        owner_id="fixture",
        fence_token=acquired.fence_token,
    )
    assert store.get_unit(build.build_id, "u1") == unit


def test_memory_publish_requires_in_scope_and_generation_increments() -> None:
    store = MemoryStore()
    store.put_source(_source())
    store.put_admission(_admission(decision_id="d0"))
    build = _build()
    store.put_build(build)
    # 复核 R2 fail-closed：发布必须持 PUBLISHED job 当前租约（测试夹具与业务走
    # 同一协议，无 no-check 旁路）。
    lease = LeaseConfig(120, 30, 360, 3)
    store.register_job(build.build_id, JobStage.PUBLISHED)
    acquired = store.acquire_job(
        build.build_id, JobStage.PUBLISHED, "fixture", datetime.now(UTC), lease
    )
    pub1 = store.publish(
        SOURCE_ID,
        "d0",
        build.build_id,
        NOW,
        owner_id="fixture",
        fence_token=acquired.fence_token,
    )
    assert pub1.generation == 1 and pub1.active_build_id == build.build_id
    # publish_idempotency_v2（I0-C 裁决）：同目标状态幂等不以时间为键——
    # 响应丢失+时钟前进的重试（此处同 token、时间前进）恒返回已提交结果。
    pub2 = store.publish(
        SOURCE_ID,
        "d0",
        build.build_id,
        NOW + timedelta(seconds=1),
        owner_id="fixture",
        fence_token=acquired.fence_token,
    )
    assert pub2 == pub1 and pub2.generation == 1
    assert pub2.activated_at == pub1.activated_at  # 时间不刷新

    excluded = contract.Admission(
        decision_id="d1",
        source_id=SOURCE_ID,
        material_type=MaterialType.PIPELINE_ARTIFACT,
        research_domain=None,
        decision=AdmissionDecision.EXCLUDED_BY_POLICY,
    )
    store.put_admission(excluded)
    with pytest.raises(StoreError):
        store.publish(
            SOURCE_ID,
            "d1",
            build.build_id,
            NOW,
            owner_id="fixture",
            fence_token=acquired.fence_token,
        )

    retired = store.retire(SOURCE_ID, "d1", NOW)
    # 指针翻转（active→None）才递增 generation：publish(1) → retire(2)。
    assert retired.active_build_id is None and retired.generation == 2


def test_memory_job_lease_order_and_fence() -> None:
    store = MemoryStore()
    build = _build()
    store.put_build(build)
    lease = LeaseConfig(
        lease_ttl_seconds=120,
        heartbeat_interval_seconds=30,
        stage_timeout_seconds=360,
        max_attempts=3,
    )

    job = store.register_job(build.build_id, JobStage.PARSED)
    assert job.state is JobState.QUEUED and job.attempt == 1

    acquired = store.acquire_job(build.build_id, JobStage.PARSED, "owner-a", NOW, lease)
    assert acquired.state is JobState.RUNNING and acquired.fence_token is not None

    # running 未过期不得抢占
    with pytest.raises(StoreError):
        store.acquire_job(build.build_id, JobStage.PARSED, "owner-b", NOW, lease)

    # 心跳：token 不匹配 → lease_lost
    with pytest.raises(StoreError):
        store.heartbeat_job(
            build.build_id,
            JobStage.PARSED,
            "owner-a",
            "wrong-token",
            NOW + timedelta(seconds=10),
            lease,
        )

    # 过期后可接管：attempt 递增、新 token
    later = NOW + timedelta(seconds=121)
    reacquired = store.acquire_job(build.build_id, JobStage.PARSED, "owner-b", later, lease)
    assert reacquired.attempt == 2 and reacquired.owner_id == "owner-b"

    # 正确 token 完成
    done = store.finish_job(
        build.build_id,
        JobStage.PARSED,
        "owner-b",
        reacquired.fence_token,
        later,
        JobState.SUCCEEDED,
    )
    assert done.state is JobState.SUCCEEDED
    # 重复完成幂等（提交已成功未收到响应）
    again = store.finish_job(
        build.build_id,
        JobStage.PARSED,
        "owner-b",
        reacquired.fence_token,
        later,
        JobState.SUCCEEDED,
    )
    assert again.state is JobState.SUCCEEDED


def test_memory_fencing_credential_precedes_state_after_takeover() -> None:
    """RM-4：凭据优先于状态——与 PgStore 断言**同一**错误语义。

    接管者已完成后，旧 worker 的迟到写入必须得到 ``lease_lost``，而不是
    「job 处于 succeeded 态，无当前所有权」这类状态提示。PG 侧对称用例见
    ``test_corpus_preparation_publication_pg.py::
    test_pg_fencing_credential_precedes_state_after_takeover``。

    覆盖两处判定：``put_units``（走 ``_require_stage_ownership``）与
    ``finish_job``（走 ``_fence``）。修复前两者都是「状态优先」，与 PG 相反。

    ``put_units`` 不接受 ``now``，过期判定走注入时钟，故此处固定为 ``NOW``，
    使接管者（w2）租约在模拟时间轴上未过期；``acquire_job`` 则用显式传入的
    模拟时间推进到 ``later`` 越过 TTL，完成一次合法接管。
    """
    store = MemoryStore(clock=lambda: NOW)
    build = _build()
    store.put_build(build)
    lease = LeaseConfig(
        lease_ttl_seconds=120,
        heartbeat_interval_seconds=30,
        stage_timeout_seconds=360,
        max_attempts=3,
    )
    store.register_job(build.build_id, JobStage.PARSED)
    stale = store.acquire_job(build.build_id, JobStage.PARSED, "w1", NOW, lease)
    later = NOW + timedelta(seconds=121)  # 越过 TTL：w2 合法接管
    current = store.acquire_job(build.build_id, JobStage.PARSED, "w2", later, lease)
    raw = "接管者写入的单元"
    store.put_units(
        build.build_id,
        [
            Unit(
                unit_id="u1",
                build_id=build.build_id,
                kind="paragraph",
                raw_text=raw,
                content_hash=source_id_from_bytes(raw.encode("utf-8")),
                status=UnitStatus.KEPT,
            )
        ],
        owner_id="w2",
        fence_token=current.fence_token,
    )
    store.finish_job(
        build.build_id, JobStage.PARSED, "w2", current.fence_token, later, JobState.SUCCEEDED
    )

    # ① 旧 worker 迟到权威写入（_require_stage_ownership）
    ghost = "陈旧 worker 的幽灵单元"
    with pytest.raises(StoreError, match="lease_lost"):
        store.put_units(
            build.build_id,
            [
                Unit(
                    unit_id="u-ghost",
                    build_id=build.build_id,
                    kind="paragraph",
                    raw_text=ghost,
                    content_hash=source_id_from_bytes(ghost.encode("utf-8")),
                    status=UnitStatus.KEPT,
                )
            ],
            owner_id="w1",
            fence_token=stale.fence_token,
        )
    # ② 旧 worker 迟到 finish（_fence）：不得被误认成同一次提交（RM-1 同族）
    with pytest.raises(StoreError, match="lease_lost"):
        store.finish_job(
            build.build_id, JobStage.PARSED, "w1", stale.fence_token, later, JobState.SUCCEEDED
        )
    # 对照：接管者的单元未被幽灵写入污染
    assert [u.unit_id for u in store.get_units(build.build_id)] == ["u1"]


def test_memory_job_max_attempts() -> None:
    store = MemoryStore()
    build = _build()
    store.put_build(build)
    lease = LeaseConfig(
        lease_ttl_seconds=120,
        heartbeat_interval_seconds=30,
        stage_timeout_seconds=360,
        max_attempts=2,
    )
    store.register_job(build.build_id, JobStage.CLEANED)
    for _ in range(2):
        job = store.acquire_job(build.build_id, JobStage.CLEANED, "o", NOW, lease)
        store.finish_job(
            build.build_id,
            JobStage.CLEANED,
            "o",
            job.fence_token,
            NOW,
            JobState.FAILED,
            error="boom",
        )
    with pytest.raises(StoreError):
        store.acquire_job(build.build_id, JobStage.CLEANED, "o", NOW, lease)


def test_i1_contract_modules_do_not_import_pg_or_model_client() -> None:
    # 干净子进程断言：同进程其他测试文件不应污染本纪律
    code = (
        "import sys; import plugins.corpus.preparation.contract;"
        "bad = [m for m in ('psycopg', 'psycopg2', 'asyncpg', 'sqlalchemy', 'openai',"
        " 'anthropic', 'plugins.corpus.material_semantics',"
        " 'plugins.corpus._r2_runtime') if m in sys.modules];"
        "print(f'leaked: {bad}'); sys.exit(1 if bad else 0)"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
