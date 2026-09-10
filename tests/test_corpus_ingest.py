"""P0b #4：内容去重——同一份文档重复 ingest 只入库一次。

真实语料「完全重复 0 组」（plan §6 偏差说明），这条验收无法用真实数据验证，
改为在临时副本上验 ``content_hash`` 幂等：同一文件 ingest 两次，
``documents`` 行数不增、``blocks`` 行数不变。

幂等由数据库的 ``content_hash UNIQUE`` 约束保证（见 ``ingest.py`` 的 ``upsert_document``）：
第二次入库命中 ``IntegrityError`` 被捕获并返回 ``False``，且不插入 ``blocks``。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from plugins.corpus.ingest import connect, init_db, parse_document, upsert_document


@pytest.fixture
def corpus_db(tmp_path: Path):
    conn = connect(tmp_path / "index.db")
    init_db(conn)
    yield conn
    conn.close()


def _write_sample(path: Path) -> None:
    path.write_text(
        "# 测试研报\n\n## 关键事实\n\n公司2026年营业收入为47.3亿元，同比增长30%。\n",
        encoding="utf-8",
    )


def test_reingest_same_file_keeps_single_document(
    corpus_db: sqlite3.Connection, tmp_path: Path
):
    """同一文件 ingest 两次：content_hash UNIQUE 应让第二次被跳过。"""
    src = tmp_path / "sample.md"
    _write_sample(src)

    doc = parse_document(src)
    assert upsert_document(corpus_db, doc) is True  # 首次新入库
    assert upsert_document(corpus_db, doc) is False  # 重复被跳过

    n_docs = corpus_db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    n_blocks = corpus_db.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
    assert n_docs == 1, f"重复 ingest 后 documents 应为 1，实际 {n_docs}"
    assert n_blocks == len(doc.blocks)
    assert (
        corpus_db.execute(
            "SELECT COUNT(*) FROM documents WHERE content_hash = ?",
            (doc.content_hash,),
        ).fetchone()[0]
        == 1
    )
