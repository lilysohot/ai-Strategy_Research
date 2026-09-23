"""I2-6 authority 族（真库）：所有消费者接**同一权威 Interface**，坏副本/错 cell/跨 build/坏哈希拒绝。

依据：架构 §12.2 ``authority`` 族（篡改 JSONB 副本、错误 cell、跨 build、未知 unit、坏哈希、
清洗拼接伪引文、导出清单不可信 → fetch/verify 同一权威 Interface 拒绝）+ tasks.md I2-6 验收门
（旧来源路径不能兜底）。

运行条件：``CORPUS_I2_DSN`` → ``i2_sandbox_corpus``（i2-verify 守卫 env）；无 DSN 模块级跳过。
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
    UnitLocation,
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
NOW = datetime(2026, 9, 18, 14, tzinfo=UTC)
SOURCE_ID = sha256_of_bytes(b"i2s6:authority-source")
#: 权威原文（双空格）+ 清洗视图（单空格）：引用必须逐字来自前者
RAW_TEXT = "石英股份  产能 100 万吨"
CLEAN_TEXT = "石英股份 产能 100 万吨"


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


def _raw_sql(query: str, params: tuple = ()) -> list[tuple]:
    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(query, params)
        return list(cur.fetchall())


def _register_source(store: PgStore, source_id: str = SOURCE_ID) -> None:
    store.put_source(
        Source(
            source_id=source_id,
            format=DocumentFormat.MARKDOWN,
            mime_type="text/markdown",
            size_bytes=128,
            archive_path=f"ab/{source_id}.md",
            original_names=("authority.md",),
        )
    )
    store.put_admission(
        Admission(
            decision_id="d1",
            source_id=source_id,
            material_type=MaterialType.RESEARCH_REPORT,
            research_domain=ResearchDomain.COMPANY,
            decision=AdmissionDecision.IN_SCOPE,
            policy_rev="v1-20260915",
        )
    )


def _stage_unit(
    store: PgStore,
    build_id: str,
    *,
    unit_id: str = "u1",
    raw_text: str = RAW_TEXT,
    clean_view: str | None = CLEAN_TEXT,
    cells: tuple[tuple[int, int], ...] = ((0, 1),),
    page: int | None = 1,
    source_id: str = SOURCE_ID,
) -> Unit:
    unit = Unit(
        unit_id=unit_id,
        build_id=build_id,
        kind="table_row",
        raw_text=raw_text,
        content_hash=sha256_of_bytes(raw_text.encode()),
        ordinal=1,
        location=UnitLocation(page=page, element="tbl0", cells=cells),
        clean_view=clean_view or "",
        status=UnitStatus.KEPT,
    )
    store.put_build(
        Build(
            build_id=build_id,
            source_id=source_id,
            decision_id="d1",
            parse_rev="parse-test",
            clean_rev="clean-test",
            chunk_rev="chunk-test",
            index_rev=INDEX_REV_V3,
            quality_report='{"gap_regions": [], "oversized_chunks": []}',
        )
    )
    store.register_job(build_id, JobStage.PARSED)
    parsed = store.acquire_job(build_id, JobStage.PARSED, "w1", NOW, LEASE)
    store.put_units(build_id, [unit], owner_id="w1", fence_token=parsed.fence_token)
    store.finish_job(build_id, JobStage.PARSED, "w1", parsed.fence_token, NOW, JobState.SUCCEEDED)
    return unit


def _publish(
    store: PgStore,
    *,
    build_id: str,
    unit_refs: tuple[str, ...] = ("u1",),
    ranges: tuple[tuple[int, int], ...] = ((0, 16),),
    source_id: str = SOURCE_ID,
) -> str:
    _register_source(store, source_id)
    _stage_unit(store, build_id, source_id=source_id)
    chunk_id = f"{build_id[:16]}:c0"
    store.register_job(build_id, JobStage.CHUNKED)
    chunked = store.acquire_job(build_id, JobStage.CHUNKED, "w1", NOW, LEASE)
    store.put_chunks(
        build_id,
        [
            Chunk(
                chunk_id=chunk_id,
                build_id=build_id,
                kind="table_row",
                unit_refs=unit_refs,
                search_text=RAW_TEXT,
                source_ranges=tuple(CharSpan(start, end) for start, end in ranges),
            )
        ],
        owner_id="w1",
        fence_token=chunked.fence_token,
    )
    store.finish_job(build_id, JobStage.CHUNKED, "w1", chunked.fence_token, NOW, JobState.SUCCEEDED)
    store.register_job(build_id, JobStage.PUBLISHED)
    published = store.acquire_job(build_id, JobStage.PUBLISHED, "w1", NOW, LEASE)
    store.publish(source_id, "d1", build_id, NOW, owner_id="w1", fence_token=published.fence_token)
    store.finish_job(
        build_id, JobStage.PUBLISHED, "w1", published.fence_token, NOW, JobState.SUCCEEDED
    )
    return chunk_id


# ── 1. 同一权威 Interface：所有消费者读出同一份 raw_text ────────


def test_all_consumers_read_same_authoritative_units(
    store: PgStore, service: CorpusService
) -> None:
    build_id = sha256_of_bytes(b"i2s6:build:authority")
    chunk_id = _publish(store, build_id=build_id)

    # 权威集合（直接读 corpus_units，作为 ground truth）
    authoritative = _raw_sql(
        "SELECT raw_text FROM corpus.corpus_units WHERE build_id = %s ORDER BY ordinal",
        (build_id,),
    )
    ground_truth = "\n".join(str(row[0]) for row in authoritative)
    assert ground_truth == RAW_TEXT

    handle = f"cv2:{build_id}"
    assert service.fetch_verbatim(handle, f"chunk:{chunk_id}").text == ground_truth
    compat = service.fetch(handle, f"chunk:{chunk_id}")
    assert compat is not None and compat.text == ground_truth
    assert service.document_text(handle) == ground_truth
    assert service.source_resolver()(handle) == ground_truth
    assert service.fetch_cell(handle, row=0, col=1, page=1).raw_text == ground_truth

    hit = json.loads(asyncio.run(corpus_search.ainvoke({"query": "石英", "limit": 5})))["hits"][0]
    payload = json.loads(
        asyncio.run(corpus_fetch.ainvoke({"doc_id": hit["doc_id"], "locator": hit["locator"]}))
    )
    assert payload["text"] == ground_truth
    assert payload["build_id"] == build_id


# ── 2. 坏哈希 / 篡改正文：同一 Interface 拒绝 ──────────────────


def test_tampered_unit_content_refused(store: PgStore, service: CorpusService) -> None:
    build_id = sha256_of_bytes(b"i2s6:build:tamper")
    chunk_id = _publish(store, build_id=build_id)
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE corpus.corpus_units SET raw_text = %s WHERE build_id = %s AND unit_id = 'u1'",
            ("被篡改的正文 999 亿元", build_id),
        )

    with pytest.raises(read_pg.IntegrityError, match="哈希不符"):
        service.fetch_verbatim(f"cv2:{build_id}", f"chunk:{chunk_id}")
    with pytest.raises(read_pg.IntegrityError, match="哈希不符"):
        service.fetch_cell(f"cv2:{build_id}", row=0, col=1, page=1)
    # 文档级不静默换正文：无法取证即 None（verify 随之 fail-closed）
    assert service.document_text(f"cv2:{build_id}") is None


def test_missing_referenced_unit_refused(store: PgStore, service: CorpusService) -> None:
    build_id = sha256_of_bytes(b"i2s6:build:missing-unit")
    chunk_id = _publish(store, build_id=build_id, unit_refs=("u1", "u-missing"))
    with pytest.raises(read_pg.IntegrityError, match="不存在的单元"):
        service.fetch_verbatim(f"cv2:{build_id}", f"chunk:{chunk_id}")


# ── 3. 错 cell / 跨 build：拒绝 ───────────────────────────────


def test_wrong_cell_refused_and_correct_cell_returned(
    store: PgStore, service: CorpusService
) -> None:
    build_id = sha256_of_bytes(b"i2s6:build:cell")
    _publish(store, build_id=build_id)
    handle = f"cv2:{build_id}"

    right = service.fetch_cell(handle, row=0, col=1, page=1)
    assert right.raw_text == RAW_TEXT and right.cells == ((0, 1),)
    with pytest.raises(read_pg.UnknownHandleError, match=r"错 cell|不含坐标"):
        service.fetch_cell(handle, row=9, col=9, page=1)
    with pytest.raises(read_pg.UnknownHandleError):
        service.fetch_cell(handle, row=0, col=1, page=7)  # 页不匹配


def test_cross_build_and_unknown_handles_refused(store: PgStore, service: CorpusService) -> None:
    build_a = sha256_of_bytes(b"i2s6:build:a")
    chunk_a = _publish(store, build_id=build_a)
    build_b = sha256_of_bytes(b"i2s6:build:b")
    _publish(store, build_id=build_b)

    with pytest.raises(read_pg.UnknownHandleError):
        service.fetch_verbatim(f"cv2:{build_b}", f"chunk:{chunk_a}")  # 跨 build
    with pytest.raises(read_pg.UnknownHandleError):
        service.fetch_verbatim(f"cv2:{'f' * 64}", f"chunk:{chunk_a}")  # 坏哈希/未知 build
    with pytest.raises(read_pg.LegacyHandleError):
        service.fetch_verbatim("2026-09-09_legacy", "chunk:x")  # 旧句柄不兜底


# ── 4. 清洗视图 / 检索展示不是权威（逐字比对抓伪引文）──────────


def test_cleaned_view_and_search_text_are_not_authoritative(
    store: PgStore, service: CorpusService
) -> None:
    from plugins.corpus.strategy_schema import build_strategy_card, dump_strategy_json
    from plugins.corpus.verify import verify_card
    from plugins.tools.position_sizing import position_sizing
    from plugins.tools.strategy_lint import strategy_lint

    build_id = sha256_of_bytes(b"i2s6:build:clean")
    _publish(store, build_id=build_id)
    handle = f"cv2:{build_id}"

    def card_with(quote: str) -> dict:
        sizing = json.loads(
            asyncio.run(
                position_sizing.func(
                    capital_total=1_000_000,
                    risk_budget_pct=2.0,
                    entry_low=100.0,
                    entry_high=110.0,
                    stop_loss=95.0,
                )
            )
        )
        card = build_strategy_card(
            symbol="X.SH",
            thesis="authority 校验",
            evidence=[{"source_ref": handle, "page": "1", "quote": quote, "kind": "fact"}],
            entry_low=100.0,
            entry_high=110.0,
            stop_loss=95.0,
            target=120.0,
            invalidation="跌破关键位",
            horizon="1-3M",
            capital_total=1_000_000,
            sizing=sizing,
            sources=[{"id": handle, "title": "权威来源", "url": ""}],
        )
        card["lint"] = json.loads(asyncio.run(strategy_lint.func(dump_strategy_json(card))))
        return card

    resolver = service.source_resolver()
    # 清洗视图（单空格）不是权威：逐字比对必须失败
    assert verify_card(card_with(CLEAN_TEXT), source_resolver=resolver)["passed"] is False
    # 检索展示文本（search_text 经 %/空白归一化）同样不是权威
    normalized = service.search("石英", limit=1)[0].snippet.strip()
    if normalized and normalized != RAW_TEXT:
        assert verify_card(card_with(normalized), source_resolver=resolver)["passed"] is False
    # 权威原文（双空格）逐字引用 → 通过
    ok = verify_card(card_with(RAW_TEXT), source_resolver=resolver)
    assert ok["passed"] is True and ok["traceability"]["rate"] == 1.0


# ── 5. JSONB 副本 / 导出件必须与权威集合一致 ─────────────────


def test_evidence_copy_inconsistent_with_authority_refused(
    store: PgStore, service: CorpusService
) -> None:
    from plugins.corpus.evidence_pipeline import build_evidence_run_from_units

    build_id = sha256_of_bytes(b"i2s6:build:copy")
    _publish(store, build_id=build_id)

    good = build_evidence_run_from_units(SOURCE_ID, [{"locator": "1", "text": RAW_TEXT}])
    service.save_evidence_run(good)
    assert service.load_evidence_run(good.run_id).run_id == good.run_id  # 一致副本可读

    # 自洽但内容与权威集合不符的副本（例如被改写后重算 run_id 的导出件）
    forged = build_evidence_run_from_units(
        SOURCE_ID, [{"locator": "1", "text": "石英股份产能 999 万吨（伪造）"}]
    )
    service.save_evidence_run(forged)
    with pytest.raises(read_pg.IntegrityError, match="与权威集合不一致"):
        service.load_evidence_run(forged.run_id)


def test_audit_flags_chunk_with_dangling_unit_reference(store: PgStore) -> None:
    """审计读侧同样以权威集合为准：悬空引用必须被看见（不自相矛盾地"看起来可用"）。"""
    from plugins.corpus.audit import audit_corpus_chain

    build_id = sha256_of_bytes(b"i2s6:build:audit")
    _publish(store, build_id=build_id)
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE corpus.corpus_chunks SET unit_refs = ARRAY['u-missing'] WHERE build_id = %s",
            (build_id,),
        )
    with psycopg.connect(DSN, autocommit=True) as conn:
        report = audit_corpus_chain(conn)
    assert "published_chunk_references_missing_unit" in report["conflicts"]
