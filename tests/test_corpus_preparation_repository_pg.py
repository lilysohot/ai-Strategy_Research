"""I2-2 PG 存储适配器真库测试（Store Seam 的 PG 侧实现验证）。

运行条件：``CORPUS_I2_DSN`` 指向隔离库 i2_sandbox_corpus（i2-sandbox 守卫 env）；
无 DSN 时模块级跳过（不影响 i1/普通环境套件；I2-5 门验收时须实际运行不得 skip）。
数据纪律：仅操作 i2_sandbox_corpus 的 corpus schema，每用例前 TRUNCATE（数据级精确
清理，schema/库不动）；不触碰 i0b2_verify_* 与任何生产库。
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from plugins.corpus.preparation.admission import POLICY_REV_V1, AdmissionPolicy
from plugins.corpus.preparation.engine import (
    INDEX_REV_V3,
    PlanEntry,
    execute_builds,
    plan_builds,
    publish_build,
)

DSN = os.environ.get("CORPUS_I2_DSN", "")
if not DSN:
    # 模块级跳过且不导入 psycopg：i1/普通环境的 sys.modules 零 PG 断言不受污染。
    pytest.skip("CORPUS_I2_DSN 未设置（非 I2 演练环境）", allow_module_level=True)

import psycopg  # noqa: E402  仅 I2 演练环境导入

from plugins.corpus.preparation.contract import (  # noqa: E402
    Admission,
    AdmissionDecision,
    Build,
    Chunk,
    DocumentFormat,
    JobStage,
    JobState,
    LeaseConfig,
    MaterialType,
    MetadataSnapshot,
    Publication,
    PublicationDateOrigin,
    PublicationDatePrecision,
    PublicationDateStatus,
    ReportPublication,
    ResearchDomain,
    ReviewDecision,
    ReviewedDecision,
    Source,
    Unit,
    UnitStatus,
    sha256_of_bytes,
)
from plugins.corpus.preparation.repository import StoreError  # noqa: E402
from plugins.corpus.preparation.repository_pg import PgStore  # noqa: E402
from plugins.corpus.preparation.search_pg import search_chunks  # noqa: E402

SANDBOX_DB = "i2_sandbox_corpus"
TABLES = (
    "corpus_source_checkpoints",
    "corpus_jobs",
    "corpus_publications",
    "corpus_chunks",
    "corpus_units",
    "corpus_builds",
    "corpus_admissions",
    "corpus_review_decisions",
    "corpus_sources",
)
LEASE = LeaseConfig(300, 60, 600, 3)
NOW = datetime(2026, 9, 17, 12, tzinfo=UTC)


def _verify_cleanup_target(cur: psycopg.Cursor) -> None:
    cur.execute("SELECT current_database()")
    row = cur.fetchone()
    database = row[0] if row else None
    if database != SANDBOX_DB:
        raise StoreError(f"拒绝清理：current_database={database!r} ≠ {SANDBOX_DB!r}")
    cur.execute("SELECT datname FROM pg_database WHERE datallowconn")
    dbs = {r[0] for r in cur.fetchall()}
    if "apodex" in dbs:
        raise StoreError("拒绝清理：目标实例含 apodex 库")


@pytest.fixture(autouse=True)
def _clean_tables():
    qualified = ", ".join(f"corpus.{t}" for t in TABLES)
    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        _verify_cleanup_target(cur)
        cur.execute(f"TRUNCATE {qualified}")  # 单语句：FK 关联表须同时清空
    yield


@pytest.fixture()
def store() -> PgStore:
    return PgStore(DSN, sandbox_db=SANDBOX_DB)


def _sid(tag: str) -> str:
    return sha256_of_bytes(f"i2s2:{tag}".encode())


def _source(tag: str) -> Source:
    return Source(
        source_id=_sid(tag),
        format=DocumentFormat.MARKDOWN,
        mime_type="text/markdown",
        size_bytes=128,
        archive_path=f"ab/{_sid(tag)}.md",
        original_names=(f"{tag}.md",),
    )


def _review(tag: str, decision_id: str, supersedes: str | None = None) -> ReviewedDecision:
    return ReviewedDecision(
        decision_id=decision_id,
        source_id=_sid(tag),
        reviewer="i2s2-test",
        reviewed_at=NOW,
        decision=ReviewDecision.ADMITTED,
        rationale="test fixture",
        supersedes=supersedes,
    )


def _admission(
    tag: str, decision_id: str, decision: AdmissionDecision = AdmissionDecision.IN_SCOPE
):
    return Admission(
        decision_id=decision_id,
        source_id=_sid(tag),
        material_type=MaterialType.RESEARCH_REPORT
        if decision is AdmissionDecision.IN_SCOPE
        else MaterialType.PIPELINE_ARTIFACT,
        research_domain=ResearchDomain.COMPANY if decision is AdmissionDecision.IN_SCOPE else None,
        decision=decision,
        policy_rev="v1-20260915",
    )


def _build(tag: str, decision_id: str, build_id: str | None = None) -> Build:
    return Build(
        build_id=build_id or sha256_of_bytes(f"build:{tag}:{decision_id}".encode()),
        source_id=_sid(tag),
        decision_id=decision_id,
        parse_rev="parse-test",
        clean_rev="clean-test",
        chunk_rev="chunk-test",
        index_rev=INDEX_REV_V3,
        quality_report='{"gap_regions": [], "oversized_chunks": []}',
    )


def _unit(tag: str, build_id: str, unit_id: str) -> Unit:
    raw = f"raw text of {unit_id}"
    return Unit(
        unit_id=unit_id,
        build_id=build_id,
        kind="paragraph",
        raw_text=raw,
        content_hash=sha256_of_bytes(raw.encode()),
        ordinal=1,
        status=UnitStatus.KEPT,
    )


def _seed_build(store: PgStore, tag: str, decision_id: str, build_id: str | None = None) -> str:
    store.put_source(_source(tag))
    store.put_admission(_admission(tag, decision_id))
    build = _build(tag, decision_id, build_id)
    store.put_build(build)
    return build.build_id


def _acquired_parsed(store: PgStore, build_id: str, owner: str = "w1"):
    store.register_job(build_id, JobStage.PARSED)
    return store.acquire_job(build_id, JobStage.PARSED, owner, NOW, LEASE)


# ---- 来源 / 审核 / 准入 ----


def test_pg_source_idempotent_and_conflict(store: PgStore) -> None:
    store.put_source(_source("a"))
    store.put_source(_source("a"))  # 同内容幂等
    from dataclasses import replace

    drifted = replace(_source("a"), size_bytes=999)
    with pytest.raises(StoreError, match="source 冲突"):
        store.put_source(drifted)
    assert store.get_source(_sid("a")) == _source("a")
    assert store.get_source(_sid("absent")) is None


def test_pg_reviewed_decision_append_and_conflict(store: PgStore) -> None:
    from dataclasses import replace

    store.put_source(_source("a"))
    store.put_reviewed_decision(_review("a", "r1"))
    store.put_reviewed_decision(_review("a", "r1"))  # 幂等
    with pytest.raises(StoreError, match="reviewed_decision 冲突"):
        store.put_reviewed_decision(replace(_review("a", "r1"), rationale="changed"))
    assert store.get_reviewed_decision("r1").rationale == "test fixture"
    assert store.get_reviewed_decision("absent") is None


def test_pg_admission_pointer_forward_only(store: PgStore) -> None:
    store.put_source(_source("a"))
    store.put_admission(_admission("a", "d1"))
    assert store.latest_admission(_sid("a")).decision_id == "d1"
    store.put_admission(_admission("a", "d2", AdmissionDecision.EXCLUDED_BY_POLICY))
    assert store.latest_admission(_sid("a")).decision_id == "d2"
    store.put_admission(_admission("a", "d1"))  # 旧决定同内容重放：不得回退指针
    assert store.latest_admission(_sid("a")).decision_id == "d2"
    from dataclasses import replace

    with pytest.raises(StoreError, match="admission 冲突"):
        store.put_admission(replace(_admission("a", "d1"), policy_rev="vX"))
    assert store.get_admission("d1") == _admission("a", "d1")


# ---- 构建 ----


def test_pg_build_idempotent_and_conflict(store: PgStore) -> None:
    from dataclasses import replace

    store.put_source(_source("a"))
    store.put_admission(_admission("a", "d1"))
    store.put_build(_build("a", "d1"))
    store.put_build(_build("a", "d1"))  # 幂等
    with pytest.raises(StoreError, match="build 冲突"):
        store.put_build(replace(_build("a", "d1"), parse_rev="other"))
    assert store.get_build(_build("a", "d1").build_id).parse_rev == "parse-test"


# ---- units/chunks 所有权门 ----


def test_pg_units_require_ownership(store: PgStore) -> None:
    build_id = _seed_build(store, "a", "d1")
    unit = _unit("a", build_id, "u1")
    with pytest.raises(StoreError, match="未登记"):
        store.put_units(build_id, [unit])
    store.register_job(build_id, JobStage.PARSED)
    with pytest.raises(StoreError, match="必须携带当前租约"):
        store.put_units(build_id, [unit])
    acquired = store.acquire_job(build_id, JobStage.PARSED, "w1", NOW, LEASE)
    store.put_units(build_id, [unit], owner_id="w1", fence_token=acquired.fence_token)
    with pytest.raises(StoreError, match="lease_lost"):
        store.put_units(build_id, [_unit("a", build_id, "u2")], owner_id="w2", fence_token="x")
    assert store.get_unit(build_id, "u1") == unit


def test_pg_units_expired_lease_refused(store: PgStore) -> None:
    build_id = _seed_build(store, "a", "d1")
    store.register_job(build_id, JobStage.PARSED)
    acquired = store.acquire_job(build_id, JobStage.PARSED, "w1", NOW, LEASE)
    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE corpus.corpus_jobs SET lease_until = now() - interval '1 second' "
            "WHERE build_id = %s AND stage = 'parsed'",
            (build_id,),
        )
    with pytest.raises(StoreError, match="租约已过期"):
        store.put_units(
            build_id, [_unit("a", build_id, "u1")], owner_id="w1", fence_token=acquired.fence_token
        )


def test_pg_units_idempotent_and_conflict(store: PgStore) -> None:

    build_id = _seed_build(store, "a", "d1")
    acquired = _acquired_parsed(store, build_id)
    unit = _unit("a", build_id, "u1")
    store.put_units(build_id, [unit], owner_id="w1", fence_token=acquired.fence_token)
    store.put_units(build_id, [unit], owner_id="w1", fence_token=acquired.fence_token)  # 幂等
    drifted_raw = "changed"
    drifted = Unit(
        unit_id="u1",
        build_id=build_id,
        kind="paragraph",
        raw_text=drifted_raw,
        content_hash=sha256_of_bytes(drifted_raw.encode()),
        ordinal=1,
    )
    with pytest.raises(StoreError, match="unit 冲突"):
        store.put_units(build_id, [drifted], owner_id="w1", fence_token=acquired.fence_token)
    assert store.get_units(build_id) == (unit,)


# ---- job 生命周期 ----


def test_pg_job_lifecycle_and_attempt_history(store: PgStore) -> None:
    build_id = _seed_build(store, "a", "d1")
    store.register_job(build_id, JobStage.PARSED)
    acquired = store.acquire_job(build_id, JobStage.PARSED, "w1", NOW, LEASE)
    assert acquired.attempt == 1 and acquired.state is JobState.RUNNING
    assert store.get_job(build_id, JobStage.PARSED) == acquired

    with pytest.raises(StoreError, match="不得抢占"):
        store.acquire_job(build_id, JobStage.PARSED, "w2", NOW, LEASE)

    finished = store.finish_job(
        build_id,
        JobStage.PARSED,
        "w1",
        acquired.fence_token,
        NOW,
        JobState.FAILED,
        error="boom",
        checkpoint='{"schema_rev": "parse-checkpoint-2"}',
    )
    assert finished.state is JobState.FAILED and finished.error == "boom"
    # 提交成功响应丢失：同终态重试幂等
    assert (
        store.finish_job(
            build_id,
            JobStage.PARSED,
            "w1",
            acquired.fence_token,
            NOW,
            JobState.FAILED,
            error="boom",
        )
        == finished
    )

    # 失败重试：attempt+1（历史追加）
    retried = store.acquire_job(build_id, JobStage.PARSED, "w2", NOW, LEASE)
    assert retried.attempt == 2 and retried.owner_id == "w2"
    assert retried.fence_token != acquired.fence_token
    done = store.finish_job(
        build_id, JobStage.PARSED, "w2", retried.fence_token, NOW, JobState.SUCCEEDED
    )
    assert done.state is JobState.SUCCEEDED
    # 成功阶段幂等短路
    assert store.acquire_job(build_id, JobStage.PARSED, "w3", NOW, LEASE).attempt == 2


def test_pg_job_max_attempts_enforced(store: PgStore) -> None:
    build_id = _seed_build(store, "a", "d1")
    store.register_job(build_id, JobStage.PARSED)
    for i in range(LEASE.max_attempts):
        owner = f"w{i}"
        acquired = store.acquire_job(build_id, JobStage.PARSED, owner, NOW, LEASE)
        store.finish_job(
            build_id, JobStage.PARSED, owner, acquired.fence_token, NOW, JobState.FAILED
        )
    with pytest.raises(StoreError, match="max_attempts"):
        store.acquire_job(build_id, JobStage.PARSED, "wN", NOW, LEASE)


def test_pg_job_expired_takeover_and_stale_write_refused(store: PgStore) -> None:
    build_id = _seed_build(store, "a", "d1")
    store.register_job(build_id, JobStage.PARSED)
    first = store.acquire_job(build_id, JobStage.PARSED, "w1", NOW, LEASE)
    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE corpus.corpus_jobs SET lease_until = now() - interval '1 second' "
            "WHERE build_id = %s AND stage = 'parsed'",
            (build_id,),
        )
    second = store.acquire_job(build_id, JobStage.PARSED, "w2", NOW, LEASE)
    assert second.attempt == 2 and second.owner_id == "w2"
    # 旧 token 迟到提交：lease_lost
    with pytest.raises(StoreError, match="lease_lost"):
        store.finish_job(
            build_id, JobStage.PARSED, "w1", first.fence_token, NOW, JobState.SUCCEEDED
        )
    # 新 token 正常提交
    store.finish_job(build_id, JobStage.PARSED, "w2", second.fence_token, NOW, JobState.SUCCEEDED)


def test_pg_cancelled_not_revived_but_published_can(store: PgStore) -> None:
    build_id = _seed_build(store, "a", "d1")
    store.register_job(build_id, JobStage.PARSED)
    acquired = store.acquire_job(build_id, JobStage.PARSED, "w1", NOW, LEASE)
    store.finish_job(build_id, JobStage.PARSED, "w1", acquired.fence_token, NOW, JobState.CANCELLED)
    with pytest.raises(StoreError, match="cancelled job 不自动复活"):
        store.acquire_job(build_id, JobStage.PARSED, "w2", NOW, LEASE)

    store.register_job(build_id, JobStage.PUBLISHED)
    pub1 = store.acquire_job(build_id, JobStage.PUBLISHED, "w1", NOW, LEASE)
    store.finish_job(build_id, JobStage.PUBLISHED, "w1", pub1.fence_token, NOW, JobState.CANCELLED)
    pub2 = store.acquire_job(build_id, JobStage.PUBLISHED, "w1", NOW, LEASE)
    assert pub2.attempt == 2  # PUBLISHED 例外：可重新 acquire（消耗预算）


# ---- 发布（publish_idempotency_v2）----


def test_pg_publish_happy_state_compare_and_retire(store: PgStore) -> None:
    build_id = _seed_build(store, "a", "d1")
    store.register_job(build_id, JobStage.PUBLISHED)
    acquired = store.acquire_job(build_id, JobStage.PUBLISHED, "w1", NOW, LEASE)
    first = store.publish(
        _sid("a"),
        "d1",
        build_id,
        NOW,
        owner_id="w1",
        fence_token=acquired.fence_token,
    )
    assert first.generation == 1 and first.active_build_id == build_id
    # engine.publish_build 成功后 finish_job(SUCCEEDED)；store 级测试同协议。
    store.finish_job(
        build_id, JobStage.PUBLISHED, "w1", acquired.fence_token, NOW, JobState.SUCCEEDED
    )
    # 同目标状态的 store 级重试需新租约（engine 层由短路免租约——见 20260917 探针）：
    # 响应丢失 + 重新 acquire（新 attempt/token）+ 时间前进 → 仍恒幂等（G2）
    reacquired = store.acquire_job(build_id, JobStage.PUBLISHED, "w1", NOW, LEASE)
    lost = store.publish(
        _sid("a"),
        "d1",
        build_id,
        NOW + timedelta(hours=1),
        owner_id="w1",
        fence_token=reacquired.fence_token,
    )
    assert lost == first and lost.generation == 1 and lost.activated_at == first.activated_at

    # retire：指针翻转 → generation+1
    retired = store.retire(_sid("a"), "d1", NOW)
    assert retired.active_build_id is None and retired.generation == 2
    # 重新发布 → generation 3
    republished = store.publish(
        _sid("a"), "d1", build_id, NOW, owner_id="w1", fence_token=reacquired.fence_token
    )
    assert republished.generation == 3
    assert isinstance(republished, Publication)


def test_pg_publish_requires_ownership_latest_and_in_scope(store: PgStore) -> None:
    build_id = _seed_build(store, "a", "d1")
    with pytest.raises(StoreError, match="PUBLISHED job"):
        store.publish(_sid("a"), "d1", build_id, NOW, owner_id="w", fence_token="t")

    store.register_job(build_id, JobStage.PUBLISHED)
    acquired = store.acquire_job(build_id, JobStage.PUBLISHED, "w1", NOW, LEASE)

    store.put_admission(_admission("a", "d2", AdmissionDecision.EXCLUDED_BY_POLICY))
    build_d2 = _build("a", "d2")
    store.put_build(build_d2)
    store.register_job(build_d2.build_id, JobStage.PUBLISHED)
    acquired_d2 = store.acquire_job(build_d2.build_id, JobStage.PUBLISHED, "w1", NOW, LEASE)
    # 非 in_scope：build/决定一致且为当前决定，但排除决定不得发布
    with pytest.raises(StoreError, match="非 in_scope"):
        store.publish(
            _sid("a"),
            "d2",
            build_d2.build_id,
            NOW,
            owner_id="w1",
            fence_token=acquired_d2.fence_token,
        )
    # 非当前决定拒绝（指针在 d2）
    with pytest.raises(StoreError, match="当前决定"):
        store.publish(
            _sid("a"), "d1", build_id, NOW, owner_id="w1", fence_token=acquired.fence_token
        )
    # build 绑定决定与请求不一致拒绝
    with pytest.raises(StoreError, match="不一致"):
        store.publish(
            _sid("a"), "dX", build_id, NOW, owner_id="w1", fence_token=acquired.fence_token
        )


# ---- 来源级检查点 ----


def test_pg_source_checkpoint_last_write_wins(store: PgStore) -> None:
    sid = _sid("a")
    store.put_source_checkpoint(sid, "parsed", '{"schema_rev": "parse-checkpoint-2", "v": 1}')
    store.put_source_checkpoint(sid, "parsed", '{"schema_rev": "parse-checkpoint-2", "v": 2}')
    assert '"v": 2' in store.get_source_checkpoint(sid, "parsed")
    assert store.get_source_checkpoint(sid, "cleaned") is None
    with pytest.raises(StoreError, match=r"source 非法|source_checkpoint"):
        store.put_source_checkpoint("short", "parsed", "{}")


# ---- engine + PgStore 端到端（Store Seam 可替换性冒烟）----


def test_pg_engine_full_chain_with_publication(store: PgStore) -> None:
    # 归档目录置于仓库内（守卫 runtime_roots 可读；/tmp 不在 I2 守卫读取范围）。
    import shutil
    import uuid

    archive_root = (
        Path(__file__).resolve().parents[1]
        / f".scratch/corpus-evidence-pipeline/ingestion-rebuild/i2/tmp/archive-{uuid.uuid4().hex[:8]}"
    )
    archive_root.parent.mkdir(parents=True, exist_ok=True)
    try:
        _run_engine_chain(store, archive_root)
    finally:
        shutil.rmtree(archive_root, ignore_errors=True)


def _run_engine_chain(store: PgStore, archive_root: Path) -> None:
    fixture = (
        Path(__file__).resolve().parents[1]
        / "tests/fixtures/corpus_preparation/synthetic-company-report.md"
    )
    policy = AdmissionPolicy(POLICY_REV_V1, tuple(ResearchDomain))
    store.put_reviewed_decision(
        ReviewedDecision(
            "r1",
            sha256_of_bytes(fixture.read_bytes()),
            "i2s2-test",
            NOW,
            ReviewDecision.ADMITTED,
            "synthetic whole-source admission",
        )
    )
    plan = plan_builds(
        [PlanEntry(str(fixture), domain_hint=ResearchDomain.COMPANY, review_decision_ids=("r1",))],
        policy=policy,
    )
    outcome = execute_builds(
        store,
        plan,
        policy=policy,
        archive_root=archive_root,
        owner_id="i2s2-engine",
        now=NOW,
        lease=LEASE,
    ).outcomes[0]
    assert outcome.build is not None
    build_id = outcome.build.build_id
    assert outcome.unit_count > 0

    units = store.get_units(build_id)
    chunks = store.get_chunks(build_id)
    assert units and chunks  # 权威产物已落 PG（fencing 门下写入）

    publication = publish_build(store, build_id, activated_at=NOW)
    assert publication.generation == 1 and publication.active_build_id == build_id
    # 幂等重放（engine 短路：同目标状态直接返回）
    assert publish_build(store, build_id, activated_at=NOW) == publication

    # I2-3：发布后经读侧 FTS 服务活动范围；zhcfg 含 'm' 数词映射，数字 token
    # （23.5%）与中文关键词均可命中（§7.1 数字固定，"47.3亿" 类不被丢弃）。
    hits = search_chunks(DSN, "营业收入")
    assert hits and all(h.build_id == build_id for h in hits)
    hits_num = search_chunks(DSN, "23.5")
    assert hits_num and all(h.source_id == sha256_of_bytes(fixture.read_bytes()) for h in hits_num)


# ---- I2-3 FTS 读侧检索（先筛活动范围，再排名）----


def _chunk(build_id: str, key: str, search_text: str) -> Chunk:
    return Chunk(
        chunk_id=f"{build_id[:16]}:{key}",
        build_id=build_id,
        kind="paragraph",
        unit_refs=("u1",),
        search_text=search_text,
    )


def _chunked_published(
    store: PgStore, tag: str, decision_id: str, build_id: str, texts: tuple[str, ...]
) -> None:
    """CHUNKED 租约下写入可命中 chunk，再走 PUBLISHED 租约完成发布。"""
    store.register_job(build_id, JobStage.CHUNKED)
    c_acq = store.acquire_job(build_id, JobStage.CHUNKED, "w1", NOW, LEASE)
    store.put_chunks(
        build_id,
        [_chunk(build_id, f"c{i}", t) for i, t in enumerate(texts)],
        owner_id="w1",
        fence_token=c_acq.fence_token,
    )
    store.register_job(build_id, JobStage.PUBLISHED)
    p_acq = store.acquire_job(build_id, JobStage.PUBLISHED, "w1", NOW, LEASE)
    store.publish(
        _sid(tag), decision_id, build_id, NOW, owner_id="w1", fence_token=p_acq.fence_token
    )
    store.finish_job(build_id, JobStage.PUBLISHED, "w1", p_acq.fence_token, NOW, JobState.SUCCEEDED)


def test_pg_search_scoped_to_active_build(store: PgStore) -> None:
    # 活动版本唯一服务面：旧 build A 命中 → 索引升级换新 index_rev ⇒ 新 build B
    # 全量重建并接管指针 ⇒ 检索只返回 B（退役/旧版本永不混入候选）。
    build_a = _seed_build(store, "a", "d1")
    _chunked_published(store, "a", "d1", build_a, ("石英股份高纯砂产能同比增长",))
    hits = search_chunks(DSN, "石英")
    assert [(h.build_id, h.chunk_id) for h in hits] == [(build_a, f"{build_a[:16]}:c0")]

    # 索引升级可重建：新 index_rev ⇒ 新 build_id ⇒ 全新 chunk 集可被检索。
    build_b = _seed_build(store, "a", "d1", sha256_of_bytes(b"build:a:d1:v2"))
    assert build_b != build_a
    _chunked_published(store, "a", "d1", build_b, ("石英股份高纯砂良率提升",))
    hits = search_chunks(DSN, "石英")
    assert [h.build_id for h in hits] == [build_b]

    # 未发布 build 的匹配 chunk 永不入候选（无 publications 行）。
    build_c = _seed_build(store, "a", "d1", sha256_of_bytes(b"build:a:d1:v3"))
    store.register_job(build_c, JobStage.CHUNKED)
    c_acq = store.acquire_job(build_c, JobStage.CHUNKED, "w1", NOW, LEASE)
    store.put_chunks(
        build_c,
        [_chunk(build_c, "c0", "石英股份隐藏草稿")],
        owner_id="w1",
        fence_token=c_acq.fence_token,
    )
    assert search_chunks(DSN, "隐藏草稿") == ()

    # retire：活动指针置空 ⇒ 零候选（不从退役库混查）。
    store.retire(_sid("a"), "d1", NOW)
    assert search_chunks(DSN, "石英") == ()


def _admission_with_snapshot(
    tag: str,
    decision_id: str,
    *,
    domain: ResearchDomain,
    pub_value: str | None = None,
) -> Admission:
    snapshot = (
        MetadataSnapshot(
            report_publication=ReportPublication(
                value=pub_value,
                precision=PublicationDatePrecision.DATE,
                status=PublicationDateStatus.KNOWN,
                evidence_refs=("page:1",),
                origin=PublicationDateOrigin.SOURCE_EXPLICIT,
            )
        )
        if pub_value
        else MetadataSnapshot()
    )
    return Admission(
        decision_id=decision_id,
        source_id=_sid(tag),
        material_type=MaterialType.RESEARCH_REPORT,
        research_domain=domain,
        decision=AdmissionDecision.IN_SCOPE,
        policy_rev="v1-20260915",
        metadata_snapshot=snapshot,
    )


def test_pg_search_domain_and_date_filters(store: PgStore) -> None:
    # a：公司域 + 研报发布日期快照；b：行业域、无快照。
    store.put_source(_source("a"))
    store.put_admission(
        _admission_with_snapshot("a", "d1", domain=ResearchDomain.COMPANY, pub_value="2026-08-01")
    )
    build_a = sha256_of_bytes(b"build:a:d1")
    store.put_build(_build("a", "d1", build_a))
    _chunked_published(store, "a", "d1", build_a, ("石英股份第三季度指引",))

    store.put_source(_source("b"))
    store.put_admission(_admission_with_snapshot("b", "d2", domain=ResearchDomain.INDUSTRY))
    build_b = sha256_of_bytes(b"build:b:d2")
    store.put_build(_build("b", "d2", build_b))
    _chunked_published(store, "b", "d2", build_b, ("石英砂行业景气度跟踪",))

    # 分词召回边界（SCWS 词典）："石英股份" 非词典词切为 石英+股份，"石英砂"
    # 是词典整词；查询 token 与文档 token 精确匹配，故用各自可命中的词断言召回。
    assert {h.source_id for h in search_chunks(DSN, "石英")} == {_sid("a")}
    assert {h.source_id for h in search_chunks(DSN, "景气")} == {_sid("b")}
    # 领域过滤经 build 的 admission（partial 索引 idx_admissions_domain）。
    assert {h.source_id for h in search_chunks(DSN, "石英", domain=ResearchDomain.COMPANY)} == {
        _sid("a")
    }
    assert {h.source_id for h in search_chunks(DSN, "景气", domain=ResearchDomain.INDUSTRY)} == {
        _sid("b")
    }
    # 日期过滤（ISO 文本序=时序，闭区间）：无快照的 admission 不命中。
    ranged = search_chunks(DSN, "石英", published_from="2026-07-01", published_to="2026-08-31")
    assert {h.source_id for h in ranged} == {_sid("a")}
    assert search_chunks(DSN, "石英", published_from="2026-09-01") == ()


def test_pg_search_fail_closed_and_validation() -> None:
    # apodex 反证分支仅在含 apodex 库的实例上可触发（生产实例），沙箱容器无法构造。
    with pytest.raises(StoreError, match="≠"):
        search_chunks(DSN, "石英", sandbox_db="not_the_sandbox")
    with pytest.raises(StoreError, match="query 不能为空"):
        search_chunks(DSN, "   ")
    with pytest.raises(StoreError, match="limit"):
        search_chunks(DSN, "石英", limit=0)
