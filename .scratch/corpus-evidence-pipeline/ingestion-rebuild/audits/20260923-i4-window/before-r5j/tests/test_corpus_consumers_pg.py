"""I2-8 消费者接线（二）真库门：版本句柄、跨发布取回、旧句柄拒绝、coverage 三轴。

运行条件：``CORPUS_I2_DSN`` 指向隔离库 ``i2_sandbox_corpus``（i2-verify 守卫 env）；
无 DSN 时模块级跳过（I2-8 过门时必须实际运行）。

验收口径（tasks.md I2-8 + 架构 §7.2/§7.3）：

- ``corpus_search`` 命中返回 ``cv2:<build_id>`` + ``chunk:<chunk_id>`` 句柄，并可由
  ``corpus_fetch`` 取回**逐字**权威原文（断言读到的就是该 build 的 raw_text）；
- 新版本发布后，旧句柄仍取回其原 build（不静默换正文）；检索只服务活动 build；
- 旧/未知句柄显式拒绝（``archive_required``/跨 build），不拿新链内容顶替；
- 撤销准入后句柄拒绝、读侧零候选；
- coverage 三轴：``no_match`` 不自动转 ``absent``（availability 仍 unknown）。
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

from plugins.corpus.preparation import read_pg  # noqa: E402
from plugins.corpus.preparation.contract import (  # noqa: E402
    Admission,
    AdmissionDecision,
    Build,
    CharSpan,
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
NOW = datetime(2026, 9, 18, 10, tzinfo=UTC)
SOURCE_ID = sha256_of_bytes(b"i2s8:consumer-source")
DEFAULT_TEXT = "石英股份高纯砂产能同比增长 23.5%"
OLD_DOC_ID = "2026-09-09_legacy_doc_prefix"


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
def service(monkeypatch: pytest.MonkeyPatch) -> CorpusService:
    monkeypatch.setenv("CORPUS_READ_CHAIN", "new")  # 该实验目标无 legacy fallback
    # 工具层经 get_service() 自行取 DSN：守卫 env 里 CORPUS_DSN 是投毒值，
    # 测试把 service.dsn 指向隔离库，使工具走的是被测目标而非投毒串。
    monkeypatch.setattr("plugins.corpus.service.dsn", lambda: DSN)
    return CorpusService(DSN)


@pytest.fixture()
def store() -> PgStore:
    instance = PgStore(DSN, sandbox_db=SANDBOX_DB)
    yield instance
    instance.close()


def _register_source(store: PgStore, source_id: str = SOURCE_ID, decision_id: str = "d1") -> None:
    store.put_source(
        Source(
            source_id=source_id,
            format=DocumentFormat.MARKDOWN,
            mime_type="text/markdown",
            size_bytes=128,
            archive_path=f"ab/{source_id}.md",
            original_names=("consumer.md",),
        )
    )
    store.put_admission(
        Admission(
            decision_id=decision_id,
            source_id=source_id,
            material_type=MaterialType.RESEARCH_REPORT,
            research_domain=ResearchDomain.COMPANY,
            decision=AdmissionDecision.IN_SCOPE,
            policy_rev="v1-20260915",
        )
    )


def _stage_units(
    store: PgStore,
    build_id: str,
    text: str,
    source_id: str = SOURCE_ID,
    decision_id: str = "d1",
) -> None:
    store.put_build(
        Build(
            build_id=build_id,
            source_id=source_id,
            decision_id=decision_id,
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


def _publish(
    store: PgStore,
    *,
    build_id: str,
    text: str = DEFAULT_TEXT,
    source_id: str = SOURCE_ID,
    ranges: tuple[tuple[int, int], ...] = (),
    decision_id: str = "d1",
) -> str:
    """建并发布一个 build，返回 chunk_id。"""
    _register_source(store, source_id, decision_id)
    _stage_units(store, build_id, text, source_id, decision_id)
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
                source_ranges=tuple(CharSpan(start, end) for start, end in ranges),
            )
        ],
        owner_id="w1",
        fence_token=chunked.fence_token,
    )
    store.finish_job(build_id, JobStage.CHUNKED, "w1", chunked.fence_token, NOW, JobState.SUCCEEDED)

    store.register_job(build_id, JobStage.PUBLISHED)
    published = store.acquire_job(build_id, JobStage.PUBLISHED, "w1", NOW, LEASE)
    store.publish(
        source_id, decision_id, build_id, NOW, owner_id="w1", fence_token=published.fence_token
    )
    store.finish_job(
        build_id, JobStage.PUBLISHED, "w1", published.fence_token, NOW, JobState.SUCCEEDED
    )
    return chunk_id


# ── 1. 检索 → 取证 往返（断言读到的是哪个 build）──────────────


def test_search_returns_version_handles_and_fetch_is_verbatim(
    store: PgStore, service: CorpusService
) -> None:
    build_id = sha256_of_bytes(b"i2s8:build:v1")
    chunk_id = _publish(store, build_id=build_id)
    assert service.read_chain() == "new"

    hits = service.search("石英", limit=5)
    assert len(hits) == 1
    hit = hits[0]
    assert hit.doc_id == f"cv2:{build_id}"
    assert hit.locator == f"chunk:{chunk_id}"
    assert (hit.build_id, hit.chunk_id, hit.source_id) == (build_id, chunk_id, SOURCE_ID)
    assert hit.published == "undated"  # 无 report_publication 快照：不伪造日期

    evidence = service.fetch_verbatim(hit.doc_id, hit.locator)
    assert evidence.build_id == build_id
    assert evidence.text == DEFAULT_TEXT  # 逐字原文（非 snippet、非清洗视图）
    assert evidence.units[0].raw_text == DEFAULT_TEXT
    assert evidence.active is True


def test_service_search_applies_selection_policy(store: PgStore, service: CorpusService) -> None:
    """R3 闭环：生产 search 走 perdoc 选择策略（top_k 来源 × 每源块数上限）。

    6 来源 × 2 块全部命中时，无选择策略会返回全部 12 块；接入 ``select_structural``
    后只保留前 ``top_k=5`` 来源的块（10 条），且任何来源不超过 8 块。
    """
    for i in range(6):
        build_id = sha256_of_bytes(f"i2s8:sel:build:{i}".encode())
        source_id = sha256_of_bytes(f"i2s8:sel:source:{i}".encode())
        decision_id = f"sel-d{i}"
        _register_source(store, source_id, decision_id)
        _stage_units(store, build_id, "石英股份高纯砂产能", source_id, decision_id)
        store.register_job(build_id, JobStage.CHUNKED)
        chunked = store.acquire_job(build_id, JobStage.CHUNKED, "w1", NOW, LEASE)
        store.put_chunks(
            build_id,
            [
                Chunk(
                    chunk_id=f"{build_id[:16]}:c{j}",
                    build_id=build_id,
                    kind="paragraph",
                    unit_refs=("u1",),
                    search_text="石英股份高纯砂产能",
                    source_ranges=(),
                )
                for j in range(2)
            ],
            owner_id="w1",
            fence_token=chunked.fence_token,
        )
        store.finish_job(
            build_id, JobStage.CHUNKED, "w1", chunked.fence_token, NOW, JobState.SUCCEEDED
        )
        store.register_job(build_id, JobStage.PUBLISHED)
        published = store.acquire_job(build_id, JobStage.PUBLISHED, "w1", NOW, LEASE)
        store.publish(
            source_id,
            decision_id,
            build_id,
            NOW,
            owner_id="w1",
            fence_token=published.fence_token,
        )
        store.finish_job(
            build_id, JobStage.PUBLISHED, "w1", published.fence_token, NOW, JobState.SUCCEEDED
        )

    hits = service.search("石英", limit=20)
    sources = {hit.source_id for hit in hits}
    assert len(sources) == 5  # top_k=5：第 6 个来源整体挤出
    assert len(hits) == 10  # 5 来源 × 2 块（池 12 ≥ max(limit,40)，选择后截断不生效）
    assert all(sum(1 for hit in hits if hit.source_id == source) <= 8 for source in sources)


def test_unpublished_build_never_in_candidates(store: PgStore, service: CorpusService) -> None:
    _register_source(store)
    draft = sha256_of_bytes(b"i2s8:build:draft")
    _stage_units(store, draft, "石英股份未发布草稿")
    store.register_job(draft, JobStage.CHUNKED)
    chunked = store.acquire_job(draft, JobStage.CHUNKED, "w1", NOW, LEASE)
    store.put_chunks(
        draft,
        [
            Chunk(
                chunk_id=f"{draft[:16]}:c0",
                build_id=draft,
                kind="paragraph",
                unit_refs=("u1",),
                search_text="石英股份未发布草稿",
            )
        ],
        owner_id="w1",
        fence_token=chunked.fence_token,
    )
    assert service.search("石英", limit=5) == []


# ── 2. 跨发布取回原版本（不静默换正文）──────────────────────


def test_old_handle_reads_original_build_after_new_publish(
    store: PgStore, service: CorpusService
) -> None:
    build_a = sha256_of_bytes(b"i2s8:build:v1")
    chunk_a = _publish(store, build_id=build_a, text="石英股份旧版产能 100 万吨")
    build_b = sha256_of_bytes(b"i2s8:build:v2")
    chunk_b = _publish(store, build_id=build_b, text="石英股份新版产能 120 万吨")

    hits = service.search("石英", limit=5)
    assert [hit.build_id for hit in hits] == [build_b]  # 只服务活动版本
    assert hits[0].locator == f"chunk:{chunk_b}"

    old = service.fetch_verbatim(f"cv2:{build_a}", f"chunk:{chunk_a}")
    assert old.build_id == build_a
    assert old.text == "石英股份旧版产能 100 万吨"  # 不回退到新版本正文
    assert old.active is False


def test_cross_build_and_malformed_handle_refused(store: PgStore, service: CorpusService) -> None:
    build_id = sha256_of_bytes(b"i2s8:build:v1")
    chunk_id = _publish(store, build_id=build_id)
    other = sha256_of_bytes(b"i2s8:build:other")
    with pytest.raises(read_pg.UnknownHandleError):
        service.fetch_verbatim(f"cv2:{other}", f"chunk:{chunk_id}")  # chunk 不属于该 build
    with pytest.raises(read_pg.UnknownHandleError):
        service.fetch_verbatim(f"cv2:{build_id}", "3")  # 非 chunk: 句柄
    with pytest.raises(read_pg.UnknownHandleError):
        service.fetch_verbatim(f"cv2:{build_id}", "chunk:")
    with pytest.raises(read_pg.UnknownHandleError):
        service.fetch_verbatim("cv2:not-a-hash", f"chunk:{chunk_id}")


# ── 3. 旧句柄 / 撤销准入：显式拒绝 ──────────────────────────


def test_legacy_handle_is_archive_required(store: PgStore, service: CorpusService) -> None:
    _publish(store, build_id=sha256_of_bytes(b"i2s8:build:v1"))
    with pytest.raises(read_pg.LegacyHandleError):
        service.fetch_verbatim(OLD_DOC_ID, "3")
    assert service.document_text(OLD_DOC_ID) is None  # 不静默换正文：verify 随之 fail-closed

    payload = json.loads(asyncio.run(corpus_fetch.ainvoke({"doc_id": OLD_DOC_ID, "locator": "3"})))
    assert payload["ok"] is False
    assert "archive_required" in payload["error"]


def test_withdrawn_source_handle_refused(store: PgStore, service: CorpusService) -> None:
    build_id = sha256_of_bytes(b"i2s8:build:v1")
    chunk_id = _publish(store, build_id=build_id)
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
    store.retire(SOURCE_ID, "d2", NOW)  # 撤销：活动指针置空

    with pytest.raises(read_pg.WithdrawnError):
        service.fetch_verbatim(f"cv2:{build_id}", f"chunk:{chunk_id}")
    assert service.search("石英", limit=5) == []


# ── 4. 工具层载荷与 coverage 三轴 ───────────────────────────


def test_corpus_search_tool_payload_has_handles_and_coverage(
    store: PgStore, service: CorpusService
) -> None:
    build_id = sha256_of_bytes(b"i2s8:build:v1")
    chunk_id = _publish(store, build_id=build_id)
    payload = json.loads(asyncio.run(corpus_search.ainvoke({"query": "石英", "limit": 5})))
    assert payload["ok"] is True and payload["count"] == 1
    hit = payload["hits"][0]
    assert hit["doc_id"] == f"cv2:{build_id}" and hit["locator"] == f"chunk:{chunk_id}"
    assert payload["coverage"]["query_status"] == "matched"
    assert payload["coverage"]["processing"] in ("full", "scoped")

    fetched = json.loads(
        asyncio.run(corpus_fetch.ainvoke({"doc_id": hit["doc_id"], "locator": hit["locator"]}))
    )
    assert fetched["ok"] is True
    assert fetched["text"] == DEFAULT_TEXT
    assert fetched["build_id"] == build_id and fetched["chunk_id"] == chunk_id


def test_empty_search_is_no_match_not_absent(store: PgStore, service: CorpusService) -> None:
    _publish(store, build_id=sha256_of_bytes(b"i2s8:build:v1"))
    payload = json.loads(
        asyncio.run(corpus_search.ainvoke({"query": "完全不相干的检索词", "limit": 5}))
    )
    assert payload["ok"] is True and payload["count"] == 0
    coverage = payload["coverage"]
    assert coverage["query_status"] == "no_match"
    assert coverage["availability"] == "unknown"  # 不把 no_match 自动当 absent
    assert "当前已发布范围" in payload["hint"]


def test_coverage_unknown_when_admission_pending(store: PgStore, service: CorpusService) -> None:
    _publish(store, build_id=sha256_of_bytes(b"i2s8:build:v1"))
    pending_id = sha256_of_bytes(b"i2s8:pending-source")
    store.put_source(
        Source(
            source_id=pending_id,
            format=DocumentFormat.MARKDOWN,
            mime_type="text/markdown",
            size_bytes=64,
            archive_path=f"ab/{pending_id}.md",
            original_names=("pending.md",),
        )
    )
    coverage = read_pg.coverage_snapshot(DSN, sandbox_db=SANDBOX_DB)
    assert coverage["processing"] == "unknown"  # 未决优先于 scoped/full
    assert "admission_pending" in coverage["reason_codes"]
    assert coverage["counts"]["pending"] == 1


# ── 5. verify 的 source_resolver 走新链 ────────────────────


def test_verify_source_resolver_reads_new_chain_only(
    store: PgStore, service: CorpusService
) -> None:
    build_id = sha256_of_bytes(b"i2s8:build:v1")
    _publish(store, build_id=build_id, text="石英股份产能 100 万吨")
    resolver = service.source_resolver()
    assert resolver(f"cv2:{build_id}") == "石英股份产能 100 万吨"
    assert resolver(OLD_DOC_ID) is None  # 旧句柄不给正文：溯源闸 fail-closed


# ── 6. audit 读侧迁移：新链完整性检查 ──────────────────────


def test_audit_corpus_chain_flags_integrity_gaps(store: PgStore) -> None:
    from plugins.corpus.audit import audit_corpus_chain

    build_id = sha256_of_bytes(b"i2s8:build:v1")
    _publish(store, build_id=build_id)
    with psycopg.connect(DSN, autocommit=True) as conn:
        clean = audit_corpus_chain(conn)
    assert clean["available"] is True and clean["conflicts"] == []
    assert clean["counts"]["active"] == 1
    assert clean["counts"]["chunks"] == 1

    # 制造缺口：新排除决定已移动准入指针，但活动指针尚未撤下（撤销未落地）
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
    with psycopg.connect(DSN, autocommit=True) as conn:
        dirty = audit_corpus_chain(conn)
    assert "published_decision_not_in_scope" in dirty["conflicts"]

    store.retire(SOURCE_ID, "d2", NOW)
    with psycopg.connect(DSN, autocommit=True) as conn:
        settled = audit_corpus_chain(conn)
    assert settled["conflicts"] == []


# ── 7. I2-8/I2-4 独立复核整改回归（RM-I28-*）────────────────


def test_document_level_reads_handle_build_across_publish(
    store: PgStore, service: CorpusService
) -> None:
    """RM-I28-1（裁定 A）：文档级读取遵循**句柄绑定 build**，且 build_id 与正文自洽。

    修复前：`fetch_document` 读活动 build（B），却把 `build_id` 填成句柄的 A。
    """
    build_a = sha256_of_bytes(b"i2s8:build:doc:a")
    chunk_a = _publish(store, build_id=build_a, text="石英股份旧版产能 100 万吨")
    build_b = sha256_of_bytes(b"i2s8:build:doc:b")
    _publish(store, build_id=build_b, text="石英股份新版产能 120 万吨")

    doc = read_pg.fetch_document(DSN, f"cv2:{build_a}", sandbox_db=SANDBOX_DB)
    assert doc.text == "石英股份旧版产能 100 万吨"  # 不静默换活动版本正文
    assert doc.build_id == build_a and doc.source_id == SOURCE_ID

    # service 的文档级读取与 verify 的 resolver 同源同语义
    assert service.document_text(f"cv2:{build_a}") == "石英股份旧版产能 100 万吨"
    assert service.source_resolver()(f"cv2:{build_a}") == "石英股份旧版产能 100 万吨"
    # 块级语义未被改动（不动项）
    assert service.fetch_verbatim(f"cv2:{build_a}", f"chunk:{chunk_a}").text == (
        "石英股份旧版产能 100 万吨"
    )


def test_retired_document_read_is_none_and_empty_doc_is_distinguishable(
    store: PgStore, service: CorpusService
) -> None:
    """RM-I28-2：撤销 → None（与块级 WithdrawnError 同族的拒绝信号），不得返回空串；
    合法空文档（零单元 build）仍返回 ""——两者必须可区分。"""
    empty_build = sha256_of_bytes(b"i2s8:build:empty")
    _register_source(store)
    store.put_build(_empty_build_row(empty_build))
    assert service.document_text(f"cv2:{empty_build}") == ""  # 合法空文档

    build_id = sha256_of_bytes(b"i2s8:build:retired-doc")
    _publish(store, build_id=build_id, text="石英股份产能 100 万吨")
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

    assert service.document_text(f"cv2:{build_id}") is None  # 撤销：显式不可服务
    assert service.source_resolver()(f"cv2:{build_id}") is None
    with pytest.raises(read_pg.WithdrawnError):
        read_pg.fetch_document(DSN, f"cv2:{build_id}", sandbox_db=SANDBOX_DB)


def _empty_build_row(build_id: str) -> Build:
    return Build(
        build_id=build_id,
        source_id=SOURCE_ID,
        decision_id="d1",
        parse_rev="parse-test",
        clean_rev="clean-test",
        chunk_rev="chunk-test",
        index_rev=INDEX_REV_V3,
        quality_report='{"gap_regions": [], "oversized_chunks": []}',
    )


def test_coverage_three_refs_and_snapshot_moves_with_publication(store: PgStore) -> None:
    """RM-I28-3：§7.3 必带三 ref；publication_snapshot_ref 随发布/撤销变化、无变化时稳定。"""
    build_id = sha256_of_bytes(b"i2s8:build:cov")
    _register_source(store)
    store.put_build(_empty_build_row(build_id))
    before = read_pg.coverage_snapshot(DSN, sandbox_db=SANDBOX_DB)
    for key in ("requested_scope_ref", "effective_scope_ref", "publication_snapshot_ref"):
        assert before[key], f"coverage 缺 §7.3 必带字段 {key}"

    _publish(store, build_id=build_id, text="石英股份产能 100 万吨")
    published = read_pg.coverage_snapshot(DSN, sandbox_db=SANDBOX_DB, query_status="matched")
    assert published["publication_snapshot_ref"] != before["publication_snapshot_ref"]
    stable = read_pg.coverage_snapshot(DSN, sandbox_db=SANDBOX_DB, query_status="matched")
    assert stable["publication_snapshot_ref"] == published["publication_snapshot_ref"]

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
    retired = read_pg.coverage_snapshot(DSN, sandbox_db=SANDBOX_DB)
    assert retired["publication_snapshot_ref"] != published["publication_snapshot_ref"]


def test_search_and_coverage_share_one_snapshot_under_concurrent_publish(
    store: PgStore, service: CorpusService
) -> None:
    """RM-I28-3：并发发布期间，命中与覆盖必须来自同一快照——不得出现
    「coverage 说零已发布来源，却返回了命中」这种拼接自两个时刻的结果。"""
    import threading

    build_id = sha256_of_bytes(b"i2s8:build:snapshot")
    _publish(store, build_id=build_id, text="石英股份产能 100 万吨")
    stop = threading.Event()

    def flip() -> None:
        worker = PgStore(DSN, sandbox_db=SANDBOX_DB)
        try:
            while not stop.is_set():
                worker.retire(SOURCE_ID, "d1", NOW)
                worker.publish(
                    SOURCE_ID,
                    "d1",
                    build_id,
                    NOW,
                    owner_id="w1",
                    fence_token="flip-token",
                )
        except Exception:
            pass  # 竞态收尾异常不影响被断言的快照不变量
        finally:
            worker.close()

    flipper = threading.Thread(target=flip, daemon=True)
    flipper.start()
    try:
        for _ in range(40):
            hits, coverage = read_pg.search_with_coverage(DSN, "石英", sandbox_db=SANDBOX_DB)
            if hits:
                assert coverage["counts"]["published"] >= 1, (
                    "命中与覆盖来自不同快照：hits 非空但 coverage 报零已发布来源"
                )
                assert coverage["query_status"] == "matched"
    finally:
        stop.set()
        flipper.join(timeout=10)
    assert not flipper.is_alive()


def test_fetch_spans_recompute_text_and_do_not_fabricate(
    store: PgStore, service: CorpusService
) -> None:
    """RM-I28-5：工具载荷透出 span；spans 可复算出 text；空引用 chunk 不伪造区间。"""
    build_id = sha256_of_bytes(b"i2s8:build:span")
    chunk_id = _publish(store, build_id=build_id, text="石英股份产能 100 万吨", ranges=((0, 13),))
    evidence = service.fetch_verbatim(f"cv2:{build_id}", f"chunk:{chunk_id}")
    rebuilt = "\n".join(evidence.text[start:end] for _unit_id, start, end in evidence.spans)
    assert rebuilt == evidence.text
    assert evidence.spans == (("u1", 0, len("石英股份产能 100 万吨")),)
    # 权威原文 code point 区间由 chunk 投影携带并原样透出（§4.2）
    assert evidence.source_ranges == ((0, 13),)

    payload = json.loads(
        asyncio.run(
            corpus_fetch.ainvoke({"doc_id": f"cv2:{build_id}", "locator": f"chunk:{chunk_id}"})
        )
    )
    assert payload["ok"] is True
    assert payload["spans"] == [{"unit_id": "u1", "start": 0, "end": 13}]
    assert payload["source_ranges"] == [[0, 13]]

    # 引用悬空（I2-6 authority 口径）：完整性错误必须显式拒绝，不得返回"其余部分"，
    # 也不得伪造区间或空正文冒充合法结果。
    dangling_build = sha256_of_bytes(b"i2s8:build:no-refs")
    _register_source(store)
    store.put_build(_empty_build_row(dangling_build))
    store.register_job(dangling_build, JobStage.CHUNKED)
    chunked = store.acquire_job(dangling_build, JobStage.CHUNKED, "w1", NOW, LEASE)
    store.put_chunks(
        dangling_build,
        [
            Chunk(
                chunk_id=f"{dangling_build[:16]}:none",
                build_id=dangling_build,
                kind="paragraph",
                # 契约禁止空 unit_refs；此处引用不存在的单元 ⇒ 权威集合不完整
                unit_refs=("u-missing",),
                search_text="占位",
            )
        ],
        owner_id="w1",
        fence_token=chunked.fence_token,
    )
    with pytest.raises(read_pg.IntegrityError, match="不存在的单元"):
        service.fetch_verbatim(f"cv2:{dangling_build}", f"chunk:{dangling_build[:16]}:none")


def test_read_chain_legacy_refused_on_migrated_target(
    store: PgStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RM-I28-8（裁定 A）：迁移目标上 legacy 读路径不可达——请求即拒绝，
    不存在「新库静默降级读旧 blocks」这条路径（M5「无 legacy fallback」可自证）。"""
    monkeypatch.setattr("plugins.corpus.service.dsn", lambda: DSN)
    monkeypatch.setenv("CORPUS_READ_CHAIN", "legacy")
    account = CorpusService(DSN)
    with pytest.raises(StoreError, match="拒绝"):
        account.read_chain()
    with pytest.raises(StoreError, match="拒绝"):
        account.search("石英", limit=5)


def test_read_chain_new_refused_without_corpus_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """RM-I28-8：反向fail-closed——目标库没有 corpus schema 时不得假装新链。"""
    legacy_like = DSN.replace(f"/{SANDBOX_DB}", "/postgres")
    assert legacy_like != DSN
    monkeypatch.setenv("CORPUS_READ_CHAIN", "new")
    account = CorpusService(legacy_like)
    with pytest.raises(StoreError, match="拒绝"):
        account.read_chain()


def test_data_coverage_tool_passes_three_axis_research_coverage(
    store: PgStore, service: CorpusService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RM-I28-4：消费者矩阵 [11] —— data_coverage 透出 §7.3 三轴（与市场字段分层）。"""
    import importlib

    # 工具在 plugins.tools.__init__ 里被绑定成 Tool，需取模块真身才能打桩内部依赖
    data_coverage_module = importlib.import_module("plugins.tools.data_coverage")
    data_coverage = data_coverage_module.data_coverage
    # 市场侧桩成不可用：本用例只验证研报侧三轴透出与市场字段分层，不发真实网络请求
    monkeypatch.setattr(data_coverage_module, "build_service", lambda: None)
    _publish(store, build_id=sha256_of_bytes(b"i2s8:build:dc"), text="石英股份产能 100 万吨")
    payload = json.loads(asyncio.run(data_coverage.ainvoke({"query": "石英股份"})))
    assert payload["ok"] is True
    research = payload["research_coverage"]
    for key in ("requested_scope_ref", "effective_scope_ref", "publication_snapshot_ref"):
        assert research[key], f"research_coverage 缺 {key}"
    assert research["query_status"] == "matched"
    assert research["counts"]["published"] >= 1
    # 市场侧结构未被改变（不动项）
    assert set(payload["coverage"]) >= {"research", "quote", "financials", "web"}
    assert payload["coverage"]["research"]["available"] is True
