"""I-RANK-1（c′/i0c-r4v）：排序信号剔除功能词与标点——候选池不变、只有 score 变。

门（c3w-rollout-plan §5；新文件落位，避开 r5/r6 绑定的 test_corpus_search.py）：

- 候选池不变（I-1）：``WHERE search_tsv @@ q.tsq`` 恒用全词元——SQL 静态断言 +
  真库只读对比（rank_query 变化不改变命中集合，limit=2000 覆盖全池）；
- score 只由实词决定：纯 SELECT 表达式（corpus schema 零写入）——仅命中虚词的
  合成块 score=0 但仍在候选集（@@ 全词元 tsq 为真）；
- 标点剔除 / 空兜底：``is_punct_lexeme`` / ``rank_lexemes`` 单元门（全为功能词/
  标点时回退原词元，fail-closed）；
- tie-break 不变（I-2）：``ORDER BY score DESC, c.build_id, c.chunk_id`` 静态断言 +
  真库命中序 = (-score, build_id, chunk_id)；
- 开关回滚：``RANK_LEXEME_PRUNE=False`` ⇒ 注入的 rank_query == query，且结果与
  显式 ``rank_query=query`` 逐字段一致（SearchHit 冻结 dataclass 逐字段相等）。

真库门运行条件：``CORPUS_I2_DSN`` 指向隔离库（只读）；无 DSN 时真库门逐测跳过，
单元门照常运行。
"""

from __future__ import annotations

import os

import pytest

from plugins.corpus.preparation import search_pg
from plugins.corpus.preparation.chunk import normalize_search_text
from plugins.corpus.preparation.negative_query import (
    _FUNCTION_WORDS,
    content_lexemes,
    is_punct_lexeme,
    rank_lexemes,
)

DSN = os.environ.get("CORPUS_I2_DSN", "")
LIVE_QUERY = "光力科技 营业收入"
#: 大池查询（全词元 OR 连接，与评估 base 池同构）：I-1/tie-break/回滚门需要多命中
#: 才有实质覆盖；websearch AND 语义下自然语句常零命中，故显式构造。
POOL_QUERY = '"光力科技" OR "营业收入" OR "2024" OR "同比"'

requires_db = pytest.mark.skipif(not DSN, reason="CORPUS_I2_DSN 未设置（非隔离库环境，真库门跳过）")


def test_is_punct_lexeme_structural():
    """标点词元=结构判定（无字母/数字/汉字）；数字/字母词元不是标点。"""
    assert is_punct_lexeme("。") and is_punct_lexeme("、") and is_punct_lexeme("％")
    assert is_punct_lexeme("")
    assert not is_punct_lexeme("23.5")
    assert not is_punct_lexeme("3D")
    assert not is_punct_lexeme("公司")


def test_rank_lexemes_prunes_function_and_punct_keeps_single_char():
    """剔除功能词与标点；单字保留（排序信号口径，区别于收紧查询）。"""
    kept = rank_lexemes(("这", "份", "材料", "。", "公司", "公", "2024"))
    assert kept == ("公司", "公", "2024")


def test_rank_lexemes_differs_from_content_lexemes_on_single_char():
    """排序信号保留单字；收紧查询口径（content_lexemes）去单字——互不覆盖。"""
    assert rank_lexemes(("公", "司")) == ("公", "司")
    assert content_lexemes(("公", "司")) == ()


def test_rank_lexemes_fallback_when_all_pruned():
    """全部为功能词/标点 ⇒ 回退原词元（fail-closed：rank_query 退化为 query）。"""
    assert rank_lexemes(("的", "了", "是否")) == ("的", "了", "是否")
    assert rank_lexemes(("。", "、")) == ("。", "、")
    assert rank_lexemes(()) == ()
    assert not set(rank_lexemes(("公司", "这"))) & _FUNCTION_WORDS


def test_search_sql_wiring_candidate_pool_vs_score():
    """SQL 接线：候选池/ts_headline 用全词元 tsq（I-1）；score 单独用 tsq_rank，tie-break 不变（I-2）。"""
    sql = search_pg._SEARCH_SQL
    assert "JOIN corpus.corpus_chunks AS c ON c.search_tsv @@ q.tsq" in sql
    assert "ts_headline('zhcfg', c.search_text, q.tsq," in sql
    assert "ts_rank(c.search_tsv, q.tsq_rank) AS score" in sql
    assert "websearch_to_tsquery('zhcfg', %(rank_query)s) AS tsq_rank" in sql
    assert "ORDER BY score DESC, c.build_id, c.chunk_id" in sql


def test_build_search_params_rank_query_key():
    """``rank_query`` 显式键同样走 R5 规范化；缺省时不出现（由 search_chunks_on 注入）。"""
    params = search_pg.build_search_params("产能 同比", rank_query="产能")
    assert params["rank_query"] == normalize_search_text("产能")
    assert "rank_query" not in search_pg.build_search_params("产能 同比")


@requires_db
def test_rank_query_on_prunes_and_falls_back():
    """真库：排序串=实词 OR 连接；全功能词查询回退原词元（同游标/同快照提取）。"""
    import psycopg

    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        pruned = search_pg._rank_query_on(cur, LIVE_QUERY)
        kept = rank_lexemes(search_pg.query_lexemes(DSN, LIVE_QUERY))
        assert pruned == " OR ".join('"' + t.replace('"', " ") + '"' for t in kept)
        assert "。" not in pruned
        fallback = search_pg._rank_query_on(cur, "的是否能否")
        original = search_pg.query_lexemes(DSN, "的是否能否")
        assert fallback == " OR ".join('"' + t.replace('"', " ") + '"' for t in original)


@requires_db
def test_candidate_pool_unchanged_live():
    """I-1 真库门：rank_query 变化不改变命中集合（limit=2000 覆盖全池，逐块一致）。"""
    import psycopg

    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        params = search_pg.build_search_params(POOL_QUERY, limit=2000)
        base_hits = search_pg.search_chunks_on(cur, dict(params, rank_query=str(params["query"])))
        assert len(base_hits) > 1  # 门有效性：池非平凡
        pruned_hits = search_pg.search_chunks_on(cur, dict(params))
        assert {(h.build_id, h.chunk_id) for h in base_hits} == {
            (h.build_id, h.chunk_id) for h in pruned_hits
        }


@requires_db
def test_function_only_match_scores_zero_but_stays_in_pool():
    """score 只由实词决定：仅命中虚词的合成块 score=0，但候选集（@@ 全词元）仍收。

    纯 SELECT 表达式（corpus schema 零写入）：合成文本"的"，全词元 tsq=
    "公司" OR "的" ⇒ @@ 为真；实词 tsq_rank="公司" ⇒ score=0。
    """
    import psycopg

    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT to_tsvector('zhcfg', %s) @@ websearch_to_tsquery('zhcfg', %s),"
            "       ts_rank(to_tsvector('zhcfg', %s), websearch_to_tsquery('zhcfg', %s))",
            ("的", '"公司" OR "的"', "的", '"公司"'),
        )
        in_pool, score = cur.fetchone()
    assert in_pool is True
    assert float(score) == 0.0


@requires_db
def test_tie_break_order_live():
    """I-2 真库门：命中序 = (-score, build_id, chunk_id)（tie-break 与 base 一致）。"""
    hits = search_pg.search_chunks(DSN, POOL_QUERY, limit=50)
    assert len(hits) > 1  # 门有效性：多命中才检验排序
    keys = [(-h.score, h.build_id, h.chunk_id) for h in hits]
    assert keys == sorted(keys)


@requires_db
def test_switch_off_rollback_field_equal(monkeypatch):
    """开关回滚：RANK_LEXEME_PRUNE=False ⇒ rank_query=query，结果与显式 base 逐字段一致。"""
    import psycopg

    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        params_off = search_pg.build_search_params(POOL_QUERY, limit=50)
        with monkeypatch.context() as m:
            m.setattr(search_pg, "RANK_LEXEME_PRUNE", False)
            hits_off = search_pg.search_chunks_on(cur, params_off)
        assert params_off["rank_query"] == params_off["query"]
        assert len(hits_off) > 1  # 门有效性
        params_base = search_pg.build_search_params(
            POOL_QUERY, limit=50, rank_query=str(params_off["query"])
        )
        hits_base = search_pg.search_chunks_on(cur, params_base)
        assert hits_off == hits_base
