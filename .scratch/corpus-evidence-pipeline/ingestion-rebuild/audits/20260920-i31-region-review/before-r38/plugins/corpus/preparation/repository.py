"""I1-1 内存存储 Adapter（与 PG repository 共享同一存储 Seam）。

架构 v1.1 §9：PostgreSQL 与内存测试 Adapter 跨相同存储 Seam；内存实现保留与
契约 §8/§8.1 相同的次序、幂等与租约语义（``memory_chain_note`` 要求），真实 PG
条件写入（事务/FTS/双 worker 竞争）在 I2 实测，不以内存锁代替。

本模块只做存储与所有权/幂等判定，不含业务规则（准入判定在 I1-5，编排在 I1-7），
纯标准库，无模型调用、无网络/PG。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TypeVar

from plugins.corpus.preparation.contract import (
    Admission,
    AdmissionDecision,
    Build,
    Chunk,
    Job,
    JobStage,
    JobState,
    LeaseConfig,
    Publication,
    ReviewedDecision,
    Source,
    Unit,
    canonical_fingerprint,
)
from plugins.corpus.preparation.gap_review import REVIEW_STAGE_PREFIX, GapReview, apply_gap_review


class StoreError(RuntimeError):
    """存储所有权/幂等/一致性冲突（含 lease_lost）。"""


_TERMINAL_STATES: frozenset[JobState] = frozenset(
    {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}
)

_T = TypeVar("_T")


class Store(ABC):
    """语料入库存储 Seam：I1 内存与 I2 PG 实现共用同一接口。"""

    @abstractmethod
    def put_source(self, source: Source) -> None:
        """幂等登记来源；同源不同内容为冲突。"""

    @abstractmethod
    def get_source(self, source_id: str) -> Source | None: ...

    @abstractmethod
    def put_reviewed_decision(self, decision: ReviewedDecision) -> None:
        """追加式登记人工审核；decision_id 唯一。"""

    @abstractmethod
    def get_reviewed_decision(self, decision_id: str) -> ReviewedDecision | None: ...

    @abstractmethod
    def put_admission(self, admission: Admission) -> None:
        """追加式登记准入；decision_id 唯一。"""

    @abstractmethod
    def get_admission(self, decision_id: str) -> Admission | None: ...

    @abstractmethod
    def latest_admission(self, source_id: str) -> Admission | None: ...

    @abstractmethod
    def put_build(self, build: Build) -> None:
        """幂等登记构建；build_id 唯一。"""

    @abstractmethod
    def get_build(self, build_id: str) -> Build | None: ...

    def get_gap_review(self, build_id: str) -> GapReview | None:
        """Read a credential from the reserved, immutable checkpoint namespace."""
        build = self.get_build(build_id)
        if build is None:
            return None
        payload = self.get_source_checkpoint(build.source_id, REVIEW_STAGE_PREFIX + build_id)
        return GapReview.from_json(payload) if payload is not None else None

    def put_gap_review(self, review: GapReview) -> None:
        """Validate before append; identical replay is allowed, replacement is not."""
        from plugins.corpus.preparation.engine import gap_records_of

        build = self.get_build(review.build_id)
        if build is None:
            raise StoreError("gap review build does not exist")
        apply_gap_review(review, build, self.get_units(build.build_id), gap_records_of(build))
        self._put_gap_review(build, review.to_json())

    @abstractmethod
    def _put_gap_review(self, build: Build, payload: str) -> None:
        """Atomically append a credential; ordinary checkpoint writes cannot replace it."""

    @abstractmethod
    def put_units(
        self,
        build_id: str,
        units: Iterable[Unit],
        *,
        owner_id: str | None = None,
        fence_token: str | None = None,
    ) -> None:
        """幂等写入候选单元；同一 ``(build_id, unit_id)`` 同内容为空操作。

        已登记 ``PARSED`` 阶段 job 的 build 必须由当前租约持有者携带
        ``owner_id``/``fence_token`` 写入（fencing：过期/被接管的 worker 不得直写权威输出）。
        """

    @abstractmethod
    def get_unit(self, build_id: str, unit_id: str) -> Unit | None: ...

    @abstractmethod
    def put_chunks(
        self,
        build_id: str,
        chunks: Iterable[Chunk],
        *,
        owner_id: str | None = None,
        fence_token: str | None = None,
    ) -> None:
        """幂等写入检索投影；chunk_id 唯一。

        所有权门与 :meth:`put_units` 相同，对应 ``CHUNKED`` 阶段 job。
        """

    @abstractmethod
    def get_chunk(self, chunk_id: str) -> Chunk | None: ...

    @abstractmethod
    def get_units(self, build_id: str) -> tuple[Unit, ...]:
        """按 build 读取全部已写单元（发布校验/审计用；无写入返回空）。"""

    @abstractmethod
    def get_chunks(self, build_id: str) -> tuple[Chunk, ...]:
        """按 build 读取全部检索投影（发布校验/审计用；无写入返回空）。"""

    @abstractmethod
    def put_source_checkpoint(self, source_id: str, stage: str, checkpoint: str) -> None:
        """按来源登记阶段检查点（架构 §8 第 4 条：可验证检查点先于重算）。

        build 级 job 以 ``(build_id, stage)`` 为键，而解析计算先于准入/建 build
        发生（内容级探查来自真实解析），故解析检查点按 **来源** 键控：值持有
        输入/产物哈希与可复用产物，由引擎校验后决定复用或重算（C6）。
        同 ``(source_id, stage)`` 重复写入以最后一次为准（检查点可被无效化重算覆盖）。
        """

    @abstractmethod
    def get_source_checkpoint(self, source_id: str, stage: str) -> str | None: ...

    @abstractmethod
    def get_publication(self, source_id: str) -> Publication | None: ...

    @abstractmethod
    def publish(
        self,
        source_id: str,
        decision_id: str,
        build_id: str,
        activated_at: datetime,
        *,
        owner_id: str | None = None,
        fence_token: str | None = None,
    ) -> Publication:
        """核对准入、构建身份与发布所有权后切换活动指针，generation 递增。

        相同目标状态（``current_decision_id=decision_id`` 且
        ``active_build_id=build_id``）的重复调用是提交重试：幂等返回已提交结果，
        不递增 generation、不刷新 ``activated_at``（publish_idempotency_v2，
        I0-C 裁决：幂等按目标状态比对，不以时间为键——响应丢失+时钟前进的
        重试不得被误判为新激活）。已登记 ``PUBLISHED`` 阶段 job 的 build 必须
        由当前租约持有者发布（复核 R2）。``activated_at`` 仅在指针翻转时生效
        （PG 实现取数据库时间）。
        """

    @abstractmethod
    def retire(self, source_id: str, decision_id: str, activated_at: datetime) -> Publication:
        """落实排除/撤销：active_build_id 置空（旧 build 仅供审计）。"""

    @abstractmethod
    def register_job(self, build_id: str, stage: JobStage) -> Job:
        """幂等创建 queued job；``(build_id, stage)`` 唯一。"""

    @abstractmethod
    def get_job(self, build_id: str, stage: JobStage) -> Job | None:
        """读取阶段 job 当前状态（发布门校验阶段完成度/审计用；未登记返回 None）。"""

    @abstractmethod
    def acquire_job(
        self,
        build_id: str,
        stage: JobStage,
        owner_id: str,
        now: datetime,
        lease_config: LeaseConfig,
    ) -> Job:
        """原子取得所有权；重试/接管递增 attempt 与 fence_token。"""

    @abstractmethod
    def heartbeat_job(
        self,
        build_id: str,
        stage: JobStage,
        owner_id: str,
        fence_token: str,
        now: datetime,
        lease_config: LeaseConfig,
    ) -> Job:
        """续租（owner/token 匹配、running 且未过期）。"""

    @abstractmethod
    def finish_job(
        self,
        build_id: str,
        stage: JobStage,
        owner_id: str,
        fence_token: str,
        now: datetime,
        state: JobState,
        error: str | None = None,
        checkpoint: str | None = None,
    ) -> Job:
        """围栏校验下提交终态（succeeded/failed/cancelled）。"""


class MemoryStore(Store):
    """单进程内存存储；比较与幂等判定基于不可变记录的值相等。

    ``clock`` 为可注入时钟（复核 R2：I1 测试注入固定时钟，默认真实 UTC 墙钟），
    用于权威写入/发布时判定租约是否过期；I2 PG 实现改用数据库时钟。
    """

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(UTC))
        self._sources: dict[str, Source] = {}
        self._reviewed: dict[str, ReviewedDecision] = {}
        self._admissions: dict[str, Admission] = {}
        self._latest_admission: dict[str, str] = {}
        self._builds: dict[str, Build] = {}
        self._units: dict[tuple[str, str], Unit] = {}
        self._chunks: dict[str, Chunk] = {}
        self._publications: dict[str, Publication] = {}
        self._jobs: dict[tuple[str, str], Job] = {}
        self._source_checkpoints: dict[tuple[str, str], str] = {}

    @staticmethod
    def _put_idempotent(table: dict[str, _T], key: str, record: _T, label: str) -> None:
        existing = table.get(key)
        if existing is None:
            table[key] = record
            return
        if existing != record:
            raise StoreError(f"{label} 冲突：{key} 已存在且内容不同，拒绝覆盖")
        # 同内容重复写入：幂等空操作。

    def put_source(self, source: Source) -> None:
        self._put_idempotent(self._sources, source.source_id, source, "source")

    def get_source(self, source_id: str) -> Source | None:
        return self._sources.get(source_id)

    def put_reviewed_decision(self, decision: ReviewedDecision) -> None:
        self._put_idempotent(self._reviewed, decision.decision_id, decision, "reviewed_decision")

    def get_reviewed_decision(self, decision_id: str) -> ReviewedDecision | None:
        return self._reviewed.get(decision_id)

    def put_admission(self, admission: Admission) -> None:
        existing = self._admissions.get(admission.decision_id)
        if existing is not None:
            if existing != admission:
                raise StoreError(
                    f"admission 冲突：{admission.decision_id} 已存在且内容不同，拒绝覆盖"
                )
            # 同内容幂等重放：历史追加不可变，不得回退当前决定指针。
            return
        self._admissions[admission.decision_id] = admission
        self._latest_admission[admission.source_id] = admission.decision_id

    def get_admission(self, decision_id: str) -> Admission | None:
        return self._admissions.get(decision_id)

    def latest_admission(self, source_id: str) -> Admission | None:
        decision_id = self._latest_admission.get(source_id)
        if decision_id is None:
            return None
        return self._admissions[decision_id]

    def put_build(self, build: Build) -> None:
        self._put_idempotent(self._builds, build.build_id, build, "build")

    def get_build(self, build_id: str) -> Build | None:
        return self._builds.get(build_id)

    def put_units(
        self,
        build_id: str,
        units: Iterable[Unit],
        *,
        owner_id: str | None = None,
        fence_token: str | None = None,
    ) -> None:
        self._require_stage_ownership(build_id, JobStage.PARSED, owner_id, fence_token)
        for unit in units:
            if unit.build_id != build_id:
                raise StoreError(f"unit.build_id 与目标 build_id 不一致: {unit.unit_id}")
            key = (build_id, unit.unit_id)
            existing = self._units.get(key)
            if existing is not None and existing != unit:
                raise StoreError(f"unit 冲突：{unit.unit_id} 已存在且内容不同")
            self._units[key] = unit

    def get_unit(self, build_id: str, unit_id: str) -> Unit | None:
        return self._units.get((build_id, unit_id))

    def put_chunks(
        self,
        build_id: str,
        chunks: Iterable[Chunk],
        *,
        owner_id: str | None = None,
        fence_token: str | None = None,
    ) -> None:
        self._require_stage_ownership(build_id, JobStage.CHUNKED, owner_id, fence_token)
        for chunk in chunks:
            if chunk.build_id != build_id:
                raise StoreError(f"chunk.build_id 与目标 build_id 不一致: {chunk.chunk_id}")
            self._put_idempotent(self._chunks, chunk.chunk_id, chunk, "chunk")

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        return self._chunks.get(chunk_id)

    def get_units(self, build_id: str) -> tuple[Unit, ...]:
        return tuple(unit for (bid, _uid), unit in self._units.items() if bid == build_id)

    def get_chunks(self, build_id: str) -> tuple[Chunk, ...]:
        return tuple(chunk for chunk in self._chunks.values() if chunk.build_id == build_id)

    def put_source_checkpoint(self, source_id: str, stage: str, checkpoint: str) -> None:
        if len(source_id) != 64 or any(c not in "0123456789abcdef" for c in source_id):
            raise StoreError(f"source_checkpoint.source_id 非法: {source_id!r}")
        if not stage:
            raise StoreError("source_checkpoint.stage 不能为空")
        if stage.startswith(REVIEW_STAGE_PREFIX):
            raise StoreError("human gap review namespace requires put_gap_review")
        self._source_checkpoints[(source_id, stage)] = checkpoint

    def _put_gap_review(self, build: Build, payload: str) -> None:
        key = (build.source_id, REVIEW_STAGE_PREFIX + build.build_id)
        existing = self._source_checkpoints.setdefault(key, payload)
        if existing != payload:
            raise StoreError("human gap review conflict: immutable credential cannot be replaced")

    def get_source_checkpoint(self, source_id: str, stage: str) -> str | None:
        return self._source_checkpoints.get((source_id, stage))

    def get_publication(self, source_id: str) -> Publication | None:
        return self._publications.get(source_id)

    def publish(
        self,
        source_id: str,
        decision_id: str,
        build_id: str,
        activated_at: datetime,
        *,
        owner_id: str | None = None,
        fence_token: str | None = None,
    ) -> Publication:
        self._require_publication_ownership(build_id, owner_id, fence_token)
        build = self._builds.get(build_id)
        if build is None or build.source_id != source_id:
            raise StoreError(f"publish：build {build_id} 不存在或不属于 source {source_id}")
        if build.decision_id != decision_id:
            # 复核 R1：发布必须核对 build 绑定的批准版本；scope 相同不能替代
            # build 身份核验（旧构建不得在新决定下复用发布）。
            raise StoreError(
                f"publish：build {build_id} 绑定决定 {build.decision_id}，"
                f"与请求决定 {decision_id} 不一致，不得复用旧构建发布新决定"
            )
        admission = self._admissions.get(decision_id)
        if admission is None or admission.source_id != source_id:
            raise StoreError(f"publish：admission {decision_id} 不存在或不属于 source {source_id}")
        latest = self.latest_admission(source_id)
        if latest is None or latest.decision_id != decision_id:
            raise StoreError(
                f"publish：admission {decision_id} 不是 source {source_id} 的当前决定"
                f"（当前为 {latest.decision_id if latest else None}），不得切活动指针"
            )
        if admission.scope_ref is not None and build.scope_ref != admission.scope_ref:
            raise StoreError(
                f"publish：build scope {build.scope_ref!r} 超出准入 scope {admission.scope_ref!r}"
                "（部分章节批准不得升级为整篇构建发布）"
            )
        if admission.decision is not AdmissionDecision.IN_SCOPE:
            raise StoreError(f"publish：admission {decision_id} 非 in_scope，不得切活动指针")
        return self._set_publication(source_id, decision_id, build_id, activated_at)

    def retire(self, source_id: str, decision_id: str, activated_at: datetime) -> Publication:
        admission = self._admissions.get(decision_id)
        if admission is None or admission.source_id != source_id:
            raise StoreError(f"retire：admission {decision_id} 不存在或不属于 source {source_id}")
        latest = self.latest_admission(source_id)
        if latest is None or latest.decision_id != decision_id:
            raise StoreError(
                f"retire：admission {decision_id} 不是 source {source_id} 的当前决定"
                f"（当前为 {latest.decision_id if latest else None}），不得撤销"
            )
        return self._set_publication(source_id, decision_id, None, activated_at)

    def _set_publication(
        self, source_id: str, decision_id: str, active_build_id: str | None, activated_at: datetime
    ) -> Publication:
        previous = self._publications.get(source_id)
        if (
            previous is not None
            and previous.current_decision_id == decision_id
            and previous.active_build_id == active_build_id
        ):
            # publish_idempotency_v2（I0-C 裁决，G2 闭合）：幂等按目标状态比对，
            # 不以时间为键——提交成功但响应丢失的重试（无论是否重新 acquire、
            # 时钟是否前进）恒返回已提交结果，不递增 generation、不刷新
            # activated_at。generation 语义 = 活动指针变更次数。
            return previous
        generation = 1 if previous is None else previous.generation + 1
        publication = Publication(
            source_id=source_id,
            current_decision_id=decision_id,
            active_build_id=active_build_id,
            generation=generation,
            activated_at=activated_at,
        )
        self._publications[source_id] = publication
        return publication

    def register_job(self, build_id: str, stage: JobStage) -> Job:
        key = (build_id, stage)
        existing = self._jobs.get(key)
        if existing is not None:
            return existing
        job = Job(
            job_id=f"{build_id}:{stage.value}",
            build_id=build_id,
            stage=stage,
            attempt=1,
            state=JobState.QUEUED,
        )
        self._jobs[key] = job
        return job

    def get_job(self, build_id: str, stage: JobStage) -> Job | None:
        return self._jobs.get((build_id, stage))

    def acquire_job(
        self,
        build_id: str,
        stage: JobStage,
        owner_id: str,
        now: datetime,
        lease_config: LeaseConfig,
    ) -> Job:
        job = self._require_job(build_id, stage)
        if job.state is JobState.SUCCEEDED:
            if stage is JobStage.PUBLISHED:
                # 发布是可重复的动作（同一 build 新 activated_at = 新激活，
                # Publication.generation 递增）：终态 PUBLISHED job 允许取得
                # 新租约重新激活；内容阶段（PARSED/CHUNKED）保持 §8.1 幂等短路。
                pass
            else:
                # 同 build 已成功的阶段返回原检查点（契约 §8.1 幂等）。
                return job
        if job.state is JobState.CANCELLED and stage is not JobStage.PUBLISHED:
            raise StoreError("cancelled job 不自动复活")
        if job.state is JobState.CANCELLED and job.attempt >= lease_config.max_attempts:
            raise StoreError("job 已达 max_attempts，不可重试")
        if job.state is JobState.RUNNING and not self._expired(job, now):
            raise StoreError(f"job 仍由 {job.owner_id} 持有且租约未过期，不得抢占")
        if job.state is JobState.RUNNING and job.attempt >= lease_config.max_attempts:
            # 过期 RUNNING 接管同样消耗重试预算（F2：不得绕过 max_attempts）。
            raise StoreError("job 已达 max_attempts，不可接管过期租约")
        if job.state is JobState.FAILED and job.attempt >= lease_config.max_attempts:
            raise StoreError("job 已达 max_attempts，不可重试")
        if (
            stage is JobStage.PUBLISHED
            and job.state is JobState.SUCCEEDED
            and job.attempt >= lease_config.max_attempts
        ):
            # PUBLISHED 终态可重新取得租约，但仍受重试预算约束（§8.1.2 不无限续租）。
            raise StoreError("job 已达 max_attempts，不可重新激活发布租约")

        attempt = job.attempt
        if job.state in (JobState.RUNNING, JobState.FAILED, JobState.CANCELLED):
            attempt += 1
        elif job.state is JobState.SUCCEEDED:
            attempt += 1  # PUBLISHED 重新激活消耗一次重试预算
        fence_token = canonical_fingerprint(
            (build_id, stage.value, attempt, owner_id, now.isoformat())
        )
        acquired = replace(
            job,
            attempt=attempt,
            state=JobState.RUNNING,
            owner_id=owner_id,
            fence_token=fence_token,
            lease_until=now + timedelta(seconds=lease_config.lease_ttl_seconds),
            heartbeat_at=now,
            error=None,
        )
        self._jobs[(build_id, stage)] = acquired
        return acquired

    def heartbeat_job(
        self,
        build_id: str,
        stage: JobStage,
        owner_id: str,
        fence_token: str,
        now: datetime,
        lease_config: LeaseConfig,
    ) -> Job:
        job = self._require_job(build_id, stage)
        self._fence(job, owner_id, fence_token, now)
        renewed = replace(
            job,
            heartbeat_at=now,
            lease_until=now + timedelta(seconds=lease_config.lease_ttl_seconds),
        )
        self._jobs[(build_id, stage)] = renewed
        return renewed

    def finish_job(
        self,
        build_id: str,
        stage: JobStage,
        owner_id: str,
        fence_token: str,
        now: datetime,
        state: JobState,
        error: str | None = None,
        checkpoint: str | None = None,
    ) -> Job:
        if state not in _TERMINAL_STATES:
            raise StoreError(f"finish_job 只能是终态，收到 {state.value}")
        job = self._require_job(build_id, stage)
        if job.state in _TERMINAL_STATES:
            # RM-1：与 PgStore 同语义——终态重放先锚定所有权（fence_token 唯一绑定
            # attempt）。接管者完成后，旧 worker 的迟到 finish 必须得到 lease_lost，
            # 不得因「终态相同」被误判为同一次提交。
            if owner_id is None or fence_token is None:
                raise StoreError(
                    f"权威写入拒绝：job ({build_id}, {stage.value}) 已终态，"
                    "finish 必须携带 owner_id/fence_token"
                )
            if job.owner_id != owner_id or job.fence_token != fence_token:
                raise StoreError(
                    "权威写入拒绝：owner/token 与当前租约不匹配（lease_lost）——"
                    f"该 job 已由 {job.owner_id!r} 在 attempt {job.attempt} 完成"
                )
            if job.state is state:
                # 提交已成功但客户端未收到响应：重试读取已提交检查点，不重复增行。
                return job
            raise StoreError(f"job 已处于终态 {job.state.value}，不得改为 {state.value}")
        self._fence(job, owner_id, fence_token, now)
        finished = replace(job, state=state, error=error, checkpoint=checkpoint, lease_until=None)
        self._jobs[(build_id, stage)] = finished
        return finished

    def _require_job(self, build_id: str, stage: JobStage) -> Job:
        job = self._jobs.get((build_id, stage))
        if job is None:
            raise StoreError(f"job 未登记: ({build_id}, {stage.value})")
        return job

    def _require_stage_ownership(
        self, build_id: str, stage: JobStage, owner_id: str | None, fence_token: str | None
    ) -> None:
        """权威输出写入的所有权门（F2 + 复核 R2 完整协议，fail-closed）。

        运行中、未过期、当前 owner/token 必须同时成立；未登记 job 一律拒绝
        （测试夹具走相同协议，不留业务旁路）。过期租约须先由 acquire_job
        接管（attempt+1）取得新租约后才可写入。
        """
        job = self._jobs.get((build_id, stage))
        if job is None:
            raise StoreError(
                f"权威写入拒绝：job ({build_id}, {stage.value}) 未登记"
                "（fail-closed：须先 register_job/acquire_job 取得租约）"
            )
        if owner_id is None or fence_token is None:
            raise StoreError(
                f"权威写入拒绝：job ({build_id}, {stage.value}) 已登记，"
                "写入必须携带当前租约的 owner_id/fence_token"
            )
        # RM-4：判定次序与 PgStore._require_ownership 一致——凭据优先，再判状态。
        if job.owner_id != owner_id or job.fence_token != fence_token:
            raise StoreError("权威写入拒绝：owner/token 与当前租约不匹配（lease_lost）")
        if job.state is not JobState.RUNNING:
            raise StoreError(
                f"权威写入拒绝：job ({build_id}, {stage.value}) 处于 {job.state.value} 态，无当前所有权"
            )
        if job.lease_until is not None and self._clock() >= job.lease_until:
            # RM-4：与 PgStore._require_ownership 及本类 _fence 同语义——
            # 租约过期同属 lease_lost（§8.1.4），错误消息须可同等匹配。
            raise StoreError(
                "权威写入拒绝：租约已过期（lease_lost，fencing），须先接管取得新 token 再写入"
            )

    def _require_publication_ownership(
        self, build_id: str, owner_id: str | None, fence_token: str | None
    ) -> None:
        """发布所有权门（复核 R2 + full-review C1，fail-closed）。

        发布必须经引擎登记 PUBLISHED job 并持有当前租约：运行中、未过期、
        owner/token 匹配缺一不可；未登记 PUBLISHED job 一律拒绝（无直发旁路，
        测试夹具走相同协议）。过期租约须先由 acquire_job 重新取得新 token。
        """
        job = self._jobs.get((build_id, JobStage.PUBLISHED))
        if job is None:
            raise StoreError(
                f"publish 拒绝：PUBLISHED job ({build_id}) 未登记"
                "（fail-closed：发布必须经引擎 register_job/acquire_job 取得租约，"
                "无 job/no-check 旁路）"
            )
        if owner_id is None or fence_token is None:
            raise StoreError(
                f"publish 拒绝：PUBLISHED job ({build_id}) 已登记，"
                "发布必须携带当前租约的 owner_id/fence_token"
            )
        # RM-4：判定次序与 PgStore._require_ownership 一致——凭据优先，再判状态。
        if job.owner_id != owner_id or job.fence_token != fence_token:
            raise StoreError("publish 拒绝：owner/token 与当前 PUBLISHED 租约不匹配（lease_lost）")
        if job.state is not JobState.RUNNING:
            raise StoreError(
                f"publish 拒绝：PUBLISHED job ({build_id}) 处于 {job.state.value} 态，无当前所有权"
            )
        if job.lease_until is not None and self._clock() >= job.lease_until:
            # RM-4：同上，与 PG 侧保持同一错误语义。
            raise StoreError("publish 拒绝：PUBLISHED 租约已过期（lease_lost，fencing）")

    @staticmethod
    def _expired(job: Job, now: datetime) -> bool:
        return job.lease_until is not None and now >= job.lease_until

    def _fence(self, job: Job, owner_id: str, fence_token: str, now: datetime) -> None:
        # RM-4：与 PgStore._require_ownership 同次序——凭据优先，再判状态与过期。
        if job.owner_id != owner_id or job.fence_token != fence_token:
            raise StoreError("lease_lost：owner/token 不匹配")
        if job.state is not JobState.RUNNING:
            raise StoreError("lease_lost：job 非 running 态")
        if self._expired(job, now):
            raise StoreError("lease_lost：租约已过期（更新零行）")
