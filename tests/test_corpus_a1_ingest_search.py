"""A1 回归门禁：跑完 ingest **不建索引** 就能直接检索。

这是启动「首次全量 8000 份」之前的**硬停点**（`p1-corpus-scaleup.md` A 组）：

- **P0 的坑**：`ingest.py` 不建索引，而 `build_index` 全仓库**没有生产调用方**，
  于是入库后检索**静默失效**，表现为"库是空的"——要跑完 2–7h 才发现。
- **PG 侧的结构性保证**：``blocks.tsv`` 与 ``documents.title_tsv`` 是
  **GENERATED ALWAYS AS ... STORED** 列，由 PG 在写入时**自动维护**。
  "忘了建索引"这个失败模式在结构上就不存在。

本测试把上述保证**钉成回归门禁**：在一个临时库里跑完整的
「全新库 → ``init_db`` → ``ingest_dir`` → **立即** ``search``」往返，
全程不调用任何 ``build_index`` / 重建索引的接口。

用法上的两点：

- 临时库 ``corpus_a1check`` 在结束时删除，**不碰正式语料库**；
- PG 不可用时整个模块 skip（与 ``test_corpus_golden.py`` 同一套约定）。
"""

from __future__ import annotations

import textwrap
from urllib.parse import quote

import psycopg
import pytest

from plugins.corpus.service import CorpusService, dsn

# 用**临时 schema**而非临时 database 做隔离：CREATE DATABASE 要复制 template1，
# 某些环境存在 collation 版本不匹配（template1 建于 X 版本、OS 提供 Y 版本）会被直接拒绝。
# schema 方案绕开了这个依赖，同时也不会碰到正式的 documents / blocks 表。
SCRATCH_SCHEMA = "corpus_a1check"


def _scratch_url(admin: str) -> str:
    """ ``search_path`` 指到临时 schema 的连接串（public 保留在后面，供 zhcfg 等对象解析）。"""
    options = quote(f"-c search_path={SCRATCH_SCHEMA},public")
    sep = "&" if "?" in admin else "?"
    return f"{admin}{sep}options={options}"


@pytest.fixture(scope="module")
def scratch_dsn():
    """准备一次性 schema 并在结束后清除。PG 不可用则跳过整个模块。"""
    admin = dsn()
    try:
        psycopg.connect(admin, connect_timeout=5).close()
    except psycopg.OperationalError as exc:  # pragma: no cover - 环境相关
        pytest.skip(f"PG 不可用，跳过 A1 门禁：{exc}")

    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP SCHEMA IF EXISTS "{SCRATCH_SCHEMA}" CASCADE')
        conn.execute(f'CREATE SCHEMA "{SCRATCH_SCHEMA}"')
    try:
        yield _scratch_url(admin)
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{SCRATCH_SCHEMA}" CASCADE')


@pytest.fixture(scope="module")
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


def test_ingest_then_search_without_any_index_build(scratch_dsn, tiny_corpus) -> None:
    """入库 → 立刻检索，中间不做任何索引构建动作。"""
    svc = CorpusService(scratch_dsn)
    svc.init_db()

    stats = svc.ingest_dir(tiny_corpus)
    assert stats.added == 1, stats.as_dict()
    assert stats.failed == 0, stats.as_dict()
    assert stats.blocks >= 1, stats.as_dict()

    # ① 生成列必须已被 PG 自动填好（不是靠事后 build_index）
    with svc._connect() as conn:
        null_tsv = conn.execute(
            "SELECT count(*) AS n FROM blocks WHERE tsv IS NULL"
        ).fetchone()["n"]
        null_title = conn.execute(
            "SELECT count(*) AS n FROM documents WHERE title_tsv IS NULL"
        ).fetchone()["n"]
    assert null_tsv == 0, "blocks.tsv 有空值 —— GENERATED 列未生效"
    assert null_title == 0, "documents.title_tsv 有空值 —— GENERATED 列未生效"

    # ② 关键断言：不建索引，直接就能检索命中
    hits = svc.search("目标价", limit=5)
    assert hits, "入库后立即检索应有命中（A1 不通过）"

    # ③ 小数与单位形态也能命中（P0 最花力气的那部分）
    assert svc.search("194.9 万亿美元", limit=5), "小数+单位形态检索失败"


def test_rerun_is_idempotent_and_skips_unchanged(scratch_dsn, tiny_corpus) -> None:
    """二次跑批：同一份文件不得重复入库（content_hash UNIQUE 兜底）。"""
    svc = CorpusService(scratch_dsn)

    stats = svc.ingest_dir(tiny_corpus)
    assert stats.added == 0, stats.as_dict()
    assert stats.skipped_unchanged == 1, stats.as_dict()

    with svc._connect() as conn:
        count = conn.execute("SELECT count(*) AS n FROM documents").fetchone()["n"]
    assert count == 1, "重复跑批导致同一份文档入库多次"
