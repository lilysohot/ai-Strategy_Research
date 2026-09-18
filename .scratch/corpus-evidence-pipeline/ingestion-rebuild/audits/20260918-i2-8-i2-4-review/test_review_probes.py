"""I2-8 / I2-4 独立复核探针：最小失败信号 + 阳性对照。

运行环境：``i2-verify`` 守卫 env、``CORPUS_I2_DSN`` → ``i2_sandbox_corpus``（隔离库）。
每个反例断言的是**契约要求**（tasks.md I2-8/I2-4、架构 §7.2/§7.3、design-review
``i0c_4.consumer_migration_matrix``），因此失败即偏离证据，不是断言写错。

末尾 ``test_control_*`` 是阳性对照：它必须通过，否则说明装置本身有问题，
前面所有红灯都不构成缺陷证据。

数据纪律：仅写 i2_sandbox_corpus 的 corpus schema（目标双校验）；不触生产库、
不读来源正文、不调模型。
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime

import pytest

DSN = os.environ.get("CORPUS_I2_DSN", "")
if not DSN:
    pytest.skip("CORPUS_I2_DSN 未设置（非 I2 演练环境）", allow_module_level=True)

import psycopg  # noqa: E402  仅 I2 演练环境导入

from plugins.corpus import cli  # noqa: E402
from plugins.corpus.preparation import read_pg  # noqa: E402
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
    sha256_of_bytes,
)
from plugins.corpus.preparation.engine import INDEX_REV_V3  # noqa: E402
from plugins.corpus.preparation.repository import StoreError  # noqa: E402
from plugins.corpus.preparation.repository_pg import PgStore  # noqa: E402
from plugins.corpus.service import CorpusService  # noqa: E402
from plugins.tools.corpus_fetch import corpus_fetch  # noqa: E402
from plugins.tools.corpus_search import corpus_search  # noqa: E402

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
NOW = datetime(2026, 9, 18, 12, tzinfo=UTC)
SOURCE_ID = sha256_of_bytes(b"i2s8review:source")


@pytest.fixture(autouse=True)
def _clean_tables():
    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        database = cur.fetchone()[0]
        if database != SANDBOX_DB:
            raise StoreError(f"拒绝清理：current_database={database!r} ≠ {SANDBOX_DB!r}")
        cur.execute("SELECT datname FROM pg_database WHERE datallowconn")
        if "apodex" in {r[0] for r in cur.fetchall()}:
            raise StoreError("拒绝清理：目标实例含 apodex 库")
        cur.execute(f"TRUNCATE {', '.join(f'corpus.{t}' for t in TABLES)}")
    yield


@pytest.fixture()
def store() -> PgStore:
    instance = PgStore(DSN, sandbox_db=SANDBOX_DB)
    yield instance
    instance.close()


@pytest.fixture()
def service(monkeypatch: pytest.MonkeyPatch) -> CorpusService:
    monkeypatch.setenv("CORPUS_READ_CHAIN", "new")
    monkeypatch.setattr("plugins.corpus.service.dsn", lambda: DSN)
    return CorpusService(DSN)


def _register_source(store: PgStore) -> None:
    store.put_source(
        Source(
            source_id=SOURCE_ID,
            format=DocumentFormat.MARKDOWN,
            mime_type="text/markdown",
            size_bytes=128,
            archive_path=f"ab/{SOURCE_ID}.md",
            original_names=("review.md",),
        )
    )
    store.put_admission(
        Admission(
            decision_id="d1",
            source_id=SOURCE_ID,
            material_type=MaterialType.RESEARCH_REPORT,
            research_domain=ResearchDomain.COMPANY,
            decision=AdmissionDecision.IN_SCOPE,
            policy_rev="v1-20260915",
        )
    )


def _publish(store: PgStore, build_id: str, text: str) -> str:
    """建并发布一个 build（单单元/单块），返回 chunk_id。"""
    _register_source(store)
    store.put_build(
        Build(
            build_id=build_id,
            source_id=SOURCE_ID,
            decision_id="d1",
            parse_rev="parse-test",
            clean_rev="clean-test",
            chunk_rev="chunk-test",
            index_rev=INDEX_REV_V3,
            quality_report='{"gap_regions": [], "oversized_chunks": []}',
        )
    )
    unit = Unit(
        unit_id="u1",
        build_id=build_id,
        kind="paragraph",
        raw_text=text,
        content_hash=sha256_of_bytes(text.encode()),
        ordinal=1,
        status=UnitStatus.KEPT,
    )
    store.register_job(build_id, JobStage.PARSED)
    parsed = store.acquire_job(build_id, JobStage.PARSED, "w1", NOW, LEASE)
    store.put_units(build_id, [unit], owner_id="w1", fence_token=parsed.fence_token)
    store.finish_job(build_id, JobStage.PARSED, "w1", parsed.fence_token, NOW, JobState.SUCCEEDED)

    chunk_id = f"{build_id[:16]}:c0"
    store.register_job(build_id, JobStage.CHUNKED)
    chunked = store.acquire_job(build_id, JobStage.CHUNKED, "w1", NOW, LEASE)
    store.put_chunks(
        build_id,
        [
            Chunk(
                chunk_id=chunk_id,
                build_id=build_id,
                kind="paragraph",
                unit_refs=("u1",),
                search_text=text,
            )
        ],
        owner_id="w1",
        fence_token=chunked.fence_token,
    )
    store.finish_job(build_id, JobStage.CHUNKED, "w1", chunked.fence_token, NOW, JobState.SUCCEEDED)

    store.register_job(build_id, JobStage.PUBLISHED)
    published = store.acquire_job(build_id, JobStage.PUBLISHED, "w1", NOW, LEASE)
    store.publish(SOURCE_ID, "d1", build_id, NOW, owner_id="w1", fence_token=published.fence_token)
    store.finish_job(
        build_id, JobStage.PUBLISHED, "w1", published.fence_token, NOW, JobState.SUCCEEDED
    )
    return chunk_id


# ── 反例 1：§7.3 / consumer matrix [11] 要求的 publication_snapshot_ref 缺失 ──


def test_coverage_carries_publication_snapshot_ref(store: PgStore) -> None:
    """§7.3「coverage 必带 requested_scope_ref/effective_scope_ref/publication_snapshot_ref/
    reason_codes」；consumer matrix [11]（data_coverage.py）同列该三 ref。"""
    _publish(store, sha256_of_bytes(b"i2s8review:cov"), "石英股份产能 100 万吨")
    coverage = read_pg.coverage_snapshot(DSN, sandbox_db=SANDBOX_DB, query_status="matched")
    for key in ("requested_scope_ref", "effective_scope_ref", "publication_snapshot_ref"):
        assert key in coverage, f"coverage 缺 §7.3 必带字段 {key}：{sorted(coverage)}"
    assert coverage["reason_codes"] is not None


# ── 反例 2：版本句柄的文档级读取静默换正文 + 出处错标 ──────────────


def test_stale_document_handle_does_not_silently_switch_body(
    store: PgStore, service: CorpusService
) -> None:
    """tasks.md I2-8 验收门：「新句柄可跨发布取回原版本」「不静默换正文」。

    同一 ``cv2:<build_a>`` 句柄：块级 ``fetch_verbatim`` 取回 A 的正文（既有已测行为），
    文档级 ``document_text`` 却返回**活动版本 B** 的正文——且返回值仍标注 build_id=A。
    """
    build_a = sha256_of_bytes(b"i2s8review:build:a")
    chunk_a = _publish(store, build_a, "石英股份旧版产能 100 万吨")
    build_b = sha256_of_bytes(b"i2s8review:build:b")
    _publish(store, build_b, "石英股份新版产能 120 万吨")

    # 既有已测行为（对照基准）：块级读取返回原 build
    assert service.fetch_verbatim(f"cv2:{build_a}", f"chunk:{chunk_a}").text == (
        "石英股份旧版产能 100 万吨"
    )

    doc = read_pg.fetch_document(DSN, f"cv2:{build_a}", sandbox_db=SANDBOX_DB)
    assert doc.text == "石英股份旧版产能 100 万吨", (
        f"文档级读取静默切换了正文：句柄=cv2:{build_a[:12]}…，实得正文={doc.text!r}"
        f"（活动版本为 {build_b[:12]}…）"
    )
    # 无论取何种语义，出处标注都不得与正文来源不一致
    assert doc.build_id == build_a


# ── 反例 3：撤销后文档级读取返回空串（fail-open）────────────────


def test_withdrawn_source_document_text_is_not_empty_string(
    store: PgStore, service: CorpusService
) -> None:
    """§7.2「来源撤销后不得继续服务」：块级抛 WithdrawnError；文档级当前返回 ``""``，
    调用方 ``if text is None`` 判空失败 → 拿到"合法空文档"而非拒绝信号。"""
    build_id = sha256_of_bytes(b"i2s8review:build:wd")
    _publish(store, build_id, "石英股份产能 100 万吨")
    store.put_admission(
        Admission(
            decision_id="d2",
            source_id=SOURCE_ID,
            material_type=MaterialType.PIPELINE_ARTIFACT,
            research_domain=None,
            decision=AdmissionDecision.EXCLUDED_BY_POLICY,
            policy_rev="v1-20260915",
        )
    )
    store.retire(SOURCE_ID, "d2", NOW)

    text = service.document_text(f"cv2:{build_id}")
    assert text != "", (
        "撤销后文档级读取返回空串（非 None/非拒绝）：与块级 WithdrawnError 语义不一致，"
        "且空串会被调用方当成合法空文档"
    )
    assert text is None


# ── 反例 4：corpus_fetch 工具载荷缺 span（consumer matrix [4]）──


def test_fetch_tool_payload_exposes_span(
    store: PgStore, service: CorpusService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """design-review``consumer_migration_matrix[4]``corpus_fetch 动作为
    「fetch 校验 chunk∈build，返回原文片段+**span**/cell」；``ChunkEvidence.source_ranges``
    已产出，但工具载荷未透出该字段。"""
    build_id = sha256_of_bytes(b"i2s8review:build:span")
    _publish(store, build_id, "石英股份产能 100 万吨")
    payload = json.loads(asyncio.run(corpus_search.ainvoke({"query": "石英", "limit": 5})))
    hit = payload["hits"][0]
    fetched = json.loads(
        asyncio.run(corpus_fetch.ainvoke({"doc_id": hit["doc_id"], "locator": hit["locator"]}))
    )
    assert fetched["ok"] is True
    assert "source_ranges" in fetched or "span" in fetched, (
        f"corpus_fetch 未透出 span（source_ranges）：载荷键={sorted(fetched)}"
    )


# ── 反例 5：同一前置条件映射到两个退出码 ──────────────────────


def test_unknown_build_exit_code_is_consistent_across_commands(
    store: PgStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """I2-4 验收门要求「错误退出码」可用：同一「build 不存在」前置条件，
    ``check`` 返 4、``status`` 返 5，调用方无法统一判定。"""
    unknown = "0" * 64
    check_code = cli.main(["check", "--build", unknown, "--dsn", DSN])
    capsys.readouterr()
    status_code = cli.main(["status", "--build", unknown, "--dsn", DSN])
    capsys.readouterr()
    assert check_code == status_code, (
        f"同一输入退出码不一致：check={check_code}、status={status_code}"
    )


# ── 阳性对照（必须通过，否则上述红灯不构成证据）──────────────


def test_control_round_trip_and_coverage_scopes(
    store: PgStore, service: CorpusService
) -> None:
    build_id = sha256_of_bytes(b"i2s8review:control")
    chunk_id = _publish(store, build_id, "石英股份产能 100 万吨")

    hits = service.search("石英", limit=5)
    assert len(hits) == 1
    assert hits[0].doc_id == f"cv2:{build_id}"
    assert hits[0].locator == f"chunk:{chunk_id}"

    evidence = service.fetch_verbatim(hits[0].doc_id, hits[0].locator)
    assert evidence.text == "石英股份产能 100 万吨"
    assert evidence.active is True

    coverage = read_pg.coverage_snapshot(DSN, sandbox_db=SANDBOX_DB, query_status="matched")
    assert coverage["requested_scope_ref"] and coverage["effective_scope_ref"]
    assert set(coverage["counts"]) >= {"sources", "published", "withdrawn", "pending", "builds"}

    # 旧句柄拒绝路径（既有契约）
    with pytest.raises(read_pg.LegacyHandleError):
        service.fetch_verbatim("2026-09-09_legacy", "chunk:x")
