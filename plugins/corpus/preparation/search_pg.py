"""I2-3 PG 读侧 FTS 查询（先筛活动范围，再排名）。

架构 §7.1 + design-review C13：检索候选只来自 ``corpus_publications.active_build_id``
指向的活动 build（INNER JOIN 先筛范围）；退役（指针置空）与未发布 build 的 chunk
永不入候选。排名仅在活动范围内按 ``ts_rank`` 计算。本模块是读侧查询接口，
不实现 :class:`~plugins.corpus.preparation.repository.Store` 写入 Seam
（Store 是写入契约，MemoryStore 不承载 FTS）。

分词：``websearch_to_tsquery('zhcfg', …)`` 与写入侧 GENERATED 列
``to_tsvector('zhcfg', search_text)`` 同配置（INDEX_REV_V3 = ``index-3-zhcfg-2``；
zhcfg 全词性→simple 映射含 ``'m'`` 数词）。查询侧经
:func:`~plugins.corpus.preparation.chunk.normalize_search_text` 与写侧同一规范化
（R5：``%``/``％`` 归一化为空格，避免写侧已规范化而查询侧 token 不一致漏召回）。
zhcfg 或索引文本规则升级必须换新 index_rev 全量重建（新 build 重算 search_tsv/GIN），
本模块只服务活动版本，不感知历史分词版本。

目标 fail-closed：与 :class:`PgStore` 同纪律——``current_database`` 必须等于隔离库；
目标实例含 ``apodex`` 库即判定为生产实例并拒绝（读侧同样不允许触碰生产库）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # psycopg 是可选依赖（PG 检索链路专属）：类型仅用于标注（本模块有
    # ``from __future__ import annotations``）；实际连接在函数内惰性 import，
    # 普通 sqlite 环境零 psycopg。
    import psycopg

from plugins.corpus.preparation.chunk import normalize_search_text
from plugins.corpus.preparation.contract import ResearchDomain
from plugins.corpus.preparation.repository import StoreError

_SANDBOX_DB = "i2_sandbox_corpus"

# 检索纪律（C13）：q（tsquery）→ GIN 候选（search_tsv @@ tsq）→ INNER JOIN
# publications.active_build_id 收敛到活动范围 → admissions 供领域/发布日期过滤
# → ts_rank 排名。ISO 文本序=时序（report_publication.value 为 ISO 日期文本）。
_SEARCH_SQL = """
SELECT p.source_id,
       c.build_id,
       c.chunk_id,
       c.kind,
       c.title_text,
       c.section_path,
       c.unit_refs,
       ts_rank(c.search_tsv, q.tsq) AS score,
       ts_headline('zhcfg', c.search_text, q.tsq,
                   'MaxWords=28, MinWords=8, ShortWord=1') AS snippet,
       a.metadata_snapshot->'report_publication'->>'value' AS published
FROM (SELECT websearch_to_tsquery('zhcfg', %(query)s) AS tsq) AS q
JOIN corpus.corpus_chunks AS c ON c.search_tsv @@ q.tsq
JOIN corpus.corpus_builds AS b ON b.build_id = c.build_id
JOIN corpus.corpus_publications AS p ON p.active_build_id = c.build_id
JOIN corpus.corpus_admissions AS a ON a.decision_id = b.decision_id
WHERE (%(domain)s::text IS NULL OR a.research_domain = %(domain)s)
  AND (%(date_from)s::text IS NULL
       OR a.metadata_snapshot->'report_publication'->>'value' >= %(date_from)s)
  AND (%(date_to)s::text IS NULL
       OR a.metadata_snapshot->'report_publication'->>'value' <= %(date_to)s)
ORDER BY score DESC, c.build_id, c.chunk_id
LIMIT %(limit)s
"""


@dataclass(frozen=True)
class SearchHit:
    """读侧检索命中：定位 chunk 并回接活动来源（消费侧证据起点）。"""

    source_id: str
    build_id: str
    chunk_id: str
    kind: str
    title_text: str | None
    section_path: tuple[str, ...]
    unit_refs: tuple[str, ...]
    score: float
    #: 截断展示片段（**非权威原文**）：仅用于定位，逐字引用必须再走 read_pg.fetch_verbatim。
    snippet: str = ""
    #: 研报发布日期（唯一落点 = admission.metadata_snapshot.report_publication，§4.3）。
    published: str | None = None


def _check_target(conn: psycopg.Connection, sandbox_db: str) -> None:
    """与 PgStore._check_target 同纪律：隔离库校验 + apodex 生产实例反证。"""
    with conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        row = cur.fetchone()
        if row is None or row[0] != sandbox_db:
            raise StoreError(f"拒绝：current_database={row[0] if row else None!r} ≠ {sandbox_db!r}")
        cur.execute("SELECT datname FROM pg_database WHERE datallowconn")
        dbs = {r[0] for r in cur.fetchall()}
    if "apodex" in dbs:
        raise StoreError("拒绝：目标实例含 apodex 库——判定为生产实例，禁止检索")


def build_search_params(
    query: str,
    *,
    domain: ResearchDomain | None = None,
    published_from: str | None = None,
    published_to: str | None = None,
    limit: int = 20,
) -> dict[str, object]:
    """校验并归一化检索参数（**唯一**来源，供 search_chunks 与同快照组合读取复用）。

    R5：查询侧必须与写侧（chunk.normalize_search_text）同一规范化——写侧把
    ``%``/``％`` 归一化为空格，查询侧若原样传 "23.5%" 给 websearch_to_tsquery
    会得到独立 token "23.5%"，与索引 token "23.5" 不一致而漏召回。``%``/``％``
    不是 websearch 操作符（OR/引号/负号），替换为空格不破坏这些语法。
    """
    if not query.strip():
        raise StoreError("query 不能为空")
    if limit < 1:
        raise StoreError("limit 必须 >= 1")
    date_from = published_from.strip() or None if published_from else None
    date_to = published_to.strip() or None if published_to else None
    return {
        "query": normalize_search_text(query),
        "domain": domain.value if domain is not None else None,
        "date_from": date_from,
        "date_to": date_to,
        "limit": limit,
    }


def search_chunks(
    dsn: str,
    query: str,
    *,
    sandbox_db: str = _SANDBOX_DB,
    domain: ResearchDomain | None = None,
    published_from: str | None = None,
    published_to: str | None = None,
    limit: int = 20,
) -> tuple[SearchHit, ...]:
    """在活动范围（published active build）内全文检索 chunk。

    ``query`` 为 websearch 语法（未加引号词 AND、双引号短语、OR）；分词走
    ``zhcfg``。``domain`` 过滤经 build 的 admission ``research_domain``；
    ``published_from``/``published_to`` 为 ISO 日期文本闭区间，过滤经 admission
    ``metadata_snapshot.report_publication.value``（仅研报携带该键，无快照的
    admission 在日期过滤下不命中）。零候选返回空元组（不报错）。
    """
    import psycopg

    params = build_search_params(
        query,
        domain=domain,
        published_from=published_from,
        published_to=published_to,
        limit=limit,
    )
    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, sandbox_db)
        with conn.cursor() as cur:
            return search_chunks_on(cur, params)


def search_chunks_on(cur: psycopg.Cursor, params: dict[str, object]) -> tuple[SearchHit, ...]:
    """在**调用方给定的游标/事务**内检索（read_pg.search_with_coverage 复用以取得同快照）。

    ``params`` 由 :func:`search_chunks` 归一化后传入（query/domain/date_from/date_to/limit）；
    语义与 :func:`search_chunks` 完全一致，只是连接与事务由调用方持有——这是
    「检索结果与覆盖元数据读同一数据库快照」（§7.3）的实现落点。
    """
    cur.execute(_SEARCH_SQL, params)
    rows = cur.fetchall()
    return tuple(
        SearchHit(
            source_id=row[0],
            build_id=row[1],
            chunk_id=row[2],
            kind=row[3],
            title_text=row[4],
            section_path=tuple(row[5]),
            unit_refs=tuple(row[6]),
            score=row[7],
            snippet=str(row[8] or ""),
            published=str(row[9]) if row[9] else None,
        )
        for row in rows
    )
