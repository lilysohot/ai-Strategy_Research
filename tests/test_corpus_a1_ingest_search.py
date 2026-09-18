"""A1 回归门禁（I2-7 新链）：入库后**不做任何索引构建动作**就能直接检索。

历史（p1-corpus-scaleup.md A 组）：P0 的坑是 ``ingest.py`` 不建索引而
``build_index`` 无生产调用方，入库后检索静默失效，跑完全量才发现。PG 侧的
结构性修正：``tsv`` 一类检索列全部为 **GENERATED ALWAYS AS ... STORED**，
写入即自动维护。

I2-7 迁移说明：旧直写分支（documents/blocks + 临时 schema）已随写路径唯一化
退役，本门禁迁到新 preparation 链——``corpus_chunks.search_tsv`` 生成列 +
``search_chunks`` 只读活动发布范围（先筛活动范围再排名）。人工审核决定由
测试预写（政策 ``auto_decision.enabled=false``：无决定不自动纳入）。

运行条件：``CORPUS_I2_DSN`` 指向隔离库 i2_sandbox_corpus；未设置模块级跳过
（与 test_corpus_preparation_repository_pg.py 同约定；I2 演练环境不得 skip）。
数据纪律：仅操作 corpus schema，每用例前 TRUNCATE（数据级精确清理）。
"""

from __future__ import annotations

import os
import textwrap
from datetime import UTC, datetime

import pytest

from plugins.corpus.service import CorpusService

DSN = os.environ.get("CORPUS_I2_DSN", "")
if not DSN:
    # 模块级跳过且不导入 psycopg：普通环境的 sys.modules 零 PG 断言不受污染。
    pytest.skip("CORPUS_I2_DSN 未设置（非 I2 演练环境）", allow_module_level=True)

import psycopg  # noqa: E402  仅 I2 演练环境导入

from plugins.corpus.preparation.contract import (  # noqa: E402
    MaterialType,
    ResearchDomain,
    ReviewDecision,
    ReviewedDecision,
    sha256_of_bytes,
)
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


def _verify_cleanup_target(cur: psycopg.Cursor) -> None:
    cur.execute("SELECT current_database()")
    row = cur.fetchone()
    database = row[0] if row else None
    if database != SANDBOX_DB:
        raise AssertionError(f"拒绝清理：current_database={database!r} ≠ {SANDBOX_DB!r}")
    cur.execute("SELECT datname FROM pg_database WHERE datallowconn")
    dbs = {r[0] for r in cur.fetchall()}
    if "apodex" in dbs:
        raise AssertionError("拒绝清理：目标实例含 apodex 库")


@pytest.fixture(autouse=True)
def _clean_tables():
    qualified = ", ".join(f"corpus.{t}" for t in TABLES)
    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        _verify_cleanup_target(cur)
        cur.execute(f"TRUNCATE {qualified}")  # 单语句：FK 关联表须同时清空
    yield


@pytest.fixture()
def tiny_corpus(tmp_path_factory):
    """一份极小语料：含口语词、小数+单位、百分比，覆盖 A1 要验的检索形态。"""
    directory = tmp_path_factory.mktemp("a1_corpus")
    (directory / "2026-09-09_A1闭环验证.md").write_text(
        textwrap.dedent(
            """
            # A1 闭环验证

            本次写入用于验证入库之后能否立即检索。

            目标价定为 88.88 元，评级维持增持。
            全球流动性最新估算规模为 194.9 万亿美元，环比增长 30%。
            """
        ).strip(),
        encoding="utf-8",
    )
    return directory


def _admit_decision(path) -> ReviewedDecision:
    """预写绑定来源哈希的人工批准决定（A1 门禁测试资产，非语料来源）。"""
    store = PgStore(DSN, sandbox_db=SANDBOX_DB)
    source_id = sha256_of_bytes(path.read_bytes())
    decision = ReviewedDecision(
        decision_id=f"rev-a1-{source_id[:12]}",
        source_id=source_id,
        reviewer="a1-gate",
        reviewed_at=datetime.now(UTC),
        decision=ReviewDecision.ADMITTED,
        rationale="A1 门禁合成决定：内容级人工批准（测试资产）",
        material_type=MaterialType.RESEARCH_REPORT,
        research_domain=ResearchDomain.INDUSTRY,
    )
    store.put_reviewed_decision(decision)
    return decision


def test_ingest_then_search_without_any_index_build(tiny_corpus) -> None:
    """入库（带人工决定）→ 立刻检索，中间不做任何索引构建动作。"""
    svc = CorpusService(DSN)
    doc = tiny_corpus / "2026-09-09_A1闭环验证.md"
    decision = _admit_decision(doc)

    status, published = svc.ingest_path(doc, review_decision_ids=(decision.decision_id,))
    assert (status, published) == ("in_scope", True)

    # ① 生成列必须已被 PG 自动填好（不是靠事后 build_index）
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM corpus.corpus_chunks WHERE search_tsv IS NULL")
        null_tsv = cur.fetchone()[0]
    assert null_tsv == 0, "corpus_chunks.search_tsv 有空值 —— GENERATED 列未生效"

    # ② 关键断言：不建索引，直接就能检索命中（读侧只看活动发布范围）
    hits = search_chunks(DSN, "目标价", limit=5)
    assert hits, "入库后立即检索应有命中（A1 不通过）"

    # ③ 小数与单位形态也能命中（P0 最花力气的那部分）
    assert search_chunks(DSN, "194.9 万亿美元", limit=5), "小数+单位形态检索失败"


def test_rerun_is_idempotent_and_skips_unchanged(tiny_corpus) -> None:
    """二次跑批：同一份文件不得重复入库（内容寻址 source_id 幂等）。"""
    svc = CorpusService(DSN)
    doc = tiny_corpus / "2026-09-09_A1闭环验证.md"
    decision = _admit_decision(doc)

    status, published = svc.ingest_path(doc, review_decision_ids=(decision.decision_id,))
    assert (status, published) == ("in_scope", True)

    # 跨入口幂等：单文件发布后，目录批跑命中内容寻址预检 → 跳过。
    stats = svc.ingest_dir(tiny_corpus)
    assert stats.added == 0, stats.as_dict()
    assert stats.skipped_unchanged == 1, stats.as_dict()

    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM corpus.corpus_sources")
        count = cur.fetchone()[0]
    assert count == 1, "重复跑批导致同一份来源入库多次"
