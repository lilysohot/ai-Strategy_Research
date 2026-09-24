"""I2-3 PG 读侧 FTS 查询（先筛活动范围，再排名）。

架构 §7.1 + design-review C13：检索候选只来自 ``corpus_publications.active_build_id``
指向的活动 build（INNER JOIN 先筛范围）；退役（指针置空）与未发布 build 的 chunk
永不入候选。排名仅在活动范围内按 ``ts_rank`` 计算。本模块是读侧查询接口，
不实现 :class:`~plugins.corpus.preparation.repository.Store` 写入 Seam
（Store 是写入契约，MemoryStore 不承载 FTS）。

分词：``websearch_to_tsquery('zhcfg', …)`` 与写入侧 GENERATED 列
``to_tsvector('zhcfg', search_text)`` 同配置（INDEX_REV_V3 = ``index-4-zhcfg-2``；
zhcfg 全词性→simple 映射含 ``'m'`` 数词）。查询侧经
:func:`~plugins.corpus.preparation.chunk.normalize_search_text` 与写侧同一规范化
（R5：``%``/``％`` 归一化为空格，避免写侧已规范化而查询侧 token 不一致漏召回）。
zhcfg 或索引文本规则升级必须换新 index_rev 全量重建（新 build 重算 search_tsv/GIN），
本模块只服务活动版本，不感知历史分词版本。

排序信号（c′/i0c-r4v）：``score`` 列按**实词词元**计算（``negative_query.rank_lexemes``
剔除功能词/标点，``RANK_LEXEME_PRUNE`` 开关可整体回退）。候选来自 chunk 全文或来源
原名，来源内最多保留 40 个候选，再按来源最高分和块分排序；``ts_headline`` 仍只展示
chunk 的截断文本。

目标 fail-closed：与 :class:`PgStore` 同纪律——``current_database`` 必须等于隔离库；
目标实例含 ``apodex`` 库即判定为生产实例并拒绝（读侧同样不允许触碰生产库）；
窗口期仅在显式 ``CORPUS_TARGET_DB`` 授权下放行（见 :mod:`pg_target`）。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # psycopg 是可选依赖（PG 检索链路专属）：类型仅用于标注（本模块有
    # ``from __future__ import annotations``）；实际连接在函数内惰性 import，
    # 普通 sqlite 环境零 psycopg。
    import psycopg

from plugins.corpus.preparation.chunk import normalize_search_text
from plugins.corpus.preparation.contract import ResearchDomain
from plugins.corpus.preparation.negative_query import rank_lexemes
from plugins.corpus.preparation.pg_target import production_instance_authorized, resolve_target_db
from plugins.corpus.preparation.repository import StoreError

# c′（i0c-r4v）排序信号开关：True ⇒ score 只按实词（rank_lexemes 剔除功能词/标点）；
# False ⇒ rank_query 退化为 query 本身，行为与 base 逐字段一致（两级回滚的代码级开关）。
RANK_LEXEME_PRUNE = True

# 检索纪律（C13）：q（tsquery）→ chunk 全文/来源原名候选 → INNER JOIN
# publications.active_build_id 收敛到活动范围 → admissions 供领域/发布日期过滤
# → 来源内截断 → ts_rank 排名。ISO 文本序=时序（report_publication.value 为 ISO 日期文本）。
# score 用 q.tsq_rank（实词，c′）；来源原名权重用于把明确点名的文档拉入有界候选池。
_SEARCH_SQL = """
WITH q AS (
  SELECT websearch_to_tsquery('zhcfg', %(query)s) AS tsq,
         websearch_to_tsquery('zhcfg', %(rank_query)s) AS tsq_rank
), matches AS (
  SELECT p.source_id, c.build_id, c.chunk_id, c.kind, c.title_text, c.section_path,
         c.unit_refs,
         (ts_rank(c.search_tsv, q.tsq_rank)
          + 2 * ts_rank(to_tsvector('zhcfg', array_to_string(s.original_names, ' ')),
                        q.tsq_rank)) AS score,
         ts_headline('zhcfg', c.search_text, q.tsq,
                     'MaxWords=28, MinWords=8, ShortWord=1') AS snippet,
         a.metadata_snapshot->'report_publication'->>'value' AS published
  FROM q
  JOIN corpus.corpus_chunks AS c ON true
  JOIN corpus.corpus_builds AS b ON b.build_id = c.build_id
  JOIN corpus.corpus_publications AS p ON p.active_build_id = c.build_id
  JOIN corpus.corpus_sources AS s ON s.source_id = p.source_id
  JOIN corpus.corpus_admissions AS a ON a.decision_id = b.decision_id
  WHERE (c.search_tsv @@ q.tsq
         OR to_tsvector('zhcfg', array_to_string(s.original_names, ' ')) @@ q.tsq)
    AND (%(domain)s::text IS NULL OR a.research_domain = %(domain)s)
    AND (%(date_from)s::text IS NULL
         OR a.metadata_snapshot->'report_publication'->>'value' >= %(date_from)s)
    AND (%(date_to)s::text IS NULL
         OR a.metadata_snapshot->'report_publication'->>'value' <= %(date_to)s)
), ranked AS (
  SELECT matches.*,
         max(score) OVER (PARTITION BY source_id) AS source_score,
         row_number() OVER (PARTITION BY source_id
                            ORDER BY score DESC, build_id, chunk_id) AS source_position
  FROM matches
)
SELECT source_id, build_id, chunk_id, kind, title_text, section_path, unit_refs,
       score, snippet, published
FROM ranked
WHERE source_position <= 40
ORDER BY source_score DESC, score DESC, build_id, chunk_id
LIMIT %(limit)s
"""


@dataclass(frozen=True)
class SearchHit:
    """读侧检索命中：定位 chunk 并回接活动来源（消费侧证据起点）。

    结构加深（票 02 I-D1）：``page``/``cells``/``label_path`` 取自该 chunk 引用
    单元（corpus_units.location）——``label_path`` 为各单元结构标签路径的去重合并，
    供结构重叠排序（票 04 I-B2）消费；非表格块为空。
    """

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
    #: chunk 首个单元的页码（定位用）。
    page: int | None = None
    #: chunk 首个单元的网格坐标（表格块）。
    cells: tuple[tuple[int, int], ...] = ()
    #: 结构标签路径去重合并（I-B1 索引文本的消费侧投影，结构重叠信号的输入）。
    label_path: tuple[str, ...] = ()
    #: Ordered authority chunks in the selected document evidence regions.
    context_chunk_ids: tuple[str, ...] = ()


_UNITS_LOCATION_SQL = """
SELECT build_id, unit_id, location
FROM corpus.corpus_units
WHERE build_id = ANY(%(build_ids)s::text[])
  AND unit_id = ANY(%(unit_ids)s::text[])
"""


def _enrich_hits(cur: psycopg.Cursor, hits: tuple[SearchHit, ...]) -> tuple[SearchHit, ...]:
    """批量加深命中（票 02 I-D1）：同游标/快照内经 corpus_units 取 page/cells/label_path。

    单条批量查询，不产生 SQL N+1；无单元引用的块原样返回（不加深）。
    """
    if not hits:
        return hits
    unit_ids: list[str] = []
    build_ids: set[str] = set()
    for hit in hits:
        build_ids.add(hit.build_id)
        unit_ids.extend(hit.unit_refs)
    if not unit_ids:
        return hits
    cur.execute(
        _UNITS_LOCATION_SQL,
        {"build_ids": sorted(build_ids), "unit_ids": unit_ids},
    )
    by_build: dict[str, dict[str, dict]] = {}
    for build_id, unit_id, location in cur.fetchall():
        by_build.setdefault(str(build_id), {})[str(unit_id)] = (
            location if isinstance(location, dict) else {}
        )
    enriched: list[SearchHit] = []
    for hit in hits:
        units = by_build.get(hit.build_id, {})
        labels: list[str] = []
        seen: set[str] = set()
        page: int | None = None
        cells: tuple[tuple[int, int], ...] = ()
        for index, unit_id in enumerate(hit.unit_refs):
            loc = units.get(unit_id)
            if loc is None:
                continue
            if index == 0:
                page = loc.get("page")
                cells = tuple(
                    (int(cell[0]), int(cell[1]))
                    for cell in (loc.get("cells") or ())
                    if isinstance(cell, (list, tuple)) and len(cell) == 2
                )
            for label in loc.get("label_path") or ():
                if label and label not in seen:
                    seen.add(label)
                    labels.append(label)
        enriched.append(replace(hit, page=page, cells=cells, label_path=tuple(labels)))
    return tuple(enriched)


def _label_tokens(hit: SearchHit) -> set[str]:
    """hit 结构标签的 token 集合（结构重叠信号的比对侧）。"""
    tokens: set[str] = set()
    for label in hit.label_path:
        tokens.update(label.split())
    return tokens


def rank_hits(
    hits: tuple[SearchHit, ...],
    *,
    lexemes: tuple[str, ...] = (),
    signals: tuple[str, ...] = ("lexical",),
) -> tuple[SearchHit, ...]:
    """按声明信号对候选排序（r39 纪律：检索/排序变更须预先声明）。

    - 默认 ``signals=("lexical",)``：按 score 降序原样返回，与现状逐字节一致；
    - 含 ``"structural"`` 时：排序键 = (结构重叠数, score) 降序。结构重叠数 =
      查询词元（``zhcfg`` 提取，经 :func:`query_lexemes` 预先计算）在 hit
      ``label_path`` token 中的**去重命中数**——词元重复不放大，标签缺失（非
      表格块）得 0。**主键为结构重叠**，即任一结构命中的表格块整体优先于纯词法
      高分块（用户确认的排序信号规则）。
    """
    if "structural" not in signals:
        return hits
    lexeme_set = set(lexemes)

    def key(hit: SearchHit) -> tuple[int, float]:
        overlap = len(lexeme_set & _label_tokens(hit))
        return (overlap, hit.score)

    return tuple(sorted(hits, key=key, reverse=True))


def query_lexemes(dsn: str, query: str, *, sandbox_db: str | None = None) -> tuple[str, ...]:
    """查询侧词元（``zhcfg``，R5 规范化后提取）：结构重叠信号的输入。

    与写侧 ``corpus_chunks.search_tsv`` 同配置（``to_tsvector('zhcfg', …)``），
    保证比对双方 token 口径一致。
    """
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, sandbox_db)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                (normalize_search_text(query),),
            )
            row = cur.fetchone()
    if row is None:
        raise StoreError("查询词元不可读")
    return tuple(str(term) for term in row[0])


def _rank_query_on(cur: psycopg.Cursor, query: str) -> str:
    """排序信号 websearch OR 串（c′）：同游标/同快照取 zhcfg 词元后剔除功能词与标点。

    与候选池查询串（全词元 ``query``）分离是 I-1 的落点：``WHERE`` 仍用全词元 tsq，
    只有 score 列改用本串（I-2）。``rank_lexemes`` 全剔时回退原词元（fail-closed：
    本串与 query 同词元集合，排序退化回 base 而非零候选/零分）。
    """
    cur.execute(
        "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
        (normalize_search_text(query),),
    )
    row = cur.fetchone()
    lexemes = tuple(str(t) for t in (row[0] if row and row[0] else ()))
    kept = rank_lexemes(lexemes)
    return " OR ".join('"' + t.replace('"', " ") + '"' for t in kept)


def _check_target(conn: psycopg.Connection, sandbox_db: str | None) -> None:
    """与 PgStore._check_target 同纪律：隔离库校验 + apodex 生产实例反证。

    M7 复核 S1：缺省目标**调用时**动态解析（显式 ``CORPUS_TARGET_DB`` 优先），
    不在 import 时缓存。
    """
    target = sandbox_db if sandbox_db is not None else resolve_target_db()
    with conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        row = cur.fetchone()
        if row is None or row[0] != target:
            raise StoreError(f"拒绝：current_database={row[0] if row else None!r} ≠ {target!r}")
        cur.execute("SELECT datname FROM pg_database WHERE datallowconn")
        dbs = {r[0] for r in cur.fetchall()}
    if "apodex" in dbs and not production_instance_authorized():
        raise StoreError("拒绝：目标实例含 apodex 库——判定为生产实例，禁止检索")


def build_search_params(
    query: str,
    *,
    domain: ResearchDomain | None = None,
    published_from: str | None = None,
    published_to: str | None = None,
    limit: int = 20,
    rank_query: str | None = None,
) -> dict[str, object]:
    """校验并归一化检索参数（**唯一**来源，供 search_chunks 与同快照组合读取复用）。

    R5：查询侧必须与写侧（chunk.normalize_search_text）同一规范化——写侧把
    ``%``/``％`` 归一化为空格，查询侧若原样传 "23.5%" 给 websearch_to_tsquery
    会得到独立 token "23.5%"，与索引 token "23.5" 不一致而漏召回。``%``/``％``
    不是 websearch 操作符（OR/引号/负号），替换为空格不破坏这些语法。
    ``rank_query`` 显式指定排序信号查询串（c′，同样规范化）；缺省时由
    :func:`search_chunks_on` 按开关（``RANK_LEXEME_PRUNE``）在同游标内计算。
    """
    if not query.strip():
        raise StoreError("query 不能为空")
    if limit < 1:
        raise StoreError("limit 必须 >= 1")
    date_from = published_from.strip() or None if published_from else None
    date_to = published_to.strip() or None if published_to else None
    params: dict[str, object] = {
        "query": normalize_search_text(query),
        "domain": domain.value if domain is not None else None,
        "date_from": date_from,
        "date_to": date_to,
        "limit": limit,
    }
    if rank_query is not None:
        params["rank_query"] = normalize_search_text(rank_query)
    return params


def search_chunks(
    dsn: str,
    query: str,
    *,
    sandbox_db: str | None = None,
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

    ``params`` 由 :func:`search_chunks` 归一化后传入（query/domain/date_from/date_to/limit，
    ``rank_query`` 可选）；语义与 :func:`search_chunks` 完全一致，只是连接与事务由
    调用方持有——这是「检索结果与覆盖元数据读同一数据库快照」（§7.3）的实现落点。
    ``rank_query`` 缺省时在**同一游标/快照**内按开关注入（c′）：
    ``RANK_LEXEME_PRUNE`` 开 ⇒ 实词排序串（:func:`_rank_query_on`），关 ⇒ 退化为
    ``query`` 本身（行为与 base 逐字段一致）。返回前在同一游标内批量加深结构字段
    （票 02 I-D1）。
    """
    if "rank_query" not in params:
        params["rank_query"] = (
            _rank_query_on(cur, str(params["query"])) if RANK_LEXEME_PRUNE else params["query"]
        )
    cur.execute(_SEARCH_SQL, params)
    rows = cur.fetchall()
    hits = tuple(
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
    return _enrich_hits(cur, hits)
