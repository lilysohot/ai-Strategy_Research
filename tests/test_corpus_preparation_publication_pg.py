"""I2-5 publication_pg 门：真 PG 双 worker、租约接管与发布并发（§12.2 测试族）。

运行条件：``CORPUS_I2_DSN`` 指向隔离库 ``i2_sandbox_corpus``（i2-sandbox 守卫 env）；
无 DSN 时模块级跳过（I2-5 过门时必须实际运行，不得 skip）。

覆盖（tasks.md I2-5 关键步骤 + design-review C7 ``acceptance_cases_i2_5``）：

- 双 worker 并发 acquire 同一 job：恰一成功（行锁等待后重判 + partial unique 兜底）；
- **真实停顿**越过 TTL 后的过期接管（不以后台改写 lease_until 代替计时证据）；
- 陈旧 token 的迟到提交（put_units/put_chunks/heartbeat/finish/publish）全部 lease_lost；
- 提交成功但响应丢失：重放幂等，不增行、不递增 generation（G2 目标状态比对）；
- cancelled 不自动复活（PUBLISHED 例外）与取消后接管发布；
- max_attempts 在失败重试 / 过期接管 / PUBLISHED 重激活三条路径的边界；
- 并发发布（同决定下两个 build）与 retire 竞态：指针单行、generation 单调、无撕裂状态；
- 失败阶段恢复到新 attempt，单元/切块不重复增行；
- 配置/索引版本升级 → 新 build_id 全量重建，读侧随活动指针切换；
- 续租正向路径：heartbeat 成功后 lease_until 前移、过期后不得原地续命（RM-5）；
- 连接断开：指针已切、finish 未提交时无半提交且可补齐（RM-6，区别于响应丢失的重放）；
- 引擎入口恢复：经 publish_build 与 VERIFIED 门，断连后重试补齐 PUBLISHED 终态（RM-8）。

数据纪律：仅写 i2_sandbox_corpus 的 corpus schema，每用例前 TRUNCATE（目标双校验）；
不触碰 i0b2_verify_* 与任何生产库。
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

DSN = os.environ.get("CORPUS_I2_DSN", "")
if not DSN:
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
    ResearchDomain,
    Source,
    Unit,
    UnitStatus,
    compute_build_id,
    sha256_of_bytes,
)
from plugins.corpus.preparation.engine import INDEX_REV_V3, publish_build  # noqa: E402
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
# I0C-2 冻结运行参数不改；短租约仅用于真实计时类接管用例（heartbeat=1 ≤ TTL/3）。
LEASE = LeaseConfig(300, 60, 600, 3)
SHORT_LEASE = LeaseConfig(3, 1, 6, 3)
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
        cur.execute(f"TRUNCATE {qualified}")
    yield


@pytest.fixture()
def store() -> PgStore:
    instance = PgStore(DSN, sandbox_db=SANDBOX_DB)
    yield instance
    instance.close()


def _connect() -> psycopg.Connection:
    return psycopg.connect(DSN, autocommit=True)


# ---- 并发 worker（真线程 + 真连接）----


class _Worker(threading.Thread):
    """捕获原始结果或异常；失败本身即证据，不做断言放松。"""

    def __init__(self, fn: Callable[[], object], barrier: threading.Barrier) -> None:
        super().__init__(daemon=True)
        self._fn = fn
        self._barrier = barrier
        self.outcome: object = None

    def run(self) -> None:
        try:
            self._barrier.wait(timeout=30)
            self.outcome = self._fn()
        except BaseException as exc:  # 竞态异常必须可见
            self.outcome = exc


def _race(*fns: Callable[[], object]) -> list[object]:
    barrier = threading.Barrier(len(fns))
    workers = [_Worker(fn, barrier) for fn in fns]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=60)
    alive = [w for w in workers if w.is_alive()]
    assert not alive, f"并发 worker 未在时限内结束：{len(alive)} 个仍存活"
    return [worker.outcome for worker in workers]


def _worker_store() -> PgStore:
    """每个 worker 独占连接（PG 连接不跨线程复用）。"""
    return PgStore(DSN, sandbox_db=SANDBOX_DB)


# ---- 夹具 ----


def _sid(tag: str) -> str:
    return sha256_of_bytes(f"i2s5:{tag}".encode())


def _source(tag: str) -> Source:
    return Source(
        source_id=_sid(tag),
        format=DocumentFormat.MARKDOWN,
        mime_type="text/markdown",
        size_bytes=128,
        archive_path=f"ab/{_sid(tag)}.md",
        original_names=(f"{tag}.md",),
    )


def _admission(
    tag: str, decision_id: str, decision: AdmissionDecision = AdmissionDecision.IN_SCOPE
) -> Admission:
    in_scope = decision is AdmissionDecision.IN_SCOPE
    return Admission(
        decision_id=decision_id,
        source_id=_sid(tag),
        material_type=MaterialType.RESEARCH_REPORT if in_scope else MaterialType.PIPELINE_ARTIFACT,
        research_domain=ResearchDomain.COMPANY if in_scope else None,
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


def _unit(build_id: str, unit_id: str, ordinal: int = 1) -> Unit:
    raw = f"raw text of {unit_id}"
    return Unit(
        unit_id=unit_id,
        build_id=build_id,
        kind="paragraph",
        raw_text=raw,
        content_hash=sha256_of_bytes(raw.encode()),
        ordinal=ordinal,
        status=UnitStatus.KEPT,
    )


def _chunk(build_id: str, key: str, search_text: str) -> Chunk:
    return Chunk(
        chunk_id=f"{build_id[:16]}:{key}",
        build_id=build_id,
        kind="paragraph",
        unit_refs=("u1",),
        search_text=search_text,
    )


def _seed_build(store: PgStore, tag: str, decision_id: str, build_id: str | None = None) -> str:
    store.put_source(_source(tag))
    store.put_admission(_admission(tag, decision_id))
    build = _build(tag, decision_id, build_id)
    store.put_build(build)
    return build.build_id


def _publish_chain(
    store: PgStore,
    tag: str,
    decision_id: str,
    build_id: str,
    owner: str,
    texts: tuple[str, ...] = (),
) -> int:
    """CHUNKED → PUBLISHED 双租约发布（与 engine 同协议），返回 generation。"""
    store.register_job(build_id, JobStage.CHUNKED)
    chunked = store.acquire_job(build_id, JobStage.CHUNKED, owner, NOW, LEASE)
    if texts:
        store.put_chunks(
            build_id,
            [_chunk(build_id, f"c{i}", text) for i, text in enumerate(texts)],
            owner_id=owner,
            fence_token=chunked.fence_token,
        )
    store.finish_job(
        build_id, JobStage.CHUNKED, owner, chunked.fence_token, NOW, JobState.SUCCEEDED
    )
    store.register_job(build_id, JobStage.PUBLISHED)
    published = store.acquire_job(build_id, JobStage.PUBLISHED, owner, NOW, LEASE)
    publication = store.publish(
        _sid(tag), decision_id, build_id, NOW, owner_id=owner, fence_token=published.fence_token
    )
    store.finish_job(
        build_id, JobStage.PUBLISHED, owner, published.fence_token, NOW, JobState.SUCCEEDED
    )
    return publication.generation


# ---- 观测辅助（只读取证，不参与被测行为）----


def _attempt_rows(build_id: str, stage: JobStage) -> list[tuple[int, str, str | None]]:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT attempt, state, owner_id FROM corpus.corpus_jobs "
            "WHERE build_id = %s AND stage = %s ORDER BY attempt",
            (build_id, stage.value),
        )
        return [(int(row[0]), str(row[1]), row[2]) for row in cur.fetchall()]


def _publication_rows() -> list[tuple[str, str, str | None, int]]:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT source_id, current_decision_id, active_build_id, generation "
            "FROM corpus.corpus_publications"
        )
        return [(str(row[0]), str(row[1]), row[2], int(row[3])) for row in cur.fetchall()]


def _backdate_leases(build_id: str) -> None:
    """把该 build 的 running 租约改写为已过期（记账式模拟；真实计时见 test_live_*）。"""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE corpus.corpus_jobs SET lease_until = now() - interval '1 second' "
            "WHERE build_id = %s AND state = 'running'",
            (build_id,),
        )


# ---- 1. 双 worker 并发 acquire / register（acceptance case 1）----


def test_double_worker_concurrent_acquire_single_winner(store: PgStore) -> None:
    build_id = _seed_build(store, "race", "d1")
    store.register_job(build_id, JobStage.PARSED)

    def attempt(owner: str) -> tuple[str, int]:
        worker = _worker_store()
        try:
            job = worker.acquire_job(build_id, JobStage.PARSED, owner, NOW, LEASE)
            return (owner, job.attempt)
        finally:
            worker.close()

    outcomes = _race(lambda: attempt("w1"), lambda: attempt("w2"))
    winners = [o for o in outcomes if not isinstance(o, BaseException)]
    losers = [o for o in outcomes if isinstance(o, BaseException)]
    assert len(winners) == 1, f"并发 acquire 赢家不唯一：{outcomes}"
    assert len(losers) == 1
    assert isinstance(losers[0], StoreError)
    assert "不得抢占" in str(losers[0])
    assert _attempt_rows(build_id, JobStage.PARSED) == [
        (1, "running", winners[0][0])
    ]  # 单活租约：仅一行 attempt


def test_double_worker_concurrent_takeover_expired_lease_single_attempt(
    store: PgStore,
) -> None:
    """两个 worker 同时接管同一过期租约：只能产生一个新 attempt（J1 advisory 锁回归）。

    行锁只能锁住已存在的 attempt 行，无法阻止并发 INSERT 同一 attempt 号；修复前该
    竞态会把数据库 UniqueViolation 直接抛给调用方（register/acquire 见同族用例）。
    """
    build_id = _seed_build(store, "takeover", "d-takeover")
    store.register_job(build_id, JobStage.PARSED)
    store.acquire_job(build_id, JobStage.PARSED, "w1", NOW, LEASE)
    _backdate_leases(build_id)

    def takeover(owner: str) -> tuple[str, int]:
        worker = _worker_store()
        try:
            job = worker.acquire_job(build_id, JobStage.PARSED, owner, NOW, LEASE)
            return (owner, job.attempt)
        finally:
            worker.close()

    outcomes = _race(lambda: takeover("w2"), lambda: takeover("w3"))
    winners = [o for o in outcomes if not isinstance(o, BaseException)]
    losers = [o for o in outcomes if isinstance(o, BaseException)]
    assert len(winners) == 1, f"并发接管赢家不唯一：{outcomes}"
    assert all(isinstance(o, StoreError) for o in losers)
    assert winners[0][1] == 2
    rows = _attempt_rows(build_id, JobStage.PARSED)
    assert [row[0] for row in rows] == [1, 2]  # 无重复 attempt 行
    assert rows[1][1:] == ("running", winners[0][0])


def test_double_worker_concurrent_register_single_row(store: PgStore) -> None:
    build_id = _seed_build(store, "register", "d1")

    def register() -> int:
        worker = _worker_store()
        try:
            return worker.register_job(build_id, JobStage.PARSED).attempt
        finally:
            worker.close()

    outcomes = _race(register, register)
    assert all(not isinstance(o, BaseException) for o in outcomes), outcomes
    assert _attempt_rows(build_id, JobStage.PARSED) == [(1, "queued", None)]


# ---- 2. 真实计时接管（I2-5 实测：停顿越过 TTL）----


def test_live_lease_expiry_takeover_and_stale_token_refused(store: PgStore) -> None:
    build_id = _seed_build(store, "ttl", "d1")
    store.register_job(build_id, JobStage.PARSED)
    first = store.acquire_job(build_id, JobStage.PARSED, "w1", NOW, SHORT_LEASE)
    assert first.attempt == 1

    # 真实停顿越过 lease_ttl_seconds（I0C-2 i2_pending_verification 要求的
    # "停顿/延迟实测 TTL 过期与接管恰好临界"，不以后台改写代替。）
    time.sleep(SHORT_LEASE.lease_ttl_seconds + 1.2)

    second = store.acquire_job(build_id, JobStage.PARSED, "w2", NOW, SHORT_LEASE)
    assert second.attempt == first.attempt + 1
    assert second.owner_id == "w2"
    assert second.fence_token != first.fence_token
    assert [row[:2] for row in _attempt_rows(build_id, JobStage.PARSED)] == [
        (1, "failed"),  # 过期行被接管时落为 failed，历史保留（G1）
        (2, "running"),
    ]

    unit = _unit(build_id, "u1")
    with pytest.raises(StoreError, match="lease_lost"):
        store.put_units(build_id, [unit], owner_id="w1", fence_token=first.fence_token)
    with pytest.raises(StoreError, match="lease_lost"):
        store.heartbeat_job(build_id, JobStage.PARSED, "w1", first.fence_token, NOW, SHORT_LEASE)
    with pytest.raises(StoreError, match="lease_lost"):
        store.finish_job(
            build_id, JobStage.PARSED, "w1", first.fence_token, NOW, JobState.SUCCEEDED
        )

    # 接管者写入完整有效
    store.put_units(build_id, [unit], owner_id="w2", fence_token=second.fence_token)
    assert store.get_units(build_id) == (unit,)


# ---- 3. 陈旧 worker 迟到提交不改变接管结果 ----


def test_stale_worker_late_commit_does_not_overwrite_takeover(store: PgStore) -> None:
    build_id = _seed_build(store, "late", "d1")
    for stage in (JobStage.PARSED, JobStage.CHUNKED, JobStage.PUBLISHED):
        store.register_job(build_id, stage)
    first_parsed = store.acquire_job(build_id, JobStage.PARSED, "w1", NOW, LEASE)
    first_chunked = store.acquire_job(build_id, JobStage.CHUNKED, "w1", NOW, LEASE)
    first_published = store.acquire_job(build_id, JobStage.PUBLISHED, "w1", NOW, LEASE)
    _backdate_leases(build_id)

    second_parsed = store.acquire_job(build_id, JobStage.PARSED, "w2", NOW, LEASE)
    assert second_parsed.attempt == 2
    unit_new = _unit(build_id, "u-new")
    store.put_units(build_id, [unit_new], owner_id="w2", fence_token=second_parsed.fence_token)
    store.finish_job(
        build_id, JobStage.PARSED, "w2", second_parsed.fence_token, NOW, JobState.SUCCEEDED
    )
    second_chunked = store.acquire_job(build_id, JobStage.CHUNKED, "w2", NOW, LEASE)
    chunk_new = _chunk(build_id, "c-new", "接管者写入的切块")
    store.put_chunks(build_id, [chunk_new], owner_id="w2", fence_token=second_chunked.fence_token)
    store.finish_job(
        build_id, JobStage.CHUNKED, "w2", second_chunked.fence_token, NOW, JobState.SUCCEEDED
    )
    second_published = store.acquire_job(build_id, JobStage.PUBLISHED, "w2", NOW, LEASE)
    publication = store.publish(
        _sid("late"), "d1", build_id, NOW, owner_id="w2", fence_token=second_published.fence_token
    )
    assert publication.generation == 1

    with pytest.raises(StoreError, match="lease_lost"):
        store.put_units(
            build_id,
            [_unit(build_id, "u-ghost", ordinal=2)],
            owner_id="w1",
            fence_token=first_parsed.fence_token,
        )
    with pytest.raises(StoreError, match="lease_lost"):
        store.put_chunks(
            build_id,
            [_chunk(build_id, "c-ghost", "陈旧 worker 的幽灵切块")],
            owner_id="w1",
            fence_token=first_chunked.fence_token,
        )
    with pytest.raises(StoreError, match="lease_lost"):
        store.publish(
            _sid("late"),
            "d1",
            build_id,
            NOW + timedelta(hours=1),
            owner_id="w1",
            fence_token=first_published.fence_token,
        )

    assert [u.unit_id for u in store.get_units(build_id)] == ["u-new"]
    assert [c.chunk_id for c in store.get_chunks(build_id)] == [chunk_new.chunk_id]
    current = store.get_publication(_sid("late"))
    assert current is not None and current.active_build_id == build_id
    assert current.generation == 1


# ---- 4. 提交成功但响应丢失（G2：目标状态比对）----


def test_lost_commit_response_replay_is_idempotent(store: PgStore) -> None:
    build_id = _seed_build(store, "lost", "d1")
    store.register_job(build_id, JobStage.PUBLISHED)
    acquired = store.acquire_job(build_id, JobStage.PUBLISHED, "w1", NOW, LEASE)
    first = store.publish(
        _sid("lost"), "d1", build_id, NOW, owner_id="w1", fence_token=acquired.fence_token
    )
    # 提交成功、客户端未收到响应：同租约原样重放（时钟前进也不得误判新激活）
    replay = store.publish(
        _sid("lost"),
        "d1",
        build_id,
        NOW + timedelta(seconds=5),
        owner_id="w1",
        fence_token=acquired.fence_token,
    )
    assert replay == first

    done = store.finish_job(
        build_id,
        JobStage.PUBLISHED,
        "w1",
        acquired.fence_token,
        NOW,
        JobState.SUCCEEDED,
        checkpoint='{"schema_rev": "publish-checkpoint-1"}',
    )
    again = store.finish_job(
        build_id, JobStage.PUBLISHED, "w1", acquired.fence_token, NOW, JobState.SUCCEEDED
    )
    assert again == done  # 不重复增行

    # 超时后重新取租约再发布：目标状态相同 → 仍恒幂等（generation/时间不刷新）
    reacquired = store.acquire_job(build_id, JobStage.PUBLISHED, "w1", NOW, LEASE)
    assert reacquired.attempt == 2
    after_reacquire = store.publish(
        _sid("lost"),
        "d1",
        build_id,
        NOW + timedelta(hours=1),
        owner_id="w1",
        fence_token=reacquired.fence_token,
    )
    assert after_reacquire == first
    rows = _publication_rows()
    assert len(rows) == 1 and rows[0][3] == 1  # 单行活动指针，generation 未漂移


# ---- 5. 取消：内容阶段不复活，PUBLISHED 例外且预算消耗 ----


def test_cancelled_not_revived_but_published_takeover_allowed(store: PgStore) -> None:
    build_id = _seed_build(store, "cancel", "d1")
    store.register_job(build_id, JobStage.PARSED)
    content = store.acquire_job(build_id, JobStage.PARSED, "w1", NOW, LEASE)
    store.finish_job(build_id, JobStage.PARSED, "w1", content.fence_token, NOW, JobState.CANCELLED)
    with pytest.raises(StoreError, match="cancelled job 不自动复活"):
        store.acquire_job(build_id, JobStage.PARSED, "w2", NOW, LEASE)

    store.register_job(build_id, JobStage.PUBLISHED)
    pub_first = store.acquire_job(build_id, JobStage.PUBLISHED, "w1", NOW, LEASE)
    store.finish_job(
        build_id, JobStage.PUBLISHED, "w1", pub_first.fence_token, NOW, JobState.CANCELLED
    )
    pub_second = store.acquire_job(build_id, JobStage.PUBLISHED, "w2", NOW, LEASE)
    assert pub_second.attempt == 2  # PUBLISHED 例外：消耗 attempt 预算
    publication = store.publish(
        _sid("cancel"), "d1", build_id, NOW, owner_id="w2", fence_token=pub_second.fence_token
    )
    assert publication.generation == 1
    with pytest.raises(StoreError, match="lease_lost"):
        store.publish(
            _sid("cancel"), "d1", build_id, NOW, owner_id="w1", fence_token=pub_first.fence_token
        )
    assert [row[:2] for row in _attempt_rows(build_id, JobStage.PUBLISHED)] == [
        (1, "cancelled"),
        (2, "running"),
    ]


# ---- 6. max_attempts：失败重试 / 过期接管 / PUBLISHED 重激活 三条路径 ----


def test_max_attempts_boundary_across_all_retry_paths(store: PgStore) -> None:
    # decision_id 全局唯一且绑定 source_id：同一测试用例内每个 tag 用独立决定号。
    # (a) 失败重试耗预算
    failed_build = _seed_build(store, "budget-fail", "d-fail")
    store.register_job(failed_build, JobStage.PARSED)
    for index in range(LEASE.max_attempts):
        owner = f"f{index}"
        job = store.acquire_job(failed_build, JobStage.PARSED, owner, NOW, LEASE)
        store.finish_job(
            failed_build, JobStage.PARSED, owner, job.fence_token, NOW, JobState.FAILED
        )
    with pytest.raises(StoreError, match="max_attempts"):
        store.acquire_job(failed_build, JobStage.PARSED, "later", NOW, LEASE)

    # (b) 过期接管同样耗预算
    takeover_build = _seed_build(store, "budget-takeover", "d-takeover")
    store.register_job(takeover_build, JobStage.PARSED)
    attempts: list[int] = []
    for index in range(LEASE.max_attempts):
        job = store.acquire_job(takeover_build, JobStage.PARSED, f"t{index}", NOW, LEASE)
        attempts.append(job.attempt)
        _backdate_leases(takeover_build)
    assert attempts == [1, 2, 3]
    with pytest.raises(StoreError, match="max_attempts"):
        store.acquire_job(takeover_build, JobStage.PARSED, "tN", NOW, LEASE)

    # (c) PUBLISHED 重激活也耗预算
    published_build = _seed_build(store, "budget-publish", "d-publish")
    store.register_job(published_build, JobStage.PUBLISHED)
    for index in range(LEASE.max_attempts):
        job = store.acquire_job(published_build, JobStage.PUBLISHED, f"p{index}", NOW, LEASE)
        store.finish_job(
            published_build,
            JobStage.PUBLISHED,
            job.owner_id,
            job.fence_token,
            NOW,
            JobState.SUCCEEDED,
        )
    with pytest.raises(StoreError, match="max_attempts"):
        store.acquire_job(published_build, JobStage.PUBLISHED, "pN", NOW, LEASE)


# ---- 7. 并发发布：同决定下两个 build 竞态串行为单行指针 ----


def test_concurrent_publish_two_builds_keeps_single_active_pointer(store: PgStore) -> None:
    tag, decision_id = "conc", "d1"
    source = _sid(tag)
    build_a = sha256_of_bytes(b"i2s5:build:conc:a")
    build_b = sha256_of_bytes(b"i2s5:build:conc:b")
    _seed_build(store, tag, decision_id, build_a)
    _seed_build(store, tag, decision_id, build_b)

    def publish_self(build_id: str, owner: str) -> object:
        worker = _worker_store()
        try:
            worker.register_job(build_id, JobStage.PUBLISHED)
            job = worker.acquire_job(build_id, JobStage.PUBLISHED, owner, NOW, LEASE)
            return worker.publish(
                source, decision_id, build_id, NOW, owner_id=owner, fence_token=job.fence_token
            )
        finally:
            worker.close()

    outcomes = _race(
        lambda: publish_self(build_a, "wa"),
        lambda: publish_self(build_b, "wb"),
    )
    failures = [o for o in outcomes if isinstance(o, BaseException)]
    assert not failures, f"并发发布出现非预期失败：{failures}"

    rows = _publication_rows()
    assert len(rows) == 1  # 活动指针单行：并发不增行
    _, current_decision, active_build, generation = rows[0]
    assert current_decision == decision_id  # 决定列不被另一写者串改
    assert active_build in (build_a, build_b)
    assert generation == 2  # 两次目标状态翻转都真正提交，无丢更新


# ---- 8. retire 与重发布竞态：无撕裂状态、generation 单调 ----


def test_retire_races_republish_without_torn_state(store: PgStore) -> None:
    tag, decision_id = "retire", "d1"
    source = _sid(tag)
    build_a = sha256_of_bytes(b"i2s5:build:retire:a")
    build_b = sha256_of_bytes(b"i2s5:build:retire:b")
    _seed_build(store, tag, decision_id, build_a)
    _seed_build(store, tag, decision_id, build_b)
    generation_before = _publish_chain(
        store, tag, decision_id, build_a, "w1", ("石英股份产能跟踪",)
    )
    assert generation_before == 1

    def do_retire() -> object:
        worker = _worker_store()
        try:
            return worker.retire(source, decision_id, NOW)
        finally:
            worker.close()

    def do_publish() -> object:
        worker = _worker_store()
        try:
            worker.register_job(build_b, JobStage.PUBLISHED)
            job = worker.acquire_job(build_b, JobStage.PUBLISHED, "wb", NOW, LEASE)
            return worker.publish(
                source, decision_id, build_b, NOW, owner_id="wb", fence_token=job.fence_token
            )
        finally:
            worker.close()

    outcomes = _race(do_retire, do_publish)
    failures = [o for o in outcomes if isinstance(o, BaseException)]
    assert not failures, f"retire/发布竞态出现非预期失败：{failures}"

    raced = _publication_rows()
    assert len(raced) == 1  # 单行：不可能出现两个活动指针
    assert raced[0][1] == decision_id
    assert raced[0][2] in (None, build_b)
    assert raced[0][3] >= generation_before  # generation 单调不回退

    settled = store.retire(source, decision_id, NOW)
    assert settled.active_build_id is None
    assert store.get_publication(source) == settled  # 同目标状态重放幂等


# ---- 9. 撤销准入：排除决定后活动版本必须撤下 ----


def test_excluded_decision_withdraws_active_version(store: PgStore) -> None:
    tag, decision_id = "withdraw", "d1"
    source = _sid(tag)
    build_id = sha256_of_bytes(b"i2s5:build:withdraw")
    _seed_build(store, tag, decision_id, build_id)
    _publish_chain(store, tag, decision_id, build_id, "w1", ("石英股份高纯砂良率提升",))
    assert [h.build_id for h in search_chunks(DSN, "石英")] == [build_id]

    store.put_admission(_admission(tag, "d2", AdmissionDecision.EXCLUDED_BY_POLICY))
    store.register_job(build_id, JobStage.PUBLISHED)
    reacquired = store.acquire_job(build_id, JobStage.PUBLISHED, "w1", NOW, LEASE)
    # 旧决定已不是当前决定：不得再据它维持/重新发布活动版本
    with pytest.raises(StoreError, match="当前决定"):
        store.publish(
            source, decision_id, build_id, NOW, owner_id="w1", fence_token=reacquired.fence_token
        )
    # 旧 build 绑定 d1，却请求以 d2 发布：不得复用旧构建充当新决定的构建
    with pytest.raises(StoreError, match="不一致"):
        store.publish(
            source, "d2", build_id, NOW, owner_id="w1", fence_token=reacquired.fence_token
        )
    # 排除决定即使有绑定自身的 build，也不得切活动指针
    excluded_build = sha256_of_bytes(b"i2s5:build:withdraw:excluded")
    store.put_build(_build(tag, "d2", excluded_build))
    store.register_job(excluded_build, JobStage.PUBLISHED)
    excluded_lease = store.acquire_job(excluded_build, JobStage.PUBLISHED, "w1", NOW, LEASE)
    with pytest.raises(StoreError, match="非 in_scope"):
        store.publish(
            source,
            "d2",
            excluded_build,
            NOW,
            owner_id="w1",
            fence_token=excluded_lease.fence_token,
        )

    retired = store.retire(source, "d2", NOW)
    assert retired.current_decision_id == "d2"
    assert retired.active_build_id is None
    assert search_chunks(DSN, "石英") == ()  # 撤销后读侧零候选


# ---- 10. 失败阶段恢复：新 attempt 重写入库，无重复增行 ----


def test_failed_stage_recovers_on_new_attempt_without_duplicates(store: PgStore) -> None:
    build_id = _seed_build(store, "recover", "d1")
    store.register_job(build_id, JobStage.PARSED)
    first = store.acquire_job(build_id, JobStage.PARSED, "w1", NOW, LEASE)
    store.finish_job(
        build_id, JobStage.PARSED, "w1", first.fence_token, NOW, JobState.FAILED, error="crash"
    )

    retried = store.acquire_job(build_id, JobStage.PARSED, "w2", NOW, LEASE)
    assert retried.attempt == 2
    unit = _unit(build_id, "u1")
    store.put_units(build_id, [unit], owner_id="w2", fence_token=retried.fence_token)
    store.finish_job(
        build_id,
        JobStage.PARSED,
        "w2",
        retried.fence_token,
        NOW,
        JobState.SUCCEEDED,
        checkpoint='{"schema_rev": "parse-checkpoint-2"}',
    )

    assert store.get_units(build_id) == (unit,)
    assert [row[:2] for row in _attempt_rows(build_id, JobStage.PARSED)] == [
        (1, "failed"),
        (2, "succeeded"),
    ]
    job = store.get_job(build_id, JobStage.PARSED)
    assert job is not None and job.checkpoint is not None
    assert "parse-checkpoint-2" in job.checkpoint


# ---- 11. 配置/索引版本升级 → 新 build 全量重建并接管活动指针 ----


def test_index_rev_upgrade_rebuild_switches_active_and_read_side(store: PgStore) -> None:
    tag, decision_id = "upgrade", "d1"
    source = _sid(tag)
    old_build = sha256_of_bytes(b"i2s5:build:upgrade:v2")
    new_build = sha256_of_bytes(b"i2s5:build:upgrade:v3")
    upgraded_rev = "index-3-zhcfg-3"

    base_kwargs = {
        "source_id": source,
        "decision_id": decision_id,
        "parse_rev": "parse-test",
        "clean_rev": "clean-test",
        "chunk_rev": "chunk-test",
        "scope_ref": None,
    }
    # index_rev 进入 build 身份（§4.1）：分词配置/索引文本规则升级必换 build_id
    assert compute_build_id(**base_kwargs, index_rev=INDEX_REV_V3) != compute_build_id(
        **base_kwargs, index_rev=upgraded_rev
    )

    _seed_build(store, tag, decision_id, old_build)
    _publish_chain(store, tag, decision_id, old_build, "w1", ("石英股份旧索引版 coherent 文本",))
    assert [h.build_id for h in search_chunks(DSN, "石英")] == [old_build]

    store.put_build(replace(_build(tag, decision_id, new_build), index_rev=upgraded_rev))
    generation = _publish_chain(
        store, tag, decision_id, new_build, "w2", ("石英股份新索引版 coherent 文本",)
    )
    assert generation == 2  # 指针翻转：generation 单调 +1
    assert [h.build_id for h in search_chunks(DSN, "石英")] == [new_build]  # 旧版本不再服务检索


# ---- 12. fencing 判据次序（RM-4：与 Memory 侧断言同一错误语义）----


def test_pg_fencing_credential_precedes_state_after_takeover(store: PgStore) -> None:
    """RM-4（PG 侧对称）：接管者已完成后，旧 worker 迟到写入的语义必须是 lease_lost。

    与 ``test_corpus_preparation_contract.py::
    test_memory_fencing_credential_precedes_state_after_takeover`` 断言同一错误
    语义，确保 Memory 与 PG 两个 Adapter 在 Store Seam 上行为一致（架构 §9）。
    """
    build_id = _seed_build(store, "fence", "d1")
    store.register_job(build_id, JobStage.PARSED)
    stale = store.acquire_job(build_id, JobStage.PARSED, "w1", NOW, LEASE)
    _backdate_leases(build_id)  # 记账式过期：w2 合法接管（新租约不过期）
    current = store.acquire_job(build_id, JobStage.PARSED, "w2", NOW, LEASE)
    store.put_units(
        build_id, [_unit(build_id, "u1")], owner_id="w2", fence_token=current.fence_token
    )
    store.finish_job(build_id, JobStage.PARSED, "w2", current.fence_token, NOW, JobState.SUCCEEDED)
    # ① 旧 worker 迟到权威写入（_require_ownership 凭据优先）
    with pytest.raises(StoreError, match="lease_lost"):
        store.put_units(
            build_id,
            [_unit(build_id, "u-ghost", ordinal=2)],
            owner_id="w1",
            fence_token=stale.fence_token,
        )
    # ② 旧 worker 迟到 finish：不得被误认成同一次提交（RM-1）
    with pytest.raises(StoreError, match="lease_lost"):
        store.finish_job(
            build_id, JobStage.PARSED, "w1", stale.fence_token, NOW, JobState.SUCCEEDED
        )
    assert [u.unit_id for u in store.get_units(build_id)] == ["u1"]


# ---- 13. 续租正向路径（RM-5：架构 §8.1.3「续租」此前零覆盖）----


def test_heartbeat_renews_lease_and_expired_renewal_is_refused(store: PgStore) -> None:
    """续租正向路径（RM-5）：heartbeat 成功后 ``lease_until`` 必须前移。

    全仓此前只覆盖 heartbeat 的两条**失败**路径（token 不匹配、已过期）；
    若心跳的 UPDATE 忘了刷新 ``lease_until``，现有测试一条都不会红。这里断言
    续租确实延长租约、不换 token、不消耗 attempt 预算，且续租取数据库时间
    （调用方传入的 ``NOW`` 仅接口兼容）。过期后不得原地续命。

    ``SHORT_LEASE = (ttl=3, heartbeat=1, ...)`` 满足 I0C-2 的 heartbeat ≤ TTL/3。
    """
    build_id = _seed_build(store, "hb", "d1")
    store.register_job(build_id, JobStage.PARSED)
    first = store.acquire_job(build_id, JobStage.PARSED, "w1", NOW, SHORT_LEASE)
    assert first.lease_until is not None and first.heartbeat_at is not None

    time.sleep(1.2)  # 让数据库时钟前进，确保续租后的到期时间严格更晚
    renewed = store.heartbeat_job(
        build_id, JobStage.PARSED, "w1", first.fence_token, NOW, SHORT_LEASE
    )
    assert renewed.state is JobState.RUNNING
    assert renewed.attempt == first.attempt  # 续租不消耗重试预算
    assert renewed.fence_token == first.fence_token  # 续租不换 token（不产生新所有权）
    assert renewed.lease_until is not None
    assert renewed.lease_until > first.lease_until  # 租约被延长
    assert renewed.heartbeat_at is not None
    assert renewed.heartbeat_at > first.heartbeat_at

    # 过期后不得原地续命（§8.1.3）：须重新竞争取得新 token。
    time.sleep(SHORT_LEASE.lease_ttl_seconds + 1.2)
    with pytest.raises(StoreError, match="lease_lost"):
        store.heartbeat_job(build_id, JobStage.PARSED, "w1", first.fence_token, NOW, SHORT_LEASE)


# ---- 14. 连接断开（RM-6：架构 §8.1 明列，区别于「提交响应丢失」的重放）----


def test_disconnect_before_finish_leave_no_half_commit_and_recovers(
    store: PgStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """连接断开（RM-6）：指针切换成功、finish 提交前断连。

    与 ``test_lost_commit_response_replay_is_idempotent``（提交成功但客户端未收到
    响应 → **重放**）的区别：这里连接/进程在两次提交之间真的断掉，验证
    ① 不产生半提交（publish 自身是原子事务，不会只写一半）；② 撕裂态（指针已切、
    job 仍 RUNNING）可被后续调用按 §8.1.6 读取已提交状态并补齐；③ 恢复动作不
    改变已提交的指针与 generation。
    """
    build_id = _seed_build(store, "disconnect", "d1")
    store.register_job(build_id, JobStage.PUBLISHED)
    job = store.acquire_job(build_id, JobStage.PUBLISHED, "w1", NOW, LEASE)
    real_finish = store.finish_job

    def broken_finish(*args: object, **kwargs: object) -> object:
        # finish_job(store, build_id, stage, owner_id, fence_token, now, state)：
        # 正式调用走位置参数，state 落在 args[5]，不能只看 kwargs。
        state = kwargs.get("state")
        if state is None and len(args) > 5:
            state = args[5]
        if state is JobState.SUCCEEDED:
            raise ConnectionError("模拟断连：指针已切换，finish 尚未提交")
        return real_finish(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(store, "finish_job", broken_finish)
    with pytest.raises(ConnectionError):
        store.publish(
            _sid("disconnect"), "d1", build_id, NOW, owner_id="w1", fence_token=job.fence_token
        )
        store.finish_job(
            build_id, JobStage.PUBLISHED, "w1", job.fence_token, NOW, JobState.SUCCEEDED
        )

    # ① 无半提交：指针要么整体提交、要么整体未提交——此处已整体提交且只有一行
    rows = _publication_rows()
    assert len(rows) == 1
    assert rows[0][2] == build_id
    assert rows[0][3] == 1  # generation 已提交一次
    # ② 撕裂态：job 仍 RUNNING，等待补齐（RM-2 的恢复窗口）
    assert store.get_job(build_id, JobStage.PUBLISHED).state is JobState.RUNNING

    # ③ 重连后按 §8.1.6 读取已提交检查点并补齐：同租约提交，指针/generation 不漂移
    monkeypatch.undo()
    recovered = store.finish_job(
        build_id, JobStage.PUBLISHED, "w1", job.fence_token, NOW, JobState.SUCCEEDED
    )
    assert recovered.state is JobState.SUCCEEDED
    assert _publication_rows() == rows  # 指针与 generation 未被恢复动作改变


# ---- 15. 引擎入口恢复（RM-8：走 VERIFIED 门，而非 _publish_chain 直操作 Store）----


def _verified_content_stages(store: PgStore, build_id: str, owner: str) -> None:
    """走通 PARSED / CHUNKED 两阶段并落 SUCCEEDED（VERIFIED 发布门的前置）。"""
    for stage in (JobStage.PARSED, JobStage.CHUNKED):
        store.register_job(build_id, stage)
        job = store.acquire_job(build_id, stage, owner, NOW, LEASE)
        if stage is JobStage.PARSED:
            store.put_units(
                build_id, [_unit(build_id, "u1")], owner_id=owner, fence_token=job.fence_token
            )
        else:
            store.put_chunks(
                build_id,
                [_chunk(build_id, "c0", "石英股份高纯砂良率提升")],
                owner_id=owner,
                fence_token=job.fence_token,
            )
        store.finish_job(build_id, stage, owner, job.fence_token, NOW, JobState.SUCCEEDED)


def test_engine_publish_reconciles_unfinished_job_after_disconnect(
    store: PgStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """引擎入口（RM-2 真 PG 版 + RM-8）：走 ``publish_build`` 与 VERIFIED 门。

    底层并发用例用 ``_publish_chain`` 直操作 Store、手工构造 chunk，绕过了
    ``_verify_publication_ready`` 的阶段/质量/scope 门。这里改用正式引擎入口：
    先走通 PARSED/CHUNKED 两阶段（使 VERIFIED 门可通过），再在 publish→finish
    之间注入断连，验证重试经 :func:`~...engine._reconcile_published_job` 补齐
    终态，且活动指针、generation 均不漂移。
    """
    build_id = _seed_build(store, "engine-dc", "d1")
    _verified_content_stages(store, build_id, "w1")

    real_finish = store.finish_job
    calls = {"broken": False}

    def broken_once(*args: object, **kwargs: object) -> object:
        # 同上：engine 以位置参数调用 finish_job，state 落在 args[5]。
        state = kwargs.get("state")
        if state is None and len(args) > 5:
            state = args[5]
        if state is JobState.SUCCEEDED and not calls["broken"]:
            calls["broken"] = True  # 只断第一次：publish 已提交、终态未提交
            raise ConnectionError("模拟断连：指针已切换，PUBLISHED 终态未提交")
        return real_finish(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(store, "finish_job", broken_once)
    with pytest.raises(ConnectionError):
        publish_build(store, build_id, activated_at=NOW, owner_id="w1", lease=LEASE)

    # 撕裂态：指针已切（publish 提交成功），PUBLISHED job 仍 RUNNING
    rows_before = _publication_rows()
    assert len(rows_before) == 1 and rows_before[0][2] == build_id
    assert store.get_job(build_id, JobStage.PUBLISHED).state is JobState.RUNNING

    # 重试：引擎短路前补齐终态（RM-2），且准入仍有效（RM-3）
    monkeypatch.undo()
    result = publish_build(store, build_id, activated_at=NOW, owner_id="w1", lease=LEASE)
    assert store.get_job(build_id, JobStage.PUBLISHED).state is JobState.SUCCEEDED
    assert result.active_build_id == build_id
    assert _publication_rows() == rows_before  # generation 不重复递增
