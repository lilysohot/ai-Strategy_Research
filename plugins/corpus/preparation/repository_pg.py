"""I2-2 PG 存储 Adapter（与 MemoryStore 共享同一 Store Seam；i0c-r1 冻结布局）。

架构 v1.1 §9 + 契约 §8/§8.1：真实 PG 条件写入（事务/租约/接管）在 I2 实测，
不以内存锁代替。本模块实现 Store 抽象的全部方法，目标为隔离库
``i2_sandbox_corpus``（corpus schema 九表，i0c-r1 冻结 DDL）。

冻结协议要点（design-review.json，签认版 sha=3c346c61…）：
- **job 每 attempt 一行**：PK (build_id, stage, attempt)，当前状态 = max(attempt) 行；
  partial UNIQUE (build_id, stage) WHERE running 保证单活租约；attempt 历史按行追加（G1）。
- **fencing**：权威写入/检查点/完成提交在同一事务先 ``SELECT … FOR UPDATE`` 锁当前
  attempt 行，校验 running/未过期/owner/token，不符即 lease_lost 停写；接管与写入经行锁串行化。
- **数据库时间**：租约与 ``activated_at`` 一律取 ``SELECT now()``（§8.1.2），
  调用方传入的 ``now`` 仅作接口兼容被忽略。
- **发布幂等 v2**：按目标状态 (current_decision_id, active_build_id) 比对；
  指针翻转时 generation+1、activated_at=事务时间。
- **latest_admission** = corpus_sources.current_decision_id 显式指针，
  put_admission 新插入时同事务更新；同内容重放不回退指针（F1/F2 语义）。

- **逻辑 job 互斥（J1）**：每个修改 job 行的短事务先取
  ``pg_advisory_xact_lock``（键 = build_id + stage），使「读状态→判归属→换 attempt」
  成为临界区；行锁只锁已存在的行，无法阻止并发 INSERT 新 attempt 行，故并发登记/接管
  必须由 advisory 锁串行化，不得把数据库 IntegrityError 泄漏给调用方。
- **发布互斥（J2）**：publish/retire 先取 source_id 键的 advisory 锁，再
  ``SELECT … FOR UPDATE`` 读 publication 行；否则行不存在时两个并发发布者都会按
  「无行」算 generation，后提交者用陈旧值覆盖，丢掉一次 generation 递增。
- **fencing 判定次序**：陈旧租约凭据优先判 ``lease_lost``（owner/token 不匹配），
  再判状态/过期——接管后旧 worker 的迟到写入必须得到 lease_lost，而不是状态提示。

目标 fail-closed：连接后校验 current_database 与 apodex 反证（生产实例拒绝）。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # psycopg 是可选依赖（PG 演练链路专属）：类型仅用于标注（本模块有
    # ``from __future__ import annotations``）；实际连接与 Jsonb 序列化在
    # 函数内惰性 import，普通 sqlite 环境零 psycopg。
    import psycopg

from plugins.corpus.preparation.contract import (
    Admission,
    AdmissionDecision,
    Build,
    CharSpan,
    Chunk,
    DocumentFormat,
    Job,
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
    UnitLocation,
    UnitStatus,
    canonical_fingerprint,
)
from plugins.corpus.preparation.gap_review import REVIEW_STAGE_PREFIX
from plugins.corpus.preparation.repository import Store, StoreError

_TERMINAL_STATES: frozenset[JobState] = frozenset(
    {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}
)

_JOB_ROW_COLS = (
    "SELECT attempt, state, owner_id, fence_token, lease_until, heartbeat_at, error, checkpoint "
    "FROM corpus.corpus_jobs WHERE build_id = %s AND stage = %s"
)

# advisory 锁命名空间（int4，见 utils.py _advisory_lock）：job 与 publication 两类资源互斥。
_ADVISORY_JOB_NS = 0x6A6F  # 'jo'
_ADVISORY_PUB_NS = 0x7075  # 'pu'


def _advisory_lock(cur: psycopg.Cursor, namespace: int, key: str) -> None:
    """事务级互斥锁（J1/J2）：行锁无法保护『尚不存在的行』与并发 INSERT。"""
    cur.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", (namespace, key))


def _snapshot_to_dict(admission: Admission) -> dict:
    rp = admission.metadata_snapshot.report_publication
    if rp is None:
        return {}
    return {
        "report_publication": {
            "value": rp.value,
            "precision": rp.precision.value,
            "status": rp.status.value,
            "evidence_refs": list(rp.evidence_refs),
            "origin": rp.origin.value if rp.origin else None,
            "review_ref": rp.review_ref,
        }
    }


def _snapshot_from_dict(data: dict) -> MetadataSnapshot:
    rp = data.get("report_publication")
    if rp is None:
        return MetadataSnapshot()
    return MetadataSnapshot(
        report_publication=ReportPublication(
            value=rp.get("value"),
            precision=PublicationDatePrecision(rp["precision"]),
            status=PublicationDateStatus(rp["status"]),
            evidence_refs=tuple(rp.get("evidence_refs", ())),
            origin=PublicationDateOrigin(rp["origin"]) if rp.get("origin") else None,
            review_ref=rp.get("review_ref"),
        )
    )


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_text_from_db(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return _json_text(json.loads(value))
    return _json_text(value)


def _normalized_json_text(text: str | None) -> str | None:
    if text is None:
        return None
    return _json_text(json.loads(text))


def _normalized_build(build: Build) -> Build:
    return replace(build, quality_report=_normalized_json_text(build.quality_report))


def _admission_from_row(decision_id: str, row: tuple) -> Admission:
    return Admission(
        decision_id=decision_id,
        source_id=row[0],
        material_type=MaterialType(row[1]) if row[1] else MaterialType.UNKNOWN,
        research_domain=ResearchDomain(row[2]) if row[2] else None,
        decision=AdmissionDecision(row[3]),
        policy_rev=row[4],
        reason_codes=tuple(row[5]),
        scope_ref=row[6],
        evidence_refs=tuple(row[7]),
        review_ref=row[8],
        rule_rev=row[9],
        metadata_snapshot=_snapshot_from_dict(row[10]),
    )


def _build_from_row(build_id: str, row: tuple) -> Build:
    return Build(
        build_id=build_id,
        source_id=row[0],
        decision_id=row[1],
        parse_rev=row[2],
        clean_rev=row[3],
        chunk_rev=row[4],
        index_rev=row[5],
        scope_ref=row[6],
        config_fingerprint=row[7],
        artifact_manifest=tuple(row[8]),
        quality_report=_json_text_from_db(row[9]),
    )


def _location_to_dict(unit: Unit) -> dict:
    loc = unit.location
    return {
        "page": loc.page,
        "element": loc.element,
        "char_span": [loc.char_span.start, loc.char_span.end] if loc.char_span else None,
        "bbox": list(loc.bbox) if loc.bbox else None,
        "cells": [list(cell) for cell in loc.cells],
        "label_path": list(loc.label_path),
    }


def _location_from_dict(data: dict) -> UnitLocation:
    span = data.get("char_span")
    bbox = data.get("bbox")
    cells = data.get("cells", [])
    return UnitLocation(
        page=data.get("page"),
        element=data.get("element"),
        char_span=CharSpan(span[0], span[1]) if span else None,
        bbox=tuple(bbox) if bbox else None,
        cells=tuple(tuple(c) for c in cells),
        label_path=tuple(data.get("label_path", ())),
    )


def _unit_from_row(build_id: str, unit_id: str, row: tuple) -> Unit:
    return Unit(
        unit_id=unit_id,
        build_id=build_id,
        parent_id=row[0],
        ordinal=row[1],
        kind=row[2],
        raw_text=row[3],
        content_hash=row[4],
        location=_location_from_dict(row[5]),
        clean_view=row[6],
        mapping=tuple(tuple(span) for span in row[7]),
        status=UnitStatus(row[8]),
        reasons=tuple(row[9]),
    )


def _chunk_from_row(build_id: str, chunk_id: str, row: tuple) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        build_id=build_id,
        kind=row[0],
        unit_refs=tuple(row[1]),
        context_refs=tuple(row[2]),
        search_text=row[3],
        title_text=row[4],
        section_path=tuple(row[5]),
        source_ranges=tuple(CharSpan(s[0], s[1]) for s in row[6]),
    )


class PgStore(Store):
    """隔离演练库 Store 实现；与 MemoryStore 逐方法同语义。"""

    def __init__(self, dsn: str, *, sandbox_db: str = "i2_sandbox_corpus") -> None:
        import psycopg

        self._conn = psycopg.connect(dsn, autocommit=True)
        self._sandbox_db = sandbox_db
        try:
            self._check_target()
        except BaseException:
            self._conn.close()
            raise

    def close(self) -> None:
        """显式释放连接（PG Adapter 专属；worker 结束时不依赖 GC 时序）。"""
        self._conn.close()

    def __enter__(self) -> PgStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _check_target(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            row = cur.fetchone()
            if row is None or row[0] != self._sandbox_db:
                raise StoreError(
                    f"拒绝：current_database={row[0] if row else None!r} ≠ {self._sandbox_db!r}"
                )
            cur.execute("SELECT datname FROM pg_database WHERE datallowconn")
            dbs = {r[0] for r in cur.fetchall()}
        if "apodex" in dbs:
            raise StoreError("拒绝：目标实例含 apodex 库——判定为生产实例，禁止写入")

    @staticmethod
    def _db_now(cur: psycopg.Cursor) -> datetime:
        """数据库当前时钟；租约判断须在行锁取得后调用。"""
        cur.execute("SELECT clock_timestamp()")
        row = cur.fetchone()
        if row is None:
            raise StoreError("数据库时间不可读")
        return row[0]

    def _current_job_row(
        self, cur: psycopg.Cursor, build_id: str, stage: JobStage, *, for_update: bool = False
    ) -> tuple | None:
        # 锁定子句须位于 ORDER BY/LIMIT 之后（PG 语法）。
        stmt = (
            _JOB_ROW_COLS + " ORDER BY attempt DESC LIMIT 1" + (" FOR UPDATE" if for_update else "")
        )
        cur.execute(stmt, (build_id, stage.value))
        return cur.fetchone()

    @staticmethod
    def _job_from_row(build_id: str, stage: JobStage, row: tuple | None) -> Job:
        if row is None:
            raise StoreError(f"job 行缺失: ({build_id}, {stage.value})")
        return Job(
            job_id=f"{build_id}:{stage.value}",
            build_id=build_id,
            stage=stage,
            attempt=row[0],
            state=JobState(row[1]),
            owner_id=row[2],
            fence_token=row[3],
            lease_until=row[4],
            heartbeat_at=row[5],
            error=row[6],
            checkpoint=_json_text_from_db(row[7]),
        )

    @staticmethod
    def _require_ownership(
        row: tuple, owner_id: str | None, fence_token: str | None, db_now: datetime
    ) -> None:
        if owner_id is None or fence_token is None:
            raise StoreError(
                "权威写入拒绝：job 已登记，写入必须携带当前租约的 owner_id/fence_token"
            )
        # fencing 判定次序（§8.1.4）：凭据不匹配先判 lease_lost——接管/重先发生后，
        # 旧 worker 的迟到写入必须得到同一语义，不能因为当前行已终态而变成状态提示。
        if row[2] != owner_id or row[3] != fence_token:
            raise StoreError("权威写入拒绝：owner/token 与当前租约不匹配（lease_lost）")
        state = JobState(row[1])
        if state is not JobState.RUNNING:
            raise StoreError(f"权威写入拒绝：job 处于 {state.value} 态，无当前所有权")
        if row[4] is not None and db_now >= row[4]:
            # RM-4：与 MemoryStore._fence 同语义——租约过期同属 lease_lost
            # （§8.1.4 更新零行即 lease_lost），两侧错误消息须可同等匹配。
            raise StoreError(
                "权威写入拒绝：租约已过期（lease_lost，fencing），须先接管取得新 token 再写入"
            )

    # ---- 来源 ----

    def put_source(self, source: Source) -> None:
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute(
                "SELECT format, mime_type, size_bytes, archive_path, original_names "
                "FROM corpus.corpus_sources WHERE source_id = %s",
                (source.source_id,),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO corpus.corpus_sources "
                    "(source_id, format, mime_type, size_bytes, archive_path, original_names) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        source.source_id,
                        source.format.value,
                        source.mime_type,
                        source.size_bytes,
                        source.archive_path,
                        list(source.original_names),
                    ),
                )
                return
            existing = Source(
                source_id=source.source_id,
                format=DocumentFormat(row[0]),
                mime_type=row[1],
                size_bytes=row[2],
                archive_path=row[3],
                original_names=tuple(row[4]),
            )
            if existing != source:
                raise StoreError(f"source 冲突：{source.source_id} 已存在且内容不同，拒绝覆盖")

    def get_source(self, source_id: str) -> Source | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT format, mime_type, size_bytes, archive_path, original_names "
                "FROM corpus.corpus_sources WHERE source_id = %s",
                (source_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return Source(
            source_id=source_id,
            format=DocumentFormat(row[0]),
            mime_type=row[1],
            size_bytes=row[2],
            archive_path=row[3],
            original_names=tuple(row[4]),
        )

    # ---- 人工审核 ----

    def put_reviewed_decision(self, decision: ReviewedDecision) -> None:
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute(
                "SELECT source_id, reviewer, reviewed_at, decision, rationale, scope_ref, "
                "supersedes, locators, material_type, research_domain "
                "FROM corpus.corpus_review_decisions WHERE decision_id = %s",
                (decision.decision_id,),
            )
            row = cur.fetchone()
            if row is not None:
                existing = ReviewedDecision(
                    decision_id=decision.decision_id,
                    source_id=row[0],
                    reviewer=row[1],
                    reviewed_at=row[2],
                    decision=ReviewDecision(row[3]),
                    rationale=row[4],
                    scope_ref=row[5],
                    supersedes=row[6],
                    locators=tuple(row[7]),
                    material_type=MaterialType(row[8]) if row[8] else None,
                    research_domain=ResearchDomain(row[9]) if row[9] else None,
                )
                if existing != decision:
                    raise StoreError(
                        f"reviewed_decision 冲突：{decision.decision_id} 已存在且内容不同"
                    )
                return
            cur.execute(
                "INSERT INTO corpus.corpus_review_decisions "
                "(decision_id, source_id, reviewer, reviewed_at, decision, rationale, "
                "scope_ref, supersedes, locators, material_type, research_domain) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    decision.decision_id,
                    decision.source_id,
                    decision.reviewer,
                    decision.reviewed_at,
                    decision.decision.value,
                    decision.rationale,
                    decision.scope_ref,
                    decision.supersedes,
                    list(decision.locators),
                    decision.material_type.value if decision.material_type else None,
                    decision.research_domain.value if decision.research_domain else None,
                ),
            )

    def get_reviewed_decision(self, decision_id: str) -> ReviewedDecision | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT source_id, reviewer, reviewed_at, decision, rationale, scope_ref, "
                "supersedes, locators, material_type, research_domain "
                "FROM corpus.corpus_review_decisions WHERE decision_id = %s",
                (decision_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return ReviewedDecision(
            decision_id=decision_id,
            source_id=row[0],
            reviewer=row[1],
            reviewed_at=row[2],
            decision=ReviewDecision(row[3]),
            rationale=row[4],
            scope_ref=row[5],
            supersedes=row[6],
            locators=tuple(row[7]),
            material_type=MaterialType(row[8]) if row[8] else None,
            research_domain=ResearchDomain(row[9]) if row[9] else None,
        )

    # ---- 准入 ----

    def put_admission(self, admission: Admission) -> None:
        from psycopg.types.json import Jsonb

        with self._conn.transaction(), self._conn.cursor() as cur:
            # RM-7：准入指针更新与 publish/retire 进入同一 source 级临界区。
            # 否则 publish 校验过 current_decision_id 之后、提交之前，另一连接仍可
            # 移动该指针（准入更新与发布交错），使最终活动指针与最新准入不再一致。
            # “谁赢”由提交顺序决定：先到者先落指针，后到者按新的当前决定重新校验。
            _advisory_lock(cur, _ADVISORY_PUB_NS, admission.source_id)
            cur.execute(
                "SELECT source_id, material_type, research_domain, decision, policy_rev, "
                "reason_codes, scope_ref, evidence_refs, review_ref, rule_rev, metadata_snapshot "
                "FROM corpus.corpus_admissions WHERE decision_id = %s",
                (admission.decision_id,),
            )
            row = cur.fetchone()
            if row is not None:
                existing = _admission_from_row(admission.decision_id, row)
                if existing != admission:
                    raise StoreError(
                        f"admission 冲突：{admission.decision_id} 已存在且内容不同，拒绝覆盖"
                    )
                # 同内容幂等重放：历史追加不可变，不得回退当前决定指针（F1/F2）。
                return
            cur.execute(
                "INSERT INTO corpus.corpus_admissions "
                "(decision_id, source_id, material_type, research_domain, decision, "
                "policy_rev, reason_codes, scope_ref, evidence_refs, review_ref, rule_rev, "
                "metadata_snapshot) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    admission.decision_id,
                    admission.source_id,
                    admission.material_type.value if admission.material_type else None,
                    admission.research_domain.value if admission.research_domain else None,
                    admission.decision.value,
                    admission.policy_rev,
                    [c.value for c in admission.reason_codes],
                    admission.scope_ref,
                    list(admission.evidence_refs),
                    admission.review_ref,
                    admission.rule_rev,
                    Jsonb(_snapshot_to_dict(admission)),
                ),
            )
            # G5：latest_admission 指针与新准入同事务更新（仅新插入时移动）。
            cur.execute(
                "UPDATE corpus.corpus_sources SET current_decision_id = %s WHERE source_id = %s",
                (admission.decision_id, admission.source_id),
            )

    def get_admission(self, decision_id: str) -> Admission | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT source_id, material_type, research_domain, decision, policy_rev, "
                "reason_codes, scope_ref, evidence_refs, review_ref, rule_rev, metadata_snapshot "
                "FROM corpus.corpus_admissions WHERE decision_id = %s",
                (decision_id,),
            )
            row = cur.fetchone()
        return _admission_from_row(decision_id, row) if row else None

    def latest_admission(self, source_id: str) -> Admission | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT a.decision_id, a.source_id, a.material_type, a.research_domain, "
                "a.decision, a.policy_rev, a.reason_codes, a.scope_ref, a.evidence_refs, "
                "a.review_ref, a.rule_rev, a.metadata_snapshot "
                "FROM corpus.corpus_admissions a "
                "JOIN corpus.corpus_sources s ON s.current_decision_id = a.decision_id "
                "WHERE a.source_id = %s",
                (source_id,),
            )
            row = cur.fetchone()
        return _admission_from_row(row[0], row[1:]) if row else None

    # ---- 构建 ----

    def put_build(self, build: Build) -> None:
        from psycopg.types.json import Jsonb

        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute(
                "SELECT source_id, decision_id, parse_rev, clean_rev, chunk_rev, index_rev, "
                "scope_ref, config_fingerprint, artifact_manifest, quality_report "
                "FROM corpus.corpus_builds WHERE build_id = %s",
                (build.build_id,),
            )
            row = cur.fetchone()
            if row is not None:
                existing = _build_from_row(build.build_id, row)
                if existing != _normalized_build(build):
                    raise StoreError(f"build 冲突：{build.build_id} 已存在且内容不同，拒绝覆盖")
                return
            cur.execute(
                "INSERT INTO corpus.corpus_builds "
                "(build_id, source_id, decision_id, parse_rev, clean_rev, chunk_rev, "
                "index_rev, scope_ref, config_fingerprint, artifact_manifest, quality_report) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    build.build_id,
                    build.source_id,
                    build.decision_id,
                    build.parse_rev,
                    build.clean_rev,
                    build.chunk_rev,
                    build.index_rev,
                    build.scope_ref,
                    build.config_fingerprint,
                    list(build.artifact_manifest),
                    Jsonb(json.loads(build.quality_report)) if build.quality_report else None,
                ),
            )

    def get_build(self, build_id: str) -> Build | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT source_id, decision_id, parse_rev, clean_rev, chunk_rev, index_rev, "
                "scope_ref, config_fingerprint, artifact_manifest, quality_report "
                "FROM corpus.corpus_builds WHERE build_id = %s",
                (build_id,),
            )
            row = cur.fetchone()
        return _build_from_row(build_id, row) if row else None

    # ---- units / chunks（fencing 权威写入）----

    def put_units(
        self,
        build_id: str,
        units: Iterable[Unit],
        *,
        owner_id: str | None = None,
        fence_token: str | None = None,
    ) -> None:
        from psycopg.types.json import Jsonb

        with self._conn.transaction(), self._conn.cursor() as cur:
            row = self._current_job_row(cur, build_id, JobStage.PARSED, for_update=True)
            if row is None:
                raise StoreError(
                    f"权威写入拒绝：job ({build_id}, parsed) 未登记"
                    "（fail-closed：须先 register_job/acquire_job 取得租约）"
                )
            db_now = self._db_now(cur)
            self._require_ownership(row, owner_id, fence_token, db_now)
            for unit in units:
                if unit.build_id != build_id:
                    raise StoreError(f"unit.build_id 与目标 build_id 不一致: {unit.unit_id}")
                cur.execute(
                    "SELECT parent_id, ordinal, kind, raw_text, content_hash, location, "
                    "clean_view, mapping, status, reasons FROM corpus.corpus_units "
                    "WHERE build_id = %s AND unit_id = %s",
                    (build_id, unit.unit_id),
                )
                existing_row = cur.fetchone()
                if existing_row is not None:
                    existing = _unit_from_row(build_id, unit.unit_id, existing_row)
                    if existing != unit:
                        raise StoreError(f"unit 冲突：{unit.unit_id} 已存在且内容不同")
                    continue
                cur.execute(
                    "INSERT INTO corpus.corpus_units "
                    "(build_id, unit_id, parent_id, ordinal, kind, raw_text, content_hash, "
                    "location, clean_view, mapping, status, reasons) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        build_id,
                        unit.unit_id,
                        unit.parent_id,
                        unit.ordinal,
                        unit.kind,
                        unit.raw_text,
                        unit.content_hash,
                        Jsonb(_location_to_dict(unit)),
                        unit.clean_view,
                        Jsonb([list(span) for span in unit.mapping]),
                        unit.status.value,
                        list(unit.reasons),
                    ),
                )

    def get_unit(self, build_id: str, unit_id: str) -> Unit | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT parent_id, ordinal, kind, raw_text, content_hash, location, "
                "clean_view, mapping, status, reasons FROM corpus.corpus_units "
                "WHERE build_id = %s AND unit_id = %s",
                (build_id, unit_id),
            )
            row = cur.fetchone()
        return _unit_from_row(build_id, unit_id, row) if row else None

    def get_units(self, build_id: str) -> tuple[Unit, ...]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT unit_id, parent_id, ordinal, kind, raw_text, content_hash, location, "
                "clean_view, mapping, status, reasons FROM corpus.corpus_units "
                "WHERE build_id = %s ORDER BY ordinal NULLS LAST, unit_id",
                (build_id,),
            )
            rows = cur.fetchall()
        return tuple(_unit_from_row(build_id, r[0], r[1:]) for r in rows)

    def put_chunks(
        self,
        build_id: str,
        chunks: Iterable[Chunk],
        *,
        owner_id: str | None = None,
        fence_token: str | None = None,
    ) -> None:
        from psycopg.types.json import Jsonb

        with self._conn.transaction(), self._conn.cursor() as cur:
            row = self._current_job_row(cur, build_id, JobStage.CHUNKED, for_update=True)
            if row is None:
                raise StoreError(
                    f"权威写入拒绝：job ({build_id}, chunked) 未登记"
                    "（fail-closed：须先 register_job/acquire_job 取得租约）"
                )
            db_now = self._db_now(cur)
            self._require_ownership(row, owner_id, fence_token, db_now)
            for chunk in chunks:
                if chunk.build_id != build_id:
                    raise StoreError(f"chunk.build_id 与目标 build_id 不一致: {chunk.chunk_id}")
                cur.execute(
                    "SELECT kind, unit_refs, context_refs, search_text, title_text, "
                    "section_path, source_ranges FROM corpus.corpus_chunks "
                    "WHERE build_id = %s AND chunk_id = %s",
                    (build_id, chunk.chunk_id),
                )
                existing_row = cur.fetchone()
                if existing_row is not None:
                    existing = _chunk_from_row(build_id, chunk.chunk_id, existing_row)
                    if existing != chunk:
                        raise StoreError(f"chunk 冲突：{chunk.chunk_id} 已存在且内容不同")
                    continue
                cur.execute(
                    "INSERT INTO corpus.corpus_chunks "
                    "(build_id, chunk_id, kind, unit_refs, context_refs, search_text, "
                    "title_text, section_path, source_ranges) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        build_id,
                        chunk.chunk_id,
                        chunk.kind,
                        list(chunk.unit_refs),
                        list(chunk.context_refs),
                        chunk.search_text,
                        chunk.title_text,
                        list(chunk.section_path),
                        Jsonb([[s.start, s.end] for s in chunk.source_ranges]),
                    ),
                )

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT build_id, kind, unit_refs, context_refs, search_text, title_text, "
                "section_path, source_ranges FROM corpus.corpus_chunks WHERE chunk_id = %s",
                (chunk_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return _chunk_from_row(row[0], chunk_id, row[1:])

    def get_chunks(self, build_id: str) -> tuple[Chunk, ...]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT chunk_id, kind, unit_refs, context_refs, search_text, title_text, "
                "section_path, source_ranges FROM corpus.corpus_chunks "
                "WHERE build_id = %s ORDER BY chunk_id",
                (build_id,),
            )
            rows = cur.fetchall()
        return tuple(_chunk_from_row(build_id, r[0], r[1:]) for r in rows)

    # ---- 来源级检查点（last-write-wins）----

    def put_source_checkpoint(self, source_id: str, stage: str, checkpoint: str) -> None:
        from psycopg.types.json import Jsonb

        if len(source_id) != 64 or any(c not in "0123456789abcdef" for c in source_id):
            raise StoreError(f"source_checkpoint.source_id 非法: {source_id!r}")
        if not stage:
            raise StoreError("source_checkpoint.stage 不能为空")
        if stage.startswith(REVIEW_STAGE_PREFIX):
            raise StoreError("human gap review namespace requires put_gap_review")
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO corpus.corpus_source_checkpoints (source_id, stage, checkpoint, "
                "updated_at) VALUES (%s, %s, %s, now()) "
                "ON CONFLICT (source_id, stage) DO UPDATE SET "
                "checkpoint = EXCLUDED.checkpoint, updated_at = now()",
                (source_id, stage, Jsonb(json.loads(checkpoint))),
            )

    def _put_gap_review(self, build: Build, payload: str) -> None:
        from psycopg.types.json import Jsonb

        stage = REVIEW_STAGE_PREFIX + build.build_id
        data = json.loads(payload)
        with self._conn.transaction(), self._conn.cursor() as cur:
            # INSERT-first + DO NOTHING serializes concurrent first writers. Compare
            # in the following statement so a conflicting winner is never overwritten.
            cur.execute(
                "INSERT INTO corpus.corpus_source_checkpoints "
                "(source_id, stage, checkpoint, updated_at) VALUES (%s, %s, %s, now()) "
                "ON CONFLICT (source_id, stage) DO NOTHING",
                (build.source_id, stage, Jsonb(data)),
            )
            cur.execute(
                "SELECT checkpoint FROM corpus.corpus_source_checkpoints "
                "WHERE source_id = %s AND stage = %s",
                (build.source_id, stage),
            )
            row = cur.fetchone()
            existing = _json_text_from_db(row[0]) if row is not None else None
            if existing is None or json.loads(existing) != data:
                raise StoreError(
                    "human gap review conflict: immutable credential cannot be replaced"
                )

    def get_source_checkpoint(self, source_id: str, stage: str) -> str | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT checkpoint FROM corpus.corpus_source_checkpoints "
                "WHERE source_id = %s AND stage = %s",
                (source_id, stage),
            )
            row = cur.fetchone()
        return _json_text_from_db(row[0]) if row else None

    # ---- 发布与撤销 ----

    def get_publication(self, source_id: str) -> Publication | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT current_decision_id, active_build_id, generation, activated_at "
                "FROM corpus.corpus_publications WHERE source_id = %s",
                (source_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return Publication(
            source_id=source_id,
            current_decision_id=row[0],
            active_build_id=row[1],
            generation=row[2],
            activated_at=row[3],
        )

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
        with self._conn.transaction(), self._conn.cursor() as cur:
            # J2：同一 source 的活动指针临界区（并发发布/generation 递增不得丢更新）。
            _advisory_lock(cur, _ADVISORY_PUB_NS, source_id)
            job_row = self._current_job_row(cur, build_id, JobStage.PUBLISHED, for_update=True)
            if job_row is None:
                raise StoreError(
                    f"publish 拒绝：PUBLISHED job ({build_id}) 未登记"
                    "（fail-closed：发布必须经引擎 register_job/acquire_job 取得租约，"
                    "无 job/no-check 旁路）"
                )
            db_now = self._db_now(cur)
            self._require_ownership(job_row, owner_id, fence_token, db_now)
            cur.execute(
                "SELECT source_id, decision_id, scope_ref "
                "FROM corpus.corpus_builds WHERE build_id = %s",
                (build_id,),
            )
            build_row = cur.fetchone()
            if build_row is None or build_row[0] != source_id:
                raise StoreError(f"publish：build {build_id} 不存在或不属于 source {source_id}")
            if build_row[1] != decision_id:
                raise StoreError(
                    f"publish：build {build_id} 绑定决定 {build_row[1]}，"
                    f"与请求决定 {decision_id} 不一致，不得复用旧构建发布新决定"
                )
            cur.execute(
                "SELECT source_id, decision, scope_ref FROM corpus.corpus_admissions "
                "WHERE decision_id = %s",
                (decision_id,),
            )
            adm_row = cur.fetchone()
            if adm_row is None or adm_row[0] != source_id:
                raise StoreError(
                    f"publish：admission {decision_id} 不存在或不属于 source {source_id}"
                )
            cur.execute(
                "SELECT current_decision_id FROM corpus.corpus_sources WHERE source_id = %s",
                (source_id,),
            )
            ptr_row = cur.fetchone()
            if ptr_row is None or ptr_row[0] != decision_id:
                raise StoreError(
                    f"publish：admission {decision_id} 不是 source {source_id} 的当前决定"
                    f"（当前为 {ptr_row[0] if ptr_row else None}），不得切活动指针"
                )
            if adm_row[2] is not None and build_row[2] != adm_row[2]:
                raise StoreError(
                    f"publish：build scope {build_row[2]!r} 超出准入 scope {adm_row[2]!r}"
                    "（部分章节批准不得升级为整篇构建发布）"
                )
            if adm_row[1] != AdmissionDecision.IN_SCOPE.value:
                raise StoreError(f"publish：admission {decision_id} 非 in_scope，不得切活动指针")
            return self._set_publication(cur, source_id, decision_id, build_id, db_now)

    def retire(self, source_id: str, decision_id: str, activated_at: datetime) -> Publication:
        del activated_at  # publish_idempotency_v2：时间由翻转事务的数据库时钟生成。
        with self._conn.transaction(), self._conn.cursor() as cur:
            _advisory_lock(cur, _ADVISORY_PUB_NS, source_id)  # J2：与 publish 同一临界区
            db_now = self._db_now(cur)
            cur.execute(
                "SELECT source_id FROM corpus.corpus_admissions WHERE decision_id = %s",
                (decision_id,),
            )
            adm_row = cur.fetchone()
            if adm_row is None or adm_row[0] != source_id:
                raise StoreError(
                    f"retire：admission {decision_id} 不存在或不属于 source {source_id}"
                )
            cur.execute(
                "SELECT current_decision_id FROM corpus.corpus_sources WHERE source_id = %s",
                (source_id,),
            )
            ptr_row = cur.fetchone()
            if ptr_row is None or ptr_row[0] != decision_id:
                raise StoreError(
                    f"retire：admission {decision_id} 不是 source {source_id} 的当前决定"
                    f"（当前为 {ptr_row[0] if ptr_row else None}），不得撤销"
                )
            return self._set_publication(cur, source_id, decision_id, None, db_now)

    def _set_publication(
        self,
        cur: psycopg.Cursor,
        source_id: str,
        decision_id: str,
        active_build_id: str | None,
        activated_at: datetime,
    ) -> Publication:
        """publish_idempotency_v2（I0-C 裁决，G2 闭合）：幂等按目标状态比对，不以时间为键。

        ``activated_at`` 由调用方在翻转事务内以数据库时钟取得（publish/retire 各自先
        ``SELECT now()``），本方法不再单独取时。
        """
        cur.execute(
            "SELECT current_decision_id, active_build_id, generation, activated_at "
            "FROM corpus.corpus_publications WHERE source_id = %s FOR UPDATE",
            (source_id,),
        )
        row = cur.fetchone()
        if row is not None and row[0] == decision_id and row[1] == active_build_id:
            return Publication(
                source_id=source_id,
                current_decision_id=row[0],
                active_build_id=row[1],
                generation=row[2],
                activated_at=row[3],
            )
        generation = 1 if row is None else row[2] + 1
        publication = Publication(
            source_id=source_id,
            current_decision_id=decision_id,
            active_build_id=active_build_id,
            generation=generation,
            activated_at=activated_at,
        )
        cur.execute(
            "INSERT INTO corpus.corpus_publications "
            "(source_id, current_decision_id, active_build_id, generation, activated_at) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (source_id) DO UPDATE SET "
            "current_decision_id = EXCLUDED.current_decision_id, "
            "active_build_id = EXCLUDED.active_build_id, "
            "generation = EXCLUDED.generation, activated_at = EXCLUDED.activated_at",
            (
                source_id,
                publication.current_decision_id,
                publication.active_build_id,
                publication.generation,
                publication.activated_at,
            ),
        )
        return publication

    # ---- job 生命周期 ----

    def register_job(self, build_id: str, stage: JobStage) -> Job:
        with self._conn.transaction(), self._conn.cursor() as cur:
            _advisory_lock(cur, _ADVISORY_JOB_NS, f"{build_id}:{stage.value}")
            row = self._current_job_row(cur, build_id, stage, for_update=True)
            if row is not None:
                return self._job_from_row(build_id, stage, row)
            cur.execute(
                "INSERT INTO corpus.corpus_jobs (build_id, stage, attempt, state) "
                "VALUES (%s, %s, 1, 'queued')",
                (build_id, stage.value),
            )
            row = self._current_job_row(cur, build_id, stage)
            return self._job_from_row(build_id, stage, row)

    def get_job(self, build_id: str, stage: JobStage) -> Job | None:
        with self._conn.cursor() as cur:
            row = self._current_job_row(cur, build_id, stage)
        return self._job_from_row(build_id, stage, row) if row else None

    def acquire_job(
        self,
        build_id: str,
        stage: JobStage,
        owner_id: str,
        now: datetime,
        lease_config: LeaseConfig,
    ) -> Job:
        del now  # §8.1.2：租约时间只取数据库时间（调用方时钟仅接口兼容）。
        with self._conn.transaction(), self._conn.cursor() as cur:
            _advisory_lock(cur, _ADVISORY_JOB_NS, f"{build_id}:{stage.value}")
            row = self._current_job_row(cur, build_id, stage, for_update=True)
            if row is None:
                raise StoreError(f"job 未登记: ({build_id}, {stage.value})")
            db_now = self._db_now(cur)
            attempt, state_s, prev_owner = row[0], row[1], row[2]
            state = JobState(state_s)
            if state is JobState.SUCCEEDED and stage is not JobStage.PUBLISHED:
                return self._job_from_row(build_id, stage, row)  # §8.1 幂等短路
            if (
                stage is JobStage.PUBLISHED
                and state is JobState.SUCCEEDED
                and attempt >= lease_config.max_attempts
            ):
                # PUBLISHED 重激活同样消耗预算（配合上面 SUCCEEDED 例外，避免无限重激活）。
                raise StoreError("job 已达 max_attempts，不可重新激活发布租约")
            if state is JobState.CANCELLED and stage is not JobStage.PUBLISHED:
                raise StoreError("cancelled job 不自动复活")
            if state is JobState.CANCELLED and attempt >= lease_config.max_attempts:
                raise StoreError("job 已达 max_attempts，不可重试")
            if state is JobState.RUNNING and row[4] is not None and db_now < row[4]:
                raise StoreError(f"job 仍由 {prev_owner} 持有且租约未过期，不得抢占")
            if state in (JobState.RUNNING, JobState.FAILED, JobState.CANCELLED) and (
                attempt >= lease_config.max_attempts
            ):
                raise StoreError("job 已达 max_attempts，不可重试")
            if state is JobState.RUNNING:
                # 接管过期 running：旧行落为 failed（attempt 历史保留），腾出
                # partial unique 的 running 位后再插入新 attempt 行。
                cur.execute(
                    "UPDATE corpus.corpus_jobs SET state = 'failed', error = %s, "
                    "lease_until = NULL WHERE build_id = %s AND stage = %s AND attempt = %s",
                    (
                        f"lease_expired (taken over by {owner_id})",
                        build_id,
                        stage.value,
                        attempt,
                    ),
                )
            new_attempt = attempt if state is JobState.QUEUED else attempt + 1
            fence_token = canonical_fingerprint(
                (build_id, stage.value, new_attempt, owner_id, db_now.isoformat())
            )
            lease_until = db_now + timedelta(seconds=lease_config.lease_ttl_seconds)
            if state is JobState.QUEUED:
                cur.execute(
                    "UPDATE corpus.corpus_jobs SET state = 'running', owner_id = %s, "
                    "fence_token = %s, lease_until = %s, heartbeat_at = %s, error = NULL "
                    "WHERE build_id = %s AND stage = %s AND attempt = %s",
                    (
                        owner_id,
                        fence_token,
                        lease_until,
                        db_now,
                        build_id,
                        stage.value,
                        new_attempt,
                    ),
                )
            else:
                cur.execute(
                    "INSERT INTO corpus.corpus_jobs "
                    "(build_id, stage, attempt, state, owner_id, fence_token, "
                    "lease_until, heartbeat_at) VALUES (%s, %s, %s, 'running', %s, %s, %s, %s)",
                    (
                        build_id,
                        stage.value,
                        new_attempt,
                        owner_id,
                        fence_token,
                        lease_until,
                        db_now,
                    ),
                )
            current = self._current_job_row(cur, build_id, stage)
            return self._job_from_row(build_id, stage, current)

    def heartbeat_job(
        self,
        build_id: str,
        stage: JobStage,
        owner_id: str,
        fence_token: str,
        now: datetime,
        lease_config: LeaseConfig,
    ) -> Job:
        del now  # 数据库时间
        with self._conn.transaction(), self._conn.cursor() as cur:
            _advisory_lock(cur, _ADVISORY_JOB_NS, f"{build_id}:{stage.value}")
            row = self._current_job_row(cur, build_id, stage, for_update=True)
            if row is None:
                raise StoreError(f"job 未登记: ({build_id}, {stage.value})")
            db_now = self._db_now(cur)
            self._require_ownership(row, owner_id, fence_token, db_now)
            cur.execute(
                "UPDATE corpus.corpus_jobs SET heartbeat_at = %s, lease_until = %s "
                "WHERE build_id = %s AND stage = %s AND attempt = %s",
                (
                    db_now,
                    db_now + timedelta(seconds=lease_config.lease_ttl_seconds),
                    build_id,
                    stage.value,
                    row[0],
                ),
            )
            current = self._current_job_row(cur, build_id, stage)
            return self._job_from_row(build_id, stage, current)

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
        del now  # 数据库时间
        from psycopg.types.json import Jsonb

        if state not in _TERMINAL_STATES:
            raise StoreError(f"finish_job 只能是终态，收到 {state.value}")
        with self._conn.transaction(), self._conn.cursor() as cur:
            _advisory_lock(cur, _ADVISORY_JOB_NS, f"{build_id}:{stage.value}")
            row = self._current_job_row(cur, build_id, stage, for_update=True)
            if row is None:
                raise StoreError(f"job 未登记: ({build_id}, {stage.value})")
            current_state = JobState(row[1])
            if current_state in _TERMINAL_STATES:
                # RM-1：终态重放必须先锚定所有权。fence_token 唯一绑定 attempt，
                # 因此「不同 attempt 的相同终态」不是同一次提交——worker 被接管、
                # 接管者已完成（attempt N+1）后，旧 worker 携 attempt N 的旧 token
                # 迟到 finish，必须得到 lease_lost，而不是被误认成自己的提交成功。
                if owner_id is None or fence_token is None:
                    raise StoreError(
                        f"权威写入拒绝：job ({build_id}, {stage.value}) 已终态，"
                        "finish 必须携带 owner_id/fence_token"
                    )
                if row[2] != owner_id or row[3] != fence_token:
                    raise StoreError(
                        "权威写入拒绝：owner/token 与当前租约不匹配（lease_lost）——"
                        f"该 job 已由 {row[2]!r} 在 attempt {row[0]} 完成，"
                        "旧 worker 不得误认他人的提交为成功"
                    )
                if current_state is state:
                    # 同 attempt 提交成功但客户端未收到响应：重试读取已提交检查点，不重复增行。
                    return self._job_from_row(build_id, stage, row)
                raise StoreError(f"job 已处于终态 {current_state.value}，不得改为 {state.value}")
            db_now = self._db_now(cur)
            self._require_ownership(row, owner_id, fence_token, db_now)
            cur.execute(
                "UPDATE corpus.corpus_jobs SET state = %s, error = %s, checkpoint = %s, "
                "lease_until = NULL WHERE build_id = %s AND stage = %s AND attempt = %s",
                (
                    state.value,
                    error,
                    Jsonb(json.loads(checkpoint)) if checkpoint else None,
                    build_id,
                    stage.value,
                    row[0],
                ),
            )
            current = self._current_job_row(cur, build_id, stage)
            return self._job_from_row(build_id, stage, current)
