"""D2 P6 验收：文档级元数据派生与入库（d2-claims-design §3.5 可得子集）。

覆盖：org / analysts / published 三层日期回退的正则口径（全部来自 78 份语料实测）、
subject 只给 company 的纪律、refresh_metadata 的幂等与 published 只回填 NULL、
老库迁移（掉列后 init_db 恢复）、ingest 挂钩（新文档入即物化）。

隔离方式与 ``test_corpus_claims.py`` 一致：临时 schema，PG 不可用则 skip。
纯规则派生，全程 0 LLM。
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

import psycopg
import pytest

from plugins.corpus.metadata import (
    derive_analysts,
    derive_metadata,
    derive_org,
    derive_published,
)
from plugins.corpus.service import CorpusService, dsn

SCRATCH_SCHEMA = "corpus_d6meta"


def _scratch_url(admin: str, schema: str = SCRATCH_SCHEMA) -> str:
    from urllib.parse import quote

    options = quote(f"-c search_path={schema},public")
    sep = "&" if "?" in admin else "?"
    return f"{admin}{sep}options={options}"


@pytest.fixture(scope="module")
def meta_dsn():
    admin = dsn()
    try:
        psycopg.connect(admin, connect_timeout=5).close()
    except psycopg.OperationalError as exc:  # pragma: no cover - 环境相关
        pytest.skip(f"PG 不可用，跳过 D6 元数据测试：{exc}")

    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP SCHEMA IF EXISTS "{SCRATCH_SCHEMA}" CASCADE')
        conn.execute(f'CREATE SCHEMA "{SCRATCH_SCHEMA}"')
    url = _scratch_url(admin)
    CorpusService(url).init_db()
    _seed(url)
    try:
        yield url
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{SCRATCH_SCHEMA}" CASCADE')


I2_SANDBOX_DB = "i2_sandbox_corpus"
_I2_TABLES = (
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


@pytest.fixture()
def i2_dsn():
    """I2 演练环境守卫：``CORPUS_I2_DSN`` 指向隔离库才运行；用例前清 corpus 表。"""
    sandbox_dsn = os.environ.get("CORPUS_I2_DSN", "")
    if not sandbox_dsn:
        pytest.skip("CORPUS_I2_DSN 未设置（非 I2 演练环境）")
    with psycopg.connect(sandbox_dsn, autocommit=True) as conn:
        row = conn.execute("SELECT current_database()").fetchone()
        dbs = {r[0] for r in conn.execute("SELECT datname FROM pg_database WHERE datallowconn")}
        if row is None or row[0] != I2_SANDBOX_DB or "apodex" in dbs:
            pytest.fail(f"CORPUS_I2_DSN 未指向隔离演练库 {I2_SANDBOX_DB}（拒绝运行）")
        conn.execute("TRUNCATE " + ", ".join(f"corpus.{t}" for t in _I2_TABLES))
    yield sandbox_dsn


def _seed(url: str) -> None:
    """三份文档：日期标题券商研报 / undated 首块带日期 / published 已填不许覆盖。"""
    docs = [
        # doc_id, title, override, published(NULL=等回填)
        (
            "2026-08-17_c195233b",
            "2026.08.17-国信证券-张向伟-王新雨-公司研究-业绩点评-贵州茅台-600519-增长",
            None,
            None,
        ),
        ("undated_03920926", "0908脱水研报", "macro", None),
        (
            "2026-01-01_deadbeef",
            "2026.08.13-长江证券-国内研报-长江证券-化工专题",
            None,
            "2026-01-01",
        ),
    ]
    blocks = {
        "2026-08-17_c195233b": [
            "分析师：张向伟（执业S1130525060002）",
            "贵州茅台（600519.SH）2026H1 营业收入 1741 亿元。",
        ],
        "undated_03920926": ["2026/09/08 摘要：市场普遍下跌。", "正文无更多日期。"],
        "2026-01-01_deadbeef": ["化工行业景气投资十问十答。"],
    }
    with psycopg.connect(url, autocommit=True) as conn:
        for doc_id, title, override, published in docs:
            conn.execute(
                "INSERT INTO documents (doc_id, title, source_path, content_hash, mime,"
                " status, block_count, doc_kind_override, published)"
                " VALUES (%s, %s, %s, %s, 'text/markdown', 'ok', %s, %s, %s)",
                (
                    doc_id,
                    title,
                    f"/tmp/{doc_id}.md",
                    f"hash-{doc_id}",
                    len(blocks[doc_id]),
                    override,
                    published,
                ),
            )
            for seq, text in enumerate(blocks[doc_id], start=1):
                conn.execute(
                    "INSERT INTO blocks (doc_id, seq, locator, text) VALUES (%s, %s, %s, %s)",
                    (doc_id, seq, f"p{seq}", text),
                )


# ── 派生函数（纯规则，无 PG） ────────────────────────────────────
def test_derive_org_from_title_segment() -> None:
    assert derive_org("2026.08.17-国信证券-张向伟-公司研究-贵州茅台-600519") == "国信证券"
    assert derive_org("2026.08.16-jpmorgan-摩根大通-中国人工智能") == "jpmorgan"
    # 非日期标题（博客/自媒体）：实测首块机构词全为误报，org 不回退首块
    assert derive_org("James-Bulltard_83126 复盘") is None
    assert derive_org("") is None


def test_derive_analysts_strips_sac_number() -> None:
    assert derive_analysts("分析师：张向伟（执业S1130525060002）\n其他") == ["张向伟"]
    assert derive_analysts("分析师：李浩(S0210524050003)") == ["李浩"]
    assert derive_analysts("分析师：赵格格") == ["赵格格"]
    assert derive_analysts("免责声明：本报告…") == []
    assert derive_analysts(None) == []


def test_derive_published_uses_explicit_text_only() -> None:
    # §4.3/design-review：doc_id 前缀派生废弃——签名已无 doc_id，句柄不再是依据
    assert derive_published("无题", None) is None
    # 标题日期
    assert derive_published("2026.08.16-华创证券-贵州茅台", None) == date(2026, 8, 16)
    # 首块正文日期（含中文日期，且 08 月不补零也能解析）
    assert derive_published("0908脱水研报", "2026/09/08 摘要") == date(2026, 9, 8)
    assert derive_published("投委会报告", "2026年08月31 通过") == date(2026, 8, 31)
    # 非法日期不算命中；全无来源返回 None
    assert derive_published("无题", "2026/13/45 是假日期，2026/09/08 是真的") == date(2026, 9, 8)
    assert derive_published("无题", "没有任何日期") is None


def test_derive_metadata_subject_only_for_company() -> None:
    texts = ["贵州茅台（600519.SH）2026H1 营业收入 1741 亿元。"]
    meta = derive_metadata("2026.08.17-国信证券-公司研究-贵州茅台-600519", texts)
    assert meta["doc_kind"] == "company"
    assert meta["subject"] == "600519.SH"
    assert meta["org"] == "国信证券"
    # industry/macro 的主体编码在 metric 前缀里，subject 给错比缺失更危险
    macro = derive_metadata("0908脱水研报", ["市场下跌。"], "macro")
    assert macro["doc_kind"] == "macro" and macro["subject"] is None
    assert macro["org"] is None


# ── refresh_metadata（scratch PG） ───────────────────────────────
def _row(url: str, doc_id: str) -> dict[str, object]:
    with psycopg.connect(url, row_factory=psycopg.rows.dict_row) as conn:
        return conn.execute(
            "SELECT doc_kind, subject, org, analysts, published FROM documents WHERE doc_id = %s",
            (doc_id,),
        ).fetchone()


def test_refresh_metadata_fills_all_fields(meta_dsn: str) -> None:
    stats = CorpusService(meta_dsn).refresh_metadata()
    assert stats["docs"] == 3
    assert stats["org_filled"] == 2  # 国信证券 + 长江证券
    assert stats["analysts_filled"] == 1  # 仅茅台研报首块有"分析师："
    assert stats["subject_filled"] == 1  # subject 只给 company
    assert stats["published_backfilled"] == 2  # ① 标题日期 + ② 首块日期；③ 已有值不补

    r1 = _row(meta_dsn, "2026-08-17_c195233b")
    assert (r1["doc_kind"], r1["subject"], r1["org"]) == ("company", "600519.SH", "国信证券")
    assert r1["analysts"] == ["张向伟"]
    # ③ published 已有值（ingest 事实）：不被标题日期 2026-08-13 覆盖
    r3 = _row(meta_dsn, "2026-01-01_deadbeef")
    assert r3["published"] == date(2026, 1, 1)
    assert (r3["doc_kind"], r3["org"]) == ("industry", "长江证券")


def test_refresh_metadata_is_idempotent(meta_dsn: str) -> None:
    stats = CorpusService(meta_dsn).refresh_metadata()
    assert stats["published_backfilled"] == 0  # 首轮已回填，二轮无 NULL 可补
    assert _row(meta_dsn, "undated_03920926")["published"] == date(2026, 9, 8)


def test_refresh_metadata_doc_scope(meta_dsn: str) -> None:
    stats = CorpusService(meta_dsn).refresh_metadata(["undated_03920926"])
    assert stats["docs"] == 1 and stats["org_filled"] == 0


def test_init_db_restores_dropped_columns(meta_dsn: str) -> None:
    """老库迁移幂等：掉列后 init_db 必须能补回列（P5 备份覆盖率检查的同类事故）。

    列被 DROP 后数据自然丢失——但派生是**从源数据可复现的**，重跑 refresh_metadata
    即可复原，这正是元数据"只存派生值、源数据在 blocks"的设计收益。
    """
    with psycopg.connect(meta_dsn, autocommit=True) as conn:
        conn.execute("ALTER TABLE documents DROP COLUMN org")
        conn.execute("ALTER TABLE documents DROP COLUMN analysts")
    CorpusService(meta_dsn).init_db()
    assert _row(meta_dsn, "2026-08-17_c195233b")["org"] is None  # 列回来了，值等重派生
    CorpusService(meta_dsn).refresh_metadata()
    assert _row(meta_dsn, "2026-08-17_c195233b")["org"] == "国信证券"


def test_backup_columns_cover_new_fields() -> None:
    """§5.1 ⚠️ 教训：documents 加列必须同步 _BACKUP_COLUMNS（P5 审计会查）。"""
    cols = CorpusService._BACKUP_COLUMNS["documents"]
    for field in ("doc_kind", "subject", "org", "analysts", "doc_kind_override"):
        assert field in cols, field


def test_ingest_hook_materializes_metadata(i2_dsn: str, tmp_path) -> None:
    """P6 挂钩（I2-7 新链语义）：ingest 发布即落权威元数据——发布日期唯一落点
    为 admission ``metadata_snapshot.report_publication``（契约 §4.3，禁止
    doc_id 前缀派生）。旧 documents 表物化随写路径退役；org/analysts 的
    读取侧迁移在 I2-7 读路径步骤验收。
    """
    doc = tmp_path / "2026.09.06-国金证券-电子行业研究-ai-pcb.html.md"
    doc.write_text(
        "报告发布日期：2026年9月6日\n"
        "分析师：樊志远（执业S1130524060002）\n\n"
        "电子行业 2026 年 9 月第 1 周：AI PCB 板块营收 500 亿元，环比上升。\n",
        encoding="utf-8",
    )
    from plugins.corpus.preparation.contract import (
        MaterialType,
        PublicationDateOrigin,
        PublicationDatePrecision,
        PublicationDateStatus,
        ResearchDomain,
        ReviewDecision,
        ReviewedDecision,
        sha256_of_bytes,
    )
    from plugins.corpus.preparation.repository_pg import PgStore

    store = PgStore(i2_dsn, sandbox_db="i2_sandbox_corpus")
    source_id = sha256_of_bytes(doc.read_bytes())
    decision = ReviewedDecision(
        decision_id=f"rev-meta-{source_id[:12]}",
        source_id=source_id,
        reviewer="metadata-gate",
        reviewed_at=datetime.now(UTC),
        decision=ReviewDecision.ADMITTED,
        rationale="元数据挂钩测试合成决定（测试资产）",
        material_type=MaterialType.RESEARCH_REPORT,
        research_domain=ResearchDomain.INDUSTRY,
    )
    store.put_reviewed_decision(decision)

    svc = CorpusService(i2_dsn)
    status, published = svc.ingest_path(doc, review_decision_ids=(decision.decision_id,))
    assert (status, published) == ("in_scope", True)

    publication = store.get_publication(source_id)
    assert publication is not None and publication.active_build_id is not None
    admission = store.get_admission(publication.current_decision_id)
    assert admission is not None
    rp = admission.metadata_snapshot.report_publication
    assert rp is not None
    assert rp.status is PublicationDateStatus.KNOWN
    assert rp.value == "2026-09-06"
    assert rp.precision is PublicationDatePrecision.DATE
    assert rp.origin is PublicationDateOrigin.SOURCE_EXPLICIT
